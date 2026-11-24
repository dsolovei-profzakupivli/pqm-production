import json
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from io import BytesIO
from datetime import datetime
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import auth_access
import server


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


class GoogleRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db_path = self.root / "runtime.sqlite3"
        self.token_path = self.root / "oauth" / "token.json"
        def attest_test_database(path, **_kwargs):
            if Path(path).resolve() != self.db_path.resolve():
                raise RuntimeError("Test Sandbox route targeted a database outside its temporary fixture")
        self.sandbox_runtime_patch = patch.object(
            server, "sandbox_runtime",
            SimpleNamespace(attest_internal_target=attest_test_database), create=True)
        self.sandbox_runtime_patch.start()
        self.addCleanup(self.sandbox_runtime_patch.stop)
        with sqlite3.connect(self.db_path) as con:
            con.execute("""CREATE TABLE audit_log(id INTEGER PRIMARY KEY AUTOINCREMENT,submission_id TEXT,
              changed_at TEXT NOT NULL,changed_by TEXT NOT NULL,field_name TEXT NOT NULL,old_value TEXT,new_value TEXT)""")
            con.execute("""CREATE TABLE supplier_edr_sync_log(id INTEGER PRIMARY KEY AUTOINCREMENT,
              started_at TEXT NOT NULL,finished_at TEXT,status TEXT NOT NULL,processed INTEGER DEFAULT 0,
              inserted INTEGER DEFAULT 0,updated INTEGER DEFAULT 0,error TEXT DEFAULT '')""")
            auth_access.migrate(con)
            server.ensure_runtime_feature_settings(con)
            server.ensure_google_oauth_transactions(con)

    def request(self, path, role="admin", payload=None):
        http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        try:
            data = None if payload is None else json.dumps(payload).encode()
            request = urllib.request.Request(
                f"http://127.0.0.1:{http.server_port}{path}", data=data,
                headers={"Content-Type": "application/json", "X-PQM-Local-Role": role},
                method="POST" if payload is not None else "GET")
            try:
                response = urllib.request.urlopen(request, timeout=5)
            except urllib.error.HTTPError as exc:
                response = exc
            with response:
                return response.status, json.load(response)
        finally:
            http.shutdown(); http.server_close(); thread.join()

    def request_bytes(self, path, payload, role="admin"):
        http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{http.server_port}{path}", data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json", "X-PQM-Local-Role": role}, method="POST")
            try:
                response = urllib.request.urlopen(request, timeout=5)
            except urllib.error.HTTPError as exc:
                response = exc
            with response:
                return response.status, dict(response.headers), response.read()
        finally:
            http.shutdown(); http.server_close(); thread.join()

    def common_patches(self):
        return (
            patch.object(server, "DB_PATH", self.db_path),
            patch.object(server, "GOOGLE_OAUTH_TOKEN_PATH", self.token_path),
            patch.object(server, "AUTH_ENABLED", False),
            patch.object(server, "LOCAL_ROLE_IMPERSONATION", True),
        )

    def test_runtime_override_persists_is_audited_and_does_not_start_work(self):
        with sqlite3.connect(self.db_path) as con:
            con.execute("""INSERT INTO runtime_feature_settings(feature_key,enabled,updated_at,updated_by)
              VALUES ('manual_bids_update',0,'before','test')""")
        scheduler_before = set(server.REGISTERED_SCHEDULER_JOBS)
        powerbi_before = server.ENABLE_POWERBI
        patches = self.common_patches()
        with patches[0], patches[1], patches[2], patches[3], \
             patch.object(server, "ENABLE_GOOGLE", False), \
             patch.object(server, "_google_oauth_client", return_value=None), \
             patch.object(server, "_google_oauth_token", return_value=None), \
             patch.object(server, "supplier_edr_sync_worker") as edr_worker, \
             patch.object(server, "supplier_nazk_review_sync_worker") as nazk_worker:
            self.assertFalse(server.google_runtime_state()["enabled"])
            status, result = self.request("/api/admin/runtime-features/google", payload={"enabled": True})
            self.assertEqual(status, 200)
            self.assertTrue(result["feature"]["enabled"])
            self.assertEqual(result["feature"]["configuration_source"], "runtime")
            self.assertTrue(server.google_runtime_state()["enabled"])
            self.assertEqual(self.request("/api/admin/runtime-features/google", "viewer", {"enabled": False})[0], 403)
            status, result = self.request("/api/admin/runtime-features/google", payload={"enabled": False})
            self.assertEqual(status, 200)
            self.assertFalse(result["feature"]["enabled"])
            edr_worker.assert_not_called(); nazk_worker.assert_not_called()
        with sqlite3.connect(self.db_path) as con:
            row = con.execute("SELECT enabled FROM runtime_feature_settings WHERE feature_key=?",
                              (server.GOOGLE_RUNTIME_FEATURE_KEY,)).fetchone()
            events = con.execute("SELECT old_value,new_value FROM audit_log WHERE submission_id=? ORDER BY id",
                                 (f"runtime_feature:{server.GOOGLE_RUNTIME_FEATURE_KEY}",)).fetchall()
        self.assertEqual(row[0], 0)
        self.assertEqual(events, [("disabled", "enabled"), ("enabled", "disabled")])
        with sqlite3.connect(self.db_path) as con:
            self.assertEqual(con.execute("SELECT enabled FROM runtime_feature_settings WHERE feature_key='manual_bids_update'").fetchone()[0], 0)
        self.assertEqual(set(server.REGISTERED_SCHEDULER_JOBS), scheduler_before)
        self.assertEqual(server.ENABLE_POWERBI, powerbi_before)

    def test_disabled_is_fail_closed_for_oauth_and_both_sync_routes(self):
        patches = self.common_patches()
        with patches[0], patches[1], patches[2], patches[3], \
             patch.object(server, "ENABLE_GOOGLE", False), \
             patch.object(server, "supplier_edr_sync_worker") as edr_worker, \
             patch.object(server, "supplier_nazk_review_sync_worker") as nazk_worker:
            with self.assertRaises(PermissionError):
                server._google_sheet_values("ФОП")
            self.assertEqual(self.request("/api/google-oauth/start", payload={})[0], 403)
            self.assertEqual(self.request("/api/supplier-edr-sync", payload={})[0], 403)
            self.assertEqual(self.request("/api/supplier-nazk-review-sync", payload={})[0], 403)
            edr_worker.assert_not_called(); nazk_worker.assert_not_called()

    def test_permanent_edr_preview_and_apply_keep_confirmed_fingerprint(self):
        fingerprint = "a" * 64
        state_digest = "b" * 64
        patches = self.common_patches()
        with patches[0], patches[1], patches[2], patches[3], \
             patch.object(server, "google_effective_enabled", return_value=True), \
             patch.object(server, "supplier_edr_sync_preview",
                          return_value={"source_fingerprint": fingerprint,
                                        "state_digest": state_digest, "summary": {}}), \
             patch.object(server, "supplier_edr_source_snapshot",
                          return_value={"source_fingerprint": fingerprint}), \
             patch.object(server.edr_sync_v2, "build_preview",
                          return_value={"conflicts": []}), \
             patch.object(server.edr_sync_v2, "preview_state_digest",
                          return_value=state_digest), \
             patch.object(server, "supplier_edr_sync_worker") as worker:
            status, preview = self.request("/api/supplier-edr-sync/preview", payload={})
            self.assertEqual(status, 200)
            self.assertEqual(preview["source_fingerprint"], fingerprint)
            self.assertEqual(self.request("/api/supplier-edr-sync", payload={"confirmed": False,
                "source_fingerprint": fingerprint})[0], 409)
            status, result = self.request("/api/supplier-edr-sync", payload={"confirmed": True,
                "source_fingerprint": fingerprint})
            self.assertEqual(status, 409)
            status, result = self.request("/api/supplier-edr-sync", payload={"confirmed": True,
                "source_fingerprint": fingerprint, "state_digest": state_digest})
            self.assertEqual(status, 202)
            self.assertTrue(result["started"])
            for _ in range(100):
                if worker.called:
                    break
                threading.Event().wait(0.01)
            worker.assert_called_once()
            self.assertEqual(worker.call_args.args[0], fingerprint)
            self.assertEqual(worker.call_args.args[2], state_digest)
            server.SUPPLIER_EDR_SYNC_STATE.update(running=False)

    def test_sandbox_apply_starts_with_conflicts_only_when_ready_and_preview_is_current(self):
        fingerprint = "a" * 64
        digest = "b" * 64
        current_plan = {"conflicts": [{"supplier_code": "1", "source_row": 2,
                                      "reasons": ["same_timestamp_verification_conflict"]}],
                        "summary": {"eligible": 1}}
        with patch.object(server, "DB_PATH", self.db_path), \
             patch.object(server, "AUTH_ENABLED", False), \
             patch.object(server, "LOCAL_ROLE_IMPERSONATION", True), \
             patch.object(server, "SANDBOX_MODE", True), \
             patch.object(server, "google_edr_effective_enabled", return_value=True), \
             patch.object(server, "supplier_edr_source_snapshot",
                          return_value={"source_fingerprint": fingerprint}), \
             patch.object(server.edr_sync_v2, "build_preview", return_value=current_plan), \
             patch.object(server.edr_sync_v2, "preview_state_digest", return_value=digest), \
             patch.object(server, "supplier_edr_sync_worker") as worker:
            payload = {"confirmed": True, "source_fingerprint": fingerprint, "state_digest": digest}
            status, result = self.request("/api/supplier-edr-sync", payload=payload)
            self.assertEqual(status, 202)
            self.assertTrue(result["started"])
            worker.assert_called_once_with(fingerprint, server.CURRENT_USER, digest)
            server.SUPPLIER_EDR_SYNC_STATE.update(running=False)

            current_plan["conflicts"] = []
            status, result = self.request("/api/supplier-edr-sync", payload=payload)
            self.assertEqual(status, 202)
            self.assertEqual(worker.call_count, 2)
            server.SUPPLIER_EDR_SYNC_STATE.update(running=False)
            current_plan["conflicts"] = [{"supplier_code": "1", "source_row": 2,
                                           "reasons": ["same_timestamp_verification_conflict"]}]

            current_plan["summary"]["eligible"] = 0
            status, result = self.request("/api/supplier-edr-sync", payload=payload)
            self.assertEqual(status, 409)
            self.assertIn("Немає готових", result["error"])
            self.assertEqual(worker.call_count, 2)

            current_plan["summary"]["eligible"] = 1
            with patch.object(server.edr_sync_v2, "preview_state_digest", return_value="c" * 64):
                status, result = self.request("/api/supplier-edr-sync", payload=payload)
            self.assertEqual(status, 409)
            self.assertIn("Стан PQM змінився", result["error"])
            self.assertEqual(worker.call_count, 2)
            with patch.object(server, "supplier_edr_source_snapshot",
                              return_value={"source_fingerprint": "c" * 64}):
                status, result = self.request("/api/supplier-edr-sync", payload=payload)
            self.assertEqual(status, 409)
            self.assertIn("Google source змінився", result["error"])
            self.assertEqual(worker.call_count, 2)
            server.SUPPLIER_EDR_SYNC_STATE.update(running=False)

    def test_conflict_xlsx_http_export_contains_all_preview_conflicts(self):
        from openpyxl import load_workbook

        fingerprint = "a" * 64
        digest = "b" * 64
        items, conflicts = [], []
        for index in range(31):
            code = f"{index:010d}"
            pqm_checked = None if index == 1 else "2026-11-23" if index == 0 else "2026-11-23T16:00:00Z"
            google_checked = None if index == 1 else "2026-11-23T17:04:26Z" if index == 0 else "23.11.2026 00:00:00"
            items.append({"supplier_code": code, "source_row": index + 2,
                          "source_sheet": "ФОП", "current_profile": {"edr_status": "PQM"},
                          "current_supplier_name": "Постачальник", "current_verification_date": pqm_checked,
                          "current_verification_officer": "УО PQM",
                          "incoming": {"source_sheet": "ФОП", "full_name": "Google name",
                                       "edr_status": "Google", "edr_checked_at": google_checked,
                                       "edr_officer": "УО Google"}})
            conflicts.append({"supplier_code": code, "source_row": index + 2,
                              "reasons": ["same_timestamp_verification_conflict"]})
        preview = {"items": items, "conflicts": conflicts}
        with patch.object(server, "DB_PATH", self.db_path), \
             patch.object(server, "AUTH_ENABLED", False), \
             patch.object(server, "LOCAL_ROLE_IMPERSONATION", True), \
             patch.object(server, "SANDBOX_MODE", True), \
             patch.object(server, "google_edr_effective_enabled", return_value=True), \
             patch.object(server, "supplier_edr_source_snapshot",
                          return_value={"source_fingerprint": fingerprint}), \
             patch.object(server.edr_sync_v2, "build_preview", return_value=preview), \
             patch.object(server.edr_sync_v2, "preview_state_digest", return_value=digest):
            status, headers, body = self.request_bytes("/api/supplier-edr-sync/conflicts.xlsx",
                {"source_fingerprint": fingerprint, "state_digest": digest})
        self.assertEqual(status, 200)
        self.assertIn("spreadsheetml.sheet", headers.get("Content-Type", ""))
        workbook = load_workbook(BytesIO(body), read_only=False)
        sheet = workbook.active
        self.assertEqual(sheet.max_row, 32)
        self.assertEqual(sheet.freeze_panes, "A2")
        self.assertEqual(sheet.auto_filter.ref, "A1:L32")
        self.assertEqual(sheet.cell(2, 2).value, "0000000000")
        self.assertEqual(sheet.cell(2, 2).number_format, "@")
        self.assertEqual(sheet.cell(32, 2).value, "0000000030")
        self.assertEqual(sheet.cell(2, 4).value, "Фактичні дані ЄДР відрізняються за однакового часу перевірки")
        self.assertIsInstance(sheet.cell(2, 8).value, datetime)
        self.assertEqual(sheet.cell(2, 8).value, datetime(2026, 11, 23, 0, 0, 0))
        self.assertEqual(sheet.cell(2, 9).value, datetime(2026, 11, 23, 19, 4, 26))
        self.assertEqual(sheet.cell(2, 8).number_format, "dd.mm.yyyy hh:mm:ss")
        self.assertEqual(sheet.cell(2, 9).number_format, "dd.mm.yyyy hh:mm:ss")
        self.assertIsNone(sheet.cell(3, 8).value)
        self.assertIsNone(sheet.cell(3, 9).value)
        self.assertEqual(sheet.cell(2, 10).value, "УО PQM")
        self.assertEqual(sheet.cell(2, 11).value, "УО Google")
        self.assertIn("supplier_code=0000000000", sheet.cell(2, 12).hyperlink.target)

    def test_preview_conflict_reasons_are_localized_and_keep_internal_codes(self):
        reasons = ["same_timestamp_verification_conflict", "missing_source_column:Дата перевірки"]
        rows = server.supplier_edr_localize_review_details([
            {"category": "conflicts", "reason": reasons},
            {"category": "verification", "reason": "newer_verification_accepted"},
        ])
        self.assertEqual(rows[0]["reason_codes"], reasons)
        self.assertEqual(rows[0]["reason"], [
            server.edr_sync_v2.conflict_reason_details(code)[0] for code in reasons])
        self.assertEqual(rows[1]["reason"], "newer_verification_accepted")
        self.assertNotIn("reason_codes", rows[1])

    def test_pkce_transaction_survives_memory_restart_and_is_one_time(self):
        client = {"client_id": "test-client", "client_secret": "test-secret",
                  "auth_uri": "https://accounts.example/authorize", "token_uri": "https://accounts.example/token"}
        patches = self.common_patches()
        with patches[0], patches[1], patches[2], patches[3], \
             patch.object(server, "ENABLE_GOOGLE", True), \
             patch.object(server, "_google_oauth_client", return_value=client), \
             patch.object(server.urllib.request, "urlopen", return_value=FakeResponse({
                 "access_token": "test-access", "refresh_token": "test-refresh", "expires_in": 3600})):
            authorization_url = server.google_oauth_authorization_url("admin")
            state = urllib.parse.parse_qs(urllib.parse.urlparse(authorization_url).query)["state"][0]
            with sqlite3.connect(self.db_path) as con:
                row = con.execute("SELECT state_hash,code_verifier,expires_at FROM google_oauth_transactions").fetchone()
            self.assertNotEqual(row[0], state)
            self.assertTrue(row[1]); self.assertGreater(row[2], server.time.time())
            result = server.google_oauth_exchange("test-code", state)
            self.assertEqual(result["expected_origin"], "http://127.0.0.1:8080")
            self.assertTrue(self.token_path.is_file())
            with self.assertRaises(ValueError):
                server.google_oauth_exchange("test-code", state)

    def test_expired_pkce_transaction_is_rejected_and_cleaned(self):
        patches = self.common_patches()
        with patches[0], patches[1], patches[2], patches[3], patch.object(server, "ENABLE_GOOGLE", True):
            server._store_google_oauth_transaction("expired", "verifier",
                "http://127.0.0.1:8080/api/google-oauth/callback", "admin")
            with sqlite3.connect(self.db_path) as con:
                con.execute("UPDATE google_oauth_transactions SET expires_at=0")
            with self.assertRaises(ValueError):
                server._consume_google_oauth_transaction("expired")
            with sqlite3.connect(self.db_path) as con:
                self.assertEqual(con.execute("SELECT COUNT(*) FROM google_oauth_transactions").fetchone()[0], 0)

    def test_atomic_token_writes_never_leave_partial_json(self):
        values = [{"access_token": f"token-{index}", "refresh_token": "refresh"} for index in range(8)]
        threads = [threading.Thread(target=server._atomic_write_google_json, args=(self.token_path, value))
                   for value in values]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        stored = json.loads(self.token_path.read_text(encoding="utf-8"))
        self.assertIn(stored, values)
        self.assertEqual(list(self.token_path.parent.glob(".*.tmp")), [])

    def test_disconnect_is_local_audited_and_preserves_client(self):
        patches = self.common_patches()
        with patches[0], patches[1], patches[2], patches[3], \
             patch.object(server, "ENABLE_GOOGLE", False), \
             patch.object(server, "_google_oauth_client", return_value={"client_id": "configured"}):
            server._atomic_write_google_json(self.token_path, {"refresh_token": "test"})
            status, result = self.request("/api/admin/google/disconnect", payload={})
            self.assertEqual(status, 200)
            self.assertFalse(self.token_path.exists())
            self.assertTrue(result["feature"]["client_configured"])
            self.assertFalse(result["feature"]["oauth_connected"])
        with sqlite3.connect(self.db_path) as con:
            event = con.execute("SELECT old_value,new_value FROM audit_log WHERE field_name='google_oauth.connection'").fetchone()
        self.assertEqual(event, ("connected", "removed_locally"))

    def test_ui_starts_in_loading_state_and_validates_callback_origin(self):
        html = Path("index.html").read_text(encoding="utf-8")
        js = Path("app.js").read_text(encoding="utf-8")
        # NEXT hides the legacy EDR action; it must remain disabled at boot.
        self.assertIn('id="supplierEdrSync" disabled', html)
        self.assertIn("event.origin!==location.origin", js)
        self.assertNotIn("postMessage('pqm-google-oauth','*')", Path("server.py").read_text(encoding="utf-8"))
        self.assertNotIn("Google OAuth не налаштовано для TEST WEB", js)


if __name__ == "__main__":
    unittest.main()
