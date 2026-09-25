"""The consolidated code release must not expose Google migration writes."""

import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import server


class ProdEdrReleaseRoutingTests(unittest.TestCase):
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
        self.assertNotIn("PQM_SANDBOX_SUPPLIER_REGISTRY_TOKEN", source)
        self.assertNotIn("1lZtneKmCTvFcEL0erlJbegVzTTLNA-IKnjempn1G8Ww", source)
        self.assertIn('"pqm.sqlite3"', source)


if __name__ == "__main__":
    unittest.main()
