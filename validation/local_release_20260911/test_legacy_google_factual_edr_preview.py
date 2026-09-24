"""Synthetic read-only Google factual E Preview and status projection regressions."""
from contextlib import ExitStack
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import edr_sync_v2
import legacy_google_factual_edr_preview as preview


def item(code, row, status="Припинено", day="2026-09-20", officer="Test Officer"):
    return {"supplier_code": code, "source_tab": "ФОП", "source_row": row,
            "verification_date": day, "verification_officer": officer,
            "factual_edr_status": status, "source": preview.SOURCE, "formulas": []}


def request(items):
    return {"spreadsheet_id": preview.verification.SANDBOX_SPREADSHEET_ID,
            "source_digest": preview.source_digest(items), "records": items}


def event(code, day="2026-09-20", status=None, kind="legacy_google_registry",
          officer="Test Officer", event_id=1):
    if kind == "legacy_google_registry":
        snapshot = {"verification_date": day, "verification_officer": officer,
                    "source": kind, "source_tab": "ФОП", "source_row": 2,
                    "source_digest": "a"*64}
        if status is not None:
            snapshot.update(factual_edr_status=status, factual_source_digest="b"*64)
    else:
        snapshot = {"edr_status": status} if status is not None else {}
    return (event_id, code, kind, day, officer, kind, "ФОП" if kind == "legacy_google_registry" else "",
            2 if kind == "legacy_google_registry" else 0, json.dumps(snapshot, ensure_ascii=False))


def legacy_ledger(status, day="2026-09-20"):
    keys = ("id", "supplier_code", "event_type", "occurred_at", "officer", "source",
            "source_sheet", "source_row", "snapshot_json")
    return dict(zip(keys, event("001", day=day, status=status)))


class FactualEdrPreviewTests(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        self.con.execute("CREATE TABLE supplier_edr_profiles (supplier_code TEXT,source_sheet TEXT,"
                         "edr_status TEXT,edr_checked_at TEXT)")
        self.con.execute("CREATE TABLE supplier_edr_verification_events (id INTEGER,supplier_code TEXT,"
                         "event_type TEXT,occurred_at TEXT,officer TEXT,source TEXT,source_sheet TEXT,"
                         "source_row INTEGER,snapshot_json TEXT)")
        self.con.commit()
        self.con.execute("PRAGMA query_only=ON")

    def tearDown(self):
        self.con.close()

    def preview(self, items, *, statuses=None, current=None, historical=None):
        codes = [x["supplier_code"] for x in items]
        identities = {code: {"supplier_code": code, "entity_type": "individual_entrepreneur"}
                      for code in codes}
        with ExitStack() as stack:
            stack.enter_context(patch.object(preview.supplier_registry_integration,
                                             "_build_full_registry",
                                             return_value={"items": list(identities.values())}))
            stack.enter_context(patch.object(preview.edr_sync_v2, "canonical_prozorro_statuses",
                                             return_value=statuses or {code: "Активний" for code in codes}))
            stack.enter_context(patch.object(preview.edr_sync_v2, "active_qualification_dates",
                                             return_value=current if current is not None else
                                             {code: "2026-09-01" for code in codes}))
            stack.enter_context(patch.object(preview.legacy_google_factual_edr_audit,
                                             "_historical_qualification_dates",
                                             return_value=historical or {}))
            stack.enter_context(patch.object(preview.edr_sync_v2, "current_verification_projections",
                                             return_value={code: {"verification_date": "2026-09-01",
                                                                       "verification_officer": ""}
                                                           for code in codes}))
            return preview.preview(self.con, request(items))

    def insert(self, *events):
        self.con.execute("PRAGMA query_only=OFF")
        self.con.executemany("INSERT INTO supplier_edr_verification_events VALUES (?,?,?,?,?,?,?,?,?)", events)
        self.con.commit()
        self.con.execute("PRAGMA query_only=ON")

    def test_new_enrichment_equivalent_and_newer_block_are_read_only(self):
        rows = [item("001", 2), item("002", 3), item("003", 4), item("004", 5)]
        self.insert(event("002", event_id=2), event("003", status="Припинено", event_id=3),
                    event("004", day="2026-09-21", status="Зареєстровано",
                          kind="manual_edr", event_id=4))
        before = self.con.total_changes
        result = self.preview(rows)
        self.assertEqual(result["new_event_needed"], 1)
        self.assertEqual(result["existing_event_enrichment"], 1)
        self.assertEqual(result["equivalent_factual_evidence"], 1)
        self.assertEqual(result["by_reason"]["newer_pqm_factual_evidence"], 1)
        self.assertEqual(result["selected"], 2)
        self.assertEqual(result["by_status_reason"]["Припинено:existing_event_enrichment"], 1)
        self.assertTrue(result["selection_digest"] and result["preview_ticket"])
        self.assertEqual((result["db_writes"], result["google_writes"],
                          result["query_only"], self.con.total_changes-before), (0, 0, 1, 0))
        self.assertNotIn("Test Officer", str(result))
        self.assertNotIn("001", str(result))

    def test_nonactive_evidence_is_historical_and_profile_newer_blocks(self):
        rows = [item("001", 2), item("002", 3)]
        self.con.execute("PRAGMA query_only=OFF")
        self.con.execute("INSERT INTO supplier_edr_profiles VALUES (?,?,?,?)",
                         ("002", "ФОП", "Зареєстровано", "2026-09-21"))
        self.con.commit(); self.con.execute("PRAGMA query_only=ON")
        result = self.preview(rows, statuses={"001": "Неактивний", "002": "Неактивний"},
                              current={}, historical={"001": "2026-09-01", "002": "2026-09-01"})
        self.assertEqual(result["new_event_needed"], 1)
        self.assertEqual(result["by_reason"]["newer_or_same_profile_factual_evidence"], 1)
        self.assertEqual(result["by_activity_reason"]["non_active:new_event_needed"], 1)

    def test_bad_status_tamper_limit_and_query_only_fail_closed(self):
        for status in ("Неактуально", "Зареєстровано", "Невідомо"):
            with self.assertRaisesRegex(ValueError, "FACTUAL_PREVIEW_ITEM_INVALID"):
                self.preview([item("001", 2, status=status)])
        body = request([item("001", 2)])
        body["records"][0]["factual_edr_status"] = "Банкрут"
        with self.assertRaisesRegex(ValueError, "FACTUAL_PREVIEW_DIGEST_MISMATCH"):
            preview.validate(body)
        with self.assertRaisesRegex(ValueError, "FACTUAL_PREVIEW_LIMIT"):
            preview.validate(request([item(str(i), i+2) for i in range(11)]))
        self.con.execute("PRAGMA query_only=OFF")
        with self.assertRaisesRegex(ValueError, "QUERY_ONLY_REQUIRED"):
            self.preview([item("001", 2)])

    def test_legacy_projection_status_vocabulary_and_chronology(self):
        for status in sorted(edr_sync_v2.LEGACY_GOOGLE_FACTUAL_STATUSES):
            ledger = [legacy_ledger(status)]
            self.assertEqual(edr_sync_v2.active_edr_status("2026-09-01", ledger), status)
            self.assertEqual(edr_sync_v2.active_edr_status("2026-09-21", ledger), "Зареєстровано")
            self.assertEqual(edr_sync_v2.operational_edr_status("Неактивний", "2026-09-01", ledger),
                             "Неактуально")
        for bad in (None, "Неактуально", "Зареєстровано", "Невідомо"):
            ledger = [legacy_ledger(bad)]
            self.assertEqual(edr_sync_v2.active_edr_status("2026-09-01", ledger), "Зареєстровано")
        missing_provenance = legacy_ledger("Припинено")
        missing_provenance["snapshot_json"] = json.dumps({"factual_edr_status": "Припинено"},
                                                         ensure_ascii=False)
        self.assertEqual(edr_sync_v2.active_edr_status("2026-09-01", [missing_provenance]),
                         "Зареєстровано")
        self.assertEqual(edr_sync_v2.active_edr_status("2026-09-01", [
            legacy_ledger("Припинено"),
            {"id": 2, "event_type": "manual_edr", "occurred_at": "2026-09-20",
             "snapshot_json": '{"edr_status":"Зареєстровано"}'}]), "Зареєстровано")

    def test_ui_and_full_registry_share_legacy_factual_ledger_status(self):
        self.insert(event("001", status="Припинено"), event("002", status=None, event_id=2))
        rows = [dict(row) for row in self.con.execute("SELECT * FROM supplier_edr_verification_events")]
        api = preview.supplier_registry_integration._factual_edr_events(self.con, ["001", "002"])
        for code, expected in (("001", "Припинено"), ("002", "Зареєстровано")):
            ui_ledger = [row for row in rows if row["supplier_code"] == code]
            self.assertEqual(edr_sync_v2.active_edr_status("2026-09-01", ui_ledger), expected)
            self.assertEqual(edr_sync_v2.active_edr_status("2026-09-01", api[code]), expected)

    def test_endpoint_uses_existing_sandbox_bearer_and_ro_connection(self):
        import server
        replies = []
        handler = SimpleNamespace(path=preview.PATH, command="POST",
            headers={"Authorization": "Bearer synthetic-secret"},
            send_json=lambda data, status=200: replies.append((status, data)))
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
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "fixture.sqlite3"
            sqlite3.connect(db_path).close()
            body = json.dumps(request([item("001", 2)])).encode("utf-8")
            handler = SimpleNamespace(path=preview.PATH, headers={"Content-Length": str(len(body))},
                rfile=io.BytesIO(body), send_json=lambda data, status=200: replies.append((status, data)))
            with patch.object(server, "SANDBOX_MODE", True), patch.object(server, "DB_PATH", db_path), \
                 patch.object(server.legacy_google_factual_edr_preview, "preview",
                              side_effect=lambda con, payload: {
                                  "db_writes": 0, "google_writes": 0,
                                  "query_only": con.execute("PRAGMA query_only").fetchone()[0]}):
                server.Handler._do_POST(handler)
            self.assertEqual(replies[-1], (200, {"db_writes": 0, "google_writes": 0, "query_only": 1}))


if __name__ == "__main__":
    unittest.main()
