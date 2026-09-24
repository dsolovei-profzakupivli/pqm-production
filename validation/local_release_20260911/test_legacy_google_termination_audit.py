"""Read-only G/J/K/M pairing without Google or live database access."""
import os
import sqlite3
import unittest
from unittest.mock import patch
import re

import legacy_google_termination_audit as audit


def record(code, row, g="", j="", k="", m="", formulas=None):
    return {"supplier_code": code, "source_tab": "ФОП", "source_row": row,
            "g": g, "j": j, "k": k, "m": m, "formulas": formulas or []}


def request(rows):
    return {"spreadsheet_id": audit.SANDBOX_SPREADSHEET_ID,
            "source_digest": audit.digest(rows), "records": rows}


class TerminationAuditTests(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        self.con.create_function("DIGITS", 1, lambda value: re.sub(r"\D", "", str(value or "")))
        self.con.execute("CREATE TABLE submissions (supplier_code TEXT)")
        self.con.execute("CREATE TABLE supplier_registry_summary (supplier_code TEXT)")
        self.con.execute("""CREATE TABLE supplier_edr_profiles (
          supplier_code TEXT,source_sheet TEXT,termination_decision_details TEXT,
          termination_record_date TEXT,termination_record_number TEXT,edr_notes TEXT)""")
        self.con.executemany("INSERT INTO submissions VALUES (?)", [(x,) for x in
            (audit.TARGET, "002", "003", "004", "005")])
        self.con.executemany("INSERT INTO supplier_edr_profiles VALUES (?,?,?,?,?,?)", [
            ("002", "ФОП", "decision", "2026-07-20", "7", "note"),
            ("003", "ФОП", "old", "2026-07-19", "6", "old note"),
            ("005", "ФОП", "saved", "2026-01-01", "1", "saved note")])
        self.con.commit()
        self.con.execute("PRAGMA query_only=ON")

    def tearDown(self):
        self.con.close()

    def test_authoritative_google_categories_and_target_are_read_only(self):
        rows = [record(audit.TARGET, 1077, "decision", "20.07.2026", "7", "note"),
                record("002", 2, "decision", "2026-07-20", "7", "note"),
                record("003", 3, "new", "2026-07-20", "7", "new note"),
                record("004", 4, "partial"), record("005", 5)]
        before = self.con.total_changes
        result = audit.audit(self.con, request(rows))
        self.assertEqual(result["compared"], 5)
        self.assertEqual(result["termination_group"]["google_complete_pqm_missing"], 1)
        self.assertEqual(result["termination_group"]["google_complete_exact"], 1)
        self.assertEqual(result["termination_group"]["google_complete_different"], 1)
        self.assertEqual(result["termination_group"]["google_partial"], 1)
        self.assertEqual(result["termination_group"]["google_blank_pqm_present_preserved"], 1)
        self.assertEqual(result["fields"]["m"]["google_only"], 1)
        self.assertEqual(result["fields"]["m"]["exact"], 1)
        self.assertEqual(result["fields"]["m"]["different"], 1)
        self.assertEqual(result["fields"]["m"]["pqm_only"], 1)
        target = result["target_2791715838"]
        self.assertEqual((target["profile_found"], target["google_j"], target["pqm_j"]),
                         (False, "2026-07-20", ""))
        self.assertTrue(target["google_g_present"] and target["google_k_present"])
        self.assertTrue(target["google_m_present"])
        self.assertEqual(target["ui_blank_reason"], "no_literal_profile")
        self.assertNotIn("decision", str(result))
        self.assertEqual((result["db_writes"], result["google_writes"], self.con.total_changes-before),
                         (0, 0, 0))

    def test_rejects_tamper_wrong_sheet_and_oversized_batch(self):
        body = request([record("002", 2)])
        body["records"][0]["m"] = "tampered"
        with self.assertRaisesRegex(ValueError, "AUDIT_DIGEST_MISMATCH"):
            audit.audit(self.con, body)
        body = request([record("002", 2)]); body["spreadsheet_id"] = "other"
        with self.assertRaisesRegex(ValueError, "SANDBOX_SPREADSHEET"):
            audit.audit(self.con, body)
        with self.assertRaisesRegex(ValueError, "AUDIT_BATCH_LIMIT"):
            audit.audit(self.con, request([record(str(i), i+2) for i in range(101)]))

    def test_formula_and_missing_identity_are_separate_issues(self):
        rows = [record("002", 2, m="=formula", formulas=["m"]), record("missing", 3, g="x")]
        result = audit.audit(self.con, request(rows))
        self.assertEqual(result["compared"], 0)
        self.assertEqual(result["issues"], {"formula_evidence": 1, "missing_pqm_identity": 1})

    def test_complete_google_block_with_partial_pqm_is_separate(self):
        self.con.execute("PRAGMA query_only=OFF")
        self.con.execute("INSERT INTO submissions VALUES ('006')")
        self.con.execute("INSERT INTO supplier_edr_profiles VALUES ('006','ФОП','decision','','','')")
        self.con.commit()
        self.con.execute("PRAGMA query_only=ON")
        result = audit.audit(self.con, request([record("006", 6, "decision", "2026-07-20", "7")]))
        self.assertEqual(result["termination_group"]["google_complete_pqm_partial"], 1)
        self.assertEqual(result["termination_group"]["google_complete_different"], 0)
        self.assertEqual(result["fields"]["g"]["exact"], 1)
        self.assertEqual(result["fields"]["j"]["google_only"], 1)

    def test_sandbox_bearer_route(self):
        import server
        responses = []
        handler = type("Fake", (), {})()
        handler.path = audit.PATH; handler.command = "POST"
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
        with patch.object(server, "SANDBOX_MODE", False):
            server.Handler._dispatch(handler, lambda: responses.append(200))
            self.assertEqual(responses[-1], 404)


if __name__ == "__main__":
    unittest.main()
