import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import sandbox_runtime
import scheduler_runtime
import server


class SandboxSchedulerControlsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.path = Path(self.temp.name) / "sandbox.sqlite3"
        with closing(sqlite3.connect(self.path)) as con:
            with con:
                scheduler_runtime.migrate(con)
                con.execute("CREATE TABLE audit_log(submission_id TEXT,changed_at TEXT,changed_by TEXT,field_name TEXT,old_value TEXT,new_value TEXT)")
                con.execute("CREATE TABLE sandbox_deployment_identity(environment TEXT,service_id TEXT)")
                con.execute("INSERT INTO sandbox_deployment_identity VALUES ('sandbox','fixture-service')")
                con.execute("CREATE TABLE runtime_feature_settings(enabled INTEGER)")
                con.execute("CREATE TABLE auth_users(role TEXT,active INTEGER)")
                con.execute("INSERT INTO auth_users VALUES ('admin',1)")
        self.env = {"PQM_SANDBOX": "1", "PQM_SANDBOX_OPERATIONAL": "1",
                    "PQM_SANDBOX_PROZORRO_READ": "1", "PQM_SANDBOX_REQUESTS_SCHEDULER": "1",
                    "PQM_SANDBOX_NAZK_READ": "1"}

    def tearDown(self):
        self.temp.cleanup()

    def _server_context(self):
        return (patch.object(server, "SANDBOX_MODE", True),
                patch.object(server, "SAFE_MODE", True),
                patch.object(server, "DB_PATH", self.path),
                patch.object(server, "sandbox_runtime", sandbox_runtime, create=True),
                patch.dict(sandbox_runtime.os.environ, self.env))

    def test_defaults_disabled_and_three_independent_persisted_settings(self):
        context = self._server_context()
        with context[0], context[1], context[2], context[3], context[4], \
                patch.object(sandbox_runtime, "attest_internal_target", return_value=self.path), \
                patch.object(server, "register_scheduler_job") as register, \
                patch.object(server, "unregister_scheduler_job") as unregister:
            initial, _ = server.effective_scheduler_settings()
            self.assertFalse(initial["prozorro"])
            self.assertFalse(initial["violation_reports"])
            self.assertFalse(initial["nazk_registry"])
            server.set_scheduler_job_enabled("prozorro", True, "sandbox.admin")
            only_prozorro, _ = server.effective_scheduler_settings()
            self.assertTrue(only_prozorro["prozorro"])
            self.assertFalse(only_prozorro["violation_reports"])
            self.assertFalse(only_prozorro["nazk_registry"])
            server.set_scheduler_job_enabled("violation_reports", True, "sandbox.admin")
            requests, _ = server.effective_scheduler_settings()
            self.assertTrue(requests["violation_reports"])
            self.assertFalse(requests["nazk_registry"])
            self.assertEqual(register.call_count, 2)
            self.assertEqual(register.call_args.kwargs["catch_up"], False)
            server.set_scheduler_job_enabled("nazk_registry", True, "sandbox.admin")
            after_restart, sources = server.effective_scheduler_settings()
            self.assertTrue(after_restart["violation_reports"])
            self.assertTrue(after_restart["nazk_registry"])
            self.assertTrue(after_restart["prozorro"])
            self.assertEqual(sources["violation_reports"], "runtime")
            server.set_scheduler_job_enabled("violation_reports", False, "sandbox.admin")
            server.set_scheduler_job_enabled("nazk_registry", False, "sandbox.admin")
            server.set_scheduler_job_enabled("prozorro", False, "sandbox.admin")
            final, _ = server.effective_scheduler_settings()
            self.assertFalse(final["prozorro"])
            self.assertFalse(final["violation_reports"])
            self.assertFalse(final["nazk_registry"])
            self.assertEqual(unregister.call_count, 3)
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(dict(con.execute("SELECT job_key,enabled FROM scheduler_job_settings"))[
                "prozorro"], 0)
            self.assertEqual(dict(con.execute("SELECT job_key,enabled FROM scheduler_job_settings"))[
                "violation_reports"], 0)
            self.assertEqual(dict(con.execute("SELECT job_key,enabled FROM scheduler_job_settings"))[
                "nazk_registry"], 0)

    def test_all_three_jobs_are_independent_sandbox_db_settings(self):
        with patch.dict(sandbox_runtime.os.environ, self.env):
            self.assertTrue(sandbox_runtime.scheduler_job_allowed("violation_reports"))
            self.assertTrue(sandbox_runtime.scheduler_job_allowed("nazk_registry"))
            self.assertTrue(sandbox_runtime.scheduler_job_allowed("prozorro"))
        with patch.dict(sandbox_runtime.os.environ, {**self.env,
                                                    "PQM_SANDBOX_REQUESTS_SCHEDULER": "0",
                                                    "PQM_SANDBOX_NAZK_READ": "0"}):
            self.assertTrue(sandbox_runtime.scheduler_job_allowed("violation_reports"))
            self.assertTrue(sandbox_runtime.scheduler_job_allowed("nazk_registry"))
        with patch.dict(sandbox_runtime.os.environ, {**self.env, "PQM_SANDBOX": "0"}):
            self.assertFalse(sandbox_runtime.scheduler_job_allowed("prozorro"))
            self.assertFalse(sandbox_runtime.scheduler_job_allowed("violation_reports"))
            self.assertFalse(sandbox_runtime.scheduler_job_allowed("nazk_registry"))

    def test_identity_and_enabled_state_are_checked_before_run(self):
        with patch.dict(sandbox_runtime.os.environ, self.env):
            sandbox_runtime._verify_existing(self.path, "fixture-service")
            with closing(sqlite3.connect(self.path)) as con:
                with con:
                    scheduler_runtime.save_enabled(con, "violation_reports", True, "sandbox.admin")
            sandbox_runtime._verify_existing(self.path, "fixture-service")
            with self.assertRaises(RuntimeError):
                sandbox_runtime._verify_existing(self.path, "prod-service")
            with patch.object(server, "SANDBOX_MODE", True), \
                    patch.object(server, "sandbox_runtime", sandbox_runtime, create=True), \
                    patch.object(sandbox_runtime, "attest_internal_target", side_effect=RuntimeError("wrong DB")), \
                    patch.object(server.scheduler_runtime, "claim") as claim:
                with self.assertRaises(RuntimeError):
                    server.start_violation_reports_sync(trigger="scheduled")
                with self.assertRaises(RuntimeError):
                    server.start_nazk_registry_refresh(trigger="scheduled")
                claim.assert_not_called()

    def test_disabled_loops_do_not_dispatch_and_scheduled_requests_use_owned_path(self):
        context = self._server_context()
        with context[0], context[1], context[2], context[3], context[4], \
                patch.object(server, "_trigger_scheduler_job") as dispatch:
            server.violation_reports_scheduler(threading.Event(), catch_up=True)
            server.nazk_registry_scheduler(threading.Event(), catch_up=True)
            dispatch.assert_not_called()
        with patch.object(server, "start_violation_reports_sync", return_value=True) as start:
            self.assertTrue(server._trigger_scheduler_job("violation_reports", "scheduled"))
            start.assert_called_once_with(trigger="scheduled")

    def test_external_transport_rejects_mutations_and_prod_destination(self):
        with patch.dict(sandbox_runtime.os.environ, self.env):
            sandbox_runtime.validate_prozorro_url(
                "https://public-api.prozorro.gov.ua/api/2.5/violation_reports")
            sandbox_runtime.validate_nazk_request(
                "https://corruptinfo.nazk.gov.ua/ep/1.0/corrupt/getAllData", "GET")
            with self.assertRaises(RuntimeError):
                sandbox_runtime.validate_nazk_request(
                    "https://corruptinfo.nazk.gov.ua/ep/1.0/corrupt/getAllData", "POST")
            with self.assertRaises(RuntimeError):
                sandbox_runtime.validate_prozorro_url(
                    "https://pqm-production-1.onrender.com/api/violation_reports")


if __name__ == "__main__":
    unittest.main()
