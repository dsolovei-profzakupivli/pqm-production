import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
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
        fake_thread = unittest.mock.MagicMock()
        with patch.object(server.threading, "Thread", return_value=fake_thread):
            self.assertTrue(server.register_scheduler_job("prozorro", lambda: None))
            self.assertFalse(server.register_scheduler_job("prozorro", lambda: None))
        fake_thread.start.assert_called_once()


if __name__ == "__main__":
    unittest.main()
