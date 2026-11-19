"""Sandbox-only persistent control; synthetic disk, DB and HTTP requests only."""
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch,Mock
import background_jobs
import sandbox_runtime
import scheduler_runtime
import server
import auth_access


class SandboxAutomationControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.path=self.root/'pqm_sandbox.sqlite3'
        self.env=patch.dict(os.environ,{'PQM_SANDBOX':'1','PQM_DATA_DIR':str(self.root),
            'PQM_DB_PATH':str(self.path),'PQM_DISABLE_BACKGROUND_JOBS':'0'})
        self.env.start();self.addCleanup(self.env.stop)
        self.con=sqlite3.connect(self.path);self.addCleanup(self.con.close)
        scheduler_runtime.migrate(self.con)
        for job in scheduler_runtime.SCHEDULES:
            self.con.execute("INSERT INTO scheduler_job_settings(job_key,enabled,updated_at,updated_by,revision,schedule_json,timezone) VALUES(?,1,'fixture','admin',2,?,'Europe/Kyiv')",(job,'{"kind":"hourly","minute":50}'))
        self.con.commit()
        self.attest=patch.object(sandbox_runtime,'attest_internal_target',return_value=self.path)
        self.guard=self.attest.start();self.addCleanup(self.attest.stop)

    def disable(self):return background_jobs.disable_sandbox()

    def handler(self,method='POST',body=None,permissions=True):
        handler=object.__new__(server.Handler)
        handler.path='/api/admin/background-jobs'
        raw=json.dumps({'confirm':True} if body is None else body).encode()
        handler.headers={'Content-Length':str(len(raw))};handler.rfile=io.BytesIO(raw)
        handler.auth_access={'permissions':{'admin.manage':permissions}}
        handler.send_json=Mock(side_effect=lambda value,code=200:(code,value))
        with patch.object(server,'SANDBOX_MODE',True):
            return handler._do_POST() if method=='POST' else handler._do_GET()

    def test_disable_is_persistent_and_does_not_modify_scheduler_data(self):
        before=self.con.execute('SELECT * FROM scheduler_job_settings').fetchall();changes=self.con.total_changes
        self.assertFalse(background_jobs.disabled())
        result=self.disable()
        self.assertTrue(result['disabled']);self.assertTrue(result['persisted'])
        self.assertEqual(self.con.execute('SELECT * FROM scheduler_job_settings').fetchall(),before)
        self.assertEqual(self.con.total_changes,changes)
        self.guard.assert_called_once_with(self.path,require_operational=False)
        self.assertFalse(result['can_disable'])

    def test_restart_reads_same_marker_without_migration_or_write(self):
        self.disable()
        code='import background_jobs; assert background_jobs.disabled(); assert background_jobs.status()["persisted"]'
        for _ in range(2):
            result=subprocess.run([sys.executable,'-B','-c',code],env=dict(os.environ),capture_output=True,timeout=10)
            self.assertEqual(result.returncode,0)

    def test_disable_is_idempotent_and_has_no_enable_operation(self):
        self.disable();marker=background_jobs._state_path();before=marker.stat().st_mtime_ns
        self.disable()
        self.assertEqual(marker.stat().st_mtime_ns,before)
        self.assertEqual(self.handler(body={'confirm':True,'enabled':True})[0],400)
        self.assertTrue(background_jobs.disabled())

    def test_env_lock_cannot_be_overridden(self):
        with patch.dict(os.environ,{'PQM_DISABLE_BACKGROUND_JOBS':'1'}):
            state=background_jobs.status()
            self.assertTrue(state['disabled']);self.assertTrue(state['environment_locked'])
            self.assertFalse(state['can_disable'])
            self.assertEqual(self.handler(body={'enabled':True})[0],400)
            self.assertTrue(background_jobs.disabled())

    def test_marker_blocks_jobs_catchup_and_google_without_settings_changes(self):
        self.disable()
        with patch.object(server,'register_scheduler_job') as register,patch.object(server,'unregister_scheduler_job'):
            self.assertFalse(any(server.apply_scheduler_settings(catch_up=True).values()))
            register.assert_not_called()
        self.assertIsNone(scheduler_runtime.claim(self.path,'prozorro',trigger='scheduled'))
        self.assertFalse(server.start_violation_reports_sync(trigger='scheduled'))
        self.assertFalse(server.start_nazk_registry_refresh(trigger='scheduled_catchup'))
        self.assertFalse(server.google_writer_available())

    def test_prod_ignores_sandbox_marker_and_rejects_write(self):
        self.disable()
        with patch.dict(os.environ,{'PQM_SANDBOX':'0'}):
            self.assertFalse(background_jobs.disabled())
            with self.assertRaises(PermissionError):self.disable()
        handler=object.__new__(server.Handler);handler.path='/api/admin/background-jobs';handler.send_json=Mock(return_value='denied')
        with patch.object(server,'SANDBOX_MODE',False):
            handler._do_POST();self.assertEqual(handler.send_json.call_args.args[1],404)
            handler._do_GET();self.assertEqual(handler.send_json.call_args.args[1],404)

    def test_authorization_and_confirmation_are_required(self):
        self.assertEqual(self.handler(permissions=False)[0],403)
        self.assertEqual(self.handler(method='GET',permissions=False)[0],403)
        self.assertEqual(self.handler(body={'confirm':False})[0],400)
        self.assertEqual(self.handler(body={'confirm':1})[0],400)
        self.assertFalse(background_jobs._state_path().exists())
        self.assertEqual(auth_access.permission_key('POST','/api/admin/background-jobs'),'admin.manage')
        for role in ('officer','viewer'):
            self.assertFalse(server.mutation_allowed(role,'POST','/api/admin/background-jobs'))

    def test_endpoint_reports_actual_state_and_saves_only_after_confirmation(self):
        self.assertFalse(self.handler(method='GET')[1]['disabled'])
        code,state=self.handler()
        self.assertEqual(code,200);self.assertTrue(state['disabled'])
        self.assertTrue(self.handler(method='GET')[1]['disabled'])

    def test_attestation_failure_has_no_state_write(self):
        self.guard.side_effect=RuntimeError('wrong identity')
        self.assertEqual(self.handler()[0],503)
        self.assertFalse(background_jobs._state_path().exists())

    def test_marker_path_is_fixed_not_client_controlled(self):
        self.assertEqual(self.handler(body={'confirm':True,'path':'/production'})[0],400)
        self.assertFalse(background_jobs._state_path().exists())

    def test_uncertain_persistent_storage_fails_closed(self):
        with patch.object(background_jobs,'_state_path',side_effect=PermissionError('unavailable')):
            self.assertTrue(background_jobs.disabled())
            self.assertFalse(background_jobs.status()['can_disable'])

    def test_one_button_and_explicit_confirmation_in_ui(self):
        root=Path(__file__).parent
        html=(root/'index.html').read_text(encoding='utf-8')
        app=(root/'app.js').read_text(encoding='utf-8')
        self.assertEqual(html.count('id="disableSandboxAutomation"'),1)
        self.assertIn("if(!confirm('Вимкнути нові автоматичні запуски?",app)
        self.assertIn("button.disabled=!state.can_disable",app)
        self.assertIn("sandbox&&role()==='admin'",app)
        self.assertIn("Автоматику вимкнено",app);self.assertIn("Автоматика активна",app)

    def test_ui_confirmation_click_refresh_lock_and_roles_dynamically(self):
        result=subprocess.run(['node','test_sandbox_automation_control.cjs'],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('SANDBOX_AUTOMATION_UI=PASS',result.stdout)


if __name__=='__main__':unittest.main()
