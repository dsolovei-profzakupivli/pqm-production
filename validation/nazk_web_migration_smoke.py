"""Synthetic, network-free regression coverage for the explicit WEB repair."""
import json
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import web_smoke as web
from migrations import web_nazk_history as m
from nazk_workflow import find_covering_factual_check

class MigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        web.fixture()

    def setUp(self):
        self.con=sqlite3.connect(':memory:')
        self.con.row_factory=sqlite3.Row
        with web.server.db() as src:src.backup(self.con)
        self.con.execute('PRAGMA foreign_keys=ON')

    def tearDown(self):
        self.con.close()

    def seed(self,result='спростовано',case='CASE-1',decision='01.01.2026',checked='01.02.2026',name='TEST PERSON',sources=1):
        c=self.con
        manager=c.execute("INSERT INTO supplier_managers(supplier_code,manager_name,normalized_name,is_current,source,created_at,updated_at) VALUES('12345678','TEST PERSON','test person',1,'test','before','before')").lastrowid
        c.execute("INSERT INTO supplier_nazk_reviews(supplier_code,manager_name,result,decision_date,case_number,checked_at,evidence_url,source_row,synced_at) VALUES('12345678',?,?,?,?,?,'https://example.test/historical-evidence',1,'before')",(name,result,decision,case,checked))
        cid=c.execute("INSERT INTO supplier_nazk_checks(supplier_code,manager_id,manager_name,workflow_status,started_at,created_at,created_by,updated_at,updated_by) VALUES('12345678',?,'TEST PERSON','needs_review','before','before','test','before','test')",(manager,)).lastrowid
        for i in range(sources):
            sid=str(i+1)
            c.execute("INSERT INTO nazk_registry(source_id,full_name,court_case_number,sentence_date,raw_json) VALUES(?,'TEST PERSON',?,'2026-01-01','{}')",(sid,'CASE-'+sid))
            c.execute("INSERT INTO supplier_nazk_check_matches VALUES(?,?,'candidate','before')",(cid,sid))
        c.execute("INSERT INTO operational_tasks(id,task_key,task_type,supplier_code,status,created_at,updated_at,source_context) VALUES('task','unique-key','nazk_check','12345678','in_progress','before','before',?)",(json.dumps({'nazk_check_id':cid}),))
        c.commit()
        return cid

    def run_plan(self):
        p=m.plan(self.con)
        m.apply(self.con,p,m.digest(p))
        return p

    def test_refuted_exact_cycle_cancels_not_completes(self):
        cid=self.seed()
        p=self.run_plan()
        self.assertEqual(1,p['summary']['duplicate_cycles_cancelled'])
        self.assertEqual(('legacy_archived',None),tuple(self.con.execute('SELECT workflow_status,result FROM supplier_nazk_checks WHERE id=?',(cid,)).fetchone()))
        self.assertEqual(('cancelled','duplicate_cycle_existing_factual'),tuple(self.con.execute('SELECT status,resolution_code FROM operational_tasks').fetchone()))
        factual=self.con.execute("SELECT * FROM supplier_nazk_checks WHERE result='refuted'").fetchone()
        self.assertEqual('2026-02-01',factual['completed_at'])
        self.assertIsNone(factual['evidence_date']) # checked date != document date

    def test_waiting_restores_without_correspondence(self):
        cid=self.seed(result='на запит')
        p=self.run_plan()
        self.assertEqual(1,p['summary']['waiting_restored'])
        self.assertEqual(1,self.con.execute('SELECT COUNT(*) FROM supplier_nazk_checks').fetchone()[0])
        self.assertEqual('waiting_response',self.con.execute('SELECT workflow_status FROM supplier_nazk_checks WHERE id=?',(cid,)).fetchone()[0])
        self.assertEqual('awaiting_response',self.con.execute('SELECT status FROM operational_tasks').fetchone()[0])
        for t in ['supplier_nazk_check_requests','supplier_nazk_check_documents','operational_task_responses']:
            self.assertEqual(0,self.con.execute('SELECT COUNT(*) FROM '+t).fetchone()[0])

    def test_inactive_never_factual_or_closes_current(self):
        self.seed(result='не актуально')
        p=self.run_plan()
        self.assertEqual(0,p['summary']['duplicate_cycles_cancelled'])
        self.assertEqual(0,self.con.execute('SELECT COUNT(*) FROM supplier_nazk_checks WHERE result IS NOT NULL').fetchone()[0])
        self.assertEqual('in_progress',self.con.execute('SELECT status FROM operational_tasks').fetchone()[0])

    def test_empty_result_stays_unresolved(self):
        self.seed(result='')
        p=self.run_plan()
        self.assertEqual(0,p['summary']['factual_refuted'])
        self.assertEqual('in_progress',self.con.execute('SELECT status FROM operational_tasks').fetchone()[0])

    def test_ambiguous_evidence_never_cancels(self):
        for kwargs in [dict(case=''),dict(decision=''),dict(checked='01.01.2020'),dict(name='OTHER PERSON'),dict(sources=2)]:
            with self.subTest(kwargs=kwargs):
                self.tearDown();self.setUp();self.seed(**kwargs)
                p=self.run_plan()
                self.assertEqual(0,p['summary']['factual_refuted'])
                self.assertEqual('in_progress',self.con.execute('SELECT status FROM operational_tasks').fetchone()[0])

    def test_idempotent_and_old_history_append_only(self):
        self.seed()
        legacy=[tuple(r) for r in self.con.execute('SELECT * FROM supplier_nazk_reviews')]
        p=self.run_plan()
        before=self.con.total_changes
        self.assertEqual(0,m.apply(self.con,p,m.digest(p))['changes'])
        self.assertEqual(before,self.con.total_changes)
        self.assertEqual(legacy,[tuple(r) for r in self.con.execute('SELECT * FROM supplier_nazk_reviews')])

    def test_concurrent_edit_fails_closed(self):
        self.seed();p=m.plan(self.con)
        self.con.execute("UPDATE operational_tasks SET version=version+1");self.con.commit()
        with self.assertRaisesRegex(RuntimeError,'source changed'):
            m.apply(self.con,p,m.digest(p))
        self.assertEqual(1,self.con.execute('SELECT COUNT(*) FROM supplier_nazk_checks').fetchone()[0])

    def test_failure_rolls_back_entire_migration(self):
        self.seed();p=m.plan(self.con)
        with patch.object(m,'check_event',side_effect=RuntimeError('test fault')):
            with self.assertRaisesRegex(RuntimeError,'test fault'):m.apply(self.con,p,m.digest(p))
        self.assertEqual(1,self.con.execute('SELECT COUNT(*) FROM supplier_nazk_checks').fetchone()[0])
        self.assertEqual('in_progress',self.con.execute('SELECT status FROM operational_tasks').fetchone()[0])

    def test_imported_factual_cannot_cover_unlinked_or_later_fact(self):
        check=dict(id=1,legacy_key=m.PREFIX+'test',workflow_status='completed',result='refuted',
                   covered_nazk_date='2026-02-01',source_ids='1',created_at='2026-09-11',completed_at='2026-02-01')
        self.assertIsNotNone(find_covering_factual_check([check],[dict(source_id='1',sentence_date='2026-01-01')]))
        for fact in [dict(source_id='2',sentence_date='2026-01-01'),dict(source_id='1',sentence_date='2026-03-01')]:
            self.assertIsNone(find_covering_factual_check([check],[fact]))

if __name__=='__main__':unittest.main(verbosity=2)
