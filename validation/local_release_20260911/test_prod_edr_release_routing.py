"""The consolidated code release must not expose Google migration writes."""

import os
import io
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import server


class ProdEdrReleaseRoutingTests(unittest.TestCase):
    def test_google_row_navigation_resolves_live_tab_and_row_without_writes(self):
        values = {"ФОП": [["name", "code"], ["other", "00000000"]],
                  "ЮО": [["name", "code"], ["other", "11111111"], ["target", "12345678"]]}
        metadata = {"sheets": [{"properties": {"title": "ФОП", "sheetId": 10}},
                               {"properties": {"title": "ЮО", "sheetId": 20}}]}
        with patch.object(server, "_google_sheet_values", side_effect=lambda tab: values[tab]) as read, \
             patch.object(server, "_google_access_token", return_value="synthetic"), \
             patch.object(server.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(metadata).encode())) as open_url:
            result = server.supplier_google_row("12345678")
        self.assertEqual(result["source_tab"], "ЮО")
        self.assertTrue(result["url"].endswith("#gid=20&range=B3"))
        self.assertEqual(read.call_count, 2)
        self.assertEqual(open_url.call_count, 1)

    def test_google_row_navigation_rejects_ambiguous_identity(self):
        with patch.object(server, "_google_sheet_values", return_value=[["name", "code"], ["target", "12345678"]]):
            with self.assertRaisesRegex(ValueError, "ambiguous"):
                server.supplier_google_row("12345678")

    def test_all_migration_routes_are_unavailable_even_with_environment_flag(self):
        for path in server.GOOGLE_MIGRATION_DISABLED_PATHS:
            for method in ("GET", "POST"):
                with self.subTest(path=path, method=method), patch.dict(
                    os.environ, {"PQM_SANDBOX": "1", "PQM_PROD_GOOGLE_MIGRATION_ENABLED": "1"}
                ):
                    responses = []
                    handler = SimpleNamespace(
                        path=path,
                        command=method,
                        send_json=lambda body, status=200: responses.append((body, status)),
                    )
                    server.Handler._dispatch(handler, lambda: self.fail("route dispatched"))
                    self.assertEqual(responses[0][1], 404)

    def test_normal_full_registry_route_remains_reachable_with_prod_auth(self):
        dispatched = []
        handler = SimpleNamespace(
            path=server.SUPPLIER_REGISTRY_INTEGRATION_PATH,
            command="GET",
            _authorize_supplier_registry_integration=lambda: True,
        )
        server.Handler._dispatch(handler, lambda: dispatched.append(True))
        self.assertEqual(dispatched, [True])
        self.assertEqual(handler.auth_user, "integration:suppliers-full-registry")
        self.assertEqual(server.SUPPLIER_REGISTRY_INTEGRATION_TOKEN_ENV,
                         "PQM_SUPPLIER_REGISTRY_TOKEN")

    def test_normal_prod_paths_and_schema_are_not_sandbox_specific(self):
        source = Path(server.__file__).read_text(encoding="utf-8")
        self.assertNotIn("pqm_sandbox.sqlite3", source)
        self.assertNotIn("1lZtneKmCTvFcEL0erlJbegVzTTLNA-IKnjempn1G8Ww", source)
        self.assertIn('"pqm.sqlite3"', source)
        responses = []
        dispatched = []
        handler = SimpleNamespace(
            path=server.SUPPLIER_REGISTRY_INTEGRATION_PATH,
            command="GET",
            headers={"Authorization": "Bearer sandbox-only-token"},
            send_json=lambda body, status=200: responses.append((body, status)),
        )
        handler._authorize_supplier_registry_integration = lambda: (
            server.Handler._authorize_supplier_registry_integration(handler))
        with patch.object(server, "SANDBOX_MODE", False), patch.dict(os.environ, {
                server.SUPPLIER_REGISTRY_INTEGRATION_TOKEN_ENV: "prod-only-token",
                server.SANDBOX_SUPPLIER_REGISTRY_INTEGRATION_TOKEN_ENV: "sandbox-only-token"}):
            server.Handler._dispatch(handler, lambda: dispatched.append(True))
            self.assertEqual(responses[-1][1], 401)
            self.assertEqual(dispatched, [])
            handler.headers["Authorization"] = "Bearer prod-only-token"
            server.Handler._dispatch(handler, lambda: dispatched.append(True))
            self.assertEqual(dispatched, [True])


if __name__ == "__main__":
    unittest.main()
