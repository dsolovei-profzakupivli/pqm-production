"""NAZK crash/lease tests using disposable SQLite and synthetic fetches only."""
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import reference_directories as refs
import scheduler_runtime
import operational_tasks


class NazkRecovery(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pqm-nazk-recovery-", dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "synthetic.sqlite3"
        refs.init_reference_tables(self.path)
        with closing(sqlite3.connect(self.path)) as con, con:
            scheduler_runtime.migrate(con)
            con.execute("INSERT INTO nazk_registry(source_id,full_name,raw_json) VALUES('old','OLD','{}')")
        self.key = str(self.path.resolve())
        self.addCleanup(self.clear_active)

    def clear_active(self):
        with refs.NAZK_ACTIVE_LOCK:
            refs.NAZK_ACTIVE.discard(self.key)

    def rows(self):
        with closing(sqlite3.connect(self.path)) as con:
            return con.execute("SELECT source_id,full_name FROM nazk_registry ORDER BY source_id").fetchall()

    def test_stale_running_get_is_read_only_and_retryable(self):
        refs._state(self.path, 'nazk', 'running', 'synthetic crash')
        with closing(sqlite3.connect(self.path)) as con:
            before = tuple(con.execute("SELECT status,message,updated_at FROM reference_sync_state WHERE source='nazk'").fetchone())
        status = refs.reference_status(self.path)['nazk']
        self.assertEqual(status['status'], 'error')
        self.assertTrue(status['interrupted'])
        self.assertEqual(status['interrupted_message'], 'synthetic crash')
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(tuple(con.execute("SELECT status,message,updated_at FROM reference_sync_state WHERE source='nazk'").fetchone()), before)
        owner = scheduler_runtime.claim(self.path, 'nazk_registry', trigger='retry')
        self.assertTrue(owner)
        with patch.object(refs.threading, 'Timer') as timer:
            timer.return_value.start.return_value = None
            self.assertTrue(refs.start_reference_refresh(self.path, 'nazk', lease_owner=owner))
            self.assertFalse(refs.start_reference_refresh(self.path, 'nazk', lease_owner=owner))
        timer.assert_called_once()
        self.assertTrue(scheduler_runtime.finish(self.path, 'nazk_registry', owner))

    def test_live_lease_from_another_process_remains_running(self):
        owner = scheduler_runtime.claim(self.path, 'nazk_registry', trigger='other-process')
        self.assertTrue(owner)
        refs._state(self.path, 'nazk', 'running', 'remote worker')
        self.assertEqual(refs.reference_status(self.path)['nazk']['status'], 'running')
        self.assertIsNone(scheduler_runtime.claim(self.path, 'nazk_registry', trigger='duplicate'))
        self.assertTrue(scheduler_runtime.finish(self.path, 'nazk_registry', owner))

    def test_expired_lease_projects_interruption_without_database_write(self):
        now = datetime.now(timezone.utc)
        owner = scheduler_runtime.claim(self.path, 'nazk_registry', trigger='crash', now=now-timedelta(minutes=5), lease_seconds=30)
        self.assertTrue(owner)
        refs._state(self.path, 'nazk', 'running', 'stale')
        refs._state(self.path, 'amcu', 'running', 'amcu stays historical')
        result = refs.reference_status(self.path)
        self.assertTrue(result['nazk']['interrupted'])
        self.assertTrue(result['amcu']['interrupted'])
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute("SELECT status FROM reference_sync_state WHERE source='nazk'").fetchone()[0], 'running')
            self.assertEqual(con.execute("SELECT status FROM reference_sync_state WHERE source='amcu'").fetchone()[0], 'running')

    def test_403_preserves_old_rows_and_retry_is_allowed(self):
        owner = scheduler_runtime.claim(self.path, 'nazk_registry', trigger='http-403')
        failed = Mock()
        with patch.dict('os.environ', {'PQM_SANDBOX': '0'}):
            with patch.object(refs, '_fetch', side_effect=RuntimeError('HTTP 403 synthetic')):
                refs.refresh_nazk(self.path, on_error=failed, lease_owner=owner)
        self.assertEqual(self.rows(), [('old', 'OLD')])
        failed.assert_called_once()
        self.assertTrue(scheduler_runtime.finish(self.path, 'nazk_registry', owner, status='error'))
        retry = scheduler_runtime.claim(self.path, 'nazk_registry', trigger='retry-403')
        self.assertTrue(retry)
        self.assertTrue(scheduler_runtime.finish(self.path, 'nazk_registry', retry))

    def test_owner_replacement_during_fetch_cannot_commit_or_finish_new_lease(self):
        old = scheduler_runtime.claim(self.path, 'nazk_registry', trigger='old', owner_id='old-owner')
        payload = json.dumps([{'id': 'new', 'indLastNameOnOffenseMoment': 'NEW'}]).encode()
        def replace(_url):
            with closing(sqlite3.connect(self.path)) as con, con:
                con.execute("UPDATE scheduler_job_leases SET lease_until=? WHERE job_key='nazk_registry'",
                            ((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),))
            self.assertEqual(scheduler_runtime.claim(self.path, 'nazk_registry', trigger='new', owner_id='new-owner'), 'new-owner')
            return payload
        failed = Mock()
        with patch.dict('os.environ', {'PQM_SANDBOX': '0'}):
            with patch.object(refs, '_fetch', side_effect=replace):
                refs.refresh_nazk(self.path, on_error=failed, lease_owner=old)
        self.assertEqual(self.rows(), [('old', 'OLD')])
        failed.assert_called_once()
        self.assertFalse(scheduler_runtime.finish(self.path, 'nazk_registry', old))
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute("SELECT owner_id FROM scheduler_job_leases WHERE job_key='nazk_registry'").fetchone()[0], 'new-owner')
        self.assertTrue(scheduler_runtime.finish(self.path, 'nazk_registry', 'new-owner'))

    def test_identical_successful_payload_replaces_without_duplicate_ids(self):
        payload = json.dumps([{'id': 'same', 'indLastNameOnOffenseMoment': 'SAME'}]).encode()
        with patch.dict('os.environ', {'PQM_SANDBOX': '0'}):
            with patch.object(refs, '_fetch', return_value=payload):
                refs.refresh_nazk(self.path)
                refs.refresh_nazk(self.path)
        self.assertEqual(self.rows(), [('same', 'SAME')])

    def test_expired_or_replaced_owner_is_rejected_in_write_transaction(self):
        old = scheduler_runtime.claim(self.path, 'nazk_registry', trigger='old', owner_id='old-owner')
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("UPDATE scheduler_job_leases SET lease_until=? WHERE job_key='nazk_registry'",
                        ((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),))
        new = scheduler_runtime.claim(self.path, 'nazk_registry', trigger='replacement', owner_id='new-owner')
        self.assertEqual((old, new), ('old-owner', 'new-owner'))
        with closing(sqlite3.connect(self.path)) as con:
            con.execute('BEGIN IMMEDIATE')
            with self.assertRaises(scheduler_runtime.LeaseLost):
                scheduler_runtime.require_current_lease(con, 'nazk_registry', old)
            con.rollback()
        self.assertTrue(scheduler_runtime.finish(self.path, 'nazk_registry', new))

    def test_expired_owner_cannot_renew_or_finish_even_before_replacement(self):
        now = datetime.now(timezone.utc)
        owner = scheduler_runtime.claim(self.path, 'nazk_registry', trigger='short-lease',
                                        now=now-timedelta(seconds=5), lease_seconds=1)
        self.assertTrue(owner)
        self.assertFalse(scheduler_runtime.renew(self.path, 'nazk_registry', owner, now=now,
                                                 require_current=True))
        self.assertFalse(scheduler_runtime.finish(self.path, 'nazk_registry', owner, now=now,
                                                  require_current=True))
        replacement = scheduler_runtime.claim(self.path, 'nazk_registry', trigger='takeover',
                                              owner_id='replacement', now=now)
        self.assertEqual(replacement, 'replacement')
        self.assertTrue(scheduler_runtime.finish(self.path, 'nazk_registry', replacement, now=now))

    def test_unrelated_scheduler_jobs_keep_legacy_lease_behavior(self):
        now = datetime.now(timezone.utc)
        for job in ('prozorro', 'violation_reports', 'nazk_registry'):
            with self.subTest(job=job):
                owner = scheduler_runtime.claim(self.path, job, trigger='legacy',
                                                now=now-timedelta(seconds=5), lease_seconds=1)
                self.assertTrue(owner)
                if job == 'nazk_registry':
                    self.assertFalse(scheduler_runtime.finish(self.path, job, owner, now=now,
                                                              require_current=True))
                self.assertTrue(scheduler_runtime.finish(self.path, job, owner, now=now))


class NazkQualificationAutoClose(unittest.TestCase):
    def connection(self):
        con = sqlite3.connect(':memory:')
        con.row_factory = sqlite3.Row
        con.executescript("""CREATE TABLE operational_tasks(
          id TEXT PRIMARY KEY,task_type TEXT,supplier_code TEXT,status TEXT,
          resolution_code TEXT DEFAULT '',resolution_text TEXT DEFAULT '',resolved_at TEXT,
          resolved_by TEXT,updated_at TEXT,version INTEGER DEFAULT 1);
          CREATE TABLE operational_task_events(id INTEGER PRIMARY KEY AUTOINCREMENT,task_id TEXT,
          event_type TEXT,created_at TEXT,actor TEXT,old_value TEXT,new_value TEXT,metadata TEXT);
          CREATE TABLE supplier_nazk_checks(id INTEGER PRIMARY KEY, supplier_code TEXT, result TEXT);
          CREATE TABLE supplier_nazk_check_matches(check_id INTEGER, source_id TEXT);
          INSERT INTO operational_tasks(id,task_type,supplier_code,status) VALUES
          ('ready','nazk_check','1111111111','ready_for_document'),
          ('working','nazk_check','1111111111','in_progress'),
          ('done','nazk_check','1111111111','completed'),
          ('active','nazk_check','22222222','in_progress');
          INSERT INTO supplier_nazk_checks VALUES(1,'1111111111','confirmed');
          INSERT INTO supplier_nazk_check_matches VALUES(1,'synthetic-source-id');""")
        return con

    def reconcile(self, con, result):
        with patch.object(operational_tasks, 'migrate', lambda _con: None), \
             patch.object(operational_tasks, '_active_application_map',
                          return_value={'22222222': [{'id': 'synthetic-active-qualification'}]}):
            return operational_tasks.reconcile_stale_nazk_tasks_after_prozorro_sync(
                con, result, 'synthetic sync')

    def test_complete_sync_cancels_ready_and_working_once_preserving_terminal(self):
        con = self.connection()
        result = {'frameworks': 4, 'completed': 4, 'errors': []}
        first = self.reconcile(con, result)
        second = self.reconcile(con, result)
        self.assertEqual(first['cancelled'], 2)
        self.assertEqual(second['cancelled'], 0)
        rows = {row['id']: (row['status'], row['resolution_code']) for row in
                con.execute('SELECT id,status,resolution_code FROM operational_tasks')}
        self.assertEqual(rows['ready'], ('cancelled', 'no_active_qualifications'))
        self.assertEqual(rows['working'], ('cancelled', 'no_active_qualifications'))
        self.assertEqual(rows['done'], ('completed', ''))
        self.assertEqual(rows['active'], ('in_progress', ''))
        self.assertEqual(con.execute('SELECT COUNT(*) FROM operational_task_events').fetchone()[0], 2)
        self.assertEqual(tuple(con.execute('SELECT supplier_code,result FROM supplier_nazk_checks').fetchone()),
                         ('1111111111', 'confirmed'))
        self.assertEqual(tuple(con.execute('SELECT check_id,source_id FROM supplier_nazk_check_matches').fetchone()),
                         (1, 'synthetic-source-id'))

    def test_partial_failed_and_incomplete_sync_never_cancel(self):
        cases = (
            {'frameworks': 4, 'completed': 3, 'errors': []},
            {'frameworks': 4, 'completed': 4, 'errors': ['synthetic failure']},
            {'frameworks': 4, 'completed': 4, 'errors': [], 'status': 'failed'},
            {'frameworks': 4, 'completed': 4, 'errors': [], 'officer_assignments_error': 'failed'},
        )
        for result in cases:
            with self.subTest(result=result):
                con = self.connection()
                outcome = self.reconcile(con, result)
                self.assertEqual(outcome['skipped'], 'sync_not_complete')
                self.assertEqual(con.execute('SELECT COUNT(*) FROM operational_task_events').fetchone()[0], 0)
                self.assertEqual(con.execute("SELECT status FROM operational_tasks WHERE id='ready'").fetchone()[0],
                                 'ready_for_document')
                con.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
