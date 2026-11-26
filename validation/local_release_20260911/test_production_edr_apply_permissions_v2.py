"""Production EDR V2 permission matrix and fail-closed Apply checks."""
import hashlib
import sqlite3
import unittest
from contextlib import ExitStack
from unittest.mock import patch

import edr_sync_review
import server
from validation.local_release_20260911 import test_google_runtime


class ProductionEdrApplyPermissionsV2Tests(unittest.TestCase):
    def setUp(self):
        self.helper = test_google_runtime.GoogleRuntimeTests()
        self.helper.setUp()
        self.addCleanup(self.helper.doCleanups)
        with sqlite3.connect(self.helper.db_path) as con:
            con.execute("CREATE TABLE supplier_edr_profiles(supplier_code TEXT)")

    def digest(self):
        return hashlib.sha256(self.helper.db_path.read_bytes()).hexdigest()

    def set_flags(self, sync, apply, partial):
        return patch.dict(server.os.environ, {
            "PQM_ENV": "web",
            "PQM_SANDBOX": "0",
            "PQM_PRODUCTION_EDR_SYNC_ENABLED": str(int(sync)),
            "PQM_PRODUCTION_EDR_APPLY_ENABLED": str(int(apply)),
            "PQM_PRODUCTION_EDR_PARTIAL_APPLY": str(int(partial)),
        })

    def request_patches(self, *, conflicts=False):
        fingerprint, digest = "a" * 64, "b" * 64
        plan = {"source_fingerprint": fingerprint, "previewed_at": "synthetic",
                "conflicts": ([{"supplier_code": "10000001"}] if conflicts else []),
                "items": [], "summary": {"ready_to_apply": 1}}
        return fingerprint, digest, (
            patch.object(server, "SANDBOX_MODE", False),
            patch.object(server, "google_effective_enabled", return_value=True),
            patch.object(server, "supplier_edr_source_snapshot",
                         return_value={"source_fingerprint": fingerprint}),
            patch.object(server.edr_sync_v2, "build_preview", return_value=plan),
            patch.object(server.edr_sync_v2, "preview_state_digest", return_value=digest),
            patch.object(edr_sync_review, "details", return_value=[]),
            patch.object(server, "supplier_edr_sync_conflicts_export", return_value=b'{"xlsx":"synthetic"}'),
        )

    def reset_sync_state(self):
        with server.SUPPLIER_EDR_SYNC_START_LOCK:
            server.SUPPLIER_EDR_SYNC_STATE.update(running=False, run_id=None, error=None)

    def test_all_eight_permission_combinations_in_web_production_mode(self):
        for sync in (0, 1):
            for apply in (0, 1):
                for partial in (0, 1):
                    for conflicts in (False, True):
                        with self.subTest(sync=sync, apply=apply, partial=partial, conflicts=conflicts):
                            self.reset_sync_state()
                            fingerprint, state_digest, patches = self.request_patches(conflicts=conflicts)
                            with ExitStack() as stack:
                                for item in patches:
                                    stack.enter_context(item)
                                stack.enter_context(patch.object(server, "DB_PATH", self.helper.db_path))
                                stack.enter_context(patch.object(server, "GOOGLE_OAUTH_TOKEN_PATH", self.helper.token_path))
                                stack.enter_context(patch.object(server, "AUTH_ENABLED", False))
                                stack.enter_context(patch.object(server, "LOCAL_ROLE_IMPERSONATION", True))
                                stack.enter_context(self.set_flags(sync, apply, partial))
                                worker = stack.enter_context(patch.object(server, "supplier_edr_sync_worker"))
                                status_status, runtime_status = self.helper.request("/api/supplier-edr-sync-status")
                                self.assertEqual(status_status, 200)
                                self.assertEqual(runtime_status["apply_enabled"], bool(apply))

                                preview_status, preview = self.helper.request(
                                    "/api/supplier-edr-sync/preview", payload={})
                                self.assertEqual(preview_status, 200 if sync else 403)
                                if sync:
                                    self.assertEqual(preview["apply_enabled"], bool(apply))
                                    self.assertEqual(preview["apply_available"],
                                        bool(apply and (not conflicts or partial)))

                                export_status, _ = self.helper.request(
                                    "/api/supplier-edr-sync/conflicts.xlsx",
                                    payload={"source_fingerprint": fingerprint, "state_digest": state_digest})
                                self.assertEqual(export_status, 403 if not sync else 200)

                                before_db = self.digest()
                                apply_status, apply_result = self.helper.request(
                                    "/api/supplier-edr-sync", payload={"confirmed": True,
                                        "source_fingerprint": fingerprint, "state_digest": state_digest})
                                if not sync or not apply:
                                    self.assertEqual(apply_status, 403)
                                    if sync and not apply:
                                        self.assertEqual(apply_result["error"],
                                            "Режим лише перегляду. Застосування змін вимкнено")
                                    worker.assert_not_called()
                                    self.assertEqual(self.digest(), before_db)
                                elif conflicts and not partial:
                                    self.assertEqual(apply_status, 409)
                                    worker.assert_not_called()
                                else:
                                    self.assertEqual(apply_status, 202)
                                    worker.assert_called_once()
                                self.reset_sync_state()

    def test_read_only_preview_and_conflict_xlsx_remain_available_without_apply_grant(self):
        fingerprint, state_digest, patches = self.request_patches(conflicts=True)
        with ExitStack() as stack:
            for item in patches:
                stack.enter_context(item)
            stack.enter_context(patch.object(server, "DB_PATH", self.helper.db_path))
            stack.enter_context(patch.object(server, "GOOGLE_OAUTH_TOKEN_PATH", self.helper.token_path))
            stack.enter_context(patch.object(server, "AUTH_ENABLED", False))
            stack.enter_context(patch.object(server, "LOCAL_ROLE_IMPERSONATION", True))
            stack.enter_context(self.set_flags(1, 0, 1))
            stack.enter_context(patch.object(server, "supplier_edr_sync_conflicts_export", return_value=b'{"xlsx":"synthetic"}'))
            status, preview = self.helper.request("/api/supplier-edr-sync/preview", payload={})
            self.assertEqual(status, 200)
            self.assertFalse(preview["apply_enabled"])
            self.assertFalse(preview["apply_available"])
            status, result = self.helper.request("/api/supplier-edr-sync/conflicts.xlsx", payload={
                "source_fingerprint": fingerprint, "state_digest": state_digest})
            self.assertEqual(status, 200)
            self.assertEqual(result, {"xlsx": "synthetic"})

    def test_worker_rechecks_apply_grant_before_any_database_write(self):
        with patch.object(server, "DB_PATH", self.helper.db_path), \
             patch.object(server, "SANDBOX_MODE", False), \
             patch.object(server, "google_effective_enabled", return_value=True), \
             self.set_flags(1, 0, 1), \
             patch.object(server.SERVER_LOG, "exception"):
            before = self.digest()
            server.supplier_edr_sync_worker("a" * 64, "test", "b" * 64,
                                            allow_partial_conflicts=True)
            self.assertEqual(self.digest(), before)
        with sqlite3.connect(self.helper.db_path) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM supplier_edr_sync_log").fetchone()[0], 0)
        self.assertFalse(server.SUPPLIER_EDR_SYNC_STATE["running"])
        self.assertEqual(server.SUPPLIER_EDR_SYNC_STATE["last_result"], "failed")

    def test_worker_rechecks_grant_at_transaction_boundary(self):
        with patch.object(server, "DB_PATH", self.helper.db_path), \
             patch.object(server, "SANDBOX_MODE", False), \
             patch.object(server, "google_effective_enabled", return_value=True), \
             self.set_flags(1, 1, 1), \
             patch.object(server, "supplier_edr_source_snapshot",
                          return_value={"source_fingerprint": "a" * 64}), \
             patch.object(server, "_require_supplier_edr_apply_enabled",
                          side_effect=[None, PermissionError("grant revoked")]), \
             patch.object(server.edr_sync_v2, "migrate") as migrate, \
             patch.object(server.edr_sync_v2, "apply") as apply, \
             patch.object(server.SERVER_LOG, "exception"):
            server.supplier_edr_sync_worker("a" * 64, "test", "b" * 64,
                                            allow_partial_conflicts=True)
            migrate.assert_not_called()
            apply.assert_not_called()
        with sqlite3.connect(self.helper.db_path) as con:
            rows = con.execute("SELECT status,error FROM supplier_edr_sync_log").fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][0], "failed")
            self.assertEqual(rows[0][1], "grant revoked")

    def test_worker_still_requires_sync_gate_and_apply_gate_independently(self):
        for sync, apply in ((0, 1), (1, 0), (0, 0)):
            with self.subTest(sync=sync, apply=apply):
                with patch.object(server, "DB_PATH", self.helper.db_path), \
                     patch.object(server, "SANDBOX_MODE", False), \
                     patch.object(server, "google_effective_enabled", return_value=True), \
                     self.set_flags(sync, apply, 1), \
                     patch.object(server.SERVER_LOG, "exception"):
                    before = self.digest()
                    server.supplier_edr_sync_worker("a" * 64, "test", "b" * 64,
                                                    allow_partial_conflicts=True)
                    self.assertEqual(self.digest(), before)
                with sqlite3.connect(self.helper.db_path) as con:
                    self.assertEqual(con.execute("SELECT COUNT(*) FROM supplier_edr_sync_log").fetchone()[0], 0)

    def test_sandbox_apply_permission_is_not_changed_by_production_flag(self):
        with patch.object(server, "SANDBOX_MODE", True), self.set_flags(1, 0, 0):
            self.assertTrue(server.production_edr_apply_enabled())

    def test_apply_permission_does_not_change_google_writer_token_gate(self):
        with patch.object(server, "google_effective_enabled", return_value=True), \
             patch.object(server, "_google_oauth_token", return_value={"access_token": "synthetic", "refresh_token": "refresh",
                 "obtained_at": server.time.time(), "expires_in": 3600}), \
             patch.object(server, "_google_oauth_client", return_value={"client_id": "synthetic"}), \
             patch.object(server, "SANDBOX_MODE", False), self.set_flags(1, 0, 0):
            self.assertFalse(server.production_edr_apply_enabled())
            self.assertEqual(server._google_access_token(), "synthetic")

    def test_frontend_disables_apply_and_explains_view_only_mode(self):
        from pathlib import Path

        app = Path("app.js").read_text(encoding="utf-8")
        preview = app.split("async function previewSupplierEdrSync()", 1)[1].split("function renderSupplierEdrReviewDetails", 1)[0]
        apply_flow = app.split("async function startSupplierEdrSync()", 1)[1].split("function edrMonitoringParams", 1)[0]
        self.assertIn("data.apply_enabled!==false", preview)
        self.assertIn("Режим лише перегляду. Застосування змін вимкнено", preview)
        self.assertIn("applyButton.disabled=!applyEnabled", preview)
        self.assertIn("supplierEdrPreview?.apply_enabled===false", apply_flow)


if __name__ == "__main__":
    unittest.main()
