"""HTTP acceptance on synthetic data only; also used by the Docker STOP/GO gate."""
import base64
import http.client
import json
import os
from pathlib import Path
import sqlite3
import socket
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
# Deterministic, offline HTTP startup for both fixture and child process.
os.environ['PQM_TEST_NETWORK_ISOLATION']='1'
os.environ['PYTHONPATH']=str(ROOT/'validation/test_runtime')
socket.getfqdn=lambda name='':name or 'localhost'
TEMP=tempfile.TemporaryDirectory(prefix='pqm-web-acceptance-')
os.environ.update(PQM_ENV='test_web',PQM_DATA_DIR=TEMP.name,PQM_DB_PATH=TEMP.name+'/test.sqlite3',PQM_AUTH_ENABLED='1',PQM_USERS_JSON='',PQM_ENABLE_SCHEDULER='0',PQM_ENABLE_PROZORRO_SCHEDULER='0',PQM_ENABLE_VIOLATION_SCHEDULER='0',PQM_ENABLE_NAZK_SCHEDULER='0',PQM_ENABLE_GOOGLE='0',PQM_ENABLE_BIDS_UPDATE='0',PQM_ENABLE_POWERBI='0',PQM_ENABLE_BROWSER='0',PQM_BIDS_MODE='disabled')
import server
from integration.safe_startup import require_current_schema

PASSWORD='Synthetic-test-only-2026'
def fixture():
    shutil.copytree(ROOT/'templates',Path(TEMP.name)/'templates',dirs_exist_ok=True)
    server.init_db();server.init_reference_tables(server.DB_PATH)
    from migrations.additive import migrate
    migrate(server.DB_PATH,json.loads((ROOT/'migrations/target_schema.json').read_text()),Path(TEMP.name)/'backups')
    with server.db() as con:
        for i,name in [(1,'Synthetic Officer'),(2,'Other Officer')]:
            con.execute('INSERT INTO authorized_officers(id,full_name,role,active,created_at,updated_at) VALUES (?,?,?,1,?,?)',(i,name,'УО','before','before'))
        for username,role,officer in [('fixture-admin','admin',None),('fixture-officer','officer',1),('fixture-officer-b','officer',2),('fixture-viewer','viewer',None)]:
            con.execute('INSERT INTO auth_users(username,password_hash,role,officer_id,active,created_at,updated_at,created_by) VALUES (?,?,?,?,1,?,?,?)',(username,server.hash_password(PASSWORD),role,officer,'before','before','fixture'))
        con.execute("INSERT INTO frameworks(id,pretty_id,dk_code,raw_json,synced_at) VALUES ('framework','UA-F-SYNTHETIC','12345678-9','{}','before')")
        con.execute("INSERT INTO framework_officers(framework_id,officer,synced_at) VALUES ('framework','Synthetic Officer','before')")
        for sid,status in [('pending','pending'),('admitted','active'),('rejected','unsuccessful')]:
            con.execute('INSERT INTO submissions(id,framework_id,supplier_name,supplier_code,date_published,qualification_id,raw_json,synced_at) VALUES (?,?,?,?,?,?,?,?)',(sid,'framework','Synthetic Supplier','00000000','2026-09-05T10:00:00Z','q-'+sid,'{}','before'))
            con.execute('INSERT INTO qualifications(id,framework_id,submission_id,status,raw_json,synced_at) VALUES (?,?,?,?,?,?)',('q-'+sid,'framework',sid,status,'{}','before'))
            con.execute('INSERT INTO application_fields(submission_id,protocol_officer) VALUES (?,?)',(sid,'Synthetic Officer'))
    require_current_schema(server.DB_PATH,ROOT)

class WebAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture()
        cls.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        cls.port=cls.http.server_address[1]
        threading.Thread(target=cls.http.serve_forever,daemon=True).start()
    @classmethod
    def tearDownClass(cls):cls.http.shutdown();cls.http.server_close()
    def request(self,path,role='admin',method='GET',data=None,cookie=None):
        headers={}
        if cookie:headers['Cookie']=cookie
        elif role:headers['Authorization']='Basic '+base64.b64encode(('fixture-'+role+':'+PASSWORD).encode()).decode()
        body=None
        if data is not None:body=json.dumps(data);headers['Content-Type']='application/json'
        client=http.client.HTTPConnection('127.0.0.1',self.port,timeout=15)
        client.request(method,path,body,headers);response=client.getresponse();raw=response.read();status=response.status;out=dict(response.getheaders());client.close()
        return status,json.loads(raw) if 'application/json' in out.get('Content-Type','') else raw,out
    def test_01_login_gate_and_private_paths(self):
        self.assertEqual(200,self.request('/',None)[0]);self.assertEqual(401,self.request('/api/applications',None)[0])
        for path in ['/server.py','/data/test.sqlite3','/.git/config','/migrations/target_schema.json']:
            self.assertEqual(404,self.request(path,None)[0],path)
        status,_,headers=self.request('/api/login',None,'POST',{'username':'fixture-admin','password':PASSWORD})
        self.assertEqual(200,status);cookie=headers['Set-Cookie'].split(';')[0]
        self.assertIn('HttpOnly',headers['Set-Cookie']);self.assertIn('Secure',headers['Set-Cookie'])
        self.assertEqual(200,self.request('/api/account',None,cookie=cookie)[0])
        self.assertEqual(204,self.request('/api/logout',None,'POST',{},cookie)[0])
        self.assertEqual(401,self.request('/api/auth/me',None,cookie=cookie)[0])
    def test_02_read_modules_and_templates(self):
        for path in ['/api/health','/api/auth/me','/api/account','/api/applications','/api/application-history','/api/application-profiles','/api/admin/access-roles','/api/admin/users','/api/admin/schema','/api/admin/frameworks','/api/admin/templates','/api/uo-work-queue','/api/violation-reports','/api/chats','/api/table-widths','/api/runtime-features','/api/supplier-profile/00000000']:
            self.assertEqual(200,self.request(path)[0],path)
        templates=self.request('/api/admin/templates')[1]
        self.assertEqual(7,len(templates['items']))
        self.assertTrue({'amcu_exclusion_protocol','termination_exclusion_protocol','nazk_supplier_request'} <= {x['key'] for x in templates['items']})
        for item in templates['items']:
            self.assertEqual(200,self.request('/api/admin/templates/'+item['key']+'/download')[0])
        self.assertEqual(404,self.request('/api/nonexistent')[0])
    def test_03_roles_and_final_lock(self):
        for role in ['officer','viewer']:
            self.assertEqual(403,self.request('/api/admin/users',role)[0])
            self.assertEqual(403,self.request('/api/admin/table-widths',role,'POST',{'table_key':'amcu','widths':{}})[0])
        self.assertEqual(403,self.request('/api/applications/pending','viewer','PATCH',{'notes':'unauthorized'})[0])
        self.assertEqual(200,self.request('/api/applications/pending','officer','PATCH',{'notes':'allowed fixture'})[0])
        for role in ['officer','admin']:
            for sid in ['admitted','rejected']:
                self.assertEqual(409,self.request('/api/applications/'+sid,role,'PATCH',{'notes':'forbidden'})[0])
        with server.db() as con:con.execute("UPDATE application_fields SET protocol_officer='Other Officer' WHERE submission_id='pending'")
        self.assertEqual(200,self.request('/api/applications/pending','officer','PATCH',{'notes':'other officer'})[0])
        with server.db() as con:con.execute("UPDATE application_fields SET protocol_officer='Synthetic Officer' WHERE submission_id='pending'")
        self.assertEqual(200,self.request('/api/applications/pending','officer-b','PATCH',{'notes':'A assignment reviewed by B'})[0])
        with server.db() as con:
            server.assert_protocol_scope(con,['pending'],'officer',2)
            con.execute("UPDATE authorized_officers SET active=0 WHERE id=2")
        self.assertEqual(403,self.request('/api/applications/pending','officer-b','PATCH',{'notes':'inactive forbidden'})[0])
        with server.db() as con:
            with self.assertRaises(PermissionError):server.assert_protocol_scope(con,['pending'],'officer',2)
            con.execute("UPDATE authorized_officers SET active=1 WHERE id=2")
            con.execute("INSERT INTO auth_role_permissions VALUES ('officer','applications.edit',0,'fixture','fixture')")
        self.assertEqual(403,self.request('/api/applications/pending','officer','PATCH',{'notes':'granular denial'})[0])
        with server.db() as con:
            con.execute("DELETE FROM auth_role_permissions WHERE role_code='officer' AND permission_key='applications.edit'")
            con.execute("INSERT INTO auth_role_permissions VALUES ('viewer','applications.edit',1,'fixture','fixture')")
        self.assertEqual(403,self.request('/api/applications/pending','viewer','PATCH',{'notes':'viewer override forbidden'})[0])
        with server.db() as con:
            con.execute("DELETE FROM auth_role_permissions WHERE role_code='viewer' AND permission_key='applications.edit'")
    def test_04_chat_and_account_isolation(self):
        status,result,_=self.request('/api/chats','viewer','POST',{'members':['fixture-admin'],'title':''})
        self.assertIn(status,[200,201]);chat=result['id']
        status,_,_=self.request(f'/api/chats/{chat}/messages','viewer','POST',{'body':'Synthetic smoke message','submission_id':'pending','attachment':{'filename':'fixture.txt','content_type':'text/plain','content':base64.b64encode(b'fixture').decode()}})
        self.assertIn(status,[200,201])
        self.assertEqual(404,self.request(f'/api/chats/{chat}/messages','officer')[0])
        message=self.request(f'/api/chats/{chat}/messages')[1]['items'][0]
        self.assertEqual('pending',message['submission']['id']);self.assertEqual(1,len(message['attachments']))
        self.assertEqual(200,self.request(f'/api/chats/{chat}/read','admin','POST',{})[0])
        self.assertTrue(self.request(f'/api/chats/{chat}/messages','viewer')[1]['items'][0]['read_by_all'])
        self.assertEqual(200,self.request('/api/account','viewer','PATCH',{'display_name':'Viewer Smoke','presence_status':'away','start_view':'applications','density':'comfortable'})[0])
        self.assertEqual('Viewer Smoke',self.request('/api/account','viewer')[1]['display_name'])
        self.assertNotEqual('Viewer Smoke',self.request('/api/account','officer')[1]['display_name'])
    def test_05_flags_and_integrity(self):
        flags=self.request('/api/runtime-features')[1]
        for key in ['bids_update','powerbi','google','scheduler','nazk_scheduler']:self.assertFalse(flags[key],key)
        with server.db() as con:
            self.assertEqual('ok',con.execute('pragma integrity_check').fetchone()[0]);self.assertEqual([],con.execute('pragma foreign_key_check').fetchall())

    def test_06_formed_protocol_lifecycle(self):
        import formed_protocols
        from protocol_docx import build_protocol_docx
        from docx import Document
        os.environ['PQM_PROTOCOL_ENGINE']='template_only'
        directory=Path(TEMP.name)/'protocol-fixture'
        with server.db() as con:
            con.execute("UPDATE application_fields SET protocol_number='SMOKE',protocol_date='2026-09-06',protocol_decision='admit' WHERE submission_id='pending'")
        with server.db() as con:
            con.execute('BEGIN IMMEDIATE')
            item=dict(con.execute("SELECT * FROM application_fields WHERE submission_id='pending'").fetchone())
            item.update(id='pending',supplier_name='Synthetic Supplier',supplier_code='00000000',framework_id='framework',pretty_id='UA-F-SYNTHETIC')
            payload=dict(protocol_number='SMOKE',protocol_date='2026-09-06',officer='Synthetic Officer',date_from='2026-09-01',date_to='2026-09-06',items=[item])
            first=formed_protocols.create(con,[item],payload,directory,build_protocol_docx,'fixture-admin')
            with self.assertRaises(ValueError):formed_protocols.guard_edit(con,'pending',{'protocol_number':'CHANGED'})
            first_path=directory/con.execute('SELECT document_path FROM formed_protocols WHERE id=?',(first['protocol_id'],)).fetchone()[0]
            # The template also has two small document-header layout tables.
            self.assertEqual(3,len([t for t in Document(first_path).tables if len(t.columns)>2]))
            with self.assertRaises(ValueError):formed_protocols.cancel(con,first['protocol_id'],'fixture-admin',False,'fixture')
            formed_protocols.cancel(con,first['protocol_id'],'fixture-admin',True,'Synthetic cancellation')
            second=formed_protocols.create(con,[item],payload,directory,build_protocol_docx,'fixture-admin')
            detail=formed_protocols.detail(con,second['protocol_id'],directory)
            self.assertEqual(2,detail['version']);self.assertEqual(2,len(detail['history']))
            self.assertTrue(all(x['document_available'] for x in detail['history']))
            self.assertTrue(first_path.is_file())
            formed_protocols.cancel(con,second['protocol_id'],'fixture-admin',True,'Fixture cleanup')

    def test_07_real_startup_restart_and_preferences(self):
        columns=[dict(key=k,visible=True,width=160,order=i) for i,k in enumerate(server.HISTORY_COLUMN_KEYS)]
        server.history_column_settings('fixture-admin',columns)
        self.assertEqual([],server.history_column_settings('fixture-viewer')['columns'])
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        environment=dict(os.environ,HOST='127.0.0.1',PORT=str(port),PYTHONUNBUFFERED='1')
        for attempt in range(2):
            log=Path(TEMP.name)/f'startup-{attempt}.log'
            with log.open('w') as output:
                process=subprocess.Popen([sys.executable,str(ROOT/'server.py')],cwd=ROOT,env=environment,stdout=output,stderr=subprocess.STDOUT)
                try:
                    deadline=time.monotonic()+25
                    while time.monotonic()<deadline:
                        self.assertIsNone(process.poll(),log.read_text())
                        try:
                            client=http.client.HTTPConnection('127.0.0.1',port,timeout=1)
                            client.request('GET','/api/health');response=client.getresponse();response.read();client.close()
                            if response.status==200:break
                        except OSError:pass
                        time.sleep(.1)
                    else:self.fail('Startup timeout: '+log.read_text())
                    self.assertEqual(columns,server.history_column_settings('fixture-admin')['columns'])
                    with server.db() as con:
                        self.assertEqual('Viewer Smoke',con.execute("SELECT display_name FROM user_preferences WHERE username='fixture-viewer'").fetchone()[0])
                finally:
                    process.terminate()
                    try:process.wait(timeout=10)
                    except subprocess.TimeoutExpired:process.kill();process.wait()
            text=log.read_text()
            self.assertNotIn('Traceback',text);self.assertNotIn('database is locked',text)
            self.assertIn('auth=True',text)

    def test_08_appeal_completion_survives_two_refreshes(self):
        payload={'id':'synthetic-appeal','violationReportID':'UA-D-SYNTHETIC','status':'pending',
                 'authority':{'identifier':{'id':server.ORGANIZER_EDRPOU},'name':'Synthetic authority'},
                 'defendants':[{'identifier':{'id':'00000000'},'name':'Synthetic Supplier'}],
                 'details':{'reason':'goodsNonCompliance','description':'Synthetic review'},
                 'datePublished':'2026-01-01T10:00:00Z','defendantPeriod':{'endDate':'2026-01-05T10:00:00Z'}}
        context={'available':True,'dk_code':'30190000-7','cpv':'30190000-7','subject':'Synthetic procurement'}
        with patch.object(server,'api_get',return_value={'data':payload}),patch.object(server,'_resolve_violation_tender',return_value=('UA-SYNTHETIC','')),patch.object(server,'build_procurement_context',return_value=context):
            server.save_violation_report(payload)
            server.save_violation_review('synthetic-appeal',{'review_status':'in_review','internal_decision':'warning','assigned_officer_id':1,'decision_justification':'Synthetic manual justification'},'fixture-admin')
            server.complete_violation_review('synthetic-appeal','fixture-admin')
            original=server.violation_report_detail('synthetic-appeal',refresh=False)
            snapshot=original['decision_context_snapshot']
            for attempt in range(2):
                payload['dateModified']=f'2026-09-0{attempt+5}T10:00:00Z'
                if attempt:payload['decisions']=[{'resolution':'satisfied','description':'Synthetic official decision'}]
                result=server.violation_report_detail('synthetic-appeal',refresh=True)
                self.assertEqual(snapshot,result['decision_context_snapshot'])
                self.assertEqual('30190000-7',result['procurement_context']['dk_code'])
                self.assertEqual('Synthetic manual justification',result['review']['decision_justification'])
                self.assertTrue(result['local_review_completed']);self.assertTrue(result['is_read_only'])
                self.assertEqual(bool(attempt),result['has_official_decision'])

    def test_10_historical_read_only_and_chat(self):
        import historical_applications
        sid='0'*31+'1'
        with server.db() as con:
            con.execute("INSERT INTO submissions(id,framework_id,supplier_name,supplier_code,date_published,raw_json,synced_at) VALUES (?,?,?,?,?,?,?)",(sid,'framework','Synthetic historical','00000000','2024-01-01','{}','fixture'))
            con.execute("INSERT INTO application_fields(submission_id,protocol_officer) VALUES (?,?)",(sid,'Other Officer'))
            before=tuple(con.execute('SELECT * FROM application_fields WHERE submission_id=?',(sid,)).fetchone())
        with patch.object(historical_applications,'manifest',return_value={'version':1,'applications':{sid:{'source_row':2}}}):
            for role in ['officer','admin']:
                status,payload,_=self.request('/api/applications/'+sid,role,'PATCH',{'notes':'blocked historical'})
                self.assertEqual(409,status);self.assertTrue(payload['historical_read_only'])
            status,payload,_=self.request('/api/chats','officer','POST',{'members':['fixture-admin']})
            self.assertIn(status,[200,201]);chat=payload['id']
            status,_,_=self.request(f'/api/chats/{chat}/messages','officer','POST',{'body':'Synthetic historical selection','submission_id':sid})
            self.assertIn(status,[200,201])
            self.assertEqual(sid,self.request(f'/api/chats/{chat}/messages')[1]['items'][0]['submission']['id'])
        with server.db() as con:
            self.assertEqual(before,tuple(con.execute('SELECT * FROM application_fields WHERE submission_id=?',(sid,)).fetchone()))

    def test_11_new_decision_records_canonical_officer(self):
        sid='canonical-decision-fixture'
        with server.db() as con:
            con.execute("INSERT INTO submissions(id,framework_id,supplier_name,supplier_code,date_published,raw_json,synced_at) VALUES (?,?,?,?,?,?,?)",(sid,'framework','Synthetic new','00000000','2026-09-14','{}','fixture'))
            con.execute("INSERT INTO application_fields(submission_id,protocol_officer,compliance_status) VALUES (?,?,'rejected')",(sid,'Other Officer'))
            expected=server.canonical_officer_identity(con,'fixture-officer',1)
        status,payload,_=self.request('/api/applications/'+sid,'officer','PATCH',{'protocol_decision':'reject'})
        self.assertEqual(200,status,payload)
        with server.db() as con:
            actual=con.execute('SELECT review_officer FROM application_fields WHERE submission_id=?',(sid,)).fetchone()[0]
        self.assertEqual(expected,actual);self.assertNotEqual('fixture-officer',actual)
        self.assertEqual('Synthetic OFFICER',actual)

    def test_09_public_favicons(self):
        from html.parser import HTMLParser
        import struct
        class IconLinks(HTMLParser):
            def __init__(self):super().__init__();self.items=[]
            def handle_starttag(self, tag, attrs):
                data=dict(attrs)
                if tag=='link' and data.get('rel') in {'icon','apple-touch-icon'}:self.items.append(data)
        status,html,_=self.request('/',None)
        self.assertEqual(200,status)
        links=IconLinks();links.feed(html.decode())
        expected={'/assets/pqm-search-icon.png':192,'/assets/pqm-tab-icon.png':32}
        self.assertEqual(set(expected),{item['href'] for item in links.items})
        for item in links.items:
            status,raw,headers=self.request(item['href'],None)
            self.assertEqual(200,status)
            self.assertEqual('image/png',headers['Content-Type'])
            self.assertEqual(b'\x89PNG\r\n\x1a\n',raw[:8])
            size=expected[item['href']]
            self.assertEqual((size,size),struct.unpack('>II',raw[16:24]))
            if item['rel']=='icon':self.assertEqual(f'{size}x{size}',item['sizes'])

if __name__=='__main__':
    if '--serve' in sys.argv:
        fixture()
        # A populated heading is essential for responsive checks: an empty
        # appeals registry hides authority cards and masks a collapsed table.
        with server.db() as con:
            for index in range(12):
                con.execute('''INSERT INTO violation_reports
                    (id,report_id,status,date_published,author_name,defendant_name,
                     authority_name,authority_code,reason,raw_json,synced_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                    (f'layout-{index}',f'UA-D-SYNTHETIC-{index:03d}','pending',
                     '2026-09-10T08:00:00Z','Synthetic Customer','Synthetic Supplier',
                     f'Synthetic authority {index%3+1}',f'0000000{index%3+1}',
                     'goodsNonCompliance','{}','fixture'))
        print('Synthetic preview: http://127.0.0.1:18080',flush=True)
        server.ThreadingHTTPServer(('127.0.0.1',18080),server.Handler).serve_forever()
    else:unittest.main(verbosity=2)
