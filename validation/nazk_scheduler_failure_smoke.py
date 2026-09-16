"""NAZK fetch failure releases its job lease; synthetic/offline fixtures only."""
import json
import sqlite3
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import web_smoke as web
import reference_directories as refs
s = web.server


class FailureRecovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        web.fixture()

    def test_fetch_error_finishes_lease_without_workflow_and_allows_retry(self):
        finished = threading.Event()
        real_finish = s._finish_scheduler_lease
        def finish(*args):
            real_finish(*args)
            finished.set()
        with patch.object(refs, '_fetch', side_effect=RuntimeError('synthetic HTTP 403')), \
             patch.object(s, 'rebuild_nazk_tasks') as workflow, \
             patch.object(s, '_finish_scheduler_lease', side_effect=finish):
            self.assertTrue(s.start_nazk_registry_refresh(trigger='synthetic'))
            self.assertTrue(finished.wait(5))
            workflow.assert_not_called()
        with s.db() as con:
            self.assertEqual(0, con.execute('SELECT COUNT(*) FROM scheduler_job_leases').fetchone()[0])
            row = con.execute("SELECT last_status,last_error FROM scheduler_job_state WHERE job_key='nazk_registry'").fetchone()
            self.assertEqual(tuple(row), ('error', 'synthetic HTTP 403'))
            self.assertEqual(0, con.execute('SELECT COUNT(*) FROM supplier_nazk_checks').fetchone()[0])
        owner = s.scheduler_runtime.claim(s.DB_PATH, 'nazk_registry', trigger='synthetic_retry')
        self.assertTrue(owner)
        s.scheduler_runtime.release(s.DB_PATH, 'nazk_registry', owner)

    def test_status_write_failure_still_calls_failure_cleanup_only(self):
        success, failure = Mock(), Mock()
        with patch.object(refs, '_state', side_effect=sqlite3.OperationalError('synthetic locked')):
            with self.assertRaises(sqlite3.OperationalError):
                refs.refresh_nazk(s.DB_PATH, success, failure)
        success.assert_not_called()
        failure.assert_called_once_with('synthetic locked')
        self.assertFalse(refs.LOCK.locked())

    def test_busy_worker_reports_failure_without_unlocking_other_worker(self):
        success, failure = Mock(), Mock()
        refs.LOCK.acquire()
        try:
            refs.refresh_nazk(s.DB_PATH, success, failure)
            self.assertTrue(refs.LOCK.locked())
        finally:
            refs.LOCK.release()
        success.assert_not_called()
        failure.assert_called_once()

    def test_success_callback_remains_success_only(self):
        success, failure = Mock(), Mock()
        payload = json.dumps([{'id': 'synthetic-source', 'indLastNameOnOffenseMoment': 'SYNTHETIC'}]).encode()
        with patch.object(refs, '_fetch', return_value=payload):
            refs.refresh_nazk(s.DB_PATH, success, failure)
        success.assert_called_once_with()
        failure.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
