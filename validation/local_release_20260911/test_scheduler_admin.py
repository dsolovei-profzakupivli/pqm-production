import json
import sqlite3
import tempfile
import threading
import subprocess
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import scheduler_runtime as runtime
import server


class SchedulerAdminTests(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(':memory:')
        runtime.migrate(self.con)
        self.con.commit()
        revisions = patch.dict(server.SCHEDULE_EXPECTED_REVISIONS, {}, clear=True)
        revisions.start()
        self.addCleanup(revisions.stop)
        wakeups = patch.dict(server.SCHEDULE_WAKEUPS, {}, clear=True)
        wakeups.start()
        self.addCleanup(wakeups.stop)

    def tearDown(self):
        self.con.close()

    def settings(self, minute=17, enabled=True):
        return {'enabled': enabled, 'timezone': 'Europe/Kyiv', 'spec': {'kind': 'hourly', 'minute': minute}}

    def apply(self, minute=17, revision=0):
        self.con.execute('BEGIN IMMEDIATE')
        result = runtime.apply_schedule(self.con, 'prozorro', self.settings(minute), revision, 'test.admin')
        self.con.commit()
        return result

    def test_additive_migration_preserves_legacy_overrides(self):
        con = sqlite3.connect(':memory:')
        self.addCleanup(con.close)
        con.execute('CREATE TABLE scheduler_job_settings(job_key TEXT PRIMARY KEY,enabled INTEGER,updated_at TEXT,updated_by TEXT)')
        con.execute("INSERT INTO scheduler_job_settings VALUES ('prozorro',1,'old','admin')")
        runtime.migrate(con)
        runtime.migrate(con)
        model = runtime.schedule_model(con, 'prozorro')
        self.assertTrue(model['enabled'])
        self.assertEqual(model['revision'], 0)
        self.assertEqual(model['spec'], runtime.default_spec('prozorro'))

    def test_preview_query_only_no_writes(self):
        self.con.execute('PRAGMA query_only=ON')
        before = self.con.total_changes
        result = runtime.preview_schedule(self.con, 'prozorro', self.settings())
        self.assertEqual(self.con.total_changes, before)
        self.assertFalse(result['immediate_run'])
        self.assertEqual(result['after']['spec']['minute'], 17)

    def test_preview_legacy_schema_without_migration(self):
        con = sqlite3.connect(':memory:')
        self.addCleanup(con.close)
        con.execute('PRAGMA query_only=ON')
        runtime.preview_schedule(con, 'prozorro', self.settings())
        self.assertEqual(con.execute('SELECT COUNT(*) FROM sqlite_master').fetchone()[0], 0)

    def test_apply_revision_audit_and_rollback(self):
        self.apply()
        previous = runtime.rollback_payload(self.con, 'prozorro', 1)
        self.assertEqual(previous['spec']['minute'], 5)
        self.con.execute('BEGIN IMMEDIATE')
        result = runtime.apply_schedule(self.con, 'prozorro', previous, 1, 'rollback.admin')
        self.con.commit()
        self.assertEqual(result['revision'], 2)
        self.assertEqual(result['spec']['minute'], 5)
        self.assertEqual(self.con.execute('SELECT actor FROM scheduler_schedule_audit ORDER BY revision').fetchall(), [('test.admin',), ('rollback.admin',)])

    def test_revision_conflict(self):
        self.apply()
        with self.assertRaises(runtime.RevisionConflict):
            runtime.apply_schedule(self.con, 'prozorro', self.settings(23), 0, 'other.admin')
        self.assertEqual(runtime.schedule_model(self.con, 'prozorro')['revision'], 1)

    def test_validation(self):
        for minute in (-1, 60, True, '5', 2.5):
            with self.subTest(minute=minute), self.assertRaises(ValueError):
                runtime.validate_spec('prozorro', {'kind': 'hourly', 'minute': minute})
        for days in ([], [7], [True], [1, 1]):
            with self.subTest(days=days), self.assertRaises(ValueError):
                runtime.validate_spec('nazk_registry', {'kind': 'weekly', 'hour': 9, 'minute': 20, 'weekdays': days})
        with self.assertRaises(ValueError):
            runtime.preview_schedule(self.con, 'prozorro', {**self.settings(), 'timezone': 'UTC'})

    def test_hourly_weekdays_and_catchup(self):
        kyiv = ZoneInfo('Europe/Kyiv')
        now = datetime(2026, 10, 12, 9, 16, tzinfo=kyiv)
        self.assertEqual(runtime.next_run(self.settings()['spec'], now).minute, 17)
        weekly = {'kind': 'weekly', 'hour': 10, 'minute': 0, 'weekdays': [2]}
        self.assertEqual(runtime.next_run(weekly, now).weekday(), 2)
        self.assertFalse(runtime.catchup_due(weekly, now, None))
        self.assertTrue(runtime.catchup_due(weekly, datetime(2026, 10, 14, 11, tzinfo=kyiv), None))

    def test_dst_gap_skipped_fold_first_only(self):
        kyiv = ZoneInfo('Europe/Kyiv')
        spec = {'kind': 'weekly', 'hour': 3, 'minute': 30, 'weekdays': [6]}
        gap = runtime.next_run(spec, datetime(2026, 3, 29, 0, tzinfo=kyiv))
        self.assertEqual(gap.day, 5)
        first = runtime.next_run(spec, datetime(2026, 10, 25, 0, tzinfo=kyiv))
        self.assertEqual(first.fold, 0)
        following = runtime.next_run(spec, first)
        self.assertEqual(following.day, 1)

    def test_overlap_warning(self):
        runtime.save_enabled(self.con, 'violation_reports', True, 'admin')
        self.con.commit()
        result = runtime.preview_schedule(self.con, 'prozorro', self.settings(5))
        self.assertTrue(any('violation_reports' in item for item in result['warnings']))

    def test_persistence_and_lease_untouched(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
            path = Path(temp) / 'fixture.sqlite3'
            with sqlite3.connect(path) as con:
                runtime.migrate(con)
            owner = runtime.claim(path, 'prozorro', trigger='fixture', owner_id='test-owner')
            with sqlite3.connect(path) as con:
                before = con.execute('SELECT * FROM scheduler_job_leases').fetchall()
                con.execute('BEGIN IMMEDIATE')
                runtime.apply_schedule(con, 'prozorro', self.settings(), 0, 'admin')
                self.assertEqual(con.execute('SELECT * FROM scheduler_job_leases').fetchall(), before)
            with sqlite3.connect(path) as con:
                self.assertEqual(runtime.schedule_model(con, 'prozorro')['spec']['minute'], 17)
            self.assertEqual(owner, 'test-owner')
            self.assertIsNone(runtime.claim(path, 'prozorro', trigger='scheduled', expected_revision=0))

    def test_server_preview_apply_guards_and_no_immediate_job(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
            path = Path(temp) / 'fixture.sqlite3'
            with sqlite3.connect(path) as con:
                runtime.migrate(con)
            with patch.object(server, 'DB_PATH', path), patch.object(server, 'SAFE_MODE', False), patch.object(server, 'SANDBOX_MODE', False), patch.object(server, 'apply_scheduler_settings') as register, patch.object(server, 'start_prozorro_sync') as launch:
                payload = {'settings': self.settings(), 'expected_revision': 0}
                server.scheduler_admin_change('prozorro', payload)
                register.assert_not_called()
                server.scheduler_admin_change('prozorro', payload, apply=True, actor='admin')
                register.assert_called_once_with(catch_up=False)
                launch.assert_not_called()
                with self.assertRaises(runtime.RevisionConflict):
                    server.scheduler_admin_change('prozorro', payload, apply=True, actor='admin')
            with patch.object(server, 'SAFE_MODE', True), patch.object(server, 'SANDBOX_MODE', False):
                with self.assertRaises(ValueError):
                    server.scheduler_admin_change('prozorro', payload)

    def test_admin_permissions(self):
        path = '/api/admin/scheduler-schedules/prozorro/apply'
        self.assertTrue(server.mutation_allowed('admin', 'POST', path))
        for role in ('viewer', 'officer'):
            self.assertFalse(server.mutation_allowed(role, 'POST', path))
            self.assertFalse(server.admin_read_allowed(role, '/api/admin/scheduler-schedules'))

    def test_wakeup_recalculates_deadline_and_revision_without_launch(self):
        class Clock:
            @classmethod
            def now(cls, tz):
                return datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        initial = {'revision': 0, 'spec': runtime.default_spec('prozorro')}
        changed = {'revision': 1, 'spec': self.settings(17)['spec']}
        future = datetime(2026, 1, 1, 12, 5, tzinfo=timezone.utc)
        past = datetime(2026, 1, 1, 11, 59, tzinfo=timezone.utc)
        with patch.object(server, 'datetime', Clock), patch.object(server, 'scheduler_schedule_model', side_effect=[initial, changed]), patch.object(server, '_scheduler_is_configured', return_value=True), patch.object(runtime, 'next_run', side_effect=[future, past]) as resolver, patch.object(server, '_trigger_scheduler_job') as launch:
            self.assertFalse(server.wait_schedule(future, threading.Event(), 'prozorro'))
            self.assertEqual(resolver.call_count, 2)
            self.assertEqual(server.SCHEDULE_EXPECTED_REVISIONS['prozorro'], 1)
            launch.assert_not_called()

    def test_stale_revision_cannot_claim_even_without_active_lease(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
            path = Path(temp) / 'fixture.sqlite3'
            with sqlite3.connect(path) as con:
                runtime.migrate(con)
                con.commit()
                con.execute('BEGIN IMMEDIATE')
                runtime.apply_schedule(con, 'prozorro', self.settings(), 0, 'admin')
            self.assertIsNone(runtime.claim(path, 'prozorro', trigger='scheduled', expected_revision=0))
            with sqlite3.connect(path) as con:
                self.assertEqual(con.execute('SELECT COUNT(*) FROM scheduler_job_leases').fetchone()[0], 0)

    def test_last_run_duration_does_not_pair_running_with_old_finish(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
            path = Path(temp) / 'fixture.sqlite3'
            with sqlite3.connect(path) as con:
                runtime.migrate(con)
                con.execute("UPDATE scheduler_job_state SET last_status='running',last_started_at='2026-01-01T12:00:00+00:00',last_finished_at='2026-01-01T11:00:00+00:00' WHERE job_key='prozorro'")
            row = next(r for r in runtime.state(path, {'prozorro': True}) if r['job'] == 'prozorro')
            self.assertIsNone(row['duration_seconds'])

    def test_read_model_is_query_only_and_registration_free(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
            path = Path(temp) / 'fixture.sqlite3'
            with sqlite3.connect(path) as con:
                runtime.migrate(con)
            with patch.object(server, 'DB_PATH', path), patch.object(server, 'SAFE_MODE', True), patch.object(server, 'SANDBOX_MODE', False), patch.object(server, 'register_scheduler_job') as register:
                model = server.scheduler_admin_model('prozorro')
                self.assertFalse(model['effective_enabled'])
                self.assertEqual(model['safety_block_reason'], 'Environment safety guard')
                register.assert_not_called()

    def test_ui_structure_and_stale_preview_protection(self):
        app = Path('app.js').read_text(encoding='utf-8')
        self.assertIn('schedulerEditorsGeneration', app)
        self.assertIn('card.dataset.editRevision', app)
        self.assertIn('root.oninput=', app)
        self.assertIn('root.onclick=', app)
        self.assertIn("role()!=='admin'", app)
        self.assertIn('expected_revision:job.revision', app)
        self.assertIn('Preview rollback', app)

    def test_js_preview_edit_apply_interactions(self):
        app = Path('app.js').read_text(encoding='utf-8')
        code = app[app.index('const schedulerScheduleDrafts='):app.index('async function loadRuntimeFeatures()')]
        harness = r'''
const assert=require('node:assert/strict');
const job={job:'prozorro',enabled:true,effective_enabled:true,spec:{kind:'hourly',minute:5},timezone:'Europe/Kyiv',revision:2,schedule:':05',history:[{revision:2}],last_status:'ok'};
const output={textContent:''},applyButton={disabled:true};
const fields={'[name="enabled"]':{checked:true},'[name="minute"]':{value:'17'}};
const card={dataset:{job:'prozorro'},querySelector:s=>s==='.scheduler-preview'?output:s==='[data-schedule-action="apply"]'?applyButton:fields[s],querySelectorAll:s=>[]};
const root={innerHTML:''},calls=[];let resolvePreview;
const API='/api',schedulerJobLabels={prozorro:'Prozorro'},role=()=> 'admin',$=()=>root,esc=x=>String(x??'').replaceAll('<','&lt;'),displayDate=x=>x,confirm=()=>true;
const request=async(url,options)=>{calls.push({url,options});if(!options)return {items:[job]};if(url.endsWith('/preview'))return new Promise(r=>resolvePreview=r);return {revision:3}};
let reloads=0;const loadRuntimeFeatures=async()=>{reloads++};
__CODE__
(async()=>{
 await loadSchedulerEditors();
 assert.match(root.innerHTML,/Preview rollback/);
 const click=action=>({target:{closest:()=>({disabled:false,dataset:{scheduleAction:action},closest:()=>card})}});
 const pending=root.onclick(click('preview'));
 assert.equal(calls.filter(c=>c.url.endsWith('/apply')).length,0);
 root.oninput({target:{closest:()=>card}});
 resolvePreview({before:job,after:job,next_run:'future',warnings:[]});await pending;
 assert.equal(applyButton.disabled,true);assert.equal(schedulerScheduleDrafts.size,0);
 const accepted=root.onclick(click('preview'));
 resolvePreview({before:job,after:job,next_run:'future',warnings:[]});await accepted;
 assert.equal(applyButton.disabled,false);
 await root.onclick(click('apply'));
 assert.equal(calls.filter(c=>c.url.endsWith('/apply')).length,1);
 assert.equal(JSON.parse(calls.at(-1).options.body).expected_revision,2);
 assert.equal(reloads,1);
 await loadSchedulerEditors();assert.equal(schedulerScheduleDrafts.size,0);
 console.log('scheduler interactions PASS');
})().catch(error=>{console.error(error);process.exit(1)});
'''.replace('__CODE__', code)
        result = subprocess.run(['node', '-e', harness], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
