"""Read-only paired Google B/I/L versus SANDBOX legacy ledger gate."""
import json
import sqlite3
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import os

import legacy_google_verification_overlap_audit as module
import legacy_google_verification_preview as verification


def identity(code, tab, row):
    return {"supplier_code": code, "source_tab": tab, "source_row": row}


def pair(code, tab, row, day="2026-09-23", officer="Test Officer"):
    return dict(identity(code, tab, row), verification_date=day,
                verification_officer=officer)


def payload(identities, records):
    identities = sorted(identities, key=lambda x: (x["source_tab"], x["source_row"], x["supplier_code"]))
    records = sorted(records, key=lambda x: (x["source_tab"], x["source_row"], x["supplier_code"]))
    return {"spreadsheet_id": verification.SANDBOX_SPREADSHEET_ID,
            "source_digest": module.source_digest(identities, records),
            "identities": identities, "records": records}


class OverlapAuditTests(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        self.con.execute("""CREATE TABLE supplier_edr_verification_events
          (supplier_code TEXT,event_type TEXT,occurred_at TEXT,officer TEXT,
           source_sheet TEXT,source_row INTEGER,snapshot_json TEXT)""")
        self.con.execute("PRAGMA query_only=ON")
        self.registry_patch = patch.object(module.supplier_registry_integration,
            "_build_full_registry", side_effect=lambda con: {"items": [
                {"supplier_code": code, "verification_date": "2026-09-23"}
                for code in ("001", "002", "003", "004", "005")]})
        self.registry_patch.start()

    def tearDown(self):
        self.registry_patch.stop()
        self.con.close()

    def insert(self, code, tab, row, *, factual=False):
        self.con.execute("PRAGMA query_only=OFF")
        self.con.execute("INSERT INTO supplier_edr_verification_events VALUES (?,?,?,?,?,?,?)",
            (code, verification.SOURCE, "2026-09-23", "Test Officer", tab, row,
             json.dumps({"factual_edr_status": "Припинено"} if factual else {}, ensure_ascii=False)))
        self.con.commit()
        self.con.execute("PRAGMA query_only=ON")

    def test_exact_factual_and_il_only_are_equivalent_without_writes(self):
        self.insert("001", "ФОП", 2, factual=True)
        self.insert("002", "ЮО", 2)
        source = payload([identity("001", "ФОП", 2), identity("002", "ЮО", 2)],
                         [pair("001", "ФОП", 2), pair("002", "ЮО", 2)])
        before = list(self.con.execute("SELECT * FROM supplier_edr_verification_events"))
        result = module.audit(self.con, source)
        counts = result["counts"]
        self.assertEqual((counts["legacy_event_total"], counts["legacy_factual"],
                          counts["legacy_il_only"]), (2, 1, 1))
        self.assertEqual((counts["existing_exact_legacy_total"], counts["existing_exact_factual"],
                          counts["existing_exact_il_only"]), (2, 1, 1))
        self.assertEqual(counts["exact_legacy_classifier_equivalent_event"], 2)
        self.assertEqual(counts["erroneous_phase1_candidates"], 0)
        self.assertTrue(result["acceptance_passed"])
        self.assertEqual(before, list(self.con.execute("SELECT * FROM supplier_edr_verification_events")))
        self.assertEqual((result["query_only"], result["db_writes"], result["google_writes"]), (1, 0, 0))
        self.assertNotIn("Test Officer", str(result))
        self.assertNotIn("001", str(result))

    def test_changed_missing_and_ambiguous_google_identity(self):
        self.insert("001", "ФОП", 2)
        self.insert("002", "ЮО", 2)
        self.insert("003", "ЮО", 3)
        self.insert("004", "ЮО", 4)
        source = payload([identity("001", "ФОП", 2), identity("002", "ЮО", 2),
                          identity("003", "ЮО", 3), identity("003", "ЮО", 33)],
                         [pair("001", "ФОП", 2, day="2026-09-24"), pair("002", "ЮО", 2)])
        counts = module.audit(self.con, source)["counts"]
        self.assertEqual(counts["legacy_google_pair_changed"], 1)
        self.assertEqual(counts["changed_current_google_pair"], 1)
        self.assertEqual(counts["existing_exact_legacy_total"], 1)
        self.assertEqual(counts["legacy_ambiguous_google_identity"], 1)
        self.assertEqual(counts["legacy_google_identity_missing"], 1)
        self.assertEqual(counts["missing_google_pair"], 1)
        self.assertGreater(counts["ambiguous_identity"], 0)
        self.assertEqual(counts["legacy_google_pair_missing"], 0)
        self.assertEqual(counts["erroneous_phase1_candidates"], 0)

    def test_digest_sheet_and_query_only_guards(self):
        source = payload([identity("001", "ФОП", 2)], [pair("001", "ФОП", 2)])
        source["records"][0]["verification_officer"] = "Tampered"
        with self.assertRaisesRegex(ValueError, "OVERLAP_DIGEST_MISMATCH"):
            module.audit(self.con, source)
        source = payload([identity("001", "ФОП", 2)], [pair("001", "ФОП", 2)])
        source["spreadsheet_id"] = "wrong"
        with self.assertRaisesRegex(ValueError, "SANDBOX_SPREADSHEET_MISMATCH"):
            module.audit(self.con, source)
        self.con.execute("PRAGMA query_only=OFF")
        with self.assertRaisesRegex(ValueError, "QUERY_ONLY_REQUIRED"):
            module.audit(self.con, payload([identity("001", "ФОП", 2)], [pair("001", "ФОП", 2)]))

    def test_google_side_candidate_overlap_fails_gate_even_if_backend_excludes(self):
        self.insert("001", "ФОП", 2, factual=True)
        source = payload([identity("001", "ФОП", 2)], [pair("001", "ФОП", 2)])
        with patch.object(module.supplier_registry_integration, "_build_full_registry",
                          return_value={"items": [{"supplier_code": "001",
                                                   "verification_date": "2026-09-22"}]}):
            result = module.audit(self.con, source)
        self.assertEqual(result["counts"]["erroneous_phase1_candidates"], 1)
        self.assertEqual(result["counts"]["exact_legacy_classifier_equivalent_event"], 1)
        self.assertFalse(result["acceptance_passed"])

    def test_endpoint_requires_sandbox_and_bearer(self):
        import server
        replies = []
        handler = SimpleNamespace(path=module.PATH, command="POST",
            headers={"Authorization": "Bearer wrong"},
            send_json=lambda body, status=200: replies.append(status))
        handler._authorize_supplier_registry_integration = lambda: (
            server.Handler._authorize_supplier_registry_integration(handler))
        with patch.object(server, "SANDBOX_MODE", False):
            server.Handler._dispatch(handler, lambda: replies.append(200))
            self.assertEqual(replies[-1], 404)
        with patch.object(server, "SANDBOX_MODE", True), patch.dict(os.environ, {
                "PQM_SANDBOX_SUPPLIER_REGISTRY_TOKEN": "secret"}):
            server.Handler._dispatch(handler, lambda: replies.append(200))
            self.assertEqual(replies[-1], 401)
            handler.headers["Authorization"] = "Bearer secret"
            server.Handler._dispatch(handler, lambda: replies.append(200))
            self.assertEqual(replies[-1], 200)


if __name__ == "__main__":
    unittest.main()
