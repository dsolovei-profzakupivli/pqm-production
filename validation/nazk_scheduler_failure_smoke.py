"""NAZK fetch failure releases its job lease; synthetic/offline fixtures only."""
import json
import io
import inspect
import os
import sqlite3
import sys
import threading
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import web_smoke as web
import reference_directories as refs
import sandbox_runtime
s = web.server


class FailureRecovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        web.fixture()

    def test_fetch_error_finishes_lease_without_workflow_and_allows_retry(self):
        finished = threading.Event()
        real_finish = s._finish_scheduler_lease
        def finish(*args, **kwargs):
            real_finish(*args, **kwargs)
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

    def _reference_db(self):
        temporary = tempfile.TemporaryDirectory(prefix='pqm-nazk-recovery-')
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / 'synthetic.sqlite3'
        refs.init_reference_tables(path)
        with sqlite3.connect(path) as con:
            s.scheduler_runtime.migrate(con)
        return path

    def test_restart_stale_running_projection_is_read_only_and_retryable(self):
        path = self._reference_db()
        refs.NAZK_ACTIVE.discard(str(path.resolve()))
        refs._state(path, 'nazk', 'running', 'synthetic process interrupted')
        with sqlite3.connect(path) as con:
            before = tuple(con.execute("SELECT status,message,updated_at FROM reference_sync_state WHERE source='nazk'").fetchone())
        status = refs.reference_status(path)['nazk']
        self.assertEqual(status['status'], 'error')
        self.assertTrue(status['interrupted'])
        self.assertEqual(status['interrupted_message'], 'synthetic process interrupted')
        with sqlite3.connect(path) as con:
            after = tuple(con.execute("SELECT status,message,updated_at FROM reference_sync_state WHERE source='nazk'").fetchone())
            self.assertEqual(con.execute("SELECT COUNT(*) FROM scheduler_job_leases").fetchone()[0], 0)
        self.assertEqual(after, before, 'GET-like projection must not update the database')

        owner = s.scheduler_runtime.claim(path, 'nazk_registry', trigger='synthetic_restart_retry')
        self.assertTrue(owner)
        with patch.object(refs.threading, 'Timer') as timer:
            timer.return_value.start.return_value = None
            self.assertTrue(refs.start_reference_refresh(path, 'nazk', lease_owner=owner))
            self.assertFalse(refs.start_reference_refresh(path, 'nazk', lease_owner=owner))
        timer.assert_called_once()
        self.assertTrue(s.scheduler_runtime.finish(path, 'nazk_registry', owner))
        with refs.NAZK_ACTIVE_LOCK:
            refs.NAZK_ACTIVE.discard(str(path.resolve()))

    def test_live_lease_from_another_process_keeps_running_status(self):
        path = self._reference_db()
        refs.NAZK_ACTIVE.discard(str(path.resolve()))
        owner = s.scheduler_runtime.claim(path, 'nazk_registry', trigger='synthetic_other_process')
        self.assertTrue(owner)
        refs._state(path, 'nazk', 'running', 'synthetic active worker')
        status = refs.reference_status(path)['nazk']
        self.assertEqual(status['status'], 'running')
        self.assertNotIn('interrupted', status)
        self.assertFalse(refs.start_reference_refresh(path, 'nazk'))
        self.assertTrue(s.scheduler_runtime.finish(path, 'nazk_registry', owner))

    def test_expired_lease_projects_interrupted_without_changing_amcu(self):
        path = self._reference_db()
        refs.NAZK_ACTIVE.discard(str(path.resolve()))
        expired = datetime.now(timezone.utc) - timedelta(minutes=5)
        owner = s.scheduler_runtime.claim(path, 'nazk_registry', trigger='synthetic_crash',
                                          now=expired, lease_seconds=60, owner_id='crashed-owner')
        self.assertEqual(owner, 'crashed-owner')
        refs._state(path, 'nazk', 'running', 'synthetic crashed fetch')
        refs._state(path, 'amcu', 'running', 'amcu state is out of scope')
        status = refs.reference_status(path)
        self.assertEqual(status['nazk']['status'], 'error')
        self.assertTrue(status['nazk']['interrupted'])
        self.assertEqual(status['amcu']['status'], 'error')
        self.assertTrue(status['amcu']['interrupted'])
        with sqlite3.connect(path) as con:
            self.assertEqual(con.execute("SELECT status FROM reference_sync_state WHERE source='nazk'").fetchone()[0], 'running')
            self.assertEqual(con.execute("SELECT status FROM reference_sync_state WHERE source='amcu'").fetchone()[0], 'running')

    def test_owner_replacement_during_fetch_fences_registry_and_old_finish(self):
        path = self._reference_db()
        with sqlite3.connect(path) as con:
            con.execute("INSERT INTO nazk_registry(source_id,full_name,raw_json) VALUES('keep','SYNTHETIC OLD','{}')")
        old = s.scheduler_runtime.claim(path, 'nazk_registry', trigger='synthetic_old', owner_id='old-owner')
        self.assertEqual(old, 'old-owner')
        payload = json.dumps([{'id': 'new', 'indLastNameOnOffenseMoment': 'SYNTHETIC NEW'}]).encode()
        def replace_owner_then_return(_url):
            with sqlite3.connect(path) as con:
                con.execute("UPDATE scheduler_job_leases SET lease_until=? WHERE job_key='nazk_registry'",
                            ((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),))
            new = s.scheduler_runtime.claim(path, 'nazk_registry', trigger='synthetic_replacement', owner_id='new-owner')
            self.assertEqual(new, 'new-owner')
            return payload
        completed, failed = Mock(), Mock()
        with patch.dict(os.environ, {'PQM_SANDBOX': '0'}), \
             patch.object(refs, '_fetch', side_effect=replace_owner_then_return):
            refs.refresh_nazk(path, completed, failed, lease_owner=old)
        with sqlite3.connect(path) as con:
            records = con.execute('SELECT source_id,full_name FROM nazk_registry ORDER BY source_id').fetchall()
            lease = con.execute("SELECT owner_id FROM scheduler_job_leases WHERE job_key='nazk_registry'").fetchone()
        self.assertEqual(records, [('keep', 'SYNTHETIC OLD')])
        self.assertEqual(lease[0], 'new-owner')
        completed.assert_not_called()
        failed.assert_called_once()
        self.assertFalse(s.scheduler_runtime.finish(path, 'nazk_registry', old),
                         'old owner cannot finish or delete a replacement owner lease')
        self.assertTrue(s.scheduler_runtime.finish(path, 'nazk_registry', 'new-owner'))

    def test_same_payload_refresh_and_materialization_remain_idempotent(self):
        payload = json.dumps([{'id': 'synthetic-source', 'indLastNameOnOffenseMoment': 'SYNTHETIC'}]).encode()
        with patch.dict(os.environ, {'PQM_SANDBOX': '0'}), patch.object(refs, '_fetch', return_value=payload):
            refs.refresh_nazk(s.DB_PATH)
            refs.refresh_nazk(s.DB_PATH)
        with s.db() as con:
            first = s.operational_tasks.materialize_nazk_tasks(con, 'synthetic repeat one')
            second = s.operational_tasks.materialize_nazk_tasks(con, 'synthetic repeat two')
            self.assertEqual(con.execute("SELECT COUNT(*) FROM nazk_registry WHERE source_id='synthetic-source'").fetchone()[0], 1)
            self.assertEqual((first['created'], second['created']), (0, 0))

    def test_scheduler_lease_loss_is_detected_before_protected_write(self):
        path = self._reference_db()
        owner = s.scheduler_runtime.claim(path, 'nazk_registry', trigger='synthetic_expired',
                                          now=datetime.now(timezone.utc)-timedelta(minutes=5),
                                          lease_seconds=60, owner_id='expired-owner')
        self.assertEqual(owner, 'expired-owner')
        with sqlite3.connect(path) as con:
            with self.assertRaises(s.scheduler_runtime.LeaseLost):
                s.scheduler_runtime.require_current_lease(con, 'nazk_registry', owner)

    def test_replaced_owner_is_fenced_inside_the_sqlite_transaction(self):
        path = self._reference_db()
        old = s.scheduler_runtime.claim(path, 'nazk_registry', trigger='synthetic_old', owner_id='old-owner')
        with sqlite3.connect(path) as con:
            con.execute("UPDATE scheduler_job_leases SET lease_until=? WHERE job_key='nazk_registry'",
                        ((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),))
        new = s.scheduler_runtime.claim(path, 'nazk_registry', trigger='synthetic_new', owner_id='new-owner')
        self.assertEqual((old,new), ('old-owner','new-owner'))
        with sqlite3.connect(path) as con:
            con.execute('BEGIN IMMEDIATE')
            with self.assertRaises(s.scheduler_runtime.LeaseLost):
                s.scheduler_runtime.require_current_lease(con, 'nazk_registry', old)
            con.rollback()
        self.assertTrue(s.scheduler_runtime.finish(path, 'nazk_registry', new))

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

    def test_sandbox_fetch_uses_prod_budget_with_isolation_unchanged(self):
        self.assertEqual(inspect.signature(refs._fetch).parameters['timeout'].default, 900)
        with patch.dict(os.environ, {'PQM_SANDBOX': '1', 'PQM_SANDBOX_OPERATIONAL': '1',
                                     'PQM_SANDBOX_NAZK_READ': '1'}), \
             patch.object(sandbox_runtime.urllib.request, 'build_opener') as build:
            response = Mock()
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            response.read.return_value = b'[]'
            build.return_value.open.return_value = response
            self.assertEqual(sandbox_runtime.fetch_nazk_bytes(refs.NAZK_URL), b'[]')
            request = build.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, refs.NAZK_URL)
            self.assertEqual(request.get_method(), 'GET')
            self.assertNotIn('Authorization', request.headers)
            self.assertEqual(build.return_value.open.call_args.kwargs, {'timeout': 900})
            response.read.assert_called_once_with(128 * 1024 * 1024 + 1)
            proxy, redirect = build.call_args.args
            self.assertIsInstance(proxy, sandbox_runtime.urllib.request.ProxyHandler)
            self.assertEqual(proxy.proxies, {})
            self.assertIsInstance(redirect, sandbox_runtime._NoGoogleRedirect)
            with self.assertRaises(RuntimeError):
                redirect.redirect_request(None, None, 302, '', {}, 'https://example.invalid/')
            for invalid in (refs.NAZK_URL + '?token=secret',
                            refs.NAZK_URL.replace('corruptinfo.nazk.gov.ua', 'example.invalid')):
                with self.assertRaises(RuntimeError):
                    sandbox_runtime.fetch_nazk_bytes(invalid)
            self.assertEqual(build.return_value.open.call_count, 1)
            self.assertFalse(sandbox_runtime._egress.active)
            class Oversized:
                def __len__(self):
                    return 128 * 1024 * 1024 + 1
            response.read.return_value = Oversized()
            with self.assertRaisesRegex(RuntimeError, 'read limit'):
                sandbox_runtime.fetch_nazk_bytes(refs.NAZK_URL)
            self.assertFalse(sandbox_runtime._egress.active)
            build.return_value.open.side_effect = TimeoutError('synthetic read timeout')
            with self.assertRaises(TimeoutError):
                sandbox_runtime.fetch_nazk_bytes(refs.NAZK_URL)
            self.assertEqual(build.return_value.open.call_count, 3)  # one per invocation; no retry
            self.assertFalse(sandbox_runtime._egress.active)

    def test_sandbox_fetch_failure_logs_only_safe_phase_and_never_rebuilds(self):
        output = io.StringIO()
        success, failure = Mock(), Mock()
        secret = 'token=SECRET supplier=PERSON'
        with patch.dict(os.environ, {'PQM_SANDBOX': '1', 'PQM_SANDBOX_OPERATIONAL': '1',
                                     'PQM_SANDBOX_NAZK_READ': '1'}), \
             patch.object(sandbox_runtime, 'attest_internal_target'), \
             patch.object(sandbox_runtime, 'nazk_read_enabled', return_value=True), \
             patch.object(sandbox_runtime, 'fetch_nazk_bytes', side_effect=TimeoutError(secret)), \
             patch.object(refs, '_state') as state, \
             patch.object(refs.sqlite3, 'connect') as db_connect, \
             patch.object(refs.NAZK_SANDBOX_LOG.handlers[0], 'stream', output):
            refs.refresh_nazk('synthetic-sandbox-db', success, failure)
        self.assertIn('phase=fetch exception_type=TimeoutError', output.getvalue())
        self.assertNotIn('SECRET', output.getvalue())
        self.assertNotIn('PERSON', output.getvalue())
        self.assertNotIn('https://', output.getvalue())
        self.assertEqual([call.args[2] for call in state.call_args_list], ['running', 'error'])
        db_connect.assert_not_called()
        success.assert_not_called()
        failure.assert_called_once()


if __name__ == '__main__':
    unittest.main(verbosity=2)
