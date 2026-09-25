import sqlite3
import unittest
from datetime import date, timedelta

import edr_sync_v2 as sync


def database():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.create_function("DIGITS", 1, sync.normalize_code, deterministic=True)
    con.executescript("""
      CREATE TABLE submissions(id TEXT PRIMARY KEY,supplier_code TEXT,supplier_name TEXT,date_published TEXT);
      CREATE TABLE application_fields(submission_id TEXT PRIMARY KEY,protocol_decision TEXT,
        protocol_date TEXT,protocol_officer TEXT,review_officer TEXT);
      CREATE TABLE supplier_edr_profiles(supplier_code TEXT PRIMARY KEY,full_name TEXT DEFAULT '',
        short_name TEXT DEFAULT '',manager_name TEXT DEFAULT '',edr_status TEXT DEFAULT '',
        edr_checked_at TEXT DEFAULT '',termination_decision_details TEXT DEFAULT '',
        edr_officer TEXT DEFAULT '',edr_notes TEXT DEFAULT '',source_sheet TEXT DEFAULT '',
        source_row INTEGER DEFAULT 0,synced_at TEXT NOT NULL);
      CREATE TABLE supplier_managers(id INTEGER PRIMARY KEY,supplier_code TEXT,manager_name TEXT,
        normalized_name TEXT DEFAULT '',valid_from TEXT,valid_to TEXT,is_current INTEGER,
        source TEXT DEFAULT '',updated_at TEXT,created_at TEXT);
      CREATE TABLE supplier_edr_sync_log(id INTEGER PRIMARY KEY,started_at TEXT,status TEXT,
        finished_at TEXT,processed INTEGER DEFAULT 0,inserted INTEGER DEFAULT 0,updated INTEGER DEFAULT 0,error TEXT DEFAULT '');
      CREATE TABLE registry_contracts(supplier_code TEXT,status TEXT,framework_id TEXT);
      CREATE TABLE frameworks(id TEXT PRIMARY KEY,status TEXT,raw_json TEXT DEFAULT '{}');
      CREATE TABLE qualifications(id TEXT,status TEXT,submission_id TEXT);
    """)
    sync.migrate(con)
    return con


def row(code="12345678", status="Зареєстровано", checked="15.09.2026", officer="УО",
        manager="НОВИЙ КЕРІВНИК"):
    values = ["", code, "Заявка", manager, status, "Активний", "", "", checked,
              "", "", officer, "", "ПОВНА НАЗВА", "СКОРОЧЕНА НАЗВА"]
    return values


def snapshot(*rows):
    values = [list(sync.HEADERS), *rows]
    return sync.source_snapshot({"ФОП": values, "ЮО": [list(sync.HEADERS)]})


class EdrSyncV2Tests(unittest.TestCase):
    def apply_observation(self, con, source):
        return sync.apply(con, source, source['source_fingerprint'], confirmed=True,
                          actor='test', synced_at='2026-09-16T12:00:00')

    def test_verification_row_move_preserves_event_identity_and_provenance(self):
        con = database()
        con.execute("INSERT INTO supplier_edr_profiles(supplier_code,synced_at) VALUES('12345678','old')")
        source = snapshot(row())
        source['rows'][0]['source_row'] = 100
        self.assertEqual(self.apply_observation(con, source)['verification_events'], 1)
        source['rows'][0]['source_row'] = 500
        preview = sync.build_preview(con, source)
        self.assertEqual(preview['summary']['verification_event_changes'], 0)
        self.assertEqual(self.apply_observation(con, source)['verification_events'], 0)
        events = con.execute('SELECT source_row,snapshot_json FROM supplier_edr_verification_events').fetchall()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['source_row'], 100)
        self.assertIn('"source_row": 100', events[0]['snapshot_json'])
        self.assertEqual(con.execute('SELECT source_row FROM supplier_edr_profiles').fetchone()[0], 500)

    def test_same_row_new_verification_or_business_snapshot_creates_event(self):
        con = database()
        con.execute("INSERT INTO supplier_edr_profiles(supplier_code,synced_at) VALUES('12345678','old')")
        self.apply_observation(con, snapshot(row()))
        new_date = snapshot(row(checked='16.09.2026'))
        self.assertEqual(self.apply_observation(con, new_date)['verification_events'], 1)
        new_business = snapshot(row(checked='16.09.2026', status='Припинено'))
        self.assertEqual(self.apply_observation(con, new_business)['verification_events'], 1)
        self.assertEqual(con.execute('SELECT COUNT(*) FROM supplier_edr_verification_events').fetchone()[0], 3)

    def test_empty_ledger_bootstraps_once_and_duplicate_import_is_idempotent(self):
        con = database()
        for code in ('12345678', '87654321'):
            con.execute('INSERT INTO supplier_edr_profiles(supplier_code,synced_at) VALUES(?,?)', (code, 'old'))
        source = snapshot(row(), row(code='87654321'))
        self.assertEqual(sync.build_preview(con, source)['summary']['verification_event_changes'], 2)
        self.assertEqual(self.apply_observation(con, source)['verification_events'], 2)
        self.assertEqual(self.apply_observation(con, source)['verification_events'], 0)
        self.assertEqual(sync.build_preview(con, source)['summary']['verification_event_changes'], 0)
        self.assertEqual(con.execute('SELECT COUNT(*) FROM supplier_edr_verification_events').fetchone()[0], 2)

    def test_blank_source_profile_preservation_does_not_change_event_hash(self):
        con = database()
        con.execute("INSERT INTO supplier_edr_profiles(supplier_code,full_name,synced_at) VALUES('12345678','KNOWN FULL NAME','old')")
        values = row()
        values[13] = ''
        source = snapshot(values)
        self.assertEqual(self.apply_observation(con, source)['verification_events'], 1)
        self.assertEqual(self.apply_observation(con, source)['verification_events'], 0)
        self.assertEqual(con.execute('SELECT full_name FROM supplier_edr_profiles').fetchone()[0], 'KNOWN FULL NAME')
        incoming = sync.source_item(source['rows'][0])
        moved = {**incoming, 'source_row': 500, 'source_sheet': 'ЮО'}
        self.assertEqual(sync.row_snapshot_hash(incoming), sync.row_snapshot_hash(moved))

    def test_active_registry_evidence_and_newer_profile_form_canonical_projection(self):
        con = database()
        con.execute("INSERT INTO frameworks(id,status,raw_json) VALUES('f1','active','{}')")
        con.execute("INSERT INTO registry_contracts VALUES('0013500191','active','f1')")
        con.execute("INSERT INTO submissions VALUES('s1','0013500191','Історична назва','2025-01-21')")
        con.execute("INSERT INTO application_fields(submission_id,protocol_decision,protocol_date,protocol_officer) VALUES('s1','admit','22.01.2025','ДМИТРО САВВА')")
        con.execute("""INSERT INTO supplier_edr_profiles
          (supplier_code,edr_status,edr_checked_at,edr_officer,source_sheet,source_row,synced_at)
          VALUES('0013500191','Зареєстровано','17.08.2026','Олена ЄРЬОМІНА','ФОП',2480,'2026-09-12')""")
        state = sync.canonical_supplier_edr_states(
            con, {'0013500191'}, today=date(2026, 9, 16))['0013500191']
        self.assertEqual(state['prozorro_status'], 'Активний')
        self.assertEqual(state['verification_date'], '2026-08-17')
        self.assertEqual(state['verification_officer'], 'Олена ЄРЬОМІНА')
        self.assertEqual(state['verification_event']['event_type'], 'google_clarity_profile')
        self.assertEqual(state['bucket'], 'gt30')

    def test_missing_current_manager_is_a_distinct_business_outcome(self):
        result = sync.classify_manager_identity("", "ЗАЙЧУК СЕРГІЙ ВАЛЕНТИНОВИЧ")
        self.assertEqual(result["kind"], "missing_current_manager")

    def test_missing_current_manager_with_conflicting_evidence_is_ambiguous(self):
        result = sync.classify_manager_identity("", "ЗАЙЧУК СЕРГІЙ ВАЛЕНТИНОВИЧ",
                                                ["ПЕТРЕНКО НАТАЛІЯ МИКОЛАЇВНА"])
        self.assertEqual(result["kind"], "ambiguous_missing_current_manager")

    def test_abbreviated_to_confirmed_full_name_is_representation_enrichment(self):
        result = sync.classify_manager_identity(
            "ТКАЧЕНКО Н.М.", "ТКАЧЕНКО НАТАЛІЯ МИКОЛАЇВНА")
        self.assertEqual(result["kind"], "representation_enrichment")

    def test_same_initials_are_not_merged_when_full_identity_conflicts(self):
        result = sync.classify_manager_identity(
            "ТКАЧЕНКО Н.М.", "ТКАЧЕНКО НАТАЛІЯ МИКОЛАЇВНА",
            ["ТКАЧЕНКО НІНА МИХАЙЛІВНА"])
        self.assertEqual(result["kind"], "real_identity_change")
        self.assertEqual(result["conflicting_evidence"], ["ТКАЧЕНКО НІНА МИХАЙЛІВНА"])

    def test_different_surname_and_different_full_name_are_real_changes(self):
        self.assertEqual(sync.classify_manager_identity(
            "ТКАЧЕНКО Н.М.", "ПЕТРЕНКО НАТАЛІЯ МИКОЛАЇВНА")["kind"], "real_identity_change")
        self.assertEqual(sync.classify_manager_identity(
            "ТКАЧЕНКО НАТАЛІЯ МИКОЛАЇВНА", "ТКАЧЕНКО НІНА МИХАЙЛІВНА")["kind"], "real_identity_change")

    def test_formatting_only_manager_difference_is_not_a_business_change(self):
        self.assertEqual(sync.classify_manager_identity(
            "  Ткаченко   Н. М. ", "ткаченко н.м.")["kind"], "same")

    def test_preview_splits_identity_changes_from_representation_enrichments(self):
        con = database()
        con.execute("""INSERT INTO supplier_edr_profiles
          (supplier_code,manager_name,synced_at) VALUES ('12345678','ТКАЧЕНКО Н.М.','old')""")
        con.execute("""INSERT INTO supplier_managers
          (supplier_code,manager_name,is_current,updated_at,created_at)
          VALUES ('12345678','ТКАЧЕНКО Н.М.',1,'old','old')""")
        preview = sync.build_preview(con, snapshot(row(
            manager="ТКАЧЕНКО НАТАЛІЯ МИКОЛАЇВНА")))
        self.assertEqual(preview["summary"]["manager_identity_changes"], 0)
        self.assertEqual(preview["summary"]["manager_representation_enrichments"], 1)
        self.assertEqual(preview["items"][0]["manager_change_kind"], "representation_enrichment")

    def test_preview_uses_supplier_scoped_full_name_as_conflicting_evidence(self):
        con = database()
        con.execute("""INSERT INTO supplier_edr_profiles
          (supplier_code,manager_name,synced_at) VALUES ('12345678','ТКАЧЕНКО Н.М.','old')""")
        con.execute("INSERT INTO submissions VALUES ('s1','12345678','OLD','2026-09-01')")
        con.execute("""ALTER TABLE application_fields ADD COLUMN manager_name TEXT DEFAULT ''""")
        con.execute("""INSERT INTO application_fields
          (submission_id,protocol_decision,manager_name) VALUES ('s1','admit','ТКАЧЕНКО НІНА МИХАЙЛІВНА')""")
        preview = sync.build_preview(con, snapshot(row(
            manager="ТКАЧЕНКО НАТАЛІЯ МИКОЛАЇВНА")))
        self.assertEqual(preview["summary"]["manager_identity_changes"], 1)
        self.assertEqual(preview["summary"]["manager_representation_enrichments"], 0)
        self.assertEqual(preview["items"][0]["manager_change_kind"], "real_identity_change")

    def test_enrichment_apply_does_not_call_change_or_nazk_refresh(self):
        con = database()
        con.execute("""INSERT INTO supplier_edr_profiles
          (supplier_code,manager_name,synced_at) VALUES ('12345678','ТКАЧЕНКО Н.М.','old')""")
        con.execute("""INSERT INTO supplier_managers
          (supplier_code,manager_name,is_current,updated_at,created_at)
          VALUES ('12345678','ТКАЧЕНКО Н.М.',1,'old','old')""")
        calls = {"change": 0, "enrich": 0, "nazk": 0}
        source = snapshot(row(manager="ТКАЧЕНКО НАТАЛІЯ МИКОЛАЇВНА"))
        result = sync.apply(con, source, source["source_fingerprint"], confirmed=True,
          actor="admin", synced_at="2026-09-15T18:00:00",
          sync_manager=lambda *args: calls.__setitem__("change", calls["change"] + 1) or {"changed": True},
          enrich_manager=lambda *args: calls.__setitem__("enrich", calls["enrich"] + 1) or {"enriched": True},
          refresh_manager_controls=lambda *args: calls.__setitem__("nazk", calls["nazk"] + 1))
        self.assertEqual(calls, {"change": 0, "enrich": 1, "nazk": 0})
        self.assertEqual(result["manager_identity_changes"], 0)
        self.assertEqual(result["manager_representation_enrichments"], 1)

    def test_missing_manager_apply_creates_one_current_row_without_nazk_refresh(self):
        import server
        con = database()
        con.execute("INSERT INTO supplier_edr_profiles(supplier_code,synced_at) VALUES ('12345678','old')")
        source = snapshot(row(manager="ЗАЙЧУК СЕРГІЙ ВАЛЕНТИНОВИЧ"))
        refreshes = []
        first = sync.apply(con, source, source["source_fingerprint"], confirmed=True,
          actor="admin", synced_at="2026-09-15T18:00:00",
          sync_manager=server.sync_current_supplier_manager,
          enrich_manager=server.enrich_current_supplier_manager,
          establish_manager=server.establish_current_supplier_manager,
          refresh_manager_controls=lambda *args: refreshes.append(args))
        rows = con.execute("SELECT * FROM supplier_managers").fetchall()
        self.assertEqual(first["manager_identity_changes"], 0)
        self.assertEqual(first["newly_established_managers"], 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["manager_name"], "ЗАЙЧУК СЕРГІЙ ВАЛЕНТИНОВИЧ")
        self.assertEqual(rows[0]["valid_from"], "2026-09-15")
        self.assertIsNone(rows[0]["valid_to"])
        self.assertEqual(refreshes, [])
        self.assertEqual(con.execute("""SELECT COUNT(*) FROM supplier_edr_verification_events
          WHERE event_type='google_clarity'""").fetchone()[0], 1)

        again = sync.apply(con, source, source["source_fingerprint"], confirmed=True,
          actor="admin", synced_at="2026-09-15T18:01:00",
          sync_manager=server.sync_current_supplier_manager,
          enrich_manager=server.enrich_current_supplier_manager,
          establish_manager=server.establish_current_supplier_manager,
          refresh_manager_controls=lambda *args: refreshes.append(args))
        self.assertEqual(again["newly_established_managers"], 0)
        self.assertEqual(again["verification_events"], 0)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM supplier_managers").fetchone()[0], 1)
        self.assertEqual(refreshes, [])

    def test_application_known_manager_is_reestablished_without_identity_change_or_nazk(self):
        import server
        con = database()
        con.execute("ALTER TABLE application_fields ADD COLUMN manager_name TEXT DEFAULT ''")
        con.execute("ALTER TABLE application_fields ADD COLUMN manager_name_source TEXT DEFAULT ''")
        con.execute("INSERT INTO submissions VALUES ('s1','12345678','OLD','2026-08-30')")
        con.execute("""INSERT INTO application_fields
          (submission_id,protocol_decision,manager_name,manager_name_source)
          VALUES ('s1','admit','ЗАЙЧУК СЕРГІЙ ВАЛЕНТИНОВИЧ','manual')""")
        con.execute("INSERT INTO supplier_edr_profiles(supplier_code,synced_at) VALUES ('12345678','old')")
        source = snapshot(row(manager="ЗАЙЧУК СЕРГІЙ ВАЛЕНТИНОВИЧ"))
        preview = sync.build_preview(con, source)
        plan = preview["items"][0]
        self.assertEqual(plan["manager_change_kind"], "manager_reestablished")
        self.assertEqual(plan["manager_change_reason"], "same_known_identity_in_application")
        self.assertEqual(plan["manager_resolution_source"], "application")
        self.assertEqual(preview["summary"]["manager_identity_changes"], 0)
        refreshes = []
        result = sync.apply(con, source, source["source_fingerprint"], confirmed=True,
          actor="admin", synced_at="2026-09-15T18:00:00",
          sync_manager=server.sync_current_supplier_manager,
          enrich_manager=server.enrich_current_supplier_manager,
          establish_manager=server.establish_current_supplier_manager,
          reestablish_manager=server.reestablish_current_supplier_manager,
          refresh_manager_controls=lambda *args: refreshes.append(args))
        self.assertEqual(result["manager_reestablishments"], 1)
        self.assertEqual(result["newly_established_managers"], 0)
        self.assertEqual(result["manager_identity_changes"], 0)
        self.assertEqual(refreshes, [])
        current = con.execute("SELECT * FROM supplier_managers WHERE is_current=1").fetchall()
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]["manager_name"], "ЗАЙЧУК СЕРГІЙ ВАЛЕНТИНОВИЧ")

    def test_closed_same_manager_history_is_reestablished_without_rewriting_history(self):
        import server
        con = database()
        con.execute("INSERT INTO supplier_edr_profiles(supplier_code,synced_at) VALUES ('12345678','old')")
        con.execute("""INSERT INTO supplier_managers
          (id,supplier_code,manager_name,normalized_name,valid_from,valid_to,is_current,source,updated_at,created_at)
          VALUES (17,'12345678','ЗАЙЧУК СЕРГІЙ ВАЛЕНТИНОВИЧ','зайчук сергій валентинович',
          '2026-08-30','2026-08-31',0,'PQM application','2026-08-31','2026-08-30')""")
        source = snapshot(row(manager="ЗАЙЧУК СЕРГІЙ ВАЛЕНТИНОВИЧ"))
        preview = sync.build_preview(con, source)
        self.assertEqual(preview["items"][0]["manager_change_kind"], "manager_reestablished")
        self.assertEqual(preview["items"][0]["manager_change_reason"], "same_identity_in_closed_history")
        refreshes = []
        result = sync.apply(con, source, source["source_fingerprint"], confirmed=True,
          actor="admin", synced_at="2026-09-15T18:00:00",
          sync_manager=server.sync_current_supplier_manager,
          enrich_manager=server.enrich_current_supplier_manager,
          establish_manager=server.establish_current_supplier_manager,
          reestablish_manager=server.reestablish_current_supplier_manager,
          refresh_manager_controls=lambda *args: refreshes.append(args))
        self.assertEqual(result["manager_reestablishments"], 1)
        history = con.execute("SELECT * FROM supplier_managers WHERE id=17").fetchone()
        self.assertEqual(history["valid_from"], "2026-08-30")
        self.assertEqual(history["valid_to"], "2026-08-31")
        self.assertEqual(history["is_current"], 0)
        current = con.execute("SELECT * FROM supplier_managers WHERE is_current=1").fetchall()
        self.assertEqual(len(current), 1)
        self.assertNotEqual(current[0]["id"], 17)
        self.assertEqual(refreshes, [])
        again = sync.apply(con, source, source["source_fingerprint"], confirmed=True,
          actor="admin", synced_at="2026-09-15T18:01:00",
          sync_manager=server.sync_current_supplier_manager,
          enrich_manager=server.enrich_current_supplier_manager,
          establish_manager=server.establish_current_supplier_manager,
          reestablish_manager=server.reestablish_current_supplier_manager,
          refresh_manager_controls=lambda *args: refreshes.append(args))
        self.assertEqual(again["manager_reestablishments"], 0)
        self.assertEqual(again["verification_events"], 0)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM supplier_managers").fetchone()[0], 2)
        self.assertEqual(refreshes, [])

    def test_application_fallback_resolver_does_not_materialize_rows(self):
        con = database()
        con.execute("ALTER TABLE application_fields ADD COLUMN manager_name TEXT DEFAULT ''")
        con.execute("INSERT INTO submissions VALUES ('s1','12345678','OLD','2026-08-30')")
        con.execute("""INSERT INTO application_fields
          (submission_id,protocol_decision,manager_name)
          VALUES ('s1','admit','ЗАЙЧУК СЕРГІЙ ВАЛЕНТИНОВИЧ')""")
        before = con.total_changes
        resolved = sync.resolve_known_manager(con, "12345678")
        self.assertEqual(resolved["manager_name"], "ЗАЙЧУК СЕРГІЙ ВАЛЕНТИНОВИЧ")
        self.assertEqual(resolved["resolution_source"], "application")
        self.assertEqual(con.total_changes, before)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM supplier_managers").fetchone()[0], 0)

    def test_google_blank_preserves_current_manager_row(self):
        import server
        con = database()
        con.execute("""INSERT INTO supplier_managers
          (supplier_code,manager_name,normalized_name,valid_from,valid_to,is_current,source,updated_at,created_at)
          VALUES ('12345678','ЗАЙЧУК СЕРГІЙ ВАЛЕНТИНОВИЧ','зайчук сергій валентинович',
          '2026-08-30',NULL,1,'PQM application','2026-08-30','2026-08-30')""")
        result = server.sync_current_supplier_manager(
          con, "12345678", "", "Google Sheets: ЮО", "2026-08-31T19:49:52")
        current = con.execute("SELECT * FROM supplier_managers WHERE supplier_code='12345678'").fetchall()
        self.assertEqual(result["reason"], "no_edr_manager_observation")
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]["is_current"], 1)
        self.assertIsNone(current[0]["valid_to"])
        self.assertEqual(current[0]["updated_at"], "2026-08-30")

    def test_non_edr_explicit_blank_keeps_established_removal_semantics(self):
        import server
        con = database()
        con.execute("""INSERT INTO supplier_managers
          (supplier_code,manager_name,normalized_name,valid_from,valid_to,is_current,source,updated_at,created_at)
          VALUES ('12345678','ОСОБА А','особа а','2026-08-30',NULL,1,
          'PQM application','2026-08-30','2026-08-30')""")
        result = server.sync_current_supplier_manager(
          con, "12345678", "", "explicit business removal", "2026-09-15")
        row = con.execute("SELECT * FROM supplier_managers WHERE supplier_code='12345678'").fetchone()
        self.assertEqual(result["reason"], "manager_removed")
        self.assertEqual(row["is_current"], 0)
        self.assertEqual(row["valid_to"], "2026-09-15")

    def test_google_blank_preview_is_no_manager_observation(self):
        con = database()
        con.execute("""INSERT INTO supplier_managers
          (supplier_code,manager_name,normalized_name,valid_from,valid_to,is_current,source,updated_at,created_at)
          VALUES ('12345678','ЗАЙЧУК СЕРГІЙ ВАЛЕНТИНОВИЧ','зайчук сергій валентинович',
          '2026-08-30',NULL,1,'PQM application','2026-08-30','2026-08-30')""")
        preview = sync.build_preview(con, snapshot(row(manager="")))
        self.assertEqual(preview["items"][0]["manager_change_kind"], "same")
        self.assertNotIn("manager_name", preview["items"][0]["changed_fields"])
        self.assertEqual(preview["summary"]["manager_removals"], 0)

    def test_real_manager_change_closes_cycle_and_refreshes_nazk(self):
        import server
        con = database()
        con.execute("""INSERT INTO supplier_edr_profiles
          (supplier_code,manager_name,synced_at) VALUES ('12345678','ОСОБА А','old')""")
        con.execute("""INSERT INTO supplier_managers
          (supplier_code,manager_name,normalized_name,valid_from,valid_to,is_current,source,updated_at,created_at)
          VALUES ('12345678','ОСОБА А','особа а','2026-08-01',NULL,1,'ЄДР','2026-08-01','2026-08-01')""")
        source = snapshot(row(manager="ОСОБА Б"))
        refreshes = []
        result = sync.apply(con, source, source["source_fingerprint"], confirmed=True,
          actor="admin", synced_at="2026-09-15T18:00:00",
          sync_manager=server.sync_current_supplier_manager,
          enrich_manager=server.enrich_current_supplier_manager,
          establish_manager=server.establish_current_supplier_manager,
          refresh_manager_controls=lambda *args: refreshes.append(args))
        rows = con.execute("SELECT * FROM supplier_managers ORDER BY id").fetchall()
        self.assertEqual(result["manager_identity_changes"], 1)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["valid_to"], "2026-09-15")
        self.assertEqual(rows[0]["is_current"], 0)
        self.assertEqual(rows[1]["manager_name"], "ОСОБА Б")
        self.assertEqual(rows[1]["is_current"], 1)
        self.assertEqual(len(refreshes), 1)

    def test_server_enrichment_preserves_current_cycle(self):
        import server
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.execute("""CREATE TABLE supplier_managers(id INTEGER PRIMARY KEY,supplier_code TEXT,
          manager_name TEXT,normalized_name TEXT,valid_from TEXT,valid_to TEXT,is_current INTEGER,
          source TEXT,created_at TEXT,updated_at TEXT)""")
        con.execute("""INSERT INTO supplier_managers VALUES
          (7,'12345678','ТКАЧЕНКО Н.М.','ткаченко н.м.','2026-08-01',NULL,1,
           'Google Sheets: ФОП','2026-08-01','2026-08-01')""")
        result = server.enrich_current_supplier_manager(con, '12345678',
          'ТКАЧЕНКО НАТАЛІЯ МИКОЛАЇВНА', 'Google Sheets: ФОП', '2026-09-15')
        rows = con.execute("SELECT * FROM supplier_managers").fetchall()
        self.assertTrue(result["enriched"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], 7)
        self.assertEqual(rows[0]["valid_from"], "2026-08-01")
        self.assertIsNone(rows[0]["valid_to"])
        self.assertEqual(rows[0]["manager_name"], 'ТКАЧЕНКО НАТАЛІЯ МИКОЛАЇВНА')

    def test_preview_is_read_only_and_legacy_profile_is_not_discarded(self):
        con = database()
        con.execute("INSERT INTO supplier_edr_profiles(supplier_code,synced_at) VALUES ('12345678','old')")
        before = con.total_changes
        result = sync.build_preview(con, snapshot(row()))
        self.assertEqual(con.total_changes, before)
        self.assertEqual(result["summary"]["legacy_ineligible"], 1)
        self.assertTrue(result["items"][0]["apply_allowed"])

    def test_new_population_requires_final_decision(self):
        con = database()
        denied = sync.build_preview(con, snapshot(row()))["items"][0]
        self.assertFalse(denied["apply_allowed"])
        con.execute("INSERT INTO submissions VALUES ('s1','12345678','OLD','2026-09-01')")
        con.execute("INSERT INTO application_fields VALUES ('s1','reject','2026-09-02','УО','')")
        allowed = sync.build_preview(con, snapshot(row()))["items"][0]
        self.assertTrue(allowed["apply_allowed"])

    def test_apply_requires_exact_confirmed_fingerprint(self):
        con = database(); source = snapshot(row())
        with self.assertRaises(PermissionError):
            sync.apply(con, source, source["source_fingerprint"], confirmed=False, actor="admin", synced_at="2026-09-15T10:00:00")
        with self.assertRaises(RuntimeError):
            sync.apply(con, source, "0" * 64, confirmed=True, actor="admin", synced_at="2026-09-15T10:00:00")

    def test_manager_observed_at_comes_from_source(self):
        con = database()
        con.execute("INSERT INTO supplier_edr_profiles(supplier_code,manager_name,synced_at) VALUES ('12345678','СТАРИЙ','old')")
        seen = []
        source = snapshot(row())
        result = sync.apply(con, source, source["source_fingerprint"], confirmed=True, actor="admin",
          synced_at="2026-09-15T18:00:00", sync_manager=lambda *args: seen.append(args[-1]) or {"changed": True})
        self.assertEqual(seen, ["2026-09-15"])
        self.assertEqual(result["manager_changes"], 1)

    def test_same_snapshot_is_idempotent(self):
        import server
        con = database()
        con.execute("INSERT INTO supplier_edr_profiles(supplier_code,synced_at) VALUES ('12345678','old')")
        source = snapshot(row())
        callbacks = dict(sync_manager=server.sync_current_supplier_manager,
          enrich_manager=server.enrich_current_supplier_manager,
          establish_manager=server.establish_current_supplier_manager,
          reestablish_manager=server.reestablish_current_supplier_manager)
        sync.apply(con, source, source["source_fingerprint"], confirmed=True, actor="admin",
                   synced_at="2026-09-15T18:00:00", **callbacks)
        again = sync.apply(con, source, source["source_fingerprint"], confirmed=True, actor="admin",
                           synced_at="2026-09-15T18:01:00", **callbacks)
        self.assertEqual(again["updated_profiles"], 0)
        self.assertEqual(again["verification_events"], 0)
        self.assertEqual(again["changed_fields"], {})

    def test_termination_clear_preserves_event(self):
        con = database()
        con.execute("""INSERT INTO supplier_edr_profiles(supplier_code,edr_status,edr_checked_at,
          termination_decision_details,edr_officer,synced_at) VALUES
          ('12345678','Припинено','2026-08-01','Запис № 7','УО','old')""")
        source = snapshot(row(status="Зареєстровано"))
        result = sync.apply(con, source, source["source_fingerprint"], confirmed=True, actor="admin", synced_at="2026-09-15T18:00:00")
        profile = con.execute("SELECT termination_decision_details FROM supplier_edr_profiles").fetchone()[0]
        self.assertEqual(profile, "")
        self.assertEqual(result["termination_clears"], 1)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM supplier_edr_verification_events WHERE event_type='termination_historical'").fetchone()[0], 1)

    def test_status_and_marker(self):
        con = database()
        con.execute("INSERT INTO submissions VALUES ('s1','11111111','A','2026-09-01')")
        con.execute("INSERT INTO application_fields VALUES ('s1','reject','2026-09-02','УО','')")
        con.execute("INSERT INTO frameworks VALUES ('f1','active','{}')")
        con.executemany("INSERT INTO registry_contracts VALUES (?,?,?)", [('22222222','active','f1'),('33333333','suspended','f1'),('44444444','cancelled','f1')])
        statuses = sync.prozorro_statuses(con)
        self.assertEqual(statuses['11111111'], 'Ще не в реєстрі')
        self.assertEqual(statuses['22222222'], 'Активний')
        self.assertEqual(statuses['33333333'], 'Призупинений')
        self.assertEqual(statuses['44444444'], 'Неактивний')
        self.assertEqual(sync.marker_for_status('Ще не в реєстрі','2026-09-15'), '🟣 Неактуально')

    def test_canonical_freshness_boundaries_and_non_monitored_states(self):
        today = date(2026, 9, 15)
        expected = {
            0: ('lt30', '🟢 <30 днів'), 29: ('lt30', '🟢 <30 днів'),
            30: ('gt30', '🟡 >30 днів'), 59: ('gt30', '🟡 >30 днів'),
            60: ('gt60', '🟠 >60 днів'), 89: ('gt60', '🟠 >60 днів'),
            90: ('gt90', '🔴 >90 днів'),
        }
        for age, pair in expected.items():
            state = sync.freshness_state('Активний', (today - timedelta(days=age)).isoformat(), today)
            self.assertEqual((state['bucket'], state['marker']), pair)
            self.assertTrue(state['monitored'])
        self.assertEqual(sync.freshness_state('Неактивний', '2020-01-01', today)['marker'], '🟣 Неактуально')
        self.assertEqual(sync.freshness_state('Ще не в реєстрі', '2026-09-15', today)['marker'], '🟣 Неактуально')
        self.assertEqual(sync.freshness_state('Призупинений', '', today)['marker'], '⚪ Не перевірено')

    def test_latest_verification_keeps_date_and_officer_from_same_event(self):
        con = database()
        con.execute("INSERT INTO submissions VALUES ('s1','12345678','Supplier','2026-09-01')")
        con.execute("INSERT INTO application_fields VALUES ('s1','admit','2026-09-10','УО ДОПУСКУ','')")
        sync._insert_event(con,item={'supplier_code':'12345678'},event_type='google_clarity',
          occurred_at='2026-09-12',officer='УО CLARITY',source='Google Sheets',changed_fields=[],
          snapshot={'supplier_code':'12345678','event':'newer'},created_at='2026-09-12')
        state=sync.canonical_supplier_edr_states(con,['12345678'],today=date(2026,9,15))['12345678']
        self.assertEqual((state['verification_date'],state['verification_officer']),('2026-09-12','УО CLARITY'))
        self.assertEqual(state['last_admission_date'],'2026-09-10')

    def test_newer_admission_beats_older_google_event(self):
        con = database()
        sync._insert_event(con,item={'supplier_code':'12345678'},event_type='google_clarity',
          occurred_at='2026-09-01',officer='УО CLARITY',source='Google Sheets',changed_fields=[],
          snapshot={'supplier_code':'12345678','event':'older'},created_at='2026-09-01')
        con.execute("INSERT INTO submissions VALUES ('s2','12345678','Supplier','2026-09-13')")
        con.execute("INSERT INTO application_fields VALUES ('s2','admit','2026-09-14','УО ПРОТОКОЛУ','')")
        state=sync.canonical_supplier_edr_states(con,['12345678'],today=date(2026,9,15))['12345678']
        self.assertEqual((state['verification_date'],state['verification_officer']),('2026-09-14','УО ПРОТОКОЛУ'))


if __name__ == "__main__":
    unittest.main()
