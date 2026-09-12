import sqlite3
import tempfile
import threading
import unittest
import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import scheduler_runtime as runtime
import server


class SchedulerRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = Path(self.temp.name) / "scheduler.sqlite3"
        with sqlite3.connect(self.db) as con:
            runtime.migrate(con)
            server.auth_access.migrate(con)
            con.execute("""CREATE TABLE IF NOT EXISTS audit_log(
              id INTEGER PRIMARY KEY, submission_id TEXT, changed_at TEXT, changed_by TEXT,
              field_name TEXT, old_value TEXT, new_value TEXT)""")

    def tearDown(self):
        self.temp.cleanup()

    def test_hourly_runs_at_minute_five_in_kyiv(self):
        kyiv = ZoneInfo("Europe/Kyiv")
        self.assertEqual(runtime.next_hourly_run(datetime(2026, 1, 12, 8, 4, tzinfo=kyiv)).isoformat(),
                         "2026-01-12T08:05:00+02:00")
        self.assertEqual(runtime.next_hourly_run(datetime(2026, 7, 12, 8, 5, tzinfo=kyiv)).isoformat(),
                         "2026-07-12T09:05:00+03:00")

    def test_nazk_weekdays_and_no_weekend_run(self):
        kyiv = ZoneInfo("Europe/Kyiv")
        friday = datetime(2026, 9, 11, 9, 19, tzinfo=kyiv)
        saturday = datetime(2026, 9, 12, 8, 0, tzinfo=kyiv)
        self.assertEqual(runtime.next_nazk_run(friday).isoformat(), "2026-09-11T09:20:00+03:00")
        self.assertEqual(runtime.next_nazk_run(saturday).isoformat(), "2026-09-14T09:20:00+03:00")
        self.assertFalse(runtime.nazk_due_today(saturday, None))

    def test_dst_is_resolved_by_europe_kyiv_zone(self):
        winter = runtime.next_nazk_run(datetime(2026, 1, 12, 8, 0, tzinfo=timezone.utc))
        summer = runtime.next_nazk_run(datetime(2026, 7, 13, 5, 0, tzinfo=timezone.utc))
        self.assertEqual(winter.utcoffset().total_seconds(), 7200)
        self.assertEqual(summer.utcoffset().total_seconds(), 10800)
        self.assertEqual((winter.hour, summer.hour), (9, 9))

    def test_disabled_job_has_no_misleading_next_run(self):
        items = {row["job"]: row for row in runtime.state(self.db, {
            "prozorro": False, "violation_reports": True, "nazk_registry": False,
        }, datetime(2026, 9, 11, 6, 0, tzinfo=timezone.utc))}
        self.assertIsNone(items["prozorro"]["next_run"])
        self.assertIsNotNone(items["violation_reports"]["next_run"])
        self.assertIsNone(items["nazk_registry"]["next_run"])

    def test_environment_defaults_enable_local_and_web_test_but_not_prod(self):
        for environment in ("local", "test", "test_web", "web"):
            self.assertTrue(runtime.enabled_by_default(environment))
        self.assertFalse(runtime.enabled_by_default("production"))

    def test_two_instance_contention_and_expired_lease_recovery(self):
        at = datetime(2026, 9, 11, 6, 0, tzinfo=timezone.utc)
        first = runtime.claim(self.db, "prozorro", trigger="scheduled", now=at,
                              lease_seconds=30, owner_id="one")
        blocked = runtime.claim(self.db, "prozorro", trigger="manual", now=at, owner_id="two")
        recovered = runtime.claim(self.db, "prozorro", trigger="scheduled",
                                  now=datetime(2026, 9, 11, 6, 1, tzinfo=timezone.utc), owner_id="two")
        self.assertEqual(first, "one")
        self.assertIsNone(blocked)
        self.assertEqual(recovered, "two")

    def test_manual_and_scheduled_overlap_but_different_jobs_do_not_block(self):
        at = datetime(2026, 9, 11, 6, 0, tzinfo=timezone.utc)
        self.assertEqual(runtime.claim(self.db, "violation_reports", trigger="manual", now=at,
                                       owner_id="manual"), "manual")
        self.assertIsNone(runtime.claim(self.db, "violation_reports", trigger="scheduled", now=at,
                                        owner_id="scheduled"))
        self.assertEqual(runtime.claim(self.db, "prozorro", trigger="scheduled", now=at,
                                       owner_id="prozorro"), "prozorro")

    def test_persisted_daily_state_prevents_nazk_restart_duplicate(self):
        kyiv = ZoneInfo("Europe/Kyiv")
        now = datetime(2026, 9, 11, 10, 0, tzinfo=kyiv)
        self.assertTrue(runtime.nazk_due_today(now, None))
        self.assertFalse(runtime.nazk_due_today(now, "2026-09-11T06:30:00+00:00"))
        self.assertTrue(runtime.hourly_catchup_due(now, "2026-09-11T05:00:00+00:00"))

    def test_registration_is_idempotent_per_process(self):
        server.REGISTERED_SCHEDULER_JOBS.clear()
        server.SCHEDULER_STOP_EVENTS.clear()
        server.SCHEDULER_THREADS.clear()
        fake_thread = unittest.mock.MagicMock()
        with patch.object(server.threading, "Thread", return_value=fake_thread):
            self.assertTrue(server.register_scheduler_job("prozorro", lambda: None))
            self.assertFalse(server.register_scheduler_job("prozorro", lambda: None))
        fake_thread.start.assert_called_once()

    def test_runtime_setting_overrides_environment_and_persists(self):
        defaults = {"prozorro": True, "violation_reports": True, "nazk_registry": True}
        with sqlite3.connect(self.db) as con:
            runtime.save_enabled(con, "prozorro", False, "admin")
        with sqlite3.connect(self.db) as con:
            effective = runtime.effective_enabled(con, defaults)
            sources = runtime.setting_sources(con)
        self.assertFalse(effective["prozorro"])
        self.assertTrue(effective["violation_reports"])
        self.assertEqual(sources["prozorro"], "runtime")
        self.assertEqual(sources["violation_reports"], "environment")

    def test_admin_enable_registers_without_immediate_catchup_and_is_audited(self):
        started = threading.Event()
        observed = []

        def fake_job(stop_event, *, catch_up=True):
            observed.append(catch_up)
            started.set()
            stop_event.wait(2)

        server.REGISTERED_SCHEDULER_JOBS.clear()
        server.SCHEDULER_STOP_EVENTS.clear()
        server.SCHEDULER_THREADS.clear()
        defaults = {"prozorro": False, "violation_reports": False, "nazk_registry": False}
        with patch.object(server, "DB_PATH", self.db), \
             patch.object(server, "scheduler_environment_defaults", return_value=defaults), \
             patch.object(server, "SCHEDULER_TARGETS", {"prozorro": fake_job}):
            item = server.set_scheduler_job_enabled("prozorro", True, "Administrator")
            self.assertTrue(started.wait(1))
            self.assertTrue(item["enabled"])
            self.assertTrue(item["registered"])
            self.assertEqual(observed, [False])
            again = server.set_scheduler_job_enabled("prozorro", True, "Administrator")
            self.assertTrue(again["enabled"])
            self.assertEqual(observed, [False])
            server.unregister_scheduler_job("prozorro")
        with sqlite3.connect(self.db) as con:
            self.assertEqual(con.execute(
                "SELECT enabled,updated_by FROM scheduler_job_settings WHERE job_key='prozorro'"
            ).fetchone(), (1, "Administrator"))
            audit = con.execute(
                "SELECT old_value,new_value FROM audit_log WHERE submission_id='scheduler_job:prozorro'"
            ).fetchone()
            audit_count = con.execute(
                "SELECT COUNT(*) FROM audit_log WHERE submission_id='scheduler_job:prozorro'"
            ).fetchone()[0]
        self.assertEqual(audit, ("disabled", "enabled"))
        self.assertEqual(audit_count, 1)

    def test_unregister_stops_only_selected_job(self):
        started = {key: threading.Event() for key in ("prozorro", "violation_reports")}

        def job(key):
            def run(stop_event, *, catch_up=True):
                started[key].set()
                stop_event.wait(2)
            return run

        server.REGISTERED_SCHEDULER_JOBS.clear()
        server.SCHEDULER_STOP_EVENTS.clear()
        server.SCHEDULER_THREADS.clear()
        server.register_scheduler_job("prozorro", job("prozorro"), catch_up=False)
        server.register_scheduler_job("violation_reports", job("violation_reports"), catch_up=False)
        self.assertTrue(started["prozorro"].wait(1))
        self.assertTrue(started["violation_reports"].wait(1))
        self.assertTrue(server.unregister_scheduler_job("prozorro"))
        self.assertNotIn("prozorro", server.REGISTERED_SCHEDULER_JOBS)
        self.assertIn("violation_reports", server.REGISTERED_SCHEDULER_JOBS)
        server.unregister_scheduler_job("violation_reports")

    def test_admin_disable_unregisters_job_and_removes_next_run(self):
        started = threading.Event()
        stopped = threading.Event()

        def fake_job(stop_event, *, catch_up=True):
            started.set()
            stop_event.wait(2)
            stopped.set()

        server.REGISTERED_SCHEDULER_JOBS.clear()
        server.SCHEDULER_STOP_EVENTS.clear()
        server.SCHEDULER_THREADS.clear()
        defaults = {"prozorro": True, "violation_reports": False, "nazk_registry": False}
        with patch.object(server, "DB_PATH", self.db), \
             patch.object(server, "scheduler_environment_defaults", return_value=defaults), \
             patch.object(server, "SCHEDULER_TARGETS", {"prozorro": fake_job}):
            server.register_scheduler_job("prozorro", fake_job, catch_up=True)
            self.assertTrue(started.wait(1))
            item = server.set_scheduler_job_enabled("prozorro", False, "Administrator")
            self.assertTrue(stopped.wait(1))
            self.assertFalse(item["enabled"])
            self.assertFalse(item["registered"])
            self.assertIsNone(item["next_run"])
        with sqlite3.connect(self.db) as con:
            self.assertEqual(con.execute(
                "SELECT enabled FROM scheduler_job_settings WHERE job_key='prozorro'"
            ).fetchone()[0], 0)

    def test_admin_ui_exposes_independent_scheduler_actions(self):
        app = Path("app.js").read_text(encoding="utf-8")
        self.assertIn("/admin/scheduler-jobs/", app)
        self.assertIn("schedulerEnableConfirmations", app)
        self.assertIn("data-scheduler-job", app)
        self.assertIn("canManage=role()==='admin'", app)

    def test_viewer_cannot_toggle_scheduler(self):
        self.assertTrue(server.mutation_allowed("admin", "POST", "/api/admin/scheduler-jobs/prozorro"))
        self.assertFalse(server.mutation_allowed("viewer", "POST", "/api/admin/scheduler-jobs/prozorro"))

    def test_admin_toggle_endpoint_returns_factual_state_without_running_job(self):
        started = threading.Event()

        def fake_job(stop_event, *, catch_up=True):
            self.assertFalse(catch_up)
            started.set()
            stop_event.wait(2)

        server.REGISTERED_SCHEDULER_JOBS.clear()
        server.SCHEDULER_STOP_EVENTS.clear()
        server.SCHEDULER_THREADS.clear()
        defaults = {"prozorro": False, "violation_reports": False, "nazk_registry": False}
        with patch.object(server, "DB_PATH", self.db), \
             patch.object(server, "scheduler_environment_defaults", return_value=defaults), \
             patch.object(server, "SCHEDULER_TARGETS", {"prozorro": fake_job}):
            http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
            thread = threading.Thread(target=http.serve_forever, daemon=True)
            thread.start()
            url = f"http://127.0.0.1:{http.server_port}/api/admin/scheduler-jobs/prozorro"
            try:
                request = urllib.request.Request(url, data=json.dumps({"enabled": True}).encode(),
                    headers={"Content-Type": "application/json", "X-PQM-Local-Role": "admin"}, method="POST")
                with urllib.request.urlopen(request) as response:
                    payload = json.load(response)
                self.assertTrue(payload["job"]["enabled"])
                self.assertTrue(payload["job"]["registered"])
                self.assertIsNotNone(payload["job"]["next_run"])
                self.assertTrue(started.wait(1))

                forbidden = urllib.request.Request(url, data=json.dumps({"enabled": False}).encode(),
                    headers={"Content-Type": "application/json", "X-PQM-Local-Role": "viewer"}, method="POST")
                with self.assertRaises(urllib.error.HTTPError) as blocked:
                    urllib.request.urlopen(forbidden)
                self.assertEqual(blocked.exception.code, 403)
            finally:
                server.unregister_scheduler_job("prozorro")
                http.shutdown()
                http.server_close()

    def test_startup_applies_persisted_overrides_independently(self):
        started = threading.Event()

        def fake_job(stop_event, *, catch_up=True):
            started.set()
            stop_event.wait(2)

        with sqlite3.connect(self.db) as con:
            runtime.save_enabled(con, "prozorro", False, "admin")
            runtime.save_enabled(con, "violation_reports", True, "admin")
        server.REGISTERED_SCHEDULER_JOBS.clear()
        server.SCHEDULER_STOP_EVENTS.clear()
        server.SCHEDULER_THREADS.clear()
        defaults = {"prozorro": True, "violation_reports": False, "nazk_registry": False}
        with patch.object(server, "DB_PATH", self.db), \
             patch.object(server, "scheduler_environment_defaults", return_value=defaults), \
             patch.object(server, "SCHEDULER_TARGETS", {
                 "prozorro": fake_job, "violation_reports": fake_job,
             }):
            effective = server.apply_scheduler_settings(catch_up=True)
            self.assertFalse(effective["prozorro"])
            self.assertTrue(effective["violation_reports"])
            self.assertTrue(started.wait(1))
            self.assertNotIn("prozorro", server.REGISTERED_SCHEDULER_JOBS)
            self.assertIn("violation_reports", server.REGISTERED_SCHEDULER_JOBS)
            server.unregister_scheduler_job("violation_reports")

    def test_persistent_disable_interrupts_other_process_wait_before_run(self):
        # Keep enough headroom for a full-suite run on a busy Windows host.
        # The assertion exercises persistent-disable interruption, not a 20 ms deadline.
        target = datetime.now(timezone.utc) + timedelta(seconds=1)
        with patch.object(server, "_scheduler_is_configured", return_value=False):
            self.assertTrue(server._wait_until(target, threading.Event(), "prozorro"))


if __name__ == "__main__":
    unittest.main()
