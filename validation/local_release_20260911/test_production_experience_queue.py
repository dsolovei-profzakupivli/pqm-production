"""Bounded Production queue: native concurrency and deterministic retry races."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
import threading
import time
import unittest
from unittest.mock import patch

import runtime_experience
import server
from validation.local_release_20260911 import test_production_memory_saved as saved_fixture


class ManualExecutor:
    def __init__(self): self.tasks=[];self.peak=0
    def submit(self, fn):
        self.tasks.append(fn);self.peak=max(self.peak,len(self.tasks))
    def drain(self):
        while self.tasks:self.tasks.pop(0)()


class Timer:
    instances=[]
    def __init__(self, delay, callback):
        self.delay,self.callback=delay,callback;self.cancelled=False
        self.instances.append(self)
    def start(self):pass
    def cancel(self):self.cancelled=True
    def fire(self):self.callback()


class ExperienceQueueTests(unittest.TestCase):
    def setUp(self):Timer.instances=[]

    def queue(self, handler, **kwargs):
        executor=ManualExecutor()
        queue=runtime_experience.ExperienceQueue(executor,handler,timer_factory=Timer,**kwargs)
        self.addCleanup(queue.close)
        return queue,executor

    def test_early_retry_callback_cannot_lose_or_duplicate_work(self):
        calls=[]
        def handler(sid):
            calls.append(sid)
            if len(calls)==1:
                self.assertTrue(queue.retry(sid))
                Timer.instances[-1].fire();Timer.instances[-1].fire()
                self.assertEqual(queue.enqueue([sid]),0)
        queue,executor=self.queue(handler)
        queue.enqueue(['s']);executor.drain()
        self.assertEqual(calls,['s','s'])
        self.assertEqual(queue.snapshot()['owned'],0)
        self.assertEqual(len(Timer.instances),1)

    def test_overlap_admission_preserves_retry_budget_and_timer(self):
        calls=[]
        def handler(sid):
            calls.append(sid)
            expected=len(calls)<3
            self.assertEqual(queue.retry(sid),expected)
            if expected:self.assertTrue(queue.retry(sid))
        queue,executor=self.queue(handler)
        queue.enqueue(['s']);executor.drain()
        for n in range(2):
            for _ in range(20):self.assertEqual(queue.enqueue(['s']),0)
            timer=Timer.instances[-1];timer.fire();timer.fire();executor.drain()
        self.assertEqual(calls,['s']*3)
        self.assertEqual(len(Timer.instances),2)
        self.assertEqual([t.delay for t in Timer.instances],[60,60])
        self.assertEqual(queue.snapshot()['owned'],0)

    def test_waiting_retries_keep_ownership_and_block_new_ids_until_release(self):
        calls=[]
        def handler(sid):
            calls.append(sid)
            if calls.count(sid)==1:queue.retry(sid)
        queue,executor=self.queue(handler,limit=2)
        queue.enqueue(['a','b']);executor.drain()
        self.assertEqual(queue.snapshot()['owned'],2)
        self.assertEqual(queue.snapshot()['timers'],2)
        completed=threading.Event()
        producer=threading.Thread(target=lambda:(queue.enqueue(['c']),completed.set()))
        producer.start()
        try:
            self.assertFalse(completed.wait(.05))
            for timer in list(Timer.instances):timer.fire()
            executor.drain()
            self.assertTrue(completed.wait(2))
            executor.drain()
            # c can itself wait for one legitimate retry, never exceed the cap.
            for timer in list(Timer.instances):timer.fire()
            executor.drain()
        finally:
            queue.close();producer.join(2)
        self.assertFalse(producer.is_alive())
        self.assertLessEqual(queue.snapshot()['peak_owned'],2)
        self.assertEqual(Counter(calls),{'a':2,'b':2,'c':2})

    def test_concurrent_producers_are_bounded_and_all_ids_finish(self):
        counts=Counter();active=0;peak=0;lock=threading.Lock()
        def handler(sid):
            nonlocal active,peak
            with lock:active+=1;peak=max(peak,active);counts[sid]+=1
            time.sleep(.001)
            with lock:active-=1
        with ThreadPoolExecutor(max_workers=2) as executor:
            queue=runtime_experience.ExperienceQueue(executor,handler,limit=128,batch=32)
            producers=[threading.Thread(target=queue.enqueue,args=([f'{n}:{i}' for i in range(200)],)) for n in range(4)]
            for thread in producers:thread.start()
            for thread in producers:thread.join(10);self.assertFalse(thread.is_alive())
            deadline=time.monotonic()+10
            while queue.snapshot()['owned'] and time.monotonic()<deadline:time.sleep(.005)
            state=queue.snapshot();queue.close()
        self.assertEqual(len(counts),800)
        self.assertTrue(all(n==1 for n in counts.values()))
        self.assertEqual(state['owned'],0)
        self.assertLessEqual(state['peak_owned'],128)
        self.assertLessEqual(state['peak_pumps'],2)
        self.assertEqual(peak,2)

    def test_same_id_cannot_run_concurrently(self):
        entered=threading.Event();release=threading.Event();calls=[]
        def handler(sid):calls.append(sid);entered.set();release.wait(3)
        with ThreadPoolExecutor(max_workers=2) as executor:
            queue=runtime_experience.ExperienceQueue(executor,handler)
            try:
                queue.enqueue(['s']);self.assertTrue(entered.wait(2))
                threads=[threading.Thread(target=queue.enqueue,args=(['s'],)) for _ in range(8)]
                for thread in threads:thread.start()
                for thread in threads:thread.join(2)
                self.assertEqual(calls,['s'])
            finally:release.set();queue.close()

    def test_small_producer_does_not_starve_behind_a_large_sync(self):
        gate=threading.Event();calls=[]
        def handler(sid):gate.wait(3);calls.append(sid);time.sleep(.001)
        with ThreadPoolExecutor(max_workers=2) as executor:
            queue=runtime_experience.ExperienceQueue(executor,handler,limit=4,batch=2)
            large=threading.Thread(target=queue.enqueue,args=([f'large-{i}' for i in range(100)],))
            small=threading.Thread(target=queue.enqueue,args=(['small'],))
            try:
                large.start()
                deadline=time.monotonic()+2
                while queue.snapshot()['producers']<1 and time.monotonic()<deadline:time.sleep(.001)
                small.start()
                deadline=time.monotonic()+2
                while queue.snapshot()['producers']<2 and time.monotonic()<deadline:time.sleep(.001)
                self.assertEqual(queue.snapshot()['producers'],2)
                gate.set();large.join(5);small.join(5)
                self.assertFalse(large.is_alive());self.assertFalse(small.is_alive())
                deadline=time.monotonic()+5
                while queue.snapshot()['owned'] and time.monotonic()<deadline:time.sleep(.001)
                self.assertLess(calls.index('small'),calls.index('large-99'))
                self.assertEqual(len(calls),101)
            finally:gate.set();queue.close();large.join(3);small.join(3)

    def test_timer_constructor_and_start_failures_retain_reserved_retry(self):
        for mode in ['constructor','start']:
            calls=[]
            def handler(sid):
                calls.append(sid)
                if len(calls)==1:queue.retry(sid)
            def factory(delay, callback):
                if mode=='constructor':raise RuntimeError('synthetic constructor')
                timer=Timer(delay,callback)
                timer.start=lambda: (_ for _ in ()).throw(RuntimeError('synthetic start'))
                return timer
            queue,executor=self.queue(handler)
            queue.timer_factory=factory
            with patch.object(runtime_experience.LOG,'exception'):
                queue.enqueue(['s']);executor.drain()
            self.assertEqual(calls,['s','s'])
            self.assertEqual(queue.snapshot()['owned'],0)

    def test_failed_submit_retains_ids_for_later_dispatch(self):
        queue,executor=self.queue(lambda sid:None)
        with patch.object(executor,'submit',side_effect=RuntimeError('synthetic')):
            with self.assertRaises(RuntimeError):queue.enqueue(['s'])
        self.assertTrue(queue.owns('s'))
        self.assertEqual(queue.snapshot()['pumps'],0)
        queue.enqueue([]);executor.drain()
        self.assertFalse(queue.owns('s'))

    def test_dispatch_failure_wakes_blocked_producer_instead_of_hanging(self):
        calls=[]
        def handler(sid):
            calls.append(sid)
            if len(calls)==1:queue.retry(sid)
        queue,executor=self.queue(handler,limit=1)
        queue.enqueue(['a']);executor.drain()
        errors=[]
        def blocked():
            try:queue.enqueue(['b'])
            except RuntimeError as exc:errors.append(str(exc))
        producer=threading.Thread(target=blocked);producer.start()
        deadline=time.monotonic()+2
        while queue.snapshot()['producers']<1 and time.monotonic()<deadline:time.sleep(.001)
        with patch.object(executor,'submit',side_effect=RuntimeError('synthetic')),patch.object(runtime_experience.LOG,'exception'):
            Timer.instances[0].fire()
        producer.join(2)
        try:
            self.assertFalse(producer.is_alive())
            self.assertEqual(errors,['Contract dispatch failed; admitted IDs retained'])
            self.assertTrue(queue.owns('a'));self.assertFalse(queue.owns('b'))
            queue.enqueue([]);executor.drain()
            self.assertEqual(calls,['a','a'])
        finally:queue.close();producer.join(2)

    def test_close_cancels_timers_and_stale_callbacks_are_inert(self):
        queue,executor=self.queue(lambda sid:queue.retry(sid))
        queue.enqueue(['s']);executor.drain();timer=Timer.instances[0]
        queue.close();timer.fire();executor.drain()
        self.assertTrue(timer.cancelled)
        self.assertEqual(queue.snapshot()['owned'],0)
        with self.assertRaises(RuntimeError):queue.enqueue(['new'])

    def test_handler_exception_releases_slot_without_changing_retry_policy(self):
        queue,executor=self.queue(lambda sid:(_ for _ in ()).throw(ValueError('synthetic')))
        with patch.object(runtime_experience.LOG,'exception'):
            queue.enqueue(['s']);executor.drain()
        self.assertEqual(queue.snapshot()['owned'],0)
        self.assertEqual(len(Timer.instances),0)


class ProductionExperienceIntegration(unittest.TestCase):
    setUp=saved_fixture.ProductionSavedResults.setUp
    seed=saved_fixture.ProductionSavedResults.seed

    def prepare(self, workers=2):
        self.enterContext(patch.object(server,'SANDBOX_MODE',False))
        self.enterContext(patch.object(server,'CONTRACT_EXPERIENCE_QUEUE',None))
        self.enterContext(patch.object(server,'CONTRACT_EXPERIENCE_PENDING',set()))
        executor=ThreadPoolExecutor(max_workers=workers)
        self.enterContext(patch.object(server,'CONTRACT_EXPERIENCE_EXECUTOR',executor))
        def stop():
            if server.CONTRACT_EXPERIENCE_QUEUE:server.CONTRACT_EXPERIENCE_QUEUE.close()
            executor.shutdown(wait=True)
        self.addCleanup(stop)

    def drain(self):
        deadline=time.monotonic()+10
        while server.CONTRACT_EXPERIENCE_QUEUE.snapshot()['owned']:
            self.assertLess(time.monotonic(),deadline)
            time.sleep(.01)

    def test_production_keeps_freshness_and_automatically_persists_search(self):
        self.prepare();self.seed()
        found={'status':'found','symbol':'+','message':'Synthetic','candidates':[]}
        with patch.object(server,'search_supplier_contract_experience',return_value=found) as search:
            server.enqueue_contract_experience_search(['s']);self.drain()
            server.enqueue_contract_experience_search(['s']);self.drain()
            self.assertEqual(search.call_count,1)
            with server.db() as con:
                stored=json.loads(con.execute("SELECT document_check_result_json FROM application_fields WHERE submission_id='s'").fetchone()[0])
                stored['category_results']['experience']['checked_at']='2020-01-01T00:00:00Z'
                con.execute("UPDATE application_fields SET document_check_result_json=? WHERE submission_id='s'",(json.dumps(stored),))
            server.enqueue_contract_experience_search(['s']);self.drain()
            self.assertEqual(search.call_count,2)
        self.assertEqual(server.CONTRACT_EXPERIENCE_PENDING,set())

    def test_production_does_not_inherit_sandbox_pending_only_policy(self):
        self.prepare();self.seed('active','active')
        found={'status':'none','symbol':'−','message':'Synthetic','candidates':[]}
        with patch.object(server,'search_supplier_contract_experience',return_value=found) as search:
            server.enqueue_contract_experience_search(['active']);self.drain()
            search.assert_called_once()

    def test_duplicate_ids_in_one_ingestion_are_deduplicated_before_dispatch(self):
        self.prepare()
        with patch.object(server,'contract_experience_worker') as worker:
            self.assertEqual(server.enqueue_contract_experience_search(['s']*100),1)
            self.drain()
            worker.assert_called_once_with(['s'])

    def test_real_worker_retries_unavailable_with_same_budget_and_persists_success(self):
        self.prepare();self.seed()
        self.enterContext(patch.object(server,'CONTRACT_EXPERIENCE_RETRY_DELAY',.01))
        unavailable={'status':'unavailable','symbol':'?','message':'Synthetic transient','candidates':[]}
        found={'status':'found','symbol':'+','message':'Synthetic restored','candidates':[]}
        with patch.object(server,'search_supplier_contract_experience',side_effect=[unavailable,unavailable,found]) as search:
            server.enqueue_contract_experience_search(['s']);self.drain()
            self.assertEqual(search.call_count,3)
        with server.db() as con:
            raw=json.loads(con.execute("SELECT document_check_result_json FROM application_fields WHERE submission_id='s'").fetchone()[0])
        self.assertEqual(raw['contract_experience']['status'],'found')
        self.assertEqual(server.CONTRACT_EXPERIENCE_QUEUE.snapshot()['timers'],0)

    def test_exhausted_budget_survives_new_admission_without_unbounded_ram_map(self):
        self.prepare();self.seed()
        self.enterContext(patch.object(server,'CONTRACT_EXPERIENCE_RETRY_DELAY',.01))
        unavailable={'status':'unavailable','symbol':'?','message':'Synthetic transient','candidates':[]}
        found={'status':'none','symbol':'−','message':'Synthetic success','candidates':[]}
        with patch.object(server,'search_supplier_contract_experience',return_value=unavailable) as search:
            server.enqueue_contract_experience_search(['s']);self.drain()
            self.assertEqual(search.call_count,3)
            server.enqueue_contract_experience_search(['s']);self.drain()
            self.assertEqual(search.call_count,4)  # Baseline: no fresh extra retry budget.
            self.assertEqual(server.CONTRACT_EXPERIENCE_RETRY_ATTEMPTS,{})
            self.assertEqual(server.CONTRACT_EXPERIENCE_QUEUE.snapshot()['owned'],0)
            search.return_value=found
            server.enqueue_contract_experience_search(['s']);self.drain()
            self.assertEqual(search.call_count,5)
            with server.db() as con:
                stored=json.loads(con.execute("SELECT document_check_result_json FROM application_fields WHERE submission_id='s'").fetchone()[0])
                check=stored['category_results']['experience']['checks'][0]
                self.assertEqual(check['background_retry']['attempts'],0)
                stored['category_results']['experience']['checked_at']='2020-01-01T00:00:00Z'
                con.execute("UPDATE application_fields SET document_check_result_json=? WHERE submission_id='s'",(json.dumps(stored),))
            search.return_value=unavailable
            server.enqueue_contract_experience_search(['s']);self.drain()
            self.assertEqual(search.call_count,8)  # Success reset preserved.

    def test_new_process_epoch_resets_budget_like_baseline(self):
        self.prepare();self.seed()
        self.enterContext(patch.object(server,'CONTRACT_EXPERIENCE_RETRY_DELAY',.01))
        unavailable={'status':'unavailable','symbol':'?','message':'Synthetic','candidates':[]}
        with patch.object(server,'search_supplier_contract_experience',return_value=unavailable) as search:
            server.enqueue_contract_experience_search(['s']);self.drain()
            old_epoch=server.CONTRACT_EXPERIENCE_QUEUE.epoch
            server.CONTRACT_EXPERIENCE_QUEUE.close();server.CONTRACT_EXPERIENCE_QUEUE=None
            server.enqueue_contract_experience_search(['s']);self.drain()
            self.assertNotEqual(server.CONTRACT_EXPERIENCE_QUEUE.epoch,old_epoch)
            self.assertEqual(search.call_count,6)

    def test_sandbox_exception_is_not_enabled_by_production_queue(self):
        with patch.object(server,'SANDBOX_MODE',True),patch.object(server,'CONTRACT_EXPERIENCE_QUEUE',None):
            self.assertEqual(server.enqueue_contract_experience_search(['s']),0)
            self.assertIsNone(server.CONTRACT_EXPERIENCE_QUEUE)
