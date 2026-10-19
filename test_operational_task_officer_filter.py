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
          INSERT INTO supplier_nazk_checks VALUES(901,9,'Інший знімок імені',NULL,NULL,NULL,NULL,NULL);
          INSERT INTO supplier_nazk_checks VALUES(902,NULL,'Олена Коваль',NULL,NULL,NULL,NULL,NULL);
        """)
        self.con.executemany("""INSERT INTO operational_tasks
          (id,task_type,status,assigned_officer_id,priority,created_at,source_context,
           document_context,metadata,due_at,supplier_name_snapshot,supplier_code,resolved_by)
          VALUES(?,?,?,?,?,'2026-10-18',?,'{}','{}',NULL,?,?,?)""",[
            ('active-42','warning_block','in_progress',42,'high','{}','Активне','10000001',None),
            ('active-43','warning_block','new',43,'normal','{}','Ще активне','10000007',None),
            ('done-7','warning_block','completed',7,'normal','{}','Завершене','10000002','Редактор'),
            ('nazk-9','nazk_check','new',42,'high','{"nazk_check_id":901}','НАЗК canonical','10000003',None),
            ('unassigned','warning_block','new',None,'normal','{}','Без призначення','10000004',None),
            ('snapshot-only','nazk_check','completed',None,'normal','{"nazk_check_id":902}','Історичне ім’я','10000005',None),
            ('editor-only','warning_block','completed',None,'normal','{}','Тільки редактор','10000006','Не відповідальна УО'),
        ])

    def tearDown(self):
        self.con.close()

    def get_tasks(self,**params):
        return operational_tasks.list_tasks(self.con,params)

    def test_options_cover_all_statuses_nazk_and_name_snapshots(self):
        result=self.get_tasks(status_group=['active'],search=['Активне'])
        options={item['value']:item['full_name'] for item in result['officers']}
        self.assertEqual(options['42'],'Ірина Мельник')
        self.assertEqual(options['43'],'Марина Шевченко')
        self.assertEqual(options['7'],'Оксана Петренко')
        self.assertEqual(options['9'],'Тетяна Бондар')
        self.assertEqual(options['__legacy_snapshot__:Олена Коваль'],'Олена Коваль')
        self.assertNotIn('Не відповідальна УО',options.values())

    def test_ids_are_stable_and_nazk_uses_canonical_assignment(self):
        self.assertEqual([x['id'] for x in self.get_tasks(officer=['9'])['items']],['nazk-9'])
        self.assertEqual([x['id'] for x in self.get_tasks(officer=['42'])['items']],['active-42'])
        self.assertEqual([x['id'] for x in self.get_tasks(officer=['7'],status_group=['historical'])['items']],['done-7'])
        self.assertEqual([x['id'] for x in self.get_tasks(officer=['__legacy_snapshot__:Олена Коваль'],status_group=['historical'])['items']],['snapshot-only'])

    def test_unassigned_and_editor_are_not_confused_with_historical_assignment(self):
        self.assertEqual([x['id'] for x in self.get_tasks(officer=['__unassigned__'])['items']],['unassigned'])
        historical={x['id'] for x in self.get_tasks(officer=['__unassigned__'],status_group=['historical'])['items']}
        self.assertEqual(historical,{'editor-only'})
        self.assertNotIn('snapshot-only',historical)

    def test_selection_can_filter_after_status_change_and_counts_remain_global(self):
        active=self.get_tasks(status_group=['active'],officer=['42'])
        completed=self.get_tasks(status_group=['completed'],officer=['42'])
        self.assertEqual([x['id'] for x in active['items']],['active-42'])
        self.assertEqual(completed['items'],[])
        self.assertEqual(active['kpis'],completed['kpis'])
        self.assertEqual(completed['total'],len(completed['items']))


if __name__ == '__main__':
    unittest.main()
