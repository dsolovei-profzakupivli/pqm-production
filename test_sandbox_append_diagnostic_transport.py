"""The APPEND diagnostic is routed only to the additive read-only entrypoint."""
import base64
import hashlib
import io
import json
import os
import unittest
from unittest.mock import patch
import urllib.request

import google_writer_execution as execution
import sandbox_runtime as runtime
from test_google_writer_execution import NOW


class AppendDiagnosticTransportTests(unittest.TestCase):
    def setUp(self):
        self.deployment='TEST_SANDBOX_DEPLOYMENT_0123456789'
        patch.dict(os.environ,{'PQM_SANDBOX':'1','RENDER_SERVICE_ID':'srv-dalfd77f3r2c7392uub0',
            'PQM_SANDBOX_EXECUTION_READY':'1','PQM_SANDBOX_EXECUTION_DEPLOYMENT_ID':self.deployment,
            'PQM_SANDBOX_EDR_GOOGLE':'1'},clear=True).start()
        self.addCleanup(patch.stopall)
        self.secret='OFFLINE_SECRET_'+'x'*32
        self.token=lambda env:{'environment':env,'access_token':'OFFLINE_TOKEN',
            'scopes':sorted(execution.PROJECT_SCOPES),'expires_at':NOW.timestamp()+3600}
        self.calls=[]
        self.network=patch.object(runtime.urllib.request,'build_opener').start().return_value
        self.client=execution.ExecutionClient('SANDBOX',self.deployment,self.secret,self.token,
            configured=True,clock=lambda:NOW)
        self.client.opener=self.fake_open
        self.response_mutator=None

    def fake_open(self,request,timeout):
        self.calls.append(request)
        payload=json.loads(json.loads(request.data)['parameters'][0]['payload'])
        self.assertEqual(request.full_url,
            'https://script.googleapis.com/v1/scripts/'+self.deployment+':run')
        self.assertEqual(json.loads(request.data)['function'],'pqmSandboxAppendDiagnostic20261112')
        result={key:payload[key] for key in ('environment','scriptId','spreadsheetId','contract','requestId')}
        if payload.get('diagnosticMode')=='audit':
            rows=payload['auditTargets']
            result.update(status='AUDITED',diagnosticMode='audit',planScope='APPEND_ONLY',
                digest=payload['expectedDigest'],detailsDigest=payload['detailsDigest'],
                fullPlanDigest=payload['fullPlanDigest'],sourceDigest=payload['sourceDigest'],
                planId=payload['planId'],auditTargetsDigest=payload['auditTargetsDigest'],
                counts={'planned':len(rows),'confirmed':25,'missing':len(rows)-25,
                    'conflict':0,'unverified':0,'remaining':len(rows)-25},reasonCodes=[],readOnly=True)
            if self.response_mutator: self.response_mutator(result)
            return io.BytesIO(json.dumps({'done':True,'response':{'result':result}}).encode())
        result.update(status='DIAGNOSED',planScope='APPEND_ONLY',digest=payload['expectedDigest'],
            detailsDigest=payload['detailsDigest'],fullPlanDigest=payload['fullPlanDigest'],
            sourceDigest=payload['sourceDigest'],chunkId=payload['chunkId'],
            chunkDigest=payload['chunkDigest'],planId=payload['planId'],chunkIndex=0,
            counts={'planned':payload['totalAppendCount'],'confirmed':25,'missing':251,
                'conflict':0,'unverified':0,'remaining':251},reasonCodes=[],manifestBinding='PASS',
            firstChunkRecoveryEvidence=True,readOnly=True)
        if self.response_mutator:
            self.response_mutator(result)
        return io.BytesIO(json.dumps({'done':True,'response':{'result':result}}).encode())

    def invoke(self):
        targets=[]
        for i in range(276):
            targets.append({'tab':'ФОП' if i%2==0 else 'ЮО','code':f'{10000000+i:08d}',
                'row':2+(i//2)})
        return self.client.invoke('diagnose_append_plan','d'*32,'sandbox-admin',trigger='manual',
            digest=self.digest('append'),plan_scope='APPEND_ONLY',manual_authorized=True,
            chunk_index=0,chunk_id='c'*32,chunk_digest=self.digest('chunk'),plan_id='d'*32,
            details_digest=self.digest('details'),full_plan_digest=self.digest('full'),
            source_digest=self.digest('source'),total_append_count=276,target_identities=targets)

    def invoke_audit(self):
        rows=[['ФОП' if i%2==0 else 'ЮО',f'{10000000+i:08d}',2+i//2,self.digest(f'row-{i}')]
            for i in range(276)]
        targets_digest=self.digest(execution._canonical_json(rows))
        return self.client.invoke('diagnose_append_plan','d'*32,'sandbox-admin',trigger='manual',
            digest=self.digest('append'),plan_scope='APPEND_ONLY',manual_authorized=True,
            plan_id='d'*32,details_digest=self.digest('details'),full_plan_digest=self.digest('full'),
            source_digest=self.digest('source'),total_append_count=276,diagnostic_mode='audit',
            audit_targets=rows,audit_targets_digest=targets_digest)

    @staticmethod
    def digest(value):
        return base64.urlsafe_b64encode(hashlib.sha256(value.encode()).digest()).decode().rstrip('=')

    def test_signed_diagnostic_uses_only_additive_endpoint_and_returns_aggregates(self):
        result=self.invoke()
        self.assertEqual(result['counts'],{'planned':276,'confirmed':25,'missing':251,
            'conflict':0,'unverified':0,'remaining':251})
        self.assertTrue(result['first_chunk_recovery_evidence'])
        request=self.calls[0]
        self.assertEqual(runtime.validate_execution_request(request,'SANDBOX',
            execution.IDENTITIES['SANDBOX'][0],execution.IDENTITIES['SANDBOX'][1],self.deployment),
            'script.googleapis.com')

    def test_egress_rejects_diagnostic_payload_mutation_and_wrong_function(self):
        self.invoke();original=self.calls[0]
        body=json.loads(original.data);envelope=body['parameters'][0];payload=json.loads(envelope['payload'])
        payload['targetIdentities'][0]['row']=1
        envelope['payload']=json.dumps(payload,separators=(',',':'))
        envelope['signature']=base64.urlsafe_b64encode(__import__('hmac').new(
            self.secret.encode(),envelope['payload'].encode(),hashlib.sha256).digest()).decode().rstrip('=')
        mutated=urllib.request.Request(original.full_url,data=json.dumps(body).encode(),
            headers=original.headers,method='POST')
        with self.assertRaises(runtime.SandboxExecutionPreflightRejected):
            runtime.validate_execution_request(mutated,'SANDBOX',execution.IDENTITIES['SANDBOX'][0],
                execution.IDENTITIES['SANDBOX'][1],self.deployment)
        body=json.loads(original.data);body['function']='pqmSandboxAllScopeExecution20261109'
        wrong=urllib.request.Request(original.full_url,data=json.dumps(body).encode(),
            headers=original.headers,method='POST')
        with self.assertRaises(runtime.SandboxExecutionPreflightRejected):
            runtime.validate_execution_request(wrong,'SANDBOX',execution.IDENTITIES['SANDBOX'][0],
                execution.IDENTITIES['SANDBOX'][1],self.deployment)

    def test_response_cannot_claim_first_chunk_recovery_with_inconsistent_counts(self):
        self.response_mutator=lambda result: result['counts'].update(confirmed=24,missing=252,remaining=252)
        with self.assertRaisesRegex(execution.ExecutionPreflightError,'status was inconsistent'):
            self.invoke()
        self.assertEqual(len(self.calls),1)

    def test_audit_page_is_signed_and_egress_bound_without_recovery_manifest(self):
        result=self.invoke_audit()
        self.assertEqual(result['counts']['confirmed'],25)
        raw=json.loads(self.calls[-1].data)['parameters'][0]['payload']
        self.assertLessEqual(len(raw.encode('utf-16-le'))//2,32768)
        payload=json.loads(raw)
        self.assertEqual(len(payload['auditTargets']),276)
        self.assertEqual(payload['diagnosticMode'],'audit')
        self.assertNotIn('chunkDigest',payload)
        self.assertEqual(runtime.validate_execution_request(self.calls[-1],'SANDBOX',
            execution.IDENTITIES['SANDBOX'][0],execution.IDENTITIES['SANDBOX'][1],self.deployment),
            'script.googleapis.com')
        body=json.loads(self.calls[-1].data);envelope=body['parameters'][0];payload['auditTargets'][0][2]=1
        envelope['payload']=json.dumps(payload,ensure_ascii=False,separators=(',',':'))
        envelope['signature']=base64.urlsafe_b64encode(__import__('hmac').new(
            self.secret.encode(),envelope['payload'].encode(),hashlib.sha256).digest()).decode().rstrip('=')
        mutated=urllib.request.Request(self.calls[-1].full_url,data=json.dumps(body).encode(),
            headers=self.calls[-1].headers,method='POST')
        with self.assertRaises(runtime.SandboxExecutionPreflightRejected):
            runtime.validate_execution_request(mutated,'SANDBOX',execution.IDENTITIES['SANDBOX'][0],
                execution.IDENTITIES['SANDBOX'][1],self.deployment)


if __name__=='__main__':
    unittest.main()
