"""Offline execution-interlock regressions; only synthetic SQLite is used."""
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import unittest
from unittest.mock import Mock, patch

import background_jobs
import google_writer_execution as writer
import reference_directories
import scheduler_runtime
import sandbox_runtime
import server


class BackgroundJobsKillSwitchTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ, {'PQM_DISABLE_BACKGROUND_JOBS':'1','PQM_SANDBOX':'1'})
        self.env.start();self.addCleanup(self.env.stop)
        self.con=sqlite3.connect(':memory:')
        self.addCleanup(self.con.close)
        scheduler_runtime.migrate(self.con)
        for key in scheduler_runtime.SCHEDULES:
            self.con.execute("INSERT INTO scheduler_job_settings(job_key,enabled,updated_at,updated_by,revision,schedule_json,timezone) VALUES(?,1,'fixture','admin',2,?, 'Europe/Kyiv')",
                             (key,'{"kind":"hourly","minute":50}'))
        self.con.commit()

    def snapshot(self):
        return self.con.execute('SELECT * FROM scheduler_job_settings ORDER BY job_key').fetchall()

    def test_persisted_enabled_cannot_override_switch_or_write_settings(self):
        before=self.snapshot();changes=self.con.total_changes
        self.con.execute('PRAGMA query_only=ON')
        with patch.object(server,'SANDBOX_MODE',True),patch.object(server,'db',side_effect=AssertionError('No DB needed')):
            enabled,sources=server.effective_scheduler_settings()
        self.assertEqual(enabled,dict.fromkeys(scheduler_runtime.SCHEDULES,False))
        self.assertEqual(set(sources.values()),{'background_jobs_disabled'})
        self.assertEqual(self.snapshot(),before)
        self.assertEqual(self.con.total_changes,changes)

    def test_startup_catchup_never_registers_enabled_jobs(self):
        with patch.object(server,'register_scheduler_job') as register,patch.object(server,'unregister_scheduler_job') as unregister:
            self.assertFalse(any(server.apply_scheduler_settings(catch_up=True).values()))
            register.assert_not_called()
            self.assertEqual(unregister.call_count,3)

    def test_direct_scheduler_registration_cannot_start_thread(self):
        with patch.object(server.threading,'Thread') as thread:
            for key in scheduler_runtime.SCHEDULES:
                self.assertFalse(server.register_scheduler_job(key,Mock(),catch_up=True))
            thread.assert_not_called()

    def test_direct_scheduler_loops_cannot_catch_up(self):
        with patch.object(server,'db',side_effect=AssertionError('No DB')),patch.object(server,'_trigger_scheduler_job') as trigger,patch.object(server,'start_nazk_registry_refresh') as nazk:
            for target in server.SCHEDULER_TARGETS.values():
                target(threading.Event(),catch_up=True)
            trigger.assert_not_called();nazk.assert_not_called()

    def test_scheduled_and_catchup_dispatch_are_blocked(self):
        with patch.object(server,'start_prozorro_sync') as prozorro,patch.object(server,'start_violation_reports_sync') as requests:
            for key in ('prozorro','violation_reports'):
                for reason in ('scheduled','startup_catchup'):
                    self.assertFalse(server._trigger_scheduler_job(key,reason))
            prozorro.assert_not_called();requests.assert_not_called()

    def test_jobs_1_to_3_entrypoints_block_before_claim(self):
        with patch.object(scheduler_runtime,'claim',side_effect=AssertionError('No claim')):
            for reason in ('scheduled','startup_catchup','scheduled_catchup','manual'):
                self.assertFalse(server.start_prozorro_sync(Mock(),mode='incremental',message='',trigger=reason))
                self.assertFalse(server.start_violation_reports_sync(trigger=reason))
                self.assertFalse(server.start_nazk_registry_refresh(trigger=reason))

    def test_lease_primitive_blocked_before_opening_database(self):
        with patch.object(scheduler_runtime.sqlite3,'connect',side_effect=AssertionError('No DB')):
            for key in scheduler_runtime.SCHEDULES:
                self.assertIsNone(scheduler_runtime.claim('unused',key,trigger='scheduled'))

    def test_google_scheduler_cannot_start_or_claim(self):
        service=writer.Scheduler('unused','sandbox',Mock(),lambda:True)
        with patch.object(writer.sqlite3,'connect',side_effect=AssertionError('No DB')),patch.object(writer.threading,'Thread') as thread:
            self.assertFalse(service.start());self.assertFalse(service.reschedule())
            service.loop()
            self.assertFalse(writer.claim_run('unused','sandbox','a'*32,'scheduler','scheduled')['claimed'])
            thread.assert_not_called()

    def test_google_execution_blocked_without_network_or_database(self):
        client=Mock()
        with patch.object(writer,'finish_run',side_effect=AssertionError('No DB')):
            self.assertEqual(writer.execute_claimed('unused',client,'a'*32,'scheduler',trigger='scheduled'),{'status':'BACKGROUND_JOBS_DISABLED'})
        client.invoke.assert_not_called()
        with patch.object(server,'google_writer_client',side_effect=AssertionError('No credentials')):
            self.assertFalse(server.google_writer_available())

    def test_waiting_scheduler_stops_before_next_automatic_run(self):
        self.assertTrue(server._wait_until(datetime.now(timezone.utc)+timedelta(hours=1),threading.Event(),'prozorro'))
        self.assertFalse(server._scheduler_is_configured('prozorro'))

    def test_reference_refresh_blocked_before_timer_db_or_identity_write(self):
        with patch.object(reference_directories,'reference_status',side_effect=AssertionError('No DB')),patch.object(reference_directories.threading,'Timer') as timer:
            for source in ('amcu','nazk'):
                self.assertFalse(reference_directories.start_reference_refresh('unused',source))
            self.assertFalse(reference_directories._start_amcu_refresh('unused',None,''))
            self.assertFalse(server.start_amcu_registry_refresh())
            timer.assert_not_called()

    def test_automatic_cache_retry_and_export_are_blocked(self):
        with patch.object(server.threading,'Thread') as thread,patch.object(server.threading,'Timer') as timer,patch.object(server.CONTRACT_EXPERIENCE_EXECUTOR,'submit') as submit:
            server.bids_sync_status(force=True)
            self.assertFalse(server._schedule_contract_experience_retry('synthetic'))
            self.assertEqual(server.enqueue_contract_experience_search(['synthetic']),0)
            self.assertEqual(server.start_powerbi_export()[1],503)
            thread.assert_not_called();timer.assert_not_called();submit.assert_not_called()

    def test_repeated_main_does_not_launch_background_or_rebuild(self):
        before=self.snapshot()
        with ExitStack() as stack:
            for name in ('init_db','init_reference_tables','restore_sync_data_timestamp'):
                stack.enter_context(patch.object(server,name))
            stack.enter_context(patch.object(server,'DB_PATH',Path(__file__)))
            stack.enter_context(patch.object(server,'db',return_value=self.con))
            stack.enter_context(patch.object(scheduler_runtime,'migrate'))
            stack.enter_context(patch.object(server,'ENABLE_BROWSER',False))
            stack.enter_context(patch.object(server,'SANDBOX_MODE',True))
            stack.enter_context(patch.object(server,'sandbox_runtime',sandbox_runtime,create=True))
            stack.enter_context(patch.object(server,'google_effective_enabled',return_value=False))
            stack.enter_context(patch.object(server,'ExclusiveThreadingHTTPServer'))
            stack.enter_context(patch.object(server,'unregister_scheduler_job'))
            register=stack.enter_context(patch.object(server,'register_scheduler_job'))
            google=stack.enter_context(patch.object(server,'google_writer_service'))
            rebuild=stack.enter_context(patch.object(server,'rebuild_operational_tasks'))
            server.main();server.main()
            register.assert_not_called();google.assert_not_called();rebuild.assert_not_called()
        self.assertEqual(self.snapshot(),before)

    def test_unset_switch_preserves_prod_persisted_enabled_behavior(self):
        with patch.dict(os.environ,{'PQM_DISABLE_BACKGROUND_JOBS':''}),patch.object(server,'SANDBOX_MODE',False),patch.object(server,'SAFE_MODE',False),patch.object(server,'db',return_value=self.con):
            enabled,_=server.effective_scheduler_settings()
            self.assertTrue(all(enabled.values()))
            with patch.object(server,'register_scheduler_job') as register:
                server.apply_scheduler_settings(catch_up=True)
                self.assertEqual(register.call_count,3)
                for call in register.call_args_list:self.assertTrue(call.kwargs['catch_up'])

    def test_unset_switch_preserves_sandbox_persisted_enabled_behavior(self):
        with patch.dict(os.environ,{'PQM_DISABLE_BACKGROUND_JOBS':''}),patch.object(server,'SANDBOX_MODE',True),patch.object(server,'sandbox_runtime',sandbox_runtime,create=True),patch.object(server,'db',return_value=self.con):
            self.assertTrue(all(server.effective_scheduler_settings()[0].values()))

    def test_disabled_values_and_explicit_enabled_values(self):
        for value in ('','0','false'):
            with patch.dict(os.environ,{'PQM_DISABLE_BACKGROUND_JOBS':value}):self.assertFalse(background_jobs.disabled())
        for value in ('1','true','yes','on'):
            with patch.dict(os.environ,{'PQM_DISABLE_BACKGROUND_JOBS':value}):self.assertTrue(background_jobs.disabled())

    def test_persistent_configuration_survives_fresh_process_restarts(self):
        for _ in range(2):
            result=subprocess.run([sys.executable,'-B','-c',
                'import background_jobs; assert background_jobs.disabled()'],
                env={**os.environ,'PQM_DISABLE_BACKGROUND_JOBS':'1'},capture_output=True,timeout=10)
            self.assertEqual(result.returncode,0)

    def test_explicit_off_allows_isolated_scheduler_test_without_code_bypass(self):
        with patch.dict(os.environ,{'PQM_DISABLE_BACKGROUND_JOBS':'0'}),patch.object(server,'SANDBOX_MODE',True),patch.object(server,'sandbox_runtime',sandbox_runtime,create=True),patch.object(server,'db',return_value=self.con),patch.object(server,'register_scheduler_job') as register:
            self.assertTrue(all(server.apply_scheduler_settings(catch_up=False).values()))
            self.assertEqual(register.call_count,3)
            for call in register.call_args_list:self.assertFalse(call.kwargs['catch_up'])


if __name__=='__main__':unittest.main()
