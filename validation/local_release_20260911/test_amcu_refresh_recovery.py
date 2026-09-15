import io
import json
import sqlite3
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import reference_directories as ref


class AmcuRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'test.sqlite3'
        ref.init_reference_tables(self.path)
        self.old = ('old', '1', '', '', '1', '2026-09-10', 'AMCU', 'OLD', '12345678', '', '{}')
        self.new = ('new', '1', '', '', '2', '2026-09-14', 'AMCU', 'NEW', '12345678', '', '{}')
        with sqlite3.connect(self.path) as con:
            con.execute('INSERT INTO amcu_registry VALUES (?,?,?,?,?,?,?,?,?,?,?)', self.old)
            con.execute("UPDATE reference_sync_state SET row_count=1,source_updated_at='2026-09-10' WHERE source='amcu'")

    def tearDown(self):
        self.assertFalse(ref.LOCK.locked())
        self.assertFalse(ref.AMCU_LOCK.locked())
        ref.AMCU_ERRORS.pop(str(self.path.resolve()), None)
        self.tmp.cleanup()

    def rows(self):
        with sqlite3.connect(self.path) as con:
            return con.execute('SELECT * FROM amcu_registry').fetchall()

    def persisted(self):
        with sqlite3.connect(self.path) as con:
            return con.execute("SELECT status FROM reference_sync_state WHERE source='amcu'").fetchone()[0]

    def test_restart_running_is_read_only_interrupted_projection(self):
        ref._state(self.path, 'amcu', 'running')
        state = ref.reference_status(self.path)['amcu']
        self.assertEqual(state['status'], 'error')
        self.assertTrue(state['interrupted'])
        self.assertEqual(self.persisted(), 'running')
        self.assertEqual(self.rows(), [self.old])

    def test_stale_state_can_restart_and_duplicate_requests_cannot(self):
        ref._state(self.path, 'amcu', 'running')
        with patch.object(ref.threading, 'Timer') as timer:
            self.assertTrue(ref.start_reference_refresh(self.path, 'amcu'))
            self.assertFalse(ref.start_reference_refresh(self.path, 'amcu'))
            self.assertEqual(ref.reference_status(self.path)['amcu']['status'], 'running')
            self.assertEqual(timer.call_count, 1)
        with patch.object(ref, '_amcu_rows_bounded', return_value=('fixture', [self.new])):
            ref.refresh_amcu(self.path, _claimed=True)
        self.assertEqual(self.persisted(), 'ok')
        self.assertEqual(self.rows(), [self.new])

    def test_timer_start_failure_releases_reservation(self):
        with patch.object(ref.threading, 'Timer') as timer:
            timer.return_value.start.side_effect = RuntimeError('cannot start thread')
            with self.assertRaises(RuntimeError):
                ref.start_reference_refresh(self.path, 'amcu')
        self.assertEqual(self.persisted(), 'error')
        self.assertEqual(self.rows(), [self.old])

    def test_timeout_kills_worker_and_preserves_registry(self):
        with patch.object(ref.subprocess, 'run', side_effect=subprocess.TimeoutExpired('test', 300)) as run:
            ref.refresh_amcu(self.path)
        self.assertEqual(run.call_args.kwargs['timeout'], 300)
        self.assertEqual(self.persisted(), 'error')
        self.assertIn('5 хвилин', ref.reference_status(self.path)['amcu']['message'])
        self.assertEqual(self.rows(), [self.old])

    def test_fetch_failure_is_terminal_and_retry_succeeds(self):
        with patch.object(ref, '_amcu_rows_bounded', side_effect=RuntimeError('HTTP Error 403: Forbidden')):
            ref.refresh_amcu(self.path)
        self.assertEqual(self.persisted(), 'error')
        self.assertEqual(self.rows(), [self.old])
        with patch.object(ref, '_amcu_rows_bounded', return_value=('fixture', [self.new])):
            ref.refresh_amcu(self.path)
        self.assertEqual(self.persisted(), 'ok')

    def test_empty_result_never_deletes_existing_rows(self):
        result = subprocess.CompletedProcess([], 0, json.dumps({'source': 'fixture', 'rows': []}).encode(), b'')
        with patch.object(ref.subprocess, 'run', return_value=result):
            ref.refresh_amcu(self.path)
        self.assertEqual(self.persisted(), 'error')
        self.assertEqual(self.rows(), [self.old])

    def test_database_failure_rolls_back_and_releases_lock(self):
        with sqlite3.connect(self.path) as con:
            con.execute("CREATE TRIGGER fail_amcu BEFORE INSERT ON amcu_registry BEGIN SELECT RAISE(ABORT, 'test write failure'); END")
        with patch.object(ref, '_amcu_rows_bounded', return_value=('fixture', [self.new])):
            ref.refresh_amcu(self.path)
        self.assertEqual(self.persisted(), 'error')
        self.assertEqual(self.rows(), [self.old])

    def test_failed_terminal_write_still_projects_error(self):
        original = ref._state
        def state(*args, **kwargs):
            if args[2] == 'error':
                raise sqlite3.OperationalError('database is locked')
            return original(*args, **kwargs)
        with patch.object(ref, '_state', side_effect=state), patch.object(ref, '_amcu_rows_bounded', side_effect=RuntimeError('fetch failed')):
            ref.refresh_amcu(self.path)
        self.assertEqual(self.persisted(), 'running')
        self.assertEqual(ref.reference_status(self.path)['amcu']['status'], 'error')
        self.assertEqual(self.rows(), [self.old])

    def test_amcu_has_no_nazk_callback_or_state_mutation(self):
        with sqlite3.connect(self.path) as con:
            before = con.execute("SELECT * FROM reference_sync_state WHERE source='nazk'").fetchone()
        with patch.object(ref, 'refresh_nazk') as nazk, patch.object(ref, '_amcu_rows_bounded', return_value=('fixture', [self.new])):
            ref.refresh_amcu(self.path)
        nazk.assert_not_called()
        with sqlite3.connect(self.path) as con:
            self.assertEqual(before, con.execute("SELECT * FROM reference_sync_state WHERE source='nazk'").fetchone())

    def test_amcu_does_not_take_or_release_nazk_lock(self):
        ref.LOCK.acquire()
        try:
            with patch.object(ref, '_amcu_rows_bounded', return_value=('fixture', [self.new])):
                ref.refresh_amcu(self.path)
            self.assertTrue(ref.LOCK.locked())
            self.assertEqual(self.persisted(), 'ok')
        finally:
            ref.LOCK.release()

    def test_real_child_parses_upload_without_network_or_database(self):
        from openpyxl import Workbook
        wb = Workbook(); ws = wb.active
        ws.append(['Ідентифікаційний код', "Суб'єкт порушення", 'Дата рішення', '№ рішення'])
        ws.append(['12345678', 'SYNTHETIC', '14.09.2026', '1'])
        raw = io.BytesIO(); wb.save(raw); wb.close()
        source, rows = ref._amcu_rows_bounded(raw.getvalue(), 'synthetic.xlsx')
        self.assertEqual(source, 'synthetic.xlsx')
        self.assertEqual(rows[0][5], '2026-09-14')
        self.assertEqual(self.rows(), [self.old])


if __name__ == '__main__':
    unittest.main()
