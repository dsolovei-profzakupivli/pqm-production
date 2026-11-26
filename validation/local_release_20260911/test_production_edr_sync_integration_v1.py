"""Production EDR integration regressions; synthetic SQLite only, no Google calls."""
import sqlite3
import unittest
from unittest.mock import patch
from io import BytesIO
from datetime import datetime
from openpyxl import load_workbook

import server
import edr_sync_v2 as sync
from test_edr_sync_v2 import database, row, snapshot


class ProductionEdrSyncIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.con = database()
        self.addCleanup(self.con.close)

    def qualify(self, submission_id, code, name, day, status):
        self.con.execute("INSERT INTO submissions VALUES(?,?,?,?)", (submission_id, code, name, day))
        self.con.execute("INSERT INTO qualifications VALUES(?,?,?)", ("q-" + submission_id, status, submission_id))

    def test_eligibility_uses_qualification_status_without_protocol_decision(self):
        self.qualify("old", "10000001", "Old", "2025-01-01", "active")
        self.qualify("meddata", "10000002", "MedData", "2025-01-02", "unsuccessful")
        self.qualify("draft", "10000003", "Draft", "2025-01-03", "pending")
        self.qualify("cancelled", "10000004", "Cancelled", "2025-01-04", "cancelled")
        self.assertEqual(sync._edr_eligible_codes(self.con), {"10000001", "10000002"})
        self.assertEqual(sync._latest_application_names(self.con),
                         {"10000001": "Old", "10000002": "MedData"})

    def test_latest_name_comes_from_newest_eligible_qualification(self):
        self.qualify("active-old", "10000011", "Eligible older", "2025-01-01", "active")
        self.qualify("pending-new", "10000011", "Ineligible newer", "2026-01-01", "pending")
        self.qualify("unsuccessful-new", "10000011", "Eligible newest", "2025-12-01", "unsuccessful")
        self.assertEqual(sync._latest_application_names(self.con)["10000011"], "Eligible newest")

    def test_partial_apply_skips_conflicted_profile_history_and_receipt(self):
        code_conflict, code_ready = "20000001", "20000002"
        self.qualify("conflict", code_conflict, "Conflict", "2026-01-01", "active")
        self.qualify("ready", code_ready, "Ready", "2026-01-02", "unsuccessful")
        self.con.execute("""INSERT INTO supplier_edr_profiles
          (supplier_code,full_name,edr_status,edr_checked_at,edr_officer,source_sheet,source_row,synced_at)
          VALUES(?,?,?,?,?,?,?,?)""", (code_conflict, "Conflict", "Припинено",
          "2026-09-15T12:00:00+03:00", "УО", "ФОП", 9, "before"))
        self.con.execute("INSERT INTO supplier_google_receipts VALUES(?,?,?,?,?,?)",
          (code_conflict, "before", "old", "ФОП", 9, "a" * 64))
        self.con.execute("""INSERT INTO supplier_edr_verification_events
          (supplier_code,event_type,occurred_at,officer,source,changed_fields,snapshot_hash,snapshot_json,created_at)
          VALUES(?,?,?,?,?,?,?,?,?)""", (code_conflict, "manual_edr", "2026-09-15T12:00:00+03:00",
          "УО", "test", "[]", "b" * 64, "{}", "before"))
        source = snapshot(row(code=code_conflict, checked="15.09.2026 12:00:00", status="Зареєстровано"),
                          row(code=code_ready, checked="15.09.2026 13:00:00"))
        preview = sync.build_preview(self.con, source)
        conflict_plan = next(p for p in preview["items"] if p["supplier_code"] == code_conflict)
        self.assertEqual(conflict_plan["row_state"], "conflict")
        self.assertEqual(preview["summary"]["ready_to_apply"], 1)
        self.assertEqual(preview["summary"]["ready_to_apply"],
                         preview["summary"]["ready_with_changes"] + preview["summary"]["ready_unchanged"])
        before_profile = tuple(self.con.execute("SELECT * FROM supplier_edr_profiles WHERE supplier_code=?", (code_conflict,)).fetchone())
        before_history = [tuple(r) for r in self.con.execute("SELECT * FROM supplier_edr_verification_events WHERE supplier_code=?", (code_conflict,))]
        before_receipt = tuple(self.con.execute("SELECT * FROM supplier_google_receipts WHERE supplier_code=?", (code_conflict,)).fetchone())
        result = sync.apply(self.con, source, source["source_fingerprint"], confirmed=True, actor="test",
            synced_at="2026-09-16T12:00:00+00:00", expected_state_digest=sync.preview_state_digest(preview),
            allow_partial_conflicts=True)
        self.assertEqual(result["skipped_conflicts"], 1)
        self.assertEqual(result["inserted"] + result["updated_profiles"] + result["unchanged"], 1)
        self.assertEqual(tuple(self.con.execute("SELECT * FROM supplier_edr_profiles WHERE supplier_code=?", (code_conflict,)).fetchone()), before_profile)
        self.assertEqual([tuple(r) for r in self.con.execute("SELECT * FROM supplier_edr_verification_events WHERE supplier_code=?", (code_conflict,))], before_history)
        self.assertEqual(tuple(self.con.execute("SELECT * FROM supplier_google_receipts WHERE supplier_code=?", (code_conflict,)).fetchone()), before_receipt)
        self.assertIsNotNone(self.con.execute("SELECT 1 FROM supplier_edr_profiles WHERE supplier_code=?", (code_ready,)).fetchone())
        with self.assertRaisesRegex(ValueError, "містить конфлікти"):
            sync.apply(self.con, source, source["source_fingerprint"], confirmed=True, actor="test",
                synced_at="2026-09-16T12:00:00+00:00", allow_partial_conflicts=False)

    def test_stale_preview_is_rejected_before_any_apply_write(self):
        self.qualify("stale", "30000001", "Stale", "2026-01-01", "active")
        source = snapshot(row(code="30000001", checked="15.09.2026 12:00:00"))
        preview = sync.build_preview(self.con, source)
        digest = sync.preview_state_digest(preview)
        self.con.execute("INSERT INTO supplier_edr_profiles(supplier_code,full_name,edr_checked_at,synced_at) VALUES(?,?,?,?)",
                         ("30000001", "Changed after preview", "2026-09-15T12:00:00+03:00", "now"))
        before = self.con.total_changes
        with self.assertRaisesRegex(RuntimeError, "PQM state changed"):
            sync.apply(self.con, source, source["source_fingerprint"], confirmed=True, actor="test",
                synced_at="2026-09-16T12:00:00+00:00", expected_state_digest=digest)
        self.assertEqual(self.con.total_changes, before)

    def test_conflict_xlsx_has_all_rows_text_ids_and_real_kyiv_datetimes(self):
        self.qualify("xlsx", "00001234", "XLSX", "2026-01-01", "active")
        self.con.execute("""INSERT INTO supplier_edr_profiles
          (supplier_code,full_name,edr_status,edr_checked_at,edr_officer,synced_at)
          VALUES('00001234','PQM name','Припинено','2026-09-15T12:00:00+03:00','УО','before')""")
        source = snapshot(row(code="00001234", checked="15.09.2026 12:00:00", status="Зареєстровано"))
        preview = sync.build_preview(self.con, source)
        raw = server.supplier_edr_conflict_xlsx(preview)
        workbook = load_workbook(BytesIO(raw), data_only=True)
        sheet = workbook["Конфлікти Preview"]
        self.assertEqual(sheet.max_row, 2)
        self.assertEqual(sheet.freeze_panes, "A2")
        self.assertIsNotNone(sheet.auto_filter.ref)
        self.assertEqual(sheet.cell(2, 2).value, "00001234")
        self.assertEqual(sheet.cell(2, 2).number_format, "@")
        self.assertIsInstance(sheet.cell(2, 8).value, datetime)
        self.assertIsInstance(sheet.cell(2, 9).value, datetime)
        self.assertEqual(sheet.cell(2, 9).number_format, "dd.mm.yyyy hh:mm:ss")
        self.assertEqual(sheet.cell(2, 9).value.hour, 12)
        self.assertIn("дані", str(sheet.cell(2, 4).value).casefold())

    def test_manager_callbacks_compare_exact_source_timestamp_not_calendar_day(self):
        for code, manual_time, expected_changed in (
                ("40000001", "17:00:00", True),
                ("40000002", "19:00:00", False),
                ("40000003", "18:00:00", False)):
            with self.subTest(manual_time=manual_time):
                con = database()
                try:
                    con.execute("""INSERT INTO supplier_managers
                      (supplier_code,manager_name,normalized_name,valid_from,valid_to,is_current,source,created_at,updated_at)
                      VALUES(?,?,?,'2026-09-15',NULL,1,'Підтверджено УО',?,?)""",
                      (code, "Ручний керівник", "ручний керівник",
                       f"2026-09-15T{manual_time}+03:00", f"2026-09-15T{manual_time}+03:00"))
                    result = server.sync_current_supplier_manager(con, code, "Google керівник",
                        "Google Sheets: ЮО", "2026-09-15", source_timestamp="2026-09-15T18:00:00+03:00")
                    self.assertEqual(bool(result["changed"]), expected_changed)
                    self.assertEqual(con.execute("SELECT COUNT(*) FROM supplier_managers WHERE is_current=0").fetchone()[0],
                                     int(expected_changed))
                finally: con.close()

    def test_manager_priority_normalizes_utc_kyiv_and_date_only_without_writing_synthetic_time(self):
        self.assertEqual(server._supplier_manager_priority_instant("2026-09-15T15:00:00Z"),
                         server._supplier_manager_priority_instant("2026-09-15T18:00:00+03:00"))
        self.assertEqual(server._supplier_manager_priority_instant("2026-01-15T12:00:00"),
                         server._supplier_manager_priority_instant("2026-01-15T10:00:00Z"))
        midnight = server._supplier_manager_priority_instant("2026-09-15")
        self.assertEqual(midnight.isoformat(), "2026-09-14T21:00:00+00:00")

        for callback_name in ("sync_current_supplier_manager", "enrich_current_supplier_manager"):
            with self.subTest(callback=callback_name):
                con = database()
                try:
                    con.execute("""INSERT INTO supplier_managers
                      (supplier_code,manager_name,normalized_name,valid_from,valid_to,is_current,source,created_at,updated_at)
                      VALUES('41000001','Ручний керівник','ручний керівник','2026-09-15',NULL,1,
                             'Підтверджено УО','before','2026-09-15')""")
                    before = con.execute("SELECT updated_at FROM supplier_managers WHERE supplier_code='41000001'").fetchone()[0]
                    callback = getattr(server, callback_name)
                    if callback_name == "sync_current_supplier_manager":
                        result = callback(con, "41000001", "Google керівник", "Google Sheets: ЮО",
                                          "2026-09-15", source_timestamp="2026-09-15T12:00:00+03:00")
                        self.assertTrue(result["changed"])
                    else:
                        result = callback(con, "41000001", "Ручний керівник повне ім'я", "Google Sheets: ЮО",
                                          "2026-09-15", source_timestamp="2026-09-15T12:00:00+03:00")
                        self.assertTrue(result["enriched"])
                    # Comparison may interpret a historical date as Kyiv midnight,
                    # but the callback must not rewrite that stored date as a timestamp.
                    stored = con.execute("SELECT updated_at FROM supplier_managers WHERE supplier_code='41000001' AND is_current=1").fetchone()[0]
                    self.assertNotEqual(before, "2026-09-15T00:00:00+03:00")
                    self.assertEqual(stored, "2026-09-15")
                finally:
                    con.close()

    def test_same_day_google_instant_compares_with_date_only_pqm_midnight(self):
        self.qualify("same-day", "40000011", "Same day", "2026-01-01", "active")
        self.con.execute("""INSERT INTO supplier_edr_profiles
          (supplier_code,edr_checked_at,source_sheet,source_row,synced_at)
          VALUES('40000011','2026-09-15','ЮО',2,'before')""")
        source = snapshot(row(code="40000011", checked="15.09.2026 12:00:00"))
        preview = sync.build_preview(self.con, source)
        self.assertTrue(preview["items"][0]["datetime_gate"]["accepted"])
        self.assertEqual(preview["items"][0]["datetime_gate"]["reason"], "newer")
        result = sync.apply(self.con, source, source["source_fingerprint"], confirmed=True,
            actor="test", synced_at="2026-09-16T12:00:00+00:00")
        self.assertEqual(result["updated_profiles"], 1)
        self.assertEqual(self.con.execute("SELECT edr_checked_at FROM supplier_edr_profiles WHERE supplier_code='40000011'").fetchone()[0],
                         "2026-09-15T12:00:00+03:00")

    def test_callback_failure_rolls_back_profile_history_and_receipt(self):
        self.qualify("rollback-first", "50000000", "First", "2026-01-01", "active")
        self.qualify("rollback-second", "50000001", "Rollback", "2026-01-02", "active")
        source = snapshot(row(code="50000000", checked="15.09.2026 11:00:00", manager=""),
                          row(code="50000001", checked="15.09.2026 12:00:00"))
        before_tables = ("supplier_edr_profiles", "supplier_edr_verification_events", "supplier_google_receipts", "supplier_managers")
        before = {name: self.con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in before_tables}
        def fail(*args, **kwargs): raise RuntimeError("synthetic callback failure")
        import socket
        with self.assertRaisesRegex(RuntimeError, "synthetic callback failure"):
            with patch.object(socket.socket, "connect", side_effect=AssertionError("Google/network write forbidden")):
                with self.con:
                    sync.apply(self.con, source, source["source_fingerprint"], confirmed=True, actor="test",
                        synced_at="2026-09-16T12:00:00+00:00", establish_manager=fail)
        after = {name: self.con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in before_tables}
        self.assertEqual(after, before)
        self.assertIsNone(self.con.execute("SELECT 1 FROM supplier_edr_profiles WHERE supplier_code='50000000'").fetchone())

    def test_migrate_adds_receipt_table_without_changing_existing_profile_data(self):
        self.con.execute("INSERT INTO supplier_edr_profiles(supplier_code,full_name,edr_checked_at,synced_at) VALUES(?,?,?,?)",
                         ("51000001", "Existing", "2025-01-01", "before"))
        self.con.execute("DROP TABLE supplier_google_receipts")
        sync.migrate(self.con)
        row = self.con.execute("SELECT full_name,edr_checked_at,synced_at FROM supplier_edr_profiles WHERE supplier_code='51000001'").fetchone()
        self.assertEqual(tuple(row), ("Existing", "2025-01-01", "before"))
        columns = {item[1] for item in self.con.execute("PRAGMA table_info(supplier_google_receipts)")}
        self.assertEqual(columns, {"supplier_code", "received_at", "actor", "source_sheet", "source_row", "source_fingerprint"})

    def test_production_gates_are_independent_and_default_off(self):
        with patch.dict(server.os.environ, {}, clear=True):
            self.assertFalse(server.production_edr_partial_apply_enabled())
            self.assertFalse(server.google_edr_effective_enabled())
        with patch.dict(server.os.environ, {"PQM_PRODUCTION_EDR_SYNC_ENABLED": "1",
                "PQM_PRODUCTION_EDR_PARTIAL_APPLY": "0", "PQM_ENABLE_GOOGLE": "1"}, clear=True), \
             patch.object(server, "google_effective_enabled", return_value=True):
            self.assertTrue(server.google_edr_effective_enabled())
            self.assertFalse(server.production_edr_partial_apply_enabled())
        with patch.object(server, "SANDBOX_MODE", False), \
             patch.object(server, "google_runtime_state", return_value={"enabled": True}):
            with patch.dict(server.os.environ, {"PQM_PRODUCTION_EDR_SYNC_ENABLED": "0",
                    "PQM_PRODUCTION_EDR_PARTIAL_APPLY": "0"}, clear=True):
                writer_gate_before = server.google_effective_enabled()
                self.assertFalse(server.google_edr_effective_enabled())
            with patch.dict(server.os.environ, {"PQM_PRODUCTION_EDR_SYNC_ENABLED": "1",
                    "PQM_PRODUCTION_EDR_PARTIAL_APPLY": "1"}, clear=True):
                self.assertEqual(server.google_effective_enabled(), writer_gate_before)
                self.assertTrue(server.google_edr_effective_enabled())
                self.assertTrue(server.production_edr_partial_apply_enabled())

    def test_google_writer_token_access_remains_available_when_edr_grant_is_off(self):
        now = server.time.time()
        with patch.object(server, "SANDBOX_MODE", False), \
             patch.object(server, "google_effective_enabled", return_value=True), \
             patch.object(server, "_google_oauth_token", return_value={
                 "access_token": "synthetic-access", "refresh_token": "synthetic-refresh",
                 "obtained_at": now, "expires_in": 3600}), \
             patch.object(server, "_google_oauth_client", return_value={"client_id": "synthetic"}), \
             patch.dict(server.os.environ, {"PQM_PRODUCTION_EDR_SYNC_ENABLED": "0"}, clear=True):
            self.assertFalse(server.google_edr_effective_enabled())
            self.assertEqual(server._google_access_token(), "synthetic-access")

    def test_note_only_change_reconciles_counts_and_second_apply_is_unchanged(self):
        code = "52000001"
        self.qualify("note-only", code, "Note only", "2026-01-01", "active")
        self.con.execute("""INSERT INTO supplier_edr_profiles
          (supplier_code,full_name,short_name,manager_name,edr_status,edr_checked_at,edr_officer,
           edr_notes,source_sheet,source_row,synced_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
          (code, "ПОВНА НАЗВА", "СКОРОЧЕНА НАЗВА", "", "Зареєстровано",
           "2026-09-15T10:00:00+03:00", "УО", "Стара примітка", "ЮО", 2, "before"))
        incoming = row(code=code, checked="15.09.2026 12:00:00", manager="")
        incoming[12] = "Нова примітка"
        source = snapshot(incoming)
        initial = sync.build_preview(self.con, source)
        plan = initial["items"][0]
        self.assertEqual(plan["changed_fields"], ["edr_notes"])
        self.assertEqual(initial["summary"]["ready_with_changes"], 1)
        self.assertEqual(initial["summary"]["ready_unchanged"], 0)
        self.assertEqual(initial["summary"]["ready_to_apply"], 1)
        preview = sync.build_preview(self.con, source)
        self.assertTrue(preview["items"][0]["verification_event_change"])
        self.assertEqual(preview["items"][0]["changed_fields"], ["edr_notes"])
        first_result = sync.apply(self.con, source, source["source_fingerprint"], confirmed=True,
            actor="test", synced_at="2026-09-16T12:00:00+00:00",
            expected_state_digest=sync.preview_state_digest(preview))
        self.assertEqual(first_result["ready_to_apply"], 1)
        self.assertEqual(first_result["updated_profiles"], 1)
        self.assertEqual(first_result["unchanged"], 0)
        self.assertEqual(first_result["changed_fields"].get("edr_notes"), 1)

        again = sync.build_preview(self.con, source)
        self.assertEqual(again["summary"]["ready_to_apply"], 1)
        self.assertEqual(again["summary"]["ready_with_changes"], 0)
        self.assertEqual(again["summary"]["ready_unchanged"], 1)
        second_result = sync.apply(self.con, source, source["source_fingerprint"], confirmed=True,
            actor="test", synced_at="2026-09-17T12:00:00+00:00",
            expected_state_digest=sync.preview_state_digest(again))
        self.assertEqual(second_result["updated_profiles"], 0)
        self.assertEqual(second_result["unchanged"], 1)
        self.assertEqual(second_result["ready_to_apply"], 1)


if __name__ == "__main__":
    unittest.main()
