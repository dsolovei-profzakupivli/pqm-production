"""Controlled G/J/K/M Preview and Apply with synthetic profiles only."""
import sqlite3
import os
import unittest
from unittest.mock import patch

import legacy_google_termination_import as imp


def row(code="001", number=2, *, g="", j="", k="", m=""):
    return {"supplier_code": code, "source_tab": "ФОП", "source_row": number,
            "g": g, "j": j, "k": k, "m": m, "formulas": []}


def request(records):
    return {"spreadsheet_id": imp.audit.SANDBOX_SPREADSHEET_ID,
            "source_digest": imp.source_digest(records), "records": records}


class TerminationImportTests(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        self.con.executescript("""
          CREATE TABLE supplier_edr_profiles (supplier_code TEXT PRIMARY KEY, source_sheet TEXT,
            edr_status TEXT, manager_name TEXT, verification_date TEXT,
            termination_decision_details TEXT, termination_record_date TEXT,
            termination_record_number TEXT, edr_notes TEXT);
          CREATE TABLE supplier_notes (supplier_code TEXT, note TEXT);
          CREATE TABLE supplier_edr_verification_events (supplier_code TEXT, officer TEXT);
          CREATE TABLE qualifications (supplier_code TEXT, status TEXT);
          CREATE TABLE submissions (supplier_code TEXT, status TEXT);
        """)
        self.con.execute("INSERT INTO supplier_edr_profiles VALUES (?,?,?,?,?,?,?,?,?)",
                         ("001", "ФОП", "Зареєстровано", "manager", "2026-09-01", "", "", "", ""))
        self.con.execute("INSERT INTO supplier_notes VALUES (?,?)", ("001", "internal"))
        self.con.commit()

    def tearDown(self):
        self.con.close()

    def bound(self, records):
        source = request(records)
        self.con.execute("PRAGMA query_only=ON")
        preview = imp.preview(self.con, source)
        self.con.execute("PRAGMA query_only=OFF")
        return {**source, "selection_digest": preview["selection_digest"],
                "preview_ticket": preview["preview_ticket"], "confirmation": imp.CONFIRMATION}

    def test_complete_partial_notes_blank_preserve_and_idempotency(self):
        records = [row(g="decision", j="20.07.2026", k="7", m="google note")]
        body = self.bound(records)
        self.con.execute("PRAGMA query_only=ON")
        preview = imp.preview(self.con, request(records))
        self.assertEqual((preview["selected"], preview["field_writes"],
                          preview["complete_termination_blocks"]),
                         (1, {"g": 1, "j": 1, "k": 1, "m": 1}, 1))
        self.assertEqual((preview["db_writes"], preview["google_writes"], preview["query_only"]), (0, 0, 1))
        self.con.execute("PRAGMA query_only=OFF")
        applied = imp.apply(self.con, body)
        self.assertEqual((applied["updated"], applied["verified"]), (1, 1))
        self.assertEqual(imp.apply(self.con, body)["transaction_status"], "ALREADY_APPLIED")
        p = self.con.execute("SELECT * FROM supplier_edr_profiles").fetchone()
        self.assertEqual((p["termination_decision_details"], p["termination_record_date"],
                          p["termination_record_number"], p["edr_notes"]),
                         ("decision", "2026-07-20", "7", "google note"))
        self.assertEqual((p["edr_status"], p["manager_name"], p["verification_date"]),
                         ("Зареєстровано", "manager", "2026-09-01"))
        self.assertEqual(self.con.execute("SELECT note FROM supplier_notes").fetchone()[0], "internal")

    def test_partial_and_m_only_preserve_other_fields(self):
        self.con.execute("UPDATE supplier_edr_profiles SET termination_record_date='2026-01-01',"
                         "termination_record_number='old' WHERE supplier_code='001'")
        self.con.commit()
        imp.apply(self.con, self.bound([row(g="new")]))
        p = self.con.execute("SELECT * FROM supplier_edr_profiles").fetchone()
        self.assertEqual((p["termination_decision_details"], p["termination_record_date"],
                          p["termination_record_number"]), ("new", "2026-01-01", "old"))
        imp.apply(self.con, self.bound([row(m="note")]))
        self.assertEqual(self.con.execute("SELECT edr_notes FROM supplier_edr_profiles").fetchone()[0], "note")

    def test_500_commits_and_501_rejected_before_write(self):
        records = [row(str(n), n + 2, m="note") for n in range(500)]
        self.con.executemany("INSERT OR IGNORE INTO supplier_edr_profiles(supplier_code,source_sheet) VALUES (?,'ФОП')",
                             [(r["supplier_code"],) for r in records])
        self.con.commit()
        body = self.bound(records)
        self.assertEqual(imp.apply(self.con, body)["updated"], 500)
        self.assertEqual(imp.apply(self.con, body)["transaction_status"], "ALREADY_APPLIED")
        too_many = request([row(str(n), n + 2, m="note") for n in range(501)])
        too_many.update(selection_digest="x", preview_ticket="x", confirmation=imp.CONFIRMATION)
        before = self.con.total_changes
        with self.assertRaisesRegex(ValueError, "IMPORT_BATCH_LIMIT"):
            imp.apply(self.con, too_many)
        self.assertEqual((self.con.total_changes, self.con.in_transaction), (before, False))

    def test_stale_ticket_digest_and_state_fail_closed(self):
        body = self.bound([row(g="new")])
        wrong = dict(body, selection_digest="x")
        with self.assertRaisesRegex(ValueError, "PREVIEW_TICKET"):
            imp.apply(self.con, wrong)
        with patch.object(imp.binding, "_ticket_valid", return_value=False):
            with self.assertRaisesRegex(ValueError, "PREVIEW_TICKET"):
                imp.apply(self.con, body)
        self.con.execute("UPDATE supplier_edr_profiles SET edr_status='changed'")
        self.con.commit()
        with self.assertRaisesRegex(ValueError, "STALE_PREVIEW"):
            imp.apply(self.con, body)
        self.assertEqual(self.con.execute("SELECT termination_decision_details FROM supplier_edr_profiles").fetchone()[0], "")

    def test_rollback_on_readback_or_protected_change(self):
        body = self.bound([row(g="new")])
        def break_readback(con):
            con.execute("UPDATE supplier_edr_profiles SET termination_decision_details='corrupt'")
        with self.assertRaisesRegex(ValueError, "AFTER_READBACK"):
            imp.apply(self.con, body, after_write_hook=break_readback)
        self.assertEqual(self.con.execute("SELECT termination_decision_details FROM supplier_edr_profiles").fetchone()[0], "")
        def break_protected(con):
            con.execute("UPDATE supplier_notes SET note='corrupt'")
        with self.assertRaisesRegex(ValueError, "PROTECTED_DATA"):
            imp.apply(self.con, body, after_write_hook=break_protected)
        self.assertEqual(self.con.execute("SELECT note FROM supplier_notes").fetchone()[0], "internal")

    def test_entire_multirow_batch_rolls_back(self):
        self.con.execute("INSERT INTO supplier_edr_profiles(supplier_code,source_sheet) VALUES ('002','ФОП')")
        self.con.commit()
        body = self.bound([row("001", 2, g="first"), row("002", 3, m="second")])
        def corrupt_second(con):
            con.execute("UPDATE supplier_edr_profiles SET edr_notes='corrupt' WHERE supplier_code='002'")
        with self.assertRaisesRegex(ValueError, "AFTER_READBACK"):
            imp.apply(self.con, body, after_write_hook=corrupt_second)
        self.assertEqual([tuple(r) for r in self.con.execute(
            "SELECT termination_decision_details,edr_notes FROM supplier_edr_profiles ORDER BY supplier_code")],
            [("", ""), (None, None)])

    def test_blocked_missing_profile_and_formula(self):
        records = [row("unknown", 3, g="value")]
        self.con.execute("PRAGMA query_only=ON")
        result = imp.preview(self.con, request(records))
        self.assertEqual((result["selected"], result["blocked"]), (0, 1))
        formula = row(g="value"); formula["formulas"] = ["g"]
        result = imp.preview(self.con, request([formula]))
        self.assertEqual((result["selected"], result["blocked"]), (0, 1))

    def test_deterministic_next_batch_and_source_tamper(self):
        records = [row(g="new")]
        body = self.bound(records)
        self.con.execute("PRAGMA query_only=ON")
        first = imp.preview(self.con, request(records))
        second = imp.preview(self.con, request(records))
        self.assertEqual(first["selection_digest"], second["selection_digest"])
        self.con.execute("PRAGMA query_only=OFF")
        bad = dict(body, records=[dict(records[0], g="tampered")])
        with self.assertRaisesRegex(ValueError, "IMPORT_SOURCE_DIGEST_MISMATCH"):
            imp.apply(self.con, bad)
        imp.apply(self.con, body)
        self.con.execute("PRAGMA query_only=ON")
        next_batch = imp.preview(self.con, request(records))
        self.assertEqual((next_batch["selected"], next_batch["equivalent"]), (0, 1))

    def test_endpoint_requires_sandbox_and_bearer(self):
        import server
        responses = []
        handler = type("Fake", (), {})()
        handler.path = imp.PREVIEW_PATH; handler.command = "POST"
        handler.headers = {"Authorization": "Bearer wrong"}
        handler.send_json = lambda data, status=200: responses.append(status)
        handler._authorize_supplier_registry_integration = lambda: (
            server.Handler._authorize_supplier_registry_integration(handler))
        with patch.object(server, "SANDBOX_MODE", True), patch.dict(os.environ, {
                "PQM_SANDBOX_SUPPLIER_REGISTRY_TOKEN": "secret"}):
            server.Handler._dispatch(handler, lambda: responses.append(200))
            self.assertEqual(responses[-1], 401)
            handler.headers["Authorization"] = "Bearer secret"
            server.Handler._dispatch(handler, lambda: responses.append(200))
            self.assertEqual(responses[-1], 200)
            handler.path = imp.APPLY_PATH
            server.Handler._dispatch(handler, lambda: responses.append(200))
            self.assertEqual(responses[-1], 200)
        with patch.object(server, "SANDBOX_MODE", False):
            server.Handler._dispatch(handler, lambda: responses.append(200))
            self.assertEqual(responses[-1], 404)


if __name__ == "__main__":
    unittest.main()
