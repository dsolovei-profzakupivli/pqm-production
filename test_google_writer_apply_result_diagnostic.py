import base64
import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import google_writer_execution as execution


def digest(value):
    return base64.urlsafe_b64encode(hashlib.sha256(value).digest()).decode().rstrip('=')


class AppendContinuationStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix='apply-status-test-')
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'status.sqlite3'
        with closing(sqlite3.connect(self.path)) as con:
            execution.migrate(con);con.commit()
        self.request_id='a'*32
        append_digest=digest(b'append digest')
        source_digest=digest(b'source digest')
        appends=[{'operation':'APPEND','tab':'ФОП','row':100+i,'code':f'{i:010d}',
            'cells':[{'column':'A','formula':True,'new_value':f'=D{100+i}'}]} for i in range(251)]
        self.details={'version':1,'environment':'SANDBOX','plan_digest':digest(b'full plan'),
            'append_only_digest':append_digest,'source_digest':source_digest,
            'counts':{'append':251,'update':0,'conflict':0,'error':0},'appends':appends,
            'updates':[],'conflicts':[],'errors':[],
            'append_continuation':{'version':1,'source_request_id':execution.APPEND_CONTINUATION_SOURCE_REQUEST_ID}}
        self.snapshot=execution.store_preview_plan(self.path,self.request_id,'actor',self.details)

    def test_preview_saved_without_run_reports_zero_confirmed_without_writes(self):
        before=hashlib.sha256(self.path.read_bytes()).hexdigest()
        result=execution.append_continuation_status(self.path,self.request_id,'actor')
        after=hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.assertEqual(result['status'],'preview_saved')
        self.assertEqual(result['confirmed_append'],0)
        self.assertIsNone(result['attempted_chunk'])
        self.assertFalse(result['checkpoint']['present'])
        self.assertEqual(result['receipts']['verified_count'],0)
        self.assertTrue(result['read_only'])
        self.assertEqual(before,after)

    def test_only_receipt_bound_to_manifest_and_run_checkpoint_counts_as_confirmed(self):
        now='2026-11-15T00:00:00+00:00'
        run_result={'plan_scope':'APPEND_ONLY','plan_digest':self.details['append_only_digest'],
            'details_digest':self.snapshot['details_digest'],'planned_counts':{'append':251,'update':0},
            'attempted_chunk':None,'verified_totals':{'append':0,'update':0,'batches':0}}
        with closing(sqlite3.connect(self.path)) as con,con:
            con.execute('''INSERT INTO google_writer_runs(request_id,environment,trigger,actor,revision,
                started_at,status,result_json) VALUES(?,?,?,?,?,?,?,?)''',
                (self.request_id,'SANDBOX','manual','actor',0,now,'running',json.dumps(run_result)))
        chunk=execution.prepare_append_chunk(self.path,self.request_id,'actor',
            self.details['append_only_digest'],self.snapshot['details_digest'],0)
        self.assertTrue(execution.mark_append_chunk_inflight(self.path,chunk['chunk_id']))
        receipt={'status':'APPLY_CHUNK_VERIFIED','digest':self.details['append_only_digest'],
            'chunkIndex':0,'nextChunk':1,'more':True,'phase':'append','planScope':'APPEND_ONLY',
            'checkpointDigest':digest(b'checkpoint'), 'chunkId':chunk['chunk_id'],
            'chunkDigest':chunk['chunk_digest'],'planId':self.request_id,
            'counts':{'append':25,'update':0,'batches':1}}
        execution.checkpoint_run(self.path,self.request_id,receipt)
        result=execution.append_continuation_status(self.path,self.request_id,'actor')
        self.assertEqual(result['confirmed_append'],25)
        self.assertEqual(result['receipts']['verified_count'],1)
        self.assertEqual(result['checkpoint'],{'present':True,'next_chunk':1})
        self.assertIsNone(result['attempted_chunk'])

    def test_mismatched_receipt_fails_closed_without_counting_it(self):
        now='2026-11-15T00:00:00+00:00'
        run_result={'plan_scope':'APPEND_ONLY','plan_digest':self.details['append_only_digest'],
            'details_digest':self.snapshot['details_digest'],'planned_counts':{'append':251,'update':0},
            'attempted_chunk':None,'verified_totals':{'append':0,'update':0,'batches':0}}
        with closing(sqlite3.connect(self.path)) as con,con:
            con.execute('''INSERT INTO google_writer_runs(request_id,environment,trigger,actor,revision,
                started_at,status,result_json) VALUES(?,?,?,?,?,?,?,?)''',
                (self.request_id,'SANDBOX','manual','actor',0,now,'running',json.dumps(run_result)))
        chunk=execution.prepare_append_chunk(self.path,self.request_id,'actor',
            self.details['append_only_digest'],self.snapshot['details_digest'],0)
        with closing(sqlite3.connect(self.path)) as con,con:
            con.execute("UPDATE google_writer_chunk_journal SET status='verified',receipt_json=? WHERE chunk_id=?",
                (json.dumps({'ticket':'NEVER_RETURNED'}),chunk['chunk_id']))
        result=execution.append_continuation_status(self.path,self.request_id,'actor')
        self.assertEqual(result['status'],'BLOCKED')
        self.assertEqual(result['reason_codes'],['RECEIPT_BINDING_MISMATCH'])
        self.assertNotIn('NEVER_RETURNED',json.dumps(result))

    def test_wrong_actor_or_bad_plan_identity_is_unavailable(self):
        result=execution.append_continuation_status(self.path,self.request_id,'other-actor')
        self.assertEqual(result['status'],'UNAVAILABLE')
        self.assertEqual(result['reason_codes'],['CONTINUATION_PLAN_UNAVAILABLE'])


if __name__=='__main__':
    unittest.main()
