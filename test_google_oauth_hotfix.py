"""Isolated OAuth hotfix checks; no production DB, token, or Google access."""
import importlib.util
import io
import json
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

import server

spec = importlib.util.spec_from_file_location("existing_google_tests",
    Path(__file__).parent / "validation/local_release_20260911/test_google_runtime.py")
existing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(existing)


class GoogleOAuthHotfixTests(existing.GoogleRuntimeTests):
    def test_only_exact_get_callback_bypasses_auth(self):
        for path, command in [("/api/google-oauth/callback?state=x", "GET"),
                              ("/api/google-oauth/callback", "POST"),
                              ("/api/google-oauth/callback/", "GET"),
                              ("/api/google-oauth/start", "POST"),
                              ("/api/google-oauth/status", "GET"),
                              ("/api/supplier-edr-sync/preview", "POST"),
                              ("/api/supplier-edr-sync", "POST"),
                              ("/api/admin/google/disconnect", "POST"),
                              ("/api/health", "GET")]:
            with self.subTest(path=path, method=command):
                handler = object.__new__(server.Handler)
                handler.path, handler.command = path, command
                handler._authorize = Mock(return_value=False)
                action = Mock()
                handler._dispatch(action)
                bypass = path.startswith("/api/google-oauth/callback?") and command == "GET"
                self.assertEqual(action.call_count, int(bypass))
                self.assertEqual(handler._authorize.call_count, int(not bypass))

    def test_real_callback_handler_valid_and_invalid_without_session(self):
        for state, error in [("valid", None), ("invalid", ValueError("Invalid OAuth state")),
                             ("expired", ValueError("Expired OAuth state")),
                             ("reused", ValueError("Reused OAuth state"))]:
            handler = object.__new__(server.Handler)
            handler.path = f"/api/google-oauth/callback?code=fixture-code&state={state}"
            handler.command = "GET"
            handler.wfile = io.BytesIO()
            handler.send_response, handler.send_header, handler.end_headers = Mock(), Mock(), Mock()
            handler._authorize = Mock(return_value=False)
            with patch.object(server, "_google_oauth_redirect_uri", return_value="https://pqm.example/api/google-oauth/callback"), \
                 patch.object(server, "google_oauth_exchange", return_value={"expected_origin":"https://pqm.example"}, side_effect=error):
                handler._dispatch(handler._do_GET)
            handler.send_response.assert_called_once_with(200 if error is None else 400)
            handler._authorize.assert_not_called()
            self.assertIn(b'https://pqm.example', handler.wfile.getvalue())

    def test_both_phase_errors_do_not_write_tokens_or_echo_secrets(self):
        for phase in ("oauth_token_refresh", "sheets_values_read"):
            payload = {"error":"invalid_grant", "error_description":"refresh_token=secret code=secret client_secret=secret"}
            exc = urllib.error.HTTPError("https://example.invalid?code=secret",400,"secret",None,io.BytesIO(json.dumps(payload).encode()))
            patches = self.common_patches()
            with patches[0], patches[1], patches[2], patches[3], \
                 patch.object(server, "google_effective_enabled", return_value=True), \
                 patch.object(server, "_google_oauth_client", return_value={"client_id":"fixture","client_secret":"secret"}), \
                 patch.object(server, "_google_oauth_token", return_value={"refresh_token":"secret"}), \
                 patch.object(server, "_google_access_token", return_value="secret") if phase == "sheets_values_read" else patch.object(server, "ENABLE_GOOGLE", True), \
                 patch.object(server.urllib.request, "urlopen", side_effect=exc), \
                 patch.object(server, "_atomic_write_google_json") as write, \
                 patch.object(server.SERVER_LOG, "warning") as log:
                with self.assertRaises(server.GooglePhaseError) as caught:
                    server._google_sheet_values("fixture") if phase == "sheets_values_read" else server._google_access_token()
            diagnostics = caught.exception.diagnostic_payload()
            self.assertEqual(set(diagnostics), {"phase","google_http_status","google_error","google_error_description"})
            self.assertEqual(diagnostics["phase"],phase)
            self.assertNotIn("secret",json.dumps(diagnostics)+str(log.call_args)+str(caught.exception))
            write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
