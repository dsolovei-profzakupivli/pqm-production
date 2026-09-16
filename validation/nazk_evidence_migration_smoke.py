"""Synthetic-only regression for legacy evidence imports, including sqlite_sequence."""
import json
from pathlib import Path
import sqlite3
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import nazk_evidence
import operational_tasks


class LegacyEvidenceMigrationTests(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.addCleanup(self.con.close)
        self.con.execute("PRAGMA foreign_keys=ON")
        self.con.executescript("""
            CREATE TABLE authorized_officers(id INTEGER PRIMARY KEY, full_name TEXT);
            CREATE TABLE supplier_nazk_checks(
                id INTEGER PRIMARY KEY, result TEXT, completed_at TEXT, updated_by TEXT);
            INSERT INTO supplier_nazk_checks VALUES (1,'refuted','2026-09-01','historical');
            INSERT INTO supplier_nazk_checks VALUES (2,NULL,NULL,'historical');
        """)
        operational_tasks.migrate(self.con)
        for check_id in (1, 2):
            self.con.execute("""INSERT INTO operational_tasks
                (id,task_key,task_type,supplier_code,created_at,updated_at,source_context)
                VALUES (?,?,'nazk_check','10000001','now','now',?)""",
                (f"task-{check_id}", f"key-{check_id}", json.dumps({"nazk_check_id": check_id})))

    def response(self, task="task-1"):
        return self.con.execute("""INSERT INTO operational_task_responses
            (task_id,source,response_date,summary,information_result,recorded_at,recorded_by)
            VALUES (?,'supplier','2026-09-01','historical evidence','refuted','now','historical')""",
            (task,)).lastrowid

    def sequence(self):
        row = self.con.execute("SELECT seq FROM sqlite_sequence WHERE name='supplier_nazk_check_evidence'").fetchone()
        return row[0] if row else 0

    def evidence(self):
        return self.con.execute("SELECT * FROM supplier_nazk_check_evidence ORDER BY id").fetchall()

    def test_eight_imports_then_three_migrations_are_sequence_noop(self):
        for _ in range(8):
            self.response()
        nazk_evidence.migrate(self.con)
        before, sequence = self.evidence(), self.sequence()
        self.assertEqual(len(before), 8)
        for _ in range(3):
            nazk_evidence.migrate(self.con)
            self.assertEqual(self.evidence(), before)
            self.assertEqual(self.sequence(), sequence)

    def test_shared_schema_path_does_not_consume_evidence_ids(self):
        self.response()
        operational_tasks.migrate(self.con)
        before, sequence = self.evidence(), self.sequence()
        for _ in range(3):
            operational_tasks.migrate(self.con)
        self.assertEqual(self.evidence(), before)
        self.assertEqual(self.sequence(), sequence)

    def test_only_new_response_is_imported_and_consumes_one_id(self):
        for _ in range(8):
            self.response()
        nazk_evidence.migrate(self.con)
        before, sequence = self.evidence(), self.sequence()
        response_id = self.response("task-2")
        nazk_evidence.migrate(self.con)
        self.assertEqual(self.evidence()[:8], before)
        self.assertEqual(self.sequence(), sequence + 1)
        row = self.con.execute("SELECT check_id,source_task_id FROM supplier_nazk_check_evidence WHERE legacy_task_response_id=?", (response_id,)).fetchone()
        self.assertEqual(row, (2, "task-2"))
        nazk_evidence.migrate(self.con)
        self.assertEqual(self.sequence(), sequence + 1)

    def test_imported_evidence_and_factual_check_are_not_overwritten(self):
        self.response()
        nazk_evidence.migrate(self.con)
        self.con.execute("UPDATE supplier_nazk_check_evidence SET short_summary='canonical correction',updated_by='officer'")
        self.con.execute("UPDATE operational_task_responses SET summary='changed legacy text'")
        evidence, sequence = self.evidence(), self.sequence()
        checks = self.con.execute("SELECT * FROM supplier_nazk_checks ORDER BY id").fetchall()
        nazk_evidence.migrate(self.con)
        self.assertEqual(self.evidence(), evidence)
        self.assertEqual(self.con.execute("SELECT * FROM supplier_nazk_checks ORDER BY id").fetchall(), checks)
        self.assertEqual(self.sequence(), sequence)

    def test_native_evidence_without_legacy_id_is_preserved(self):
        self.con.execute("""INSERT INTO supplier_nazk_check_evidence
            (check_id,short_summary,recorded_at,recorded_by) VALUES (1,'native','now','officer')""")
        native = self.evidence()[0]
        self.response()
        nazk_evidence.migrate(self.con)
        self.assertEqual(self.evidence()[0], native)
        self.assertEqual(len(self.evidence()), 2)
        sequence = self.sequence()
        nazk_evidence.migrate(self.con)
        self.assertEqual(self.sequence(), sequence)

    def test_non_nazk_or_unlinked_response_is_not_imported(self):
        self.con.execute("UPDATE operational_tasks SET task_type='manual' WHERE id='task-1'")
        self.con.execute("UPDATE operational_tasks SET source_context='{}' WHERE id='task-2'")
        self.response("task-1")
        self.response("task-2")
        nazk_evidence.migrate(self.con)
        self.assertEqual(self.evidence(), [])
        self.assertEqual(self.sequence(), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
