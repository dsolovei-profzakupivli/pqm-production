"""Sandbox-only supplier-registry token selection must not inherit PROD credentials."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import server


class RegistryTokenTests(unittest.TestCase):
    def handler(self, header):
        item = server.Handler.__new__(server.Handler)
        item.headers = {"Authorization": header}
        item.result = None
        item.send_json = lambda body, status=200: setattr(item, "result", (body, status))
        return item

    def test_sandbox_accepts_only_sandbox_token(self):
        env = {server.SANDBOX_SUPPLIER_REGISTRY_INTEGRATION_TOKEN_ENV: "sandbox-secret",
               server.SUPPLIER_REGISTRY_INTEGRATION_TOKEN_ENV: "prod-secret"}
        with patch.object(server, "SANDBOX_MODE", True), patch.dict(os.environ, env, clear=True):
            self.assertTrue(self.handler("Bearer sandbox-secret")._authorize_supplier_registry_integration())
            rejected = self.handler("Bearer prod-secret")
            self.assertFalse(rejected._authorize_supplier_registry_integration())
            self.assertEqual(rejected.result[1], 401)

    def test_sandbox_does_not_fallback_to_generic_token(self):
        with patch.object(server, "SANDBOX_MODE", True), patch.dict(
                os.environ, {server.SUPPLIER_REGISTRY_INTEGRATION_TOKEN_ENV: "prod-secret"}, clear=True):
            item = self.handler("Bearer prod-secret")
            self.assertFalse(item._authorize_supplier_registry_integration())
            self.assertEqual(item.result[1], 503)

    def test_non_sandbox_behavior_keeps_generic_token(self):
        with patch.object(server, "SANDBOX_MODE", False), patch.dict(
                os.environ, {server.SUPPLIER_REGISTRY_INTEGRATION_TOKEN_ENV: "prod-secret"}, clear=True):
            self.assertTrue(self.handler("Bearer prod-secret")._authorize_supplier_registry_integration())


if __name__ == "__main__":
    unittest.main()
