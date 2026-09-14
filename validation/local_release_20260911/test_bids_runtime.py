import json
import threading
import sqlite3
import tempfile
import unittest
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
import server
import auth_access


class BidsRuntimeTests(unittest.TestCase):
    def post(self, payload):
        http = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        try:
            req = urllib.request.Request(f'http://127.0.0.1:{http.server_port}/api/bids-sync',
                data=json.dumps(payload).encode(), headers={'Content-Type':'application/json', 'X-PQM-Local-Role':'admin'})
            try:
                response = urllib.request.urlopen(req, timeout=5)
            except urllib.error.HTTPError as exc:
                response = exc
            with response:
                return response.status, json.load(response)
        finally:
            http.shutdown(); http.server_close(); thread.join()

    def setUp(self):
        self.patches = [patch.object(server, 'AUTH_ENABLED', False),
                       patch.object(server, 'LOCAL_ROLE_IMPERSONATION', True),
                       patch.object(server, 'IS_WEB_ENV', False),
                       patch.object(server, 'ENABLE_BIDS_UPDATE', True),
                       patch.object(server, 'manual_bids_update_state', return_value={'enabled':True}),
                       patch.object(server, 'BIDS_MODE', 'readonly'),
                       patch.object(server, 'BIDS_UPDATE_STATE', {'running':False})]
        for p in self.patches: p.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(self.patches)])

    def test_lightweight_check_never_launches_update(self):
        diagnostics = {'preflight_pid': 123}
        with patch.object(server, 'bids_runtime_check', return_value=diagnostics), patch.object(server, 'bids_update_worker') as worker:
            status, result = self.post({'check_only':True})
            self.assertEqual(status, 200)
            self.assertFalse(result['started'])
            self.assertEqual(result['preflight'], diagnostics)
            worker.assert_not_called()

    def test_start_failure_is_json_and_logged(self):
        with patch.object(server, 'bids_runtime_check', side_effect=OSError('test unavailable')), patch.object(server.SERVER_LOG, 'exception') as log:
            status, result = self.post({})
            self.assertEqual(status, 503)
            self.assertEqual(result['code'], 'bids_start_failed')
            self.assertIn('test unavailable', result['error'])
            self.assertFalse(server.BIDS_UPDATE_STATE['running'])
            log.assert_called_once()

    def test_already_running_and_runtime_disabled(self):
        server.BIDS_UPDATE_STATE['running'] = True
        self.assertEqual(self.post({})[0], 409)
        with patch.object(server, 'IS_WEB_ENV', True):
            # WEB must fail closed before RBAC when authentication is disabled.
            self.assertEqual(self.post({})[0], 503)
        with patch.object(server, 'manual_bids_update_state', return_value={'enabled':False}):
            self.assertEqual(self.post({})[0], 403)

    def test_runtime_uses_configured_python(self):
        with patch.object(server.Path, 'is_file', return_value=True), patch.object(server.subprocess, 'Popen') as popen:
            process = popen.return_value.__enter__.return_value
            process.pid = 321
            process.communicate.return_value = ('', '')
            process.returncode = 0
            result = server.bids_runtime_check()
            self.assertEqual(popen.call_args.args[0][0], str(server.BIDS_PYTHON))
            self.assertEqual(popen.call_args.kwargs['cwd'], server.BIDS_SCRIPT.parent)
            self.assertEqual(result['preflight_pid'], 321)

    def test_runtime_permission_error_is_actionable(self):
        with patch.object(server.Path, 'is_file', return_value=True), \
             patch.object(server.subprocess, 'Popen', side_effect=PermissionError(5, 'Access is denied')):
            with self.assertRaisesRegex(RuntimeError, 'PQM_BIDS_PYTHON'):
                server.bids_runtime_check()

    def test_worker_streams_output_and_failure(self):
        with patch.object(server.subprocess, 'Popen') as popen, patch.object(server.SERVER_LOG, 'info') as log:
            process = popen.return_value.__enter__.return_value
            process.stdout = ['test stdout\n', 'Traceback test\n']
            process.wait.return_value = 1
            with self.assertRaises(RuntimeError): server.run_bids_command(['--help'])
            self.assertEqual(popen.call_args.args[0][:2], [str(server.BIDS_PYTHON),str(server.BIDS_SCRIPT)])
            self.assertGreaterEqual(log.call_count,3)

    def test_progress_is_current_run_and_pause_is_not_error(self):
        server.BIDS_UPDATE_STATE.update(current_run_errors=0)
        server.bids_progress_line('[810/6141] UA-test')
        self.assertEqual(server.BIDS_UPDATE_STATE['processed'],809)
        self.assertEqual(server.BIDS_UPDATE_STATE['total'],6141)
        server.bids_progress_line('  Ліміт запитів. Пауза 37 с.')
        self.assertEqual(server.BIDS_UPDATE_STATE['current_run_errors'],0)
        server.bids_progress_line('  bids: 5; awards: 1')
        self.assertEqual(server.BIDS_UPDATE_STATE['processed'],810)
        server.bids_progress_line('  ПОМИЛКА: test fault')
        self.assertEqual(server.BIDS_UPDATE_STATE['current_run_errors'],1)
        self.assertTrue(server.BIDS_UPDATE_STATE['last_activity_at'])

    def test_duplicate_launch_has_run_id_and_no_worker(self):
        server.BIDS_UPDATE_STATE.update(running=True,run_id='existing',status='running')
        with patch.object(server,'bids_update_worker') as worker:
            status,result=self.post({})
            self.assertEqual(status,409)
            self.assertEqual(result['code'],'already_running')
            self.assertEqual(result['run_id'],'existing')
            worker.assert_not_called()

    def test_completed_and_failed_terminal_state(self):
        for failure in (None,RuntimeError('isolated fault')):
            server.BIDS_UPDATE_STATE.update(running=True,status='running',started_at=server.now_iso(),current_run_errors=0)
            with patch.object(server,'bids_db') as db, patch.object(server,'bids_runtime_check'), patch.object(server,'run_bids_command',side_effect=failure):
                db.return_value.__enter__.return_value.execute.return_value.fetchone.return_value=['2026-09-04']
                server.bids_update_worker()
            self.assertFalse(server.BIDS_UPDATE_STATE['running'])
            self.assertEqual(server.BIDS_UPDATE_STATE['status'],'failed' if failure else 'completed')
            self.assertTrue(server.BIDS_UPDATE_STATE['finished_at'])
            self.assertIsNotNone(server.bids_run_snapshot()['duration_seconds'])


class ManualBidsRuntimeSettingTests(unittest.TestCase):
    def setUp(self):
        # HTTP handler threads can keep a short-lived SQLite handle during
        # Windows teardown even after the response is fully consumed.
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temp.cleanup)
        self.db_path = Path(self.temp.name) / 'runtime.sqlite3'
        with sqlite3.connect(self.db_path) as con:
            con.execute('''CREATE TABLE audit_log(id INTEGER PRIMARY KEY AUTOINCREMENT,submission_id TEXT,
              changed_at TEXT NOT NULL,changed_by TEXT NOT NULL,field_name TEXT NOT NULL,old_value TEXT,new_value TEXT)''')
            auth_access.migrate(con)

    def request(self, role, enabled):
        http = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        thread = threading.Thread(target=http.serve_forever, daemon=True); thread.start()
        try:
            req = urllib.request.Request(
                f'http://127.0.0.1:{http.server_port}/api/admin/runtime-features/manual-bids-update',
                data=json.dumps({'enabled':enabled}).encode(),
                headers={'Content-Type':'application/json','X-PQM-Local-Role':role}, method='POST')
            try: response = urllib.request.urlopen(req, timeout=5)
            except urllib.error.HTTPError as exc: response = exc
            with response: return response.status, json.load(response)
        finally:
            http.shutdown(); http.server_close(); thread.join()

    def test_persistent_admin_toggle_is_audited_and_never_starts_update(self):
        scheduler_before = set(server.REGISTERED_SCHEDULER_JOBS)
        with patch.object(server,'DB_PATH',self.db_path), patch.object(server,'BIDS_MODE','readonly'), \
             patch.object(server,'ENABLE_BIDS_UPDATE',False), patch.object(server,'AUTH_ENABLED',False), \
             patch.object(server,'LOCAL_ROLE_IMPERSONATION',True), \
             patch.object(server,'bids_update_worker') as worker:
            initial = server.manual_bids_update_state(); self.assertFalse(initial['enabled']); self.assertEqual(initial['configuration_source'],'environment')
            status, enabled = self.request('admin', True)
            self.assertEqual(status,200); self.assertTrue(enabled['feature']['enabled']); worker.assert_not_called()
            self.assertTrue(server.manual_bids_update_state()['enabled'])
            server.set_manual_bids_update_enabled(True,'admin')
            self.assertEqual(self.request('viewer',False)[0],403)
            status, disabled = self.request('admin', False)
            self.assertEqual(status,200); self.assertFalse(disabled['feature']['enabled']); worker.assert_not_called()
            self.assertFalse(server.manual_bids_update_state()['enabled'])
        with sqlite3.connect(self.db_path) as con:
            row=con.execute("SELECT enabled,updated_by FROM runtime_feature_settings WHERE feature_key='manual_bids_update'").fetchone()
            events=con.execute("SELECT old_value,new_value FROM audit_log WHERE submission_id='runtime_feature:manual_bids_update' ORDER BY id").fetchall()
        self.assertEqual(row[0],0)
        self.assertTrue(row[1])
        self.assertEqual(events,[('disabled','enabled'),('enabled','disabled')])
        self.assertEqual(set(server.REGISTERED_SCHEDULER_JOBS),scheduler_before)
