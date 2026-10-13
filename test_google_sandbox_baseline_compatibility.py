"""SANDBOX baseline + fourth-job integration; disposable fixtures only."""
import ast, hashlib, json, sqlite3, tempfile, threading, unittest
from unittest.mock import patch
from pathlib import Path
from contextlib import closing
import server
import scheduler_runtime as runtime
import google_writer_execution as writer

BASELINE = '9a253417c270c6b589e7e57940c0d42b7cdc0ced'
EXPECTED = {"_finish_scheduler_lease":"0aeb3eb6c26131fad08e167d601162b178061709d0c29e6a9c226e8a49f254f8","_scheduler_is_configured":"1f7f58ad19eb583234e526cb0b78e435c551573b0decb1487505cfb91dd61b2e","_wait_until":"9ea1abff846b5ccf51cf101558a57a016318bece43ef65de8aa2414d0405431d","scheduler_schedule_model":"fa6961a37df0a716118baeeb43b146f78e261fbd61b63dfc48d81443a93d4105","scheduler_admin_model":"d578e62992ee629540470b1f9b904fe400b0d6324f2125035c8fb373b8cffdb0","scheduler_admin_change":"07ccda5cf56bd75eb8e1e7f5f75a691db7e42b83fa4a3d136978e44a81713980","_trigger_scheduler_job":"58f96fc3b23a2c4105f25403e34e14d6edbd6b91e7e9af33fda9c7ef9ebf8f87","prozorro_scheduler":"fed78476dd6386501e2b80f909d507db1d9d4f2bc7c3b27b241ac24c38a0e17c","violation_reports_scheduler":"3487d3566d38c1afd9cf7b51c330bbf72e5f2c5dd7518426c6b540c6b32a061f","nazk_registry_scheduler":"9dfa4af2772cc5117720a1d2208ab8cf4d2381b3a493f94921c555aaf2f0092e","register_scheduler_job":"7e9351199319f62a13955731ea0abf77a275f6eccfae6baa754d177617554b21","unregister_scheduler_job":"e7cfea099e51c627241b6011c14b5e630d1a988d49500e26214923fd7280a72f","scheduler_environment_defaults":"ef08d3853a9f44af16f454b55c47f5f71c48826d2e54c8b06b36ccd2997d16d1","effective_scheduler_settings":"9b1c1f1c3486bc635ba73e7c9ff4f175e070f9c8d0f8f2b64525cb9a78684f44","apply_scheduler_settings":"f45333d09488d3b50fe1b09348b609dff573941f69d6dc684efaa337481715d8","set_scheduler_job_enabled":"42cbed6fa61b5796444c7354289f0de2ddda515367052bb57114c7d9bcb6c47b","scheduler_status_payload":"d93f14987f3b10e7a0a80c3d0b7ab3c3f23c433af85a288e6ba3121a8a164f4b"}
ROOT = Path(__file__).resolve().parent

class SandboxMirrorBaselineCompatibility(unittest.TestCase):
    def test_manual_thread_start_failure_releases_owned_lease(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db=Path(tmp)/'fixture.sqlite3'
            with closing(sqlite3.connect(db)) as con:
                runtime.migrate(con);con.commit()
            class CannotStart:
                def __init__(self,**kwargs):pass
                def start(self):raise RuntimeError('synthetic start failure')
            with patch.object(server,'DB_PATH',db),patch.object(server,'SANDBOX_MODE',False), \
                 patch.object(server,'SYNC_STATE',{'running':False}), \
                 patch.object(server.threading,'Thread',CannotStart):
                with self.assertRaisesRegex(RuntimeError,'synthetic start failure'):
                    server.start_prozorro_sync(lambda:None,mode='single',message='fixture')
                self.assertFalse(server.SYNC_STATE['running'])
            with closing(sqlite3.connect(db)) as con:
                self.assertEqual(0,con.execute('SELECT COUNT(*) FROM scheduler_job_leases').fetchone()[0])

    def test_manual_running_false_does_not_mean_owner_lease_finished(self):
        for outcome in ('ok','failed','raised'):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                db=Path(tmp)/'fixture.sqlite3'
                with closing(sqlite3.connect(db)) as con:
                    runtime.migrate(con);con.commit()
                waiting,allow_finish,finished=threading.Event(),threading.Event(),threading.Event()
                def target():
                    server.SYNC_STATE.update(running=False,last_result={'status':outcome})
                    if outcome=='raised':raise RuntimeError('synthetic worker failure')
                def finish(job,owner,status='ok',error=''):
                    waiting.set()
                    if not allow_finish.wait(5):raise AssertionError('fixture finish not released')
                    try:runtime.finish(db,job,owner,status=status,error=error)
                    finally:finished.set()
                errors=[]
                real_thread=threading.Thread
                workers=[]
                class Worker:
                    def __init__(self,target,**kwargs):self.target=target
                    def start(self):
                        def run():
                            try:self.target()
                            except RuntimeError as exc:errors.append(str(exc))
                        self.thread=real_thread(target=run)
                        workers.append(self.thread)
                        self.thread.start()
                with patch.object(server,'DB_PATH',db),patch.object(server,'SANDBOX_MODE',False), \
                     patch.object(server,'SYNC_STATE',{'running':False}), \
                     patch.object(server,'_finish_scheduler_lease',finish), \
                     patch.object(server.threading,'Thread',Worker), \
                     patch.object(runtime,'keepalive',lambda *args: __import__('contextlib').nullcontext()):
                    # Worker uses the real Thread captured before the patch.
                    self.assertTrue(server.start_prozorro_sync(target,mode='single',message='fixture'))
                    try:
                        self.assertTrue(waiting.wait(5))
                        self.assertFalse(server.SYNC_STATE['running'])
                        with closing(sqlite3.connect(db)) as con:
                            self.assertEqual(1,con.execute('SELECT COUNT(*) FROM scheduler_job_leases').fetchone()[0])
                        self.assertIsNone(runtime.claim(db,'prozorro',trigger='scheduled'))
                    finally:allow_finish.set()
                    self.assertTrue(finished.wait(5))
                    workers[0].join(5)
                    self.assertFalse(workers[0].is_alive())
                    with closing(sqlite3.connect(db)) as con:
                        self.assertEqual(0,con.execute('SELECT COUNT(*) FROM scheduler_job_leases').fetchone()[0])
                        self.assertEqual('ok' if outcome=='ok' else 'error',con.execute("SELECT last_status FROM scheduler_job_state WHERE job_key='prozorro'").fetchone()[0])
                    self.assertEqual(['synthetic worker failure'] if outcome=='raised' else [],errors)

    def fixture(self, con):
        runtime.migrate(con)
        for job in ('prozorro','nazk_registry'):
            runtime.apply_schedule(con,job,{'enabled':True,'timezone':'Europe/Kyiv','spec':runtime.default_spec(job)},0,'fixture')
        runtime.apply_schedule(con,'violation_reports',{'enabled':True,'timezone':'Europe/Kyiv','spec':{'kind':'hourly','minute':45}},0,'fixture')
        runtime.apply_schedule(con,'violation_reports',{'enabled':True,'timezone':'Europe/Kyiv','spec':{'kind':'hourly','minute':50}},1,'fixture')
        con.commit()

    def snapshot(self, con):
        return (con.execute('SELECT * FROM scheduler_job_settings ORDER BY job_key').fetchall(),
                con.execute('SELECT * FROM scheduler_schedule_audit ORDER BY job_key,revision').fetchall(),
                con.execute('SELECT * FROM scheduler_job_state ORDER BY job_key').fetchall(),
                con.execute('SELECT * FROM scheduler_job_leases ORDER BY job_key').fetchall())

    def test_first_three_scheduler_runtime_and_admin_functions_exact_baseline(self):
        self.assertEqual(hashlib.sha256((ROOT/'scheduler_runtime.py').read_bytes().replace(b'\r\n',b'\n')).hexdigest(),'813f53364896364ac29e731c8631d3eb495995804da0fe8fce547a872d62e914')
        tree=ast.parse((ROOT/'server.py').read_text(encoding='utf-8-sig'))
        functions={n.name:n for n in tree.body if isinstance(n,ast.FunctionDef)}
        for name,digest in EXPECTED.items():
            with self.subTest(function=name):
                self.assertEqual(hashlib.sha256(ast.dump(functions[name],include_attributes=False).encode()).hexdigest(),digest)
        self.assertEqual(set(server.SCHEDULER_TARGETS),{'prozorro','violation_reports','nazk_registry'})

    def test_existing_scheduler_admin_ui_exact_baseline_with_fourth_separate_card(self):
        app=(ROOT/'app.js').read_text(encoding='utf-8-sig')
        section=app[app.index('let schedulerEditorsGeneration=0;'):app.index('async function loadRuntimeFeatures(){')]
        self.assertEqual(hashlib.sha256(section.encode()).hexdigest(),'5a00d0a8928125ebf9368004aedaf4c8f07ce0ee96cbd24eb501dd768e71ae67')
        self.assertIn('await loadSchedulerEditors();',app)
        self.assertIn('await loadGoogleWriterJob();',app)
        self.assertIn('googleWriterJobCard',(ROOT/'google_writer_ui.js').read_text(encoding='utf-8'))

    def test_fourth_migration_preserves_revision_2_50_and_all_existing_settings_audit_leases(self):
        with closing(sqlite3.connect(':memory:')) as con:
            self.fixture(con);before=self.snapshot(con)
            writer.migrate(con);writer.migrate(con)
            self.assertEqual(self.snapshot(con),before)
            model=runtime.schedule_model(con,'violation_reports')
            self.assertEqual((model['revision'],model['spec']['minute'],model['enabled']),(2,50,True))
            self.assertEqual(writer.settings(con),{'enabled':0,'hour':7,'minute':0,'revision':0})

    def test_fourth_schedule_change_does_not_change_first_three_or_launch_any_job(self):
        with closing(sqlite3.connect(':memory:')) as con:
            self.fixture(con);writer.migrate(con);before=self.snapshot(con)
            preview=writer.preview_settings(con,{'enabled':False,'hour':8,'minute':30})
            self.assertFalse(preview['after']['enabled'])
            writer.save_settings(con,{'enabled':False,'hour':8,'minute':30},0,'fixture')
            self.assertEqual(self.snapshot(con),before)
            self.assertEqual(writer.settings(con),{'enabled':0,'hour':8,'minute':30,'revision':1})
            self.assertEqual(con.execute('SELECT COUNT(*) FROM google_writer_runs').fetchone()[0],0)

    def test_fourth_readonly_preview_preserves_revision_2_and_no_sql_writes(self):
        with closing(sqlite3.connect(':memory:')) as con:
            self.fixture(con);writer.migrate(con);before=self.snapshot(con)
            con.execute('PRAGMA query_only=ON');changes=con.total_changes
            writer.preview_settings(con,{'enabled':False,'hour':7,'minute':0})
            runtime.preview_schedule(con,'violation_reports',{'enabled':True,'timezone':'Europe/Kyiv','spec':{'kind':'hourly','minute':50}})
            self.assertEqual(con.total_changes,changes)
            self.assertEqual(self.snapshot(con),before)

    def test_first_three_stale_revision_claim_guard_survives_fourth_run_lane(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'fixture.sqlite3'
            with closing(sqlite3.connect(db)) as con:
                self.fixture(con);writer.migrate(con)
            claim=writer.claim_run(db,'SANDBOX','a'*32,'fixture','manual')
            self.assertTrue(claim['claimed'])
            self.assertIsNone(runtime.claim(db,'violation_reports',trigger='scheduled',expected_revision=1))
            owner=runtime.claim(db,'violation_reports',trigger='scheduled',expected_revision=2)
            self.assertTrue(owner)
            runtime.release(db,'violation_reports',owner)
            with closing(sqlite3.connect(db)) as con:
                self.assertEqual(runtime.schedule_model(con,'violation_reports')['revision'],2)
                self.assertEqual(writer.settings(con)['enabled'],0)

if __name__=='__main__': unittest.main()
