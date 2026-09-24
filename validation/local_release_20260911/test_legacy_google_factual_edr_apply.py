"""Bounded factual Google E Apply regressions; SQLite fixtures only."""
import json
import sqlite3
import time
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

import edr_sync_v2
import legacy_google_factual_edr_preview as factual


def item(code, row, status="Припинено", day="2026-09-20", officer="Test Officer"):
    return {"supplier_code": code, "source_tab": "ФОП", "source_row": row,
            "verification_date": day, "verification_officer": officer,
            "factual_edr_status": status, "source": factual.SOURCE, "formulas": []}


def request(items):
    return {"spreadsheet_id": factual.verification.SANDBOX_SPREADSHEET_ID,
            "source_digest": factual.source_digest(items), "records": items}


class FactualEdrApplyTests(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        self.con.execute("""CREATE TABLE supplier_edr_verification_events (
            id INTEGER PRIMARY KEY, supplier_code TEXT,event_type TEXT,occurred_at TEXT,
            officer TEXT,source TEXT,source_submission_id TEXT,source_sheet TEXT,
            source_row INTEGER,changed_fields TEXT,snapshot_hash TEXT,
            snapshot_json TEXT,created_at TEXT)""")
        self.con.execute("CREATE TABLE supplier_edr_profiles (supplier_code TEXT,source_sheet TEXT,"
                         "edr_status TEXT,edr_checked_at TEXT)")
        self.con.execute("INSERT INTO supplier_edr_profiles VALUES ('001','ФОП','Зареєстровано','')")
        self.con.commit()

    def tearDown(self):
        self.con.close()

    def payload(self, rows=None, *, confirmation=factual.APPLY_CONFIRMATION):
        source = request(rows or [item("001", 2)])
        selection = "a" * 64
        return dict(source, selection_digest=selection,
                    preview_ticket=factual.verification._preview_ticket(
                        "factual-e:" + selection, int(time.time()) + 900),
                    confirmation=confirmation)

    def classified(self, payload, category="new_event_needed", digest=None):
        return {"selection_digest": digest or payload["selection_digest"],
                "selected": len(payload["records"]),
                "rows": [{"result": category} for _ in payload["records"]]}

    def test_new_insert_readback_projection_and_replay(self):
        payload = self.payload()
        with patch.object(factual, "preview", return_value=self.classified(payload)):
            result = factual.apply(self.con, payload)
        self.assertEqual((result["inserted"], result["enriched"], result["verified"]), (1, 0, 1))
        self.assertEqual(self.con.execute("SELECT count(*) FROM supplier_edr_verification_events").fetchone()[0], 1)
        row = dict(self.con.execute("SELECT * FROM supplier_edr_verification_events").fetchone())
        self.assertEqual(edr_sync_v2.active_edr_status("2026-09-01", [row]), "Припинено")
        self.assertEqual(edr_sync_v2.active_edr_status("2026-09-21", [row]), "Зареєстровано")
        self.assertEqual(edr_sync_v2.operational_edr_status("Неактивний", "2026-09-01", [row]), "Неактуально")
        self.assertEqual(self.con.execute("SELECT edr_status FROM supplier_edr_profiles").fetchone()[0],
                         "Зареєстровано")
        with patch.object(factual, "preview", return_value=self.classified(payload, digest="b"*64)):
            replay = factual.apply(self.con, payload)
        self.assertEqual(replay["transaction_status"], "ALREADY_APPLIED")
        self.assertEqual(replay["db_writes"], 0)

    def test_real_preview_digest_rechecked_inside_transaction(self):
        payload = self.payload()
        with ExitStack() as stack:
            stack.enter_context(patch.object(factual.supplier_registry_integration,
                "_build_full_registry", return_value={"items": [{
                    "supplier_code": "001", "entity_type": "individual_entrepreneur"}]}))
            stack.enter_context(patch.object(factual.edr_sync_v2,
                "canonical_prozorro_statuses", return_value={"001": "Активний"}))
            stack.enter_context(patch.object(factual.edr_sync_v2,
                "active_qualification_dates", return_value={"001": "2026-09-01"}))
            stack.enter_context(patch.object(factual.legacy_google_factual_edr_audit,
                "_historical_qualification_dates", return_value={}))
            stack.enter_context(patch.object(factual.edr_sync_v2,
                "current_verification_projections", return_value={"001": {
                    "verification_date": "2026-09-01", "verification_officer": ""}}))
            self.con.execute("PRAGMA query_only=ON")
            fresh = factual.preview(self.con, {key: payload[key] for key in factual.REQUEST_KEYS})
            self.con.execute("PRAGMA query_only=OFF")
            payload["selection_digest"] = fresh["selection_digest"]
            payload["preview_ticket"] = fresh["preview_ticket"]
            self.assertEqual(fresh["new_event_needed"], 1)
            applied = factual.apply(self.con, payload)
        self.assertEqual((applied["inserted"], applied["verified"]), (1, 1))

    def test_existing_il_event_enriched_not_duplicated(self):
        payload = self.payload()
        old = {"verification_date": "2026-09-20", "verification_officer": "Test Officer",
               "source": factual.SOURCE, "source_tab": "ФОП", "source_row": 2,
               "source_digest": "c"*64, "spreadsheet_id": payload["spreadsheet_id"]}
        self.con.execute("""INSERT INTO supplier_edr_verification_events
            (supplier_code,event_type,occurred_at,officer,source,source_sheet,source_row,
             changed_fields,snapshot_hash,snapshot_json) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            ("001", factual.SOURCE, "2026-09-20", "Test Officer", factual.SOURCE,
             "ФОП", 2, '["verification_date","verification_officer"]', "k",
             json.dumps(old, ensure_ascii=False)))
        self.con.commit()
        with patch.object(factual, "preview", return_value=self.classified(
                payload, "existing_event_enrichment")):
            result = factual.apply(self.con, payload)
        self.assertEqual((result["inserted"], result["enriched"]), (0, 1))
        self.assertEqual(self.con.execute("SELECT count(*) FROM supplier_edr_verification_events").fetchone()[0], 1)
        row = dict(self.con.execute("SELECT * FROM supplier_edr_verification_events").fetchone())
        snapshot = json.loads(row["snapshot_json"])
        self.assertEqual(snapshot["source_digest"], "c"*64)
        self.assertEqual(snapshot["factual_source_digest"], payload["source_digest"])
        self.assertEqual(edr_sync_v2.active_edr_status("2026-09-01", [row]), "Припинено")

    def test_rejects_limit_status_confirmation_ticket_and_stale(self):
        with self.assertRaisesRegex(ValueError, "FACTUAL_PREVIEW_LIMIT"):
            factual.apply(self.con, self.payload([item(str(i), i+2) for i in range(11)]))
        for bad in ("Неактуально", "Зареєстровано", "unknown"):
            with self.assertRaisesRegex(ValueError, "FACTUAL_PREVIEW_ITEM_INVALID"):
                factual.apply(self.con, self.payload([item("001", 2, status=bad)]))
        with self.assertRaisesRegex(ValueError, "EXPLICIT_CONFIRMATION_REQUIRED"):
            factual.apply(self.con, self.payload(confirmation=""))
        payload = self.payload()
        payload["preview_ticket"] = "bad"
        with self.assertRaisesRegex(ValueError, "PREVIEW_TICKET_INVALID_OR_EXPIRED"):
            factual.apply(self.con, payload)
        payload = self.payload()
        payload["preview_ticket"] = factual.verification._preview_ticket(
            "factual-e:" + payload["selection_digest"], int(time.time()) - 1)
        with self.assertRaisesRegex(ValueError, "PREVIEW_TICKET_INVALID_OR_EXPIRED"):
            factual.apply(self.con, payload)
        payload = self.payload()
        payload["records"][0]["factual_edr_status"] = "Банкрут"
        with self.assertRaisesRegex(ValueError, "FACTUAL_PREVIEW_DIGEST_MISMATCH"):
            factual.apply(self.con, payload)
        payload = self.payload()
        with patch.object(factual, "preview", return_value=self.classified(payload, digest="b"*64)):
            with self.assertRaisesRegex(ValueError, "STALE_PREVIEW_OR_PQM_STATE"):
                factual.apply(self.con, payload)
        self.assertEqual(self.con.execute("SELECT count(*) FROM supplier_edr_verification_events").fetchone()[0], 0)

    def test_rollback_all_after_readback_or_protected_state_failure(self):
        rows = [item("001", 2), item("002", 3)]
        payload = self.payload(rows)
        with patch.object(factual, "preview", return_value=self.classified(payload)):
            with self.assertRaisesRegex(ValueError, "AFTER_VERIFICATION_FAILED"):
                factual.apply(self.con, payload,
                    after_write_hook=lambda con: con.execute(
                        "UPDATE supplier_edr_verification_events SET snapshot_json='{}' WHERE supplier_code='002'"))
        self.assertEqual(self.con.execute("SELECT count(*) FROM supplier_edr_verification_events").fetchone()[0], 0)
        with patch.object(factual, "preview", return_value=self.classified(payload)):
            with self.assertRaisesRegex(ValueError, "PROTECTED_STATE_CHANGED"):
                factual.apply(self.con, payload,
                    after_write_hook=lambda con: con.execute(
                        "UPDATE supplier_edr_profiles SET edr_status='Припинено'"))
        self.assertEqual(self.con.execute("SELECT count(*) FROM supplier_edr_verification_events").fetchone()[0], 0)
        self.assertEqual(self.con.execute("SELECT edr_status FROM supplier_edr_profiles").fetchone()[0],
                         "Зареєстровано")

    def test_equivalent_is_no_write_and_apply_route_is_sandbox_authenticated(self):
        payload = self.payload()
        with patch.object(factual, "preview", return_value=self.classified(
                payload, "equivalent_factual_evidence")):
            with self.assertRaisesRegex(ValueError, "SELECTION_NOT_FULLY_ELIGIBLE"):
                factual.apply(self.con, payload)
        self.assertEqual(self.con.total_changes, 1)  # Only setUp profile fixture.
        import server
        replies = []
        handler = SimpleNamespace(path=factual.APPLY_PATH, command="POST",
            headers={"Authorization": "Bearer synthetic-secret"},
            send_json=lambda data, status=200: replies.append((status, data)))
        handler._authorize_supplier_registry_integration = lambda: (
            server.Handler._authorize_supplier_registry_integration(handler))
        with patch.object(server, "SANDBOX_MODE", False):
            server.Handler._dispatch(handler, lambda: replies.append((200, "unexpected")))
        self.assertEqual(replies[-1][0], 404)
        with patch.object(server, "SANDBOX_MODE", True), patch.dict(
                "os.environ", {"PQM_SANDBOX_SUPPLIER_REGISTRY_TOKEN": "synthetic-secret"}):
            server.Handler._dispatch(handler, lambda: replies.append((200, "called")))
            self.assertEqual(replies[-1], (200, "called"))
            handler.headers["Authorization"] = "Bearer wrong"
            server.Handler._dispatch(handler, lambda: replies.append((200, "unexpected")))
            self.assertEqual(replies[-1][0], 401)


if __name__ == "__main__":
    unittest.main()
