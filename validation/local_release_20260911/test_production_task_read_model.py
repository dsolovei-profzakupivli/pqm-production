"""Additive UI read model: synthetic sources, no live DB or network."""
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import unittest
from unittest.mock import patch

import operational_tasks as tasks


ROOT=Path(__file__).resolve().parent
if not (ROOT/'app.js').exists():
    ROOT=ROOT.parents[1]


def fixture():
    con=sqlite3.connect(':memory:'); con.row_factory=sqlite3.Row
    con.create_function('DIGITS',1,lambda value:''.join(x for x in str(value or '') if x.isdigit()))
    con.executescript('''
      CREATE TABLE amcu_registry(row_key TEXT,decision_no TEXT,decision_date TEXT,court_case_no TEXT);
      CREATE TABLE operational_task_amcu_decisions(task_id TEXT,amcu_decision_id TEXT,extract_url TEXT);
      CREATE TABLE qualifications(id TEXT,submission_id TEXT,framework_id TEXT);
      CREATE TABLE submissions(id TEXT,supplier_code TEXT);
      CREATE TABLE frameworks(id TEXT,status TEXT,raw_json TEXT);
      CREATE TABLE registry_contracts(id TEXT,qualification_id TEXT,supplier_code TEXT,status TEXT,framework_id TEXT);
      CREATE TABLE operational_task_qualifications(task_id TEXT,qualification_id TEXT);
      INSERT INTO frameworks VALUES('f','active','{}');
      INSERT INTO submissions VALUES('s','123');
      INSERT INTO qualifications VALUES('q1','s','f'),('q2','s','f'),('q3','s','f');
      INSERT INTO registry_contracts VALUES('c1','q1','123','active','f'),('c2','q1','123','active','f'),
        ('c3','q2','123','terminated','f'),('c4','q3','123','active','f');
      INSERT INTO operational_task_qualifications VALUES('t','q1'),('t','q1'),('t','q2');
      INSERT INTO amcu_registry VALUES('a','D1','2026-09-01','CASE1'),
        ('b','D2','2026-10-01','CASE2'),('c',NULL,NULL,'CASE3');
      INSERT INTO operational_task_amcu_decisions VALUES('t','a','https://example.test/a'),
        ('t','b','https://example.test/b'),('t','c','');
    ''')
    con.commit(); con.execute('PRAGMA query_only=ON')
    allowed={sqlite3.SQLITE_SELECT,sqlite3.SQLITE_READ,sqlite3.SQLITE_FUNCTION,sqlite3.SQLITE_TRANSACTION}
    con.set_authorizer(lambda action,a,b,db,trigger:sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY)
    return con


def item(kind='amcu_exclusion',**values):
    return {'id':'t','supplier_code':'123','task_type':kind,'source_context':{},**values}


class OperationalUiSummaryTests(unittest.TestCase):
    def setUp(self): self.con=fixture()
    def tearDown(self): self.con.close()

    def test_multiple_decisions_and_no_case_number_fallback(self):
        value=tasks.task_ui_summary(self.con,item())
        self.assertEqual([x['number'] for x in value['basis_items']],['D2','D1',None])
        self.assertEqual(value['latest_basis_date'],'2026-10-01')
        self.assertNotIn('CASE3',json.dumps(value))

    def test_missing_invalid_dates_are_not_fabricated(self):
        for value in ('','invalid','2026-02-30',None):
            self.assertIsNone(tasks._basis_date(value))
        self.assertEqual(tasks._basis_date('2026-10-01T12:00:00+03:00'),'2026-10-01')

    def test_read_model_cannot_write(self):
        before=self.con.total_changes
        tasks.task_ui_summary(self.con,item()); tasks.qualification_ui_summary(self.con,item())
        self.assertEqual(self.con.total_changes,before)
        for sql in ('DELETE FROM qualifications','CREATE TABLE bad(x)','PRAGMA user_version=1'):
            with self.assertRaises(sqlite3.DatabaseError): self.con.execute(sql)

    def test_distinct_counts_and_residual_are_not_completion_guards(self):
        value=tasks.qualification_ui_summary(self.con,item())
        self.assertEqual(value['current']['active'],2)
        self.assertEqual(value['current']['inactive'],1)
        self.assertEqual(value['current']['total'],3)
        self.assertEqual(value['coverage']['linked'],2)
        self.assertEqual(value['residual']['linked_active'],1)
        self.assertEqual(value['residual']['outside_linked_active'],1)
        self.assertFalse(value['residual']['coverage_complete'])

    def test_linkage_is_not_historical_snapshot(self):
        coverage=tasks.qualification_ui_summary(self.con,item())['coverage']
        for key in ('captured_active','historically_excluded','historically_remaining','captured_at'):
            self.assertIsNone(coverage[key])

    def test_creation_snapshot_not_reconstructed_from_current(self):
        value=item('termination_exclusion',source_context={'snapshot_created_at':'2026-09-01',
            'affected_qualifications':[{'qualification_id':'q1'},{'qualification_id':'q2'}]})
        coverage=tasks.qualification_ui_summary(self.con,value)['coverage']
        self.assertEqual(coverage['captured_active'],2)
        self.assertEqual(coverage['current_linked_active'],1)
        self.assertIsNone(coverage['historically_excluded'])
        self.assertEqual(coverage['captured_at'],'2026-09-01')

    def test_unstamped_snapshot_is_unproven(self):
        value=item('termination_exclusion',source_context={'affected_qualifications':[{'qualification_id':'q1'}]})
        self.assertIsNone(tasks.qualification_ui_summary(self.con,value)['coverage']['captured_active'])

    def test_exclusion_count_only_from_explicit_sync_receipt(self):
        value=item(events=[{'event_type':'amcu_exclusion_confirmed_by_sync','created_at':'2026-10-01',
                            'metadata':{'qualification_ids':['q2','q2']}}])
        coverage=tasks.qualification_ui_summary(self.con,value)['coverage']
        self.assertEqual(coverage['historically_excluded'],1)
        self.assertIsNone(coverage['historically_remaining'])
        self.assertEqual(coverage['exclusion_provenance'][0]['at'],'2026-10-01')

    def test_canonical_nazk_results(self):
        for code,label in [('confirmed','підтверджено'),('refuted','спростовано'),('insufficient','Недостатньо')]:
            with self.subTest(code=code):
                result=tasks.task_ui_summary(self.con,item('nazk_check',nazk_current_state={'result':code}))['result_summary']
                self.assertEqual(result['code'],code); self.assertIn(label,result['label'])

    def test_not_current_is_not_old_confirmed_result(self):
        result=tasks.task_ui_summary(self.con,item('nazk_check',resolution_code='nazk_not_current',nazk_current_state={'result':'confirmed'}))['result_summary']
        self.assertEqual(result['code'],'not_current')

    def test_missing_protocol_never_uses_request_number(self):
        value=tasks.task_ui_summary(self.con,item('nazk_check',source_context={'request_number':'REQ99'}))
        self.assertIsNone(value['officer_decision']['number'])
        self.assertEqual(value['officer_decision']['documents'],[])

    def test_termination_record_is_labelled_as_record(self):
        value=tasks.task_ui_summary(self.con,item('termination_exclusion',source_context={'termination':{'record_number':'EDR1','record_date':'2026-10-01'}}))
        self.assertEqual(value['basis_items'][0]['kind'],'edr_record')

    def test_documents_request_vs_protocol(self):
        con=sqlite3.connect(':memory:')
        con.execute('CREATE TABLE generated_documents(id TEXT)')
        docs=[{'document_type':'nazk_supplier_request','status':'generated','filename':'Request'},
              {'document_type':'amcu_exclusion_protocol','status':'generated','filename':'Protocol'},
              {'document_type':'amcu_exclusion_protocol','status':'failed','filename':'Bad'}]
        with patch('task_documents.documents',return_value=docs):
            value=tasks.task_ui_summary(con,item('manual'))
        self.assertEqual([x['filename'] for x in value['supplier_requests']],['Request'])
        self.assertEqual([x['filename'] for x in value['officer_decision']['documents']],['Protocol'])
        con.close()

    def test_nazk_sentence_number_not_court_case(self):
        con=sqlite3.connect(':memory:')
        con.executescript('CREATE TABLE supplier_nazk_check_matches(id);CREATE TABLE nazk_registry(id);')
        with patch('nazk_registry_evidence.registry_records',return_value=[{'source_id':'n',
             'sentence_number':'S1','court_case_number':'CASE','sentence_date':'2026-10-01'}]):
            value=tasks.task_ui_summary(con,item('nazk_check',source_context={'nazk_check_id':1}))
        self.assertEqual(value['basis_items'][0]['number'],'S1');con.close()

    def test_basis_sort_both_directions_missing_last_and_filters_preserved(self):
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row
        con.executescript('''CREATE TABLE operational_tasks(id TEXT,task_type TEXT,status TEXT,
          assigned_officer_id INTEGER,priority TEXT,created_at TEXT,source_context TEXT,
          supplier_name_snapshot TEXT,supplier_code TEXT);
          CREATE TABLE authorized_officers(id INTEGER,full_name TEXT);
          CREATE TABLE supplier_nazk_checks(id INTEGER,responsible_officer_id INTEGER,
          responsible_officer_name TEXT,workflow_status TEXT,result TEXT,manager_name TEXT,completed_at TEXT,updated_at TEXT);
          INSERT INTO operational_tasks VALUES('a','manual','new',NULL,'high','2026-01-01','{}','',''),
          ('b','manual','new',NULL,'high','2026-01-01','{}','',''),
          ('c','manual','new',NULL,'high','2026-01-01','{}','',''),
          ('d','manual','completed',NULL,'high','2026-01-01','{}','','');''')
        def projected(connection,row):
            return {**dict(row),'latest_basis_date':{'a':'2026-09-01','b':'2026-10-01','c':None}.get(row['id'])}
        with patch.object(tasks,'_task',side_effect=projected):
            for direction,expected in [('asc',['a','b','c']),('desc',['b','a','c'])]:
                result=tasks.list_tasks(con,{'sort':'latest_basis_date','direction':direction,'type':'manual'})
                self.assertEqual([x['id'] for x in result['items']],expected)
                self.assertEqual(result['kpis']['completed'],1)
            with self.assertRaises(ValueError): tasks.list_tasks(con,{'sort':'latest_basis_date','direction':'BAD'})
        con.close()

    def test_warning_requisites_from_attached_decision(self):
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row
        con.executescript('''CREATE TABLE operational_task_blocking_decisions(task_id TEXT,
        protocol_number TEXT,decision_date TEXT,document_url TEXT,prozorro_url TEXT);
        INSERT INTO operational_task_blocking_decisions VALUES('t','P40','2026-10-01','https://example.test/document','');''')
        result=tasks.task_ui_summary(con,item('warning_block'))
        self.assertEqual(result['officer_decision']['number'],'P40')
        self.assertEqual(result['officer_decision']['reference'],'https://example.test/document')
        con.close()


class OperationalV2TargetTests(unittest.TestCase):
    def setUp(self):
        self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row
        self.con.executescript('''
          CREATE TABLE operational_task_qualifications(task_id,qualification_id,registry_contract_id,relation_type);
          CREATE TABLE qualifications(id,submission_id,framework_id,status);
          CREATE TABLE submissions(id,supplier_code,framework_id);
          CREATE TABLE frameworks(id,dk_code,title);
          CREATE TABLE registry_contracts(id,qualification_id,supplier_code,status,milestones_json,framework_id);
          INSERT INTO qualifications VALUES('q','s','f','active');
          INSERT INTO submissions VALUES('s','123','f');
          INSERT INTO frameworks VALUES('f','12300000','Selection');
          INSERT INTO operational_task_qualifications VALUES('t','q','exact','targeted_exclusion');
          INSERT INTO registry_contracts VALUES('exact','q','123','terminated','[]','f'),
            ('latest','q','123','active','[]','f');
        ''')
    def tearDown(self): self.con.close()
    def rows(self,events=None):
        return tasks.amcu_target_ui_rows(self.con,item(events=events or []))
    def test_exact_target_not_latest_contract_and_inactivity_not_proof(self):
        row=self.rows()[0]
        self.assertEqual(row['registry_contract_id'],'exact')
        self.assertEqual(row['registry_status'],'terminated')
        self.assertEqual(row['submission_id'],'s')
        self.assertEqual(row['sync_evidence'],[])

    def test_exact_submission_status_and_framework_limitation(self):
        self.con.execute('ALTER TABLE submissions ADD COLUMN status')
        self.con.execute("UPDATE submissions SET status='pending' WHERE id='s'")
        self.con.execute("INSERT INTO submissions VALUES('unrelated','123','f','active')")
        row=self.rows()[0]
        self.assertEqual(row['submission_status'],'pending')
        self.assertEqual(row['qualification_status'],'active')
        self.assertEqual(row['registry_status'],'terminated')
        self.assertEqual(row['framework_id'],'f')
        self.con.execute("UPDATE submissions SET framework_id='other' WHERE id='s'")
        row=self.rows()[0]
        self.assertFalse(row['source_identity_proven'])
        self.assertIn('FRAMEWORK_IDENTITY_NOT_PROVEN',row['limitations'])
        self.assertIn('DECISION_SPECIFIC_EXCLUSION_NOT_PROVEN',row['limitations'])
    def test_sync_requires_both_exact_identities(self):
        event={'id':9,'event_type':'amcu_exclusion_confirmed_by_sync','created_at':'2026-09-16',
               'metadata':{'qualification_ids':['q'],'registry_contract_ids':['latest']}}
        self.assertFalse(self.rows([event])[0]['sync_evidence'])
        event['metadata']['registry_contract_ids']=['exact']
        self.assertEqual(self.rows([event])[0]['sync_evidence'][0]['event_id'],9)
    def test_document_resource_identity_not_filename_protocol_proof(self):
        payload=[{'id':'m','type':'activation','documents':[{'id':'doc','url':'https://example.test/signed',
                                                         'title':'706.pdf.asice.zip'}]}]
        self.con.execute('UPDATE registry_contracts SET milestones_json=? WHERE id=?',(json.dumps(payload),'exact'))
        doc=self.rows()[0]['registry_documents'][0]
        self.assertEqual(doc['registry_contract_id'],'exact')
        self.assertEqual(doc['document_id'],'doc')
        self.assertEqual(doc['protocol_identity'],'NOT_PROVEN')
        self.assertFalse(doc['exclusion_proof'])
    def test_conflicting_source_and_malformed_documents_fail_closed(self):
        self.con.execute("UPDATE registry_contracts SET qualification_id='other',milestones_json='invalid' WHERE id='exact'")
        row=self.rows()[0]
        self.assertFalse(row['source_identity_proven'])
        self.assertFalse(row['registry_documents'])
        self.assertIn('SOURCE_IDENTITY_NOT_PROVEN',row['limitations'])
    def test_target_model_query_only(self):
        self.con.commit();self.con.execute('PRAGMA query_only=ON')
        allowed={sqlite3.SQLITE_SELECT,sqlite3.SQLITE_READ,sqlite3.SQLITE_FUNCTION}
        self.con.set_authorizer(lambda a,*rest:sqlite3.SQLITE_OK if a in allowed else sqlite3.SQLITE_DENY)
        before=self.con.total_changes
        self.assertEqual(self.rows(),self.rows())
        self.assertEqual(self.con.total_changes,before)

    def test_minimal_source_without_document_metadata_is_explicit_not_proven(self):
        self.con.execute('ALTER TABLE registry_contracts DROP COLUMN milestones_json')
        row=self.rows()[0]
        self.assertEqual(row['registry_documents'],[])
        self.assertIn('REGISTRY_DOCUMENT_METADATA_NOT_AVAILABLE',row['limitations'])

    def test_multiple_contracts_explicit_ambiguity_and_malformed_receipt(self):
        self.con.execute("INSERT INTO operational_task_qualifications VALUES('t','q','latest','targeted_exclusion')")
        event={'event_type':'amcu_exclusion_confirmed_by_sync','created_at':'2026-09-16',
               'metadata':{'qualification_ids':'q','registry_contract_ids':'exact'}}
        rows=self.rows([event])
        self.assertEqual(len(rows),2)
        for row in rows:
            self.assertFalse(row['sync_evidence'])
            self.assertIn('MULTIPLE_LINKED_CONTRACTS_DISPLAYED_SEPARATELY',row['limitations'])



class ProductionTaskEndpointTests(unittest.TestCase):
    """Actual HTTP dispatcher against a disposable DB, never a live DB."""
    def setUp(self):
        import tempfile
        import threading
        from http.server import ThreadingHTTPServer
        import server
        self.server=server
        self.temp=tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db=Path(self.temp.name)/'synthetic.sqlite3'
        self.patches=[patch.object(server,'DB_PATH',self.db),
                      patch.object(server,'AUTH_ENABLED',False),
                      patch.object(server,'LOCAL_ROLE_IMPERSONATION',True)]
        for p in self.patches:p.start()
        server.init_db();server.init_reference_tables(self.db)
        with server.db() as con:
            tasks.migrate(con)
            for i,kind in enumerate(['manual','manual','manual','manual']):
                con.execute('''INSERT INTO operational_tasks
                  (id,task_key,task_type,supplier_code,supplier_name_snapshot,status,priority,
                   created_at,updated_at,source_context,document_context,metadata)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                  (f'{i+1:032x}',f'test:{i}',kind,'00000001','SYNTHETIC',
                   'completed' if i==3 else 'new','normal','2020-01-01',
                   '2099-01-01','{}','{}','{}'))
        self.http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True)
        self.thread.start()

    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.thread.join(timeout=5)
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()

    def get(self,path):
        import urllib.request
        request=urllib.request.Request(f'http://127.0.0.1:{self.http.server_port}{path}',
                                       headers={'X-PQM-Local-Role':'admin'})
        with urllib.request.urlopen(request,timeout=5) as response:
            self.assertEqual(response.status,200)
            return json.load(response)

    def test_list_http_filters_and_existing_nonpaginated_contract(self):
        result=self.get('/api/operational-tasks?status_group=active&type=manual&search=SYNTHETIC&size=1&page=2')
        # Existing Production list is not paginated; do not invent pagination.
        self.assertEqual(result['total'],3)
        self.assertEqual(len(result['items']),3)
        for row in result['items']:
            self.assertIn('basis_items',row)
            self.assertIn('officer_decision',row)
            self.assertIn('result_summary',row)
            self.assertIsNone(row['latest_basis_date'])
        self.assertEqual(self.get('/api/operational-tasks?status_group=completed')['total'],1)
        self.assertEqual(self.get('/api/operational-tasks?search=ABSENT')['total'],0)

    def test_detail_http_repeated_get_keeps_all_persisted_state_unchanged(self):
        with sqlite3.connect(self.db) as con:before='\n'.join(con.iterdump())
        path='/api/operational-tasks/'+f'{1:032x}'
        first=self.get(path);second=self.get(path)
        self.assertEqual(first,second)
        self.assertIn('qualification_summary',first)
        self.assertIsNone(first['latest_basis_date'])
        self.assertEqual(first['officer_decision']['documents'],[])
        self.assertNotEqual(first['latest_basis_date'],'2099-01-01')
        with sqlite3.connect(self.db) as con:after='\n'.join(con.iterdump())
        self.assertEqual(before,after)

    def test_list_http_missing_dates_last_stable_both_directions(self):
        expected=[f'{i:032x}' for i in (1,2,3)]
        for direction in ('asc','desc'):
            result=self.get('/api/operational-tasks?sort=latest_basis_date&direction='+direction)
            self.assertEqual([row['id'] for row in result['items']],expected)


if __name__=='__main__': unittest.main()
