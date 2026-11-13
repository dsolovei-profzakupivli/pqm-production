"""Mock-only safety tests for the fixed Sandbox APPEND continuation path."""
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import google_writer_execution as writer


def _d(text):
    return writer._sha256_b64(text.encode())


def _operation(index):
    code=f'{10000000+index:08d}'
    tab='ФОП' if index%2==0 else 'ЮО'
    row=100+index
    return {'operation':'APPEND','tab':tab,'row':row,'code':code,'name':f'Test {index}',
        'cells':[{'column':'A','old_value':'','new_value':f'=IF(B{row}="","",1)','formula':True},
                 {'column':'B','old_value':'','new_value':code,'formula':False},
                 {'column':'I','old_value':'','new_value':'12.11.2026 00:00:00','formula':False}]}


class ContinuationClient:
    environment='SANDBOX'
    shared_secret='test-signing-secret-that-is-not-used-for-network'

    def __init__(self, old_details, *, audit_statuses=None, audit_digest=None, preview_digest=None,
                 preview_operations=None, timeout_action=None):
        self.old_details=old_details
        self.audit_statuses=audit_statuses or ['CONFIRMED']*25+['MISSING']*251
        self.audit_digest=audit_digest or _d('sheet-state')
        self.preview_digest=preview_digest or self.audit_digest
        self.preview_operations=preview_operations or [item for i,item in enumerate(old_details['appends'])
            if i>=25]
        self.timeout_action=timeout_action
        self.calls=[]

    def clock(self):
        return datetime(2026,11,12,tzinfo=timezone.utc)

    def invoke(self, action, request_id, actor, **kwargs):
        self.calls.append((action,request_id,kwargs))
        if action=='diagnose_append_plan':
            if kwargs.get('diagnostic_mode')!='audit':
                raise AssertionError('Continuation must use audit only, never recovery')
            if self.timeout_action=='audit':raise writer.ExecutionOutcomeUnknown('mock audit timeout')
            counts={'planned':276,'confirmed':self.audit_statuses.count('CONFIRMED'),
                'missing':self.audit_statuses.count('MISSING'),'conflict':self.audit_statuses.count('CONFLICT'),
                'unverified':self.audit_statuses.count('UNVERIFIED')}
            counts['remaining']=counts['planned']-counts['confirmed']
            return {'status':'AUDITED' if not counts['unverified'] else 'READ_INCOMPLETE','counts':counts,
                'reason_codes':[],'conflicts':[],'target_statuses':self.audit_statuses,
                'continuation_guard_rows':[{'tab':item['tab'],'row':item['row'],
                    'identity_digest':_d(writer._canonical_json([item['tab'],item['row'],item['code']])),
                    'row_digest':_d('row-'+item['code']),
                    'service_digest':_d('service-'+item['code'])}
                    for item,status in zip(self.old_details['appends'],self.audit_statuses)
                    if status=='CONFIRMED'],
                'google_state_digest':self.audit_digest,'read_only':True,
                'sqlite_writes':0,'sheets_writes':0,'properties_writes':0}
        if action=='preview':
            if self.timeout_action=='preview':raise writer.ExecutionOutcomeUnknown('mock preview timeout')
            details={'version':1,'environment':'SANDBOX','plan_digest':_d('new-full-plan'),
                'source_digest':self.old_details['source_digest'],'append_only_digest':_d('new-append-plan'),
                'counts':{'append':len(self.preview_operations),'update':0,'conflict':0,'error':0},
                'appends':self.preview_operations,'updates':[],'conflicts':[],'errors':[]}
            return {'status':'PREVIEW','digest':details['plan_digest'],
                'google_state_digest':self.preview_digest,'planDetails':details}
        if action=='resume_check':
            return {'status':'NOT_READY'}
        raise AssertionError(f'unexpected action {action}')


class AppendContinuationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix='append-continuation-')
        self.addCleanup(self.tmp.cleanup)
        self.path=str(Path(self.tmp.name)/'sandbox.sqlite3')
        self.actor='sandbox-admin'
        self.source=writer.APPEND_CONTINUATION_SOURCE_REQUEST_ID
        self.ops=[_operation(i) for i in range(276)]
        self.source_digest=_d('source')
        self.old={'version':1,'environment':'SANDBOX','plan_digest':_d('old-full'),
            'source_digest':self.source_digest,'append_only_digest':_d('old-append'),
            'counts':{'append':276,'update':0,'conflict':0,'error':0},
            'appends':self.ops,'updates':[],'conflicts':[],'errors':[]}
        with closing(sqlite3.connect(self.path)) as con:
            writer.migrate(con)
        with closing(sqlite3.connect(self.path)) as con,con:
            con.execute('''INSERT INTO google_writer_runs(request_id,environment,trigger,actor,revision,
                started_at,status,result_json) VALUES(?,'SANDBOX','manual',?,1,'2026-11-11T20:00:00Z',
                'outcome_unknown',?)''',(self.source,self.actor,json.dumps({'status':'OUTCOME_UNKNOWN_HOLD_NO_RETRY',
                'plan_scope':'APPEND_ONLY','attempted_chunk':0,'outcome_unknown':True})))
            details_digest=writer._preview_details_digest(self.old)
            con.execute('''INSERT INTO google_writer_plan_journal(plan_id,request_id,environment,actor,
                plan_digest,append_only_digest,details_digest,source_digest,created_at,details_json)
                VALUES(?,?,'SANDBOX',?,?,?,?,?,1,?)''',(self.source,self.source,self.actor,
                self.old['plan_digest'],self.old['append_only_digest'],details_digest,self.source_digest,
                writer._preview_details_raw(self.old)))

    def client(self, **kwargs):
        return ContinuationClient(self.old,**kwargs)

    def _seed_separate_source_close(self):
        close_id='f'*32;reason_digest=_d('separate administrative decision')
        evidence_digest=_d('source close evidence')
        receipt={'environment':'SANDBOX','scriptId':writer.IDENTITIES['SANDBOX'][0],
            'spreadsheetId':writer.IDENTITIES['SANDBOX'][1],'contract':writer.CONTRACT,
            'requestId':self.source,'status':'ADMIN_CLOSED_UNKNOWN','closeId':close_id,
            'planScope':'APPEND_ONLY','disposition':'OUTCOME_UNKNOWN_NOT_CONFIRMED',
            'evidenceDigest':evidence_digest,'reasonDigest':reason_digest,
            'runRecordDigest':_d('immutable source record'),'closedAt':'2026-11-12T10:00:00Z',
            'actor':self.actor}
        receipt['digest']=writer._close_receipt_digest(receipt)
        with closing(sqlite3.connect(self.path)) as con,con:
            con.execute("UPDATE google_writer_runs SET status='closed_unknown' WHERE request_id=?",
                (self.source,))
            con.execute('''INSERT INTO google_writer_run_closures(close_id,request_id,environment,actor,reason,
                reason_digest,evidence_digest,plan_scope,plan_digest,attempted_chunk,original_status,
                original_result_digest,original_started_at,state,prepared_at,closed_at,receipt_json)
                VALUES(?,?, 'SANDBOX',?,'mock disposition',?,?, 'APPEND_ONLY',?,0,'outcome_unknown',? ,
                    '2026-11-11T20:00:00Z','closed_unknown','2026-11-12T09:59:00Z',?,?)''',
                (close_id,self.source,self.actor,reason_digest,evidence_digest,self.old['plan_digest'],
                 _d('old run result'),'2026-11-12T10:00:00Z',writer._canonical_json(receipt)))

    def _prepare_claimed_continuation(self):
        result=writer.prepare_append_continuation_preview(self.path,self.client(),self.source,self.actor)
        snapshot=writer.load_preview_plan(self.path,result['request_id'],self.actor,result['plan_digest'],
            details_digest=result['details_digest'])
        self._seed_separate_source_close()
        writer.validate_append_continuation_closed(self.path,snapshot,self.actor)
        claimed=writer.claim_run(self.path,'SANDBOX',result['request_id'],self.actor,'manual',
            manual_authorized=True,plan_scope='APPEND_ONLY',plan_digest=snapshot['append_only_digest'],
            details_digest=result['details_digest'])
        if not claimed['claimed']:
            raise AssertionError(f"test continuation claim failed: {claimed}")
        return result,snapshot

    def _checkpoint_mock_client(self, *, timeout_chunk=None, recovery_status='CHUNK_AMBIGUOUS'):
        test=self
        class Client:
            environment='SANDBOX'
            def __init__(self):self.calls=[]
            def invoke(self,action,request_id,actor,**kwargs):
                self.calls.append((action,request_id,kwargs))
                if action=='resume_check':
                    index=kwargs['chunk_index']
                    expected=kwargs['expected_checkpoint_digest']
                    remaining=251-index*25
                    return {'status':'RESUME_READY','digest':kwargs['digest'],
                        'checkpointDigest':expected,'nextChunk':index,
                        'planDetails':{'appends':[{} for _ in range(remaining)],'updates':[]},
                        'counts':{'append':remaining,'update':0}}
                if action=='recover_append_chunk':
                    return {'status':recovery_status}
                if action!='apply':raise AssertionError(f'unexpected mock action: {action}')
                index=kwargs['chunk_index']
                if index==timeout_chunk:raise writer.ExecutionOutcomeUnknown('synthetic boundary timeout')
                with closing(sqlite3.connect(test.path)) as con:
                    chunk=con.execute('''SELECT chunk_id,chunk_digest,plan_id,expected_json,status
                        FROM google_writer_chunk_journal WHERE run_id=? AND chunk_index=?''',
                        (request_id,index)).fetchone()
                if not chunk or chunk[4]!='inflight':
                    raise AssertionError('mock saw an apply without a durable in-flight chunk')
                row_count=len(json.loads(chunk[3])['rows'])
                more=index<10
                return {'status':'APPLY_CHUNK_VERIFIED' if more else 'COMPLETE',
                    'digest':kwargs['digest'],'planScope':'APPEND_ONLY','chunkIndex':index,
                    'nextChunk':index+1,'more':more,'phase':'append',
                    'checkpointDigest':_d(f'continuation-checkpoint-{index}'),
                    'chunkId':chunk[0],'chunkDigest':chunk[1],'planId':chunk[2],
                    'counts':{'append':row_count,'update':0,'batches':1}}
        return Client()

    def test_exact_25_confirmed_251_missing_builds_only_saved_missing_operations(self):
        client=self.client()
        result=writer.prepare_append_continuation_preview(self.path,client,self.source,self.actor)
        self.assertEqual(result['status'],'PREVIEW_READY')
        self.assertEqual(result['counts'],{'append':251,'update':0,'conflict':0,'error':0})
        self.assertFalse(result['writer_started'])
        self.assertEqual((result['google_writes'],result['script_properties_writes']),(0,0))
        self.assertEqual([call[0] for call in client.calls],['diagnose_append_plan','preview'])
        self.assertEqual(client.calls[0][2]['diagnostic_mode'],'audit')
        self.assertTrue(client.calls[0][2]['require_audit_statuses'])
        self.assertEqual(len(client.calls[0][2]['audit_targets']),276)
        snap=writer.load_preview_plan(self.path,result['request_id'],self.actor,result['plan_digest'],
            details_digest=result['details_digest'])
        self.assertEqual(snap['details']['appends'],self.ops[25:])
        self.assertEqual(len(snap['details']['appends']),251)
        self.assertEqual(len(snap['details']['append_continuation']['preserved_rows']),25)
        self.assertEqual(writer._append_continuation_operations_digest(snap['details']['appends']),
            snap['details']['append_continuation']['operation_digest'])
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute('SELECT status FROM google_writer_runs WHERE request_id=?',
                (self.source,)).fetchone()[0],'outcome_unknown')
            self.assertEqual(con.execute('SELECT COUNT(*) FROM google_writer_runs').fetchone()[0],1)

    def test_table_change_between_audit_and_preview_blocks_without_saving_candidate(self):
        client=self.client(preview_digest=_d('changed-sheet'))
        result=writer.prepare_append_continuation_preview(self.path,client,self.source,self.actor)
        self.assertEqual(result['status'],'BLOCKED')
        self.assertIn('CONTINUATION_PREVIEW_NOT_EXACT',result['reason_codes'])
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM google_writer_preview_plans').fetchone()[0],0)

    def test_conflict_or_incomplete_audit_blocks_and_does_not_call_preview(self):
        for status,code in [('CONFLICT','SOURCE_SHEETS_AUDIT_NOT_EXACT'),
                            ('UNVERIFIED','SOURCE_SHEETS_AUDIT_INCOMPLETE')]:
            with self.subTest(status=status):
                statuses=['CONFIRMED']*25+['MISSING']*250+[status]
                client=self.client(audit_statuses=statuses)
                result=writer.prepare_append_continuation_preview(self.path,client,self.source,self.actor)
                self.assertEqual(result['status'],'BLOCKED')
                self.assertIn(code,result['reason_codes'])
                self.assertEqual([call[0] for call in client.calls],['diagnose_append_plan'])

    def test_duplicate_or_unplanned_preview_target_blocks(self):
        duplicated=[dict(item) for item in self.ops[25:]]
        duplicated[-1]=dict(duplicated[0])
        client=self.client(preview_operations=duplicated)
        result=writer.prepare_append_continuation_preview(self.path,client,self.source,self.actor)
        self.assertEqual(result['status'],'BLOCKED')
        self.assertIn('CONTINUATION_PREVIEW_PLAN_MISMATCH',result['reason_codes'])

    def test_unknown_remote_audit_or_preview_keeps_old_hold_and_saves_no_new_run(self):
        for action in ('audit','preview'):
            with self.subTest(action=action):
                client=self.client(timeout_action=action)
                result=writer.prepare_append_continuation_preview(self.path,client,self.source,self.actor)
                self.assertEqual(result['status'],'BLOCKED')
                with closing(sqlite3.connect(self.path)) as con:
                    self.assertEqual(con.execute('SELECT status FROM google_writer_runs WHERE request_id=?',
                        (self.source,)).fetchone()[0],'outcome_unknown')
                    self.assertEqual(con.execute('SELECT COUNT(*) FROM google_writer_runs').fetchone()[0],1)
                    self.assertEqual(con.execute('SELECT COUNT(*) FROM google_writer_preview_plans').fetchone()[0],0)

    def test_repeated_preview_click_reuses_same_ticket_and_does_not_create_runs(self):
        client=self.client()
        first=writer.prepare_append_continuation_preview(self.path,client,self.source,self.actor)
        second=writer.prepare_append_continuation_preview(self.path,client,self.source,self.actor)
        self.assertEqual(first['status'],second['status'])
        self.assertEqual(first['request_id'],second['request_id'])
        self.assertEqual(first['ticket'],second['ticket'])
        self.assertEqual([call[0] for call in client.calls],
            ['diagnose_append_plan','preview','diagnose_append_plan','preview'])
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM google_writer_runs').fetchone()[0],1)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM google_writer_preview_plans').fetchone()[0],1)

    def test_apply_gate_refuses_until_old_hold_has_valid_close_receipt(self):
        result=writer.prepare_append_continuation_preview(self.path,self.client(),self.source,self.actor)
        snapshot=writer.load_preview_plan(self.path,result['request_id'],self.actor,result['plan_digest'],
            details_digest=result['details_digest'])
        with self.assertRaisesRegex(ValueError,'separately confirmed administrative close'):
            writer.validate_append_continuation_closed(self.path,snapshot,self.actor)

    def test_chunk_ids_are_stable_and_partition_251_as_ten_full_pages_and_one_row(self):
        result=writer.prepare_append_continuation_preview(self.path,self.client(),self.source,self.actor)
        snapshot=writer.load_preview_plan(self.path,result['request_id'],self.actor,result['plan_digest'],
            details_digest=result['details_digest'])
        details=snapshot['details']
        chunks=[writer.prepare_append_chunk(self.path,result['request_id'],self.actor,
            snapshot['append_only_digest'],snapshot['details_digest'],index) for index in range(11)]
        replay=writer.prepare_append_chunk(self.path,result['request_id'],self.actor,
            snapshot['append_only_digest'],snapshot['details_digest'],0)
        self.assertEqual([len(chunk['expected']['rows']) for chunk in chunks],[25]*10+[1])
        self.assertEqual(len({chunk['chunk_id'] for chunk in chunks}),11)
        self.assertEqual(replay['chunk_id'],chunks[0]['chunk_id'])
        self.assertEqual(chunks[-1]['expected']['chunk_index'],10)
        # Model the run as claimed before the worker marks a journaled chunk
        # in flight. This is a local fixture only; no client call is made.
        with closing(sqlite3.connect(self.path)) as con,con:
            con.execute("UPDATE google_writer_runs SET status='closed_unknown' WHERE request_id=?",
                (self.source,))
            con.execute('''INSERT INTO google_writer_runs(request_id,environment,trigger,actor,revision,
                started_at,status,result_json) VALUES(?,'SANDBOX','manual',?,1,?,'running',?)''',
                (result['request_id'],self.actor,'2026-11-12T10:00:00Z',
                 json.dumps({'plan_scope':'APPEND_ONLY','attempted_chunk':None})))
        self.assertFalse(writer.mark_append_chunk_inflight(self.path,chunks[1]['chunk_id']))
        self.assertTrue(writer.mark_append_chunk_inflight(self.path,chunks[0]['chunk_id']))
        self.assertFalse(writer.mark_append_chunk_inflight(self.path,chunks[1]['chunk_id']))
        for index,chunk in enumerate(chunks):
            more=index<10
            receipt={'status':'APPLY_CHUNK_VERIFIED' if more else 'COMPLETE',
                'digest':snapshot['append_only_digest'],'planScope':'APPEND_ONLY','chunkIndex':index,
                'nextChunk':index+1,'more':more,'phase':'append','checkpointDigest':_d(f'checkpoint-{index}'),
                'chunkId':chunk['chunk_id'],'chunkDigest':chunk['chunk_digest'],'planId':chunk['plan_id'],
                'counts':{'append':len(chunk['expected']['rows']),'update':0}}
            with closing(sqlite3.connect(self.path)) as con,con:
                con.execute("UPDATE google_writer_chunk_journal SET status='verified',receipt_json=? WHERE chunk_id=?",
                    (writer._canonical_json(receipt),chunk['chunk_id']))
            if index<10:
                self.assertTrue(writer.mark_append_chunk_inflight(self.path,chunks[index+1]['chunk_id']))
        expected=[writer._append_continuation_operation(item) for item in details['appends']]
        actual=[]
        for index in range(11):
            guard=writer._append_continuation_guard_for_chunk(self.path,result['request_id'],self.actor,index,
                {'continuation_request_id':self.source,'details_digest':snapshot['details_digest'],
                 'plan_digest':snapshot['append_only_digest']})
            actual.append(guard['continuation_remaining_digest'])
            self.assertEqual(guard['continuation_source_request_id'],self.source)
            self.assertEqual(guard['continuation_plan_digest'],
                details['append_continuation']['operation_digest'])
            self.assertEqual(len(guard['continuation_guard_rows']),25)
            self.assertTrue(all(writer.is_canonical_sha256_b64url(row['row_digest'])
                for row in guard['continuation_guard_rows']))
        self.assertEqual(len(set(actual)),11)

    def test_resume_after_four_confirmed_continuation_chunks_uses_same_run_and_next_checkpoint(self):
        result,snapshot=self._prepare_claimed_continuation()
        client=self._checkpoint_mock_client()
        first=writer.execute_claimed(self.path,client,result['request_id'],self.actor,
            digest=snapshot['append_only_digest'],manual_authorized=True,plan_scope='APPEND_ONLY',
            max_append_chunks=4)
        self.assertEqual(first['status'],'HALTED_AFTER_VERIFIED_CHECKPOINTS')
        self.assertEqual(first['verified_chunks'],4);self.assertEqual(first['next_chunk'],4)
        candidate=writer.load_append_only_resume_candidate(self.path,result['request_id'],self.actor)
        self.assertEqual(candidate['next_chunk'],4)
        self.assertEqual(candidate['verified_totals']['append'],100)
        prior_ids=[]
        with closing(sqlite3.connect(self.path)) as con:
            prior_ids=[row[0] for row in con.execute('''SELECT chunk_id FROM google_writer_chunk_journal
                WHERE run_id=? AND chunk_index<4 ORDER BY chunk_index''',(result['request_id'],))]
        self.assertEqual(len(prior_ids),4);self.assertEqual(len(set(prior_ids)),4)
        resumed=writer.continue_append_only_checkpoint(self.path,client,result['request_id'],self.actor,
            digest=snapshot['append_only_digest'],manual_authorized=True,max_append_chunks=4)
        self.assertEqual(resumed['status'],'HALTED_AFTER_VERIFIED_CHECKPOINTS')
        self.assertEqual(resumed['verified_chunks'],8);self.assertEqual(resumed['next_chunk'],8)
        apply_calls=[call for call in client.calls if call[0]=='apply']
        self.assertEqual([call[2]['chunk_index'] for call in apply_calls],list(range(8)))
        self.assertEqual({call[1] for call in apply_calls},{result['request_id']})
        self.assertEqual([call[2]['chunk_id'] for call in apply_calls[:4]],prior_ids)
        resume_call=next(call for call in client.calls if call[0]=='resume_check')
        self.assertEqual(resume_call[1],result['request_id'])
        self.assertEqual(resume_call[2]['chunk_index'],4)
        self.assertEqual(len(resume_call[2]['continuation_guard_rows']),25)
        with closing(sqlite3.connect(self.path)) as con:
            states=con.execute('''SELECT chunk_index,status FROM google_writer_chunk_journal
                WHERE run_id=? ORDER BY chunk_index''',(result['request_id'],)).fetchall()
            status,progress=con.execute('''SELECT status,result_json FROM google_writer_runs
                WHERE request_id=?''',(result['request_id'],)).fetchone()
        self.assertEqual(states,[(index,'verified') for index in range(8)])
        self.assertEqual(status,'partial');self.assertEqual(json.loads(progress)['next_chunk'],8)

    def test_timeout_at_four_chunk_resume_boundary_holds_without_replaying_any_chunk(self):
        result,snapshot=self._prepare_claimed_continuation()
        client=self._checkpoint_mock_client(timeout_chunk=4,recovery_status='CHUNK_AMBIGUOUS')
        first=writer.execute_claimed(self.path,client,result['request_id'],self.actor,
            digest=snapshot['append_only_digest'],manual_authorized=True,plan_scope='APPEND_ONLY',
            max_append_chunks=4)
        self.assertEqual(first['status'],'HALTED_AFTER_VERIFIED_CHECKPOINTS')
        held=writer.continue_append_only_checkpoint(self.path,client,result['request_id'],self.actor,
            digest=snapshot['append_only_digest'],manual_authorized=True,max_append_chunks=4)
        self.assertEqual(held['status'],'OUTCOME_UNKNOWN_HOLD_NO_RETRY')
        applies=[call for call in client.calls if call[0]=='apply']
        recoveries=[call for call in client.calls if call[0]=='recover_append_chunk']
        self.assertEqual([call[2]['chunk_index'] for call in applies],[0,1,2,3,4])
        self.assertEqual(len(recoveries),1);self.assertEqual(recoveries[0][2]['chunk_index'],4)
        with closing(sqlite3.connect(self.path)) as con:
            status,progress=con.execute('''SELECT status,result_json FROM google_writer_runs
                WHERE request_id=?''',(result['request_id'],)).fetchone()
            chunk=con.execute('''SELECT status FROM google_writer_chunk_journal
                WHERE run_id=? AND chunk_index=4''',(result['request_id'],)).fetchone()
        state=json.loads(progress)
        self.assertEqual(status,'outcome_unknown');self.assertEqual(state['next_chunk'],4)
        self.assertEqual(state['verified_totals']['append'],100);self.assertEqual(state['attempted_chunk'],4)
        self.assertEqual(chunk[0],'outcome_unknown')

    def test_claim_cannot_start_continuation_until_separate_close_receipt_exists(self):
        result=writer.prepare_append_continuation_preview(self.path,self.client(),self.source,self.actor)
        snapshot=writer.load_preview_plan(self.path,result['request_id'],self.actor,result['plan_digest'],
            details_digest=result['details_digest'])
        unclosed=writer.claim_run(self.path,'SANDBOX',result['request_id'],self.actor,'manual',
            manual_authorized=True,plan_scope='APPEND_ONLY',plan_digest=snapshot['append_only_digest'],
            details_digest=result['details_digest'])
        self.assertFalse(unclosed['claimed'])
        self.assertEqual(unclosed['status'],'continuation_source_close_required')

    def test_checkpoint_resume_reuses_same_request_and_resends_saved_continuation_bindings(self):
        result=writer.prepare_append_continuation_preview(self.path,self.client(),self.source,self.actor)
        snapshot=writer.load_preview_plan(self.path,result['request_id'],self.actor,result['plan_digest'],
            details_digest=result['details_digest'])
        close_id='f'*32;reason_digest=_d('separate administrative decision');evidence_digest=_d('source close evidence')
        receipt={'environment':'SANDBOX','scriptId':writer.IDENTITIES['SANDBOX'][0],
            'spreadsheetId':writer.IDENTITIES['SANDBOX'][1],'contract':writer.CONTRACT,
            'requestId':self.source,'status':'ADMIN_CLOSED_UNKNOWN','closeId':close_id,
            'planScope':'APPEND_ONLY','disposition':'OUTCOME_UNKNOWN_NOT_CONFIRMED',
            'evidenceDigest':evidence_digest,'reasonDigest':reason_digest,
            'runRecordDigest':_d('immutable source record'),'closedAt':'2026-11-12T10:00:00Z',
            'actor':self.actor}
        receipt['digest']=writer._close_receipt_digest(receipt)
        with closing(sqlite3.connect(self.path)) as con,con:
            con.execute("UPDATE google_writer_runs SET status='closed_unknown' WHERE request_id=?",(self.source,))
            con.execute('''INSERT INTO google_writer_run_closures(close_id,request_id,environment,actor,reason,
                reason_digest,evidence_digest,plan_scope,plan_digest,attempted_chunk,original_status,
                original_result_digest,original_started_at,state,prepared_at,closed_at,receipt_json)
                VALUES(?,?, 'SANDBOX',?,'mock disposition',?,?, 'APPEND_ONLY',?,0,'outcome_unknown',?,
                    '2026-11-11T20:00:00Z','closed_unknown','2026-11-12T09:59:00Z',?,?)''',
                (close_id,self.source,self.actor,reason_digest,evidence_digest,self.old['plan_digest'],
                 _d('old run result'),'2026-11-12T10:00:00Z',writer._canonical_json(receipt)))
            progress={'status':'HALTED_AFTER_VERIFIED_CHECKPOINTS','plan_scope':'APPEND_ONLY',
                'outcome_unknown':False,'attempted_chunk':None,'next_chunk':1,'last_verified_chunk':0,
                'checkpoint_digest':_d('verified chunk zero'),'plan_digest':snapshot['append_only_digest'],
                'details_digest':snapshot['details_digest'],'verified_totals':{'append':25,'update':0},
                'continuation_request_id':self.source}
            con.execute('''INSERT INTO google_writer_runs(request_id,environment,trigger,actor,revision,
                started_at,finished_at,status,result_json) VALUES(?,'SANDBOX','manual',?,1,
                '2026-11-12T10:00:00Z','2026-11-12T10:01:00Z','partial',?)''',
                (result['request_id'],self.actor,json.dumps(progress)))
        client=self.client()
        with self.assertRaises(writer.ExecutionPreflightError):
            writer.continue_append_only_checkpoint(self.path,client,result['request_id'],self.actor,
                digest=snapshot['append_only_digest'])
        self.assertEqual(len(client.calls),1)
        action,request_id,kwargs=client.calls[0]
        self.assertEqual((action,request_id,kwargs['chunk_index']),('resume_check',result['request_id'],1))
        self.assertEqual(kwargs['continuation_source_request_id'],self.source)
        self.assertEqual(len(kwargs['continuation_guard_rows']),25)
        self.assertTrue(all('row_digest' in row for row in kwargs['continuation_guard_rows']))
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute('SELECT status FROM google_writer_runs WHERE request_id=?',
                (result['request_id'],)).fetchone()[0],'partial')

    def test_apply_gate_opens_only_for_closed_unknown_with_matching_receipt(self):
        result=writer.prepare_append_continuation_preview(self.path,self.client(),self.source,self.actor)
        snapshot=writer.load_preview_plan(self.path,result['request_id'],self.actor,result['plan_digest'],
            details_digest=result['details_digest'])
        close_id='e'*32;reason_digest=_d('separate admin reason');evidence_digest=_d('close evidence')
        receipt={'environment':'SANDBOX','scriptId':writer.IDENTITIES['SANDBOX'][0],
            'spreadsheetId':writer.IDENTITIES['SANDBOX'][1],'contract':writer.CONTRACT,
            'requestId':self.source,'status':'ADMIN_CLOSED_UNKNOWN','closeId':close_id,
            'planScope':'APPEND_ONLY','disposition':'OUTCOME_UNKNOWN_NOT_CONFIRMED',
            'evidenceDigest':evidence_digest,'reasonDigest':reason_digest,
            'runRecordDigest':_d('immutable run receipt'),'closedAt':'2026-11-12T10:00:00Z',
            'actor':self.actor}
        receipt['digest']=writer._close_receipt_digest(receipt)
        with closing(sqlite3.connect(self.path)) as con,con:
            con.execute("UPDATE google_writer_runs SET status='closed_unknown' WHERE request_id=?",(self.source,))
            con.execute('''INSERT INTO google_writer_run_closures(close_id,request_id,environment,actor,reason,
                reason_digest,evidence_digest,plan_scope,plan_digest,attempted_chunk,original_status,
                original_result_digest,original_started_at,state,prepared_at,closed_at,receipt_json)
                VALUES(?,?, 'SANDBOX',?,'mock disposition',?,?, 'APPEND_ONLY',?,0,'outcome_unknown',?,
                    '2026-11-11T20:00:00Z','closed_unknown','2026-11-12T09:59:00Z',?,?)''',
                (close_id,self.source,self.actor,reason_digest,evidence_digest,self.old['plan_digest'],
                 _d('old run result'),'2026-11-12T10:00:00Z',writer._canonical_json(receipt)))
        self.assertEqual(writer.validate_append_continuation_closed(self.path,snapshot,self.actor),
            {'source_request_id':self.source,'closed':True,'disposition':'OUTCOME_UNKNOWN_NOT_CONFIRMED'})


if __name__=='__main__':
    unittest.main()
