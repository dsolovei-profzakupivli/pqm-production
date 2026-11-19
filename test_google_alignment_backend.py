import unittest
import io
import json
from unittest.mock import patch
from types import SimpleNamespace
import edr_sync_v2 as sync
from validation.local_release_20260911.test_edr_sync_v2 import database, row, snapshot


class GoogleAlignmentBackend(unittest.TestCase):
    def setUp(self):
        self.con = database()
        self.addCleanup(self.con.close)
        self.con.execute("INSERT INTO supplier_edr_profiles(supplier_code,full_name,short_name,manager_name,edr_status,edr_checked_at,edr_officer,synced_at) VALUES ('12345678','Verified name','Short','Manager','Зареєстровано','2026-10-12T17:03:00+03:00','Original UO','Prozorro technical time')")

    def apply(self, source):
        return sync.apply(self.con, source, source['source_fingerprint'], confirmed=True,
                          actor='manual-test', synced_at='2026-10-13T10:00:00+03:00')

    def test_equal_older_blank_and_invalid_do_not_update_any_business_fields(self):
        before = dict(self.con.execute('SELECT * FROM supplier_edr_profiles').fetchone())
        before.pop('last_google_received_at')
        for stamp in ['2026-10-12T14:03:00Z','12.10.2026 17:02:59','']:
            source = snapshot(row(checked=stamp, officer='Other UO', manager='Other manager', status='Припинено'))
            preview = sync.build_preview(self.con, source)
            self.assertTrue(preview['conflicts'])
            with self.assertRaises(ValueError):
                self.apply(source)
            actual=dict(self.con.execute('SELECT * FROM supplier_edr_profiles').fetchone());actual.pop('last_google_received_at')
            self.assertEqual(actual,before)
        with self.assertRaises(ValueError):
            self.apply(snapshot(row(checked='invalid')))
        actual=dict(self.con.execute('SELECT * FROM supplier_edr_profiles').fetchone());actual.pop('last_google_received_at')
        self.assertEqual(actual,before)

    def test_noop_receipt_advances_without_verification_events_and_missing_row_does_not(self):
        source=snapshot(row(checked='2026-10-12T17:03:00+03:00',manager='Manager'))
        self.assertEqual(self.apply(source)['verification_events'],0)
        first=self.con.execute('SELECT received_at FROM supplier_google_receipts').fetchone()[0]
        result=sync.apply(self.con,source,source['source_fingerprint'],confirmed=True,actor='manual-test',synced_at='2026-10-13T10:01:00+03:00')
        self.assertEqual(result['updated_profiles'],0);self.assertEqual(result['verification_events'],0)
        self.assertEqual(self.con.execute('SELECT received_at FROM supplier_google_receipts').fetchone()[0],'2026-10-13T10:01:00+03:00')
        self.assertNotEqual(first,'2026-10-13T10:01:00+03:00')
        missing=snapshot()
        self.assertEqual(self.apply(missing)['received_suppliers'],0)
        self.assertEqual(self.con.execute('SELECT received_at FROM supplier_google_receipts').fetchone()[0],'2026-10-13T10:01:00+03:00')

    def test_one_second_newer_updates_all_owned_fields_and_receipt_only_after_apply(self):
        source = snapshot(row(checked='12.10.2026 17:03:01', manager='Manager', officer='Checked UO'))
        before = self.con.total_changes
        plan = sync.build_preview(self.con, source)
        self.assertTrue(plan['items'][0]['datetime_gate']['accepted'])
        self.assertEqual(self.con.total_changes,before)
        self.assertEqual(self.con.execute('SELECT last_google_received_at FROM supplier_edr_profiles').fetchone()[0], '')
        self.apply(source)
        profile = self.con.execute('SELECT full_name,short_name,edr_checked_at,edr_officer,last_google_received_at FROM supplier_edr_profiles').fetchone()
        self.assertEqual(tuple(profile), ('ПОВНА НАЗВА','СКОРОЧЕНА НАЗВА','2026-10-12T17:03:01+03:00','Checked UO','2026-10-13T10:00:00+03:00'))
        self.assertEqual(self.apply(source)['verification_events'],0)

    def test_blank_names_preserve_prior_verified_names(self):
        values = row(checked='12.10.2026 17:03:01',manager='Manager');values[13]=values[14]=''
        self.apply(snapshot(values))
        self.assertEqual(tuple(self.con.execute('SELECT full_name,short_name FROM supplier_edr_profiles').fetchone()), ('Verified name','Short'))

    def test_pending_name_and_internal_uo_decision_are_not_population_evidence(self):
        self.con.execute("INSERT INTO submissions VALUES ('old','00001234','Decided name','2025-10-13')")
        self.con.execute("INSERT INTO qualifications VALUES ('q-old','unsuccessful','old')")
        self.con.execute("INSERT INTO submissions VALUES ('new','00001234','Pending name','2026-10-12')")
        self.con.execute("INSERT INTO qualifications VALUES ('q-new','pending','new')")
        self.con.execute("INSERT INTO application_fields VALUES ('new','admit','2026-10-12','Internal UO','')")
        self.assertEqual(sync._latest_application_names(self.con)['00001234'],'Decided name')
        self.assertIn('00001234',sync._eligible_codes(self.con))
        self.con.execute("DELETE FROM qualifications WHERE id='q-old'")
        self.assertNotIn('00001234',sync._eligible_codes(self.con))

    def test_rejected_application_does_not_replace_verification(self):
        before = sync.current_verification_projections(self.con, ['12345678'])['12345678']
        self.con.execute("INSERT INTO submissions VALUES ('rejected','12345678','New application','2026-10-13')")
        self.con.execute("INSERT INTO qualifications VALUES ('q-rejected','unsuccessful','rejected')")
        self.con.execute("INSERT INTO application_fields VALUES ('rejected','reject','2026-10-13','Reject UO','')")
        after = sync.current_verification_projections(self.con, ['12345678'])['12345678']
        self.assertEqual(after['verification_date'],before['verification_date'])
        self.assertEqual(after['verification_officer'],before['verification_officer'])

    def test_technical_synced_at_is_not_google_receipt_and_migration_is_idempotent(self):
        before = tuple(self.con.execute('SELECT * FROM supplier_edr_profiles').fetchone())
        sync.migrate(self.con);sync.migrate(self.con)
        self.assertEqual(tuple(self.con.execute('SELECT * FROM supplier_edr_profiles').fetchone()),before)
        self.assertEqual(self.con.execute('SELECT last_google_received_at FROM supplier_edr_profiles').fetchone()[0],'')

    def test_numeric_sheet_datetime_survives_snapshot_and_fingerprint_is_type_aware(self):
        values = row(checked=46307 + (17 * 3600 + 3 * 60 + 19) / 86400,manager='Manager')
        raw = snapshot(values)
        self.assertIsInstance(raw['rows'][0]['Дата перевірки'],float)
        values[8] = str(values[8])
        self.assertNotEqual(raw['source_fingerprint'],snapshot(values)['source_fingerprint'])
        self.assertTrue(sync.source_item(raw['rows'][0])['edr_checked_at'].endswith('17:03:19+03:00'))

    def test_grid_reader_preserves_literal_code_and_hidden_verification_seconds(self):
        import server
        header = {'values':[{'formattedValue':h} for h in sync.HEADERS]}
        cells = [{'formattedValue':''} for _ in range(15)]
        cells[1] = {'formattedValue':'00001234', 'effectiveValue':{'numberValue':1234}}
        cells[8] = {'formattedValue':'12.10.2026 17:03:19', 'effectiveValue':{'numberValue':46307.71063657408}}
        payload = {'properties':{'timeZone':'Europe/Kyiv'},
                   'sheets':[{'properties':{'title':'ЮО'}, 'data':[{'rowData':[header,{'values':cells}]}]}]}
        with patch.object(server,'SANDBOX_MODE',False), patch.object(server,'google_edr_effective_enabled',return_value=True), \
             patch.object(server,'_google_access_token',return_value='TEST_ONLY'), \
             patch.object(server.urllib.request,'urlopen',return_value=io.BytesIO(json.dumps(payload).encode())) as opener:
            values = server._google_edr_sheet_values('ЮО')
        self.assertEqual(values[1][1],'00001234')
        self.assertEqual(values[1][8],'12.10.2026 17:03:19')
        self.assertEqual(opener.call_count,1)

    def test_grid_reader_rejects_wrong_sandbox_destination_before_network(self):
        import server
        runtime = SimpleNamespace(SANDBOX_EDR_SPREADSHEET_ID='EXPECTED_SANDBOX')
        with patch.object(server,'SANDBOX_MODE',True), patch.object(server,'SUPPLIER_EDR_SHEET_ID','PROD_OTHER'), \
             patch.object(server,'sandbox_runtime',runtime,create=True), \
             patch.object(server.urllib.request,'urlopen') as opener:
            with self.assertRaises(PermissionError): server._google_edr_sheet_values('ЮО')
            opener.assert_not_called()


if __name__ == '__main__':
    unittest.main()
