"""Offline regressions for the real SANDBOX scoped Execution transport."""
import io
import base64
import hashlib
import json
import os
import stat
import tempfile
import unittest
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import google_writer_execution as execution
import sandbox_runtime as runtime
from test_google_writer_execution import NOW


class SandboxExecutionTransportTests(unittest.TestCase):
    def setUp(self):
        self.script, self.sheet, self.function = execution.IDENTITIES['SANDBOX']
        self.deployment = 'TEST_SANDBOX_DEPLOYMENT_0123456789'
        self.env = {'PQM_SANDBOX':'1','RENDER_SERVICE_ID':'srv-dalfd77f3r2c7392uub0',
            'PQM_SANDBOX_EXECUTION_READY':'1','PQM_SANDBOX_EXECUTION_DEPLOYMENT_ID':self.deployment,
            'PQM_SANDBOX_EDR_GOOGLE':'1'}
        self.addCleanup(patch.stopall)
        patch.dict(os.environ,self.env,clear=True).start()
        self.token = lambda env: {'environment':env,'access_token':'OFFLINE_TOKEN',
            'scopes':sorted(execution.PROJECT_SCOPES),'expires_at':NOW.timestamp()+3600}
        self.client = execution.ExecutionClient('SANDBOX',self.deployment,'OFFLINE_SECRET_'+'x'*32,
            self.token,configured=True,clock=lambda:NOW)
        self.preview_digest=base64.urlsafe_b64encode(hashlib.sha256(b'PQM synthetic Preview digest').digest()).decode().rstrip('=')
        self.append_only_digest=base64.urlsafe_b64encode(hashlib.sha256(b'PQM synthetic APPEND_ONLY digest').digest()).decode().rstrip('=')
        self.calls = []
        self.network = patch.object(runtime.urllib.request,'build_opener').start().return_value
        self.network.open.side_effect = self.fake_open

    def fake_open(self, request, timeout):
        self.calls.append(request)
        self.assertTrue(runtime._egress.active)
        runtime.outbound_audit('socket.getaddrinfo',(request.host,443,0,0,0))
        runtime.outbound_audit('urllib.Request',(request.full_url,request.data,dict(request.headers),request.get_method()))
        if request.host == 'oauth2.googleapis.com':
            return io.BytesIO(json.dumps({'access_token':'OFFLINE_TOKEN','expires_in':3600}).encode())
        body=json.loads(request.data)
        message=json.loads(body['parameters'][0]['payload'])
        result={k:message[k] for k in ('environment','scriptId','spreadsheetId','contract','requestId')}
        status={'preview':'PREVIEW','apply':'COMPLETE',
            'reconcile_partial':'RECONCILED_PARTIAL'}[message['action']]
        counts={'append':0,'update':0,'conflict':0,'error':0}
        result.update(status=status,digest=self.preview_digest,counts=counts)
        if message['action']=='preview':
            result['planDetails']={'version':1,'environment':'SANDBOX',
                'plan_digest':self.preview_digest,'append_only_digest':self.append_only_digest,
                'counts':counts,'appends':[],'updates':[],'conflicts':[],'errors':[]}
        if message['action']=='apply':
            result.update(chunkIndex=message['chunkIndex'],nextChunk=message['chunkIndex']+1,
                more=False,phase='append',checkpointDigest=self.preview_digest,
                planScope=message.get('planScope','ALL'),chunkId=message.get('chunkId'),
                chunkDigest=message.get('chunkDigest'),planId=message.get('planId'))
        if message['action']=='reconcile_partial':
            evidence_raw=json.dumps(message['evidence'],ensure_ascii=False,sort_keys=True,separators=(',',':'))
            evidence_digest=base64.urlsafe_b64encode(hashlib.sha256(evidence_raw.encode('utf-8')).digest()).decode().rstrip('=')
            result.update(reconciliationId=message['reconciliationId'],
                requestFingerprint=message['requestFingerprint'],evidenceDigest=evidence_digest)
        return io.BytesIO(json.dumps({'done':True,'response':{'result':result}}).encode())

    def request(self):
        self.client.invoke('preview','a'*32,'uo')
        return self.calls.pop()

    def all_apply_binding(self, request_id, chunk_index):
        return {'manual_authorized':True,'digest':self.preview_digest,'chunk_index':chunk_index,
            'chunk_id':f'{chunk_index + 1:032x}','chunk_digest':self.append_only_digest,
            'plan_id':request_id,'chunk_phase':'append','chunk_added_at':'2026-11-09T12:00:00+02:00',
            'chunk_details_digest':self.append_only_digest}

    def validate(self, request, **overrides):
        values=dict(environment='SANDBOX',script_id=self.script,spreadsheet_id=self.sheet,deployment_id=self.deployment)
        values.update(overrides)
        return runtime.validate_execution_request(request,**values)

    def test_default_adapter_preview_real_scoped_guard_no_apply_or_receipts(self):
        result=self.client.invoke('preview','a'*32,'uo')
        self.assertEqual(result['status'],'PREVIEW')
        self.assertEqual(result['digest'],self.preview_digest)
        self.assertEqual(len(self.calls),1)
        message=json.loads(json.loads(self.calls[0].data)['parameters'][0]['payload'])
        self.assertEqual(message['action'],'preview')
        self.assertFalse(runtime._egress.active)
        self.assertIsNone(runtime._egress.execution_identity)
        self.assertNotIn('OFFLINE_TOKEN',json.dumps(result))

    def test_preview_ticket_and_apply_preserve_canonical_base64url_digest(self):
        preview=self.client.invoke('preview','a'*32,'uo')
        ticket=execution.preview_ticket(self.client,'a'*32,'uo',preview['digest'])
        verified=execution.verify_ticket(self.client,ticket,'uo')
        self.assertEqual(verified['digest'],self.preview_digest)
        self.client.invoke('apply','b'*32,'uo',**(self.all_apply_binding('b'*32,0)|{'digest':verified['digest']}))
        self.assertEqual(json.loads(self.calls[-1].data)['function'],
            'pqmSandboxAllScopeExecution20261109')
        message=json.loads(json.loads(self.calls[-1].data)['parameters'][0]['payload'])
        self.assertEqual(message['expectedDigest'],self.preview_digest)
        self.assertEqual(message['chunkIndex'],0)
        self.assertEqual(len(self.calls),2)

    def test_apply_checkpoint_receipt_is_bound_to_digest_and_chunk_index(self):
        result=self.client.invoke('apply','b'*32,'uo',**(self.all_apply_binding('b'*32,7)|
            {'expected_checkpoint_digest':self.preview_digest}))
        payload=json.loads(json.loads(self.calls[-1].data)['parameters'][0]['payload'])
        self.assertEqual(payload['chunkIndex'],7)
        self.assertEqual(payload['expectedDigest'],self.preview_digest)
        self.assertEqual((result['chunkIndex'],result['nextChunk'],result['more']),(7,8,False))

        original=self.network.open.side_effect
        def wrong_receipt(request,timeout):
            response=original(request,timeout)
            body=json.loads(response.getvalue())
            body['response']['result']['chunkIndex']=8
            return io.BytesIO(json.dumps(body).encode())
        self.network.open.side_effect=wrong_receipt
        with self.assertRaisesRegex(execution.ExecutionOutcomeUnknown,'Invalid Apply checkpoint receipt'):
            self.client.invoke('apply','c'*32,'uo',
                expected_checkpoint_digest=self.preview_digest,**self.all_apply_binding('c'*32,2))
        self.assertEqual(self.network.open.call_count,2,'invalid receipt is not retried')

    def test_receipt_ticket_and_apply_reject_noncanonical_sha256_digests(self):
        alphabet='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'
        final=alphabet.index(self.preview_digest[-1])
        noncanonical=self.preview_digest[:-1]+alphabet[final+1]
        invalid=(None, 123, 'a'*64, self.preview_digest+'=', self.preview_digest[:-1],
                 self.preview_digest[:-1]+'$', noncanonical)
        for index,digest in enumerate(invalid):
            with self.subTest(digest_kind=type(digest).__name__,index=index):
                self.preview_digest=digest
                with self.assertRaisesRegex(execution.ExecutionOutcomeUnknown,'Invalid Preview receipt'):
                    self.client.invoke('preview',f'{index+1:032x}','uo')
                ticket=execution.preview_ticket(self.client,f'{index+1:032x}','uo',digest)
                with self.assertRaisesRegex(ValueError,'Reviewed Preview ticket is invalid or expired'):
                    execution.verify_ticket(self.client,ticket,'uo')
                with self.assertRaisesRegex(ValueError,'Reviewed Preview digest required'):
                    self.client.invoke('apply',f'{index+1:032x}','uo',digest=digest)
        self.assertEqual(len(self.calls),len(invalid))

    def test_sandbox_egress_guard_accepts_only_canonical_apply_digest(self):
        request=self.request()
        body=json.loads(request.data)
        envelope=body['parameters'][0]
        payload=json.loads(envelope['payload'])
        body['function']='pqmSandboxAllScopeExecution20261109'
        payload.update(action='apply',expectedDigest=self.preview_digest,planScope='ALL',
            chunkId='d'*32,chunkDigest=self.append_only_digest,planId='a'*32,
            chunkPhase='append',chunkAddedAt='2026-11-09T12:00:00+02:00',
            chunkDetailsDigest=self.append_only_digest)
        payload['chunkIndex']=0
        envelope['payload']=json.dumps(payload)
        accepted=urllib.request.Request(request.full_url,data=json.dumps(body).encode(),headers=request.headers,method='POST')
        self.assertEqual(self.validate(accepted),'script.googleapis.com')
        payload['requestId']='592128d9837d4b71bbeb330ef8aabf4b'
        envelope['payload']=json.dumps(payload)
        historical=urllib.request.Request(request.full_url,data=json.dumps(body).encode(),headers=request.headers,method='POST')
        with self.assertRaisesRegex(RuntimeError,'Sandbox execution envelope is not approved'):
            self.validate(historical)
        payload['requestId']='a'*32
        envelope['payload']=json.dumps(payload)
        envelope['payload']='[]'
        malformed=urllib.request.Request(request.full_url,data=json.dumps(body).encode(),headers=request.headers,method='POST')
        with self.assertRaisesRegex(RuntimeError,'Sandbox execution envelope is not approved'):
            self.validate(malformed)
        envelope['payload']=json.dumps(payload)
        alphabet='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'
        final=alphabet.index(self.preview_digest[-1])
        invalid=(self.preview_digest+'=',self.preview_digest[:-1]+'$',
                 self.preview_digest[:-1]+alphabet[final+1],'a'*64)
        for digest in invalid:
            with self.subTest(digest=digest):
                payload['expectedDigest']=digest
                envelope['payload']=json.dumps(payload)
                changed=urllib.request.Request(request.full_url,data=json.dumps(body).encode(),headers=request.headers,method='POST')
                with self.assertRaisesRegex(RuntimeError,'Sandbox execution envelope is not approved'):
                    self.validate(changed)
        for invalid_index in (None, -1, 500, True, '0'):
            with self.subTest(chunk_index=invalid_index):
                payload['expectedDigest']=self.preview_digest
                if invalid_index is None:
                    payload.pop('chunkIndex',None)
                else:
                    payload['chunkIndex']=invalid_index
                envelope['payload']=json.dumps(payload)
                changed=urllib.request.Request(request.full_url,data=json.dumps(body).encode(),headers=request.headers,method='POST')
                with self.assertRaisesRegex(RuntimeError,'Sandbox execution envelope is not approved'):
                    self.validate(changed)

    def test_historical_profile_request_cannot_route_to_new_all_scope_entrypoint(self):
        request_id='592128d9837d4b71bbeb330ef8aabf4b'
        with self.assertRaisesRegex(ValueError,'Historical reconciliation request'):
            self.client.invoke('apply',request_id,'sandbox-admin',digest=self.preview_digest,
                manual_authorized=True,chunk_id='c'*32,chunk_digest=self.append_only_digest,
                plan_id=request_id,chunk_phase='append',chunk_added_at='2026-11-09T12:00:00+02:00',
                chunk_details_digest=self.append_only_digest)
        self.assertEqual(self.calls,[],'legacy profile request is rejected before transport')
    def test_reconcile_partial_uses_scoped_guard_and_same_manual_request_contract(self):
        request_id='a'*32
        reconciliation_id='b'*32
        fingerprint=hashlib.sha256(request_id.encode('utf-8')).hexdigest()[:24]
        second_profile=execution.PARTIAL_RECONCILIATION_PROFILES[
            '18a4aba10c1c13ab3bf59f56']
        with patch.dict(execution.PARTIAL_RECONCILIATION_PROFILES,{fingerprint:second_profile}), \
                patch.object(execution,'PARTIAL_RECONCILIATION_REQUEST_FINGERPRINT',fingerprint), \
                patch.object(runtime,'SANDBOX_PARTIAL_RECONCILIATION_REQUEST_FINGERPRINT',fingerprint):
            result=self.client.invoke('reconcile_partial',request_id,'sandbox-admin',
                trigger='manual',manual_authorized=True,reconciliation_id=reconciliation_id,
                request_fingerprint=fingerprint,evidence=second_profile['evidence'])
        self.assertEqual(result['status'],'RECONCILED_PARTIAL')
        self.assertEqual(result['reconciliationId'],reconciliation_id)
        self.assertEqual(result['requestFingerprint'],fingerprint)
        self.assertEqual(len(self.calls),1)
        self.assertEqual(json.loads(json.loads(self.calls[0].data)['parameters'][0]['payload'])['action'],
            'reconcile_partial')
        self.assertEqual(json.loads(self.calls[0].data)['function'],'pqmSandboxExecution',
            'historical reconciliation remains on the immutable dispatcher')
        self.assertEqual(json.loads(json.loads(self.calls[0].data)['parameters'][0]['payload'])['evidence'],
            second_profile['evidence'])
        changed_evidence=dict(second_profile['evidence'])
        changed_evidence['duplicate_rows']=1
        with patch.dict(execution.PARTIAL_RECONCILIATION_PROFILES,{fingerprint:second_profile}), \
                patch.object(execution,'PARTIAL_RECONCILIATION_REQUEST_FINGERPRINT',fingerprint):
            with self.assertRaisesRegex(ValueError,'evidence or identity rejected'):
                self.client.invoke('reconcile_partial',request_id,'sandbox-admin',
                    trigger='manual',manual_authorized=True,reconciliation_id=reconciliation_id,
                    request_fingerprint=fingerprint,evidence=changed_evidence)
        self.assertEqual(len(self.calls),1,'rejected evidence must not reach the transport')
        self.assertFalse(runtime._egress.active)
        self.assertIsNone(runtime._egress.execution_identity)

    def test_reconcile_partial_guard_rejects_fingerprint_id_trigger_and_digest_mismatches(self):
        request=self.request()
        body=json.loads(request.data)
        envelope=body['parameters'][0]
        payload=json.loads(envelope['payload'])
        request_id=payload['requestId']
        fingerprint=hashlib.sha256(request_id.encode('utf-8')).hexdigest()[:24]
        evidence_raw=json.dumps(execution.PARTIAL_RECONCILIATION_EVIDENCE,
            ensure_ascii=False,sort_keys=True,separators=(',',':'))
        evidence_digest=base64.urlsafe_b64encode(hashlib.sha256(evidence_raw.encode('utf-8')).digest()).decode().rstrip('=')
        payload.update(action='reconcile_partial',trigger='manual',expectedDigest=None,
            actor='sandbox-admin',reconciliationId='b'*32,requestFingerprint=fingerprint,
            evidence=execution.PARTIAL_RECONCILIATION_EVIDENCE,evidenceDigest=evidence_digest)
        with patch.object(runtime,'SANDBOX_PARTIAL_RECONCILIATION_REQUEST_FINGERPRINT',fingerprint):
            valid=urllib.request.Request(request.full_url,data=json.dumps(body).encode(),
                headers=request.headers,method='POST')
            self.assertEqual(self.validate(valid),'script.googleapis.com')
            bad_cases=(
                ('wrong_fingerprint',{'requestFingerprint':'0'*24}),
                ('malformed_reconciliation_id',{'reconciliationId':'not-an-id'}),
                ('scheduled_trigger',{'trigger':'scheduled'}),
                ('non_null_expected_digest',{'expectedDigest':self.preview_digest}),
                ('malformed_request_id',{'requestId':'not-an-id'}),
                ('missing_evidence_digest',{'evidenceDigest':None}),
                ('wrong_action',{'action':'arbitrary_action'}),
            )
            for name,override in bad_cases:
                with self.subTest(name=name):
                    altered=dict(payload); altered.update(override)
                    envelope['payload']=json.dumps(altered)
                    changed=urllib.request.Request(request.full_url,data=json.dumps(body).encode(),
                        headers=request.headers,method='POST')
                    with self.assertRaisesRegex(RuntimeError,'Sandbox execution envelope is not approved'):
                        self.validate(changed)

    def test_sandbox_partial_reconciliation_fingerprint_matches_execution_contract(self):
        self.assertEqual(runtime.SANDBOX_PARTIAL_RECONCILIATION_REQUEST_FINGERPRINT,
            execution.PARTIAL_RECONCILIATION_REQUEST_FINGERPRINT)
        self.assertIn('18a4aba10c1c13ab3bf59f56',
            execution.PARTIAL_RECONCILIATION_PROFILES)
        self.assertIn('18a4aba10c1c13ab3bf59f56',
            runtime.SANDBOX_PARTIAL_RECONCILIATION_REQUEST_FINGERPRINTS)

    def test_prepared_append_only_profile_fingerprint_reaches_only_reconciliation(self):
        request_id='ab1d69b6d7c6427f8abdffea35830948'
        reconciliation_id='23da3b07224e43bfa07725e41339a99f'
        fingerprint=execution.request_id_fingerprint(request_id)
        profile=execution.partial_reconciliation_profile(fingerprint)
        self.assertEqual(fingerprint,'30331b560493209210f1e507')
        self.assertIsNotNone(profile)
        self.assertIn(fingerprint,runtime.SANDBOX_PARTIAL_RECONCILIATION_REQUEST_FINGERPRINTS)

        def reconciliation_response(request,timeout):
            self.assertTrue(runtime._egress.active)
            self.calls.append(request)
            body=json.loads(request.data)
            message=json.loads(body['parameters'][0]['payload'])
            result={k:message[k] for k in ('environment','scriptId','spreadsheetId','contract','requestId')}
            evidence_raw=json.dumps(message['evidence'],ensure_ascii=False,sort_keys=True,separators=(',',':'))
            evidence_digest=base64.urlsafe_b64encode(hashlib.sha256(evidence_raw.encode('utf-8')).digest()).decode().rstrip('=')
            result.update(status='RECONCILED_PARTIAL',digest=self.preview_digest,
                reconciliationId=message['reconciliationId'],requestFingerprint=message['requestFingerprint'],
                evidenceDigest=evidence_digest,counts=profile['result_counts'],**profile['receipt_fields'])
            return io.BytesIO(json.dumps({'done':True,'response':{'result':result}}).encode())

        self.network.open.side_effect=reconciliation_response
        result=self.client.invoke('reconcile_partial',request_id,'sandbox-admin',trigger='manual',
            manual_authorized=True,reconciliation_id=reconciliation_id,
            request_fingerprint=fingerprint,evidence=profile['evidence'])
        self.assertEqual(result['status'],'RECONCILED_PARTIAL')
        self.assertEqual(result['reconciliationId'],reconciliation_id)
        self.assertEqual(len(self.calls),1)

    def test_legacy_326_profile_is_allowlisted_only_for_its_exact_reconciliation(self):
        request_id='592128d9837d4b71bbeb330ef8aabf4b'
        reconciliation_id='a'*32
        fingerprint=execution.request_id_fingerprint(request_id)
        profile=execution.partial_reconciliation_profile(fingerprint)
        self.assertEqual(fingerprint,'816c6424279bff220878b0c4')
        self.assertEqual(profile['request_id'],request_id)
        self.assertIn(fingerprint,runtime.SANDBOX_PARTIAL_RECONCILIATION_REQUEST_FINGERPRINTS)

        def reconciliation_response(request,timeout):
            self.assertTrue(runtime._egress.active)
            self.calls.append(request)
            body=json.loads(request.data)
            message=json.loads(body['parameters'][0]['payload'])
            result={k:message[k] for k in ('environment','scriptId','spreadsheetId','contract','requestId')}
            evidence_raw=json.dumps(message['evidence'],ensure_ascii=False,sort_keys=True,separators=(',',':'))
            evidence_digest=base64.urlsafe_b64encode(hashlib.sha256(evidence_raw.encode('utf-8')).digest()).decode().rstrip('=')
            result.update(status='RECONCILED_PARTIAL',digest=self.preview_digest,
                reconciliationId=message['reconciliationId'],requestFingerprint=fingerprint,
                evidenceDigest=evidence_digest,counts=profile['result_counts'],**profile['receipt_fields'])
            return io.BytesIO(json.dumps({'done':True,'response':{'result':result}}).encode())

        self.network.open.side_effect=reconciliation_response
        result=self.client.invoke('reconcile_partial',request_id,'sandbox-admin',trigger='manual',
            manual_authorized=True,reconciliation_id=reconciliation_id,
            request_fingerprint=fingerprint,evidence=profile['evidence'])
        self.assertEqual(result['status'],'RECONCILED_PARTIAL')
        self.assertFalse(result['checkpointPresent'])
        self.assertFalse(result['resumeAuthorized'])
        self.assertEqual(result['nextAction'],'NEW_PREVIEW_REQUIRED')
        self.assertEqual(result['counts']['fully_matching_rows'],25)
        self.assertEqual(result['counts']['partial_rows'],0)
        self.assertEqual(result['counts']['unverified_column_i_rows'],0)
        self.assertEqual(len(self.calls),1)

    def test_arbitrary_fingerprint_is_rejected_before_network_even_for_registered_profile(self):
        request_id='c'*32
        fingerprint=execution.request_id_fingerprint(request_id)
        self.assertNotIn(fingerprint,runtime.SANDBOX_PARTIAL_RECONCILIATION_REQUEST_FINGERPRINTS)
        profile=execution.PARTIAL_RECONCILIATION_PROFILES['18a4aba10c1c13ab3bf59f56']
        with patch.dict(execution.PARTIAL_RECONCILIATION_PROFILES,{fingerprint:profile}):
            with self.assertRaises(execution.ExecutionOutcomeUnknown):
                self.client.invoke('reconcile_partial',request_id,'sandbox-admin',trigger='manual',
                    manual_authorized=True,reconciliation_id='d'*32,
                    request_fingerprint=fingerprint,evidence=profile['evidence'])
        self.network.open.assert_not_called()
        self.assertEqual(self.calls,[])

    def test_new_fingerprint_does_not_authorize_apply_or_resume(self):
        request=self.request()
        body=json.loads(request.data)
        envelope=body['parameters'][0]
        payload=json.loads(envelope['payload'])
        fingerprint='816c6424279bff220878b0c4'

        altered=dict(payload,action='apply',expectedDigest=None,chunkIndex=0,
                     requestFingerprint=fingerprint,reconciliationId='23da3b07224e43bfa07725e41339a99f')
        envelope['payload']=json.dumps(altered)
        apply_request=urllib.request.Request(request.full_url,data=json.dumps(body).encode(),
            headers=request.headers,method='POST')
        with self.assertRaisesRegex(RuntimeError,'Sandbox execution envelope is not approved'):
            self.validate(apply_request)

        altered.update(action='resume_check',expectedDigest=self.preview_digest,
            planScope='APPEND_ONLY',expectedCheckpointDigest=self.append_only_digest)
        envelope['payload']=json.dumps(altered)
        resume_request=urllib.request.Request(request.full_url,data=json.dumps(body).encode(),
            headers=request.headers,method='POST')
        with self.assertRaisesRegex(RuntimeError,'Sandbox execution envelope is not approved'):
            self.validate(resume_request)

    def test_legacy_profile_fingerprint_does_not_authorize_apply_or_resume(self):
        request=self.request()
        body=json.loads(request.data)
        envelope=body['parameters'][0]
        payload=json.loads(envelope['payload'])
        fingerprint='816c6424279bff220878b0c4'
        payload['requestId']='592128d9837d4b71bbeb330ef8aabf4b'
        payload['requestFingerprint']=fingerprint
        payload['reconciliationId']='a'*32

        payload.update(action='apply',expectedDigest=None,chunkIndex=0)
        envelope['payload']=json.dumps(payload)
        apply_request=urllib.request.Request(request.full_url,data=json.dumps(body).encode(),
            headers=request.headers,method='POST')
        with self.assertRaisesRegex(RuntimeError,'Sandbox execution envelope is not approved'):
            self.validate(apply_request)

        payload.update(action='resume_check',expectedDigest=self.preview_digest,
            planScope='APPEND_ONLY',expectedCheckpointDigest=self.append_only_digest)
        envelope['payload']=json.dumps(payload)
        resume_request=urllib.request.Request(request.full_url,data=json.dumps(body).encode(),
            headers=request.headers,method='POST')
        with self.assertRaisesRegex(RuntimeError,'Sandbox execution envelope is not approved'):
            self.validate(resume_request)

    def test_oauth_refresh_default_adapter_uses_same_scoped_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'credential.json'
            path.write_text(json.dumps({'environment':'SANDBOX','gcp_project_id':'sandbox-only',
                'scopes':sorted(execution.PROJECT_SCOPES),'client_id':'offline','client_secret':'offline',
                'refresh_token':'offline'}))
            path.chmod(0o600)
            provider=execution.DedicatedTokenProvider('SANDBOX',str(path),'sandbox-only',clock=lambda:NOW)
            self.assertEqual(provider('SANDBOX')['access_token'],'OFFLINE_TOKEN')
            self.assertEqual(self.calls[0].full_url,'https://oauth2.googleapis.com/token')
            provider('SANDBOX')
            self.assertEqual(len(self.calls),1)
            self.assertFalse(runtime._egress.active)

    def test_credential_permission_policy_accepts_only_private_or_render_secret_modes(self):
        policy=execution._credential_mode_allowed
        self.assertTrue(policy(0o100600,render_managed=False))
        self.assertTrue(policy(0o100400,render_managed=False))
        self.assertTrue(policy(0o100640,render_managed=True))
        self.assertFalse(policy(0o100640,render_managed=False))
        for mode in (0o100644,0o100660,0o100666,0o100777):
            with self.subTest(mode=oct(mode)):
                self.assertFalse(policy(mode,render_managed=True))
                self.assertFalse(policy(mode,render_managed=False))

    @unittest.skipUnless(os.name != 'nt','POSIX file permission and atomic-copy contract runs in Linux container Gate')
    def test_render_secret_0640_is_copied_atomically_to_private_ephemeral_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'secrets'
            root.mkdir(mode=0o700)
            temp_root=Path(directory)/'private-temp'
            temp_root.mkdir(mode=0o700)
            path=root/'credential.json'
            raw=json.dumps({'environment':'SANDBOX','gcp_project_id':'sandbox-only',
                'scopes':sorted(execution.PROJECT_SCOPES),'client_id':'offline','client_secret':'offline',
                'refresh_token':'offline'}).encode()
            path.write_bytes(raw);path.chmod(0o640)
            with patch.object(execution,'RENDER_SECRET_DIR',root), \
                 patch.object(execution.tempfile,'gettempdir',return_value=str(temp_root)), \
                 patch.object(execution,'_private_credential_copy',wraps=execution._private_credential_copy) as staged:
                value=execution._load_execution_credential(path)
            staged.assert_called_once_with(raw)
            self.assertEqual(value['environment'],'SANDBOX')
            self.assertEqual(path.stat().st_mode & 0o777,0o640)
            self.assertEqual(list(temp_root.iterdir()),[])

    @unittest.skipUnless(os.name != 'nt','Render Secret File symlink contract runs in Linux container Gate')
    def test_render_versioned_secret_symlink_is_pinned_and_staged_privately(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'secrets';root.mkdir(mode=0o700)
            version=root/'..2026_11_01_21_12_41.1089918540';version.mkdir(mode=0o700)
            temp_root=Path(directory)/'private-temp';temp_root.mkdir(mode=0o700)
            target=version/'pqm-sandbox-execution.json'
            raw=json.dumps({'environment':'SANDBOX','gcp_project_id':'sandbox-only',
                'scopes':sorted(execution.PROJECT_SCOPES),'client_id':'offline','client_secret':'offline',
                'refresh_token':'offline'}).encode()
            target.write_bytes(raw);target.chmod(0o640)
            data_link=root/'..data';data_link.symlink_to(version.name)
            link=root/'pqm-sandbox-execution.json'
            link.symlink_to(Path('..data')/target.name)
            opened_modes=[]
            real_open=execution._open_regular_nofollow
            def record_private_copy(path, flags):
                fd, info=real_open(path,flags)
                if Path(path).name=='credential.json' and 'pqm-execution-oauth-' in str(path):
                    opened_modes.append(stat.S_IMODE(info.st_mode))
                return fd,info
            with patch.object(execution,'RENDER_SECRET_DIR',root), \
                 patch.object(execution.tempfile,'gettempdir',return_value=str(temp_root)), \
                 patch.object(execution.os.path,'ismount',return_value=True), \
                 patch.object(execution.os,'statvfs',return_value=SimpleNamespace(f_flag=os.ST_RDONLY)), \
                 patch.object(execution,'_open_regular_nofollow',side_effect=record_private_copy), \
                 patch.object(execution,'_private_credential_copy',wraps=execution._private_credential_copy) as staged:
                value=execution._load_execution_credential(link)
            self.assertEqual(value['environment'],'SANDBOX')
            staged.assert_called_once_with(raw)
            self.assertEqual(opened_modes,[0o600])
            self.assertTrue(link.is_symlink())
            self.assertTrue(data_link.is_symlink())
            self.assertEqual(target.read_bytes(),raw)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode),0o640)
            self.assertEqual(list(temp_root.iterdir()),[])

    @unittest.skipUnless(os.name != 'nt','Render Secret version-pointer contract runs in Linux container Gate')
    def test_render_version_pointer_replacement_during_read_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'secrets';root.mkdir(mode=0o700)
            first=root/'..2026_11_01_21_12_41.1089918540';first.mkdir(mode=0o700)
            second=root/'..2026_11_02_09_30_00.1089918541';second.mkdir(mode=0o700)
            for version in (first,second):
                target=version/'credential.json';target.write_text('{}',encoding='utf-8');target.chmod(0o640)
            data_link=root/'..data';data_link.symlink_to(first.name)
            link=root/'credential.json';link.symlink_to(Path('..data')/link.name)
            real_read=execution.os.read;swapped=False
            def read_then_swap(fd,size):
                nonlocal swapped
                data=real_read(fd,size)
                if not swapped:
                    swapped=True
                    replacement=root/'..data.new';replacement.symlink_to(second.name)
                    replacement.replace(data_link)
                return data
            with patch.object(execution,'RENDER_SECRET_DIR',root), \
                 patch.object(execution.os.path,'ismount',return_value=True), \
                 patch.object(execution.os,'statvfs',return_value=SimpleNamespace(f_flag=os.ST_RDONLY)), \
                 patch.object(execution.os,'read',side_effect=read_then_swap):
                with self.assertRaises(ValueError):execution._load_execution_credential(link)

    @unittest.skipUnless(os.name != 'nt','Render Secret version-pointer guards run in Linux container Gate')
    def test_render_version_pointer_rejects_escape_alias_cycle_and_symlink_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);root=base/'secrets';root.mkdir(mode=0o700)
            outside=base/'outside';outside.mkdir(mode=0o700)
            (outside/'credential.json').write_text('{}',encoding='utf-8')
            (outside/'credential.json').chmod(0o640)
            real=root/'..2026_11_01_21_12_41.1089918540';real.mkdir(mode=0o700)
            (real/'credential.json').write_text('{}',encoding='utf-8')
            (real/'credential.json').chmod(0o640)
            data_link=root/'..data';source=root/'credential.json'
            source.symlink_to(Path('..data')/'credential.json')
            bad_targets=('../outside','..data','..not-versioned','..2026_11_01_21_12_41.1089918540/child')
            with patch.object(execution,'RENDER_SECRET_DIR',root), \
                 patch.object(execution.os.path,'ismount',return_value=True), \
                 patch.object(execution.os,'statvfs',return_value=SimpleNamespace(f_flag=os.ST_RDONLY)):
                for bad_target in bad_targets:
                    with self.subTest(target_kind=bad_target.split('/')[0]):
                        if data_link.exists() or data_link.is_symlink():data_link.unlink()
                        data_link.symlink_to(bad_target)
                        with self.assertRaises((OSError,ValueError)):
                            execution._load_execution_credential(source)
                if data_link.exists() or data_link.is_symlink():data_link.unlink()
                version_link=root/'..2026_11_02_09_30_00.1089918541'
                version_link.symlink_to(outside,target_is_directory=True)
                data_link.symlink_to(version_link.name)
                self.assertTrue(version_link.is_symlink())
                with self.assertRaises((OSError,ValueError)):
                    execution._load_execution_credential(source)

    @unittest.skipUnless(os.name != 'nt','Render Secret File symlink contract runs in Linux container Gate')
    def test_render_secret_symlink_rejects_escape_nested_links_cycles_and_unsafe_modes(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);root=base/'secrets';root.mkdir(mode=0o700)
            version=root/'..2026';version.mkdir(mode=0o700)
            target=version/'credential.json';target.write_text('{}',encoding='utf-8');target.chmod(0o640)
            link=root/'credential.json'
            escapes=base/'outside.json';escapes.write_text('{}',encoding='utf-8');escapes.chmod(0o640)
            nested=base/'nested';nested.mkdir();(nested/'credential.json').write_text('{}',encoding='utf-8')
            cases=[('escape',Path(os.path.relpath(escapes,root))),
                   ('parent traversal',Path('../outside.json'))]
            with patch.object(execution,'RENDER_SECRET_DIR',root), \
                 patch.object(execution.os.path,'ismount',return_value=True), \
                 patch.object(execution.os,'statvfs',return_value=SimpleNamespace(f_flag=os.ST_RDONLY)):
                for label,destination in cases:
                    with self.subTest(label=label):
                        if link.exists() or link.is_symlink():link.unlink()
                        link.symlink_to(destination)
                        with self.assertRaises((OSError,ValueError)):
                            execution._load_execution_credential(link)
                nested_link=version/'nested-link';nested_link.symlink_to(nested,target_is_directory=True)
                if link.exists() or link.is_symlink():link.unlink()
                link.symlink_to(Path(version.name)/'nested-link'/'credential.json')
                with self.assertRaises((OSError,ValueError)):
                    execution._load_execution_credential(link)
                if link.exists() or link.is_symlink():link.unlink()
                link.symlink_to(link.name)
                with self.assertRaises((OSError,ValueError)):
                    execution._load_execution_credential(link)
                if link.exists() or link.is_symlink():link.unlink()
                link.symlink_to(Path(version.name)/target.name)
                for mode in (0o644,0o660,0o666,0o777):
                    with self.subTest(mode=oct(mode)):
                        target.chmod(mode)
                        with self.assertRaises(ValueError):
                            execution._load_execution_credential(link)
                target.chmod(0o640)
                with patch.object(execution.os,'statvfs',return_value=SimpleNamespace(f_flag=0)):
                    with self.assertRaises(ValueError):
                        execution._load_execution_credential(link)

    @unittest.skipUnless(os.name != 'nt','Render Secret File TOCTOU checks run in Linux container Gate')
    def test_render_secret_symlink_replacement_during_read_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'secrets';root.mkdir(mode=0o700)
            version=root/'..version';version.mkdir(mode=0o700)
            first=version/'credential.json';first.write_text('{}',encoding='utf-8');first.chmod(0o640)
            second=version/'replacement.json';second.write_text('{"replacement":true}',encoding='utf-8');second.chmod(0o640)
            link=root/'credential.json';link.symlink_to(Path(version.name)/first.name)
            real_read=execution.os.read;swapped=False
            def read_then_swap(fd,size):
                nonlocal swapped
                data=real_read(fd,size)
                if not swapped:
                    swapped=True
                    link.unlink();link.symlink_to(Path(version.name)/second.name)
                return data
            with patch.object(execution,'RENDER_SECRET_DIR',root), \
                 patch.object(execution.os.path,'ismount',return_value=True), \
                 patch.object(execution.os,'statvfs',return_value=SimpleNamespace(f_flag=os.ST_RDONLY)), \
                 patch.object(execution.os,'read',side_effect=read_then_swap):
                with self.assertRaises(ValueError):execution._load_execution_credential(link)

    @unittest.skipUnless(os.name != 'nt','Render Secret File TOCTOU checks run in Linux container Gate')
    def test_render_secret_target_replacement_during_read_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'secrets';root.mkdir(mode=0o700)
            version=root/'..version';version.mkdir(mode=0o700)
            target=version/'credential.json';target.write_text('{}',encoding='utf-8');target.chmod(0o640)
            link=root/'credential.json';link.symlink_to(Path(version.name)/target.name)
            real_read=execution.os.read;swapped=False
            def read_then_replace(fd,size):
                nonlocal swapped
                data=real_read(fd,size)
                if not swapped:
                    swapped=True
                    moved=version/'old.json';target.replace(moved)
                    target.write_text('{"replacement":true}',encoding='utf-8');target.chmod(0o640)
                return data
            with patch.object(execution,'RENDER_SECRET_DIR',root), \
                 patch.object(execution.os.path,'ismount',return_value=True), \
                 patch.object(execution.os,'statvfs',return_value=SimpleNamespace(f_flag=os.ST_RDONLY)), \
                 patch.object(execution.os,'read',side_effect=read_then_replace):
                with self.assertRaises(ValueError):execution._load_execution_credential(link)

    @unittest.skipUnless(os.name != 'nt','POSIX file permission enforcement runs in Linux container Gate')
    def test_group_readable_non_render_and_unsafe_render_modes_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'secrets';root.mkdir()
            private=Path(directory)/'outside.json'
            private.write_text('{}',encoding='utf-8')
            private.chmod(0o640)
            with self.assertRaises(ValueError):execution._load_execution_credential(private)
            unsafe=root/'unsafe.json';unsafe.write_text('{}',encoding='utf-8');unsafe.chmod(0o644)
            with patch.object(execution,'RENDER_SECRET_DIR',root):
                with self.assertRaises(ValueError):execution._load_execution_credential(unsafe)

    def test_credential_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'target.json';target.write_text('{}',encoding='utf-8')
            link=Path(directory)/'link.json'
            try:
                link.symlink_to(target)
            except (OSError,NotImplementedError):
                self.skipTest('Symlink creation is unavailable to this test user')
            with self.assertRaises((OSError,ValueError)):
                execution._load_execution_credential(link)

    def test_invalid_endpoint_variants_are_rejected_before_network(self):
        valid=self.request()
        for url in ('https://evil.example/token','http://script.googleapis.com/v1/scripts/'+self.deployment+':run',
                    valid.full_url+'?x=1',valid.full_url+'#fragment',valid.full_url.replace('https://','https://user@'),
                    valid.full_url.replace(':run','%3Arun'),valid.full_url.replace(self.deployment,'OTHER_DEPLOYMENT_0123456789'),
                    'https://script.googleapis.com:443/v1/scripts/'+self.deployment+':run',
                    'https://oauth2.googleapis.com/token/','https://sheets.googleapis.com/v4/spreadsheets/'+self.sheet):
            with self.subTest(url=url), self.assertRaises(RuntimeError):
                self.validate(urllib.request.Request(url,data=valid.data,headers=valid.headers,method='POST'))
        self.assertEqual(self.calls,[])

    def test_wrong_script_sheet_environment_and_deployment_fail_closed(self):
        request=self.request()
        for override in ({'script_id':execution.IDENTITIES['PROD'][0]},
                         {'spreadsheet_id':execution.IDENTITIES['PROD'][1]},
                         {'environment':'PROD'},{'deployment_id':'OTHER_DEPLOYMENT_0123456789'}):
            with self.subTest(override=override),self.assertRaises(RuntimeError):self.validate(request,**override)
        body=json.loads(request.data)
        for field,value in (('environment','PROD'),('scriptId',execution.IDENTITIES['PROD'][0]),
                            ('spreadsheetId',execution.IDENTITIES['PROD'][1])):
            payload=json.loads(body['parameters'][0]['payload']);payload[field]=value
            changed=json.loads(request.data);changed['parameters'][0]['payload']=json.dumps(payload)
            with self.subTest(field=field),self.assertRaises(RuntimeError):
                self.validate(urllib.request.Request(request.full_url,data=json.dumps(changed).encode(),headers=request.headers))

    def test_ready_service_and_sandbox_flags_are_required(self):
        request=self.request()
        for key,value in (('PQM_SANDBOX','0'),('PQM_SANDBOX_EXECUTION_READY','0'),
                          ('RENDER_SERVICE_ID','srv-da7vmitg1s2s73fim0p0'),('PQM_SANDBOX_EXECUTION_DEPLOYMENT_ID','')):
            with self.subTest(key=key),patch.dict(os.environ,{key:value}),self.assertRaises(RuntimeError):
                self.validate(request)

    def test_prod_client_cannot_use_sandbox_transport(self):
        prod=execution.ExecutionClient('PROD',self.deployment,'offline_'+'x'*32,self.token,configured=True,clock=lambda:NOW)
        with self.assertRaises(execution.ExecutionPreflightError):prod.invoke('preview','b'*32,'uo')
        self.assertEqual(self.calls,[])

    def test_dns_and_connections_remain_closed_outside_scope(self):
        for host in ('script.googleapis.com','oauth2.googleapis.com','evil.example'):
            with self.subTest(host=host),self.assertRaises(RuntimeError):
                runtime.outbound_audit('socket.getaddrinfo',(host,443,0,0,0))
        with self.assertRaises(RuntimeError):runtime.outbound_audit('socket.connect',(None,('8.8.8.8',443)))

    def test_scope_pins_dns_public_ip_connection_and_rejects_nested_scopes(self):
        request=self.request()
        with runtime.execution_open(request,timeout=390,environment='SANDBOX',script_id=self.script,
                                    spreadsheet_id=self.sheet,deployment_id=self.deployment):
            rows=[(2,1,6,'',('8.8.8.8',443))]
            with patch.object(runtime,'_original_getaddrinfo',return_value=rows):
                self.assertEqual(runtime._restricted_getaddrinfo('script.googleapis.com',443),rows)
            runtime.outbound_audit('socket.connect',(None,('8.8.8.8',443)))
            for host in ('oauth2.googleapis.com','evil.example'):
                with self.assertRaises(RuntimeError):runtime.outbound_audit('socket.getaddrinfo',(host,443,0,0,0))
            with self.assertRaises(RuntimeError):runtime.outbound_audit('socket.connect',(None,('8.8.4.4',443)))
            with self.assertRaises(RuntimeError):
                with runtime.execution_open(request,timeout=1,environment='SANDBOX',script_id=self.script,
                                            spreadsheet_id=self.sheet,deployment_id=self.deployment):pass
            with patch.object(runtime,'_original_getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
                with self.assertRaises(RuntimeError):runtime._restricted_getaddrinfo('script.googleapis.com',443)
        self.assertFalse(runtime._egress.active)
        self.assertEqual(runtime._egress.addresses,set())

    def test_auth_failure_once_cleanup_and_no_secret_in_error(self):
        self.network.open.side_effect=OSError('OFFLINE_TOKEN SECRET')
        with self.assertRaises(execution.ExecutionOutcomeUnknown) as error:self.client.invoke('preview','a'*32,'uo')
        self.assertNotIn('OFFLINE_TOKEN',str(error.exception))
        self.assertEqual(self.network.open.call_count,1)
        self.assertFalse(runtime._egress.active)
        self.assertIsNone(runtime._egress.execution_host)

    def test_redirects_even_same_host_are_rejected(self):
        for url in ('https://evil.example','https://script.googleapis.com/v1/scripts/'+self.deployment+':run'):
            with self.subTest(url=url),self.assertRaises(RuntimeError):
                runtime._NoGoogleRedirect().redirect_request(None,None,302,'',{},url)

    def test_no_apply_without_digest_and_repeated_preview_is_only_preview(self):
        with self.assertRaises(ValueError):self.client.invoke('apply','a'*32,'uo')
        self.assertEqual(self.calls,[])
        for _ in range(2):self.client.invoke('preview','a'*32,'uo')
        self.assertEqual(len(self.calls),2)
        self.assertTrue(all(json.loads(json.loads(r.data)['parameters'][0]['payload'])['action']=='preview' for r in self.calls))

    def test_missing_wrong_environment_or_incomplete_credentials_no_network(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'credential.json'
            for value in ({},{'environment':'PROD','gcp_project_id':'sandbox-only'},
                          {'environment':'SANDBOX','gcp_project_id':'sandbox-only','scopes':sorted(execution.PROJECT_SCOPES)}):
                path.write_text(json.dumps(value));path.chmod(0o600)
                provider=execution.DedicatedTokenProvider('SANDBOX',str(path),'sandbox-only',clock=lambda:NOW)
                with self.assertRaises(execution.ExecutionConfigurationError):provider('SANDBOX')
            with self.assertRaises(execution.ExecutionConfigurationError):
                execution.DedicatedTokenProvider('SANDBOX',str(path)+'-absent','sandbox-only')('SANDBOX')
        self.assertEqual(self.calls,[])

    def test_malformed_oauth_and_execution_requests_are_rejected(self):
        request=self.request()
        for raw in (b'{}',b'null',b'[]',b'broken'):
            with self.subTest(raw=raw),self.assertRaises(RuntimeError):
                self.validate(urllib.request.Request(request.full_url,data=raw,headers=request.headers))
        for raw in (b'grant_type=client_credentials',b'grant_type=refresh_token&client_id=x',
                    b'grant_type=refresh_token&client_id=x&client_secret=x&refresh_token=x&url=evil'):
            with self.subTest(raw=raw),self.assertRaises(RuntimeError):
                self.validate(urllib.request.Request('https://oauth2.googleapis.com/token',data=raw))
        with self.assertRaises(RuntimeError):self.validate(urllib.request.Request(request.full_url))
        with self.assertRaises(RuntimeError):self.validate(urllib.request.Request(request.full_url,data=request.data))

    def test_execution_error_response_no_retry_or_secret_leak(self):
        self.network.open.side_effect=lambda request,timeout:io.BytesIO(json.dumps(
            {'done':True,'error':{'message':'OFFLINE_SECRET'}}).encode())
        with self.assertRaises(execution.ExecutionOutcomeUnknown) as error:
            self.client.invoke('preview','a'*32,'uo')
        self.assertEqual(self.network.open.call_count,1)
        self.assertNotIn('OFFLINE_SECRET',str(error.exception))
        self.assertFalse(runtime._egress.active)

    def test_oauth_auth_error_no_retry_and_scope_cleanup(self):
        self.network.open.side_effect=OSError('OFFLINE_REFRESH_SECRET')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'credential.json'
            path.write_text(json.dumps({'environment':'SANDBOX','gcp_project_id':'sandbox-only',
                'scopes':sorted(execution.PROJECT_SCOPES),'client_id':'offline','client_secret':'offline',
                'refresh_token':'OFFLINE_REFRESH_SECRET'}));path.chmod(0o600)
            with self.assertRaises(execution.ExecutionConfigurationError) as error:
                execution.DedicatedTokenProvider('SANDBOX',str(path),'sandbox-only',clock=lambda:NOW)('SANDBOX')
        self.assertEqual(self.network.open.call_count,1)
        self.assertNotIn('OFFLINE_REFRESH_SECRET',str(error.exception))
        self.assertFalse(runtime._egress.active)

    def test_legacy_google_guard_does_not_gain_execution_endpoint(self):
        with self.assertRaises(RuntimeError):
            runtime.validate_google_request('https://script.googleapis.com/v1/scripts/'+self.deployment+':run','POST')
        with self.assertRaises(RuntimeError):
            runtime.validate_google_request('https://sheets.googleapis.com/v4/spreadsheets/'+execution.IDENTITIES['PROD'][1],'GET')

    def test_wrong_production_runtime_cannot_open_sandbox_execution(self):
        with patch.dict(os.environ,{'PQM_SANDBOX':'0','RENDER_SERVICE_ID':'srv-da7vmitg1s2s73fim0p0'}):
            with self.assertRaises(execution.ExecutionOutcomeUnknown):self.client.invoke('preview','a'*32,'uo')
        self.assertEqual(self.calls,[])


if __name__=='__main__':unittest.main()
