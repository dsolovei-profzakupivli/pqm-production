"""Current protocol read projection; all mutations use disposable synthetic DBs."""
from contextlib import closing
import hashlib
import http.client
import json
from pathlib import Path
import threading
import subprocess
from http.server import ThreadingHTTPServer
import unittest
from unittest.mock import patch
import operational_tasks as tasks
import task_documents as td
import server
import test_task_documents as fixtures


class CurrentProtocolTests(unittest.TestCase):
    def setUp(self):
        self.con,self.item=fixtures.fixture();self.addCleanup(self.con.close)
        self.item.update(task_type='amcu_exclusion',protocol_number='701',protocol_date='2026-09-14')

    def add(self,ident,version,stamp,kind=td.AMCU_PROTOCOL_KEY,day='2026-09-14',task=None,status='generated'):
        task=task or self.item['id']
        self.con.execute('''INSERT INTO generated_documents
          (id,task_id,supplier_code,document_type,template_key,template_reference,filename,storage_name,
           created_at,created_by,generation_provider,status,document_date,version,sha256,metadata_json)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
          (ident,task,'43897155',kind,kind,'synthetic','АМКУ_43897155_701_v'+str(version)+'.docx',
           ident+'/synthetic.docx',stamp,'test','docx_local',status,day,version,'synthetic','{}'))

    def summary(self):
        return tasks.task_ui_summary(self.con,self.item,{'generated_documents'})

    def test_single_and_three_versions_match_card_order(self):
        self.assertEqual(self.summary()['officer_decision']['documents'],[])
        for version in range(1,4):
            self.add(str(version)*32,version,f'2026-09-14T10:00:0{version}+00:00')
            card=td.documents(self.con,self.item['id'])
            self.assertEqual(self.summary()['officer_decision']['documents'],[card[0]])
        self.assertEqual([d['version'] for d in card],[3,2,1])
        self.assertEqual([d['version'] for d in self.summary()['officer_decision']['documents']],[3])

    def test_distinct_protocol_types_and_supplier_requests_are_not_collapsed(self):
        self.add('a'*32,1,'2026-09-14T10:00:01Z')
        self.add('b'*32,2,'2026-09-14T10:00:02Z')
        self.add('c'*32,1,'2026-09-14T10:00:03Z',kind=td.TERMINATION_PROTOCOL_KEY)
        for i in range(2):self.add(str(i)*32,i+1,f'2026-09-14T10:00:0{4+i}Z',kind=td.KEY)
        result=self.summary()
        self.assertEqual({d['id'] for d in result['officer_decision']['documents']},{'b'*32,'c'*32})
        self.assertEqual(len(result['supplier_requests']),2)

    def test_latest_creation_not_largest_version_or_protocol_date(self):
        self.add('a'*32,9,'2026-09-14T10:00:01Z',day='2026-09-14')
        self.add('b'*32,1,'2026-09-15T10:00:01Z',day='2026-09-13')
        self.assertEqual(self.summary()['officer_decision']['documents'][0]['id'],'b'*32)
        self.assertEqual(td.documents(self.con,self.item['id'])[0]['id'],'b'*32)

    def test_tied_timestamp_uses_existing_card_tiebreak_and_task_scope(self):
        for ident,version in [('a'*32,1),('b'*32,2)]:self.add(ident,version,'2026-09-14T10:00:01Z')
        self.add('c'*32,1,'2099-01-01T00:00:00Z',task='other-task')
        self.assertEqual(self.summary()['officer_decision']['documents'][0]['id'],'b'*32)

    def test_projection_read_only_preserves_rows_statuses_and_events(self):
        for i in range(1,4):self.add(str(i)*32,i,f'2026-09-14T10:00:0{i}Z')
        before='\n'.join(self.con.iterdump())
        for _ in range(3):self.summary()
        self.assertEqual(before,'\n'.join(self.con.iterdump()))
        self.assertEqual([r[0] for r in self.con.execute('SELECT status FROM generated_documents')],['generated']*3)

    def test_actual_table_and_card_renderers_single_repeated_and_distinct_types(self):
        for version in range(1,4):
            self.add(str(version)*32,version,f'2026-09-14T10:00:0{version}Z')
            item={**self.item,**self.summary(),'document_generation':{
                'documents':td.documents(self.con,self.item['id'])}}
            run=subprocess.run(['node','validation/amcu_current_protocol_ui.cjs'],
                input=json.dumps(item),text=True,capture_output=True,timeout=15)
            self.assertEqual(run.returncode,0,run.stderr)
        self.add('f'*32,1,'2026-09-14T10:00:04Z',kind=td.TERMINATION_PROTOCOL_KEY)
        item={**self.item,**self.summary(),'document_generation':{'documents':[
            d for d in td.documents(self.con,self.item['id']) if d['document_type']==td.AMCU_PROTOCOL_KEY]}}
        run=subprocess.run(['node','validation/amcu_current_protocol_ui.cjs'],
            input=json.dumps(item),text=True,capture_output=True,timeout=15)
        self.assertEqual(run.returncode,0,run.stderr)

    def test_three_real_generations_preserve_files_and_all_generation_events(self):
        fixtures.TaskDocumentTests.setUpClass()
        fixture=fixtures.TaskDocumentTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        original=td.generate_amcu;created=[];files=[]
        def three(*args,**kw):
            for _ in range(3):
                doc=original(*args,**kw);created.append(doc)
                files.append((td.download(args[0],doc['task_id'],doc['id'],args[3])[0],doc['sha256']))
            return created[0]
        with patch.object(td,'generate_amcu',side_effect=three):
            fixture.test_amcu_activation_ready_context_generation_and_real_hyperlink()
        result=tasks.task_ui_summary(fixture.con,{'id':fixture.item['id'],'task_type':'amcu_exclusion'}, {'generated_documents'})
        self.assertEqual([d['version'] for d in result['officer_decision']['documents']],[3])
        self.assertEqual([d['version'] for d in td.documents(fixture.con,fixture.item['id'])],[3,2,1])
        self.assertEqual([r[0] for r in fixture.con.execute('SELECT event_type FROM operational_task_events')],['amcu_exclusion_protocol_generated']*3)
        for file,digest in files:self.assertEqual(hashlib.sha256(file.read_bytes()).hexdigest(),digest)

    def test_http_list_current_detail_history_and_read_only(self):
        for i in range(1,4):self.add(str(i)*32,i,f'2026-09-14T10:00:0{i}Z')
        def remove_synthetic_rows():
            with closing(server.db()) as full:
                with full:
                    full.execute('DELETE FROM generated_documents WHERE task_id=?',(self.item['id'],))
                    full.execute('DELETE FROM operational_tasks WHERE id=?',(self.item['id'],))
        self.addCleanup(remove_synthetic_rows)
        with closing(server.db()) as full:
            with full:
                full.execute('''INSERT INTO operational_tasks
                  (id,task_key,task_type,supplier_code,supplier_name_snapshot,status,created_at,updated_at,protocol_number,protocol_date)
                  VALUES(?,?,?,?,?,?,?,?,?,?)''',(self.item['id'],'test:current-amcu','amcu_exclusion','43897155','Synthetic',
                  'ready_for_document','2026-09-14','2026-09-14','701','2026-09-14'))
                for row in self.con.execute('SELECT * FROM generated_documents'):
                    values=dict(row);full.execute('INSERT INTO generated_documents('+','.join(values)+') VALUES('+','.join('?' for _ in values)+')',list(values.values()))
        def snapshot():
            with closing(server.db()) as full:return '\n'.join(full.iterdump())
        before=snapshot()
        with patch.object(server,'AUTH_ENABLED',False),patch.object(server,'LOCAL_ROLE_IMPERSONATION',True):
            service=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
            thread=threading.Thread(target=service.serve_forever,daemon=True);thread.start()
            try:
                output=[]
                for path in ('/api/operational-tasks?type=amcu_exclusion','/api/operational-tasks/'+self.item['id']):
                    with closing(http.client.HTTPConnection('127.0.0.1',service.server_port,timeout=10)) as client:
                        client.request('GET',path,headers={'X-PQM-Local-Role':'admin'})
                        response=client.getresponse();self.assertEqual(response.status,200);output.append(json.loads(response.read()))
            finally:service.shutdown();service.server_close();thread.join(5)
        row=next(r for r in output[0]['items'] if r['id']==self.item['id'])
        self.assertEqual([d['version'] for d in row['officer_decision']['documents']],[3])
        self.assertEqual([d['version'] for d in output[1]['officer_decision']['documents']],[3])
        self.assertEqual([d['version'] for d in output[1]['document_generation']['documents']],[3,2,1])
        self.assertEqual(before,snapshot())
