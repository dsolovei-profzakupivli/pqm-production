"""Scoped experience exception with global automation OFF; synthetic only."""
import json
import os
from pathlib import Path
import threading
import unittest
from unittest.mock import Mock,patch
import background_jobs
import server
import sandbox_runtime
import test_sandbox_functionality_repair as repair
REAL_DISABLED=background_jobs.disabled
REAL_ATTEST=sandbox_runtime.attest_internal_target
FOUND={'status':'found','symbol':'+','message':'Synthetic','candidates':[{'contract_id':'UA-SYNTHETIC','url':'https://prozorro.gov.ua/uk/contract/UA-SYNTHETIC'}]}

class ExperiencePolicyTests(unittest.TestCase):
    seed=repair.SandboxFunctionalityTests.seed
    def setUp(self):
        repair.SandboxFunctionalityTests.setUp(self)
        self.enterContext(patch.dict(os.environ,{'PQM_SANDBOX':'1','PQM_DISABLE_BACKGROUND_JOBS':'1','PQM_DATA_DIR':self.folder.name,'PQM_DB_PATH':str(Path(self.folder.name)/'pqm_sandbox.sqlite3')}))
        self.enterContext(patch.object(background_jobs,'disabled',REAL_DISABLED))
        self.search=self.enterContext(patch.object(server,'search_supplier_contract_experience',return_value=FOUND))
        for name,empty in [('CONTRACT_EXPERIENCE_ACTIVE',set()),('CONTRACT_EXPERIENCE_RETRY_READY',set()),('CONTRACT_EXPERIENCE_RETRY_TIMERS',{}),('CONTRACT_EXPERIENCE_DEFERRED_SCOPES',{})]:
            self.enterContext(patch.object(server,name,empty))
        self.addCleanup(lambda:[getattr(entry[1],'cancel',lambda:None)() for entry in server.CONTRACT_EXPERIENCE_RETRY_TIMERS.values()])
    def raw(self,sid='s'):
        with server.db() as con:
            row=con.execute('SELECT document_check_result_json,document_checked_at FROM application_fields WHERE submission_id=?',(sid,)).fetchone()
        return tuple(row) if row else None
    def test_named_exception_keeps_global_interlock_and_other_jobs_off(self):
        self.assertTrue(background_jobs.disabled());self.assertTrue(server.contract_experience_enabled())
        target=Mock()
        self.assertFalse(server.start_prozorro_sync(target,mode='synthetic',message='synthetic'))
        with patch.object(server,'google_writer_manual_available') as writer:
            self.assertFalse(server.google_writer_available());writer.assert_not_called()
        with patch.object(server,'register_scheduler_job') as register:
            server.apply_scheduler_settings(catch_up=True);register.assert_not_called()
        target.assert_not_called();self.assertEqual(os.environ['PQM_DISABLE_BACKGROUND_JOBS'],'1')
    def test_production_does_not_receive_exception(self):
        with patch.object(server,'SANDBOX_MODE',False):self.assertFalse(server.contract_experience_enabled())
        with patch.dict(os.environ,{'PQM_SANDBOX':'0'}):self.assertFalse(background_jobs.sandbox_experience_allowed())
    def test_emergency_marker_and_uncertain_state_block_all_experience_paths(self):
        self.seed();marker=Path(self.folder.name)/'.pqm-background-jobs-disabled';marker.touch()
        self.assertFalse(server.contract_experience_enabled())
        with patch.object(server.CONTRACT_EXPERIENCE_EXECUTOR,'submit') as submit:
            self.assertEqual(server.enqueue_missing_sandbox_experience(),0)
            self.assertEqual(server.enqueue_contract_experience_search(['s'],'f'),0);submit.assert_not_called()
        server.contract_experience_worker(['s']);self.search.assert_not_called()
        self.assertFalse(server._schedule_contract_experience_retry('s'))
        self.assertIsNone(server._store_document_check_result('s',{},'fixture',require_pending=True))
        with patch.object(background_jobs,'status',return_value={'disabled':True,'state_error':True}):self.assertFalse(background_jobs.sandbox_experience_allowed())
    def test_attestation_fails_before_queue_and_no_search_or_database_write(self):
        self.seed();before=self.raw()
        with patch.object(sandbox_runtime,'attest_internal_target',REAL_ATTEST):
            with self.assertRaises(RuntimeError):server.enqueue_missing_sandbox_experience()
        self.search.assert_not_called();self.assertEqual(self.raw(),before)
    def test_manual_ingestion_context_admits_only_existing_scope_once(self):
        with patch.object(server.CONTRACT_EXPERIENCE_EXECUTOR,'submit') as submit:
            self.assertEqual(server.enqueue_contract_experience_search([],'f'),1)
            self.assertEqual(server.enqueue_contract_experience_search([],'f'),0)
            submit.assert_called_once_with(server._sandbox_experience_scope_worker,'f')
    def test_authorized_manual_ingestion_starts_experience_but_not_automatic_sync(self):
        from contextlib import nullcontext
        self.seed()
        class Thread:
            def __init__(self,target,**kwargs):self.target=target
            def start(self):self.target()
        def ingest():server.enqueue_contract_experience_search(['s'],'f')
        with patch.object(server,'SYNC_STATE',{'running':False}),patch.object(server.scheduler_runtime,'claim',return_value='synthetic-owner') as claim,patch.object(server.scheduler_runtime,'keepalive',return_value=nullcontext()),patch.object(server,'_finish_scheduler_lease'),patch.object(server,'uo_statistics_revision',return_value='unchanged'),patch.object(server.threading,'Thread',Thread),patch.object(server.CONTRACT_EXPERIENCE_EXECUTOR,'submit',side_effect=lambda fn,*args:fn(*args)):
            self.assertTrue(server.start_prozorro_sync(ingest,mode='synthetic',message='fixture',trigger='manual',manual_authorized=True,actor='fixture'))
            self.assertTrue(claim.call_args.kwargs['manual_authorized'])
            self.assertFalse(server.start_prozorro_sync(ingest,mode='synthetic',message='fixture',trigger='scheduled'))
            self.assertEqual(claim.call_count,1)
        self.search.assert_called_once();self.assertIn('UA-SYNTHETIC',self.raw()[0])
        self.assertTrue(background_jobs.disabled());self.assertEqual(os.environ['PQM_DISABLE_BACKGROUND_JOBS'],'1')

    def test_backlog_does_not_load_prozorro_and_preserves_all_existing_outcomes(self):
        for i in range(70):self.seed('s%03d'%i)
        self.seed('final','active');self.seed('rejected','unsuccessful')
        saved={}
        for i,value in [(0,{'category_results':{'experience':{'checks':[],'status':'ok'}}}),(1,{'checks':[{'key':'contract_experience','status':'neutral','search_status':'none'}]}),(2,{'checks':[{'key':'business_legacy','status':'ok'}]}),(3,{'contract_experience':{'status':'unavailable'}})]:
            sid='s%03d'%i
            with server.db() as con:con.execute("UPDATE application_fields SET document_check_result_json=?,document_checked_at='historical' WHERE submission_id=?",(json.dumps(value),sid))
            saved[sid]=self.raw(sid)
        with patch.object(server.CONTRACT_EXPERIENCE_EXECUTOR,'submit') as submit:
            self.assertEqual(server.enqueue_missing_sandbox_experience(),1)
            self.assertEqual(server.enqueue_missing_sandbox_experience(),0)
            submit.assert_called_once_with(server._sandbox_experience_scope_worker,None)
        with patch.object(server,'contract_experience_worker',wraps=server.contract_experience_worker) as worker:
            server._sandbox_experience_scope_worker(None)
            self.assertLessEqual(max(len(call.args[0]) for call in worker.call_args_list),32)
        self.assertEqual(self.search.call_count,66)
        for sid,before in saved.items():self.assertEqual(self.raw(sid),before)
        for sid in ['final','rejected']:self.assertIn(self.raw(sid)[0],('',None))
        self.assertFalse(server.CONTRACT_EXPERIENCE_PENDING);self.assertFalse(server.CONTRACT_EXPERIENCE_SCOPE_PENDING)
        server._sandbox_experience_scope_worker(None);self.assertEqual(self.search.call_count,66)
    def test_full_queue_yields_and_resumes_without_dropping_missing_rows(self):
        for n in range(35):self.seed('s%03d'%n)
        server.CONTRACT_EXPERIENCE_PENDING.update('other-'+str(n) for n in range(128))
        server.CONTRACT_EXPERIENCE_SCOPE_PENDING.add('__missing_pending__')
        with patch.object(server.CONTRACT_EXPERIENCE_EXECUTOR,'submit') as submit:
            server._sandbox_experience_scope_worker(None)
            submit.assert_not_called()
            self.search.assert_not_called();self.assertIn('__missing_pending__',server.CONTRACT_EXPERIENCE_SCOPE_PENDING)
            self.assertEqual(server.CONTRACT_EXPERIENCE_DEFERRED_SCOPES['__missing_pending__'],(None,''))
            server.CONTRACT_EXPERIENCE_PENDING.clear()
            server._sandbox_experience_drain()
            submit.assert_called_once_with(server._sandbox_experience_scope_worker,None,'')
        submit.call_args.args[0](*submit.call_args.args[1:])
        self.assertEqual(self.search.call_count,35)
        self.assertFalse(server.CONTRACT_EXPERIENCE_PENDING);self.assertFalse(server.CONTRACT_EXPERIENCE_SCOPE_PENDING)

    def test_racing_result_and_finalization_are_rechecked_before_write(self):
        self.seed()
        def racing(*args):
            with server.db() as con:con.execute("UPDATE application_fields SET document_check_result_json=? WHERE submission_id='s'",(json.dumps({'checks':[{'key':'contract_experience','status':'neutral','detail':'other completed search'}]}),))
            return FOUND
        self.search.side_effect=racing;server.contract_experience_worker(['s'])
        self.assertIn('other completed search',self.raw()[0]);self.assertNotIn('UA-SYNTHETIC',self.raw()[0])
        self.seed('late')
        def finalize(*args):
            with server.db() as con:con.execute("UPDATE qualifications SET status='active' WHERE submission_id='late'")
            return FOUND
        self.search.side_effect=finalize;server.contract_experience_worker(['late']);self.assertIn(self.raw('late')[0],('',None))
    def test_technical_failure_not_saved_and_retries_are_bounded(self):
        self.seed();before=self.raw();self.search.return_value={'status':'unavailable','symbol':'-','message':'synthetic','candidates':[]}
        timers=[]
        class Timer:
            def __init__(self,delay,callback):self.callback=callback;timers.append(self)
            def start(self):pass
        with patch.object(server.threading,'Timer',Timer),patch.object(server.CONTRACT_EXPERIENCE_EXECUTOR,'submit'):
            server.contract_experience_worker(['s']);self.assertEqual(self.raw(),before)
            for _ in range(2):
                timers[-1].callback();server.contract_experience_worker(['s'])
            self.assertEqual(len(timers),2);self.assertEqual(self.raw(),before)
    def manual_timers(self, immediate=False, fail_start=False):
        timers=[]
        class Timer:
            def __init__(self,delay,callback):self.callback=callback;self.delay=delay;self.cancelled=False;timers.append(self)
            def start(self):
                if fail_start:raise RuntimeError('synthetic timer start failure')
                if immediate:self.callback()
            def cancel(self):self.cancelled=True
        self.enterContext(patch.object(server.threading,'Timer',Timer))
        return timers
    def unavailable(self,*args):
        return {'status':'unavailable','symbol':'-','message':'synthetic','candidates':[]}
    def test_retry_expiring_during_next_application_is_not_lost(self):
        self.seed('a');self.seed('b');timers=self.manual_timers()
        def search(*args):
            if args[-1]=='b':timers[0].callback()
            return self.unavailable()
        self.search.side_effect=search
        with server.CONTRACT_EXPERIENCE_PENDING_LOCK:server._sandbox_experience_admit_locked(['a','b'])
        with patch.object(server.CONTRACT_EXPERIENCE_EXECUTOR,'submit') as submit:
            server.contract_experience_worker(['a','b'])
            submit.assert_called_once_with(server.contract_experience_worker,['a'])
            self.assertEqual(server.CONTRACT_EXPERIENCE_RETRY_ATTEMPTS['a'],1)
            self.assertIn('a',server.CONTRACT_EXPERIENCE_PENDING)
            self.search.side_effect=None;self.search.return_value=FOUND
            submit.call_args.args[0](*submit.call_args.args[1:])
        self.assertIn('UA-SYNTHETIC',self.raw('a')[0]);self.assertNotIn('a',server.CONTRACT_EXPERIENCE_PENDING)
    def test_callback_before_active_release_defers_exactly_once(self):
        self.seed();timers=self.manual_timers(immediate=True);self.search.side_effect=self.unavailable
        with patch.object(server.CONTRACT_EXPERIENCE_EXECUTOR,'submit') as submit:
            server.contract_experience_worker(['s']);submit.assert_called_once_with(server.contract_experience_worker,['s'])
            timers[0].callback();self.assertEqual(submit.call_count,1)
            self.assertEqual(server.CONTRACT_EXPERIENCE_RETRY_ATTEMPTS['s'],1)
            self.assertFalse(server.CONTRACT_EXPERIENCE_ACTIVE)
    def test_overlapping_scans_never_reset_budget_or_duplicate_timers(self):
        self.seed();timers=self.manual_timers();self.search.side_effect=self.unavailable
        with patch.object(server.CONTRACT_EXPERIENCE_EXECUTOR,'submit') as submit:
            server.contract_experience_worker(['s'])
            for attempt in [1,2]:
                for _ in range(4):
                    server._sandbox_experience_scope_worker(None)
                    self.assertEqual(server.enqueue_contract_experience_search(['s']),0)
                self.assertEqual(server.CONTRACT_EXPERIENCE_RETRY_ATTEMPTS['s'],attempt)
                self.assertEqual(len(timers),attempt)
                timer=timers[-1];timer.callback();timer.callback()
                self.assertEqual(submit.call_count,attempt)
                submit.call_args.args[0](*submit.call_args.args[1:])
            for _ in range(4):server._sandbox_experience_scope_worker(None)
        self.assertEqual(self.search.call_count,3);self.assertEqual(len(timers),2)
        self.assertEqual(server.CONTRACT_EXPERIENCE_RETRY_ATTEMPTS['s'],3)
        self.assertFalse(server.CONTRACT_EXPERIENCE_PENDING);self.assertFalse(server.CONTRACT_EXPERIENCE_RETRY_PENDING)
        self.assertFalse(server.CONTRACT_EXPERIENCE_RETRY_TIMERS);self.assertFalse(server.CONTRACT_EXPERIENCE_RETRY_READY)
    def test_concurrent_callback_scan_and_admission_have_one_owner(self):
        from concurrent.futures import ThreadPoolExecutor
        self.seed();timers=self.manual_timers();self.search.side_effect=self.unavailable
        with patch.object(server.CONTRACT_EXPERIENCE_EXECUTOR,'submit') as submit:
            server.contract_experience_worker(['s'])
            operations=[timers[0].callback]*10+[lambda:server.enqueue_contract_experience_search(['s'])]*5+[lambda:server._sandbox_experience_scope_worker(None)]*5
            with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(lambda fn:fn(),operations))
            submit.assert_called_once_with(server.contract_experience_worker,['s'])
            self.assertEqual(self.search.call_count,1);self.assertEqual(server.CONTRACT_EXPERIENCE_RETRY_ATTEMPTS['s'],1)
            self.search.side_effect=None;self.search.return_value=FOUND;submit.call_args.args[0](*submit.call_args.args[1:])
        self.assertFalse(server.CONTRACT_EXPERIENCE_PENDING);self.assertFalse(server.CONTRACT_EXPERIENCE_ACTIVE)
    def test_retry_submit_failure_retains_ready_owner_and_budget(self):
        self.seed();timers=self.manual_timers();self.search.side_effect=self.unavailable
        server.contract_experience_worker(['s'])
        with patch.object(server.CONTRACT_EXPERIENCE_EXECUTOR,'submit',side_effect=RuntimeError('synthetic submit failure')),patch.object(server.SERVER_LOG,'exception'):
            timers[0].callback()
        self.assertIn('s',server.CONTRACT_EXPERIENCE_RETRY_READY);self.assertIn('s',server.CONTRACT_EXPERIENCE_PENDING)
        self.assertEqual(server.CONTRACT_EXPERIENCE_RETRY_ATTEMPTS['s'],1)
        with patch.object(server.CONTRACT_EXPERIENCE_EXECUTOR,'submit') as submit:
            server._sandbox_experience_drain();submit.assert_called_once_with(server.contract_experience_worker,['s'])
            self.search.side_effect=None;self.search.return_value=FOUND;submit.call_args.args[0](*submit.call_args.args[1:])
        self.assertIn('UA-SYNTHETIC',self.raw()[0])
    def test_timer_start_failure_falls_back_without_losing_or_duplicating_retry(self):
        self.seed();self.manual_timers(fail_start=True);self.search.side_effect=self.unavailable
        with patch.object(server.CONTRACT_EXPERIENCE_EXECUTOR,'submit') as submit,patch.object(server.SERVER_LOG,'exception'):
            server.contract_experience_worker(['s']);submit.assert_called_once_with(server.contract_experience_worker,['s'])
            self.assertEqual(server.CONTRACT_EXPERIENCE_RETRY_ATTEMPTS['s'],1)
            self.search.side_effect=None;self.search.return_value=FOUND;submit.call_args.args[0](*submit.call_args.args[1:])
        self.assertFalse(server.CONTRACT_EXPERIENCE_PENDING)
    def test_timer_constructor_failure_has_no_orphan_waiter(self):
        self.seed();self.search.side_effect=self.unavailable
        with patch.object(server.threading,'Timer',side_effect=RuntimeError('synthetic constructor failure')),patch.object(server.CONTRACT_EXPERIENCE_EXECUTOR,'submit') as submit,patch.object(server.SERVER_LOG,'warning'):
            server.contract_experience_worker(['s']);submit.assert_called_once_with(server.contract_experience_worker,['s'])
            self.assertEqual(server.CONTRACT_EXPERIENCE_RETRY_ATTEMPTS['s'],1)
            self.assertFalse(server.CONTRACT_EXPERIENCE_RETRY_TIMERS);self.assertFalse(server.CONTRACT_EXPERIENCE_RETRY_READY)
            self.search.side_effect=None;self.search.return_value=FOUND;submit.call_args.args[0](*submit.call_args.args[1:])
        self.assertFalse(server.CONTRACT_EXPERIENCE_PENDING)

    def test_cancelled_callback_cannot_take_new_timer_and_has_no_timer_cycle(self):
        self.seed();timers=self.manual_timers();self.search.side_effect=self.unavailable;server.contract_experience_worker(['s'])
        self.assertNotIn('timer',timers[0].callback.__code__.co_freevars)
        server._sandbox_experience_finish_id('s',False)
        self.assertTrue(timers[0].cancelled)
        server.contract_experience_worker(['s']);self.assertEqual(len(timers),2)
        with patch.object(server.CONTRACT_EXPERIENCE_EXECUTOR,'submit') as submit:
            timers[0].callback();submit.assert_not_called()
        self.assertEqual(server.CONTRACT_EXPERIENCE_RETRY_ATTEMPTS['s'],1)
        self.assertIs(server.CONTRACT_EXPERIENCE_RETRY_TIMERS['s'][1],timers[1])

    def test_marker_cancels_waiting_retry_without_dispatch(self):
        self.seed();timers=self.manual_timers();self.search.side_effect=self.unavailable;server.contract_experience_worker(['s'])
        (Path(self.folder.name)/'.pqm-background-jobs-disabled').touch()
        with patch.object(server.CONTRACT_EXPERIENCE_EXECUTOR,'submit') as submit:
            timers[0].callback();submit.assert_not_called()
        self.assertFalse(server.CONTRACT_EXPERIENCE_PENDING);self.assertFalse(server.CONTRACT_EXPERIENCE_RETRY_PENDING)
        self.assertFalse(server.CONTRACT_EXPERIENCE_RETRY_READY);self.assertFalse(server.CONTRACT_EXPERIENCE_RETRY_TIMERS)
    def test_waiting_capacity_parks_scope_until_retry_completes(self):
        self.seed();timers=self.manual_timers()
        with server.CONTRACT_EXPERIENCE_PENDING_LOCK:server._sandbox_experience_admit_locked(['other-'+str(n) for n in range(128)])
        for sid in list(server.CONTRACT_EXPERIENCE_PENDING):self.assertTrue(server._schedule_contract_experience_retry(sid))
        with patch.object(server.CONTRACT_EXPERIENCE_EXECUTOR,'submit') as submit:
            server.CONTRACT_EXPERIENCE_SCOPE_PENDING.add('__missing_pending__');server._sandbox_experience_scope_worker(None)
            submit.assert_not_called();self.assertEqual(len(server.CONTRACT_EXPERIENCE_DEFERRED_SCOPES),1)
            timers[0].callback();self.assertEqual(submit.call_count,1)
            fn,*args=submit.call_args.args;fn(*args) # Unknown synthetic ID releases a slot.
            self.assertEqual(submit.call_count,2)
            fn,*args=submit.call_args.args;self.assertIs(fn,server._sandbox_experience_scope_worker);fn(*args)
        self.assertIn('UA-SYNTHETIC',self.raw()[0]);self.assertLessEqual(len(server.CONTRACT_EXPERIENCE_PENDING),128)
    def test_terminal_metadata_is_bounded_and_live_budgets_are_never_evicted(self):
        for n in range(300):
            sid='terminal-'+str(n)
            with server.CONTRACT_EXPERIENCE_PENDING_LOCK:
                self.assertEqual(server._sandbox_experience_admit_locked([sid]),[sid])
                server.CONTRACT_EXPERIENCE_RETRY_ATTEMPTS[sid]=3
            server._sandbox_experience_finish_id(sid)
            self.assertLessEqual(len(server.CONTRACT_EXPERIENCE_RETRY_ATTEMPTS),128)
        self.assertFalse(server.CONTRACT_EXPERIENCE_PENDING)
        server.CONTRACT_EXPERIENCE_RETRY_ATTEMPTS.clear()
        with server.CONTRACT_EXPERIENCE_PENDING_LOCK:
            admitted=server._sandbox_experience_admit_locked(['live-'+str(n) for n in range(128)])
            self.assertEqual(len(admitted),128);before=dict(server.CONTRACT_EXPERIENCE_RETRY_ATTEMPTS)
            self.assertEqual(server._sandbox_experience_admit_locked(['overflow']),[])
            self.assertEqual(server.CONTRACT_EXPERIENCE_RETRY_ATTEMPTS,before)

    def test_concurrent_writers_only_fill_missing_experience_once(self):
        from concurrent.futures import ThreadPoolExecutor
        self.seed();gate=threading.Barrier(2)
        def write(number):
            gate.wait(timeout=5)
            current={'checks':[{'key':'contract_experience','status':'neutral','detail':str(number),'search_status':'none'}],'selected_categories':['experience']}
            return server._store_document_check_result('s',current,'fixture',require_pending=True)
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(write,[1,2]))
        self.assertEqual(sum(result is not None for result in results),1)
        stored=json.loads(self.raw()[0]);self.assertEqual(len(stored['category_results']['experience']['checks']),1)

    def test_emergency_stop_during_search_prevents_late_write(self):
        self.seed();before=self.raw()
        def stop(*args):
            (Path(self.folder.name)/'.pqm-background-jobs-disabled').touch()
            return FOUND
        self.search.side_effect=stop;server.contract_experience_worker(['s'])
        self.assertEqual(self.raw(),before)
    def test_corrupt_saved_shape_is_not_overwritten(self):
        self.seed()
        for value in ['not-json',json.dumps(['unknown']),json.dumps({'category_results':['unknown']})]:
            with server.db() as con:con.execute("UPDATE application_fields SET document_check_result_json=? WHERE submission_id='s'",(value,))
            before=self.raw();server.contract_experience_worker(['s']);self.assertEqual(self.raw(),before)
        self.search.assert_not_called()

    def test_manual_checks_timestamp_and_categories_unchanged_when_experience_added(self):
        self.seed();signature={'checks':[{'key':'signer','status':'ok'}],'selected_categories':['signature']}
        server._store_document_check_result('s',signature,'fixture')
        before=self.raw();data=json.loads(before[0]);server.contract_experience_worker(['s']);after=self.raw();updated=json.loads(after[0])
        self.assertEqual(before[1],after[1]);self.assertEqual(data['category_results']['signature'],updated['category_results']['signature'])
        self.assertEqual(updated['signature'] if 'signature' in updated else None,data.get('signature'))
        self.assertIn('experience',updated['category_results'])

if __name__=='__main__':unittest.main()
