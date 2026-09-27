import sqlite3
import unittest

import operational_tasks


class OperationalTypeKpiTests(unittest.TestCase):
    def test_local_type_facet_respects_other_filters_not_selected_type(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.executescript("""
            CREATE TABLE operational_tasks(id TEXT, task_type TEXT, status TEXT,
                assigned_officer_id INTEGER, priority TEXT DEFAULT 'high',
                created_at TEXT DEFAULT '2026-09-26', source_context TEXT DEFAULT '{}',
                document_context TEXT DEFAULT '{}', metadata TEXT DEFAULT '{}',
                supplier_name_snapshot TEXT DEFAULT '', supplier_code TEXT DEFAULT '');
            CREATE TABLE authorized_officers(id INTEGER, full_name TEXT);
            CREATE TABLE supplier_nazk_checks(id INTEGER, responsible_officer_id INTEGER,
                responsible_officer_name TEXT, workflow_status TEXT, result TEXT,
                manager_name TEXT, completed_at TEXT, updated_at TEXT);
            INSERT INTO operational_tasks(id,task_type,status) VALUES
                ('1','amcu_exclusion','new'),
                ('2','amcu_exclusion','awaiting_response'),
                ('3','nazk_check','in_progress'),
                ('4','warning_block','ready_for_document'),
                ('5','termination_exclusion','new'),
                ('6','amcu_exclusion','completed');
        """)
        result = operational_tasks.list_tasks(con, {"status_group": ["active"], "type": ["amcu_exclusion"]})
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["type_counts"], {
            "amcu_exclusion": 2, "nazk_check": 1, "warning_block": 1,
            "termination_exclusion": 1,
        })
        self.assertEqual(result["kpis"]["completed"], 1)
        self.assertEqual(result["kpis"]["active"], 5)
        completed = operational_tasks.list_tasks(con, {"status_group": ["completed"]})
        self.assertEqual(completed["type_counts"], {"amcu_exclusion": 1})
        con.close()


if __name__ == "__main__":
    unittest.main()
