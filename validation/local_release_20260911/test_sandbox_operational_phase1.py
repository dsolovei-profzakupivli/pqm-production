"""Phase-1 SANDBOX destination isolation and local task-chain regressions."""
import os
import contextlib
import gc
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import operational_tasks
import reference_directories as ref
import sandbox_runtime
import server
try:
    from test_nazk_task_relevance import NazkTaskPersonRelevanceTests
except ImportError:
    from validation.local_release_20260911.test_nazk_task_relevance import NazkTaskPersonRelevanceTests


class SandboxOperationalBoundaryTests(unittest.TestCase):
    def test_upload_rejects_wrong_db_before_state_or_parser(self):
        with patch.dict(os.environ, {'PQM_SANDBOX': '1', 'PQM_SANDBOX_OPERATIONAL': '1',
                                     'PQM_SANDBOX_AMCU_READ': '1'}), \
             patch.object(sandbox_runtime, 'attest_internal_target', side_effect=RuntimeError('wrong DB')), \
             patch.object(ref, '_state') as state, patch.object(ref, '_amcu_rows_bounded') as parser:
            with self.assertRaisesRegex(RuntimeError, 'wrong DB'):
                ref.start_reference_refresh('wrong.sqlite3', 'amcu', b'xlsx', 'official.xlsx')
            state.assert_not_called()
            parser.assert_not_called()

    def test_excel_failure_does_not_replace_registry_or_rebuild_tasks(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'sandbox.sqlite3'
            with contextlib.closing(sqlite3.connect(path)) as con:
                con.execute('CREATE TABLE reference_sync_state(source TEXT PRIMARY KEY,status TEXT,message TEXT,row_count INTEGER,updated_at TEXT,source_updated_at TEXT)')
                con.execute("INSERT INTO reference_sync_state(source,status) VALUES('amcu','idle')")
                con.execute('CREATE TABLE amcu_registry(row_key TEXT PRIMARY KEY,ordinal TEXT,division_no TEXT,sequence_no TEXT,decision_no TEXT,decision_date TEXT,authority TEXT,offender_name TEXT,offender_code TEXT,court_case_no TEXT,raw_json TEXT)')
                con.execute("INSERT INTO amcu_registry(row_key,decision_date) VALUES('old','2026-09-18')")
                con.commit()
            with patch.object(ref, '_amcu_rows_bounded', side_effect=ValueError('invalid Excel')):
                rebuilt = []
                ref.refresh_amcu(path, b'bad', 'official.xlsx', on_complete=lambda: rebuilt.append(True))
            with contextlib.closing(sqlite3.connect(path)) as con:
                self.assertEqual(con.execute('SELECT row_key FROM amcu_registry').fetchone()[0], 'old')
            self.assertEqual(rebuilt, [])
            gc.collect()

    def test_excel_commit_precedes_task_rebuild_and_repeat_is_stable(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'sandbox.sqlite3'
            with contextlib.closing(sqlite3.connect(path)) as con:
                con.execute('CREATE TABLE reference_sync_state(source TEXT PRIMARY KEY,status TEXT,message TEXT,row_count INTEGER,updated_at TEXT,source_updated_at TEXT)')
                con.execute("INSERT INTO reference_sync_state(source,status) VALUES('amcu','idle')")
                con.execute('CREATE TABLE amcu_registry(row_key TEXT PRIMARY KEY,ordinal TEXT,division_no TEXT,sequence_no TEXT,decision_no TEXT,decision_date TEXT,authority TEXT,offender_name TEXT,offender_code TEXT,court_case_no TEXT,raw_json TEXT)')
                con.commit()
            row = ('new', '1', '', '', '42', '2026-09-24', 'АМКУ', 'Fixture', '12345678', '', '{}')
            observed = []
            def rebuild():
                with contextlib.closing(sqlite3.connect(path)) as con:
                    observed.append((con.execute('SELECT row_key FROM amcu_registry').fetchone()[0],
                                     not con.in_transaction))
            with patch.object(ref, '_amcu_rows_bounded', return_value=('official.xlsx', [row])):
                ref.refresh_amcu(path, b'xlsx', 'official.xlsx', on_complete=rebuild)
                ref.refresh_amcu(path, b'xlsx', 'official.xlsx', on_complete=rebuild)
            self.assertEqual(observed, [('new', True), ('new', True)])
            with contextlib.closing(sqlite3.connect(path)) as con:
                self.assertEqual(con.execute('SELECT COUNT(*) FROM amcu_registry').fetchone()[0], 1)
            gc.collect()

    def test_opt_in_requires_approved_sandbox_service_and_owned_target(self):
        env = {**sandbox_runtime.POLICY, 'PQM_DATA_DIR': '/var/data',
               'PQM_DB_PATH': '/var/data/pqm_sandbox.sqlite3',
               'RENDER_SERVICE_ID': 'srv-dalfd77f3r2c7392uub0',
               'RENDER_SERVICE_NAME': 'pqm-sandbox',
               'PQM_SANDBOX_OPERATIONAL': '1'}
        sandbox_runtime.validate_environment(env)
        with self.assertRaises(RuntimeError):
            sandbox_runtime.validate_environment({**env, 'RENDER_SERVICE_NAME': 'pqm-production-1'})
        with self.assertRaises(RuntimeError):
            sandbox_runtime.validate_environment({**env, 'PQM_DB_PATH': '/var/data/pqm_prod.sqlite3'})
        with self.assertRaises(RuntimeError):
            sandbox_runtime.validate_environment({**env, 'PQM_SANDBOX_OPERATIONAL': '0',
                                                  'PQM_SANDBOX_NAZK_READ': '1'})

    def test_shared_server_amcu_refresh_binds_task_completion_in_every_environment(self):
        observed = {}
        def start(path, source, raw, filename, on_complete):
            observed.update(source=source, raw=raw, filename=filename)
            on_complete()
            return True
        with patch.object(server, 'start_reference_refresh', side_effect=start), \
             patch.object(server, 'rebuild_operational_tasks', return_value={'amcu': 1}) as build:
            self.assertTrue(server.start_amcu_registry_refresh(b'xlsx', 'official.xlsx'))
        self.assertEqual(observed, {'source': 'amcu', 'raw': b'xlsx', 'filename': 'official.xlsx'})
        build.assert_called_once_with('PQM AMCU refresh')

    def test_operational_routes_are_explicit_and_do_not_include_documents_or_prod(self):
        with patch.dict(os.environ, {'PQM_SANDBOX': '1', 'PQM_SANDBOX_OPERATIONAL': '1'}):
            self.assertTrue(sandbox_runtime.operational_route_allowed('POST', '/api/operational-tasks/rebuild'))
            self.assertTrue(sandbox_runtime.operational_route_allowed('POST', '/api/violation-reports/sync'))
            self.assertTrue(sandbox_runtime.operational_route_allowed('PATCH', '/api/operational-tasks/' + 'a' * 32))
            self.assertFalse(sandbox_runtime.operational_route_allowed('POST', '/api/operational-tasks/' + 'a' * 32 + '/documents/amcu-exclusion-protocol'))
            self.assertFalse(sandbox_runtime.operational_route_allowed('POST', '/api/admin/runtime-features/google'))
            self.assertFalse(sandbox_runtime.operational_route_allowed('POST', '/api/nazk-registry/refresh'))
        with patch.dict(os.environ, {'PQM_SANDBOX': '1', 'PQM_SANDBOX_OPERATIONAL': '0'}):
            self.assertFalse(sandbox_runtime.operational_route_allowed('POST', '/api/operational-tasks/rebuild'))

    def test_prod_db_or_link_cannot_be_used_as_internal_target(self):
        with TemporaryDirectory() as folder, patch.dict(os.environ, {'PQM_SANDBOX': '1', 'PQM_SANDBOX_OPERATIONAL': '1'}):
            data = Path(folder)
            owned = data / 'pqm_sandbox.sqlite3'
            owned.touch()
            prod = data / 'prod.sqlite3'
            prod.touch()
            with patch.object(sandbox_runtime, 'validate_environment', return_value=(data, owned, 'fixture')):
                with patch.object(sandbox_runtime, '_verify_existing') as verify:
                    self.assertEqual(sandbox_runtime.attest_internal_target(owned), owned)
                    verify.assert_called_once_with(owned, 'fixture')
                    with self.assertRaisesRegex(RuntimeError, 'non-SANDBOX'):
                        sandbox_runtime.attest_internal_target(prod)

    def test_public_read_destinations_are_integration_specific(self):
        with patch.dict(os.environ, {'PQM_SANDBOX': '1', 'PQM_SANDBOX_OPERATIONAL': '1',
                                     'PQM_SANDBOX_NAZK_READ': '1'}):
            self.assertEqual(sandbox_runtime.validate_nazk_request(
                'https://corruptinfo.nazk.gov.ua/ep/1.0/corrupt/getAllData', 'GET'),
                sandbox_runtime.NAZK_HOST)
            for url, method in [
                ('https://pqm-production-1.onrender.com/api/sync', 'GET'),
                ('https://corruptinfo.nazk.gov.ua/ep/1.0/corrupt/getAllData', 'POST'),
                ('https://corruptinfo.nazk.gov.ua/ep/1.0/corrupt/getAllData?write=1', 'GET'),
            ]:
                with self.subTest(url=url), self.assertRaises(RuntimeError):
                    sandbox_runtime.validate_nazk_request(url, method)
        with patch.dict(os.environ, {'PQM_SANDBOX': '1', 'PQM_SANDBOX_PROZORRO_READ': '1'}):
            sandbox_runtime.validate_prozorro_url(
                'https://public-api.prozorro.gov.ua/api/2.5/violation_reports/abc')
            with self.assertRaises(RuntimeError):
                sandbox_runtime.validate_prozorro_url('https://pqm-production-1.onrender.com/api/violation_reports')

    def test_amcu_worker_late_prod_target_drift_releases_lock_without_db_write(self):
        with patch.dict(os.environ, {'PQM_SANDBOX': '1', 'PQM_SANDBOX_OPERATIONAL': '1'}), \
             patch.object(sandbox_runtime, 'attest_internal_target', side_effect=RuntimeError('PROD target')), \
             patch.object(ref, '_state') as state:
            ref.refresh_amcu('fixture')
            state.assert_not_called()
            self.assertFalse(ref.AMCU_LOCK.locked())


class SandboxOperationalTaskChainTests(unittest.TestCase):
    def setUp(self):
        self.fixture = NazkTaskPersonRelevanceTests('test_current_manager_match_creates_one_task_idempotently')
        self.fixture.setUp()
        self.con = self.fixture.con
        for column in ('decision_no', 'authority', 'court_case_no', 'offender_name'):
            self.con.execute(f'ALTER TABLE amcu_registry ADD COLUMN {column} TEXT DEFAULT \'\'')

    def tearDown(self):
        self.con.close()

    def test_amcu_read_state_predicate_task_registry_and_card(self):
        self.con.execute("INSERT INTO amcu_registry(row_key,offender_code,decision_date,decision_no) VALUES('A1',?,'2026-09-20','42')", (self.fixture.CODE,))
        first = operational_tasks.build(self.con, 'SANDBOX AMCU refresh', include_nazk=False)
        second = operational_tasks.build(self.con, 'SANDBOX repeat', include_nazk=False)
        self.assertEqual(first['amcu'], 1)
        self.assertEqual(second['created'], 0)
        row = self.con.execute("SELECT id FROM operational_tasks WHERE task_type='amcu_exclusion'").fetchone()
        self.assertIsNotNone(row)
        card = operational_tasks.detail(self.con, row['id'])
        self.assertEqual(card['supplier_code'], self.fixture.CODE)
        self.assertEqual(card['task_type'], 'amcu_exclusion')
        self.assertEqual(len(card['amcu_decisions']), 1)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM operational_task_events WHERE task_id=?', (row['id'],)).fetchone()[0] >= 1, True)

    def test_pending_application_without_active_qualification_never_creates_amcu_task(self):
        self.con.execute("UPDATE registry_contracts SET status='inactive' WHERE id='RC'")
        self.con.execute("INSERT INTO submissions VALUES('P','F','Pending supplier',?,'2026-09-25','pending')", (self.fixture.CODE,))
        self.con.execute("INSERT INTO amcu_registry(row_key,offender_code,decision_date,decision_no) VALUES('A1',?,'2026-09-20','42')", (self.fixture.CODE,))
        self.assertEqual(operational_tasks.build(self.con, 'pending', include_nazk=False)['amcu'], 0)
        self.assertEqual(operational_tasks.build(self.con, 'pending repeat', include_nazk=False)['amcu'], 0)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM operational_tasks WHERE task_type='amcu_exclusion'").fetchone()[0], 0)

    def test_historical_excluded_amcu_population_does_not_flood_tasks(self):
        self.con.execute("UPDATE registry_contracts SET status='inactive' WHERE id='RC'")
        for index in range(20):
            self.con.execute("INSERT INTO amcu_registry(row_key,offender_code,decision_date,decision_no) VALUES(?,?,?,?)",
                             (f'A{index}', str(10000000 + index), '2026-09-20', str(index)))
        self.con.execute("INSERT INTO amcu_registry(row_key,offender_code,decision_date,decision_no) VALUES('A-current',?,'2026-09-20','42')", (self.fixture.CODE,))
        self.assertEqual(operational_tasks.build(self.con, 'historical', include_nazk=False)['amcu'], 0)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM operational_tasks WHERE task_type='amcu_exclusion'").fetchone()[0], 0)

    def test_direct_application_api_rejects_amcu_admit_without_business_write(self):
        self.con.execute("INSERT INTO amcu_registry(row_key,offender_code,decision_date,decision_no) VALUES('A1',?,'2026-09-20','42')", (self.fixture.CODE,))
        self.con.execute("ALTER TABLE submissions ADD COLUMN qualification_id TEXT DEFAULT ''")
        self.con.execute("UPDATE submissions SET qualification_id='Q' WHERE id='S'")
        self.con.execute('''CREATE TABLE application_fields (
          submission_id TEXT PRIMARY KEY,protocol_decision TEXT DEFAULT '',compliance_status TEXT DEFAULT '',
          marketplace_decision TEXT DEFAULT '',protocol_number TEXT DEFAULT '',protocol_date TEXT DEFAULT '',
          manager_name TEXT DEFAULT '',compliance_comments TEXT DEFAULT '',generated_protocol_number TEXT DEFAULT '',
          generated_protocol_date TEXT DEFAULT '',generated_protocol_decision TEXT DEFAULT '',
          protocol_generated_at TEXT DEFAULT '',protocol_remarks TEXT DEFAULT '')''')
        self.con.execute("INSERT INTO application_fields(submission_id) VALUES('S')")
        self.con.commit()
        class Request:
            path = '/api/applications/S'
            auth_role = 'admin'
            auth_user = 'fixture'
            payload = {}
            def read_json(self): return dict(self.payload)
            def send_json(self, body, status=200):
                self.response = (status, body)
                return self.response
        request = Request()
        before = self.con.total_changes
        with patch.object(server, 'db', return_value=contextlib.nullcontext(self.con)), \
             patch.object(server.historical_applications, 'assert_editable'), \
             patch.object(server.formed_protocols, 'guard_edit'):
            for field in ('protocol_decision', 'marketplace_decision'):
                request.payload = {field: 'admit'}
                server.Handler._do_PATCH(request)
                self.assertEqual(request.response[0], 409)
                self.assertIn('АМКУ', request.response[1]['error'])
                self.con.rollback()
        self.assertEqual(self.con.total_changes, before)
        self.assertFalse(server.amcu_blocks_submission(self.con, 'missing'))
        self.con.execute("DELETE FROM amcu_registry WHERE row_key='A1'")
        self.assertFalse(server.amcu_blocks_submission(self.con, 'S'))

    def test_warning_appeal_source_creates_local_task(self):
        for number, day in enumerate(('2026-09-01', '2026-09-10', '2026-09-20'), 1):
            self.con.execute('INSERT INTO violation_reports VALUES(?,?,?,?,?,?,?,?,?)',
                             (str(number), f'UA-D-{number}', 'satisfied', day, self.fixture.CODE,
                              day, 'UA-TEST', 'SANDBOX CUSTOMER', ''))
        counts = operational_tasks.build(self.con, 'SANDBOX violation refresh', include_nazk=False)
        self.assertEqual(counts['warning'], 1)
        row = self.con.execute("SELECT id FROM operational_tasks WHERE task_type='warning_block'").fetchone()
        self.assertEqual(operational_tasks.detail(self.con, row['id'])['task_type'], 'warning_block')

    def test_completed_amcu_evidence_stays_covered_until_new_decision_cycle(self):
        self.con.execute("INSERT INTO amcu_registry(row_key,offender_code,decision_date,decision_no) VALUES('A1',?,'2026-09-20','42')", (self.fixture.CODE,))
        operational_tasks.build(self.con, 'fixture', include_nazk=False)
        first = self.con.execute("SELECT id FROM operational_tasks WHERE task_type='amcu_exclusion'").fetchone()[0]
        self.con.execute("UPDATE operational_tasks SET status='completed',resolution_code='amcu_excluded' WHERE id=?", (first,))
        self.assertEqual(operational_tasks.build(self.con, 'repeat', include_nazk=False)['created'], 0)
        self.con.execute("INSERT INTO amcu_registry(row_key,offender_code,decision_date,decision_no) VALUES('A2',?,'2026-09-21','43')", (self.fixture.CODE,))
        changed = operational_tasks.build(self.con, 'new decision', include_nazk=False)
        self.assertEqual(changed['created'], 1)
        self.assertEqual(operational_tasks.build(self.con, 'repeat new decision', include_nazk=False)['created'], 0)

    def test_new_active_qualification_is_new_cycle_even_with_same_amcu_decision(self):
        self.con.execute("INSERT INTO amcu_registry(row_key,offender_code,decision_date,decision_no) VALUES('A1',?,'2026-09-20','42')", (self.fixture.CODE,))
        operational_tasks.build(self.con, 'first cycle', include_nazk=False)
        first = self.con.execute("SELECT id FROM operational_tasks WHERE task_type='amcu_exclusion'").fetchone()[0]
        self.con.execute("UPDATE operational_tasks SET status='completed',resolution_code='amcu_excluded' WHERE id=?", (first,))
        self.con.execute("UPDATE registry_contracts SET status='inactive' WHERE id='RC'")
        self.con.execute("INSERT INTO submissions VALUES('P','F','Supplier X',?,'2026-09-25','pending')", (self.fixture.CODE,))
        self.assertEqual(operational_tasks.build(self.con, 'new pending only', include_nazk=False)['created'], 0)
        self.con.execute("INSERT INTO submissions VALUES('S2','F','Supplier X',?,'2026-09-26','complete')", (self.fixture.CODE,))
        self.con.execute("INSERT INTO qualifications VALUES('Q2','S2','active','2026-09-26')")
        self.con.execute("INSERT INTO registry_contracts(id,qualification_id,framework_id,supplier_code,status) VALUES('RC2','Q2','F',?,'active')", (self.fixture.CODE,))
        self.assertEqual(operational_tasks.build(self.con, 'new active cycle', include_nazk=False)['created'], 1)
        self.assertEqual(operational_tasks.build(self.con, 'repeat new active cycle', include_nazk=False)['created'], 0)
        current = self.con.execute("SELECT id FROM operational_tasks WHERE task_type='amcu_exclusion' AND status NOT IN ('completed','cancelled')").fetchone()[0]
        linked = {row[0] for row in self.con.execute("SELECT application_id FROM operational_task_applications WHERE task_id=?", (current,))}
        self.assertIn('S2', linked)
        qualifications = {row[0] for row in self.con.execute("SELECT qualification_id FROM operational_task_qualifications WHERE task_id=?", (current,))}
        self.assertIn('Q2', qualifications)

    def test_committed_amcu_refresh_materializes_once_and_reports_downstream_failure(self):
        self.con.execute('DROP TABLE amcu_registry')
        self.con.execute('''CREATE TABLE amcu_registry (
          row_key TEXT PRIMARY KEY,ordinal TEXT,division_no TEXT,sequence_no TEXT,
          decision_no TEXT,decision_date TEXT,authority TEXT,offender_name TEXT,
          offender_code TEXT,court_case_no TEXT,raw_json TEXT)''')
        self.con.execute('''CREATE TABLE reference_sync_state (
          source TEXT PRIMARY KEY,status TEXT,message TEXT,row_count INTEGER DEFAULT 0,
          updated_at TEXT,source_updated_at TEXT)''')
        self.con.execute("INSERT INTO reference_sync_state(source,status) VALUES('amcu','idle')")
        matching = ('A1', '1', '', '', '42', '2026-09-20', 'AMCU', 'Fixture supplier', self.fixture.CODE, '', '{}')
        unrelated = ('A2', '2', '', '', '43', '2026-09-20', 'AMCU', 'Other supplier', '99999999', '', '{}')
        callback = lambda: operational_tasks.build(self.con, 'PQM AMCU refresh', include_nazk=False)
        with patch.object(ref.sqlite3, 'connect', return_value=self.con), \
             patch.object(ref, '_amcu_rows_bounded', return_value=('fixture', [matching])):
            ref.refresh_amcu('fixture', on_complete=callback)
            self.assertEqual(self.con.execute("SELECT status FROM reference_sync_state WHERE source='amcu'").fetchone()[0], 'ok')
            self.assertEqual(self.con.execute("SELECT COUNT(*) FROM operational_tasks WHERE task_type='amcu_exclusion'").fetchone()[0], 1)
            ref.refresh_amcu('fixture', on_complete=callback)
            self.assertEqual(self.con.execute("SELECT COUNT(*) FROM operational_tasks WHERE task_type='amcu_exclusion'").fetchone()[0], 1)
        with patch.object(ref.sqlite3, 'connect', return_value=self.con), \
             patch.object(ref, '_amcu_rows_bounded', return_value=('fixture', [unrelated])):
            ref.refresh_amcu('fixture', on_complete=callback)
            self.assertEqual(self.con.execute("SELECT COUNT(*) FROM operational_tasks WHERE task_type='amcu_exclusion' AND status!='cancelled'").fetchone()[0], 0)
        with patch.object(ref.sqlite3, 'connect', return_value=self.con), \
             patch.object(ref, '_amcu_rows_bounded', return_value=('fixture', [matching])):
            ref.refresh_amcu('fixture', on_complete=lambda: (_ for _ in ()).throw(RuntimeError('task build failed')))
            self.assertEqual(self.con.execute("SELECT status FROM reference_sync_state WHERE source='amcu'").fetchone()[0], 'error')


if __name__ == '__main__':
    unittest.main()
