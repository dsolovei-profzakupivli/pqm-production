"""Synthetic-only NAZK failure/recovery and registry preservation tests."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import reference_directories as refs
import sandbox_nazk as transport


class Guard(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / 'fixture.sqlite3'
        refs.init_reference_tables(self.db)
        with sqlite3.connect(self.db) as con:
            con.execute("INSERT INTO nazk_registry(source_id,full_name,raw_json) VALUES('old','SYNTHETIC','{}')")
        self.env = patch.dict(os.environ, PQM_SANDBOX='1', PQM_SANDBOX_NAZK_READ='0')
        self.env.start()
    def tearDown(self):
        refs.SANDBOX_NAZK_ACTIVE.discard(str(self.db.resolve()))
        refs.SANDBOX_NAZK_ERRORS.pop(str(self.db.resolve()), None)
        self.env.stop()
        self.temp.cleanup()
    def rows(self):
        with sqlite3.connect(self.db) as con:
            return con.execute('SELECT * FROM nazk_registry').fetchall()
    def test_disabled_preserves_registry(self):
        before = self.rows()
        callback = Mock()
        refs.refresh_nazk(self.db, callback)
        self.assertEqual(self.rows(), before)
        self.assertEqual(refs.reference_status(self.db)['nazk']['status'], 'error')
        callback.assert_not_called()
        self.assertFalse(refs.LOCK.locked())
    def test_failure_payloads_preserve_registry_and_release_lock(self):
        before = self.rows()
        for payload in (b'broken', b'[]', b'[{}]', b'[{"id":1},{"id":1}]'):
            with self.subTest(payload=payload), patch.object(transport, 'download', return_value=payload):
                refs.refresh_nazk(self.db)
                self.assertEqual(self.rows(), before)
                self.assertEqual(refs.reference_status(self.db)['nazk']['status'], 'error')
                self.assertFalse(refs.LOCK.locked())
    def test_timeout_preserves_registry(self):
        before = self.rows()
        with patch.object(transport, 'download', side_effect=TimeoutError('deadline')):
            refs.refresh_nazk(self.db)
        self.assertEqual(self.rows(), before)
        self.assertEqual(refs.reference_status(self.db)['nazk']['status'], 'error')
    def test_stale_running_is_readonly_projection(self):
        refs._state(self.db, 'nazk', 'running')
        self.assertTrue(refs.reference_status(self.db)['nazk']['interrupted'])
        with sqlite3.connect(self.db) as con:
            self.assertEqual(con.execute("SELECT status FROM reference_sync_state WHERE source='nazk'").fetchone()[0], 'running')
    def test_start_failure_releases_reservation(self):
        with patch.object(refs.threading, 'Timer') as timer:
            timer.return_value.start.side_effect = RuntimeError('cannot start')
            with self.assertRaises(RuntimeError):
                refs.start_reference_refresh(self.db, 'nazk')
        self.assertNotIn(str(self.db.resolve()), refs.SANDBOX_NAZK_ACTIVE)
        self.assertEqual(refs.reference_status(self.db)['nazk']['status'], 'error')
    def test_duplicate_start_and_direct_call_do_not_clear_active_claim(self):
        with patch.object(refs.threading, 'Timer'), patch.object(transport, 'download') as download:
            self.assertTrue(refs.start_reference_refresh(self.db, 'nazk'))
            self.assertFalse(refs.start_reference_refresh(self.db, 'nazk'))
            refs.refresh_nazk(self.db)
            download.assert_not_called()
            self.assertIn(str(self.db.resolve()), refs.SANDBOX_NAZK_ACTIVE)
    def test_success_never_invokes_business_callback(self):
        callback = Mock()
        with patch.object(transport, 'download', return_value=b'[{"id":"new"}]'):
            refs.refresh_nazk(self.db, callback)
        self.assertEqual(refs.reference_status(self.db)['nazk']['status'], 'ok')
        self.assertEqual(self.rows()[0][0], 'new')
        callback.assert_not_called()
    def test_status_write_failure_still_exposes_terminal_error(self):
        original = refs._state
        def state(db, source, status, *args, **kwargs):
            if status == 'error':
                raise sqlite3.OperationalError('locked')
            return original(db, source, status, *args, **kwargs)
        with patch.object(refs, '_state', side_effect=state):
            with self.assertRaises(sqlite3.OperationalError):
                refs.refresh_nazk(self.db)
        self.assertEqual(refs.reference_status(self.db)['nazk']['status'], 'error')
        self.assertFalse(refs.LOCK.locked())
    def test_total_deadline_kills_worker_and_clears_permission(self):
        process = Mock(pid=12345)
        process.wait.side_effect = [subprocess.TimeoutExpired('worker', 60), 0]
        with patch.dict(os.environ, PQM_SANDBOX_NAZK_READ='1'), \
             patch('sandbox_runtime.validate_environment'), \
             patch.object(transport.subprocess, 'Popen', return_value=process), \
             patch.object(transport.os, 'killpg') as kill:
            with self.assertRaises(TimeoutError):
                transport.download()
        kill.assert_called_once_with(12345, transport.signal.SIGKILL)
        self.assertIsNone(transport._launch.expected)
        self.assertEqual(process.wait.call_args_list[0].kwargs, {'timeout': 60})


if __name__ == '__main__':
    unittest.main()
