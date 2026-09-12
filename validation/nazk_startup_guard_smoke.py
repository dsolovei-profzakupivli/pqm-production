"""Unrelated WEB startup/sync paths cannot mutate NAZK, even with stored matches."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import web_smoke as web
s = web.server


class GuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        web.fixture()
        with s.db() as con:
            con.execute("INSERT INTO supplier_registry_summary(supplier_code,active_count,refreshed_at) VALUES('12345678',1,'before')")
            con.execute("INSERT INTO supplier_managers(supplier_code,manager_name,normalized_name,is_current,source,created_at,updated_at) VALUES('12345678','TEST PERSON','test person',1,'test','before','before')")
            con.execute("INSERT INTO nazk_registry(source_id,full_name,sentence_date,raw_json) VALUES('match','TEST PERSON','2026-01-01','{}')")

    def assert_no_nazk(self):
        with s.db() as con:
            self.assertEqual(0, con.execute('SELECT COUNT(*) FROM supplier_nazk_checks').fetchone()[0])
            self.assertEqual(0, con.execute("SELECT COUNT(*) FROM operational_tasks WHERE task_type='nazk_check'").fetchone()[0])

    def test_generic_two_rebuilds_are_nazk_free(self):
        with patch.object(s, 'reconcile_active_supplier_nazk', side_effect=AssertionError('unexpected reconciliation')), \
             patch.object(s.operational_tasks, 'materialize_nazk_tasks', side_effect=AssertionError('unexpected materialization')), \
             patch.object(s.operational_tasks, 'reconcile_stale_nazk_tasks', side_effect=AssertionError('unexpected cancellation')), \
             patch.object(s.operational_tasks, 'reconcile_irrelevant_nazk_managers', side_effect=AssertionError('unexpected cancellation')):
            for _ in range(2):
                self.assertEqual(0, s.rebuild_operational_tasks()['nazk'])
        self.assert_no_nazk()

    def test_violation_startup_catchup_with_nazk_disabled(self):
        class EndLoop(Exception):
            pass
        def start_job(*, trigger):
            self.assertEqual('startup_catchup', trigger)
            s.sync_violation_reports_worker()
            return True
        with patch.object(s, 'ENABLE_VIOLATION_SCHEDULER', True), \
             patch.object(s, 'ENABLE_NAZK_SCHEDULER', False), \
             patch.object(s, 'paginated_pages', return_value=iter([])), \
             patch.object(s.scheduler_runtime, 'state', return_value=[{'job':'violation_reports','last_finished_at':None}]), \
             patch.object(s, 'start_violation_reports_sync', side_effect=start_job) as start, \
             patch.object(s, '_scheduler_is_configured', return_value=True), \
             patch.object(s, '_wait_until', side_effect=EndLoop), \
             patch.object(s, 'reconcile_active_supplier_nazk', side_effect=AssertionError('unrelated NAZK write')):
            with self.assertRaises(EndLoop):
                s.violation_reports_scheduler(Mock(wait=lambda _:False, is_set=lambda:False))
            start.assert_called_once_with(trigger='startup_catchup')
        self.assert_no_nazk()

    def test_prozorro_workers_do_not_reconcile_nazk(self):
        result={'framework':'fixture','completed':0,'frameworks':0,'submissions':0,'qualifications':0,'contracts':0,'errors':[]}
        with patch.object(s, 'sync_one_framework', return_value=result), \
             patch.object(s, 'sync_all_tracked_frameworks', return_value=result), \
             patch.object(s, 'sync_incremental_active_frameworks', return_value=result), \
             patch.object(s, 'sync_framework_officers'), \
             patch.object(s, 'reconcile_active_supplier_nazk', side_effect=AssertionError('unrelated NAZK write')):
            s.sync_worker('fixture')
            s.sync_all_worker()
            s.sync_incremental_worker()
        self.assert_no_nazk()

    def test_nazk_job_requires_explicit_enable(self):
        with patch.dict(os.environ, {'PQM_ENABLE_NAZK_WORKFLOW':'0'}), patch.object(s,'reconcile_active_supplier_nazk') as reconcile:
            self.assertEqual('nazk_workflow_disabled',s.rebuild_nazk_tasks('test',workflow='nazk_job')['skipped'])
            reconcile.assert_not_called()
        with self.assertRaises(ValueError):
            s.rebuild_nazk_tasks('test',workflow='appeals')

    def test_explicit_maintenance_routes_to_nazk_only(self):
        with patch.object(s,'reconcile_active_supplier_nazk',return_value={'items':[]}) as reconcile, \
             patch.object(s.operational_tasks,'materialize_nazk_tasks',return_value={'created':0}) as materialize, \
             patch.object(s.operational_tasks,'build',side_effect=AssertionError('unrelated task write')):
            self.assertEqual(0,s.rebuild_nazk_tasks('test',workflow='maintenance')['created'])
            self.assertTrue(reconcile.call_args.kwargs['apply'])
            materialize.assert_called_once()


if __name__ == '__main__':
    unittest.main(verbosity=2)
