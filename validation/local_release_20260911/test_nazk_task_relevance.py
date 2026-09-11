import json
import sqlite3
import unittest

import operational_tasks


class NazkTaskPersonRelevanceTests(unittest.TestCase):
    CODE='12345678'
    def setUp(self):
        self.con=sqlite3.connect(':memory:'); self.con.row_factory=sqlite3.Row
        self.con.create_function('DIGITS',1,lambda value:''.join(x for x in str(value or '') if x.isdigit()))
        self.con.create_function('NORMALIZE_NAME',1,lambda value:' '.join(str(value or '').casefold().split()))
        self.con.executescript('''
          CREATE TABLE authorized_officers(id INTEGER PRIMARY KEY,full_name TEXT,active INTEGER DEFAULT 1);
          CREATE TABLE submissions(id TEXT PRIMARY KEY,framework_id TEXT,supplier_name TEXT,supplier_code TEXT,date_published TEXT,status TEXT);
          CREATE TABLE qualifications(id TEXT PRIMARY KEY,submission_id TEXT,status TEXT,decision_date TEXT);
          CREATE TABLE frameworks(id TEXT PRIMARY KEY,pretty_id TEXT,dk_code TEXT,title TEXT,status TEXT,raw_json TEXT);
          CREATE TABLE registry_contracts(id TEXT PRIMARY KEY,qualification_id TEXT,framework_id TEXT,supplier_code TEXT,status TEXT);
          CREATE TABLE supplier_edr_profiles(supplier_code TEXT,full_name TEXT,short_name TEXT);
          CREATE TABLE amcu_registry(row_key TEXT,offender_code TEXT,decision_date TEXT);
          CREATE TABLE supplier_managers(id INTEGER PRIMARY KEY,supplier_code TEXT,manager_name TEXT,normalized_name TEXT,manager_tax_id TEXT,is_current INTEGER);
          CREATE TABLE supplier_nazk_checks(id INTEGER PRIMARY KEY,supplier_code TEXT,manager_id INTEGER,manager_name TEXT,workflow_status TEXT,result TEXT,started_at TEXT,completed_at TEXT,updated_at TEXT);
          CREATE TABLE supplier_nazk_check_matches(check_id INTEGER,nazk_source_id TEXT,match_status TEXT);
          CREATE TABLE violation_reports(id TEXT,report_id TEXT,status TEXT,decision_date TEXT,defendant_code TEXT,date_published TEXT,tender_pretty_id TEXT,author_name TEXT,contract_pretty_id TEXT);
        ''')
        operational_tasks.migrate(self.con)
        self.con.execute("INSERT INTO frameworks VALUES('F','UA-F-X','00000000-0','Fixture','active',?)",(json.dumps({'qualificationPeriod':{'endDate':'2099-01-01'}}),))
        self.con.execute("INSERT INTO submissions VALUES('S','F','Supplier X',?,'2026-01-01','complete')",(self.CODE,))
        self.con.execute("INSERT INTO qualifications VALUES('Q','S','active','2026-01-02')")
        self.con.execute("INSERT INTO registry_contracts VALUES('RC','Q','F',?,'active')",(self.CODE,))
        self.con.executemany("INSERT INTO supplier_managers VALUES(?,?,?,?,?,?)",[(1,self.CODE,'PERSON_A','person_a','111',0),(2,self.CODE,'PERSON_B','person_b','222',1)])
        self.con.execute("INSERT INTO supplier_nazk_checks VALUES(10,?,1,'PERSON_A','completed','confirmed','2025-01-01','2025-01-02','2025-01-02')",(self.CODE,))
        self.con.execute("INSERT INTO supplier_nazk_check_matches VALUES(10,'RECORD_A','confirmed')")
        stamp=operational_tasks.now_iso()
        self.con.execute("""INSERT INTO operational_tasks(id,task_key,task_type,supplier_code,supplier_name_snapshot,status,priority,created_at,updated_at,source_context,document_context)
          VALUES('history','historical_exclusion:X:PERSON_A','nazk_check',?,'Supplier X','completed','critical',?,?,?,?)""",
          (self.CODE,stamp,stamp,json.dumps({'historical_exclusion':True,'person_name':'PERSON_A'}),'{}'))
        operational_tasks._event(self.con,'history','historical_exclusion_completed','fixture')

    def active_for_record(self,record):
        return self.con.execute("""SELECT COUNT(*) FROM operational_tasks WHERE task_type='nazk_check'
          AND status NOT IN ('completed','cancelled') AND source_context LIKE ?""",(f'%{record}%',)).fetchone()[0]

    def test_historical_confirmed_previous_manager_does_not_retrigger(self):
        self.assertNotEqual('PERSON_A',self.con.execute("SELECT manager_name FROM supplier_managers WHERE is_current=1").fetchone()[0])
        before=self.con.execute("SELECT result,manager_name FROM supplier_nazk_checks WHERE id=10").fetchone()
        self.assertEqual(tuple(before),('confirmed','PERSON_A'))
        self.assertEqual(len(operational_tasks._active_application_map(self.con)[self.CODE]),1)
        operational_tasks.build(self.con,'fixture',include_nazk=True); operational_tasks.build(self.con,'fixture repeat',include_nazk=True)
        self.assertEqual(self.active_for_record('RECORD_A'),0)
        self.assertEqual(tuple(self.con.execute("SELECT result,manager_name FROM supplier_nazk_checks WHERE id=10").fetchone()),('confirmed','PERSON_A'))
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM operational_task_events WHERE task_id='history'").fetchone()[0],1)

    def test_current_manager_match_creates_one_task_idempotently(self):
        self.con.execute("UPDATE supplier_managers SET is_current=CASE id WHEN 1 THEN 1 ELSE 0 END")
        operational_tasks.build(self.con,'fixture',include_nazk=True); operational_tasks.build(self.con,'fixture repeat',include_nazk=True)
        self.assertEqual(self.active_for_record('RECORD_A'),1)
        self.assertEqual(self.con.execute("SELECT task_key FROM operational_tasks WHERE source_context LIKE '%RECORD_A%'").fetchone()[0],
                         f'nazk_check:{self.CODE}:1:RECORD_A')

    def test_new_current_manager_match_is_a_new_business_event(self):
        self.con.execute("INSERT INTO supplier_nazk_checks VALUES(11,?,2,'PERSON_B','needs_review',NULL,'2026-01-03',NULL,'2026-01-03')",(self.CODE,))
        self.con.execute("INSERT INTO supplier_nazk_check_matches VALUES(11,'RECORD_B','confirmed')")
        operational_tasks.build(self.con,'fixture',include_nazk=True); operational_tasks.build(self.con,'fixture repeat',include_nazk=True)
        self.assertEqual(self.active_for_record('RECORD_A'),0)
        self.assertEqual(self.active_for_record('RECORD_B'),1)
        self.assertEqual(self.con.execute("SELECT task_key FROM operational_tasks WHERE source_context LIKE '%RECORD_B%'").fetchone()[0],
                         f'nazk_check:{self.CODE}:2:RECORD_B')


class CanonicalRelationCycleTests(NazkTaskPersonRelevanceTests):
    def test_missing_record_cancellation_and_new_record(self):
        self.con.execute("INSERT INTO supplier_nazk_checks VALUES(11,?,2,'PERSON_B','needs_review',NULL,'2026-01-03',NULL,'2026-01-03')",(self.CODE,))
        operational_tasks.build(self.con,'fixture',include_nazk=True)
        row=self.con.execute("SELECT id,task_key FROM operational_tasks WHERE status='in_progress'").fetchone()
        self.con.execute("UPDATE operational_tasks SET status='cancelled',resolution_code='nazk_record_no_longer_present' WHERE id=?",(row['id'],))
        operational_tasks.build(self.con,'repeat',include_nazk=True)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM operational_tasks WHERE status='in_progress'").fetchone()[0],0)
        self.con.execute("INSERT INTO supplier_nazk_check_matches VALUES(11,'NEW_RECORD','candidate')")
        operational_tasks.build(self.con,'new event',include_nazk=True)
        operational_tasks.build(self.con,'repeat',include_nazk=True)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM operational_tasks WHERE status='in_progress'").fetchone()[0],1)
        self.assertEqual(self.con.execute('SELECT status FROM operational_tasks WHERE id=?',(row['id'],)).fetchone()[0],'cancelled')

    def test_additive_relation_preserves_existing_task_key(self):
        self.con.execute("INSERT INTO supplier_nazk_checks VALUES(11,?,2,'PERSON_B','needs_review',NULL,'2026-01-03',NULL,'2026-01-03')",(self.CODE,))
        operational_tasks.build(self.con,'fixture',include_nazk=True)
        key=self.con.execute("SELECT task_key FROM operational_tasks WHERE status='in_progress'").fetchone()[0]
        self.con.execute("INSERT INTO supplier_nazk_check_matches VALUES(11,'LINKED_RECORD','candidate')")
        operational_tasks.build(self.con,'repeat',include_nazk=True)
        self.assertEqual([r[0] for r in self.con.execute("SELECT task_key FROM operational_tasks WHERE status='in_progress'")],[key])

if __name__=='__main__': unittest.main()
