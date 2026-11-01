"""Offline regressions for the real SANDBOX scoped Execution transport."""
import io
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
            target=version/'pqm-sandbox-execution.json'
            raw=json.dumps({'environment':'SANDBOX','gcp_project_id':'sandbox-only',
                'scopes':sorted(execution.PROJECT_SCOPES),'client_id':'offline','client_secret':'offline',
                'refresh_token':'offline'}).encode()
            target.write_bytes(raw);target.chmod(0o640)
            link=root/'pqm-sandbox-execution.json'
            link.symlink_to(Path(version.name)/target.name)
            opened_modes=[]
            real_open=execution._open_regular_nofollow
            def record_private_copy(path, flags):
                fd, info=real_open(path,flags)
                if Path(path).name=='credential.json' and 'pqm-execution-oauth-' in str(path):
                    opened_modes.append(stat.S_IMODE(info.st_mode))
                return fd,info
            with patch.object(execution,'RENDER_SECRET_DIR',root), \
                 patch.object(execution.os.path,'ismount',return_value=True), \
                 patch.object(execution.os,'statvfs',return_value=SimpleNamespace(f_flag=os.ST_RDONLY)), \
                 patch.object(execution,'_open_regular_nofollow',side_effect=record_private_copy), \
                 patch.object(execution,'_private_credential_copy',wraps=execution._private_credential_copy) as staged:
                value=execution._load_execution_credential(link)
            self.assertEqual(value['environment'],'SANDBOX')
            staged.assert_called_once_with(raw)
            self.assertEqual(opened_modes,[0o600])
            self.assertTrue(link.is_symlink())
            self.assertEqual(target.read_bytes(),raw)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode),0o640)

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
