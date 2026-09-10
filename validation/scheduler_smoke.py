"""Scheduler/indicator checks; isolated database, clocks and external workers."""
import datetime
import http.client
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import web_smoke as web
s = web.server


class SchedulerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        web.fixture()

    def test_disabled_and_dead_scheduler_never_advertise_next_run(self):
        with patch.dict(s.SYNC_STATE, {'next_run_at': 'future'}), patch.object(s, 'ENABLE_SCHEDULER', False):
            self.assertFalse(s.sync_status_payload()['scheduler_enabled'])
            self.assertIsNone(s.sync_status_payload()['next_run_at'])
        with patch.object(s, 'ENABLE_SCHEDULER', True), patch.object(s, 'PROZORRO_SCHEDULER_THREAD', Mock(is_alive=lambda: False)):
            self.assertFalse(s.sync_status_payload()['scheduler_running'])
            self.assertIsNone(s.sync_status_payload()['next_run_at'])
        with patch.object(s, 'ENABLE_SCHEDULER', True), patch.object(s, 'PROZORRO_SCHEDULER_THREAD', Mock(is_alive=lambda: True)), patch.dict(s.SYNC_STATE, {'next_run_at': 'future'}):
            self.assertTrue(s.sync_status_payload()['scheduler_running'])
            self.assertEqual('future', s.sync_status_payload()['next_run_at'])

    def test_restore_data_timestamp_does_not_invent_completed_run(self):
        stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with s.db() as con:
            con.execute('UPDATE submissions SET synced_at=?', (stamp,))
        with patch.dict(s.SYNC_STATE, {'updated_at': None, 'last_completed_at': None}):
            s.restore_sync_data_timestamp()
            self.assertEqual(stamp, s.SYNC_STATE['last_data_sync_at'])
            self.assertIsNone(s.SYNC_STATE['updated_at'])
            self.assertIsNone(s.SYNC_STATE['last_completed_at'])

    def test_hour_boundary_including_year_rollover(self):
        for value, expected in [('2026-09-10T12:04:59+00:00', '2026-09-10T12:05:00+00:00'),
                                ('2026-09-10T12:05:00+00:00', '2026-09-10T13:05:00+00:00'),
                                ('2026-12-31T23:06:00+00:00', '2027-01-01T00:05:00+00:00')]:
            self.assertEqual(expected, s.next_hourly_run(datetime.datetime.fromisoformat(value)).isoformat())

    def test_failed_or_busy_prozorro_does_not_stop_appeals_or_next_trigger(self):
        with patch.object(s, 'start_prozorro_sync', side_effect=[RuntimeError('synthetic'), False, True]) as prozorro, patch.object(s, 'start_violation_reports_sync', return_value=True) as appeals:
            for _ in range(3):
                s.trigger_scheduled_syncs('fixture')
            self.assertEqual(3, prozorro.call_count)
            self.assertEqual(3, appeals.call_count)

    def test_busy_lock_does_not_start_duplicate_worker(self):
        with patch.dict(s.SYNC_STATE, {'running': True}), patch.object(s.threading, 'Thread') as thread:
            self.assertFalse(s.start_prozorro_sync(lambda: None, mode='incremental', message='fixture'))
            thread.assert_not_called()

    def test_clock_runs_hourly_and_only_catches_up_when_stale(self):
        class EndClock(Exception):
            pass
        class Clock(datetime.datetime):
            current = datetime.datetime(2026, 9, 10, 10, 4, 40, tzinfo=datetime.timezone.utc)
            @classmethod
            def now(cls, tz=None):
                return cls.current.astimezone(tz) if tz else cls.current
        for stale in (False, True):
            Clock.current = datetime.datetime(2026, 9, 10, 10, 4, 40, tzinfo=datetime.timezone.utc)
            last = Clock.current - datetime.timedelta(hours=2 if stale else 0)
            def sleep(seconds):
                Clock.current += datetime.timedelta(seconds=seconds)
                if Clock.current.minute > 5:
                    raise EndClock()
            with patch.object(s, 'datetime', Clock), patch.object(s.time, 'sleep', sleep), patch.object(s, 'trigger_scheduled_syncs') as trigger, patch.dict(s.SYNC_STATE, {'last_data_sync_at': last.isoformat()}):
                with self.assertRaises(EndClock):
                    s.hourly_sync_scheduler()
                self.assertEqual(['startup_catchup', 'hourly'] if stale else ['hourly'], [c.args[0] for c in trigger.call_args_list])

    def test_automatic_outcome_distinguishes_success_partial_failure(self):
        base = {'frameworks': 2, 'completed': 2, 'submissions': 3, 'qualifications': 3, 'contracts': 0, 'errors': []}
        for result, expected in [(base, 'ok'), (dict(base, completed=1, errors=[{'error': 'synthetic'}]), 'partial'), (RuntimeError('synthetic'), 'failed')]:
            options = {'side_effect': result} if isinstance(result, Exception) else {'return_value': result}
            with patch.dict(s.SYNC_STATE, {}), patch.object(s, 'sync_incremental_active_frameworks', **options), patch.object(s, 'rebuild_operational_tasks'):
                s.sync_incremental_worker()
                self.assertEqual(expected, s.SYNC_STATE['last_automatic_result']['status'])
                self.assertTrue(s.SYNC_STATE['last_automatic_completed_at'])
                self.assertFalse(s.SYNC_STATE['running'])

    def test_real_enabled_startup_exposes_live_thread_and_restored_timestamp(self):
        stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with s.db() as con:
            con.execute('UPDATE submissions SET synced_at=?', (stamp,))
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        environment = dict(os.environ, HOST='127.0.0.1', PORT=str(port), PQM_ENABLE_SCHEDULER='1', PYTHONUNBUFFERED='1')
        with (Path(web.TEMP.name)/'scheduler-startup.log').open('w') as log:
            process = subprocess.Popen([sys.executable, str(web.ROOT/'server.py')], cwd=web.ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic()+15
                while time.monotonic() < deadline:
                    self.assertIsNone(process.poll())
                    try:
                        client = http.client.HTTPConnection('127.0.0.1', port, timeout=1)
                        client.request('GET', '/api/health'); response = client.getresponse(); body = json.loads(response.read()); client.close()
                        if response.status == 200:
                            break
                    except OSError:
                        time.sleep(.1)
                else:
                    self.fail('Startup timeout')
                self.assertTrue(body['sync']['scheduler_enabled'])
                self.assertTrue(body['sync']['scheduler_running'])
                self.assertTrue(body['sync']['next_run_at'])
                self.assertEqual(stamp, body['sync']['last_data_sync_at'])
            finally:
                process.terminate(); process.wait(timeout=10)

    def test_frontend_indicator_states(self):
        source = (web.ROOT/'app.js').read_text()
        function = source.split('function syncStatusPresentation(state){', 1)[1].split('async function refreshSyncStatus()', 1)[0]
        script = 'const assert=require("node:assert/strict"); const displayDate=x=>x; function syncStatusPresentation(state){'+function+'''
const show=syncStatusPresentation;
assert.match(show({scheduler_enabled:false,next_run_at:'future'}).text,/Автооновлення вимкнено/);
assert.doesNotMatch(show({scheduler_enabled:false}).text,/:05|Наступне/);
assert.match(show({scheduler_enabled:true,scheduler_running:false}).text,/Планувальник не працює/);
assert.match(show({scheduler_enabled:true,scheduler_running:true,next_run_at:'future'}).text,/Наступне автооновлення: future/);
assert.match(show({last_data_sync_at:'persisted',scheduler_enabled:false}).text,/Дані синхронізовано: persisted/);
assert.match(show({updated_at:'attempt'}).text,/Остання спроба: attempt/);
assert.match(show({}).text,/Стан автооновлення невідомий/);
assert.match(show({running:true,message:'Ручне оновлення',scheduler_enabled:false}).text,/Ручне оновлення.*Автооновлення вимкнено/);
'''
        result = subprocess.run([os.environ.get('PQM_TEST_NODE') or shutil.which('node') or 'node', '-e', script], capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
