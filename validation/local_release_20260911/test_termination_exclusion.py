import json
import sqlite3
import unittest
from unittest.mock import patch

import operational_tasks
import task_documents


class TerminationExclusionTests(unittest.TestCase):
    def connection(self, *, status="Припинено", active=True, code="1234567890"):
        con=sqlite3.connect(":memory:");con.row_factory=sqlite3.Row
        con.create_function("DIGITS",1,lambda value:"".join(ch for ch in str(value or "") if ch.isdigit()))
        con.create_function("CASEFOLD",1,lambda value:str(value or "").casefold())
        con.executescript("""
          CREATE TABLE supplier_edr_profiles(supplier_code TEXT PRIMARY KEY,full_name TEXT,short_name TEXT,
            edr_status TEXT,termination_decision_details TEXT,termination_record_date TEXT,
            termination_record_number TEXT);
          CREATE TABLE supplier_registry_summary(supplier_code TEXT,supplier_name TEXT);
          CREATE TABLE submissions(id TEXT PRIMARY KEY,framework_id TEXT,supplier_code TEXT,supplier_name TEXT,date_published TEXT);
          CREATE TABLE qualifications(id TEXT PRIMARY KEY,submission_id TEXT,status TEXT,decision_date TEXT);
          CREATE TABLE registry_contracts(id TEXT PRIMARY KEY,framework_id TEXT,qualification_id TEXT,supplier_code TEXT,status TEXT,raw_json TEXT);
          CREATE TABLE frameworks(id TEXT PRIMARY KEY,pretty_id TEXT,dk_code TEXT,title TEXT,status TEXT,raw_json TEXT);
          CREATE TABLE framework_officers(framework_id TEXT,marketplace_url TEXT);
          CREATE TABLE authorized_officers(id INTEGER PRIMARY KEY,full_name TEXT,active INTEGER);
          CREATE TABLE operational_tasks(id TEXT PRIMARY KEY,task_key TEXT UNIQUE,task_type TEXT,supplier_code TEXT,
            supplier_name_snapshot TEXT,status TEXT,priority TEXT,assigned_officer_id INTEGER,created_at TEXT,updated_at TEXT,
            due_at TEXT,ready_for_document_at TEXT,protocol_number TEXT DEFAULT '',protocol_date TEXT DEFAULT '',
            protocol_reference TEXT DEFAULT '',published_at TEXT,published_reference TEXT DEFAULT '',resolved_at TEXT,
            resolved_by TEXT,resolution_code TEXT DEFAULT '',resolution_text TEXT DEFAULT '',source_context TEXT,
            document_context TEXT,metadata TEXT DEFAULT '{}',version INTEGER DEFAULT 1);
          CREATE TABLE operational_task_qualifications(task_id TEXT,qualification_id TEXT,registry_contract_id TEXT,
            relation_type TEXT,linked_at TEXT,PRIMARY KEY(task_id,qualification_id,registry_contract_id,relation_type));
          CREATE TABLE operational_task_qualification_decisions(task_id TEXT,qualification_id TEXT,registry_contract_id TEXT,
            decision TEXT DEFAULT '',note TEXT DEFAULT '',updated_at TEXT,updated_by TEXT,
            PRIMARY KEY(task_id,qualification_id,registry_contract_id));
          CREATE TABLE operational_task_events(id INTEGER PRIMARY KEY AUTOINCREMENT,task_id TEXT,event_type TEXT,
            created_at TEXT,actor TEXT,old_value TEXT,new_value TEXT,metadata TEXT);
          CREATE TABLE operational_task_applications(task_id TEXT,application_id TEXT,relation_type TEXT);
          CREATE TABLE operational_task_warnings(task_id TEXT,violation_report_id TEXT,warning_date TEXT,sequence_no INTEGER);
          CREATE TABLE operational_task_amcu_decisions(task_id TEXT,amcu_decision_id TEXT,extract_url TEXT);
          CREATE TABLE operational_task_channels(task_id TEXT,channel TEXT,status TEXT);
          CREATE TABLE operational_task_responses(id INTEGER,task_id TEXT);
          CREATE TABLE supplier_nazk_checks(id INTEGER,workflow_status TEXT,result TEXT,manager_name TEXT,completed_at TEXT,updated_at TEXT,responsible_officer_id INTEGER,responsible_officer_name TEXT);
          INSERT INTO authorized_officers VALUES(1,'Тестова УО',1);
          INSERT INTO frameworks VALUES('f','UA-F-1','12340000-0','Тестовий відбір','active','{"qualificationPeriod":{"endDate":"2099-01-01"}}');
        """)
        con.execute("INSERT INTO supplier_edr_profiles VALUES(?,?,?,?,?,?,?)",(code,'ФОП ТЕСТОВА ОСОБА','ФОП ТЕСТОВА О.',status,'№ 10 від 2026-09-01','2026-09-01','10'))
        con.execute("INSERT INTO submissions VALUES('s','f',?, 'ФОП ТЕСТОВА ОСОБА','2026-08-01')",(code,))
        con.execute("INSERT INTO qualifications VALUES('q','s','active','2026-08-02')")
        con.execute("INSERT INTO registry_contracts VALUES('rc','f','q',?,?, '{}')",(code,'active' if active else 'terminated'))
        return con

    def call(self, func, *args):
        with patch.object(operational_tasks,"migrate",lambda con:None):
            return func(*args)

    def test_eligible_preview_create_snapshot_and_duplicate(self):
        con=self.connection()
        preview=self.call(operational_tasks.preview_termination_exclusions,con,['1234567890'])
        self.assertEqual((preview['eligible'],preview['to_create'],preview['skipped']),(1,1,0))
        created=self.call(operational_tasks.create_termination_exclusions,con,['1234567890'],'Тестова УО')
        repeated=self.call(operational_tasks.create_termination_exclusions,con,['1234567890'],'Тестова УО')
        self.assertEqual((created['created'],repeated['created'],repeated['skipped']),(1,0,1))
        row=con.execute("SELECT * FROM operational_tasks").fetchone();source=json.loads(row['source_context'])
        self.assertEqual(source['termination']['record_number'],'10')
        self.assertEqual(source['supplier']['type'],'individual_entrepreneur')
        self.assertEqual(len(source['affected_qualifications']),1)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM operational_task_qualifications").fetchone()[0],1)

    def test_ineligible_registered_and_no_active(self):
        registered=self.connection(status='Зареєстровано')
        inactive=self.connection(active=False)
        registered_item=self.call(operational_tasks.preview_termination_exclusions,registered,['1234567890'])['items'][0]
        inactive_item=self.call(operational_tasks.preview_termination_exclusions,inactive,['1234567890'])['items'][0]
        self.assertEqual(registered_item['reason'],'no_longer_eligible')
        self.assertEqual(registered_item['reasons'],['Статус ЄДР: не Припинено'])
        self.assertEqual(inactive_item['reason'],'no_active_qualifications')
        self.assertEqual(inactive_item['reasons'],['Немає активних кваліфікацій'])

    def test_preview_reports_all_independent_skip_reasons(self):
        con=self.connection(status='Зареєстровано',active=False)
        item=self.call(operational_tasks.preview_termination_exclusions,con,['1234567890'])['items'][0]
        self.assertEqual(item['reasons'],['Статус ЄДР: не Припинено','Немає активних кваліфікацій'])

    def test_snapshot_does_not_follow_future_edr_change(self):
        con=self.connection();task_id=self.call(operational_tasks.create_termination_exclusions,con,['1234567890'],'Тестова УО')['task_ids'][0]
        before=json.loads(con.execute("SELECT source_context FROM operational_tasks WHERE id=?",(task_id,)).fetchone()[0])
        con.execute("UPDATE supplier_edr_profiles SET termination_decision_details='CHANGED',edr_status='Зареєстровано'")
        after=json.loads(con.execute("SELECT source_context FROM operational_tasks WHERE id=?",(task_id,)).fetchone()[0])
        self.assertEqual(before,after)

    def test_multiple_qualifications_create_one_task_with_all_targets(self):
        con=self.connection()
        con.executescript("""INSERT INTO submissions VALUES('s2','f','1234567890','ФОП ТЕСТОВА ОСОБА','2026-08-03');
          INSERT INTO qualifications VALUES('q2','s2','active','2026-08-04');
          INSERT INTO registry_contracts VALUES('rc2','f','q2','1234567890','active','{}');""")
        result=self.call(operational_tasks.create_termination_exclusions,con,['1234567890'],'Тестова УО')
        self.assertEqual(result['created'],1)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM operational_task_qualifications").fetchone()[0],2)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM operational_task_qualification_decisions").fetchone()[0],2)

    def test_document_boundary_is_type_specific(self):
        base={'id':'t','supplier_code':'1234567890','assigned_officer_name':'СВІТЛАНА НАМЯСЕНКО',
          'protocol_number':'1','protocol_date':'2026-09-16','source_context':{'supplier':{'code':'1234567890',
          'type':'individual_entrepreneur','code_label':'РНОКПП','name':'ФОП ТЕСТОВА ОСОБА','full_name':'ФОП ТЕСТОВА ОСОБА','short_name':'ФОП ТЕСТОВА О.'},
          'termination':{'details':'record'}}}
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row
        con.execute("CREATE TABLE generated_documents(id TEXT,task_id TEXT,supplier_code TEXT,document_type TEXT,template_key TEXT,template_reference TEXT,filename TEXT,storage_name TEXT,created_at TEXT,created_by TEXT,generation_provider TEXT,status TEXT,document_date TEXT,version INTEGER,sha256 TEXT,metadata_json TEXT)")
        fop=task_documents.termination_readiness(con,base)
        legal=task_documents.termination_readiness(con,{**base,'source_context':{**base['source_context'],'supplier':{**base['source_context']['supplier'],'type':'legal_entity','code':'12345678'}}})
        self.assertEqual(fop['template_boundary'],'fop_candidate')
        self.assertEqual(fop['canonical_payload']['termination.reference'],'record')
        self.assertEqual(legal['template_boundary'],'legal_entity_blocked')
        self.assertIn('юридичної особи',' '.join(legal['errors']))

    def test_post_sync_completion_uses_only_snapshotted_exclusions(self):
        con=self.connection();task_id=self.call(operational_tasks.create_termination_exclusions,con,['1234567890'],'Тестова УО')['task_ids'][0]
        con.execute("UPDATE operational_tasks SET status='awaiting_sync' WHERE id=?",(task_id,))
        con.execute("UPDATE operational_task_qualification_decisions SET decision='exclude' WHERE task_id=?",(task_id,))
        active=self.call(operational_tasks.reconcile_termination_after_qualification_sync,con,'sync')
        self.assertEqual(active['completed'],0)
        con.execute("UPDATE registry_contracts SET status='terminated' WHERE id='rc'")
        completed=self.call(operational_tasks.reconcile_termination_after_qualification_sync,con,'sync')
        repeated=self.call(operational_tasks.reconcile_termination_after_qualification_sync,con,'sync')
        self.assertEqual((completed['completed'],repeated['completed']),(1,0))
        self.assertEqual(tuple(con.execute("SELECT status,resolution_code FROM operational_tasks WHERE id=?",(task_id,)).fetchone()),('completed','termination_excluded'))


if __name__ == '__main__': unittest.main()
