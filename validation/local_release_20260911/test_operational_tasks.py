import unittest
from datetime import date
from pathlib import Path

import operational_tasks
import supplier_activity
import sqlite3
import json
from unittest.mock import patch


def warning(item_id, decision_date):
    return {"id": item_id, "report_id": f"UA-D-{item_id}", "decision_date": decision_date}


class WarningBlockRollingTests(unittest.TestCase):
    def test_three_warnings_use_rolling_one_calendar_month(self):
        rows = [warning("1", "2026-08-08"), warning("2", "2026-08-20"), warning("3", "2026-09-08")]
        events = operational_tasks._warning_events(rows, date(2026, 9, 8))
        self.assertEqual(events[0][0], "3_in_1_rolling_month")
        self.assertEqual([item[0]["id"] for item in events[0][3]], ["1", "2", "3"])

    def test_calendar_month_is_not_used(self):
        rows = [warning("1", "2026-08-07"), warning("2", "2026-08-20"), warning("3", "2026-09-08")]
        self.assertEqual(operational_tasks._warning_events(rows, date(2026, 9, 8)), [])

    def test_five_warnings_use_rolling_three_calendar_months(self):
        rows = [warning(str(i), value) for i, value in enumerate(
            ["2026-06-08", "2026-06-20", "2026-07-15", "2026-08-10", "2026-09-08"], 1)]
        events = operational_tasks._warning_events(rows, date(2026, 9, 8))
        self.assertEqual(events[0][0], "5_in_3_rolling_months")

    def test_month_end_is_clamped_as_calendar_arithmetic(self):
        self.assertEqual(operational_tasks.subtract_calendar_months(date(2026, 3, 31), 1), date(2026, 2, 28))

    def test_completed_event_warning_ids_are_not_reused(self):
        rows = [warning("1", "2026-08-08"), warning("2", "2026-08-20"), warning("3", "2026-09-08")]
        self.assertIsNone(operational_tasks._next_warning_event(rows, {"1", "2", "3"}, date(2026, 9, 8)))


class EffectiveSupplierActivityTests(unittest.TestCase):
    def test_canonical_predicate_contains_all_three_business_conditions(self):
        predicate = supplier_activity.effective_active_sql("rc", "f")
        self.assertIn("rc.status='active'", predicate)
        self.assertIn("f.status", predicate)
        self.assertIn("qualificationPeriod.endDate", predicate)

    def test_amcu_effective_qualification_projection_reuses_registry_and_marketplace_data(self):
        con=sqlite3.connect(":memory:");con.row_factory=sqlite3.Row
        con.create_function("DIGITS",1,lambda value:"".join(ch for ch in str(value or "") if ch.isdigit()))
        con.executescript("""CREATE TABLE registry_contracts(id TEXT,status TEXT,supplier_code TEXT,
          qualification_id TEXT,framework_id TEXT,raw_json TEXT);
          CREATE TABLE qualifications(id TEXT,submission_id TEXT,status TEXT,decision_date TEXT);
          CREATE TABLE submissions(id TEXT,framework_id TEXT,date_published TEXT);
          CREATE TABLE frameworks(id TEXT,pretty_id TEXT,dk_code TEXT,title TEXT,status TEXT,raw_json TEXT);
          CREATE TABLE framework_officers(framework_id TEXT,marketplace_url TEXT);
          INSERT INTO frameworks VALUES('f','UA-F-2020-12-15-000044-a','31430000-9',
            'Електричні акумулятори','active','{"qualificationPeriod":{"endDate":"2099-01-01"}}');
          INSERT INTO submissions VALUES('s','f','2025-09-25T16:00:00+03:00');
          INSERT INTO qualifications VALUES('q','s','active','2025-09-25T16:37:08+03:00');
          INSERT INTO registry_contracts VALUES('rc','active','2884318089','q','f',
            '{"date":"2025-09-25T16:37:08+03:00"}');
          INSERT INTO framework_officers VALUES('f',
            'https://market.test/qualification/5fd7ec0d0be3b38799cdd43f/offersList');""")
        rows=operational_tasks._effective_active_applications(con,'2884318089')
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['framework_pretty_id'],'UA-F-2020-12-15-000044-a')
        self.assertEqual(rows[0]['qualification_status'],'active')
        self.assertEqual(rows[0]['qualification_event_date'],'2025-09-25T16:37:08+03:00')
        self.assertIn('5fd7ec0d0be3b38799cdd43f',rows[0]['marketplace_url'])


class AmcuPostSyncLifecycleTests(unittest.TestCase):
    def connection(self):
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row
        con.create_function('DIGITS',1,lambda value:''.join(ch for ch in str(value or '') if ch.isdigit()))
        con.executescript("""CREATE TABLE operational_tasks(
          id TEXT PRIMARY KEY,task_key TEXT,task_type TEXT,supplier_code TEXT,supplier_name_snapshot TEXT DEFAULT '',
          status TEXT,priority TEXT DEFAULT 'high',assigned_officer_id INTEGER,created_at TEXT DEFAULT '2026-09-15',
          updated_at TEXT DEFAULT '',due_at TEXT,ready_for_document_at TEXT,protocol_number TEXT DEFAULT '',
          protocol_date TEXT DEFAULT '',protocol_reference TEXT DEFAULT '',published_at TEXT,published_reference TEXT DEFAULT '',
          resolved_at TEXT,resolved_by TEXT,resolution_code TEXT DEFAULT '',resolution_text TEXT DEFAULT '',
          source_context TEXT DEFAULT '{}',document_context TEXT DEFAULT '{}',metadata TEXT DEFAULT '{}',version INTEGER DEFAULT 1);
          CREATE TABLE operational_task_qualifications(task_id TEXT,qualification_id TEXT,registry_contract_id TEXT,
            relation_type TEXT,linked_at TEXT,PRIMARY KEY(task_id,qualification_id,registry_contract_id,relation_type));
          CREATE TABLE operational_task_applications(task_id TEXT,application_id TEXT,relation_type TEXT,
            PRIMARY KEY(task_id,application_id,relation_type));
          CREATE TABLE operational_task_events(id INTEGER PRIMARY KEY AUTOINCREMENT,task_id TEXT,event_type TEXT,
            created_at TEXT,actor TEXT,old_value TEXT,new_value TEXT,metadata TEXT);
          CREATE TABLE generated_documents(task_id TEXT,document_type TEXT,status TEXT);
          CREATE TABLE authorized_officers(id INTEGER PRIMARY KEY,active INTEGER);
          CREATE TABLE submissions(id TEXT PRIMARY KEY,framework_id TEXT,date_published TEXT);
          CREATE TABLE qualifications(id TEXT PRIMARY KEY,submission_id TEXT,status TEXT,decision_date TEXT);
          CREATE TABLE registry_contracts(id TEXT PRIMARY KEY,framework_id TEXT,qualification_id TEXT,
            supplier_code TEXT,status TEXT,milestones_json TEXT DEFAULT '[]',raw_json TEXT DEFAULT '{}');
          CREATE TABLE frameworks(id TEXT PRIMARY KEY,pretty_id TEXT,dk_code TEXT,title TEXT,status TEXT,raw_json TEXT);
          CREATE TABLE framework_officers(framework_id TEXT,marketplace_url TEXT);
          INSERT INTO operational_tasks(id,task_key,task_type,supplier_code,status) VALUES
            ('t','amcu_exclusion:1','amcu_exclusion','1','awaiting_sync');
          INSERT INTO frameworks VALUES('f','F','1','Framework','active','{"qualificationPeriod":{"endDate":"2099-01-01"}}');
          INSERT INTO submissions VALUES('s','f','2026-09-01');
          INSERT INTO operational_task_applications VALUES('t','s','active_application');
          INSERT INTO qualifications VALUES('q','s','active','2026-09-01');
          INSERT INTO registry_contracts(id,framework_id,qualification_id,supplier_code,status) VALUES('rc','f','q','1','active');
          INSERT INTO operational_task_qualifications VALUES('t','q','rc','targeted_exclusion','2026-09-15');""")
        return con

    def reconcile(self,con):
        with patch.object(operational_tasks,'migrate',lambda _con:None):
            return operational_tasks.reconcile_amcu_after_qualification_sync(con,'sync-test')

    def test_reviewed_with_linked_qualification_active_stays_reviewed(self):
        con=self.connection();result=self.reconcile(con)
        self.assertEqual(result['completed'],0)
        self.assertEqual(con.execute("SELECT status FROM operational_tasks").fetchone()[0],'awaiting_sync')

    def test_reviewed_with_linked_qualification_inactive_completes_idempotently(self):
        con=self.connection();con.execute("UPDATE registry_contracts SET status='terminated' WHERE id='rc'")
        first=self.reconcile(con);second=self.reconcile(con)
        self.assertEqual((first['completed'],second['completed']),(1,0))
        self.assertEqual(tuple(con.execute("SELECT status,resolution_code FROM operational_tasks").fetchone()),
                         ('completed','amcu_excluded'))
        self.assertEqual(con.execute("SELECT COUNT(*) FROM operational_task_events").fetchone()[0],1)

    def test_multiple_links_one_active_stays_reviewed_then_all_inactive_completes(self):
        con=self.connection()
        con.executescript("""INSERT INTO submissions VALUES('s2','f','2026-09-02');
          INSERT INTO qualifications VALUES('q2','s2','active','2026-09-02');
          INSERT INTO registry_contracts(id,framework_id,qualification_id,supplier_code,status) VALUES('rc2','f','q2','1','terminated');
          INSERT INTO operational_task_qualifications VALUES('t','q2','rc2','targeted_exclusion','2026-09-15');""")
        self.assertEqual(self.reconcile(con)['completed'],0)
        con.execute("UPDATE registry_contracts SET status='terminated' WHERE id='rc'")
        self.assertEqual(self.reconcile(con)['completed'],1)

    def test_other_active_qualification_keeps_supplier_active_but_task_completes(self):
        con=self.connection();con.execute("UPDATE registry_contracts SET status='terminated' WHERE id='rc'")
        con.executescript("""INSERT INTO submissions VALUES('other-s','f','2026-09-03');
          INSERT INTO qualifications VALUES('other-q','other-s','active','2026-09-03');
          INSERT INTO registry_contracts(id,framework_id,qualification_id,supplier_code,status) VALUES('other-rc','f','other-q','1','active');""")
        self.assertEqual(self.reconcile(con)['completed'],1)
        metadata=json.loads(con.execute("SELECT metadata FROM operational_task_events").fetchone()[0])
        self.assertEqual((metadata['supplier_effective_active_count'],metadata['supplier_activity']),(1,'active'))

    def test_last_inactive_marks_supplier_inactive_in_audit(self):
        con=self.connection();con.execute("UPDATE registry_contracts SET status='terminated' WHERE id='rc'")
        self.assertEqual(self.reconcile(con)['completed'],1)
        metadata=json.loads(con.execute("SELECT metadata FROM operational_task_events").fetchone()[0])
        self.assertEqual((metadata['supplier_effective_active_count'],metadata['supplier_activity']),(0,'inactive'))

    def test_missing_target_snapshot_never_auto_completes(self):
        con=self.connection();con.execute("DELETE FROM operational_task_qualifications")
        con.execute("UPDATE registry_contracts SET status='terminated'")
        self.assertEqual(self.reconcile(con)['completed'],0)
        self.assertEqual(con.execute("SELECT status FROM operational_tasks").fetchone()[0],'awaiting_sync')

    def test_completed_decision_cycle_blocks_duplicate_but_new_fact_does_not(self):
        con=self.connection()
        con.executescript("""CREATE TABLE operational_task_amcu_decisions(
          task_id TEXT,amcu_decision_id TEXT,extract_url TEXT DEFAULT '',created_at TEXT,updated_at TEXT,updated_by TEXT,
          PRIMARY KEY(task_id,amcu_decision_id));
          UPDATE operational_tasks SET status='completed',resolution_code='amcu_excluded';
          INSERT INTO operational_task_amcu_decisions(task_id,amcu_decision_id) VALUES('t','d1');""")
        self.assertTrue(operational_tasks.amcu_decision_cycle_covered(con,'1',['d1']))
        self.assertFalse(operational_tasks.amcu_decision_cycle_covered(con,'1',['d1','d2']))

    def test_manual_review_transition_snapshots_targets_but_does_not_complete(self):
        con=self.connection()
        con.executescript("""UPDATE operational_tasks SET status='ready_for_document',assigned_officer_id=1,
          protocol_number='701',protocol_date='2026-09-15' WHERE id='t';
          INSERT INTO authorized_officers VALUES(1,1);
          INSERT INTO generated_documents VALUES('t','amcu_exclusion_protocol','generated');""")
        current=dict(con.execute("SELECT * FROM operational_tasks WHERE id='t'").fetchone())
        current['amcu_decisions']=[]
        with patch.object(operational_tasks,'detail',return_value=current):
            operational_tasks.update(con,'t',{'status':'awaiting_sync'},'uo')
        self.assertEqual(con.execute("SELECT status FROM operational_tasks WHERE id='t'").fetchone()[0],
                         'awaiting_sync')
        self.assertEqual(con.execute("SELECT COUNT(*) FROM operational_task_qualifications WHERE task_id='t'").fetchone()[0],1)


class OperationalStatusGroupTests(unittest.TestCase):
    def test_groups_are_single_source_for_kpi_and_list(self):
        con=sqlite3.connect(":memory:"); con.row_factory=sqlite3.Row
        con.create_function("CASEFOLD",1,lambda value:(value or "").casefold())
        con.executescript("""CREATE TABLE operational_tasks(id TEXT,status TEXT,priority TEXT,created_at TEXT,task_type TEXT,assigned_officer_id TEXT,supplier_name_snapshot TEXT,supplier_code TEXT,source_context TEXT,document_context TEXT,metadata TEXT,due_at TEXT); CREATE TABLE authorized_officers(id TEXT,full_name TEXT); CREATE TABLE supplier_nazk_checks(id INTEGER,workflow_status TEXT,result TEXT,manager_name TEXT,completed_at TEXT,updated_at TEXT,responsible_officer_id TEXT,responsible_officer_name TEXT);""")
        rows=[("a","new"),("b","awaiting_response"),("c","completed"),("d","cancelled")]
        con.executemany("INSERT INTO operational_tasks VALUES(?,?, 'normal','2026-09-09','nazk_check',NULL,'Supplier','1','{}','{}','{}',NULL)",rows)
        queries=[]; con.set_trace_callback(lambda sql: queries.append(sql) if sql.lstrip().upper().startswith(('SELECT','WITH')) else None)
        active=operational_tasks.list_tasks(con,{})
        self.assertEqual(active["status_group"],"active"); self.assertEqual(active["total"],2); self.assertEqual(active["kpis"]["active"],2)
        self.assertEqual(len(queries),2)  # list projection + KPI statuses, independent of row count
        history=operational_tasks.list_tasks(con,{"status_group":["historical"]})
        self.assertEqual(history["total"],2); self.assertEqual({x["status"] for x in history["items"]},{"completed","cancelled"})

    def test_search_filters_by_unicode_supplier_name_or_code(self):
        con=sqlite3.connect(":memory:"); con.row_factory=sqlite3.Row
        con.create_function("CASEFOLD",1,lambda value:(value or "").casefold())
        con.executescript("""CREATE TABLE operational_tasks(id TEXT,status TEXT,priority TEXT,created_at TEXT,task_type TEXT,assigned_officer_id INTEGER,supplier_name_snapshot TEXT,supplier_code TEXT,source_context TEXT,document_context TEXT,metadata TEXT,due_at TEXT); CREATE TABLE authorized_officers(id INTEGER,full_name TEXT); CREATE TABLE supplier_nazk_checks(id INTEGER,workflow_status TEXT,result TEXT,manager_name TEXT,completed_at TEXT,updated_at TEXT,responsible_officer_id INTEGER,responsible_officer_name TEXT);""")
        con.executemany("INSERT INTO operational_tasks VALUES(?, 'in_progress','normal','2026-09-09','nazk_check',1,?,?, '{}','{}','{}',NULL)",[
            ("a",'ТОВАРИСТВО З ОБМЕЖЕНОЮ ВІДПОВІДАЛЬНІСТЮ "ГУРКІТ ГРУП"',"43897155"),
            ("b",'ІНШИЙ ПОСТАЧАЛЬНИК',"12345678"),
        ])
        by_name=operational_tasks.list_tasks(con,{"search":["гуркі"]})
        by_code=operational_tasks.list_tasks(con,{"search":["43897155"]})
        combined=operational_tasks.list_tasks(con,{"search":["гуркі"],"type":["nazk_check"],"officer":["1"],"date_from":["2026-09-01"]})
        cleared=operational_tasks.list_tasks(con,{"search":[""]})
        self.assertEqual([item["supplier_code"] for item in by_name["items"]],["43897155"])
        self.assertEqual([item["supplier_code"] for item in by_code["items"]],["43897155"])
        self.assertEqual([item["supplier_code"] for item in combined["items"]],["43897155"])
        self.assertEqual(cleared["total"],2)

    def test_nazk_task_becomes_cancelled_when_effective_activity_disappears(self):
        con=sqlite3.connect(":memory:"); con.row_factory=sqlite3.Row
        con.executescript("""CREATE TABLE operational_tasks(id TEXT PRIMARY KEY,supplier_code TEXT,task_type TEXT,status TEXT,resolution_code TEXT DEFAULT '',resolution_text TEXT DEFAULT '',resolved_at TEXT,resolved_by TEXT,updated_at TEXT,version INTEGER DEFAULT 1); CREATE TABLE operational_task_events(id INTEGER PRIMARY KEY AUTOINCREMENT,task_id TEXT,event_type TEXT,created_at TEXT,actor TEXT,old_value TEXT,new_value TEXT,metadata TEXT);""")
        con.execute("INSERT INTO operational_tasks(id,supplier_code,task_type,status,updated_at) VALUES('task1','37066465','nazk_check','in_progress','old')")
        first=operational_tasks.reconcile_stale_nazk_tasks(con,'test',supplier_codes=['37066465'],active_applications={})
        second=operational_tasks.reconcile_stale_nazk_tasks(con,'test',supplier_codes=['37066465'],active_applications={})
        row=con.execute("SELECT status,resolution_code FROM operational_tasks WHERE id='task1'").fetchone()
        self.assertEqual(first['cancelled'],1); self.assertEqual(second['cancelled'],0)
        self.assertEqual(tuple(row),('cancelled','no_active_qualifications'))
        self.assertEqual(con.execute("SELECT COUNT(*) FROM operational_task_events").fetchone()[0],1)


class OperationalTaskCardTests(unittest.TestCase):
    def action_connection(self):
        con=sqlite3.connect(":memory:"); con.row_factory=sqlite3.Row
        con.executescript("""CREATE TABLE operational_tasks(id TEXT PRIMARY KEY,status TEXT,resolution_code TEXT,resolved_at TEXT,resolved_by TEXT,updated_at TEXT,version INTEGER);
          CREATE TABLE operational_task_events(id INTEGER PRIMARY KEY AUTOINCREMENT,task_id TEXT,event_type TEXT,created_at TEXT,actor TEXT,old_value TEXT,new_value TEXT,metadata TEXT);
          CREATE TABLE supplier_nazk_checks(id INTEGER PRIMARY KEY,result TEXT,workflow_status TEXT,completed_at TEXT,updated_at TEXT,updated_by TEXT,result_at TEXT,result_by TEXT);
          CREATE TABLE supplier_nazk_check_events(id INTEGER PRIMARY KEY AUTOINCREMENT,check_id INTEGER,event_type TEXT,event_at TEXT,event_by TEXT,details_json TEXT);
          CREATE TABLE operational_task_blocking_decisions(task_id TEXT PRIMARY KEY,decision_date TEXT,protocol_number TEXT,prozorro_url TEXT,document_url TEXT,officer_note TEXT,attached_at TEXT,attached_by TEXT,used_for_blocking INTEGER);""")
        con.execute("INSERT INTO operational_tasks VALUES('t','in_progress','',NULL,NULL,'',1)")
        return con

    def test_manual_nazk_result_confirmed_and_insufficient(self):
        con=self.action_connection(); con.execute("INSERT INTO supplier_nazk_checks VALUES(7,'needs_review','in_progress',NULL,'','','','')")
        current={'id':'t','task_type':'nazk_check','status':'in_progress','source_context':{'nazk_check_id':7},'channels':{},'effective_active_count':1}
        with patch.object(operational_tasks,'detail',return_value=current):
            operational_tasks.set_nazk_result(con,'t','confirmed','uo')
        self.assertEqual(tuple(con.execute("SELECT status,resolution_code FROM operational_tasks").fetchone()),('ready_for_document','nazk_confirmed'))
        con.execute("UPDATE operational_tasks SET status='in_progress',resolution_code='' WHERE id='t'")
        current['channels']={'supplier':{'status':'waiting'}}
        with patch.object(operational_tasks,'detail',return_value=current): operational_tasks.set_nazk_result(con,'t','insufficient','uo')
        self.assertEqual(con.execute("SELECT status FROM operational_tasks").fetchone()[0],'waiting_external')

    def test_nazk_not_current_is_terminal_but_nonfactual(self):
        con=self.action_connection(); con.execute("INSERT INTO supplier_nazk_checks VALUES(7,'needs_review','in_progress',NULL,'','','','')")
        current={'id':'t','task_type':'nazk_check','status':'in_progress','source_context':{'nazk_check_id':7},'channels':{},'effective_active_count':1}
        with patch.object(operational_tasks,'detail',return_value=current):
            operational_tasks.set_nazk_result(con,'t','not_current','uo','Перевірено УО')
        self.assertEqual(tuple(con.execute("SELECT status,resolution_code FROM operational_tasks").fetchone()),('completed','nazk_not_current'))
        self.assertEqual(tuple(con.execute("SELECT result,workflow_status FROM supplier_nazk_checks").fetchone()),(None,'not_current'))

    def test_warning_protocol_validation_and_completion(self):
        con=self.action_connection(); current={'id':'t','task_type':'warning_block','status':'in_progress'}
        with patch.object(operational_tasks,'detail',return_value=current):
            with self.assertRaisesRegex(ValueError,'валідне посилання'): operational_tasks.attach_blocking_decision(con,'t',{'decision_date':'2026-09-03','protocol_number':'670','prozorro_url':'bad'},'uo')
            operational_tasks.attach_blocking_decision(con,'t',{'decision_date':'2026-09-03','protocol_number':'670','prozorro_url':'https://prozorro.gov.ua/x'},'uo')
        row=con.execute("SELECT protocol_number,used_for_blocking FROM operational_task_blocking_decisions").fetchone()
        self.assertEqual(tuple(row),('670',1))
        complete={**current,'blocking_factual_state':'blocked','blocking_decision':{'decision_date':'2026-09-03','protocol_number':'670','prozorro_url':'https://prozorro.gov.ua/x'}}
        with patch.object(operational_tasks,'detail',return_value=complete): operational_tasks.complete_legacy_blocking(con,'t','uo')
        self.assertEqual(tuple(con.execute("SELECT status,resolution_code FROM operational_tasks").fetchone()),('completed','legacy_blocking_confirmed'))

    def test_warning_zero_active_does_not_cancel(self):
        item={'task_type':'warning_block','effective_active_count':0,'status':'new'}
        self.assertEqual(item['status'],'new')

    def test_warning_highlight_requires_attached_decision_and_expires(self):
        con=sqlite3.connect(":memory:"); con.row_factory=sqlite3.Row
        con.executescript("""CREATE TABLE operational_tasks(id TEXT PRIMARY KEY,status TEXT,source_context TEXT);
          CREATE TABLE violation_reports(id TEXT PRIMARY KEY,report_id TEXT);
          CREATE TABLE operational_task_warnings(task_id TEXT,violation_report_id TEXT);
          CREATE TABLE operational_task_blocking_decisions(task_id TEXT,protocol_number TEXT,decision_date TEXT,used_for_blocking INTEGER);
          INSERT INTO operational_tasks VALUES('t','completed','{"blocking_start_date":"2026-09-03","blocking_end_date":"2099-12-31"}');
          INSERT INTO violation_reports VALUES('v','UA-D-1'); INSERT INTO operational_task_warnings VALUES('t','v');""")
        self.assertEqual(operational_tasks.warning_marker_map(con),{})
        con.execute("INSERT INTO operational_task_blocking_decisions VALUES('t','670','2026-09-03',1)")
        self.assertTrue(operational_tasks.warning_marker_map(con)['UA-D-1']['highlighting_active'])
        con.execute("UPDATE operational_tasks SET source_context=?",(json.dumps({'blocking_end_date':'2000-01-01'}),))
        self.assertFalse(operational_tasks.warning_marker_map(con)['UA-D-1']['highlighting_active'])
    def test_previous_manager_task_is_cancelled_without_deleting_history(self):
        con=sqlite3.connect(":memory:"); con.row_factory=sqlite3.Row
        con.create_function("DIGITS",1,lambda value:"".join(x for x in str(value or "") if x.isdigit()))
        con.create_function("NORMALIZE_NAME",1,lambda value:" ".join(str(value or "").casefold().split()))
        con.executescript("""CREATE TABLE operational_tasks(id TEXT PRIMARY KEY,supplier_code TEXT,task_type TEXT,status TEXT,
          source_context TEXT,resolution_code TEXT DEFAULT '',resolution_text TEXT DEFAULT '',resolved_at TEXT,resolved_by TEXT,
          updated_at TEXT,version INTEGER DEFAULT 1);
          CREATE TABLE operational_task_events(id INTEGER PRIMARY KEY AUTOINCREMENT,task_id TEXT,event_type TEXT,created_at TEXT,
          actor TEXT,old_value TEXT,new_value TEXT,metadata TEXT);
          CREATE TABLE supplier_nazk_checks(id INTEGER PRIMARY KEY,manager_id INTEGER,manager_name TEXT);
          CREATE TABLE supplier_managers(id INTEGER PRIMARY KEY,supplier_code TEXT,manager_name TEXT,normalized_name TEXT,
          manager_tax_id TEXT,is_current INTEGER);""")
        con.execute("INSERT INTO supplier_managers VALUES(2,'123','PERSON B','person b','',1)")
        con.execute("INSERT INTO supplier_nazk_checks VALUES(7,1,'PERSON A')")
        con.execute("INSERT INTO operational_tasks VALUES('t','123','nazk_check','in_progress',?,'','','',NULL,'old',1)",
                    (json.dumps({'nazk_check_id':7}),))
        first=operational_tasks.reconcile_irrelevant_nazk_managers(con,'test',['123'])
        second=operational_tasks.reconcile_irrelevant_nazk_managers(con,'test',['123'])
        self.assertEqual(first['cancelled'],1); self.assertEqual(second['cancelled'],0)
        self.assertEqual(tuple(con.execute("SELECT status,resolution_code FROM operational_tasks").fetchone()),
                         ('cancelled','manager_changed'))
        self.assertEqual(con.execute("SELECT COUNT(*) FROM operational_task_events").fetchone()[0],1)

    def test_document_context_keeps_per_decision_links_and_frozen_warnings(self):
        amcu=operational_tasks.build_document_context({'task_type':'amcu_exclusion','supplier_code':'1',
          'supplier_name_snapshot':'S','assigned_officer_id':4,'assigned_officer_name':'Officer',
          'effective_applications':[{'id':'q1'}],'amcu_decisions':[{'decision_date':'2026-04-09',
          'decision_no':'60/44-р/к','extract_url':'https://one'}]})
        self.assertEqual(amcu['amcu_decisions'][0]['displayed_text'],'від 2026-04-09 № 60/44-р/к')
        self.assertEqual(amcu['amcu_decisions'][0]['hyperlink'],'https://one')
        warning_context=operational_tasks.build_document_context({'task_type':'warning_block','supplier_code':'1',
          'supplier_name_snapshot':'S','source_context':{'threshold_type':'3_in_1_rolling_month',
          'threshold_reached_at':'2026-09-01','blocking_start_date':'2026-09-01','blocking_end_date':'2026-11-30'},
          'warnings':[{'report_id':'UA-D-1'}]})
        self.assertEqual(warning_context['protocol_date'],'2026-09-01')
        self.assertEqual(warning_context['warning_references'][0]['report_id'],'UA-D-1')

    def test_amcu_extract_urls_persist_per_decision_and_are_idempotent(self):
        con=sqlite3.connect(":memory:"); con.row_factory=sqlite3.Row
        con.executescript("""CREATE TABLE operational_task_amcu_decisions(
          task_id TEXT,amcu_decision_id TEXT,extract_url TEXT,created_at TEXT,updated_at TEXT,updated_by TEXT,
          PRIMARY KEY(task_id,amcu_decision_id));
          CREATE TABLE operational_task_events(id INTEGER PRIMARY KEY AUTOINCREMENT,task_id TEXT,event_type TEXT,
          created_at TEXT,actor TEXT,old_value TEXT,new_value TEXT,metadata TEXT);
          INSERT INTO operational_task_amcu_decisions VALUES('t','d1','','','','');
          INSERT INTO operational_task_amcu_decisions VALUES('t','d2','','','','');""")
        payload=[{'decision_id':'d1','extract_url':' https://example.test/one '},
                 {'decision_id':'d2','extract_url':'https://example.test/two'}]
        self.assertEqual(operational_tasks.update_amcu_extracts(con,'t',payload,'uo'),2)
        self.assertEqual([tuple(r) for r in con.execute(
          "SELECT amcu_decision_id,extract_url FROM operational_task_amcu_decisions ORDER BY amcu_decision_id")],
          [('d1','https://example.test/one'),('d2','https://example.test/two')])
        self.assertEqual(con.execute("SELECT COUNT(*) FROM operational_task_events").fetchone()[0],2)
        self.assertEqual(operational_tasks.update_amcu_extracts(con,'t',payload,'uo'),0)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM operational_task_events").fetchone()[0],2)

    def test_amcu_extract_batch_rejects_unlinked_decision(self):
        con=sqlite3.connect(":memory:"); con.row_factory=sqlite3.Row
        con.executescript("""CREATE TABLE operational_task_amcu_decisions(
          task_id TEXT,amcu_decision_id TEXT,extract_url TEXT,created_at TEXT,updated_at TEXT,updated_by TEXT,
          PRIMARY KEY(task_id,amcu_decision_id));
          CREATE TABLE operational_task_events(id INTEGER PRIMARY KEY AUTOINCREMENT,task_id TEXT,event_type TEXT,
          created_at TEXT,actor TEXT,old_value TEXT,new_value TEXT,metadata TEXT);
          INSERT INTO operational_task_amcu_decisions VALUES('t','d1','','','','');""")
        with self.assertRaisesRegex(ValueError,'не пов’язане'):
            operational_tasks.update_amcu_extracts(
              con,'t',[{'decision_id':'another','extract_url':'https://example.test'}],'uo')
        self.assertEqual(con.execute("SELECT extract_url FROM operational_task_amcu_decisions").fetchone()[0],'')
        self.assertEqual(con.execute("SELECT COUNT(*) FROM operational_task_events").fetchone()[0],0)

    def test_main_task_save_persists_amcu_url_before_document_gate(self):
        con=sqlite3.connect(":memory:"); con.row_factory=sqlite3.Row
        con.executescript("""CREATE TABLE operational_tasks(id TEXT PRIMARY KEY,task_type TEXT,status TEXT,
          assigned_officer_id INTEGER,resolution_code TEXT,resolution_text TEXT,protocol_number TEXT,
          protocol_date TEXT,protocol_reference TEXT,published_reference TEXT,resolved_at TEXT,resolved_by TEXT,
          updated_at TEXT,version INTEGER);
          CREATE TABLE authorized_officers(id INTEGER PRIMARY KEY,active INTEGER);
          CREATE TABLE operational_task_amcu_decisions(task_id TEXT,amcu_decision_id TEXT,extract_url TEXT,
          created_at TEXT,updated_at TEXT,updated_by TEXT,PRIMARY KEY(task_id,amcu_decision_id));
          CREATE TABLE operational_task_events(id INTEGER PRIMARY KEY AUTOINCREMENT,task_id TEXT,event_type TEXT,
          created_at TEXT,actor TEXT,old_value TEXT,new_value TEXT,metadata TEXT);
          INSERT INTO operational_tasks VALUES('t','amcu_exclusion','in_progress',1,'','','','','','',NULL,NULL,'',1);
          INSERT INTO authorized_officers VALUES(1,1);
          INSERT INTO operational_task_amcu_decisions VALUES('t','d1','','','','');""")
        def current(_con,task_id):
            task=dict(_con.execute("SELECT * FROM operational_tasks WHERE id=?",(task_id,)).fetchone())
            task['amcu_decisions']=[dict(r) for r in _con.execute(
              "SELECT amcu_decision_id row_key,extract_url FROM operational_task_amcu_decisions WHERE task_id=?",(task_id,))]
            return task
        with patch.object(operational_tasks,'detail',side_effect=current):
            result=operational_tasks.update(con,'t',{'status':'ready_for_document','assigned_officer_id':1,
              'protocol_number':'701','protocol_date':'2026-09-14',
              'amcu_decisions':[{'decision_id':'d1','extract_url':'https://example.test/extract'}]},'uo')
        self.assertEqual(result['status'],'ready_for_document')
        self.assertEqual((result['protocol_number'],result['protocol_date']),('701','2026-09-14'))
        self.assertEqual(result['amcu_decisions'][0]['extract_url'],'https://example.test/extract')
        self.assertEqual([r[0] for r in con.execute(
          "SELECT event_type FROM operational_task_events ORDER BY id")],['amcu_extract_url_added','status_changed'])

    def test_active_task_renderer_installs_amcu_row_save_handler(self):
        source = Path(__file__).with_name("app.js").read_text(encoding="utf-8")
        before_polish_wrapper = source[:source.index("const openOperationalTaskPolished=")]
        active_renderer = before_polish_wrapper[before_polish_wrapper.rfind("openOperationalTask=async function(taskId){"):]
        self.assertIn("installOperationalAmcuActions(item,body)", active_renderer)
        self.assertIn("button.closest('tr')", source)
        self.assertIn("/amcu-decisions/${encodeURIComponent(button.dataset.decision)}", source)
        self.assertIn('data-amcu-protocol-number', source)
        self.assertIn('data-amcu-protocol-date', source)
        self.assertIn('/documents/amcu-exclusion-protocol', source)
        self.assertIn('openDeclensionFromAmcuValidation', source)
        self.assertIn("originType:'operational_task'", source)
        self.assertIn('title="Зберегти посилання на витяг"', source)
        self.assertIn('aria-label="Завантажити DOCX"', source)
        self.assertIn('aria-label="Завантажити PDF"', source)
        self.assertIn('resolvedDocumentMetadataHtml(latest.resolved_metadata)', source)
        self.assertIn("marketplaceApplicationsUrl(x.marketplace_url,supplierCode)", source)


if __name__ == "__main__":
    unittest.main()
