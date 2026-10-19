import sqlite3
import subprocess
import unittest

import operational_tasks


class OperationalTaskOfficerFilterTests(unittest.TestCase):
    def setUp(self):
        self.con=sqlite3.connect(':memory:')
        self.con.row_factory=sqlite3.Row
        self.con.create_function('CASEFOLD',1,lambda value:(value or '').casefold())
        self.con.executescript("""
          CREATE TABLE operational_tasks(
            id TEXT,task_type TEXT,status TEXT,assigned_officer_id INTEGER,
            priority TEXT,created_at TEXT,source_context TEXT,document_context TEXT,
            metadata TEXT,due_at TEXT,supplier_name_snapshot TEXT,supplier_code TEXT,
            resolved_by TEXT
          );
          CREATE TABLE authorized_officers(id INTEGER,full_name TEXT,active INTEGER);
          CREATE TABLE supplier_nazk_checks(
            id INTEGER,responsible_officer_id INTEGER,responsible_officer_name TEXT,
            workflow_status TEXT,result TEXT,manager_name TEXT,completed_at TEXT,updated_at TEXT
          );
          INSERT INTO authorized_officers VALUES(42,'Ірина Мельник',1),(43,'Марина Шевченко',1),(7,'Оксана Петренко',0),(9,'Тетяна Бондар',1);
          INSERT INTO supplier_nazk_checks VALUES(901,9,'Знімок іншого імені',NULL,NULL,NULL,NULL,NULL);
          INSERT INTO supplier_nazk_checks VALUES(902,NULL,'Олена Коваль',NULL,NULL,NULL,NULL,NULL);
        """)
        self.con.executemany("""INSERT INTO operational_tasks
          (id,task_type,status,assigned_officer_id,priority,created_at,source_context,
           document_context,metadata,due_at,supplier_name_snapshot,supplier_code,resolved_by)
          VALUES(?,?,?,?,?,'2026-10-18',?,'{}','{}',NULL,?,?,?)""",[
            ('active-42','warning_block','in_progress',42,'high','{}','Активне призначення','10000001',None),
            ('active-43','warning_block','new',43,'normal','{}','Друге активне призначення','10000007',None),
            ('done-7','warning_block','completed',7,'normal','{}','Завершене історичне призначення','10000002','Редактор'),
            ('nazk-9','nazk_check','new',42,'high','{"nazk_check_id":901}','НАЗК canonical','10000003',None),
            ('unassigned','warning_block','new',None,'normal','{}','Без призначення','10000004',None),
            ('snapshot-only','nazk_check','completed',None,'normal','{"nazk_check_id":902}','Історичний snapshot','10000005',None),
            ('editor-only','warning_block','completed',None,'normal','{}','Лише редактор','10000006','Не відповідальна УО'),
        ])

    def tearDown(self):
        self.con.close()

    def get(self,**params):
        return operational_tasks.list_tasks(self.con,params)

    def test_officer_options_cover_all_statuses_and_canonical_nazk_assignment(self):
        result=self.get(status_group=['active'],search=['Активне призначення'])
        options={item['value']:item['full_name'] for item in result['officers']}
        self.assertEqual(options['42'],'Ірина Мельник')
        self.assertEqual(options['43'],'Марина Шевченко')
        self.assertEqual(options['7'],'Оксана Петренко')
        self.assertEqual(options['9'],'Тетяна Бондар')
        self.assertEqual(options['__legacy_snapshot__:Олена Коваль'],'Олена Коваль')
        self.assertNotIn('Не відповідальна УО',options.values())

    def test_filter_uses_stable_ids_and_nazk_canonical_id_not_task_fallback_or_editor(self):
        self.assertEqual([x['id'] for x in self.get(officer=['9'])['items']],['nazk-9'])
        self.assertEqual([x['id'] for x in self.get(officer=['42'])['items']],['active-42'])
        self.assertEqual([x['id'] for x in self.get(officer=['43'])['items']],['active-43'])
        self.assertEqual([x['id'] for x in self.get(officer=['7'],status_group=['historical'])['items']],['done-7'])
        self.assertEqual([x['id'] for x in self.get(officer=['__legacy_snapshot__:Олена Коваль'],status_group=['historical'])['items']],['snapshot-only'])

    def test_unassigned_is_separate_and_name_only_history_is_not_reassigned(self):
        active=self.get(officer=['__unassigned__'])
        self.assertEqual([x['id'] for x in active['items']],['unassigned'])
        history=self.get(officer=['__unassigned__'],status_group=['historical'])
        self.assertEqual({x['id'] for x in history['items']},{'editor-only'})
        self.assertNotIn('snapshot-only',{x['id'] for x in history['items']})

    def test_selection_and_counts_survive_status_refresh_and_results_are_not_paginated_away(self):
        active=self.get(status_group=['active'],officer=['42'])
        completed=self.get(status_group=['completed'],officer=['42'])
        self.assertEqual(active['status_group'],'active')
        self.assertEqual(completed['status_group'],'completed')
        self.assertEqual(active['total'],1)
        self.assertEqual(completed['total'],0)
        self.assertEqual(active['kpis'],completed['kpis'])
        self.assertEqual(len(active['items']),active['total'])
        self.assertEqual(len(completed['items']),completed['total'])

    def test_ui_rebuilds_options_without_dropping_selected_officer(self):
        result=subprocess.run(['node','validation/operational_task_officer_filter_unit.cjs'],
                              capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':
    unittest.main()
