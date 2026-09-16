"""Allowlisted local sandbox edits retain RBAC and deny jobs/imports/egress."""
import base64
import os
import sqlite3
import unittest
from unittest.mock import patch
import sandbox_smoke as base


class AllowlistTests(unittest.TestCase):
    def test_explicit_flag_required_and_unknown_routes_fail_closed(self):
        with patch.dict(os.environ, {'PQM_SANDBOX':'1','PQM_SANDBOX_EDITS':'0'}):
            self.assertFalse(base.sandbox.local_edit_allowed('PATCH','/api/applications/sandbox-pending'))
        with patch.dict(os.environ, {'PQM_SANDBOX':'1','PQM_SANDBOX_EDITS':'1'}):
            self.assertTrue(base.sandbox.local_edit_allowed('PATCH','/api/applications/sandbox-pending'))
            for method,path in [('POST','/api/sync'),('POST','/api/unknown-future-feature'),
                ('PATCH','/api/applications/sandbox-pending/nazk-control'),
                ('PATCH','/api/applications/sandbox-pending%2Fnazk-control'),
                ('PUT','/api/applications/sandbox-pending'),('POST','/api/admin/templates/test/replace')]:
                self.assertFalse(base.sandbox.local_edit_allowed(method,path),(method,path))
        with patch.dict(os.environ, {'PQM_SANDBOX':'0','PQM_SANDBOX_EDITS':'1'}):
            self.assertFalse(base.sandbox.local_edit_allowed('PATCH','/api/account'))


class EditableSandbox(base.SandboxHTTP):
    EDIT_MODE = '1'

    def test_12_safe_mode_denies_updates(self):
        denied = ['/api/sync','/api/frameworks/refresh','/api/violation-reports/sync',
            '/api/bids-sync','/api/powerbi-export','/api/supplier-edr-sync','/api/google-oauth/start',
            '/api/admin/scheduler-jobs/prozorro','/api/admin/runtime-features/google',
            '/api/amcu-registry/refresh','/api/amcu-registry/upload','/api/nazk-registry/refresh',
            '/api/operational-tasks/rebuild','/api/admin/frameworks/import-new',
            '/api/protocol/generate','/api/edr-monitoring/termination-exclusions/create',
            '/api/unknown-future-route']
        for role in ['admin','officer','viewer']:
            for path in denied:
                with self.subTest(role=role,path=path):
                    status,result,_=self.request(path,role,'POST',{'enabled':True})
                    self.assertEqual(503,status);self.assertEqual('safe_mode',result['code'])
        for path in ['/api/amcu-registry?refresh=1','/api/nazk-registry?force=true',
                     '/api/applications/sandbox-pending/verify-documents/start']:
            self.assertEqual(503,self.request(path)[0])
        self.assertEqual(503,self.request('/api/applications/sandbox-pending?refresh=1',
                                        'admin','PATCH',{'notes':'must not save'})[0])

    def test_20_edits_and_final_status_locks(self):
        for role in ['admin','officer']:
            marker='synthetic local edit '+role
            self.assertEqual(200,self.request('/api/applications/sandbox-pending',role,'PATCH',{'notes':marker})[0])
            with sqlite3.connect(self.data/'pqm_sandbox.sqlite3') as con:
                self.assertEqual((marker,'sandbox.'+role),con.execute("SELECT notes,updated_by FROM application_fields WHERE submission_id='sandbox-pending'").fetchone())
            for sid in ['sandbox-admitted','sandbox-rejected']:
                self.assertEqual(409,self.request('/api/applications/'+sid,role,'PATCH',{'notes':'blocked'})[0])
        self.assertEqual(403,self.request('/api/applications/sandbox-pending','viewer','PATCH',{'notes':'blocked'})[0])
        # Current application manager edits retain local form behavior, not supplier checks/tasks.
        self.assertEqual(200,self.request('/api/applications/sandbox-pending','officer','PATCH',{'manager_name':'ТЕСТОВИЙ КЕРІВНИК SANDBOX'})[0])
        self.assertTrue(self.request('/api/runtime-features')[1]['sandbox_local_edits'])

    def test_30_local_account_and_admin_user_controls(self):
        self.assertEqual(200,self.request('/api/account','viewer','PATCH',{'display_name':'Тестовий глядач','presence_status':'away'})[0])
        payload={'username':'sandbox.extra','password':'synthetic-only-fixture-123!','role':'viewer'}
        for role in ['officer','viewer']:
            self.assertEqual(403,self.request('/api/admin/users',role,'POST',payload)[0])
        self.assertEqual(201,self.request('/api/admin/users','admin','POST',payload)[0])
        self.assertEqual(200,self.request('/api/admin/users/sandbox.extra','admin','PATCH',{'active':False})[0])
        self.assertEqual(200,self.request('/api/admin/users/sandbox.extra','admin','DELETE')[0])
        self.assertEqual(409,self.request('/api/admin/users/sandbox.admin','admin','DELETE')[0])
        self.assertEqual(409,self.request('/api/admin/users/sandbox.admin','admin','PATCH',{'role':'viewer'})[0])
        self.assertEqual(200,self.request('/api/admin/officers/1','admin','PATCH',{'active':False})[0])
        self.assertEqual(403,self.request('/api/applications/sandbox-pending','officer','PATCH',{'notes':'blocked inactive officer'})[0])
        self.assertEqual(200,self.request('/api/admin/officers/1','admin','PATCH',{'active':True})[0])

    def test_40_local_chat_attachment_and_submission_link(self):
        status,chat,_=self.request('/api/chats','admin','POST',{'members':['sandbox.officer'],'title':''})
        self.assertEqual(201,status);path='/api/chats/'+str(chat['id'])
        status,message,_=self.request(path+'/messages','admin','POST',{'body':'Synthetic sandbox smoke',
            'submission_id':'sandbox-pending','attachment':{'filename':'sandbox.txt','content_type':'text/plain',
            'content':base64.b64encode(b'SYNTHETIC ONLY').decode()}})
        self.assertEqual(201,status)
        self.assertEqual(200,self.request(path+'/messages','officer')[0])
        self.assertEqual(404,self.request(path+'/messages','viewer')[0])
        self.assertEqual(200,self.request(path+'/read','officer','POST',{})[0])

    def test_90_no_external_or_workflow_side_effects(self):
        with sqlite3.connect(self.data/'pqm_sandbox.sqlite3') as con:
            for table in ['operational_tasks','supplier_nazk_checks','supplier_nazk_reviews','nazk_registry','amcu_registry']:
                self.assertEqual(0,con.execute('SELECT COUNT(*) FROM '+table).fetchone()[0],table)
            self.assertEqual(0,con.execute('SELECT COUNT(*) FROM scheduler_job_settings WHERE enabled<>0').fetchone()[0])
            self.assertEqual(0,con.execute('SELECT COUNT(*) FROM runtime_feature_settings WHERE enabled<>0').fetchone()[0])
            self.assertEqual('ok',con.execute('PRAGMA integrity_check').fetchone()[0])
            self.assertEqual([],con.execute('PRAGMA foreign_key_check').fetchall())
        self.test_14_restart_keeps_accounts_and_fixture()
        with sqlite3.connect(self.data/'pqm_sandbox.sqlite3') as con:
            self.assertEqual('synthetic local edit officer',con.execute("SELECT notes FROM application_fields WHERE submission_id='sandbox-pending'").fetchone()[0])
            self.assertEqual(1,con.execute('SELECT COUNT(*) FROM chat_messages').fetchone()[0])


if __name__=='__main__':unittest.main(verbosity=2)
