import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import auth_access
import google_writer_execution as writer


class MockAppsScriptClose:
    def __init__(self, *, timeout_once=False):
        self.marker=None
        self.tombstones={}
        self.calls=0
        self.sheet_writes=0
        self.timeout_once=timeout_once
        self.lock=threading.Lock()

    def invoke(self, action, request_id, actor, **kwargs):
        self.assertions(action,request_id,actor,kwargs)
        close_id=kwargs['close_id']
        with self.lock:
            self.calls+=1
            event=self.tombstones.get(request_id)
            if event:
                if event['closeId']!=close_id:
                    raise PermissionError('different close id')
            else:
                if self.marker!=request_id:
                    raise RuntimeError('marker mismatch')
                event={'requestId':request_id,'closeId':close_id,
                    'planScope':kwargs['plan_scope'],'expectedDigest':kwargs['digest'],
                    'closeEvidenceDigest':kwargs['close_evidence_digest'],
                    'reasonDigest':kwargs['reason_digest'],'actor':actor,
                    'runRecordDigest':writer._sha256_b64(b'mock immutable Apps Script run record'),
                    'closedAt':'2026-11-10T10:00:00.000Z'}
                self.tombstones[request_id]=event
                self.marker=None
            receipt={'environment':'SANDBOX','scriptId':writer.IDENTITIES['SANDBOX'][0],
                'spreadsheetId':writer.IDENTITIES['SANDBOX'][1],'contract':writer.CONTRACT,
                'requestId':request_id,'status':'ADMIN_CLOSED_UNKNOWN','closeId':close_id,
                'planScope':kwargs['plan_scope'],'disposition':'OUTCOME_UNKNOWN_NOT_CONFIRMED',
                'evidenceDigest':kwargs['close_evidence_digest'],
                'reasonDigest':kwargs['reason_digest'],'runRecordDigest':event['runRecordDigest'],
                'closedAt':event['closedAt'],'actor':actor,'idempotent':self.calls>1}
            receipt['digest']=writer._close_receipt_digest(receipt)
            if self.timeout_once:
                self.timeout_once=False
                raise writer.ExecutionOutcomeUnknown('mock response lost')
            return receipt

    @staticmethod
    def assertions(action,request_id,actor,kwargs):
        assert action=='close_unknown_run'
        assert request_id and actor
        assert kwargs['manual_authorized'] is True


class AdminCloseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.path=Path(self.temp.name)/'isolated-writer.sqlite3'
        with closing(sqlite3.connect(self.path)) as con, con:
            writer.migrate(con)
        self.request_id='a'*32
        self.close_id='b'*32
        self.actor='admin-fixture'
        self.reason='Synthetic test close for an unknown outcome.'
        self.plan_digest=writer._sha256_b64(b'synthetic preview plan')
        self.result_raw=json.dumps({'status':'OUTCOME_UNKNOWN_HOLD_NO_RETRY',
            'outcome_unknown':True,'plan_scope':'ALL','plan_digest':self.plan_digest,
            'attempted_chunk':0,'safe_error':{'stage':'mock','category':'transport_timeout',
            'exception_type':'TimeoutError'}},sort_keys=True)
        self.finished='2026-11-10T09:00:00+00:00'
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute('''INSERT INTO google_writer_runs(request_id,environment,trigger,actor,revision,
                started_at,finished_at,status,result_json) VALUES(?,?,?,?,?,?,?,?,?)''',
                (self.request_id,'SANDBOX','manual','writer-fixture',1,
                 '2026-11-10T08:00:00+00:00',self.finished,'outcome_unknown',self.result_raw))

    def tearDown(self):
        self.temp.cleanup()

    def run_row(self):
        with closing(sqlite3.connect(self.path)) as con, con:
            return con.execute('SELECT status,finished_at,result_json FROM google_writer_runs WHERE request_id=?',
                               (self.request_id,)).fetchone()

    def test_migration_only_adds_closure_table_and_preserves_existing_run(self):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute('DROP TABLE google_writer_run_closures')
            before_schema=dict(con.execute("SELECT name,sql FROM sqlite_master WHERE type='table'"))
            before_run=con.execute('SELECT * FROM google_writer_runs WHERE request_id=?',
                                   (self.request_id,)).fetchone()
            writer.migrate(con)
            after_schema=dict(con.execute("SELECT name,sql FROM sqlite_master WHERE type='table'"))
            self.assertEqual(set(after_schema)-set(before_schema),{'google_writer_run_closures'})
            for table,sql in before_schema.items():self.assertEqual(after_schema[table],sql)
            self.assertEqual(con.execute('SELECT * FROM google_writer_runs WHERE request_id=?',
                                         (self.request_id,)).fetchone(),before_run)
            writer.migrate(con)
            self.assertEqual(dict(con.execute("SELECT name,sql FROM sqlite_master WHERE type='table'")),after_schema)

    def test_close_requires_admin_route_and_preserves_execution_history(self):
        self.assertEqual(auth_access.permission_key('POST','/api/admin/google-writer/close-unknown'),
                         'google.writer.execute')
        details='{"synthetic_manifest":true}'
        source_digest=writer._sha256_b64(b'synthetic source')
        chunk_digest=writer._sha256_b64(b'synthetic chunk')
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute('''INSERT INTO google_writer_plan_journal(plan_id,request_id,environment,actor,
                plan_digest,append_only_digest,details_digest,source_digest,created_at,details_json)
                VALUES(?,?,?,?,?,?,?,?,?,?)''',
                (self.request_id,self.request_id,'SANDBOX','writer-fixture',self.plan_digest,
                 self.plan_digest,self.plan_digest,source_digest,1,details))
            con.execute('''INSERT INTO google_writer_apply_chunk_journal(chunk_id,plan_id,run_id,
                environment,scope,phase,plan_digest,source_digest,chunk_index,chunk_digest,status,
                expected_json,prepared_at,inflight_at,verified_at,receipt_json)
                VALUES(?,?,?,'SANDBOX','ALL','append',?,?,0,?,'outcome_unknown',?,?,'now',NULL,?)''',
                ('d'*32,self.request_id,self.request_id,self.plan_digest,source_digest,
                 chunk_digest,'{"operations":[{"synthetic":true}]}','2026-11-10T09:00:00Z','{"kept":true}'))
            before={name:con.execute(f'SELECT * FROM {name} WHERE '+
                ('request_id=?' if name=='google_writer_plan_journal' else 'run_id=?'),
                (self.request_id,)).fetchall() for name in (
                    'google_writer_plan_journal','google_writer_apply_chunk_journal')}
        script=MockAppsScriptClose();script.marker=self.request_id
        result=writer.close_unknown_run(self.path,script,self.request_id,self.actor,self.close_id,self.reason)
        self.assertEqual(result['status'],'ADMIN_CLOSED_UNKNOWN')
        self.assertEqual(result['disposition'],'OUTCOME_UNKNOWN_NOT_CONFIRMED')
        self.assertEqual(self.run_row(),('closed_unknown',self.finished,self.result_raw))
        self.assertEqual(script.sheet_writes,0)
        with closing(sqlite3.connect(self.path)) as con, con:
            closure=con.execute('SELECT state,actor,reason,original_status,original_result_digest,receipt_json '
                'FROM google_writer_run_closures WHERE request_id=?',(self.request_id,)).fetchone()
            self.assertEqual(closure[:4],('closed_unknown',self.actor,self.reason,'outcome_unknown'))
            self.assertEqual(closure[4],writer._sha256_b64(self.result_raw.encode()))
            self.assertEqual(json.loads(closure[5])['status'],'ADMIN_CLOSED_UNKNOWN')
            after={name:con.execute(f'SELECT * FROM {name} WHERE '+
                ('request_id=?' if name=='google_writer_plan_journal' else 'run_id=?'),
                (self.request_id,)).fetchall() for name in before}
            self.assertEqual(after,before)
        status=writer.status(self.path,'SANDBOX',actor=self.actor)
        self.assertFalse(status['blocked'])
        self.assertEqual(status['runs'][0]['status'],'closed_unknown')
        same=writer.claim_run(self.path,'SANDBOX',self.request_id,self.actor,'manual',
            manual_authorized=True,plan_scope='ALL',plan_digest=self.plan_digest)
        self.assertEqual(same['status'],'closed_unknown')
        fresh=writer.claim_run(self.path,'SANDBOX','c'*32,self.actor,'manual',
            manual_authorized=True,plan_scope='ALL',plan_digest=self.plan_digest)
        self.assertTrue(fresh['claimed'])
        self.assertIsNone(writer.claim_interrupted_apply_chunk_recovery(self.path,self.request_id))
        self.assertIsNone(writer.claim_interrupted_append_chunk_recovery(self.path,self.request_id))
        with self.assertRaises(PermissionError):
            writer.load_append_only_resume_candidate(self.path,self.request_id,'writer-fixture')
        with self.assertRaises(RuntimeError):
            writer.prepare_partial_reconciliation(self.path,'SANDBOX','e'*32,
                '816c6424279bff220878b0c4',self.actor)

    def test_append_only_scope_is_closed_without_changing_its_result(self):
        raw=json.loads(self.result_raw);raw['plan_scope']='APPEND_ONLY'
        self.result_raw=json.dumps(raw,sort_keys=True)
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute('UPDATE google_writer_runs SET result_json=? WHERE request_id=?',
                        (self.result_raw,self.request_id))
        script=MockAppsScriptClose();script.marker=self.request_id
        result=writer.close_unknown_run(self.path,script,self.request_id,self.actor,self.close_id,self.reason)
        self.assertEqual(result['status'],'ADMIN_CLOSED_UNKNOWN')
        self.assertEqual(self.run_row(),('closed_unknown',self.finished,self.result_raw))
        self.assertEqual(script.sheet_writes,0)

    def test_lost_response_retains_hold_then_same_id_retry_finalizes(self):
        script=MockAppsScriptClose(timeout_once=True);script.marker=self.request_id
        with self.assertRaises(writer.ExecutionOutcomeUnknown):
            writer.close_unknown_run(self.path,script,self.request_id,self.actor,self.close_id,self.reason)
        self.assertEqual(self.run_row(),('outcome_unknown',self.finished,self.result_raw))
        status=writer.status(self.path,'SANDBOX',actor=self.actor)
        self.assertTrue(status['blocked'])
        queued=writer.claim_run(self.path,'SANDBOX','c'*32,self.actor,'manual',
            manual_authorized=True,plan_scope='ALL',plan_digest=writer._sha256_b64(b'new plan'))
        self.assertFalse(queued['claimed'])
        with closing(sqlite3.connect(self.path)) as con, con:
            self.assertEqual(con.execute('SELECT state FROM google_writer_run_closures WHERE request_id=?',
                                         (self.request_id,)).fetchone()[0],'prepared')
        result=writer.close_unknown_run(self.path,script,self.request_id,self.actor,self.close_id,self.reason)
        self.assertEqual(result['status'],'ADMIN_CLOSED_UNKNOWN')
        self.assertEqual(script.calls,2)
        self.assertEqual(script.sheet_writes,0)
        self.assertEqual(self.run_row(),('closed_unknown',self.finished,self.result_raw))
        with self.assertRaises(PermissionError):
            writer.prepare_admin_close_unknown(self.path,'SANDBOX','d'*32,
                self.request_id,self.actor,self.reason)

    def test_concurrent_double_submit_is_idempotent(self):
        script=MockAppsScriptClose();script.marker=self.request_id
        def close():
            return writer.close_unknown_run(self.path,script,self.request_id,self.actor,
                                            self.close_id,self.reason)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:close(),range(2)))
        self.assertTrue(all(item['status']=='ADMIN_CLOSED_UNKNOWN' for item in results))
        self.assertEqual(script.sheet_writes,0)
        with closing(sqlite3.connect(self.path)) as con, con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM google_writer_run_closures WHERE request_id=?',
                                         (self.request_id,)).fetchone()[0],1)
        self.assertEqual(self.run_row()[0],'closed_unknown')

    def test_wrong_state_or_reconciliation_intent_is_rejected(self):
        with self.assertRaises(RuntimeError):
            writer.prepare_admin_close_unknown(self.path,'SANDBOX',self.close_id,
                'f'*32,self.actor,self.reason)
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("UPDATE google_writer_runs SET status='partial' WHERE request_id=?",(self.request_id,))
        with self.assertRaises(RuntimeError):
            writer.prepare_admin_close_unknown(self.path,'SANDBOX',self.close_id,
                self.request_id,self.actor,self.reason)
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("UPDATE google_writer_runs SET status='outcome_unknown' WHERE request_id=?",(self.request_id,))
            con.execute('''INSERT INTO google_writer_run_reconciliations(
                reconciliation_id,request_id,environment,actor,request_fingerprint,evidence_digest,
                evidence_json,state,prepared_at,original_status,original_result_json,original_actor,
                original_trigger,original_revision,original_started_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                ('e'*32,self.request_id,'SANDBOX',self.actor,'f'*24,'g'*43,'{}','prepared',
                 datetime.now(timezone.utc).isoformat(),'outcome_unknown',self.result_raw,
                 'writer-fixture','manual',1,'2026-11-10T08:00:00+00:00'))
        with self.assertRaises(RuntimeError):
            writer.prepare_admin_close_unknown(self.path,'SANDBOX',self.close_id,
                self.request_id,self.actor,self.reason)

    def test_bad_receipt_cannot_release_lane(self):
        intent=writer.prepare_admin_close_unknown(self.path,'SANDBOX',self.close_id,
            self.request_id,self.actor,self.reason)
        with self.assertRaises(PermissionError):
            writer.finalize_admin_close_unknown(self.path,self.close_id,self.actor,{'status':'ADMIN_CLOSED_UNKNOWN'})
        self.assertEqual(self.run_row()[0],'outcome_unknown')
        self.assertEqual(intent['state'],'prepared')


class AdminCloseHttpPermissionTests(unittest.TestCase):
    def test_endpoint_requires_both_admin_and_writer_permissions(self):
        path='/api/admin/google-writer/close-unknown'
        self.assertEqual(auth_access.permission_key('POST',path),'google.writer.execute')
        source=Path(__file__).with_name('server.py').read_text(encoding='utf-8')
        start=source.index("if parsed.path == '/api/admin/google-writer/close-unknown':")
        end=source.index("if parsed.path in {'/api/google-writer/preview','/api/google-writer/apply'}:",start)
        route=source[start:end]
        self.assertIn("not permissions.get('admin.manage') or not permissions.get('google.writer.execute')",route)
        self.assertLess(route.index("not permissions.get('admin.manage')"),route.index('google_writer_client()'))
        self.assertIn("payload.get('confirmed') is not True",route)


class AdminCloseExecutionClientTests(unittest.TestCase):
    def test_signed_close_uses_additive_dispatcher_and_validates_receipt_digest(self):
        now=datetime(2026,11,10,10,0,tzinfo=timezone.utc)
        request_id='a'*32;close_id='b'*32
        digest=writer._sha256_b64(b'plan')
        evidence=writer._sha256_b64(b'evidence')
        reason=writer._sha256_b64(b'reason')
        receipt={'environment':'SANDBOX','scriptId':writer.IDENTITIES['SANDBOX'][0],
            'spreadsheetId':writer.IDENTITIES['SANDBOX'][1],'contract':writer.CONTRACT,
            'requestId':request_id,'status':'ADMIN_CLOSED_UNKNOWN','closeId':close_id,
            'planScope':'ALL','disposition':'OUTCOME_UNKNOWN_NOT_CONFIRMED',
            'evidenceDigest':evidence,'reasonDigest':reason,
            'runRecordDigest':writer._sha256_b64(b'Apps Script run record'),
            'closedAt':'2026-11-10T10:00:00.000Z','actor':'admin-fixture','idempotent':False}
        receipt['digest']=writer._close_receipt_digest(receipt)
        response={'done':True,'response':{'result':receipt}}
        captured={}
        class Response:
            def __enter__(self):return self
            def __exit__(self,*_):return False
            def read(self,_limit):return json.dumps(response).encode()
        def opener(request,timeout):
            captured['url']=request.full_url;captured['body']=json.loads(request.data)
            captured['timeout']=timeout;return Response()
        token={'environment':'SANDBOX','scopes':sorted(writer.PROJECT_SCOPES),
            'expires_at':now.timestamp()+3600,'access_token':'mock-only-token'}
        client=writer.ExecutionClient('SANDBOX','deployment-id-01234567890123456789',
            'M'*40,lambda _environment:token,configured=True,opener=opener,clock=lambda:now)
        result=client.invoke('close_unknown_run',request_id,'admin-fixture',trigger='manual',
            digest=digest,plan_scope='ALL',manual_authorized=True,close_id=close_id,
            close_evidence_digest=evidence,reason_digest=reason)
        self.assertEqual(captured['body']['function'],'pqmSandboxAllScopeExecution20261109')
        request=json.loads(captured['body']['parameters'][0]['payload'])
        self.assertEqual(request['action'],'close_unknown_run')
        self.assertEqual(request['requestId'],request_id)
        self.assertEqual(request['closeId'],close_id)
        self.assertEqual(result['status'],'ADMIN_CLOSED_UNKNOWN')
        self.assertEqual(result['disposition'],'OUTCOME_UNKNOWN_NOT_CONFIRMED')
        self.assertEqual(result['closeId'],close_id)
        self.assertNotIn('reason',result)

    def test_production_execution_client_rejects_admin_close_before_network(self):
        now=datetime(2026,11,10,10,0,tzinfo=timezone.utc)
        called=[]
        token={'environment':'PROD','scopes':sorted(writer.PROJECT_SCOPES),
            'expires_at':now.timestamp()+3600,'access_token':'mock-only-token'}
        client=writer.ExecutionClient('PROD','deployment-id-01234567890123456789',
            'M'*40,lambda _environment:token,configured=True,
            opener=lambda *_args,**_kwargs:called.append(True),clock=lambda:now)
        with self.assertRaises(ValueError):
            client.invoke('close_unknown_run','a'*32,'admin-fixture',trigger='manual',
                digest=writer._sha256_b64(b'plan'),plan_scope='ALL',manual_authorized=True,
                close_id='b'*32,close_evidence_digest=writer._sha256_b64(b'evidence'),
                reason_digest=writer._sha256_b64(b'reason'))
        self.assertEqual(called,[])


if __name__=='__main__':
    unittest.main()
