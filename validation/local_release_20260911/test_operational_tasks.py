import unittest
from datetime import date

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


if __name__ == "__main__":
    unittest.main()
