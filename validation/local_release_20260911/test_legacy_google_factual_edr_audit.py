"""Read-only factual Google E audit and chronology guards."""
import io
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import legacy_google_factual_edr_audit as audit


def record(code, row, status="Припинено", day="2026-09-20", officer="Test Officer", formulas=None):
    return {"supplier_code": code, "source_tab": "ФОП", "source_row": row,
            "google_edr_status": status, "google_prozorro_status": "Активний",
            "verification_date": day, "verification_officer": officer,
            "formulas": formulas or []}


def request(rows):
    return {"spreadsheet_id": audit.SANDBOX_SPREADSHEET_ID,
            "source_digest": audit.source_digest(rows), "records": rows}


def event(day, status, kind="manual_edr"):
    return {"id": 1, "event_type": kind, "occurred_at": day,
            "snapshot_json": '{"edr_status":"' + status + '"}'}


class FactualEdrAuditTests(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        self.con.execute("CREATE TABLE submissions (supplier_code TEXT)")
        self.con.execute("CREATE TABLE supplier_registry_summary (supplier_code TEXT)")
        self.con.execute("CREATE TABLE supplier_edr_profiles (supplier_code TEXT,source_sheet TEXT,"
                         "edr_status TEXT,edr_checked_at TEXT)")
        self.con.execute("CREATE TABLE supplier_edr_verification_events (supplier_code TEXT,"
                         "event_type TEXT,occurred_at TEXT,officer TEXT,snapshot_json TEXT)")
        self.con.executemany("INSERT INTO submissions VALUES (?)", [(str(i),) for i in range(1, 8)])
        self.con.execute("INSERT INTO supplier_edr_verification_events VALUES (?,?,?,?,?)",
                         ("1", "legacy_google_registry", "2026-09-20", "Test Officer", "{}"))
        self.con.commit()
        self.con.execute("PRAGMA query_only=ON")

    def tearDown(self):
        self.con.close()

    def test_chronology_overlap_risk_and_zero_writes(self):
        rows = [record("1", 2), record("2", 3, day="2026-08-20"),
                record("3", 4, day="2026-09-10"), record("4", 5, day=""),
                record("5", 6, day="2026-09-15"), record("6", 7, day="2026-09-20"),
                record("7", 8, day="2026-09-20", formulas=["e"])]
        facts = {"2": [event("2026-08-25", "Припинено")],
                 "3": [event("2026-09-15", "Припинено")],
                 "6": [event("2026-09-20", "Банкрут")]}
        before = self.con.total_changes
        with patch.object(audit.edr_sync_v2, "canonical_prozorro_statuses",
                          return_value={str(i): "Активний" for i in range(1, 8)}), \
             patch.object(audit.edr_sync_v2, "active_qualification_dates",
                          return_value={str(i): "2026-09-01" for i in range(1, 8)}), \
             patch.object(audit.supplier_registry_integration, "_factual_edr_events",
                          return_value=facts):
            result = audit.audit(self.con, request(rows))
        counts = result["counts"]
        self.assertEqual(counts["A_after_latest_qualification"], 2)
        self.assertEqual(counts["B_before_newer_qualification"], 1)
        self.assertEqual(counts["C_equivalent_or_newer_pqm_factual"], 1)
        self.assertEqual(counts["D_missing_or_unsafe_evidence"], 2)
        self.assertEqual(counts["review_same_day_conflicting_factual"], 1)
        self.assertEqual(counts["legacy_event_same_date_officer"], 1)
        self.assertEqual(counts["legacy_pair_without_factual_status"], 1)
        self.assertEqual(counts["classified"], len(rows))
        self.assertEqual(result["legacy_event_db_total"], 1)
        self.assertEqual(result["by_google_factual_status"]["Припинено"]
                         ["A_after_latest_qualification_active"], 2)
        self.assertEqual(result["pqm_to_google_e_overwrite_risk"]["to_registered"], 5)
        self.assertEqual((result["db_writes"], result["google_writes"],
                          self.con.total_changes-before), (0, 0, 0))
        self.assertNotIn("Test Officer", str(result))

    def test_rejects_tamper_wrong_sheet_batch_and_write_capable_db(self):
        body = request([record("1", 2)])
        body["records"][0]["verification_date"] = "2026-09-21"
        with self.assertRaisesRegex(ValueError, "AUDIT_DIGEST_MISMATCH"):
            audit.audit(self.con, body)
        body = request([record("1", 2)]); body["spreadsheet_id"] = "wrong"
        with self.assertRaisesRegex(ValueError, "SANDBOX_SPREADSHEET_MISMATCH"):
            audit.audit(self.con, body)
        with self.assertRaisesRegex(ValueError, "AUDIT_BATCH_LIMIT"):
            audit.audit(self.con, request([record(str(i), i+2) for i in range(101)]))
        self.con.execute("PRAGMA query_only=OFF")
        with self.assertRaisesRegex(ValueError, "QUERY_ONLY_REQUIRED"):
            audit.audit(self.con, request([record("1", 2)]))

    def test_inactive_uses_historical_effective_qualification_for_chronology_only(self):
        self.con.execute("PRAGMA query_only=OFF")
        self.con.execute("CREATE TABLE qualifications (id TEXT,decision_date TEXT)")
        self.con.execute("CREATE TABLE registry_contracts (supplier_code TEXT,qualification_id TEXT,status TEXT)")
        self.con.execute("INSERT INTO qualifications VALUES ('q1','2026-09-01')")
        self.con.execute("INSERT INTO registry_contracts VALUES ('2','q1','terminated')")
        self.con.commit()
        self.con.execute("PRAGMA query_only=ON")
        item = record("2", 3, day="2026-08-20")
        item["google_prozorro_status"] = "Неактивний"
        with patch.object(audit.edr_sync_v2, "canonical_prozorro_statuses",
                          return_value={"2": "Неактивний"}), \
             patch.object(audit.edr_sync_v2, "active_qualification_dates", return_value={}), \
             patch.object(audit.supplier_registry_integration, "_factual_edr_events", return_value={}):
            result = audit.audit(self.con, request([item]))
        self.assertEqual(result["counts"]["B_before_newer_qualification"], 1)
        self.assertEqual(result["by_google_factual_status"]["Припинено"]
                         ["B_before_newer_qualification_non_active"], 1)
        self.assertEqual(result["pqm_to_google_e_overwrite_risk"]["to_not_current"], 1)
        self.assertEqual(result["db_writes"], 0)

    def test_all_four_special_statuses_have_separate_active_nonactive_buckets(self):
        rows = [record("1", 2, "Припинено"),
                record("2", 3, "В стані припинення"),
                record("3", 4, "Порушено справу про банкрутство"),
                record("4", 5, "Банкрут"), record("missing", 6, "Банкрут")]
        rows[3]["google_prozorro_status"] = "Неактивний"
        with patch.object(audit.edr_sync_v2, "canonical_prozorro_statuses",
                          return_value={"1": "Активний", "2": "Активний",
                                        "3": "Активний", "4": "Неактивний"}), \
             patch.object(audit.edr_sync_v2, "active_qualification_dates",
                          return_value={"1": "2026-09-01", "2": "2026-09-01",
                                        "3": "2026-09-01"}), \
             patch.object(audit.supplier_registry_integration, "_factual_edr_events",
                          return_value={}):
            result = audit.audit(self.con, request(rows))
        for status in ("Припинено", "В стані припинення", "Порушено справу про банкрутство"):
            self.assertEqual(result["by_google_factual_status"][status]
                             ["A_after_latest_qualification_active"], 1)
        self.assertEqual(result["by_google_factual_status"]["Банкрут"]
                         ["review_no_effective_qualification_date_non_active"], 1)
        self.assertEqual(result["by_google_factual_status"]["Банкрут"]
                         ["E_blocked_identity_google_active"], 1)
        self.assertEqual(result["pqm_to_google_e_overwrite_risk"]["unresolved_identity"], 1)
        self.assertEqual(result["counts"]["classified"], 5)

    def test_endpoint_is_sandbox_only_and_uses_existing_bearer_guard(self):
        import server
        replies = []
        handler = SimpleNamespace(path=audit.PATH, command="POST",
            headers={"Authorization": "Bearer synthetic-secret"},
            send_json=lambda body, status=200: replies.append((status, body)))
        handler._authorize_supplier_registry_integration = lambda: (
            server.Handler._authorize_supplier_registry_integration(handler))
        with patch.object(server, "SANDBOX_MODE", True), patch.dict(os.environ, {
                "PQM_SANDBOX_SUPPLIER_REGISTRY_TOKEN": "synthetic-secret"}):
            server.Handler._dispatch(handler, lambda: replies.append((200, "called")))
            self.assertEqual(replies[-1], (200, "called"))
            handler.headers["Authorization"] = "Bearer wrong"
            server.Handler._dispatch(handler, lambda: replies.append((200, "unexpected")))
            self.assertEqual(replies[-1][0], 401)
        with patch.object(server, "SANDBOX_MODE", False):
            server.Handler._dispatch(handler, lambda: replies.append((200, "unexpected")))
            self.assertEqual(replies[-1][0], 404)
        self.assertEqual(server.GOOGLE_FACTUAL_EDR_APPLY_PATH,
                         "/api/integrations/google/factual-edr/apply")

    def test_post_route_opens_ro_query_only_and_returns_zero_writes(self):
        import server
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "synthetic.sqlite3"
            sqlite3.connect(db_path).close()
            body = json.dumps(request([record("1", 2)])).encode("utf-8")
            replies = []
            handler = SimpleNamespace(path=audit.PATH,
                headers={"Content-Length": str(len(body))}, rfile=io.BytesIO(body),
                send_json=lambda data, status=200: replies.append((status, data)))
            with patch.object(server, "SANDBOX_MODE", True), patch.object(server, "DB_PATH", db_path), \
                 patch.object(server.legacy_google_factual_edr_audit, "audit",
                              side_effect=lambda con, payload: {
                                  "received": len(payload["records"]), "db_writes": 0,
                                  "google_writes": 0,
                                  "query_only": con.execute("PRAGMA query_only").fetchone()[0]}):
                server.Handler._do_POST(handler)
            self.assertEqual(replies[0][0], 200)
            self.assertEqual(replies[0][1]["query_only"], 1)
            self.assertEqual(replies[0][1]["db_writes"], 0)

    def test_current_active_status_ignores_legacy_google_status_snapshot(self):
        ledger = [{"id": 1, "event_type": "legacy_google_registry",
                   "occurred_at": "2026-09-20", "snapshot_json": '{"edr_status":"Припинено"}'}]
        self.assertEqual(audit.edr_sync_v2.active_edr_status("2026-09-01", ledger),
                         "Зареєстровано")


if __name__ == "__main__":
    unittest.main()
