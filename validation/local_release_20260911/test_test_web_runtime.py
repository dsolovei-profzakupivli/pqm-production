import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import server
import scheduler_runtime


class TestWebRuntimeTests(unittest.TestCase):
    def test_basic_auth_users_are_read_only_from_environment(self):
        payload = json.dumps({"users": [{"username": "reviewer", "password": "temporary"}]})
        with patch.dict(os.environ, {"PQM_USERS_JSON": payload}, clear=False):
            self.assertEqual(server.configured_basic_auth_users(), {"reviewer": "temporary"})

    def test_sha256_basic_auth_secret(self):
        digest = server.hashlib.sha256(b"temporary").hexdigest()
        self.assertTrue(server.verify_basic_auth_secret("temporary", f"sha256:{digest}"))
        self.assertFalse(server.verify_basic_auth_secret("wrong", f"sha256:{digest}"))

    def test_configured_accounts_support_distinct_roles(self):
        payload = json.dumps({"users": [
            {"username": "administrator", "password_hash": "sha256:aaa", "role": "admin"},
            {"username": "officer", "password": "temporary", "role": "officer"},
            {"username": "reader", "password": "temporary", "role": "viewer"},
        ]})
        with patch.dict(os.environ, {"PQM_USERS_JSON": payload}, clear=False):
            accounts = server.configured_auth_accounts()
        self.assertEqual(accounts["administrator"]["role"], "admin")
        self.assertEqual(accounts["officer"]["role"], "officer")
        self.assertEqual(accounts["reader"]["role"], "viewer")

    def test_rbac_is_default_deny_for_mutations(self):
        self.assertTrue(server.mutation_allowed("admin", "POST", "/api/sync"))
        self.assertTrue(server.mutation_allowed(
            "officer", "PATCH", "/api/violation-reports/report-1/review"))
        self.assertTrue(server.mutation_allowed(
            "officer", "POST", "/api/violation-reports/report-1/review/complete"))
        self.assertFalse(server.mutation_allowed("officer", "POST", "/api/sync"))
        self.assertFalse(server.mutation_allowed("viewer", "PATCH", "/api/applications/submission-1"))
        self.assertFalse(server.mutation_allowed("unknown", "POST", "/api/anything"))

    def test_admin_reads_are_protected_but_active_assignment_data_remains_available(self):
        self.assertTrue(server.admin_read_allowed("admin", "/api/admin/templates"))
        self.assertFalse(server.admin_read_allowed("officer", "/api/admin/templates"))
        self.assertFalse(server.admin_read_allowed("viewer", "/api/audit"))
        self.assertTrue(server.admin_read_allowed(
            "officer", "/api/admin/officers", {"active": ["1"]}))
        self.assertFalse(server.admin_read_allowed("officer", "/api/admin/officers", {}))

    def test_only_one_prozorro_sync_can_be_claimed(self):
        original = dict(server.SYNC_STATE)
        old_db = server.DB_PATH
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
          server.DB_PATH = Path(directory) / "scheduler.sqlite3"
          with sqlite3.connect(server.DB_PATH) as con:
            scheduler_runtime.migrate(con)
          try:
            server.SYNC_STATE.update(running=False)
            with patch.object(server.threading, "Thread") as thread:
                thread.return_value.start.return_value = None
                self.assertTrue(server.start_prozorro_sync(
                    lambda: None, mode="manual", message="Підготовка"))
                self.assertFalse(server.start_prozorro_sync(
                    lambda: None, mode="manual", message="Другий запуск"))
                self.assertEqual(thread.call_count, 1)
          finally:
            server.SYNC_STATE.clear()
            server.SYNC_STATE.update(original)
            server.DB_PATH = old_db

    def test_environment_banner_favicon_and_dynamic_titles_are_configured(self):
        root = Path(__file__).resolve().parent
        html = (root / "index.html").read_text(encoding="utf-8")
        javascript = (root / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="environmentBanner"', html)
        # Preserve the user's separately approved WEB magnifier/favicon assets.
        self.assertIn('rel="icon" href="/assets/pqm-tab-icon.png"', html)
        self.assertIn('rel="icon" href="/assets/pqm-search-icon.png"', html)
        self.assertTrue((root / "assets" / "pqm-tab-icon.png").is_file())
        self.assertTrue((root / "assets" / "pqm-search-icon.png").is_file())
        self.assertNotIn("'PQM · WEB TEST'", javascript)
        self.assertIn("if(features?.sandbox_mode)return 'PQM · SANDBOX'", javascript)
        self.assertIn("if(environment==='local')return 'PQM · LOCAL'", javascript)
        self.assertIn('>PQM</em>', html)
        self.assertIn('document.title=`PQM — ${titles[name]', javascript)

    def test_local_role_switch_reapplies_admin_capabilities_centrally(self):
        javascript = (Path(__file__).resolve().parent / "app.js").read_text(encoding="utf-8")
        self.assertIn("element.dataset.roleDisabled=admin?'0':'1'", javascript)
        self.assertIn("element.disabled=!admin||element.dataset.runtimeDisabled==='1'", javascript)
        self.assertIn("document.body.classList.toggle('role-viewer',viewer)", javascript)
        self.assertIn("element.dataset.runtimeDisabled='1'", javascript)
        self.assertIn("requestsRefresh.disabled=viewer||requestsRefresh.dataset.runtimeDisabled==='1'", javascript)
        self.assertIn("Дія недоступна для ролі лише перегляду", javascript)

    def test_bids_disabled_fails_with_controlled_exception(self):
        with patch.object(server, "BIDS_MODE", "disabled"):
            with self.assertRaisesRegex(server.BidsUnavailableError, "вимкнена"):
                with server.bids_db():
                    pass

    def test_bids_status_refresh_is_background_and_not_duplicated(self):
        original = dict(server.BIDS_STATUS_CACHE)
        server.BIDS_STATUS_CACHE.clear()
        self.assertFalse(server.BIDS_STATUS_LOCK.locked())
        try:
            with patch.object(server.threading, "Thread") as thread:
                thread.return_value.start.return_value = None
                first = server.bids_sync_status()
                second = server.bids_sync_status()
                self.assertTrue(first["refreshing"])
                self.assertTrue(second["refreshing"])
                self.assertEqual(thread.call_count, 1)
        finally:
            if server.BIDS_STATUS_LOCK.locked():
                server.BIDS_STATUS_LOCK.release()
            server.BIDS_STATUS_CACHE.clear()
            server.BIDS_STATUS_CACHE.update(original)

    def test_long_running_updates_are_detached_from_http_response(self):
        source = (Path(__file__).resolve().parent / "server.py").read_text(encoding="utf-8")
        javascript = (Path(__file__).resolve().parent / "app.js").read_text(encoding="utf-8")
        self.assertIn("threading.Thread(target=bids_update_worker, daemon=True)", source)
        self.assertIn("worker.start()", source)
        self.assertIn("start_nazk_registry_refresh(trigger=\"manual\")", source)
        self.assertIn("if(state?.status==='running')", javascript)
        self.assertIn("transient poll failure", javascript)

    def test_powerbi_disabled_has_safe_status(self):
        with patch.object(server, "ENABLE_POWERBI", False):
            status = server.powerbi_export_status()
        self.assertFalse(status["available"])
        self.assertFalse(status["state"]["running"])

    def test_google_disabled_does_not_expose_local_paths(self):
        with patch.object(server, "ENABLE_GOOGLE", False):
            status = server.google_oauth_status()
        self.assertFalse(status["enabled"])
        self.assertNotIn("client_path", status)

    def test_inaccessible_google_oauth_client_is_controlled_status(self):
        inaccessible = Mock()
        inaccessible.is_file.side_effect = PermissionError("access denied")
        missing_token = Mock()
        missing_token.is_file.return_value = False
        with patch.object(server, "ENABLE_GOOGLE", True), \
             patch.object(server, "GOOGLE_OAUTH_CLIENT_PATH", inaccessible), \
             patch.object(server, "GOOGLE_OAUTH_TOKEN_PATH", missing_token):
            status = server.google_oauth_status()
        self.assertFalse(status["configured"])
        self.assertFalse(status["available"])
        self.assertEqual(status["configuration_error"], "access_denied")
        self.assertNotIn("access denied", json.dumps(status))


if __name__ == "__main__":
    unittest.main()
