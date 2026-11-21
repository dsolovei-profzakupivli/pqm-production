"""Acceptance tests for the approved Sandbox functionality repairs; synthetic only."""
import copy
import json
from pathlib import Path
import sqlite3
import threading
import unittest
from unittest.mock import Mock,patch

import server
import sandbox_runtime
import runtime_memory


class SandboxFunctionalityTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.enterContext(patch.object(server,'DB_PATH',Path(self.folder.name)/'synthetic.sqlite3'))
        self.enterContext(patch.object(server,'api_get',side_effect=AssertionError('No external API')))
        server.init_db();server.init_reference_tables(server.DB_PATH)
        with server.db() as con:
            con.execute("INSERT INTO frameworks(id,pretty_id,status,dk_code,raw_json,synced_at) VALUES ('f','SYNTHETIC','active','44190000-8','{}','before')")
            con.execute("INSERT INTO framework_officers(framework_id,officer,category,synced_at) VALUES ('f','Officer','Synthetic','before')")
        self.enterContext(patch.object(server,'SANDBOX_MODE',True))
        self.enterContext(patch.object(server,'sandbox_runtime',sandbox_runtime,create=True))
        self.attest=self.enterContext(patch.object(sandbox_runtime,'attest_internal_target',return_value=None))
        self.enterContext(patch.object(server.background_jobs,'disabled',return_value=False))
        self.enterContext(patch.object(server,'CONTRACT_EXPERIENCE_PENDING',set()))
        self.enterContext(patch.object(server,'CONTRACT_EXPERIENCE_SCOPE_PENDING',set()))
        self.enterContext(patch.object(server,'CONTRACT_EXPERIENCE_RETRY_ATTEMPTS',{}))
        self.enterContext(patch.object(server,'CONTRACT_EXPERIENCE_RETRY_PENDING',set()))

    def seed(self,sid='s',status='pending'):
        with server.db() as con:
            con.execute("INSERT INTO submissions(id,framework_id,supplier_code,supplier_name,date_published,qualification_id,documents_json,raw_json,synced_at) VALUES (?,'f','12345678','Synthetic','2026-10-01T00:00:00Z',?,'[]','{}','before')",(sid,'q-'+sid))
            con.execute("INSERT INTO qualifications(id,framework_id,submission_id,status,raw_json,synced_at) VALUES (?,'f',?,?,'{}','before')",('q-'+sid,sid,status))
            con.execute('INSERT INTO application_fields(submission_id) VALUES (?)',(sid,))

    def test_saved_history_verdicts_and_counters_never_change(self):
        raw={'checks':[{'key':'signer','status':'ok','detail':'Original'},{'key':'mvs_person','status':'warning','detail':'Manual'}],
             'counts':{'ok':1,'warning':1,'error':0,'neutral':0},'category_results':{'signature':{'status':'ok'}},'ready':True}
        before=copy.deepcopy(raw)
        result=server.document_result_for_current_sources('s',raw,[('supplier',{'id':'doc','hash':'one'})])
        self.assertEqual(result['counts'],before['counts']);self.assertEqual(result['checks'][0]['status'],'ok')
        self.assertEqual(result['category_results'],before['category_results']);self.assertEqual(raw,before)
        self.assertEqual(result,before);self.assertTrue(result['ready'])
        self.assertNotIn('source_freshness',result)

    def test_changed_sources_keep_actual_error_without_freshness_warnings(self):
        docs=[('supplier',{'id':'doc','hash':'one'})]
        raw={'checks':[{'key':'signer','status':'error','detail':'Original error'}],'counts':{'ok':0,'warning':0,'error':1,'neutral':0},'document_fingerprints':{'signature':server.document_source_fingerprint(docs)}}
        result=server.document_result_for_current_sources('s',raw,[('supplier',{'id':'doc','hash':'two'})])
        self.assertEqual(result['counts'],raw['counts']);self.assertEqual(result['checks'][0]['status'],'error')
        self.assertEqual(result['checks'][0]['detail'],'Original error');self.assertEqual(result,raw)

    def test_legacy_business_checks_are_kept_as_saved_history(self):
        raw={'checks':[{'key':'business_contract','status':'ok'}],'counts':{'ok':1},'ready':True}
        self.assertEqual(server.document_result_for_current_sources('s',raw,[])['checks'],raw['checks'])

    def test_pending_only_queue_and_duplicate_suppression(self):
        self.seed('a');self.seed('b','active');self.seed('c','unsuccessful')
        with patch.object(server.CONTRACT_EXPERIENCE_EXECUTOR,'submit') as submit:
            self.assertEqual(server.enqueue_contract_experience_search(['a','a','b','c']),1)
            self.assertEqual(server.enqueue_contract_experience_search(['a']),0)
            submit.assert_called_once();self.assertEqual(submit.call_args.args[1],['a'])

    def test_scope_admission_is_bounded_and_rolls_back_on_executor_failure(self):
        with patch.object(server.CONTRACT_EXPERIENCE_EXECUTOR,'submit') as submit:
            for n in range(300):server.enqueue_contract_experience_search([],framework_id='f'+str(n))
            self.assertEqual(submit.call_count,128);self.assertEqual(len(server.CONTRACT_EXPERIENCE_SCOPE_PENDING),128)
        server.CONTRACT_EXPERIENCE_SCOPE_PENDING.clear()
        with patch.object(server.CONTRACT_EXPERIENCE_EXECUTOR,'submit',side_effect=RuntimeError('synthetic')):
            with self.assertRaises(RuntimeError):server.enqueue_contract_experience_search([],framework_id='f')
        self.assertFalse(server.CONTRACT_EXPERIENCE_SCOPE_PENDING)

    def test_scope_batches_do_not_retain_all_application_ids(self):
        for n in range(90):self.seed('%03d'%n)
        self.seed('done','active');sizes=[]
        def worker(ids):
            sizes.append(len(ids));server.CONTRACT_EXPERIENCE_PENDING.difference_update(ids)
        with patch.object(server,'contract_experience_worker',side_effect=worker):server._sandbox_experience_scope_worker('f')
        self.assertEqual(sum(sizes),90);self.assertLessEqual(max(sizes),32);self.assertFalse(server.CONTRACT_EXPERIENCE_PENDING)

    def test_background_interlock_and_wrong_target_fail_before_open(self):
        with patch.object(server.background_jobs,'disabled',return_value=True),patch.object(server.CONTRACT_EXPERIENCE_EXECUTOR,'submit') as submit:
            self.assertEqual(server.enqueue_contract_experience_search([],framework_id='f'),0);submit.assert_not_called()
        self.attest.side_effect=RuntimeError('wrong target')
        with patch.object(server,'db',side_effect=AssertionError('Must not open')):
            with self.assertRaises(RuntimeError):server.enqueue_contract_experience_search(['s'])
            with self.assertRaises(RuntimeError):server._store_document_check_result('s',{},'test',require_pending=True)

    def test_changed_qualification_during_search_prevents_storage(self):
        self.seed()
        def search(*args):
            with server.db() as con:con.execute("UPDATE qualifications SET status='active' WHERE id='q-s'")
            return {'status':'found','symbol':'+','message':'Synthetic','candidates':[]}
        with patch.object(server,'search_supplier_contract_experience',side_effect=search):server.contract_experience_worker(['s'])
        with server.db() as con:self.assertIn(con.execute("SELECT document_check_result_json FROM application_fields WHERE submission_id='s'").fetchone()[0],('',None))

    def test_existing_worker_persists_result_and_reuses_fresh_category(self):
        self.seed();signature={'checks':[{'key':'signer','status':'ok'}],'selected_categories':['signature'],'counts':{'ok':1}}
        server._store_document_check_result('s',signature,'fixture')
        found={'status':'found','symbol':'+','message':'Synthetic','candidates':[{'contract_id':'UA-SYNTHETIC','url':'https://prozorro.gov.ua/uk/contract/UA-SYNTHETIC'}]}
        with patch.object(server,'search_supplier_contract_experience',return_value=found) as search:
            server.contract_experience_worker(['s']);server.contract_experience_worker(['s']);self.assertEqual(search.call_count,1)
        with server.db() as con:raw=json.loads(con.execute("SELECT document_check_result_json FROM application_fields WHERE submission_id='s'").fetchone()[0])
        self.assertEqual(raw['category_results']['signature']['checks'],signature['checks'])
        self.assertEqual(server.document_check_category_summaries(raw)['experience'],'ok')

    def test_uo_revision_ignores_sync_timestamps_but_detects_semantic_changes(self):
        self.seed();before=server.uo_statistics_revision();self.assertIsNotNone(before)
        with server.db() as con:con.execute("UPDATE submissions SET synced_at='later'")
        self.assertEqual(server.uo_statistics_revision(),before)
        with server.db() as con:con.execute("UPDATE qualifications SET status='active'")
        self.assertNotEqual(server.uo_statistics_revision(),before)

    def test_get_presentation_does_not_update_sqlite(self):
        self.seed();raw={'checks':[{'key':'signer','status':'ok'}],'counts':{'ok':1}}
        with server.db() as con:con.execute("UPDATE application_fields SET document_check_result_json=?",(json.dumps(raw),))
        with server.db() as con:before=con.execute('SELECT document_check_result_json FROM application_fields').fetchone()[0]
        server.document_result_for_current_sources('s',json.loads(before))
        with server.db() as con:self.assertEqual(con.execute('SELECT document_check_result_json FROM application_fields').fetchone()[0],before)

class LastCompletedResultTests(unittest.TestCase):
    setUp=SandboxFunctionalityTests.setUp
    seed=SandboxFunctionalityTests.seed
    def test_failed_or_interrupted_repeat_keeps_last_json_and_date(self):
        self.seed()
        original={'checks':[{'key':'signer','status':'ok'}],'selected_categories':['signature'],'signature':{'technical_status':'success'},'counts':{'ok':1}}
        server._store_document_check_result('s',original,'fixture')
        with server.db() as con:before=tuple(con.execute("SELECT document_check_result_json,document_checked_at FROM application_fields WHERE submission_id='s'").fetchone())
        jobs=runtime_memory.DocumentJobs()
        for failure in [
            {'checks':[{'key':'eds_verification','status':'warning'}],'selected_categories':['signature'],'signature':{'technical_status':'technical_error'}},
            {'checks':[{'key':'eds_verification','status':'warning'}],'selected_categories':['signature'],'signature':{'technical_status':'service_unavailable'}},
            {'checks':[{'key':'mvs_signature','status':'warning'}],'selected_categories':['mvs_signature'],'mvs_seal':{'technical_status':'technical_error'}},
            {'checks':[{'key':'signer','status':'warning'}],'files':[{'error':'download failed'}]},
            TimeoutError('interrupted')]:
            job='failed-'+str(len(jobs));jobs.start(job,'s')
            options={'side_effect':failure} if isinstance(failure,Exception) else {'return_value':failure}
            with patch.object(server,'DOCUMENT_CHECK_JOBS',jobs),patch.object(server,'analyze_application_documents',**options),patch.object(server.SERVER_LOG,'exception'):
                server.document_check_worker(job,'s',{'0':['signature']})
            self.assertEqual(jobs.get(job)['status'],'error');self.assertNotIn('result',jobs.get(job))
            with server.db() as con:self.assertEqual(tuple(con.execute("SELECT document_check_result_json,document_checked_at FROM application_fields WHERE submission_id='s'").fetchone()),before)

    def test_repeat_success_replaces_one_record_and_keeps_result_out_of_ram(self):
        self.seed();jobs=runtime_memory.DocumentJobs()
        for n in range(3):
            job='done-'+str(n);jobs.start(job,'s')
            result={'checks':[{'key':'signer','status':'ok','detail':'run '+str(n)}],'selected_categories':['signature'],'signature':{'technical_status':'success'},'counts':{'ok':1}}
            with patch.object(server,'DOCUMENT_CHECK_JOBS',jobs),patch.object(server,'analyze_application_documents',return_value=result):server.document_check_worker(job,'s')
            self.assertEqual(jobs.get(job)['status'],'complete');self.assertNotIn('result',jobs.get(job))
        with server.db() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM application_fields').fetchone()[0],1)
            raw,stamp=con.execute("SELECT document_check_result_json,document_checked_at FROM application_fields WHERE submission_id='s'").fetchone()
        result=json.loads(raw);self.assertEqual(result['checks'][0]['detail'],'run 2');self.assertEqual(result['checked_at'],stamp)
        self.assertEqual(result['document_check_job_id'],'done-2')

    def test_manual_repeat_replaces_prior_manual_categories_not_background_experience(self):
        self.seed()
        prior={'checks':[{'key':'signer','status':'error'},{'key':'mvs_person','status':'error'},{'key':'contract_experience','status':'neutral','search_status':'none'}],'selected_categories':['signature','mvs','experience']}
        server._store_document_check_result('s',prior,'fixture')
        jobs=runtime_memory.DocumentJobs();jobs.start('replacement','s')
        current={'checks':[{'key':'signer','status':'ok'}],'selected_categories':['signature'],'signature':{'technical_status':'success'}}
        with patch.object(server,'DOCUMENT_CHECK_JOBS',jobs),patch.object(server,'analyze_application_documents',return_value=current):server.document_check_worker('replacement','s')
        with server.db() as con:result=json.loads(con.execute("SELECT document_check_result_json FROM application_fields WHERE submission_id='s'").fetchone()[0])
        self.assertEqual([item['key'] for item in result['checks']],['signer','contract_experience'])
        self.assertNotIn('mvs',result['category_results']);self.assertEqual(result['counts']['error'],0)
        self.assertEqual(result['document_check_job_id'],'replacement')

    def test_background_experience_does_not_change_complex_check_time(self):
        self.seed();server._store_document_check_result('s',{'checks':[{'key':'signer','status':'ok'}],'selected_categories':['signature']},'fixture')
        with server.db() as con:stamp=con.execute("SELECT document_checked_at FROM application_fields WHERE submission_id='s'").fetchone()[0]
        found={'status':'found','symbol':'+','message':'Synthetic','candidates':[]}
        with patch.object(server,'search_supplier_contract_experience',return_value=found):server.contract_experience_worker(['s'])
        with server.db() as con:after=con.execute("SELECT document_checked_at FROM application_fields WHERE submission_id='s'").fetchone()[0]
        self.assertEqual(after,stamp)

    def test_completion_racing_with_row_lock_keeps_previous_result(self):
        self.seed();server._store_document_check_result('s',{'checks':[{'key':'signer','status':'ok'}],'selected_categories':['signature']},'fixture')
        with server.db() as con:before=con.execute("SELECT document_check_result_json FROM application_fields WHERE submission_id='s'").fetchone()[0]
        def analyze(*args):
            with server.db() as con:con.execute("UPDATE qualifications SET status='active' WHERE id='q-s'")
            return {'checks':[{'key':'signer','status':'warning'}],'selected_categories':['signature'],'signature':{'technical_status':'success'}}
        jobs=runtime_memory.DocumentJobs();jobs.start('late','s')
        with patch.object(server,'DOCUMENT_CHECK_JOBS',jobs),patch.object(server,'analyze_application_documents',side_effect=analyze),patch.object(server.SERVER_LOG,'exception'):
            server.document_check_worker('late','s')
        self.assertEqual(jobs.get('late')['status'],'error')
        with server.db() as con:self.assertEqual(con.execute("SELECT document_check_result_json FROM application_fields WHERE submission_id='s'").fetchone()[0],before)

    def test_completed_job_cache_discards_any_result_payload(self):
        jobs=runtime_memory.DocumentJobs();jobs.start('large','s')
        jobs.finish('large',{'status':'complete','result':{'data':'x'*1000000}})
        self.assertNotIn('result',jobs.get('large'));self.assertLess(jobs._completed._bytes,1024)

class SavedHistoryHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import sys
        sys.path.insert(0,str(Path(server.__file__).parent/'validation'))
        import web_smoke
        cls.web=web_smoke
        cls.patch_db=patch.object(server,'DB_PATH',Path(web_smoke.TEMP.name)/'http-history.sqlite3');cls.patch_db.start()
        cls.patch_auth=patch.object(server,'AUTH_ENABLED',True);cls.patch_auth.start()
        web_smoke.fixture()
        checks=[{'key':'signer'+str(i),'status':'ok' if i<16 else 'warning','detail':'Original'} for i in range(17)]
        cls.saved={'checks':checks,'counts':{'ok':16,'warning':1,'error':0,'neutral':0},'ready':False,'document_check_job_id':'fixture-job','checked_at':'2026-11-21T10:00:00Z'}
        with server.db() as con:
            con.execute("UPDATE submissions SET documents_json=? WHERE id='pending'",(json.dumps([{'id':'doc','hash':'one'}]),))
            con.execute("UPDATE application_fields SET document_check_result_json=?,document_check_status='warning',document_check_summary='Original 16/1',document_checked_at='2026-11-21T10:00:00Z' WHERE submission_id='pending'",(json.dumps(cls.saved),))
        cls.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        cls.port=cls.http.server_address[1];threading.Thread(target=cls.http.serve_forever,daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown();cls.http.server_close();cls.patch_auth.stop();cls.patch_db.stop()

    def get(self,path,role):
        import base64,http.client
        con=http.client.HTTPConnection('127.0.0.1',self.port,timeout=10)
        auth=base64.b64encode(('fixture-'+role+':'+self.web.PASSWORD).encode()).decode()
        con.request('GET',path,headers={'Authorization':'Basic '+auth});response=con.getresponse();data=json.loads(response.read());con.close()
        self.assertEqual(response.status,200,data);return data

    def test_saved_statuses_are_identical_for_three_read_roles(self):
        with server.db() as con:before=con.execute("SELECT document_check_result_json FROM application_fields WHERE submission_id='pending'").fetchone()[0]
        with patch.object(server,'api_get',side_effect=AssertionError('No external requests')), patch.object(server,'application_documents',side_effect=AssertionError('No source reads')), patch.object(server,'document_source_fingerprint',side_effect=AssertionError('No fingerprint evaluation')), patch.object(server,'verify_prozorro_eds',side_effect=AssertionError('No verification')):
            for role in ['admin','officer','viewer']:
                result=self.get('/api/applications/pending/document-check-result',role)
                self.assertEqual(result['counts'],self.saved['counts']);self.assertNotIn('source_freshness',result)
                self.assertEqual([x['status'] for x in result['checks']],[x['status'] for x in self.saved['checks']])
        with server.db() as con:self.assertEqual(con.execute("SELECT document_check_result_json FROM application_fields WHERE submission_id='pending'").fetchone()[0],before)

    def test_saved_and_job_endpoints_keep_actual_counters_after_ram_reset(self):
        jobs=runtime_memory.DocumentJobs();jobs.start('fixture-job','pending');jobs.finish('fixture-job',{'status':'complete','result':self.saved})
        with patch.object(server,'DOCUMENT_CHECK_JOBS',jobs):
            result=self.get('/api/document-check-jobs/fixture-job','admin')
            self.assertEqual(result['result']['counts'],self.saved['counts'])
        with patch.object(server,'DOCUMENT_CHECK_JOBS',runtime_memory.DocumentJobs()):
            self.assertEqual(self.get('/api/applications/pending/document-check-result','admin')['counts'],self.saved['counts'])
        listing=self.get('/api/applications?page=1&size=100','admin');row=next(item for item in listing['items'] if item['id']=='pending')
        self.assertEqual(row['document_check_summary'],'Original 16/1');self.assertNotIn('document_check_source_freshness',row)

    def test_final_row_blocks_both_check_entrypoints_but_allows_saved_read(self):
        import base64,http.client
        with server.db() as con:
            for sid in ['admitted','rejected']:
                con.execute('UPDATE application_fields SET document_check_result_json=?,document_check_status=? WHERE submission_id=?',(json.dumps(self.saved),'warning',sid))
        with patch.object(server,'launch_document_check_job') as launch:
            for sid in ['admitted','rejected']:
                for method,suffix in [('GET','verify-documents/start'),('POST','verify-documents')]:
                    client=http.client.HTTPConnection('127.0.0.1',self.port,timeout=10)
                    auth=base64.b64encode(('fixture-admin:'+self.web.PASSWORD).encode()).decode()
                    client.request(method,'/api/applications/'+sid+'/'+suffix,headers={'Authorization':'Basic '+auth})
                    response=client.getresponse();data=json.loads(response.read());client.close()
                    self.assertEqual(response.status,409,data);self.assertEqual(data.get('code'),'application_final_locked')
                for role in ['admin','officer','viewer']:
                    self.assertEqual(self.get('/api/applications/'+sid+'/document-check-result',role)['counts'],self.saved['counts'])
            launch.assert_not_called()

if __name__=='__main__':unittest.main()
