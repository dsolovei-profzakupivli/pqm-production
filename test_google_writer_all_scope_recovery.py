import base64
import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import google_writer_execution as execution


class AllScopeApplyJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix='all-apply-journal-')
        self.addCleanup(self.temp.cleanup)
        self.path=str(Path(self.temp.name)/'sandbox.sqlite3')
        with closing(sqlite3.connect(self.path)) as con, con:
            execution.migrate(con)
        self.request_id='a'*32
        self.plan_digest=self.digest('plan')
        self.source_digest=self.digest('source')
        self.append_only_digest=self.digest('append-only')
        self.details={
            'version':1,'environment':'SANDBOX','plan_digest':self.plan_digest,
            'append_only_digest':self.append_only_digest,'source_digest':self.source_digest,
            'counts':{'append':30,'update':2,'conflict':1,'error':0},
            'appends':[{'operation':'APPEND','tab':'ФОП','row':445+i,'code':f'{i+1:010d}',
                'cells':[{'column':'A','new_value':f'=F{445+i}','formula':True},
                         {'column':'B','new_value':f'{i+1:010d}','formula':False}]}
                for i in range(30)],
            'updates':[{'operation':'UPDATE','tab':'ЮО','row':700+i,'code':f'{9000+i:010d}',
                'cells':[{'column':'E','new_value':'Активний','formula':False}]}
                for i in range(2)],
            'conflicts':[{'reason':'routing_mismatch'}],'errors':[]}
        self.snapshot=execution.store_preview_plan(self.path,self.request_id,'operator',self.details)
        claim=execution.claim_run(self.path,'SANDBOX',self.request_id,'operator','manual',
            manual_authorized=True,plan_scope='ALL',plan_digest=self.plan_digest,
            details_digest=self.snapshot['details_digest'])
        self.assertTrue(claim['claimed'])

    @staticmethod
    def digest(text):
        return base64.urlsafe_b64encode(hashlib.sha256(text.encode()).digest()).decode().rstrip('=')

    def prepare(self,index):
        return execution.prepare_apply_chunk(self.path,self.request_id,'operator',self.plan_digest,
            self.snapshot['details_digest'],'ALL',index,now=datetime(2026,11,9,10,0,tzinfo=timezone.utc))

    def test_write_ahead_journal_covers_append_and_update_pages_with_immutable_digest(self):
        first=self.prepare(0)
        update=self.prepare(2)
        self.assertEqual(first['phase'],'append')
        self.assertEqual(update['phase'],'update')
        with closing(sqlite3.connect(self.path)) as con:
            rows=con.execute('''SELECT phase,scope,status,expected_json,chunk_digest FROM google_writer_apply_chunk_journal
                WHERE run_id=? ORDER BY chunk_index''',(self.request_id,)).fetchall()
        self.assertEqual([(row[0],row[1],row[2]) for row in rows],
            [('append','ALL','prepared'),('update','ALL','prepared')])
        self.assertEqual(json.loads(rows[0][3])['phase'],'append')
        self.assertEqual(json.loads(rows[0][3])['added_at'],'2026-11-09T12:00:00+02:00')
        self.assertEqual(json.loads(rows[1][3])['phase'],'update')
        self.assertNotIn('added_at',json.loads(rows[1][3]))
        self.assertEqual(first['chunk_digest'],rows[0][4])
        self.assertEqual(update['chunk_digest'],rows[1][4])
        self.assertEqual(first['chunk_id'],self.prepare(0)['chunk_id'])
        self.assertEqual(len(json.loads(rows[0][3])['operations']),25)
        with self.assertRaisesRegex(ValueError,'identity rejected'):
            execution.prepare_apply_chunk(self.path,self.request_id,'operator',self.append_only_digest,
                self.snapshot['details_digest'],'APPEND_ONLY',0)

    def test_unknown_or_verified_chunk_cannot_be_reissued(self):
        chunk=self.prepare(0)
        execution.mark_apply_chunk_inflight(self.path,chunk['chunk_id'])
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("UPDATE google_writer_apply_chunk_journal SET status='outcome_unknown' WHERE chunk_id=?",
                (chunk['chunk_id'],))
        with self.assertRaisesRegex(RuntimeError,'unresolved'):
            self.prepare(0)

    def test_checkpoint_receipt_must_match_phase_scope_chunk_and_counts(self):
        chunk=self.prepare(2)
        execution.mark_apply_chunk_inflight(self.path,chunk['chunk_id'])
        receipt={'status':'APPLY_CHUNK_VERIFIED','digest':self.plan_digest,'planScope':'ALL',
            'chunkIndex':2,'nextChunk':3,'more':False,'phase':'update',
            'checkpointDigest':self.digest('checkpoint'),'chunkId':chunk['chunk_id'],
            'chunkDigest':chunk['chunk_digest'],'planId':chunk['plan_id'],
            'counts':{'append':0,'update':2,'batches':1,'conflict':1,'error':0,'remaining_safe':0}}
        execution.checkpoint_run(self.path,self.request_id,receipt)
        with closing(sqlite3.connect(self.path)) as con:
            row=con.execute('SELECT status,receipt_json FROM google_writer_apply_chunk_journal WHERE chunk_id=?',
                (chunk['chunk_id'],)).fetchone()
            run=json.loads(con.execute('SELECT result_json FROM google_writer_runs WHERE request_id=?',
                (self.request_id,)).fetchone()[0])
        self.assertEqual(row[0],'verified')
        self.assertEqual(json.loads(row[1])['phase'],'update')
        self.assertEqual(run['verified_totals']['update'],2)
        self.assertEqual(run['attempted_chunk'],None)

    def test_mutated_saved_plan_is_rejected_before_chunk_is_created(self):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("UPDATE google_writer_plan_journal SET details_json='{}' WHERE request_id=?",
                (self.request_id,))
        with self.assertRaisesRegex(ValueError,'unavailable or changed|digest binding failed'):
            self.prepare(0)
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM google_writer_apply_chunk_journal').fetchone()[0],0)

    def test_worker_recovers_exact_uncertain_chunk_then_continues_with_remaining_append_and_update(self):
        first=self.prepare(0)
        execution.mark_apply_chunk_inflight(self.path,first['chunk_id'])
        execution.hold_unknown_run(self.path,self.request_id,attempted_chunk=0,
            digest=self.plan_digest,chunk_id=first['chunk_id'],phase='append',
            safe_error={'stage':'append_read_back','category':'transport','exception_type':'TimeoutError'})
        with closing(sqlite3.connect(self.path)) as con, con:
            row=con.execute('SELECT result_json FROM google_writer_runs WHERE request_id=?',(self.request_id,)).fetchone()
            state=json.loads(row[0]);state['auto_continue_chunks']=True
            con.execute('UPDATE google_writer_runs SET result_json=? WHERE request_id=?',
                (json.dumps(state,sort_keys=True),self.request_id))

        class RecoveryClient:
            environment='SANDBOX'
            def __init__(self): self.actions=[]
            def invoke(inner,action,request_id,actor,**kw):
                inner.actions.append((action,kw.get('chunk_index'),kw.get('chunk_phase')))
                if action=='recover_apply_chunk':
                    return {'status':'CHUNK_RECOVERED','digest':kw['digest'],'planScope':'ALL',
                        'chunkIndex':kw['chunk_index'],'nextChunk':kw['chunk_index']+1,'more':True,
                        'phase':kw['chunk_phase'],'checkpointDigest':self.digest('recovered-checkpoint'),
                        'chunkId':kw['chunk_id'],'chunkDigest':kw['chunk_digest'],'planId':kw['plan_id'],
                        'counts':{'append':25,'update':0,'batches':1,'conflict':1,'error':0}}
                phase=kw['chunk_phase']; index=kw['chunk_index']
                count=5 if phase=='append' else 2
                more=phase=='append'
                return {'status':'APPLY_CHUNK_VERIFIED' if more else 'COMPLETE_WITH_CONFLICTS',
                    'digest':kw['digest'],'planScope':'ALL','chunkIndex':index,'nextChunk':index+1,
                    'more':more,'phase':phase,'checkpointDigest':self.digest(f'checkpoint-{index}'),
                    'chunkId':kw['chunk_id'],'chunkDigest':kw['chunk_digest'],'planId':kw['plan_id'],
                    'counts':{'append':count if phase=='append' else 0,
                        'update':count if phase=='update' else 0,'batches':1,'conflict':1,'error':0}}

        client=RecoveryClient()
        result=execution.recover_interrupted_apply_chunk(self.path,client,self.request_id,'operator')
        self.assertEqual(result['status'],'COMPLETE_WITH_CONFLICTS')
        self.assertEqual(client.actions,[('recover_apply_chunk',0,'append'),
            ('apply',1,'append'),('apply',2,'update')])
        with closing(sqlite3.connect(self.path)) as con:
            journal=con.execute('''SELECT chunk_index,phase,status FROM google_writer_apply_chunk_journal
                WHERE run_id=? ORDER BY chunk_index''',(self.request_id,)).fetchall()
            run=con.execute('SELECT status,result_json FROM google_writer_runs WHERE request_id=?',
                (self.request_id,)).fetchone()
        self.assertEqual(journal,[(0,'append','verified'),(1,'append','verified'),(2,'update','verified')])
        self.assertEqual(run[0],'partial')
        final_state=json.loads(run[1])
        self.assertEqual(final_state['counts'],{'append':30,'update':2,'batches':3,
            'conflict':1,'error':0})
        self.assertEqual(final_state['last_recovered_error'],{
            'stage':'append_read_back','category':'transport','exception_type':'TimeoutError'})

    def test_read_only_no_write_proof_keeps_all_scope_run_held(self):
        chunk=self.prepare(0)
        execution.mark_apply_chunk_inflight(self.path,chunk['chunk_id'])
        execution.hold_unknown_run(self.path,self.request_id,attempted_chunk=0,
            digest=self.plan_digest,chunk_id=chunk['chunk_id'],phase='append')

        class NoWriteClient:
            def invoke(inner,action,request_id,actor,**kw):
                return {'status':'CHUNK_NOT_APPLIED','digest':kw['digest'],'planScope':'ALL',
                    'chunkIndex':kw['chunk_index'],'nextChunk':kw['chunk_index'],'phase':kw['chunk_phase'],
                    'chunkId':kw['chunk_id'],'chunkDigest':kw['chunk_digest'],'planId':kw['plan_id'],
                    'counts':{'append':0,'update':0,'batches':0}}
        result=execution.recover_interrupted_apply_chunk(self.path,NoWriteClient(),self.request_id,'operator')
        self.assertEqual(result['status'],'OUTCOME_UNKNOWN_HOLD_NO_RETRY')
        with closing(sqlite3.connect(self.path)) as con:
            status=con.execute('SELECT status FROM google_writer_runs WHERE request_id=?',(self.request_id,)).fetchone()[0]
            chunk_status=con.execute('SELECT status FROM google_writer_apply_chunk_journal WHERE chunk_id=?',
                (chunk['chunk_id'],)).fetchone()[0]
        self.assertEqual(status,'outcome_unknown')
        self.assertEqual(chunk_status,'outcome_unknown')

    def test_continuation_worker_discovers_all_scope_unknown_chunk(self):
        chunk=self.prepare(0)
        execution.mark_apply_chunk_inflight(self.path,chunk['chunk_id'])
        execution.hold_unknown_run(self.path,self.request_id,attempted_chunk=0,
            digest=self.plan_digest,chunk_id=chunk['chunk_id'],phase='append')
        worker=execution.AppendOnlyContinuationWorker(self.path,lambda:None,lambda:True)
        self.assertEqual(worker.recoverable(),[(self.request_id,'operator','ALL')])

    def test_all_scope_worker_bounds_each_http_apply_to_four_confirmed_chunks(self):
        request_id='b'*32
        long_path=str(Path(self.temp.name)/'bounded-worker.sqlite3')
        with closing(sqlite3.connect(long_path)) as con, con:
            execution.migrate(con)
        details=json.loads(json.dumps(self.details))
        details['appends']=[{'operation':'APPEND','tab':'ФОП','row':800+i,'code':f'{i+1:010d}',
            'cells':[{'column':'A','new_value':f'=F{800+i}','formula':True},
                     {'column':'B','new_value':f'{i+1:010d}','formula':False}]} for i in range(101)]
        details['counts']['append']=101
        plan=execution.store_preview_plan(long_path,request_id,'operator',details)
        self.assertTrue(execution.claim_run(long_path,'SANDBOX',request_id,'operator','manual',
            manual_authorized=True,plan_scope='ALL',plan_digest=self.plan_digest,
            details_digest=plan['details_digest'])['claimed'])

        class ApplyClient:
            environment='SANDBOX'
            def __init__(inner): inner.calls=[]
            def invoke(inner,action,rid,actor,**kw):
                self.assertEqual(action,'apply')
                index=kw['chunk_index'];phase=kw['chunk_phase'];inner.calls.append((index,phase))
                count=(25 if index<4 else 1) if phase=='append' else 2
                more=(index<4 or phase=='append')
                return {'status':'APPLY_CHUNK_VERIFIED' if more else 'COMPLETE_WITH_CONFLICTS',
                    'digest':kw['digest'],'planScope':'ALL','chunkIndex':index,'nextChunk':index+1,
                    'more':more,'phase':phase,'checkpointDigest':self.digest(f'c-{request_id}-{index}'),
                    'chunkId':kw['chunk_id'],'chunkDigest':kw['chunk_digest'],'planId':kw['plan_id'],
                    'counts':{'append':count if phase=='append' else 0,
                        'update':count if phase=='update' else 0,'batches':1,'conflict':1,'error':0}}

        client=ApplyClient()
        first=execution.execute_claimed(long_path,client,request_id,'operator',digest=self.plan_digest,
            manual_authorized=True,plan_scope='ALL')
        self.assertEqual(first['status'],'HALTED_AFTER_VERIFIED_CHECKPOINTS')
        self.assertEqual(client.calls,[(0,'append'),(1,'append'),(2,'append'),(3,'append')])
        state=execution.status(long_path,'SANDBOX',available=True,running=True,actor='operator')
        self.assertTrue(state['blocked'])
        second=execution.claim_run(long_path,'SANDBOX','c'*32,'operator','manual',
            manual_authorized=True,plan_scope='ALL',plan_digest=self.plan_digest)
        self.assertEqual(second['status'],'verified_checkpoint_continuation_required')
        worker=execution.AppendOnlyContinuationWorker(long_path,lambda:client,lambda:True)
        eligible=worker.eligible()
        self.assertEqual(eligible,[(request_id,'operator',self.plan_digest,'ALL')])
        claimed=execution.claim_apply_continuation(long_path,request_id,'operator')
        self.assertTrue(claimed)
        stale=(datetime.now(timezone.utc)-execution.timedelta(seconds=execution.APPEND_RECOVERY_LEASE_SECONDS+1)).isoformat()
        with closing(sqlite3.connect(long_path)) as con, con:
            row=con.execute('SELECT result_json FROM google_writer_runs WHERE request_id=?',(request_id,)).fetchone()
            state=json.loads(row[0]);state['recovery_claimed_at']=stale
            con.execute('UPDATE google_writer_runs SET result_json=? WHERE request_id=?',
                (json.dumps(state,sort_keys=True),request_id))
        self.assertEqual(execution.reclaim_stale_apply_continuation(long_path),[request_id])
        final=execution.continue_apply_checkpoint(long_path,client,request_id,'operator')
        self.assertEqual(final['status'],'COMPLETE_WITH_CONFLICTS')
        self.assertEqual(client.calls[-2:],[(4,'append'),(5,'update')])
        with closing(sqlite3.connect(long_path)) as con:
            states=con.execute('''SELECT status,COUNT(*) FROM google_writer_apply_chunk_journal
                WHERE run_id=? GROUP BY status''',(request_id,)).fetchall()
        self.assertEqual(states,[('verified',6)])


if __name__=='__main__':
    unittest.main()
