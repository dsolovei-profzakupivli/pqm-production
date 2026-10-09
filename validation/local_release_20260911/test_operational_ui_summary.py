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


class OperationalUiJsTests(unittest.TestCase):
    def test_repeat_detail_get_model_has_no_writes(self):
        from test_warning_task_card import fixture as warning_fixture
        con,task_id=warning_fixture();con.commit()
        con.execute('PRAGMA query_only=ON')
        allowed={sqlite3.SQLITE_SELECT,sqlite3.SQLITE_READ,sqlite3.SQLITE_FUNCTION,sqlite3.SQLITE_TRANSACTION}
        con.set_authorizer(lambda action,a,b,db,trigger:sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY)
        before=con.total_changes
        first=tasks.detail(con,task_id);second=tasks.detail(con,task_id)
        self.assertEqual(first,second)
        self.assertIn('basis_items',first);self.assertIn('qualification_summary',first)
        self.assertEqual(con.total_changes,before)
        con.close()

    def test_summary_and_terminal_interactions(self):
        node=shutil.which('node') or 'C:/Users/User/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
        script=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const src=fs.readFileSync('app.js','utf8');
const names=['operationalSummaryLink','operationalBasisHtml','operationalDecisionHtml','operationalQualificationHtml','operationalTerminalHtml','operationalTaskHumanState'];
const c={esc:x=>String(x??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;'),displayDateOnly:x=>x||''};vm.createContext(c);
for(const name of names){const line=src.split('\n').find(x=>x.startsWith('function '+name+'('));assert(line,name);vm.runInContext(line,c)}
const value={task_type:'nazk_check',status:'completed',result_summary:{label:'Спростовано'},officer_decision:{number:'P1',date:'2026-10-01',documents:[]},supplier_requests:[{filename:'Request',download_url:'/api/operational-tasks/t/documents/1/download'}]};
assert.equal(c.operationalTaskHumanState(value),'Спростовано');
const terminal=c.operationalTerminalHtml(value);assert(terminal.includes('Спростовано'));assert(terminal.includes('P1'));assert(terminal.includes('не рішення УО'));assert(!terminal.includes('Потребує опрацювання'));assert(!terminal.includes('<button'));assert(!terminal.includes('Підготувати'));
assert(!c.operationalSummaryLink('javascript:alert(1)','Unsafe').includes('<a'));
assert(!c.operationalSummaryLink('//evil.test','Unsafe').includes('<a'));
const basis=c.operationalBasisHtml({basis_items:[{kind:'amcu_decision',number:'D1',date:'2026-10-01'},{kind:'amcu_decision',number:'<script>',date:null}]});assert(basis.includes('<details>'));assert(basis.includes('&lt;script>'));assert(basis.includes('Інші підстави (1)'));
const q=c.operationalQualificationHtml({task_type:'amcu_exclusion',qualification_summary:{coverage:{linked:2,captured_active:null},residual:{linked_active:1,outside_linked_active:4,limitation:'NOT PROVEN'}}});assert(q.includes('Зафіксовано активних: —'));assert(q.includes('NOT PROVEN'));assert(q.includes('Інформаційно'));
assert(src.includes("textarea,summary,details"));
assert(src.includes("confirmed=!terminal&&result==='confirmed'"));
assert(src.includes("operationalTerminalHtml(item)+operationalNazkWorkspace(item)"));
assert(src.includes("hidden=['completed','cancelled'].includes(item.status)"));
console.log('Operational UI interactions PASS');
'''
        result=subprocess.run([node,'-e',script],cwd=ROOT,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__=='__main__': unittest.main()
