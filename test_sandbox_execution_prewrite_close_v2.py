import base64
import hashlib
import hmac
import json
import os
import unittest
import urllib.request
from unittest.mock import patch

import google_writer_execution as execution
import sandbox_runtime as runtime
from test_google_writer_execution import NOW


RUN_ID='b11433e8efb84b4492bf2df7c7c25908'
SECRET='MOCK_SHARED_SECRET_'+'x'*32


def digest(raw):
    return base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).decode().rstrip('=')


def close_request(test, **changes):
    rows=[{'tab':'ФОП' if i<21 else 'ЮО','row':i+2,'code':str(i+1).zfill(10),
           'formulaA':'='+('x'*220)} for i in range(25)]
    projection=[{'code':row['code'],'formulaA':row['formulaA'],'row':row['row'],'tab':row['tab']}
                for row in rows]
    identities=[{'tab':row['tab'],'code':row['code']} for row in rows]
    identity_digest=digest(json.dumps([[row['tab'],row['code']] for row in rows],
        ensure_ascii=False,separators=(',',':')).encode())
    projection_digest=digest(json.dumps(projection,ensure_ascii=False,sort_keys=True,
        separators=(',',':')).encode())
    now=int(NOW.timestamp())
    payload={'environment':'SANDBOX','scriptId':test.script,'spreadsheetId':test.sheet,
        'contract':execution.CONTRACT,'action':'close_prewrite_failure','requestId':RUN_ID,
        'actor':'sandbox-admin','trigger':'manual','issuedAt':now,'expiresAt':now+300,
        'expectedDigest':test.plan_digest,'planScope':'APPEND_ONLY','closeId':'c'*32,
        'closeEvidenceDigest':digest(b'close evidence'),'reasonDigest':digest(b'reason'),
        'chunkIndex':0,'prewriteStage':'LEGACY_V1_WRITEAHEAD_LIMIT_PROOF_V1',
        'targetIdentityDigest':identity_digest,'targetIdentities':identities,
        'chunkId':'d'*32,'chunkDigest':test.chunk_digest,'planId':RUN_ID,
        'legacyManifestRows':rows,'legacyManifestProjectionDigest':projection_digest}
    payload.update(changes)
    raw=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':'))
    signature=base64.urlsafe_b64encode(hmac.new(SECRET.encode(),raw.encode(),hashlib.sha256).digest()).decode().rstrip('=')
    body={'function':'pqmSandboxAllScopeExecution20261109','devMode':False,
          'parameters':[{'payload':raw,'signature':signature}]}
    return urllib.request.Request('https://script.googleapis.com/v1/scripts/'+test.deployment+':run',
        data=json.dumps(body).encode(),method='POST',headers={'Authorization':'Bearer MOCK_TOKEN',
        'Content-Type':'application/json'})


class SandboxPrewriteCloseV22EgressTests(unittest.TestCase):
    def setUp(self):
        self.script,self.sheet,_=execution.IDENTITIES['SANDBOX']
        self.deployment='TEST_SANDBOX_DEPLOYMENT_0123456789'
        self.plan_digest=digest(b'plan')
        self.chunk_digest=digest(b'chunk')
        self.env={'PQM_SANDBOX':'1','RENDER_SERVICE_ID':'srv-dalfd77f3r2c7392uub0',
            'PQM_SANDBOX_EXECUTION_READY':'1','PQM_SANDBOX_EXECUTION_DEPLOYMENT_ID':self.deployment,
            'PQM_SANDBOX_EDR_GOOGLE':'1'}
        self.clean=patch.dict(os.environ,self.env,clear=True);self.clean.start()
        self.addCleanup(self.clean.stop)

    def validate(self,request,**overrides):
        values={'environment':'SANDBOX','script_id':self.script,'spreadsheet_id':self.sheet,
                'deployment_id':self.deployment}
        values.update(overrides)
        return runtime.validate_execution_request(request,**values)

    def test_exact_25_row_closure_contract_passes_the_all_scope_egress_filter(self):
        request=close_request(self)
        body=json.loads(request.data);payload=json.loads(body['parameters'][0]['payload'])
        self.assertEqual(self.validate(request),'script.googleapis.com')
        self.assertEqual(payload['action'],'close_prewrite_failure')
        self.assertEqual(payload['planScope'],'APPEND_ONLY')
        self.assertEqual(payload['requestId'],RUN_ID)
        self.assertEqual(payload['planId'],RUN_ID)
        self.assertEqual(payload['spreadsheetId'],self.sheet)
        self.assertEqual(len(payload['legacyManifestRows']),25)
        self.assertEqual(len(payload['legacyManifestProjectionDigest']),43)

    def test_closure_rejects_wrong_handler_environment_permissions_bindings_and_proof(self):
        valid=close_request(self)
        body=json.loads(valid.data)
        cases=(
            ('legacy_handler',{'function':'pqmSandboxExecution'}),
            ('production',{'environment':'PROD'}),
            ('scheduled',{'trigger':'scheduled'}),
            ('wrong_scope',{'planScope':'ALL'}),
            ('bad_request',{'requestId':'not-a-request-id'}),
            ('bad_close_id',{'closeId':'bad'}),
            ('bad_plan_digest',{'expectedDigest':'bad'}),
            ('bad_close_evidence',{'closeEvidenceDigest':'bad'}),
            ('bad_reason',{'reasonDigest':'bad'}),
            ('bad_chunk_id',{'chunkId':'bad'}),
            ('bad_chunk_digest',{'chunkDigest':'bad'}),
            ('wrong_plan',{'planId':'e'*32}),
            ('wrong_chunk',{'chunkIndex':1}),
            ('bad_target_digest',{'targetIdentityDigest':'bad'}),
            ('bad_identity',{'targetIdentities':[{'tab':'PROD','code':'12345678'}]}),
            ('duplicate_identity',{'targetIdentities':[{'tab':'ФОП','code':'0000000001'},
                {'tab':'ЮО','code':'0000000001'}]}),
            ('missing_manifest',{'legacyManifestRows':None}),
            ('missing_projection_digest',{'legacyManifestProjectionDigest':None}),
            ('extra_field',{'unexpected':'value'}),
        )
        for name,changes in cases:
            with self.subTest(name=name):
                request=close_request(self,**changes)
                if 'function' in changes:
                    changed=json.loads(request.data);changed['function']=changes['function']
                    request=urllib.request.Request(request.full_url,data=json.dumps(changed).encode(),
                        headers=request.headers,method='POST')
                with self.assertRaises(runtime.SandboxExecutionPreflightRejected):self.validate(request)
        with self.assertRaises(runtime.SandboxExecutionPreflightRejected):
            self.validate(valid,deployment_id='OTHER_SANDBOX_DEPLOYMENT_0123456789')
        with self.assertRaises(runtime.SandboxExecutionPreflightRejected):
            self.validate(valid,spreadsheet_id='OTHER_SANDBOX_SPREADSHEET_0123456789')

    def test_other_mutating_and_recovery_actions_do_not_inherit_closure_allowance(self):
        for action in ('apply','resume_check','recover_apply_chunk','recover_append_chunk'):
            with self.subTest(action=action):
                request=close_request(self,action=action)
                with self.assertRaises(runtime.SandboxExecutionPreflightRejected):self.validate(request)
        self.assertEqual(runtime.SANDBOX_LEGACY_WRITER_REQUEST_IDS,frozenset({'592128d9837d4b71bbeb330ef8aabf4b'}))


if __name__=='__main__':
    unittest.main()
