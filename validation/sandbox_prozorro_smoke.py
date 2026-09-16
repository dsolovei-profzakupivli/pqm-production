"""Manual sandbox Prozorro exception: narrow egress, RBAC and stable guards."""
import io,os,socket,sqlite3,threading,time,unittest
from unittest.mock import patch
import sandbox_smoke as base
sandbox=base.sandbox
URL='https://public-api.prozorro.gov.ua/api/2.5/frameworks/test'

class NetworkPolicy(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{'PQM_SANDBOX':'1','PQM_SANDBOX_PROZORRO_READ':'1'})
        self.env.start();sandbox._egress.active=False;sandbox._egress.addresses=set()
    def tearDown(self):
        sandbox._egress.active=False;sandbox._egress.addresses=set();self.env.stop()
    def test_flag_is_explicit_and_target_bound(self):
        with patch.dict(os.environ,{'PQM_SANDBOX_PROZORRO_READ':'0'}):
            self.assertFalse(sandbox.manual_sync_allowed('POST','/api/sync'))
            with self.assertRaises(RuntimeError):sandbox.fetch_prozorro_json(URL)
        self.assertTrue(sandbox.manual_sync_allowed('POST','/api/sync'))
        for method,path in [('GET','/api/sync'),('POST','/api/frameworks/refresh'),('POST','/api/amcu-registry/refresh')]:
            self.assertFalse(sandbox.manual_sync_allowed(method,path))
        env=base.PolicyTests().env();env['PQM_SANDBOX_PROZORRO_READ']='1'
        with self.assertRaises(RuntimeError):sandbox.validate_environment(env)
        env['RENDER_SERVICE_ID']='srv-dalfd77f3r2c7392uub0';sandbox.validate_environment(env)
    def test_urls_and_redirects_fail_closed(self):
        for url in [URL,URL+'/submissions?offset=123.4',URL+'/qualifications',
                    'https://public-api.prozorro.gov.ua/api/2.5/agreements/abc/contracts']:
            sandbox.validate_prozorro_url(url)
        for url in [URL.replace('https:','http:'),URL.replace('public-api.prozorro.gov.ua','pqm-production-1.onrender.com'),
                    URL+'?callback=https://evil.invalid',URL+'#fragment',URL+'/../../tenders',
                    URL.replace('gov.ua/','gov.ua:443/'),URL.replace('https://','https://user:password@'),
                    'https://public-api.prozorro.gov.ua/api/2.5/tenders',
                    'https://127.0.0.1/api/2.5/frameworks',URL.replace('/test','/%2e%2e')]:
            with self.subTest(url=url),self.assertRaises(RuntimeError):sandbox.validate_prozorro_url(url)
        with self.assertRaises(RuntimeError):sandbox._ProzorroRedirect().redirect_request(None,None,302,'',{},'https://evil.invalid/')
    def test_dns_and_socket_scope(self):
        with self.assertRaises(RuntimeError):sandbox.outbound_audit('socket.getaddrinfo',(sandbox.PROZORRO_HOST,443))
        sandbox._egress.active=True
        sandbox.outbound_audit('socket.getaddrinfo',(sandbox.PROZORRO_HOST,443))
        public=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('8.8.8.8',443))]
        with patch.object(sandbox,'_original_getaddrinfo',return_value=public):
            self.assertEqual(public,sandbox._restricted_getaddrinfo(sandbox.PROZORRO_HOST,443))
        sandbox.outbound_audit('socket.connect',(None,('8.8.8.8',443)))
        for address in [('8.8.8.8',80),('1.1.1.1',443),('10.0.0.1',443)]:
            with self.assertRaises(RuntimeError):sandbox.outbound_audit('socket.connect',(None,address))
        with patch.object(sandbox,'_original_getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaises(RuntimeError):sandbox._restricted_getaddrinfo(sandbox.PROZORRO_HOST,443)
        for event,args in [('socket.gethostbyname',(sandbox.PROZORRO_HOST,)),('socket.getaddrinfo',('pqm-production-1',443)),
                           ('socket.sendto',(None,b'bad',('8.8.8.8',443))),('subprocess.Popen',())]:
            with self.assertRaises(RuntimeError):sandbox.outbound_audit(event,args)
        sandbox.outbound_audit('urllib.Request',(URL,None,{},'GET'))
        for method in ['POST','PATCH','DELETE']:
            with self.assertRaises(RuntimeError):sandbox.outbound_audit('urllib.Request',(URL,None,{},method))
        with self.assertRaises(RuntimeError):sandbox.outbound_audit('urllib.Request',(URL,b'body',{},'GET'))
        other=[]
        def other_thread():
            try:sandbox.outbound_audit('socket.connect',(None,('8.8.8.8',443)))
            except RuntimeError:other.append('blocked')
        thread=threading.Thread(target=other_thread);thread.start();thread.join();self.assertEqual(['blocked'],other)
    def test_fetch_has_no_credentials_and_always_relocks(self):
        with patch('urllib.request.build_opener') as builder:
            builder.return_value.open.return_value=io.BytesIO(b'{"data":[]}')
            self.assertEqual({'data':[]},sandbox.fetch_prozorro_json(URL))
            req=builder.return_value.open.call_args.args[0]
            self.assertEqual('GET',req.get_method());self.assertIsNone(req.data)
            self.assertNotIn('Authorization',req.headers)
            self.assertFalse(sandbox._egress.active);self.assertEqual(set(),sandbox._egress.addresses)
            builder.return_value.open.side_effect=OSError('synthetic failure')
            with self.assertRaises(OSError):sandbox.fetch_prozorro_json(URL)
            self.assertFalse(sandbox._egress.active)

class ManualHTTP(base.SandboxHTTP):
    EDIT_MODE='1'
    EXTRA_ENV={'PQM_SANDBOX_PROZORRO_READ':'1'}
    RUNNER='validation/sandbox_prozorro_fixture.py'
    def test_12_safe_mode_denies_updates(self):
        for role in ['admin','officer','viewer']:
            for path in ['/api/admin/scheduler-jobs/prozorro','/api/admin/runtime-features/google',
                         '/api/violation-reports/sync','/api/frameworks/refresh',
                         '/api/amcu-registry/refresh','/api/nazk-registry/refresh','/api/operational-tasks/rebuild']:
                self.assertEqual(503,self.request(path,role,'POST',{'enabled':True})[0])
        self.assertEqual(503,self.request('/api/sync?refresh=1','admin','POST',{})[0])
    def test_20_manual_single_and_full_without_jobs_or_google(self):
        self.assertTrue(self.request('/api/runtime-features')[1]['sandbox_prozorro_read'])
        self.assertEqual(403,self.request('/api/sync','viewer','POST',{})[0])
        self.assertEqual(403,self.request('/api/sync','officer','POST',{})[0])
        self.assertEqual(401,self.request('/api/sync',None,'POST',{})[0])
        for role,payload in [('admin',{'framework_id':'sandbox-framework'}),('admin',{})]:
            self.assertEqual(202,self.request('/api/sync',role,'POST',payload)[0])
            self.assertEqual(409,self.request('/api/sync',role,'POST',payload)[0])
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                state=self.request('/api/health',None)[1]['sync']
                if not state['running']:break
                time.sleep(.05)
            self.assertFalse(state['running']);self.assertNotEqual('failed',state['last_result'].get('status'))
            self.assertEqual(1,state['last_result']['submissions'])
        with sqlite3.connect(self.data/'pqm_sandbox.sqlite3') as c:
            self.assertEqual('SYNTHETIC UPDATED',c.execute("SELECT supplier_name FROM submissions WHERE id='sandbox-pending'").fetchone()[0])
            self.assertEqual('active',c.execute("SELECT status FROM qualifications WHERE id='sandbox-q-pending'").fetchone()[0])
            for table in ['supplier_nazk_checks','supplier_nazk_reviews','operational_tasks','amcu_registry','nazk_registry','scheduler_job_leases']:
                self.assertEqual(0,c.execute('SELECT COUNT(*) FROM '+table).fetchone()[0],table)
            self.assertEqual(('ok','manual'),c.execute("SELECT last_status,last_trigger FROM scheduler_job_state WHERE job_key='prozorro'").fetchone())
            self.assertEqual(0,c.execute('SELECT count(*) FROM scheduler_job_settings WHERE enabled<>0').fetchone()[0])
        self.test_14_restart_keeps_accounts_and_fixture()
        flags=self.request('/api/runtime-features')[1]
        self.assertTrue(all(not j['enabled'] and not j['running'] for j in flags['scheduler_jobs']))
        self.assertIn('РУЧНИЙ PROZORRO',self.request('/',None)[1].decode())

if __name__=='__main__':unittest.main(verbosity=2)
