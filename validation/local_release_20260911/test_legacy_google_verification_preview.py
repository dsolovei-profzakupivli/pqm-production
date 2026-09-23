"""Synthetic read-only Google-initiated verification Preview contract."""
import io
import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace

import legacy_google_verification_preview as preview


def item(code="001", tab="ФОП", row=2, day="2026-09-23", officer="Олена ЄРЬОМІНА"):
    return {"supplier_code": code, "source_tab": tab, "source_row": row,
            "verification_date": day, "verification_officer": officer,
            "source": preview.SOURCE}


def request(items):
    items = sorted(items, key=lambda x: (x["source_tab"], x["source_row"], x["supplier_code"]))
    return {"spreadsheet_id": preview.SANDBOX_SPREADSHEET_ID,
            "source_digest": preview.source_digest(items), "records": items}


class LegacyGoogleVerificationPreviewTests(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        self.con.execute("CREATE TABLE supplier_edr_verification_events "
                         "(supplier_code TEXT,occurred_at TEXT,officer TEXT)")
        self.registry = {"001": "individual_entrepreneur", "002": "legal_entity",
                         "003": "legal_entity", "004": "legal_entity", "005": "legal_entity"}
        self.dates = {"001": "2026-09-22", "002": "", "003": "2026-09-23",
                      "004": "2026-09-24", "005": "2026-09-22"}
        self.registry_patch = patch.object(preview.supplier_registry_integration,
            "_build_full_registry", side_effect=lambda con: {"items": [
                {"supplier_code": code, "entity_type": kind} for code, kind in self.registry.items()]})
        self.projection_patch = patch.object(preview.edr_sync_v2,
            "current_verification_projections", side_effect=lambda con, codes: {
                code: {"verification_date": self.dates[code]} for code in codes if code in self.dates})
        self.registry_patch.start()
        self.projection_patch.start()

    def tearDown(self):
        self.registry_patch.stop()
        self.projection_patch.stop()
        self.con.close()

    def test_js_python_digest_parity_and_preview_categories(self):
        self.assertEqual(preview.source_digest([item()]),
                         "1b7c8b78b545e2d2df2524d9141f48aad28d749da9f788633fe2c0e821a3d5c8")
        items = [item(), item("002", "ЮО", 2, "2026-09-23", "Officer B"),
                 item("003", "ЮО", 3, "2026-09-23", "Officer C"),
                 item("004", "ЮО", 4, "2026-09-23", "Officer D"),
                 item("005", "ЮО", 5, "2026-09-23", "Officer E")]
        result = preview.preview(self.con, request(items))
        self.assertEqual([result[k] for k in ("incoming_newer", "initial", "same_date", "older")],
                         [2, 1, 1, 1])
        self.assertEqual((result["db_writes"], result["google_writes"]), (0, 0))
        self.assertNotIn("supplier_code", result["rows"][0])
        self.assertNotIn("verification_officer", result["rows"][0])

    def test_equivalent_event_and_ambiguous_identity(self):
        self.con.execute("INSERT INTO supplier_edr_verification_events VALUES (?,?,?)",
                         ("001", "2026-09-23", "олена єрьоміна"))
        self.con.commit()
        result = preview.preview(self.con, request([item()]))
        self.assertEqual(result["equivalent_event"], 1)
        result = preview.preview(self.con, request([item(), item(row=3)]))
        self.assertEqual(result["ambiguous"], 2)
        self.registry.pop("001")
        result = preview.preview(self.con, request([item()]))
        self.assertEqual(result["ambiguous"], 1)

    def test_invalid_officer_date_routing_and_extra_fields(self):
        bad = [item("001", "ФОП", 2, "bad", "Officer"),
               item("002", "ЮО", 2, "2026-09-23", "—"),
               item("003", "ФОП", 3, "2026-09-23", "Officer")]
        result = preview.preview(self.con, request(bad))
        self.assertEqual(result["blocked"], 3)
        tampered = request([item()])
        tampered["records"][0]["edr_status"] = "Зареєстровано"
        with self.assertRaisesRegex(ValueError, "ITEM_SCHEMA_INVALID"):
            preview.preview(self.con, tampered)

    def test_wrong_sheet_digest_size_and_literal_identity(self):
        payload = request([item()])
        payload["spreadsheet_id"] = "wrong"
        with self.assertRaisesRegex(ValueError, "SANDBOX_SPREADSHEET_MISMATCH"):
            preview.validate_request(payload)
        payload = request([item()])
        payload["records"][0]["verification_officer"] = "changed"
        with self.assertRaisesRegex(ValueError, "SOURCE_DIGEST_MISMATCH"):
            preview.validate_request(payload)
        with self.assertRaisesRegex(ValueError, "CONTROLLED_PREVIEW_LIMIT"):
            preview.validate_request(request([item(str(i), "ФОП", i + 2) for i in range(11)]))
        self.assertEqual(preview.preview(self.con, request([item("UA-001")]))["ambiguous"], 1)

    def test_pqm_state_recheck_is_current(self):
        payload = request([item()])
        self.assertEqual(preview.preview(self.con, payload)["incoming_newer"], 1)
        self.dates["001"] = "2026-09-24"
        self.assertEqual(preview.preview(self.con, payload)["older"], 1)

    def test_read_only_connection_rejects_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "synthetic.sqlite3"
            writable = sqlite3.connect(db_path)
            try:
                writable.execute("CREATE TABLE fixture (value TEXT)")
                writable.commit()
            finally:
                writable.close()
            readonly = preview.open_read_only(db_path)
            try:
                self.assertEqual(readonly.execute("PRAGMA query_only").fetchone()[0], 1)
                with self.assertRaises(sqlite3.OperationalError):
                    readonly.execute("INSERT INTO fixture VALUES ('no')")
            finally:
                readonly.close()

    def test_endpoint_is_sandbox_only_and_bearer_protected(self):
        import server
        replies = []
        handler = SimpleNamespace(path=preview.PATH, command="POST",
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

    def test_post_handler_uses_read_only_db_and_returns_zero_writes(self):
        import server
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "synthetic.sqlite3"
            sqlite3.connect(db_path).close()
            body = json.dumps(request([item()])).encode("utf-8")
            replies = []
            handler = SimpleNamespace(path=preview.PATH,
                headers={"Content-Length": str(len(body))}, rfile=io.BytesIO(body),
                send_json=lambda data, status=200: replies.append((status, data)))
            with patch.object(server, "DB_PATH", db_path), patch.object(
                    server.legacy_google_verification_preview, "preview",
                    side_effect=lambda con, payload: {
                        "received": len(payload["records"]), "db_writes": 0, "google_writes": 0,
                        "db_query_only_during_preview": con.execute("PRAGMA query_only").fetchone()[0]}):
                server.Handler._do_POST(handler)
            self.assertEqual(replies[0][0], 200)
            self.assertEqual(replies[0][1]["db_query_only_during_preview"], 1)
            self.assertEqual(replies[0][1]["query_only"], 1)
            self.assertEqual(replies[0][1]["db_writes"], 0)


if __name__ == "__main__":
    unittest.main()
