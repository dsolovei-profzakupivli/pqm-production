"""Current-tree multi-officer verification and resource ownership, no external I/O."""
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

import server
import runtime_memory
from validation.local_release_20260911 import test_production_memory_saved as fixture

class ProductionVerificationConcurrency(unittest.TestCase):
    setUp=fixture.ProductionSavedResults.setUp
    seed=fixture.ProductionSavedResults.seed

    def test_concurrent_officers_keep_results_after_ram_replacement_and_new_process(self):
        for n in range(8):self.seed('s'+str(n))
        jobs=runtime_memory.DocumentJobs()
        def analyze(sid,selection):
            return {'submission_id':sid,'selected_categories':['signature'],
                    'checks':[{'key':'signer','status':'ok','detail':sid}],
                    'signature':{'technical_status':'success'}}
        with patch.object(server,'DOCUMENT_CHECK_JOBS',jobs),patch.object(server,'analyze_application_documents',side_effect=analyze):
            for n in range(8):self.assertTrue(server.launch_document_check_job('j'+str(n),'s'+str(n)))
            deadline=time.monotonic()+5
            while any(jobs.get('j'+str(n))['status']=='running' for n in range(8)):
                self.assertLess(time.monotonic(),deadline);time.sleep(.005)
            self.assertTrue(all(jobs.get('j'+str(n))['status']=='complete' for n in range(8)))
            self.assertTrue(all('result' not in jobs.get('j'+str(n)) for n in range(8)))
        with patch.object(server,'DOCUMENT_CHECK_JOBS',runtime_memory.DocumentJobs()):
            with server.db() as con:
                records=con.execute('SELECT document_checked_at,document_check_result_json FROM application_fields').fetchall()
            self.assertEqual(len(records),8)
            self.assertTrue(all(row[0] and json.loads(row[1])['counts']['ok']==1 for row in records))
        script="import sqlite3,sys,json;c=sqlite3.connect(sys.argv[1]);c.execute('PRAGMA query_only=ON');r=c.execute('SELECT document_checked_at,document_check_result_json FROM application_fields').fetchall();assert len(r)==8 and all(t and json.loads(v)['counts']['ok']==1 for t,v in r);c.close();print('fresh process 8/8')"
        result=subprocess.check_output([sys.executable,'-B','-c',script,str(server.DB_PATH)],text=True)
        self.assertIn('fresh process 8/8',result)

    def test_active_jobs_are_not_evicted_and_admission_is_released(self):
        for sid in ['a','b','c']:self.seed(sid)
        jobs=runtime_memory.DocumentJobs(max_active=2,max_completed=1)
        gate=threading.Event()
        def analyze(sid,selection):
            gate.wait(3)
            return {'selected_categories':['signature'],'checks':[{'key':'signer','status':'ok'}]}
        with patch.object(server,'DOCUMENT_CHECK_JOBS',jobs),patch.object(server,'analyze_application_documents',side_effect=analyze):
            try:
                self.assertTrue(server.launch_document_check_job('a','a'))
                self.assertTrue(server.launch_document_check_job('b','b'))
                self.assertFalse(server.launch_document_check_job('c','c'))
                self.assertEqual(jobs.get('a')['status'],'running')
                self.assertEqual(jobs.get('b')['status'],'running')
            finally:gate.set()
            deadline=time.monotonic()+5
            while jobs._active:
                self.assertLess(time.monotonic(),deadline);time.sleep(.005)
            self.assertTrue(server.launch_document_check_job('c','c'))
            while jobs._active:
                self.assertLess(time.monotonic(),deadline);time.sleep(.005)
        with server.db() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM application_fields WHERE document_check_result_json<>''").fetchone()[0],3)

    def test_thread_start_failure_preserves_previous_result_and_releases_slot(self):
        self.seed()
        before=server._store_document_check_result('s',{'selected_categories':['signature'],'checks':[{'key':'signer','status':'ok'}]},'fixture')
        jobs=runtime_memory.DocumentJobs(max_active=1)
        with patch.object(server,'DOCUMENT_CHECK_JOBS',jobs),patch.object(server.threading.Thread,'start',side_effect=RuntimeError('synthetic')):
            with self.assertRaises(RuntimeError):server.launch_document_check_job('failed','s')
        self.assertEqual(jobs.get('failed')['status'],'error')
        self.assertTrue(jobs.start('next','s'))
        with server.db() as con:
            after=json.loads(con.execute("SELECT document_check_result_json FROM application_fields WHERE submission_id='s'").fetchone()[0])
        self.assertEqual(after,before)

    def test_background_and_manual_category_writes_do_not_lose_each_other(self):
        self.seed();barrier=threading.Barrier(2);errors=[]
        def save(manual):
            try:
                barrier.wait(timeout=3)
                result={'selected_categories':['signature' if manual else 'experience'],
                        'checks':[{'key':'signer' if manual else 'contract_experience','status':'ok' if manual else 'neutral','search_status':'found'}]}
                server._store_document_check_result('s',result,'Synthetic officer' if manual else 'Synthetic background',require_editable=manual)
            except Exception as exc:errors.append(repr(exc))
        threads=[threading.Thread(target=save,args=(manual,)) for manual in [True,False]]
        for thread in threads:thread.start()
        for thread in threads:thread.join(5);self.assertFalse(thread.is_alive())
        self.assertEqual(errors,[])
        with server.db() as con:
            result=json.loads(con.execute("SELECT document_check_result_json FROM application_fields WHERE submission_id='s'").fetchone()[0])
        self.assertEqual(set(result['category_results']),{'signature','experience'})
        self.assertEqual(result['counts']['ok'],1)
        self.assertEqual(result['counts']['neutral'],1)
