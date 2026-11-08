"""Manual operations remain available through authenticated paths while automation is locked."""
from contextlib import closing, contextmanager, nullcontext
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

import auth_access
import background_jobs
import google_writer_execution
import scheduler_runtime
import sandbox_runtime
import server

# The production module imports this name only when launched with PQM_SANDBOX=1.
# Unit tests set that flag after import, so bind the same real module explicitly.
server.sandbox_runtime = sandbox_runtime


class ManualOperationInterlockTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"PQM_DISABLE_BACKGROUND_JOBS": "1", "PQM_SANDBOX": "1"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent, prefix="manual-ops-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "sandbox.sqlite3"
        self.con = sqlite3.connect(self.path)
        self.addCleanup(self.con.close)
        server.SYNC_STATE["running"] = False
        server.VIOLATION_SYNC_STATE["running"] = False
        self.addCleanup(lambda: server.SYNC_STATE.update(running=False))
        self.addCleanup(lambda: server.VIOLATION_SYNC_STATE.update(running=False))
        with closing(sqlite3.connect(self.path)) as con:
            scheduler_runtime.migrate(con)
            google_writer_execution.migrate(con)
            con.executescript("""
              CREATE TABLE audit_log(id INTEGER PRIMARY KEY AUTOINCREMENT, submission_id TEXT,
                changed_at TEXT, changed_by TEXT, field_name TEXT, old_value TEXT, new_value TEXT);
              CREATE TABLE auth_roles(code TEXT PRIMARY KEY, label TEXT, base_role TEXT, active INTEGER,
                protected INTEGER, updated_at TEXT, updated_by TEXT);
              CREATE TABLE auth_role_permissions(role_code TEXT, permission_key TEXT, allowed INTEGER,
                updated_at TEXT, updated_by TEXT, PRIMARY KEY(role_code,permission_key));
              CREATE TABLE auth_user_roles(username TEXT PRIMARY KEY, role_code TEXT, updated_at TEXT, updated_by TEXT);
            """)
            for key in scheduler_runtime.SCHEDULES:
                spec = json.dumps(scheduler_runtime.default_spec(key))
                con.execute("INSERT INTO scheduler_job_settings(job_key,enabled,updated_at,updated_by,revision,schedule_json,timezone) VALUES(?,1,'fixture','admin',3,?,'Europe/Kyiv')", (key, spec))
            con.commit()

    def _settings(self):
        with closing(sqlite3.connect(self.path)) as con:
            return con.execute("SELECT job_key,enabled,revision,schedule_json FROM scheduler_job_settings ORDER BY job_key").fetchall()

    def test_manual_claim_is_explicit_audited_single_lane_and_does_not_edit_schedule(self):
        before = self._settings()
        for index, key in enumerate(scheduler_runtime.SCHEDULES):
            owner = scheduler_runtime.claim(str(self.path), key, trigger="manual",
                owner_id=f"owner-{index}", manual_authorized=True, actor="sandbox.admin")
            self.assertTrue(owner)
            self.assertIsNone(scheduler_runtime.claim(str(self.path), key, trigger="manual",
                manual_authorized=True, actor="sandbox.admin"))
            self.assertTrue(scheduler_runtime.finish(str(self.path), key, owner, status="ok"))
        self.assertEqual(self._settings(), before)
        with closing(sqlite3.connect(self.path)) as con:
            events = con.execute("SELECT field_name,changed_by FROM audit_log ORDER BY id").fetchall()
        self.assertEqual(len(events), 6)
        self.assertEqual({row[1] for row in events}, {"sandbox.admin"})
        self.assertEqual({row[0] for row in events}, {"background_job.started", "background_job.finished"})
        self.assertTrue(background_jobs.disabled())

    def test_worker_errors_are_finished_and_audited_without_live_external_calls(self):
        class InlineThread:
            def __init__(self, *, target, **_kwargs): self.target = target
            def start(self):
                try: self.target()
                except RuntimeError: pass
        class DummyKeepalive:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
        def nazk_failure(_db_path, _source, *, on_error, **_kwargs):
            on_error("synthetic upstream failure")
            return True
        with patch.object(server, "DB_PATH", self.path), patch.object(server, "SANDBOX_MODE", True), \
             patch.object(server, "sandbox_runtime", sandbox_runtime, create=True), \
             patch.object(sandbox_runtime, "attest_internal_target"), \
             patch.object(server.threading, "Thread", InlineThread), \
             patch.object(scheduler_runtime, "keepalive", return_value=DummyKeepalive()), \
             patch.object(server, "start_reference_refresh", side_effect=nazk_failure), \
             patch.object(server, "sync_violation_reports_worker", side_effect=RuntimeError("synthetic appeals failure")):
            self.assertTrue(server.start_prozorro_sync(Mock(side_effect=RuntimeError("synthetic prozorro failure")),
                mode="full", message="manual", manual_authorized=True, actor="sandbox.admin"))
            self.assertTrue(server.start_violation_reports_sync(manual_authorized=True, actor="sandbox.admin"))
            self.assertTrue(server.start_nazk_registry_refresh(manual_authorized=True, actor="sandbox.admin"))
        with closing(sqlite3.connect(self.path)) as con:
            state = dict((row[0], row[1:]) for row in con.execute(
                "SELECT job_key,last_started_at,last_finished_at,last_status,last_error FROM scheduler_job_state"))
            completed = con.execute("SELECT COUNT(*) FROM audit_log WHERE field_name='background_job.finished'").fetchone()[0]
        for key in scheduler_runtime.SCHEDULES:
            self.assertIsNotNone(state[key][0])
            self.assertIsNotNone(state[key][1])
            self.assertEqual(state[key][2], "error")
            self.assertTrue(state[key][3])
        self.assertEqual(completed, 3)
        self.assertTrue(background_jobs.disabled())

    def test_manual_authorization_cannot_be_reused_for_scheduled_or_actorless_runs(self):
        for key in scheduler_runtime.SCHEDULES:
            self.assertIsNone(scheduler_runtime.claim(str(self.path), key, trigger="scheduled",
                manual_authorized=True, actor="sandbox.admin"))
            self.assertIsNone(scheduler_runtime.claim(str(self.path), key, trigger="manual",
                manual_authorized=True, actor=""))
        self.assertTrue(background_jobs.disabled())

    def test_all_three_manual_refresh_entrypoints_claim_only_after_sandbox_attestation(self):
        before = self._settings()
        fake_thread = Mock()
        class DummyKeepalive:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
        with patch.object(server, "DB_PATH", self.path), patch.object(server, "SANDBOX_MODE", True), \
             patch.object(sandbox_runtime, "attest_internal_target"), \
             patch.object(server.threading, "Thread", return_value=fake_thread), \
             patch.object(scheduler_runtime, "keepalive", return_value=DummyKeepalive()), \
             patch.object(server, "start_reference_refresh", return_value=True) as nazk_start:
            self.assertTrue(server.start_prozorro_sync(Mock(), mode="full", message="manual",
                manual_authorized=True, actor="sandbox.admin"))
            self.assertTrue(server.start_violation_reports_sync(manual_authorized=True, actor="sandbox.admin"))
            self.assertTrue(server.start_nazk_registry_refresh(manual_authorized=True, actor="sandbox.admin"))
            self.assertEqual(fake_thread.start.call_count, 2)
            nazk_start.assert_called_once()
            self.assertTrue(nazk_start.call_args.kwargs["manual_authorized"])
        self.assertEqual(self._settings(), before)
        with closing(sqlite3.connect(self.path)) as con:
            claimed = {row[0] for row in con.execute("SELECT job_key FROM scheduler_job_leases")}
            actors = {row[0] for row in con.execute("SELECT changed_by FROM audit_log WHERE field_name='background_job.started'")}
        self.assertEqual(claimed, {"prozorro", "violation_reports", "nazk_registry"})
        self.assertEqual(actors, {"sandbox.admin"})
        with closing(sqlite3.connect(self.path)) as con:
            owners = dict(con.execute("SELECT job_key,owner_id FROM scheduler_job_leases"))
        for key, owner in owners.items():
            scheduler_runtime.release(str(self.path), key, owner)

    def test_manual_entrypoints_without_authenticated_actor_stay_blocked(self):
        with patch.object(server, "SANDBOX_MODE", True), \
             patch.object(sandbox_runtime, "attest_internal_target"), \
             patch.object(scheduler_runtime, "claim", side_effect=AssertionError("claim must not run")):
            self.assertFalse(server.start_prozorro_sync(Mock(), mode="full", message="", manual_authorized=True))
            self.assertFalse(server.start_violation_reports_sync(manual_authorized=True))
            self.assertFalse(server.start_nazk_registry_refresh(manual_authorized=True))

    def test_handler_authorization_and_explicit_confirmation_for_manual_refresh_routes(self):
        class FakeHandler:
            command = "POST"
            client_address = ("127.0.0.1", 1)
            headers = {"Content-Length": "20"}
            auth_user = "sandbox.admin"
            auth_role = "admin"
            auth_officer_id = None
            def __init__(self, path, payload, permissions):
                self.path = path
                self.payload = payload
                self.rfile = io.BytesIO(json.dumps(payload).encode())
                self.auth_access = {"active": True, "permissions": permissions}
                self.response = None
            def _authorize(self): return True
            def read_json(self): return self.payload
            def send_json(self, body, status=200): self.response = (status, body)
            def _do_POST(self): return server.Handler._do_POST(self)

        routes = [
            ("/api/sync", "prozorro.update", "start_prozorro_sync"),
            ("/api/frameworks/refresh", "prozorro.update", "start_prozorro_sync"),
            ("/api/violation-reports/sync", "appeals.update", "start_violation_reports_sync"),
            ("/api/nazk-registry/refresh", "references.update", "start_nazk_registry_refresh"),
        ]
        for path, permission, starter_name in routes:
            self.assertEqual(auth_access.permission_key("POST", path), permission)
            denied = FakeHandler(path, {"confirmed": True}, {permission: False})
            with patch.object(server, "SANDBOX_MODE", True), patch.object(sandbox_runtime, "attest_internal_target"), \
                 patch.object(server, "db", return_value=nullcontext(self.con)), \
                 patch.object(auth_access, "effective", return_value=denied.auth_access), \
                 patch.object(server, starter_name) as starter:
                server.Handler._dispatch(denied, denied._do_POST)
                self.assertEqual(denied.response[0], 403)
                starter.assert_not_called()
            unconfirmed = FakeHandler(path, {}, {permission: True})
            with patch.object(server, "SANDBOX_MODE", True), patch.object(sandbox_runtime, "attest_internal_target"), \
                 patch.object(server, "db", return_value=nullcontext(self.con)), \
                 patch.object(auth_access, "effective", return_value=unconfirmed.auth_access), \
                 patch.object(server, starter_name) as starter:
                server.Handler._dispatch(unconfirmed, unconfirmed._do_POST)
                self.assertEqual(unconfirmed.response[0], 400)
                starter.assert_not_called()
            allowed = FakeHandler(path, {"confirmed": True}, {permission: True})
            with patch.object(server, "SANDBOX_MODE", True), patch.object(sandbox_runtime, "attest_internal_target"), \
                 patch.object(auth_access, "effective", return_value=allowed.auth_access), \
                 patch.object(server, "db", return_value=nullcontext(self.con)), \
                 patch.object(server, starter_name, return_value=True) as starter:
                server.Handler._dispatch(allowed, allowed._do_POST)
                self.assertEqual(allowed.response[0], 202)
                starter.assert_called_once()
                self.assertTrue(starter.call_args.kwargs["manual_authorized"])
                self.assertEqual(starter.call_args.kwargs["actor"], "sandbox.admin")

    def test_google_writer_manual_execution_keeps_ticket_and_parallel_guards(self):
        client = Mock()
        client.invoke.return_value = {"status": "COMPLETE"}
        with patch.object(google_writer_execution.background_jobs, "disabled", return_value=True):
            run_id = "b" * 32
            claimed = google_writer_execution.claim_run(str(self.path), "SANDBOX", run_id,
                "sandbox.admin", "manual", manual_authorized=True)
            self.assertTrue(claimed["claimed"])
            self.assertEqual(google_writer_execution.claim_run(str(self.path), "SANDBOX", "c" * 32,
                "other", "manual", manual_authorized=True)["status"], "another_run_or_unknown_outcome")
            result = google_writer_execution.execute_claimed(str(self.path), client, run_id,
                "sandbox.admin", digest="d" * 64, manual_authorized=True)
            self.assertEqual(result["status"], "COMPLETE")
            self.assertEqual([call.args[0] for call in client.invoke.call_args_list], ["apply"])
            with self.assertRaises(google_writer_execution.ExecutionConfigurationError):
                google_writer_execution.ExecutionClient("SANDBOX", "x" * 24, "s" * 32,
                    lambda _env: {}, configured=True).invoke("preview", "e" * 32, "sandbox.admin")
        with closing(sqlite3.connect(self.path)) as con:
            schedule = con.execute("SELECT enabled,revision FROM google_writer_settings").fetchone()
        self.assertEqual(schedule, (0, 0))
        self.assertTrue(background_jobs.disabled())

    def test_google_writer_http_apply_without_preview_ticket_is_rejected(self):
        class FakeHandler:
            command = "POST"
            client_address = ("127.0.0.1", 1)
            headers = {"Content-Length": "40"}
            auth_user = "sandbox.admin"
            auth_role = "admin"
            auth_officer_id = None
            path = "/api/google-writer/apply"
            def __init__(self, permissions):
                self.payload = {"confirmed": True}
                self.rfile = io.BytesIO(json.dumps(self.payload).encode())
                self.auth_access = {"active": True, "permissions": permissions}
                self.response = None
            def _authorize(self): return True
            def read_json(self): return self.payload
            def send_json(self, body, status=200): self.response = (status, body)
            def _do_POST(self): return server.Handler._do_POST(self)

        permission = "google.writer.execute"
        self.assertEqual(auth_access.permission_key("POST", "/api/google-writer/apply"), permission)
        denied = FakeHandler({permission: False})
        with patch.object(server, "SANDBOX_MODE", True), patch.object(server, "db", return_value=nullcontext(self.con)), \
             patch.object(sandbox_runtime, "attest_internal_target"), \
             patch.object(auth_access, "effective", return_value=denied.auth_access), \
             patch.object(server, "google_writer_client") as client:
            server.Handler._dispatch(denied, denied._do_POST)
            self.assertEqual(denied.response[0], 403)
            client.assert_not_called()
        allowed = FakeHandler({permission: True})
        with patch.object(server, "SANDBOX_MODE", True), patch.object(server, "db", return_value=nullcontext(self.con)), \
             patch.object(sandbox_runtime, "attest_internal_target"), \
             patch.object(auth_access, "effective", return_value=allowed.auth_access), \
             patch.object(server, "google_writer_manual_available", return_value=True), \
             patch.object(server, "google_writer_client") as client, \
             patch.object(google_writer_execution, "claim_run") as claim:
            server.Handler._dispatch(allowed, allowed._do_POST)
            self.assertEqual(allowed.response[0], 409)
            client.assert_called_once()
            claim.assert_not_called()

    def test_google_writer_stale_sandbox_preview_requires_new_confirmation_before_claim(self):
        request_id = "a" * 32
        old_digest = google_writer_execution.base64.urlsafe_b64encode(b"o" * 32).decode().rstrip("=")
        new_digest = google_writer_execution.base64.urlsafe_b64encode(b"n" * 32).decode().rstrip("=")
        details = {"version": 1, "environment": "SANDBOX", "plan_digest": old_digest,
            "append_only_digest": old_digest, "counts": {"append": 0, "update": 0, "conflict": 0, "error": 0},
            "appends": [], "updates": [], "conflicts": [], "errors": []}
        google_writer_execution.store_preview_plan(str(self.path), request_id, "sandbox.admin", details)
        client = Mock()
        client.environment = "SANDBOX"
        client.shared_secret = "s" * 40
        client.validate.return_value = None
        ticket = google_writer_execution.preview_ticket(client, request_id, "sandbox.admin", old_digest,
            plan_scope="ALL", parent_digest=old_digest,
            details_digest=google_writer_execution._preview_details_digest(details))
        fresh = dict(details, plan_digest=new_digest, append_only_digest=new_digest)
        invocations = []
        def invoke(action, preview_id, _actor, **_kwargs):
            invocations.append((action, preview_id))
            return {"status": "PREVIEW", "digest": new_digest, "planDetails": fresh}
        client.invoke.side_effect = invoke

        class FakeHandler:
            command = "POST"
            client_address = ("127.0.0.1", 1)
            headers = {"Content-Length": "1"}
            auth_user = "sandbox.admin"
            auth_role = "admin"
            auth_officer_id = None
            path = "/api/google-writer/apply"
            auth_access = {"active": True, "permissions": {"google.writer.execute": True}}
            def __init__(self): self.payload = {"ticket": ticket, "confirmed": True}; self.response = None
            def _authorize(self): return True
            def read_json(self): return self.payload
            def send_json(self, body, status=200): self.response = (status, body)
            def _do_POST(self): return server.Handler._do_POST(self)
        handler = FakeHandler()
        with patch.object(server, "DB_PATH", self.path), patch.object(server, "SANDBOX_MODE", True), \
             patch.object(server, "google_writer_environment", return_value="SANDBOX"), \
             patch.object(server, "db", return_value=nullcontext(self.con)), \
             patch.object(sandbox_runtime, "attest_internal_target"), \
             patch.object(auth_access, "effective", return_value=handler.auth_access), \
             patch.object(server, "google_writer_manual_available", return_value=True), \
             patch.object(server, "google_writer_client", return_value=client), \
             patch.object(google_writer_execution, "claim_run") as claim, \
             patch.object(server.threading, "Thread") as worker:
            server.Handler._dispatch(handler, handler._do_POST)
        self.assertEqual(handler.response[0], 409)
        self.assertEqual(handler.response[1]["status"], "PREVIEW_STALE_RECONFIRM")
        self.assertFalse(handler.response[1]["started"])
        self.assertEqual(len(invocations), 2, "the live plan is checked, then a new Preview is frozen")
        self.assertEqual(invocations[0], ("preview", request_id))
        self.assertNotEqual(invocations[1][1], request_id)
        claim.assert_not_called()
        worker.assert_not_called()

    def test_google_writer_status_reports_manual_readiness_without_enabling_automation(self):
        with patch.object(server, "DB_PATH", self.path), \
             patch.object(server, "google_writer_manual_available", return_value=True), \
             patch.object(server, "google_writer_available", return_value=False):
            status = server.google_writer_status()
        self.assertTrue(status["channel_ready"])
        self.assertTrue(status["manual_available"])
        self.assertTrue(status["automation_blocked"])
        self.assertFalse(status["enabled"])
        self.assertFalse(status["configured_enabled"])

    def test_ui_marks_manual_actions_separately_and_requires_confirmation(self):
        app = (Path(__file__).parent / "app.js").read_text(encoding="utf-8")
        writer_ui = (Path(__file__).parent / "google_writer_ui.js").read_text(encoding="utf-8")
        self.assertIn("Запустити ручне оновлення заявок Prozorro", app)
        self.assertIn("Запустити ручне оновлення звернень", app)
        self.assertIn("Запустити ручне отримання актуального реєстру НАЗК", app)
        self.assertIn("last_trigger==='manual'?'Ручний запуск'", app)
        self.assertIn("Автоматику вимкнено · ручний Preview → Apply доступний", writer_ui)
        self.assertIn("background_jobs.disabled()", Path(__file__).parent.joinpath("server.py").read_text(encoding="utf-8"))

    def test_global_interlock_rejects_schedule_enable_but_allows_safe_disable(self):
        @contextmanager
        def scoped_db():
            con = sqlite3.connect(self.path)
            con.row_factory = sqlite3.Row
            try:
                yield con
                con.commit()
            except Exception:
                con.rollback()
                raise
            finally:
                con.close()
        with patch.object(server, "DB_PATH", self.path), patch.object(server, "SANDBOX_MODE", True), \
             patch.object(server, "db", side_effect=scoped_db), \
             patch.object(sandbox_runtime, "attest_internal_target"), \
             patch.object(server, "register_scheduler_job") as register, \
             patch.object(server, "unregister_scheduler_job") as unregister:
            with self.assertRaisesRegex(ValueError, "interlock"):
                server.set_scheduler_job_enabled("prozorro", True, "sandbox.admin")
            result = server.set_scheduler_job_enabled("prozorro", False, "sandbox.admin")
        self.assertFalse(result["configured_enabled"])
        register.assert_not_called()
        unregister.assert_called_once_with("prozorro")
        self.assertTrue(background_jobs.disabled())


if __name__ == "__main__":
    unittest.main(verbosity=2)
