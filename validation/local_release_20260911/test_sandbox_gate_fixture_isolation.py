"""Regression for Gate 44947804174; temporary DBs and loopback only."""
import os
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import Mock, patch
import server
import test_sandbox_functionality_repair as repair

class GateFixtureIsolationTests(unittest.TestCase):
    def state(self):
        return server.DB_PATH,server.AUTH_ENABLED,dict(os.environ),socket.getfqdn,list(sys.path)

    def test_seeded_gate_does_not_collide_and_restores_all_fixture_state(self):
        class Probe(repair.SavedHistoryHTTPTests):pass
        with patch.dict(os.environ,{'PQM_RELEASE_SCHEMA_ONLY':'0'}):
            before=self.state()
            try:
                Probe.setUpClass()
                self.assertNotEqual(server.DB_PATH,before[0])
                self.assertTrue(server.AUTH_ENABLED)
                with server.db() as con:
                    self.assertEqual([r[0] for r in con.execute('SELECT id FROM authorized_officers ORDER BY id')],[1,2])
                self.assertEqual(os.environ['PQM_RELEASE_SCHEMA_ONLY'],'0')
                self.assertEqual(socket.getfqdn,before[3]);self.assertEqual(sys.path,before[4])
            finally:Probe.doClassCleanups()
            self.assertEqual(self.state(),before)
            self.assertFalse(Probe.thread.is_alive())
            self.assertFalse(Path(Probe.folder.name).exists())

    def test_setup_exception_cleans_auth_db_environment_and_next_scheduler_http(self):
        class Probe(repair.SavedHistoryHTTPTests):pass
        before=self.state()
        with patch.object(server,'init_reference_tables',side_effect=RuntimeError('injected fixture failure')):
            outcome=unittest.TestResult()
            unittest.TestSuite([Probe('test_saved_statuses_are_identical_for_three_read_roles')]).run(outcome)
        self.assertEqual(len(outcome.errors),1);self.assertIn('injected fixture failure',outcome.errors[0][1])
        self.assertEqual(self.state(),before)
        self.assertFalse(Path(Probe.folder.name).exists())
        # Execute the original unchanged admin/viewer assertions after the failure.
        from test_scheduler_runtime import SchedulerRuntimeTests
        case=SchedulerRuntimeTests('test_admin_toggle_endpoint_returns_factual_state_without_running_job')
        outcome=unittest.TestResult();unittest.TestSuite([case]).run(outcome)
        self.assertEqual(outcome.errors,[]);self.assertEqual(outcome.failures,[])

    def test_production_queue_keeps_worker_when_framework_context_is_supplied(self):
        lock=server.CONTRACT_EXPERIENCE_PENDING_LOCK
        with lock:previous=set(server.CONTRACT_EXPERIENCE_PENDING);server.CONTRACT_EXPERIENCE_PENDING.clear()
        try:
            with patch.object(server,'SANDBOX_MODE',False),patch.object(server.background_jobs,'disabled',return_value=False),patch.object(server.CONTRACT_EXPERIENCE_EXECUTOR,'submit') as submit:
                self.assertEqual(server.enqueue_contract_experience_search(['synthetic','synthetic'],'framework-context'),1)
                submit.assert_called_once_with(server.contract_experience_worker,['synthetic'])
        finally:
            with lock:server.CONTRACT_EXPERIENCE_PENDING.clear();server.CONTRACT_EXPERIENCE_PENDING.update(previous)

if __name__=='__main__':unittest.main()
