"""Render response-contract regressions for the Apps Script prewrite dispatcher."""
import base64
import datetime
import hashlib
import hmac
import io
import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import google_writer_execution as execution
import sandbox_runtime as runtime


ROOT=Path(__file__).resolve().parent
HISTORICAL_ID='b11433e8efb84b4492bf2df7c7c25908'
LEGACY_STAGE='LEGACY_V1_WRITEAHEAD_LIMIT_PROOF_V1'


def b64digest(value):
    return base64.urlsafe_b64encode(hashlib.sha256(value).digest()).decode().rstrip('=')


class PrewriteStageContractTests(unittest.TestCase):
    def setUp(self):
        inherited_path=os.environ.get('PATH','')
        configured_node=os.environ.get('PQM_NODE_EXECUTABLE')
        self.script,self.sheet,self.function=execution.IDENTITIES['SANDBOX']
        self.deployment='TEST_SANDBOX_DEPLOYMENT_0123456789'
        self.now=datetime.datetime.now(datetime.timezone.utc)
        env={'PQM_SANDBOX':'1','RENDER_SERVICE_ID':'srv-dalfd77f3r2c7392uub0',
            'PQM_SANDBOX_EXECUTION_READY':'1','PQM_SANDBOX_EXECUTION_DEPLOYMENT_ID':self.deployment,
            'PQM_SANDBOX_EDR_GOOGLE':'1','PATH':inherited_path}
        if configured_node:env['PQM_NODE_EXECUTABLE']=configured_node
        patch.dict(os.environ,env,clear=True).start()
        self.addCleanup(patch.stopall)
        self.network=Mock()
        patch.object(runtime.urllib.request,'build_opener',return_value=self.network).start()
        self.requests=[]
        self.response_mutator=None
        self.response_status='READY'
        self.network.open.side_effect=self._open
        self.token=lambda environment:{'environment':environment,'access_token':'MOCK_TOKEN',
            'scopes':sorted(execution.PROJECT_SCOPES),'expires_at':self.now.timestamp()+3600}
        self.client=execution.ExecutionClient('SANDBOX',self.deployment,'MOCK_SHARED_SECRET_'+'x'*32,
            self.token,configured=True,clock=lambda:self.now)

    def _open(self,request,timeout):
        self.requests.append(request)
        self.assertTrue(runtime._egress.active)
        runtime.outbound_audit('socket.getaddrinfo',(request.host,443,0,0,0))
        runtime.outbound_audit('urllib.Request',(request.full_url,request.data,dict(request.headers),request.get_method()))
        body=json.loads(request.data)
        self.assertEqual(body['function'],'pqmSandboxAllScopeExecution20261109')
        envelope=body['parameters'][0]
        raw=envelope['payload']
        expected=base64.urlsafe_b64encode(hmac.new(self.client.shared_secret.encode(),
            raw.encode(),hashlib.sha256).digest()).decode().rstrip('=')
        self.assertEqual(envelope['signature'],expected)
        message=json.loads(raw)
        result={key:message[key] for key in ('environment','scriptId','spreadsheetId','contract','requestId')}
        result.update(status=self.response_status,digest=message['expectedDigest'],planScope='APPEND_ONLY',
            chunkIndex=0,chunkId=message['chunkId'],chunkDigest=message['chunkDigest'],
            targetIdentityDigest=message['targetIdentityDigest'],prewriteStage=message['prewriteStage'],
            targetCount=len(message['targetIdentities']),targetCodeMatches=0,runMarkerMatches=0,
            writeAheadBytes=8649 if self.response_status=='READY' else 8000,checkpointMaxBytes=8000,
            proofType='LEGACY_V1_WRITEAHEAD_OVERSIZE' if self.response_status=='READY' else 'APPS_SCRIPT_LAST_ERROR',
            runRecordDigest=self.client_digest(),reasonCodes=[] if self.response_status=='READY' else ['MANIFEST_NOT_OVERSIZED'],
            readOnly=True)
        if message['prewriteStage']==LEGACY_STAGE and self.response_status=='READY':
            result.update(prewriteStage='append_inflight_save',
                legacyManifestProjectionDigest=message['legacyManifestProjectionDigest'])
        if self.response_mutator:
            self.response_mutator(result,message)
        # This is the Apps Script Execution API's done/response/result envelope.
        return io.BytesIO(json.dumps({'done':True,'response':{'result':result}}).encode())

    def client_digest(self):
        return b64digest(b'mock Apps Script run record')

    def request_kwargs(self,*,legacy=True,request_id=HISTORICAL_ID):
        rows=[{'tab':'ФОП' if i<21 else 'ЮО','row':i+2,'code':str(i+1).zfill(10),
            'formulaA':'='+('x'*220)} for i in range(25)] if legacy else None
        identities=([{'tab':row['tab'],'code':row['code']} for row in rows] if rows else
            [{'tab':'ФОП','code':'12345678'}])
        identity_digest=b64digest(json.dumps([[item['tab'],item['code']] for item in identities],
            ensure_ascii=False,separators=(',',':')).encode())
        projection_digest=(b64digest(json.dumps([{'code':row['code'],'formulaA':row['formulaA'],
            'row':row['row'],'tab':row['tab']} for row in rows],ensure_ascii=False,sort_keys=True,
            separators=(',',':')).encode()) if rows else None)
        return {'action':'prewrite_close_preflight','request_id':request_id,'actor':'sandbox-admin',
            'trigger':'manual','manual_authorized':True,'digest':self.client_digest(),
            'plan_scope':'APPEND_ONLY','chunk_id':'c'*32,'chunk_digest':self.client_digest(),
            'plan_id':request_id,'chunk_index':0,
            'prewrite_stage':LEGACY_STAGE if legacy else 'append_prewrite_guard',
            'target_identity_digest':identity_digest,'target_identities':identities,
            'legacy_manifest_rows':rows,'legacy_manifest_projection_digest':projection_digest}

    def invoke(self,**overrides):
        kwargs=self.request_kwargs(**overrides)
        return self.client.invoke(**kwargs)

    def test_render_egress_accepts_exact_legacy_dispatcher_response_read_only(self):
        result=self.invoke()
        self.assertEqual(result['status'],'READY')
        self.assertEqual(result['plan_binding'],'PASS')
        self.assertEqual(result['chunk_binding'],'PASS')
        self.assertEqual(result['manifest_binding'],'PASS')
        self.assertTrue(result['read_only'])
        self.assertEqual((result['sqlite_writes'],result['sheets_writes'],result['properties_writes']),(0,0,0))
        body=json.loads(self.requests[0].data)
        message=json.loads(body['parameters'][0]['payload'])
        self.assertEqual(message['action'],'prewrite_close_preflight')
        self.assertEqual(message['spreadsheetId'],self.sheet)
        self.assertEqual(message['prewriteStage'],LEGACY_STAGE)

    def test_legacy_stage_or_proof_mismatch_never_becomes_ready(self):
        cases=(
            ({'prewriteStage':'wrong'},'APPS_SCRIPT_PREFLIGHT_PREWRITE_STAGE'),
            ({'proofType':'APPS_SCRIPT_LAST_ERROR'},'APPS_SCRIPT_LEGACY_SIZE_PROOF_INVALID'),
            ({'writeAheadBytes':8000},'APPS_SCRIPT_LEGACY_SIZE_PROOF_INVALID'),
            ({'checkpointMaxBytes':8192},'APPS_SCRIPT_LEGACY_SIZE_PROOF_INVALID'),
            ({'legacyManifestProjectionDigest':'wrong'},'APPS_SCRIPT_LEGACY_SIZE_PROOF_INVALID'),
            ({'reasonCodes':None},'APPS_SCRIPT_PREFLIGHT_REASON_CODES'),
        )
        for changes,expected_code in cases:
            with self.subTest(changes=changes):
                self.response_mutator=lambda result,_message,changes=changes:result.update(changes)
                with self.assertRaises(execution.ExecutionPreflightError) as caught:
                    self.invoke()
                self.assertEqual(caught.exception.safe_error['diagnostic_code'],expected_code)
        self.response_mutator=lambda result,_message:result.pop('prewriteStage',None)
        with self.assertRaises(execution.ExecutionPreflightError) as caught:
            self.invoke()
        self.assertEqual(caught.exception.safe_error['diagnostic_code'],'APPS_SCRIPT_PREFLIGHT_PREWRITE_STAGE')

    def test_missing_proof_fields_and_nonlegacy_stage_remain_fail_closed(self):
        for field,expected_code in (
                ('writeAheadBytes','APPS_SCRIPT_PREFLIGHT_WRITE_AHEAD_BYTES'),
                ('checkpointMaxBytes','APPS_SCRIPT_PREFLIGHT_CHECKPOINT_MAX_BYTES'),
                ('reasonCodes','APPS_SCRIPT_PREFLIGHT_REASON_CODES'),
                ('legacyManifestProjectionDigest','APPS_SCRIPT_LEGACY_SIZE_PROOF_INVALID')):
            with self.subTest(field=field):
                self.response_mutator=lambda result,_message,field=field:result.pop(field,None)
                with self.assertRaises(execution.ExecutionPreflightError) as caught:
                    self.invoke()
                self.assertEqual(caught.exception.safe_error['diagnostic_code'],expected_code)
        self.response_mutator=lambda result,_message:result.update(prewriteStage='append_inflight_save')
        with self.assertRaises(execution.ExecutionPreflightError) as caught:
            self.invoke(legacy=False,request_id='a'*32)
        self.assertEqual(caught.exception.safe_error['diagnostic_code'],'APPS_SCRIPT_PREFLIGHT_PREWRITE_STAGE')

    def test_subject_matter_blocked_remains_blocked(self):
        self.response_status='BLOCKED'
        self.response_mutator=lambda result,message:result.update(status='BLOCKED',
            prewriteStage='append_inflight_save',proofType='LEGACY_V1_WRITEAHEAD_OVERSIZE',
            writeAheadBytes=8649,checkpointMaxBytes=8000,
            legacyManifestProjectionDigest=message['legacyManifestProjectionDigest'],
            targetCodeMatches=1,reasonCodes=['TARGET_CODES_PRESENT'])
        result=self.invoke()
        self.assertEqual(result['status'],'BLOCKED')
        self.assertEqual(result['reason_codes'],['TARGET_CODES_PRESENT'])
        self.response_mutator=lambda result,message:result.update(status='BLOCKED',
            prewriteStage='append_inflight_save',proofType='LEGACY_V1_WRITEAHEAD_OVERSIZE',
            writeAheadBytes=8649,checkpointMaxBytes=8000,runRecordDigest=None,
            legacyManifestProjectionDigest=message['legacyManifestProjectionDigest'],
            targetCodeMatches=1,reasonCodes=['TARGET_CODES_PRESENT'])
        with self.assertRaises(execution.ExecutionPreflightError) as caught:
            self.invoke()
        self.assertEqual(caught.exception.safe_error['diagnostic_code'],'APPS_SCRIPT_LEGACY_SIZE_PROOF_INVALID')

    def test_quick_runner_executes_the_real_apps_script_dispatcher_mock(self):
        if os.name=='nt':
            self.skipTest('Windows runs the Node dispatcher test directly; nested Node startup is Linux CI only')
        configured_node=os.environ.get('PQM_NODE_EXECUTABLE')
        node=(configured_node if configured_node and Path(configured_node).is_file() else shutil.which('node'))
        self.assertIsNotNone(node,'Node.js is required for the dispatcher half of this integration check')
        test_path=ROOT/'scripts/pqm-google-writer/mirror-alignment/sandbox/prewrite-stage-contract.test.cjs'
        completed=subprocess.run([node,'--test',str(test_path)],cwd=ROOT,text=True,
            stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=30)
        self.assertEqual(completed.returncode,0,completed.stdout)
        self.assertIn('Apps Script v21 dispatcher returns the concrete legacy proof stage',completed.stdout)


if __name__=='__main__':
    unittest.main()
