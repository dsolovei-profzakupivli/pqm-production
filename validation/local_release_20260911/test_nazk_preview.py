import hashlib
from contextlib import closing
import gc
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import urllib.request
import urllib.error
import time
from contextlib import ExitStack
from http.server import ThreadingHTTPServer
import unittest
from unittest.mock import patch
import nazk_preview
import server
from validation.nazk_preview_fixture import build

RIGHTS={'tasks.read','suppliers.read'}


class NazkPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.path=build(Path(self.temp.name)/'synthetic.sqlite3')
        server._SUPPLIER_RISK_CACHE['fingerprint']=None
    def tearDown(self): gc.collect(); self.temp.cleanup()
    def read(self,params=None,role='admin',permissions=RIGHTS,**kwargs):
        return nazk_preview.snapshot(self.path,params or {},role=role,permissions=permissions,risk_projector=server.supplier_risk_projection,**kwargs)

    def test_population_and_expected_reasons(self):
        out=self.read({'scope':['all']})
        self.assertEqual(out['counts']['population'],11)
        self.assertEqual(out['counts']['active_suppliers'],10)
        self.assertEqual(out['counts']['new_checks'],1)
        self.assertEqual(out['counts']['new_tasks'],1)
        expected=['eligible_new_cycle','waiting_response_existing_cycle','refuted_current_risk_covered',
                  'completed_current_risk_covered','existing_work','open_check_without_task',
                  'no_linked_active_applications','no_active_qualifications','activity_projection_conflict',
                  'current_manager_missing','historical_task_key_conflict']
        self.assertEqual([r['reason'] for r in out['items']],expected)

    def test_reads_do_not_change_any_table_or_file(self):
        before=self.path.read_bytes()
        with closing(sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True)) as con: dump=list(con.iterdump())
        for params in [{},{'scope':['all']},{'reason':['no_linked_active_applications']},{'state':['refuted']}]: self.read(params)
        self.assertEqual(self.path.read_bytes(),before)
        with closing(sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True)) as con: self.assertEqual(list(con.iterdump()),dump)

    def test_negative_write_and_attach_queries(self):
        for sql in ['DELETE FROM supplier_nazk_checks','UPDATE operational_tasks SET status=\'new\'',
                    'CREATE TABLE bad(id)','ATTACH DATABASE \'x.sqlite3\' AS bad','PRAGMA journal_mode=WAL']:
            with self.subTest(sql=sql),nazk_preview.read_connection(self.path) as con:
                with self.assertRaises(sqlite3.DatabaseError):con.execute(sql)

    def test_three_roles_require_both_read_grants(self):
        for role in ['admin','officer','viewer']:
            self.assertFalse(self.read(role=role)['can_launch'])
            with patch('nazk_preview.read_connection',side_effect=AssertionError('No DB access before permission gate')):
                for missing in RIGHTS:
                    with self.assertRaises(PermissionError):self.read(role=role,permissions=RIGHTS-{missing})

    def test_unknown_role_denied(self):
        with self.assertRaises(PermissionError):self.read(role='unknown')

    def test_no_refresh_force_apply_path_or_unknown_parameters(self):
        for key in ['refresh','force','apply','path','supplier_code','sql']:
            with self.subTest(key=key),self.assertRaises(ValueError):self.read({key:['1']})

    def test_filters_and_pagination_do_not_change_counters(self):
        initial=self.read()
        filtered=self.read({'search':['00000007']})
        self.assertEqual(filtered['total'],1)
        self.assertEqual(filtered['counts'],initial['counts'])
        self.assertEqual(self.read({'state':['refuted']})['total'],1)
        self.assertEqual(self.read({'scope':['inactive']})['total'],1)
        self.assertEqual(self.read({'group':['completed']})['total'],2)
        out=self.read({'scope':['all'],'size':['10'],'page':['2']})
        self.assertEqual((out['total'],len(out['items'])),(11,1))

    def test_minimal_payload(self):
        text=json.dumps(self.read({'scope':['all']}),ensure_ascii=False)
        for key in ['raw_json','manager_name','manager_tax_id','document_url','comment','task_key']:
            self.assertNotIn('"'+key+'"',text)

    def test_never_calls_reconciliation_ensure_or_migrate(self):
        with patch('nazk_workflow.reconcile_supplier_nazk',side_effect=AssertionError('write forbidden')),patch('nazk_workflow.reconcile_active_supplier_nazk',side_effect=AssertionError('write forbidden')),patch('nazk_workflow.ensure_submission_nazk_control',side_effect=AssertionError('write forbidden')),patch('operational_tasks.migrate',side_effect=AssertionError('write forbidden')):
            self.read()

    def test_bad_query_values(self):
        for params in [{'scope':['bad']},{'state':['bad']},{'group':['bad']},{'page':['0']},{'size':['201']},{'search':['x'*161]},{'state':['refuted','confirmed']}]:
            with self.subTest(params=params),self.assertRaises(ValueError):self.read(params)

    def test_authorizer_observes_reads_only(self):
        actions=[];self.read(audit=actions)
        self.assertTrue(actions)
        self.assertTrue(set(actions)<={sqlite3.SQLITE_SELECT,sqlite3.SQLITE_READ,sqlite3.SQLITE_FUNCTION,sqlite3.SQLITE_TRANSACTION,sqlite3.SQLITE_RECURSIVE})

    def test_legacy_null_manager_open_check_is_not_duplicated(self):
        with closing(sqlite3.connect(self.path)) as con, con:con.execute('UPDATE supplier_nazk_checks SET manager_id=NULL WHERE id=6')
        row=self.read({'search':['00000006']})['items'][0]
        self.assertEqual(row['reason'],'open_check_without_task')
        self.assertFalse(row['potential_new_check'])

    def test_new_source_does_not_silently_reopen_refuted(self):
        with closing(sqlite3.connect(self.path)) as con, con:con.execute("INSERT INTO nazk_registry(source_id,full_name,raw_json) VALUES ('SYN-NEW','ТЕСТОВА ОСОБА 3','{}')")
        row=self.read({'search':['00000003']})['items'][0]
        self.assertEqual(row['reason'],'refuted_requires_new_basis_review')
        self.assertFalse(row['potential_new_check'])


class NazkPreviewHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.path=build(Path(cls.temp.name)/'http-synthetic.sqlite3')
        cls.patches=ExitStack()
        for key,value in {'DB_PATH':cls.path,'AUTH_ENABLED':False,'IS_WEB_ENV':False,'SANDBOX_MODE':False,
                          'LOCAL_ROLE_IMPERSONATION':True,'SAFE_MODE':True}.items():
            cls.patches.enter_context(patch.object(server,key,value))
        server._SUPPLIER_RISK_CACHE['fingerprint']=None
        class QuietHandler(server.Handler):
            def log_message(self,*args):pass
        cls.httpd=ThreadingHTTPServer(('127.0.0.1',0),QuietHandler)
        cls.thread=threading.Thread(target=cls.httpd.serve_forever,daemon=True);cls.thread.start()
        cls.url=f'http://127.0.0.1:{cls.httpd.server_port}'
    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown();cls.httpd.server_close();cls.thread.join(timeout=2)
        cls.patches.close();gc.collect();cls.temp.cleanup()
    def request(self,path='/api/operational-tasks/nazk-preview',role='admin',method='GET'):
        req=urllib.request.Request(self.url+path,method=method,headers={'X-PQM-Local-Role':role},
                                   data=b'{}' if method!='GET' else None)
        try:
            with urllib.request.urlopen(req,timeout=5) as response:return response.status,json.load(response)
        except urllib.error.HTTPError as error:
            with error:return error.code,json.load(error)

    def test_admin_officer_viewer_direct_get(self):
        for role in ['admin','officer','viewer']:
            code,out=self.request(role=role)
            self.assertEqual(code,200);self.assertTrue(out['read_only']);self.assertFalse(out['can_launch'])

    def test_secondary_supplier_permission_denied_before_repository(self):
        context={'code':'viewer','active':True,'permissions':{'tasks.read':True,'suppliers.read':False}}
        with patch('auth_access.effective',return_value=context),patch('nazk_preview.snapshot',side_effect=AssertionError('No repository access')):
            self.assertEqual(self.request(role='viewer')[0],403)

    def test_primary_task_permission_denied(self):
        context={'code':'viewer','active':True,'permissions':{'tasks.read':False,'suppliers.read':True}}
        with patch('auth_access.effective',return_value=context),patch('nazk_preview.snapshot',side_effect=AssertionError('No repository access')):
            self.assertEqual(self.request(role='viewer')[0],403)

    def test_inactive_account_denied(self):
        with patch('auth_access.effective',return_value={'code':'viewer','active':False,'permissions':dict.fromkeys(RIGHTS,True)}):
            self.assertEqual(self.request(role='viewer')[0],403)

    def test_unauthenticated_denied(self):
        with patch.object(server,'AUTH_ENABLED',True),patch('server.auth_accounts',return_value={'synthetic':{'active':True,'role':'viewer','secret':'not-a-real-secret'}}):
            self.assertEqual(self.request()[0],401)

    def test_production_has_no_route_or_ui_capability(self):
        def authorized(handler):
            handler.auth_user='synthetic';handler.auth_role='admin';handler.auth_officer_id=None;return True
        with patch.object(server,'IS_WEB_ENV',True),patch.object(server.Handler,'_authorize',authorized):
            self.assertEqual(self.request()[0],404)
            self.assertFalse(self.request('/api/auth/me')[1]['ui_features']['nazk_preview'])

    def test_no_http_method_can_create_preview_work(self):
        before=self.path.read_bytes()
        for method in ['POST','PATCH','DELETE']:
            self.assertNotEqual(self.request(method=method)[0],200)
        self.assertEqual(self.path.read_bytes(),before)

    def test_http_get_filter_refresh_preserves_database(self):
        before=self.path.read_bytes()
        for query in ['','?scope=all','?state=refuted','?search=00000007','?group=completed']:
            self.assertEqual(self.request('/api/operational-tasks/nazk-preview'+query)[0],200)
        self.assertEqual(self.path.read_bytes(),before)

    def test_authenticated_session_does_not_persist_presence(self):
        # This exercises the real cookie/session authorization path, not local-role impersonation.
        for role in ['admin','officer','viewer']:
            username='synthetic-'+role;token='synthetic-preview-session-'+role
            with closing(sqlite3.connect(self.path)) as con,con:
                con.execute('''INSERT OR REPLACE INTO auth_users
                  (username,password_hash,role,officer_id,active,created_at,updated_at,created_by,last_seen_at)
                  VALUES (?,? ,?,NULL,1,'2026-01-01','2026-01-01','synthetic','UNCHANGED')''',
                  (username,'synthetic-not-a-password',role))
            session={'username':username,'expires_at':time.time()+3600,'last_seen':0,'last_seen_persisted':0}
            with server.AUTH_SESSIONS_LOCK:server.AUTH_SESSIONS[token]=session
            try:
                with closing(sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True)) as con:before=list(con.iterdump())
                with patch.object(server,'AUTH_ENABLED',True):
                    req=urllib.request.Request(self.url+'/api/operational-tasks/nazk-preview',headers={'Cookie':server.AUTH_COOKIE+'='+token})
                    with urllib.request.urlopen(req,timeout=5) as response:
                        self.assertEqual(response.status,200);self.assertTrue(json.load(response)['read_only'])
                with closing(sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True)) as con:
                    self.assertEqual(list(con.iterdump()),before)
                    self.assertEqual(con.execute('SELECT last_seen_at FROM auth_users WHERE username=?',(username,)).fetchone()[0],'UNCHANGED')
                self.assertEqual(session['last_seen_persisted'],0)
                # Other authenticated reads retain their existing presence behavior.
                with patch.object(server,'AUTH_ENABLED',True):
                    normal=urllib.request.Request(self.url+'/api/auth/me',headers={'Cookie':server.AUTH_COOKIE+'='+token})
                    with urllib.request.urlopen(normal,timeout=5) as response:self.assertEqual(response.status,200)
                self.assertGreater(session['last_seen_persisted'],0)
            finally:
                with server.AUTH_SESSIONS_LOCK:server.AUTH_SESSIONS.pop(token,None)


if __name__=='__main__':unittest.main(verbosity=2)
