"""Destination-attested SANDBOX writes retain RBAC and isolate PROD targets."""
import base64
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sandbox_smoke as base
import sandbox_documents
import sandbox_amcu
import scheduler_runtime
import table_widths


class DestinationPolicyTests(unittest.TestCase):
    def test_sandbox_db_only_and_local_operations_are_not_flag_allowlisted(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'PQM_SANDBOX':'1','PQM_SANDBOX_EDITS':'0','PQM_SANDBOX_OPERATIONAL':'0'}):
            data=Path(temp); owned=data/'pqm_sandbox.sqlite3'; owned.touch()
            with patch.object(base.sandbox,'validate_environment',return_value=(data,owned,'fixture')), \
                 patch.object(base.sandbox,'_verify_existing'):
                self.assertEqual(owned,base.sandbox.attest_internal_target(owned))
                self.assertTrue(base.sandbox.local_edits_enabled())
                self.assertTrue(base.sandbox.operational_enabled())
                for target in (data/'prod.sqlite3',data/'unknown.sqlite3'):
                    target.touch()
                    with self.subTest(target=target),self.assertRaises(RuntimeError):
                        base.sandbox.attest_internal_target(target)

    def test_attested_google_only_and_external_reads_not_mutations(self):
        sheet=base.sandbox.SANDBOX_EDR_SPREADSHEET_ID
        with patch.dict(os.environ, {'PQM_SANDBOX':'1','PQM_SANDBOX_EDR_GOOGLE':'0'}):
            url='https://sheets.googleapis.com/v4/spreadsheets/'+sheet+'/values/%D0%AE%D0%9E!A1'
            self.assertEqual(base.sandbox.GOOGLE_SHEETS_HOST,base.sandbox.validate_google_request(url,'PUT'))
            for target in ('https://sheets.googleapis.com/v4/spreadsheets/prod-sheet/values/A1',
                           'https://unknown.example/write'):
                with self.subTest(target=target),self.assertRaises(RuntimeError):
                    base.sandbox.validate_google_request(target,'POST')
            self.assertEqual('public-api.prozorro.gov.ua',base.sandbox.validate_public_read_request(
                'https://public-api.prozorro.gov.ua/api/2.5/tenders/example','GET'))
            with self.assertRaises(RuntimeError):
                base.sandbox.validate_public_read_request('https://public-api.prozorro.gov.ua/api/2.5/tenders/example','POST')

    def test_local_preferences_documents_and_scheduler_defaults(self):
        with sqlite3.connect(':memory:') as con:
            con.row_factory=sqlite3.Row
            table_widths.migrate(con)
            key='suppliersView:supplierRegistryBody'
            table_widths.save(con,key,{'єдрпоу-рнокпп':240},'sandbox.admin')
            self.assertEqual(240,table_widths.list_all(con)[key]['єдрпоу-рнокпп'])
            scheduler_runtime.migrate(con)
            self.assertEqual({'prozorro':False,'violation_reports':False,'nazk_registry':False},
                             scheduler_runtime.effective_enabled(con,{
                                 'prozorro':False,'violation_reports':False,'nazk_registry':False}))
        with patch.dict(os.environ, {'PQM_SANDBOX':'1','PQM_SANDBOX_DOCUMENTS':'0',
                                      'PQM_SANDBOX_AMCU_READ':'0'}):
            self.assertTrue(sandbox_documents.enabled())
            self.assertTrue(sandbox_amcu.enabled())


@unittest.skipIf(os.name == 'nt', 'HTTP bootstrap hard-link cleanup requires Linux filesystem semantics')
class EditableSandbox(base.SandboxHTTP):
    EDIT_MODE = '1'

    def test_11_offline_features_and_modules(self):
        status, flags, _ = self.request('/api/runtime-features')
        self.assertEqual(200,status)
        self.assertTrue(flags['sandbox_mode'])
        self.assertTrue(flags['safe_mode'])
        self.assertTrue(all(not row['configured_enabled'] and not row['running']
                            for row in flags['scheduler_jobs']))
        for path in ['/api/applications','/api/application-history','/api/violation-reports',
                     '/api/chats','/api/edr-monitoring']:
            self.assertEqual(200,self.request(path)[0],path)

    def test_12_attested_mutations_still_require_auth_and_known_route(self):
        # Safe mode no longer denies every local write. Unknown routes and
        # ordinary RBAC still fail closed while the destination is attested.
        self.assertEqual(404,self.request('/api/unknown-future-route','admin','POST',{})[0])
        self.assertEqual(403,self.request('/api/admin/table-widths','viewer','POST',
                                          {'table_key':'requests','widths':{'supplier':240}})[0])

    def test_12_attested_local_settings_and_unknown_route(self):
        key='suppliersView:supplierRegistryBody'
        payload={'table_key':key,'widths':{'єдрпоу-рнокпп':240}}
        self.assertEqual(403,self.request('/api/admin/table-widths','viewer','POST',payload)[0])
        self.assertEqual(200,self.request('/api/admin/table-widths','admin','POST',payload)[0])
        self.assertEqual(240,self.request('/api/table-widths','admin')[1]['tables'][key]['єдрпоу-рнокпп'])
        self.assertEqual(404,self.request('/api/unknown-future-route','admin','POST',{})[0])

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
