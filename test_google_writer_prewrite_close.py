import base64
import hashlib
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import auth_access
import google_writer_execution as writer


class MockPrewriteClose:
    def __init__(self, request_id, *, existing_codes=(), run_marker_count=0, write_ahead_bytes=8501):
        self.request_id=request_id
        self.existing_codes=set(existing_codes)
        self.run_marker_count=run_marker_count
        self.marker=request_id
        self.calls=0
        self.sheet_writes=0
        self.actual_stage='append_inflight_save'
        self.write_ahead_bytes=write_ahead_bytes
        self.tombstones={}

    def invoke(self, action, request_id, actor, **kwargs):
        self.calls+=1
        assert action=='close_prewrite_failure'
        assert request_id==self.request_id and kwargs['plan_scope']=='APPEND_ONLY'
        assert kwargs['manual_authorized'] is True and kwargs['chunk_index']==0
        assert kwargs['target_identity_digest']==writer._sha256_b64(writer._canonical_json(
            [[item['tab'],item['code']] for item in kwargs['target_identities']]).encode())
        if self.marker!=request_id:
            raise RuntimeError('uncertain marker mismatch')
        if any(item['code'] in self.existing_codes for item in kwargs['target_identities']):
            raise RuntimeError('planned identity exists on a target tab')
        if self.run_marker_count:
            raise RuntimeError('run marker exists in Sheets')
        event=self.tombstones.get(request_id)
        if event and event['closeId']!=kwargs['close_id']:
            raise PermissionError('close id mismatch')
        if not event:
            event={'requestId':request_id,'closeId':kwargs['close_id'],
                'runRecordDigest':writer._sha256_b64(b'mock ready Apps Script prewrite record'),
                'closedAt':'2026-11-10T20:00:00.000Z'}
            self.tombstones[request_id]=event
            self.marker=None
        legacy=kwargs['prewrite_stage']==writer._LEGACY_PREWRITE_LIMIT_STAGE
        receipt={'environment':'SANDBOX','scriptId':writer.IDENTITIES['SANDBOX'][0],
            'spreadsheetId':writer.IDENTITIES['SANDBOX'][1],'contract':writer.CONTRACT,
            'requestId':request_id,'status':'ADMIN_CLOSED_PREWRITE_NO_WRITE',
            'closeId':kwargs['close_id'],'planScope':'APPEND_ONLY',
            'disposition':'PREWRITE_FAILURE_CONFIRMED_NO_SHEET_WRITE',
            'evidenceDigest':kwargs['close_evidence_digest'],'reasonDigest':kwargs['reason_digest'],
            'chunkId':kwargs['chunk_id'],'chunkDigest':kwargs['chunk_digest'],'chunkIndex':0,
            'targetIdentityDigest':kwargs['target_identity_digest'],'prewriteStage':self.actual_stage,
            'runRecordDigest':event['runRecordDigest'],'closedAt':event['closedAt'],'actor':actor,
            'proofType':'LEGACY_V1_WRITEAHEAD_OVERSIZE' if legacy else 'APPS_SCRIPT_LAST_ERROR',
            'writeAheadBytes':self.write_ahead_bytes if legacy else 0,
            'checkpointMaxBytes':writer._LEGACY_PREWRITE_LIMIT_BYTES if legacy else 0,
            'legacyManifestProjectionDigest':kwargs.get('legacy_manifest_projection_digest') or '',
            'idempotent':self.calls>1}
        receipt['digest']=writer._prewrite_close_receipt_digest(receipt)
        return receipt


class MockPrewriteReadOnly:
    environment='SANDBOX'
    def __init__(self, *, status='READY', reason_codes=(), fail=False):
        self.status=status;self.reason_codes=list(reason_codes);self.fail=fail;self.calls=[]
    def invoke(self, action, request_id, actor, **kwargs):
        self.calls.append((action,request_id,actor,kwargs))
        if self.fail: raise writer.ExecutionPreflightError('mock read-only source unavailable')
        return {'status':self.status,'request_id_matches':True,'plan_binding':'PASS',
            'chunk_binding':'PASS','manifest_binding':'PASS','write_ahead_bytes':8501,
            'checkpoint_max_bytes':8000,'target_count':len(kwargs['target_identities']),
            'target_code_matches':0 if not self.reason_codes else 1,
            'run_marker_matches':0,'reason_codes':self.reason_codes,
            'read_only':True,'sqlite_writes':0,'sheets_writes':0,'properties_writes':0}


class PrewriteCloseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix='prewrite-close-')
        self.addCleanup(self.temp.cleanup)
        self.path=str(Path(self.temp.name)/'sandbox.sqlite3')
        with closing(sqlite3.connect(self.path)) as con, con: writer.migrate(con)
        self.request_id='a'*32
        self.close_id='b'*32
        self.actor='admin-fixture'
        self.reason='Confirmed prewrite failure; no Sheet writes occurred.'
        self.plan_digest=self.digest('plan')
        self.source_digest=self.digest('source')
        self.details={
            'version':1,'environment':'SANDBOX','plan_digest':self.plan_digest,
            'append_only_digest':self.plan_digest,'source_digest':self.source_digest,
            'counts':{'append':25,'update':0,'conflict':0,'error':0},
            'appends':[{'operation':'APPEND','tab':'ФОП' if i<21 else 'ЮО','row':100+i,
                'code':f'{i+1:010d}','cells':[{'column':'A','new_value':f'=F{100+i}','formula':True},
                {'column':'B','new_value':f'{i+1:010d}','formula':False}]} for i in range(25)],
            'updates':[],'conflicts':[],'errors':[]}
        snap=writer.store_preview_plan(self.path,self.request_id,'writer-fixture',self.details)
        self.details_digest=snap['details_digest']
        writer.claim_run(self.path,'SANDBOX',self.request_id,'writer-fixture','manual',
            manual_authorized=True,plan_scope='APPEND_ONLY',plan_digest=self.plan_digest,
            details_digest=self.details_digest)
        self.chunk=writer.prepare_append_chunk(self.path,self.request_id,'writer-fixture',
            self.plan_digest,self.details_digest,0,now=datetime(2026,11,10,19,0,tzinfo=timezone.utc))
        self.safe_error={'stage':'append_inflight_save','category':'apps_script_stage_error','exception_type':'Error'}
        self.result_raw=json.dumps({'status':'APPS_SCRIPT_PREWRITE_REJECTED_NO_SHEET_WRITE',
            'plan_scope':'APPEND_ONLY','plan_digest':self.plan_digest,'details_digest':self.details_digest,
            'planned_counts':{'append':25,'update':0},'safe_error':self.safe_error},sort_keys=True)
        self.finished='2026-11-10T19:01:00+00:00'
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("UPDATE google_writer_runs SET status='failed_safe',finished_at=?,result_json=? WHERE request_id=?",
                (self.finished,self.result_raw,self.request_id))

    @staticmethod
    def digest(text):
        return base64.urlsafe_b64encode(hashlib.sha256(text.encode()).digest()).decode().rstrip('=')

    def run_row(self):
        with closing(sqlite3.connect(self.path)) as con:
            return con.execute('SELECT status,finished_at,result_json FROM google_writer_runs WHERE request_id=?',
                               (self.request_id,)).fetchone()

    def test_confirmed_prewrite_close_preserves_history_and_releases_only_after_receipt(self):
        writer.prepare_admin_close_prewrite(self.path,'SANDBOX',self.close_id,self.request_id,
            self.actor,self.reason)
        pending=writer.status(self.path,'SANDBOX',available=True,running=True,actor=self.actor)
        self.assertTrue(pending['blocked'])
        self.assertTrue(pending['prewrite_close_blocked'])
        denied=writer.claim_run(self.path,'SANDBOX','c'*32,'another-admin','manual',
            manual_authorized=True,plan_scope='APPEND_ONLY')
        self.assertFalse(denied['claimed'])
        self.assertEqual(denied['status'],'prewrite_failure_close_required')
        script=MockPrewriteClose(self.request_id)
        result=writer.close_confirmed_prewrite_failure(self.path,script,self.request_id,
            self.actor,self.close_id,self.reason)
        self.assertEqual(result['status'],'ADMIN_CLOSED_PREWRITE_NO_WRITE')
        self.assertEqual(result['disposition'],'PREWRITE_FAILURE_CONFIRMED_NO_SHEET_WRITE')
        self.assertEqual(script.sheet_writes,0)
        self.assertEqual(script.marker,None)
        self.assertEqual(self.run_row(),('closed_prewrite',self.finished,self.result_raw))
        with closing(sqlite3.connect(self.path)) as con:
            row=con.execute('SELECT status,expected_json FROM google_writer_chunk_journal WHERE run_id=?',
                            (self.request_id,)).fetchone()
            audit=con.execute('SELECT state,original_status,original_result_digest,receipt_json FROM google_writer_prewrite_closures WHERE request_id=?',
                              (self.request_id,)).fetchone()
        self.assertEqual(row[0],'prepared')
        self.assertEqual(audit[0:2],('closed_prewrite','failed_safe'))
        self.assertEqual(audit[2],writer._sha256_b64(self.result_raw.encode()))
        self.assertEqual(json.loads(audit[3])['status'],'ADMIN_CLOSED_PREWRITE_NO_WRITE')
        replay=writer.claim_run(self.path,'SANDBOX',self.request_id,self.actor,'manual',
            manual_authorized=True,plan_scope='APPEND_ONLY',plan_digest=self.plan_digest)
        self.assertFalse(replay['claimed'])
        self.assertEqual(replay['status'],'closed_prewrite')
        after=writer.status(self.path,'SANDBOX',available=True,running=True,actor=self.actor)
        self.assertFalse(after['blocked'])
        allowed=writer.claim_run(self.path,'SANDBOX','c'*32,'another-admin','manual',
            manual_authorized=True,plan_scope='APPEND_ONLY')
        self.assertTrue(allowed['claimed'])

    def test_read_only_preflight_ready_returns_only_safe_aggregates_and_creates_no_intent(self):
        client=MockPrewriteReadOnly()
        before=self.run_row()
        result=writer.prewrite_close_preflight(self.path,client,self.request_id,self.actor)
        self.assertEqual(result['status'],'READY')
        self.assertEqual((result['write_ahead_bytes'],result['checkpoint_max_bytes']),(8501,8000))
        self.assertEqual((result['target_count'],result['target_code_matches'],result['run_marker_matches']),(25,0,0))
        self.assertTrue(result['read_only'])
        self.assertEqual((result['sqlite_writes'],result['sheets_writes'],result['properties_writes']),(0,0,0))
        self.assertEqual(client.calls[0][0],'prewrite_close_preflight')
        self.assertEqual(self.run_row(),before)
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM google_writer_prewrite_closures').fetchone()[0],0)
            self.assertEqual(con.execute('SELECT status FROM google_writer_chunk_journal WHERE run_id=?',
                                         (self.request_id,)).fetchone()[0],'prepared')

    def test_read_only_preflight_blocked_when_target_row_or_marker_is_found(self):
        for reason in ('TARGET_CODES_PRESENT','RUN_MARKER_PRESENT'):
            with self.subTest(reason=reason):
                result=writer.prewrite_close_preflight(self.path,
                    MockPrewriteReadOnly(status='BLOCKED',reason_codes=[reason]),self.request_id,self.actor)
                self.assertEqual(result['status'],'BLOCKED')
                self.assertEqual(result['reason_codes'],[reason])
                self.assertEqual(result['sqlite_writes'],0)
                with closing(sqlite3.connect(self.path)) as con:
                    self.assertEqual(con.execute('SELECT COUNT(*) FROM google_writer_prewrite_closures').fetchone()[0],0)

    def test_read_only_preflight_incomplete_remote_read_fails_closed(self):
        result=writer.prewrite_close_preflight(self.path,
            MockPrewriteReadOnly(fail=True),self.request_id,self.actor)
        self.assertEqual(result['status'],'BLOCKED')
        self.assertEqual(result['reason_codes'],['APPS_SCRIPT_CHECK_UNAVAILABLE'])
        self.assertTrue(result['read_only'])
        self.assertEqual(self.run_row()[0],'failed_safe')
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM google_writer_prewrite_closures').fetchone()[0],0)

    def test_state_change_after_ready_preflight_is_rechecked_before_close_intent(self):
        result=writer.prewrite_close_preflight(self.path,MockPrewriteReadOnly(),self.request_id,self.actor)
        self.assertEqual(result['status'],'READY')
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("UPDATE google_writer_chunk_journal SET status='inflight' WHERE run_id=?",
                        (self.request_id,))
        client=MockPrewriteClose(self.request_id)
        with self.assertRaisesRegex(RuntimeError,'First APPEND portion'):
            writer.close_confirmed_prewrite_failure(self.path,client,self.request_id,
                self.actor,self.close_id,self.reason)
        self.assertEqual(client.calls,0)
        self.assertEqual(self.run_row()[0],'failed_safe')
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM google_writer_prewrite_closures').fetchone()[0],0)

    def test_receipt_cannot_finalize_if_failed_safe_evidence_changes_after_remote_read(self):
        script=MockPrewriteClose(self.request_id)
        original=script.invoke
        def mutate_after_remote(*args,**kwargs):
            receipt=original(*args,**kwargs)
            with closing(sqlite3.connect(self.path)) as con, con:
                con.execute("UPDATE google_writer_chunk_journal SET status='inflight' WHERE run_id=?",
                            (self.request_id,))
            return receipt
        script.invoke=mutate_after_remote
        with self.assertRaises(writer.AdminCloseFinalizationUnknown):
            writer.close_confirmed_prewrite_failure(self.path,script,self.request_id,
                self.actor,self.close_id,self.reason)
        self.assertEqual(self.run_row()[0],'failed_safe')
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute('SELECT state FROM google_writer_prewrite_closures').fetchone()[0],'prepared')
        held=writer.status(self.path,'SANDBOX',available=True,running=True,actor=self.actor)
        self.assertTrue(held['blocked'])

    def test_incomplete_or_non_prewrite_sqlite_evidence_creates_no_intent(self):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("UPDATE google_writer_runs SET result_json=? WHERE request_id=?",
                (json.dumps({'status':'APPS_SCRIPT_PREWRITE_REJECTED_NO_SHEET_WRITE',
                    'plan_scope':'APPEND_ONLY','plan_digest':self.plan_digest,
                    'safe_error':{'stage':'append_batch_update','category':'apps_script_stage_error'}}),self.request_id))
        with self.assertRaisesRegex(RuntimeError,'prewrite candidate'):
            writer.prepare_admin_close_prewrite(self.path,'SANDBOX',self.close_id,self.request_id,
                self.actor,self.reason)
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM google_writer_prewrite_closures').fetchone()[0],0)

    def test_legacy_http4xx_classification_requires_apps_script_stage_and_sheet_proof(self):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("UPDATE google_writer_runs SET result_json=? WHERE request_id=?",
                (json.dumps({'status':'PRECALL_REJECTED_NO_REMOTE_CALL','plan_scope':'APPEND_ONLY',
                    'plan_digest':self.plan_digest}),self.request_id))
        script=MockPrewriteClose(self.request_id)
        result=writer.close_confirmed_prewrite_failure(self.path,script,self.request_id,
            self.actor,self.close_id,self.reason)
        self.assertEqual(result['status'],'ADMIN_CLOSED_PREWRITE_NO_WRITE')
        self.assertEqual(script.sheet_writes,0)
        with closing(sqlite3.connect(self.path)) as con:
            audit=con.execute('SELECT prewrite_stage,verified_prewrite_stage FROM google_writer_prewrite_closures').fetchone()
        self.assertEqual(audit,('APPS_SCRIPT_PREWRITE_GUARD_V1','append_inflight_save'))

    def test_historical_v18_generic_catch_uses_exact_oversize_v1_writeahead_proof(self):
        with patch.object(writer,'_LEGACY_PREWRITE_LIMIT_REQUEST_ID',self.request_id):
            with closing(sqlite3.connect(self.path)) as con, con:
                con.execute("UPDATE google_writer_runs SET result_json=? WHERE request_id=?",
                    (json.dumps({'status':'PRECALL_REJECTED_NO_REMOTE_CALL','plan_scope':'APPEND_ONLY',
                        'plan_digest':self.plan_digest,'safe_error':{'stage':'execution_api_response',
                        'category':'execution_api_http_error','http_status':400}}),self.request_id))
            script=MockPrewriteClose(self.request_id,write_ahead_bytes=8217)
            closed=writer.close_confirmed_prewrite_failure(self.path,script,self.request_id,
                self.actor,self.close_id,self.reason)
            self.assertEqual(closed['status'],'ADMIN_CLOSED_PREWRITE_NO_WRITE')
            self.assertEqual(script.sheet_writes,0)
            with closing(sqlite3.connect(self.path)) as con:
                audit=con.execute('SELECT prewrite_stage,receipt_json FROM google_writer_prewrite_closures').fetchone()
            self.assertEqual(audit[0],writer._LEGACY_PREWRITE_LIMIT_STAGE)
            receipt=json.loads(audit[1])
            self.assertEqual(receipt['proofType'],'LEGACY_V1_WRITEAHEAD_OVERSIZE')
            self.assertEqual(receipt['writeAheadBytes'],8217)
            self.assertEqual(receipt['checkpointMaxBytes'],8000)

    def test_historical_size_proof_at_or_below_limit_is_rejected_and_hold_remains(self):
        with patch.object(writer,'_LEGACY_PREWRITE_LIMIT_REQUEST_ID',self.request_id):
            with closing(sqlite3.connect(self.path)) as con, con:
                con.execute("UPDATE google_writer_runs SET result_json=? WHERE request_id=?",
                    (json.dumps({'status':'PRECALL_REJECTED_NO_REMOTE_CALL','plan_scope':'APPEND_ONLY',
                        'plan_digest':self.plan_digest}),self.request_id))
            with self.assertRaises(writer.AdminCloseFinalizationUnknown):
                writer.close_confirmed_prewrite_failure(self.path,
                    MockPrewriteClose(self.request_id,write_ahead_bytes=8000),self.request_id,
                    self.actor,self.close_id,self.reason)
            self.assertEqual(self.run_row()[0],'failed_safe')
            with closing(sqlite3.connect(self.path)) as con:
                self.assertEqual(con.execute('SELECT state FROM google_writer_prewrite_closures').fetchone()[0],'prepared')

    def test_chunk_must_remain_prepared_and_unique(self):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("UPDATE google_writer_chunk_journal SET status='inflight' WHERE run_id=?",
                        (self.request_id,))
        with self.assertRaisesRegex(RuntimeError,'First APPEND portion'):
            writer.prepare_admin_close_prewrite(self.path,'SANDBOX',self.close_id,self.request_id,
                self.actor,self.reason)

    def test_sheet_identity_or_run_marker_evidence_rejects_before_release(self):
        for script in (MockPrewriteClose(self.request_id,existing_codes={'0000000001'}),
                       MockPrewriteClose(self.request_id,run_marker_count=1)):
            with self.subTest(existing=bool(script.existing_codes),marker=script.run_marker_count):
                # A proof failure at the Apps Script read-only gate retains SQLite failed_safe.
                with self.assertRaises(RuntimeError):
                    writer.close_confirmed_prewrite_failure(self.path,script,self.request_id,
                        self.actor,self.close_id,self.reason)
                self.assertEqual(self.run_row()[0],'failed_safe')
                with closing(sqlite3.connect(self.path)) as con:
                    self.assertEqual(con.execute('SELECT COUNT(*) FROM google_writer_prewrite_closures').fetchone()[0],1)
                    self.assertEqual(con.execute('SELECT state FROM google_writer_prewrite_closures').fetchone()[0],'prepared')

    def test_missing_remote_receipt_keeps_hold_and_retry_is_same_idempotent_close(self):
        script=MockPrewriteClose(self.request_id)
        original=script.invoke
        def lost(*args,**kwargs):
            original(*args,**kwargs)
            raise writer.ExecutionOutcomeUnknown('mock response lost')
        script.invoke=lost
        with self.assertRaises(writer.ExecutionOutcomeUnknown):
            writer.close_confirmed_prewrite_failure(self.path,script,self.request_id,
                self.actor,self.close_id,self.reason)
        self.assertEqual(self.run_row()[0],'failed_safe')
        intent=writer.prepare_admin_close_prewrite(self.path,'SANDBOX',self.close_id,self.request_id,
            self.actor,self.reason)
        self.assertEqual(intent['state'],'prepared')

    def test_endpoint_requires_admin_and_writer_permissions(self):
        path='/api/admin/google-writer/close-prewrite'
        self.assertEqual(auth_access.permission_key('POST',path),'google.writer.execute')
        source=Path(__file__).with_name('server.py').read_text(encoding='utf-8')
        start=source.index("if parsed.path == '/api/admin/google-writer/close-prewrite':")
        end=source.index("if parsed.path in {'/api/google-writer/preview','/api/google-writer/apply'}:",start)
        route=source[start:end]
        self.assertIn("not permissions.get('admin.manage') or not permissions.get('google.writer.execute')",route)
        self.assertIn("payload.get('confirmed') is not True",route)
        self.assertLess(route.index("not permissions.get('admin.manage')"),route.index('google_writer_client()'))

    def test_read_only_preflight_endpoint_is_sandbox_admin_only_and_does_not_prepare_close(self):
        path='/api/admin/google-writer/prewrite-close-preflight'
        self.assertEqual(auth_access.permission_key('POST',path),'google.writer.execute')
        source=Path(__file__).with_name('server.py').read_text(encoding='utf-8')
        start=source.index("if parsed.path == '/api/admin/google-writer/prewrite-close-preflight':")
        end=source.index("if parsed.path == '/api/admin/google-writer/close-prewrite':",start)
        route=source[start:end]
        self.assertIn("not permissions.get('admin.manage') or not permissions.get('google.writer.execute')",route)
        self.assertIn('prewrite_close_preflight(',route)
        self.assertNotIn('prepare_admin_close_prewrite(',route)
        self.assertNotIn('close_confirmed_prewrite_failure(',route)
        auth_start=source.index('if (seen_now - float(session.get("last_seen_persisted") or 0) >= 60')
        auth_guard=source[auth_start:source.index('session["last_seen_persisted"] = seen_now',auth_start)]
        self.assertIn('self.command == "POST" and path == "/api/admin/google-writer/prewrite-close-preflight"',auth_guard)

    def test_apps_script_proof_path_is_read_only_for_sheets(self):
        path=Path(__file__).parent/'scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxAllScopeExecution20261109.gs'
        source=path.read_text(encoding='utf-8')
        start=source.index('function pqmSandboxClosePrewriteFailure20261109_')
        end=source.index('/* Read-only support view.',start)
        function=source[start:end]
        self.assertIn('pqmSandboxAppendCodeCounts_',function)
        self.assertIn('Values.batchGet',function)
        self.assertNotIn('batchUpdate(',function)
        self.assertIn("properties.setProperty(closeKey",function)
        self.assertIn("properties.deleteProperty('PQM_EXECUTION_UNCERTAIN')",function)


if __name__=='__main__':
    unittest.main()
