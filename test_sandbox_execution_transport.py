"""Offline regressions for the real SANDBOX scoped Execution transport."""
import io
import json
import os
import tempfile
import unittest
import urllib.request
from pathlib import Path
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
        result.update(status='PREVIEW',digest='a'*64,counts={'update':0})
        return io.BytesIO(json.dumps({'done':True,'response':{'result':result}}).encode())

    def request(self):
        self.client.invoke('preview','a'*32,'uo')
        return self.calls.pop()

    def validate(self, request, **overrides):
        values=dict(environment='SANDBOX',script_id=self.script,spreadsheet_id=self.sheet,deployment_id=self.deployment)
        values.update(overrides)
        return runtime.validate_execution_request(request,**values)

    def test_default_adapter_preview_real_scoped_guard_no_apply_or_receipts(self):
        result=self.client.invoke('preview','a'*32,'uo')
        self.assertEqual(result['status'],'PREVIEW')
        self.assertEqual(len(self.calls),1)
        message=json.loads(json.loads(self.calls[0].data)['parameters'][0]['payload'])
        self.assertEqual(message['action'],'preview')
        self.assertFalse(runtime._egress.active)
        self.assertIsNone(runtime._egress.execution_identity)
        self.assertNotIn('OFFLINE_TOKEN',json.dumps(result))

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
        with self.assertRaises(execution.ExecutionOutcomeUnknown):prod.invoke('preview','b'*32,'uo')
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
