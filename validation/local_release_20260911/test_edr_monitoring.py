import unittest
import csv
import io
import os
import json
from pathlib import Path
from unittest.mock import patch

import server
import edr_sync_v2


class EdrMonitoringTests(unittest.TestCase):
    def test_active_qualification_defaults_to_registered_without_newer_check(self):
        for old in ('', 'Неактуально', 'Немає інформації'):
            with self.subTest(old=old):
                self.assertEqual(edr_sync_v2.active_edr_status('2026-08-31', []), 'Зареєстровано')
        self.assertEqual(edr_sync_v2.active_edr_status('', []), 'Зареєстровано')

    def test_sandbox_active_blank_metadata_regression_cases(self):
        # These are synthetic reproductions of the reported SANDBOX rows, not live DB assertions.
        for supplier_code, active_qualifications, last_application in (
            ('3467208370', 23, ''),
            ('46244393', 4, '2026-09-22'),
        ):
            with self.subTest(supplier_code=supplier_code):
                self.assertGreater(active_qualifications, 0)
                self.assertEqual(edr_sync_v2.active_edr_status('', []), 'Зареєстровано')
                source = Path('server.py').read_text(encoding='utf-8')
                projection = source.split('def _edr_monitoring_rows()', 1)[1].split('def _edr_monitoring_dk_map()', 1)[0]
                self.assertIn('"verification_date": checked', projection)
                self.assertNotIn('verification_date": latest_application_date', projection)

    def test_later_authoritative_edr_overrides_admission(self):
        event = {'event_type': 'manual_edr', 'occurred_at': '2026-09-02',
            'officer': 'EDR Officer', 'snapshot_json': '{"edr_status":"Припинено"}'}
        self.assertEqual(edr_sync_v2.active_edr_status('2026-08-31', [event]), 'Припинено')
        self.assertEqual(edr_sync_v2.active_edr_status('2026-09-03', [event]), 'Зареєстровано')

    def test_legacy_factual_evidence_requires_configured_spreadsheet_and_provenance(self):
        digest = 'a' * 64
        for configured in ('sandbox-registry', 'prod-registry'):
            with self.subTest(configured=configured):
                snapshot = {
                    'source': 'legacy_google_registry', 'verification_date': '2026-09-02',
                    'verification_officer': 'Actual Officer', 'source_tab': 'ФОП',
                    'source_row': 12, 'source_digest': digest,
                    'factual_edr_status': 'Припинено',
                    'factual_spreadsheet_id': configured,
                    'factual_source_tab': 'ФОП', 'factual_source_row': 12,
                    'factual_source_digest': digest, 'factual_provenance_version': 1,
                }
                event = {'id': 1, 'event_type': 'legacy_google_registry',
                         'source': 'legacy_google_registry', 'occurred_at': '2026-09-02',
                         'officer': 'Actual Officer', 'source_sheet': 'ФОП',
                         'source_row': 12, 'snapshot_json': json.dumps(snapshot)}
                def projected():
                    return edr_sync_v2.active_edr_status('2026-09-01', [event])
                with patch.dict(os.environ, {'PQM_GOOGLE_REGISTRY_SPREADSHEET_ID': configured}):
                    for status in edr_sync_v2.LEGACY_GOOGLE_FACTUAL_STATUSES:
                        snapshot['factual_edr_status'] = status
                        event['snapshot_json'] = json.dumps(snapshot)
                        self.assertEqual(projected(), status)
                    snapshot['factual_edr_status'] = 'Зареєстровано'
                    event['snapshot_json'] = json.dumps(snapshot)
                    self.assertEqual(projected(), 'Зареєстровано')
                    snapshot['factual_edr_status'] = 'Неактуально'
                    event['snapshot_json'] = json.dumps(snapshot)
                    self.assertEqual(projected(), 'Зареєстровано')
                    snapshot['factual_edr_status'] = 'Припинено'
                    snapshot['factual_source_digest'] = ''
                    event['snapshot_json'] = json.dumps(snapshot)
                    self.assertEqual(projected(), 'Зареєстровано')
                    snapshot['factual_source_digest'] = digest
                    event['snapshot_json'] = json.dumps(snapshot)
                    event['event_type'] = 'manual_edr'
                    self.assertEqual(projected(), 'Зареєстровано')
                    event['event_type'] = 'legacy_google_registry'
                    snapshot.pop('factual_edr_status')
                    event['snapshot_json'] = json.dumps(snapshot)
                    self.assertEqual(projected(), 'Зареєстровано')
                    snapshot['factual_edr_status'] = 'Припинено'
                    event['snapshot_json'] = json.dumps(snapshot)
                with patch.dict(os.environ, {'PQM_GOOGLE_REGISTRY_SPREADSHEET_ID': 'wrong-registry'}):
                    self.assertEqual(projected(), 'Зареєстровано')
                with patch.dict(os.environ, {'PQM_GOOGLE_REGISTRY_SPREADSHEET_ID': ''}):
                    self.assertEqual(projected(), 'Зареєстровано')

    def test_current_operational_edr_status_preserves_historical_evidence(self):
        later = {'event_type': 'manual_edr', 'occurred_at': '2026-09-03',
                 'snapshot_json': '{"edr_status":"Припинено"}'}
        self.assertEqual(edr_sync_v2.operational_edr_status(
            'Активний','2026-09-02',[],'Припинено'),'Зареєстровано')
        self.assertEqual(edr_sync_v2.operational_edr_status(
            'Активний','2026-09-02',[later],'Зареєстровано'),'Припинено')
        for status in ('Неактивний','Ще не в реєстрі'):
            with self.subTest(status=status):
                self.assertEqual(edr_sync_v2.operational_edr_status(
                    status,'2026-09-02',[later],'Припинено'),'Неактуально')
                self.assertEqual(edr_sync_v2.freshness_state(status,'')['marker'],'🟣 Неактуально')

    def test_google_note_search_sort_and_filtered_export_population(self):
        rows = [dict(self.rows()[0], google_note='Zulu unique note'),
                dict(self.rows()[1], google_note='Alpha unique note')]
        with patch.object(server, '_edr_monitoring_rows', return_value=rows):
            matched = server.list_edr_monitoring({'search': ['ZULU UNIQUE'], 'page': ['1']})
            codes = server.edr_monitoring_filtered_codes({'search': ['ZULU UNIQUE']})
            ascending = server.list_edr_monitoring({'sort': ['google_note'], 'direction': ['asc']})
            descending = server.list_edr_monitoring({'sort': ['google_note'], 'direction': ['desc']})
        self.assertEqual(matched['total'], 1)
        self.assertEqual(matched['kpis'], {'gt90': 1})
        self.assertEqual(codes, ['001'])
        self.assertEqual([r['supplier_code'] for r in ascending['items']], ['002', '001'])
        self.assertEqual([r['supplier_code'] for r in descending['items']], ['001', '002'])
        where, args = server._edr_monitoring_filters({'search': ['UNIQUE']})
        self.assertIn("COALESCE(google_note,'')", where)
        self.assertEqual(args, ['unique'] * 4)

    def test_google_notes_are_separate_read_only_snapshot_projection(self):
        source = Path('server.py').read_text(encoding='utf-8')
        projection = source.split('def _edr_monitoring_rows()', 1)[1].split('def _edr_monitoring_dk_map()', 1)[0]
        self.assertIn('"google_note": str(profile.get("edr_notes") or "").strip()', projection)
        self.assertNotIn('FROM supplier_notes', projection)
        import edr_sync_v2
        self.assertEqual(edr_sync_v2.source_item({'Примітки': ' source note '})['edr_notes'], 'source note')
        app = Path('app.js').read_text(encoding='utf-8')
        html = Path('index.html').read_text(encoding='utf-8')
        renderer = app.split('async function loadEdrMonitoring()', 1)[1].split('\n', 1)[0]
        self.assertIn('note=item.google_note?', renderer)
        self.assertIn('openGoogleNote(item)', renderer)
        self.assertIn('data-edr-column="google_note"', renderer)
        self.assertIn('data-edr-column="google_note" data-edr-sort="google_note">Примітка з Google', html)
        self.assertNotIn('openSupplierNote(', renderer)
        dialog = html.split('id="googleNoteDialog"', 1)[1].split('</dialog>', 1)[0]
        self.assertNotIn('textarea', dialog)
        self.assertNotIn('Зберегти', dialog)
        self.assertIn('Примітка з Google', app)

    def rows(self):
        return [
            {"supplier_code": "001", "supplier_name": "Active supplier", "manager_name": "Manager A",
             "edr_full_name": "Active supplier LLC", "edr_short_name": "AS LLC",
             "edr_status": "Зареєстровано", "prozorro_status": "Активний", "freshness": "gt90",
             "verification_date": "2026-01-01", "verification_officer": "УО 1",
             "last_admission_date": "2025-01-01", "latest_application_date": "2026-09-10", "termination_details": "",
             "termination_record_date": "", "termination_record_number": "",
             "verification_event_type": "google_clarity", "verification_source": "Google"},
            {"supplier_code": "002", "supplier_name": "Inactive supplier", "manager_name": "Manager B",
             "edr_full_name": "Inactive supplier LLC", "edr_short_name": "",
             "edr_status": "Припинено", "prozorro_status": "Неактивний", "freshness": "not_current",
             "verification_date": "2026-09-01", "verification_officer": "УО 2",
             "last_admission_date": "2026-09-12", "latest_application_date": "2025-01-01", "termination_details": "record",
             "termination_record_date": "2026-08-01", "termination_record_number": "7",
             "verification_event_type": "google_clarity", "verification_source": "Google"},
        ]

    def test_lightweight_projection_filters_and_kpi_without_dossier_counts(self):
        with patch.object(server, "_edr_monitoring_rows", return_value=self.rows()):
            result = server.list_edr_monitoring({"freshness": ["gt90"], "page": ["1"], "size": ["100"]})
        self.assertEqual([row["supplier_code"] for row in result["items"]], ["001"])
        self.assertEqual(result["kpis"], {"gt90": 1, "not_current": 1})
        self.assertNotIn("applications_count", result["items"][0])
        self.assertNotIn("qualifications_count", result["items"][0])

    def test_kpi_facets_follow_context_but_ignore_selected_freshness(self):
        with patch.object(server, "_edr_monitoring_rows", return_value=self.rows()):
            result = server.list_edr_monitoring({"edr_status": ["Припинено"], "freshness": ["gt90"], "page": ["1"]})
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["kpis"], {"not_current": 1})

    def test_status_multiselect_is_or_within_dimension_and_and_across_dimensions(self):
        with patch.object(server, "_edr_monitoring_rows", return_value=self.rows()):
            both = server.list_edr_monitoring({"edr_status": ["Зареєстровано,Припинено"], "page": ["1"]})
            narrowed = server.list_edr_monitoring({"edr_status": ["Зареєстровано,Припинено"],
                                                   "prozorro_status": ["Активний"], "page": ["1"]})
        self.assertEqual(both["total"], 2)
        self.assertEqual(both["kpis"], {"gt90": 1, "not_current": 1})
        self.assertEqual([row["supplier_code"] for row in narrowed["items"]], ["001"])

    def test_sql_filter_builder_accepts_repeated_and_comma_separated_statuses(self):
        where, args = server._edr_monitoring_filters({"edr_status": ["Припинено", "В стані припинення"],
                                                       "prozorro_status": ["Активний,Призупинений"]})
        self.assertIn("edr_status IN (?,?)", where)
        self.assertIn("prozorro_status IN (?,?)", where)
        self.assertEqual(args, ["Активний", "Призупинений", "Припинено", "В стані припинення"])

    def test_latest_application_range_and_selected_codes_are_server_side(self):
        with patch.object(server, "_edr_monitoring_rows", return_value=self.rows()):
            result = server.list_edr_monitoring({"application_from": ["2026-09-01"], "page": ["1"]})
            codes = server.edr_monitoring_filtered_codes({"prozorro_status": ["Неактивний"]})
        self.assertEqual(result["total"], 1)
        self.assertEqual(codes, ["002"])

    def test_sorting_is_server_side_and_name_completeness_uses_edr_fields(self):
        with patch.object(server, "_edr_monitoring_rows", return_value=self.rows()):
            descending = server.list_edr_monitoring({"sort": ["supplier_code"], "direction": ["desc"], "page": ["1"]})
            incomplete = server.list_edr_monitoring({"edr_names": ["missing_any"], "page": ["1"]})
        self.assertEqual([row["supplier_code"] for row in descending["items"]], ["002", "001"])
        self.assertEqual([row["supplier_code"] for row in incomplete["items"]], ["002"])

    def test_freshness_business_sort_order(self):
        expected = ["not_checked", "gt90", "gt60", "gt30", "lt30", "not_current"]
        rows = []
        for index, bucket in enumerate(reversed(expected)):
            row = dict(self.rows()[0], supplier_code=str(index), freshness=bucket)
            rows.append(row)
        with patch.object(server, "_edr_monitoring_rows", return_value=rows):
            result = server.list_edr_monitoring({"sort": ["freshness"], "direction": ["asc"], "page": ["1"]})
        self.assertEqual([row["freshness"] for row in result["items"]], expected)

    def test_ui_has_separate_operational_register_and_single_export(self):
        html = Path("index.html").read_text(encoding="utf-8")
        app = Path("app.js").read_text(encoding="utf-8")
        styles = Path("styles.css").read_text(encoding="utf-8")
        self.assertIn('id="edrMonitoringView"', html)
        self.assertIn('id="edrMonitoringView" class="module-view data-module-shell"', html)
        self.assertIn('edr-monitoring-table-card data-module-table', html)
        self.assertIn('id="edrMonitoringExport"', html)
        self.assertIn('Дата останньої заявки', html)
        self.assertIn('id="edrMonitoringApplicationFrom"', html)
        self.assertNotIn('id="edrMonitoringAdmissionFrom"', html)
        self.assertIn("edrMonitoringSelected=new Set()", app)
        self.assertIn("view:'edr_monitoring'", app)
        self.assertIn('data-edr-sort="supplier_name"', html)
        self.assertIn('id="edrMonitoringNames"', html)
        self.assertIn('id="edrMonitoringChips"', html)
        self.assertIn("syncSharedFilterPresentation($('#edrMonitoringView'))", app)
        self.assertIn("#queueFilterChips button,.edr-monitoring-chips button", styles)
        self.assertIn(".data-module-table>:is(.supplier-table-scroll,.table-scroll)", styles)

    def test_monitoring_export_uses_exact_filtered_population_and_existing_contract(self):
        with patch.object(server, "_edr_monitoring_rows", return_value=self.rows()):
            raw = server.edr_monitoring_export_csv(["001"])
        rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
        self.assertEqual(rows[0], server.EDR_EXPORT_HEADERS)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][0], "001")


if __name__ == "__main__":
    unittest.main()
