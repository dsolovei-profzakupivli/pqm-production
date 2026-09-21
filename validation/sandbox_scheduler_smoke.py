"""Sandbox-only automatic Prozorro: opt-in, durable lease and restart smoke."""
import datetime,json,os,sqlite3,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import sandbox_smoke as base
import scheduler_runtime
sandbox=base.sandbox
UTC=datetime.timezone.utc

class SchedulerPolicy(unittest.TestCase):
    def test_explicit_flag_and_target(self):
        env=base.PolicyTests().env()
        for value in ['yes','true','invalid']:
            with self.assertRaises(RuntimeError):sandbox.validate_environment({**env,'PQM_SANDBOX_PROZORRO_SCHEDULER':value})
        env['PQM_SANDBOX_PROZORRO_SCHEDULER']='1'
        with self.assertRaises(RuntimeError):sandbox.validate_environment(env)
        env['PQM_SANDBOX_PROZORRO_READ']='1'
        with self.assertRaises(RuntimeError):sandbox.validate_environment(env)
        env['RENDER_SERVICE_ID']='srv-dalfd77f3r2c7392uub0'
        sandbox.validate_environment(env)
        with patch.dict(os.environ,env):self.assertTrue(sandbox.prozorro_scheduler_enabled())
        for change in [{'PQM_SANDBOX':'0'},{'PQM_SANDBOX_PROZORRO_READ':'0'},{'PQM_SANDBOX_PROZORRO_SCHEDULER':'0'}]:
            with patch.dict(os.environ,{**env,**change}):self.assertFalse(sandbox.prozorro_scheduler_enabled())

    def test_durable_catchup_and_180s_lease(self):
        now=datetime.datetime(2026,9,17,0,0,tzinfo=UTC)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'fixture.sqlite3'
            with sqlite3.connect(path) as con:scheduler_runtime.migrate(con)
            self.assertEqual(0,sandbox.prozorro_catchup_delay(path,now))
            with sqlite3.connect(path) as con:
                con.execute("UPDATE scheduler_job_state SET last_status='ok',last_trigger='manual',last_finished_at=? WHERE job_key='prozorro'",(now.isoformat(),))
            self.assertEqual(0,sandbox.prozorro_catchup_delay(path,now),'single manual import cannot mask missing automatic run')
            with sqlite3.connect(path) as con:con.execute("UPDATE scheduler_job_state SET last_trigger='scheduled' WHERE job_key='prozorro'")
            self.assertIsNone(sandbox.prozorro_catchup_delay(path,now))
            self.assertEqual(0,sandbox.prozorro_catchup_delay(path,now+datetime.timedelta(hours=1)))
            with sqlite3.connect(path) as con:
                con.execute("UPDATE scheduler_job_state SET last_status='running' WHERE job_key='prozorro'")
                con.execute("INSERT INTO scheduler_job_leases VALUES ('prozorro','old',?,?)",(now.isoformat(),(now+datetime.timedelta(seconds=180)).isoformat()))
            for seconds,expected in [(0,30),(150,30),(179,1),(180,0),(181,0)]:
                self.assertEqual(expected,sandbox.prozorro_catchup_delay(path,now+datetime.timedelta(seconds=seconds)))
            with sqlite3.connect(path) as con:
                self.assertEqual(('running',),con.execute("SELECT last_status FROM scheduler_job_state WHERE job_key='prozorro'").fetchone())
                self.assertEqual(('old',),con.execute('SELECT owner_id FROM scheduler_job_leases').fetchone(),'decision must never steal/write lease')

class AutomaticHTTP(unittest.TestCase):
    EDIT_MODE='1'
    EXTRA_ENV={'PQM_SANDBOX_PROZORRO_READ':'1','PQM_SANDBOX_PROZORRO_SCHEDULER':'1'}
    RUNNER='validation/sandbox_prozorro_fixture.py'
    setUpClass=base.SandboxHTTP.__dict__['setUpClass']
    tearDownClass=base.SandboxHTTP.__dict__['tearDownClass']
    start=base.SandboxHTTP.__dict__['start']
    stop=base.SandboxHTTP.__dict__['stop']
    request=base.SandboxHTTP.__dict__['request']

    def job(self):
        return next(j for j in self.request('/api/runtime-features')[1]['scheduler_jobs'] if j['job']=='prozorro')

    def wait_job(self,trigger,after=None):
        deadline=time.monotonic()+50
        while time.monotonic()<deadline:
            job=self.job()
            if job['last_status']=='ok' and job['last_trigger']==trigger and job['last_started_at']!=after:
                return job
            time.sleep(.2)
        self.fail('automatic job did not finish: '+json.dumps(job))

    def test_automatic_start_schedule_restart_and_orphan_recovery(self):
        flags=self.request('/api/runtime-features')[1]
        self.assertTrue(flags['safe_mode']);self.assertTrue(flags['sandbox_prozorro_scheduler'])
        for job in flags['scheduler_jobs']:
            self.assertEqual(job['job']=='prozorro',job['enabled'])
            self.assertEqual(job['job']=='prozorro',job['running'])
        for key in ['google','bids_update','powerbi','nazk_scheduler']:self.assertFalse(flags[key],key)
        for path in ['/api/amcu-registry/refresh','/api/nazk-registry/refresh','/api/operational-tasks/rebuild',
                     '/api/violation-reports/sync','/api/admin/scheduler-jobs/violation_reports']:
            self.assertEqual(503,self.request(path,'admin','POST',{'enabled':True})[0],path)
        first=self.wait_job('startup_catchup')
        self.assertTrue(first['next_run']);self.assertTrue(first['heartbeat_at'])
        self.assertEqual('Europe/Kyiv',first['timezone'])
        self.stop();self.start()
        time.sleep(12)
        self.assertEqual(first['last_started_at'],self.job()['last_started_at'],'restart must not duplicate fresh successful run')
        scheduled=self.wait_job('scheduled',first['last_started_at'])
        self.stop()
        expired=(datetime.datetime.now(UTC)-datetime.timedelta(seconds=1)).isoformat()
        with sqlite3.connect(self.data/'pqm_sandbox.sqlite3') as con:
            con.execute("UPDATE scheduler_job_state SET last_status='running' WHERE job_key='prozorro'")
            con.execute("INSERT INTO scheduler_job_leases VALUES ('prozorro','synthetic-crashed-owner',?,?)",(expired,expired))
        self.start()
        recovered=self.wait_job('startup_catchup',scheduled['last_started_at'])
        self.assertTrue(recovered['running'])
        with sqlite3.connect(self.data/'pqm_sandbox.sqlite3') as con:
            for table in ['supplier_nazk_checks','supplier_nazk_reviews','operational_tasks','amcu_registry','nazk_registry','scheduler_job_leases']:
                self.assertEqual(0,con.execute('SELECT COUNT(*) FROM '+table).fetchone()[0],table)
            self.assertEqual(0,con.execute("SELECT COUNT(*) FROM scheduler_job_state WHERE job_key<>'prozorro' AND last_status<>'never'").fetchone()[0])
            self.assertEqual(0,con.execute('SELECT COUNT(*) FROM scheduler_job_settings WHERE enabled<>0').fetchone()[0])
            self.assertEqual('ok',con.execute('PRAGMA integrity_check').fetchone()[0])
            self.assertEqual([],con.execute('PRAGMA foreign_key_check').fetchall())
        self.assertIn('автоматично щогодини о :05',self.request('/',None)[1].decode())

if __name__=='__main__':unittest.main(verbosity=2)
