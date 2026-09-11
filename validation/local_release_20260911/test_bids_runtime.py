import json
import threading
import unittest
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
from unittest.mock import patch
import server


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
                       patch.object(server, 'BIDS_MODE', 'readonly'),
                       patch.object(server, 'BIDS_UPDATE_STATE', {'running':False})]
        for p in self.patches: p.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(self.patches)])

    def test_lightweight_check_never_launches_update(self):
        with patch.object(server, 'bids_runtime_check'), patch.object(server, 'bids_update_worker') as worker:
            status, result = self.post({'check_only':True})
            self.assertEqual(status, 200)
            self.assertFalse(result['started'])
            worker.assert_not_called()

    def test_start_failure_is_json_and_logged(self):
        with patch.object(server, 'bids_runtime_check', side_effect=OSError('test unavailable')), patch.object(server.SERVER_LOG, 'exception') as log:
            status, result = self.post({})
            self.assertEqual(status, 503)
            self.assertEqual(result['code'], 'bids_start_failed')
            self.assertFalse(server.BIDS_UPDATE_STATE['running'])
            log.assert_called_once()

    def test_already_running_and_web_disabled(self):
        server.BIDS_UPDATE_STATE['running'] = True
        self.assertEqual(self.post({})[0], 409)
        with patch.object(server, 'IS_WEB_ENV', True):
            # WEB must fail closed before RBAC when authentication is disabled.
            self.assertEqual(self.post({})[0], 503)

    def test_runtime_uses_configured_python(self):
        with patch.object(server.Path, 'is_file', return_value=True), patch.object(server.subprocess, 'run') as run:
            server.bids_runtime_check()
            self.assertEqual(run.call_args.args[0][0], str(server.BIDS_PYTHON))
            self.assertEqual(run.call_args.kwargs['cwd'], server.BIDS_SCRIPT.parent)

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
