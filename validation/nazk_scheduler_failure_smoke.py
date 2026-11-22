"""NAZK fetch failure releases its job lease; synthetic/offline fixtures only."""
import json
import io
import inspect
import importlib
import os
import sqlite3
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
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
        finish_calls = []
        def finish(job_key, owner, status="ok", error="", *, require_current=False):
            finish_calls.append((job_key, owner, status, error, require_current))
            try:
                return real_finish(job_key, owner, status, error,
                                   require_current=require_current)
            finally:
                finished.set()
        with patch.object(refs, '_fetch', side_effect=RuntimeError('synthetic HTTP 403')), \
             patch.object(s, 'rebuild_nazk_tasks') as workflow, \
             patch.object(s, '_finish_scheduler_lease', side_effect=finish):
            self.assertTrue(s.start_nazk_registry_refresh(trigger='synthetic'))
            self.assertTrue(finished.wait(5))
            workflow.assert_not_called()
        self.assertEqual(len(finish_calls), 1)
        self.assertEqual(finish_calls[0][0], 'nazk_registry')
        self.assertTrue(finish_calls[0][1])
        self.assertEqual(finish_calls[0][2:], ('error', 'synthetic HTTP 403', True))
        with s.db() as con:
            self.assertEqual(0, con.execute('SELECT COUNT(*) FROM scheduler_job_leases').fetchone()[0])
            row = con.execute("SELECT last_status,last_error FROM scheduler_job_state WHERE job_key='nazk_registry'").fetchone()
            self.assertEqual(tuple(row), ('error', 'synthetic HTTP 403'))
            self.assertEqual(0, con.execute('SELECT COUNT(*) FROM supplier_nazk_checks').fetchone()[0])
        owner = s.scheduler_runtime.claim(s.DB_PATH, 'nazk_registry', trigger='synthetic_retry')
        self.assertTrue(owner)
        s.scheduler_runtime.release(s.DB_PATH, 'nazk_registry', owner)

    def test_status_write_failure_still_calls_failure_cleanup_only(self):
        finished = threading.Event()
        real_state = refs._state_with_lease
        real_finish = s._finish_scheduler_lease
        state_calls = []
        finish_calls = []
        def fail_worker_running(db_path, source, status, message, owner_id, *, count=None,
                                source_updated_at=None):
            state_calls.append((source, status, owner_id))
            if len(state_calls) == 2:
                raise sqlite3.OperationalError('synthetic locked')
            return real_state(db_path, source, status, message, owner_id,
                              count=count, source_updated_at=source_updated_at)
        def finish(job_key, owner, status="ok", error="", *, require_current=False):
            finish_calls.append((job_key, owner, status, error, require_current))
            try:
                return real_finish(job_key, owner, status, error,
                                   require_current=require_current)
            finally:
                finished.set()
        with s.db() as con:
            before = tuple(con.execute("SELECT * FROM nazk_registry ORDER BY source_id"))
        with patch.object(refs, '_state_with_lease', side_effect=fail_worker_running), \
             patch.object(refs, '_fetch') as fetch, \
             patch.object(s, 'rebuild_nazk_tasks') as workflow, \
             patch.object(s, '_finish_scheduler_lease', side_effect=finish):
            self.assertTrue(s.start_nazk_registry_refresh(trigger='status_write_failure'))
            self.assertTrue(finished.wait(5))
            fetch.assert_not_called()
            workflow.assert_not_called()
        self.assertEqual([call[:2] for call in state_calls],
                         [('nazk', 'running'), ('nazk', 'running'), ('nazk', 'error')])
        self.assertEqual(len(finish_calls), 1)
        self.assertEqual(finish_calls[0][0], 'nazk_registry')
        self.assertTrue(finish_calls[0][1])
        self.assertEqual(finish_calls[0][2:], ('error', 'synthetic locked', True))
        self.assertFalse(refs.LOCK.locked())
        with s.db() as con:
            after = tuple(con.execute("SELECT * FROM nazk_registry ORDER BY source_id"))
            leases = con.execute("SELECT COUNT(*) FROM scheduler_job_leases WHERE job_key='nazk_registry'").fetchone()[0]
            state = con.execute("SELECT last_status,last_error FROM scheduler_job_state WHERE job_key='nazk_registry'").fetchone()
        self.assertEqual(after, before)
        self.assertEqual(leases, 0)
        self.assertEqual(tuple(state), ('error', 'synthetic locked'))
        retry_owner = s.scheduler_runtime.claim(s.DB_PATH, 'nazk_registry', trigger='status_write_retry')
        self.assertTrue(retry_owner)
        s.scheduler_runtime.release(s.DB_PATH, 'nazk_registry', retry_owner)

    def test_other_scheduler_finish_keeps_legacy_default(self):
        with patch.object(s.scheduler_runtime, 'finish', return_value=True) as finish:
            s._finish_scheduler_lease('violation_reports', 'owner-token', 'ok', '')
        finish.assert_called_once_with(s.DB_PATH, 'violation_reports', 'owner-token',
                                       status='ok', error='', require_current=False)

    def test_nazk_finish_rejects_non_owner_token(self):
        owner = s.scheduler_runtime.claim(s.DB_PATH, 'nazk_registry', trigger='owner-token-test')
        self.assertTrue(owner)
        self.assertFalse(s.scheduler_runtime.finish(
            s.DB_PATH, 'nazk_registry', owner + '-wrong', status='error',
            error='stale worker', require_current=True))
        with s.db() as con:
            lease = con.execute("SELECT owner_id FROM scheduler_job_leases WHERE job_key='nazk_registry'").fetchone()
        self.assertEqual(lease[0], owner)
        self.assertTrue(s.scheduler_runtime.finish(
            s.DB_PATH, 'nazk_registry', owner, status='ok', require_current=True))

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


NAZK_GATE_MODULES = (
    "validation.local_release_20260911.test_production_nazk_recovery",
    "validation.local_release_20260911.test_production_nazk_sync_hook",
    "validation.local_release_20260911.test_operational_tasks",
    "validation.local_release_20260911.test_nazk_task_relevance",
    "validation.local_release_20260911.test_reference_directories",
    "test_production_ui_release_integrity",
    "test_production_dst_hotfix_integrity",
    "test_production_declension_preview_integrity",
    "test_production_scenario_projection_integrity",
    "test_production_nazk_recovery_integrity",
    "test_production_nazk_recovery_followup_integrity",
)


def gate_suite():
    """Run the failure smoke plus its Linux NAZK, scheduler, and integrity regressions."""
    modules = [sys.modules[__name__]]
    modules.extend(importlib.import_module(name) for name in NAZK_GATE_MODULES)
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite()
    for module in modules:
        suite.addTests(loader.loadTestsFromModule(module))
    return suite


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(gate_suite())
    raise SystemExit(0 if result.wasSuccessful() else 1)
