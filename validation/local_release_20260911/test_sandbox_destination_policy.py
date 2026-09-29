"""SANDBOX mutation policy is based on attested destinations, not UI actions."""
import inspect
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sandbox_runtime
import server
import table_widths


class SandboxDestinationPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.data = Path(self.temp.name)
        self.path = self.data / 'pqm_sandbox.sqlite3'
        with sqlite3.connect(self.path) as con:
            con.executescript("""
                CREATE TABLE sandbox_deployment_identity(environment TEXT,service_id TEXT);
                INSERT INTO sandbox_deployment_identity VALUES ('sandbox','fixture-service');
                CREATE TABLE scheduler_job_settings(job_key TEXT,enabled INTEGER);
                CREATE TABLE runtime_feature_settings(enabled INTEGER);
                CREATE TABLE auth_users(role TEXT,active INTEGER);
                INSERT INTO auth_users VALUES ('admin',1);
            """)
            table_widths.migrate(con)

    def tearDown(self):
        self.temp.cleanup()

    def test_only_attested_sandbox_database_is_a_write_target(self):
        with patch.dict(sandbox_runtime.os.environ, {'PQM_SANDBOX': '1'}), \
                patch.object(sandbox_runtime, 'validate_environment',
                             return_value=(self.data,self.path,'fixture-service')):
            self.assertEqual(sandbox_runtime.attest_internal_target(self.path), self.path)
            with self.assertRaises(RuntimeError):
                sandbox_runtime.attest_internal_target(self.data / 'pqm_test_prod.sqlite3')
            with self.assertRaises(RuntimeError):
                sandbox_runtime.attest_internal_target(self.data / 'unknown.sqlite3')

    def test_supplier_column_widths_save_and_f5_reload(self):
        key = 'suppliersView:supplierRegistryBody'
        with sqlite3.connect(self.path) as con:
            table_widths.save(con, key, {'єдрпоу-рнокпп': 240}, 'sandbox.admin')
        with sqlite3.connect(self.path) as con:
            con.row_factory = sqlite3.Row
            self.assertEqual(table_widths.list_all(con)[key]['єдрпоу-рнокпп'], 240)

    def test_google_write_only_to_attested_sandbox_sheet(self):
        sheet = sandbox_runtime.SANDBOX_EDR_SPREADSHEET_ID
        with patch.dict(sandbox_runtime.os.environ, {'PQM_SANDBOX': '1'}):
            canonical = f'https://sheets.googleapis.com/v4/spreadsheets/{sheet}'
            for url, method in ((canonical, 'GET'),
                                (canonical + "/values/%27ЮО%27%21A%3AO?majorDimension=ROWS", 'GET'),
                                (canonical + "/values/%27ЮО%27%21A%3AO:append", 'POST'),
                                (canonical + '/values:batchUpdate', 'POST')):
                with self.subTest(url_kind=method):
                    self.assertEqual(sandbox_runtime.validate_google_request(url, method),
                                     sandbox_runtime.GOOGLE_SHEETS_HOST)
            for case, url in enumerate((
                    canonical + '/values/%2e%2e/%2e%2e/other-sheet/values/A1',
                    canonical + '/values/%252e%252e/%252e%252e/other-sheet/values/A1',
                    canonical + '/values/%2e./%2E%2e/other-sheet/values/A1',
                    canonical + '/values/%2F..%2Fother-sheet',
                    canonical + '/../other-sheet/values/A1',
                    canonical + '-sibling/values/A1',
                    'https://sheets.googleapis.com/v4/spreadsheets/PROD/values/X:append',
                    'https://sheets.googleapis.com/v4/spreadsheets/unknown:batchUpdate',
                    'https://sheets.googleapis.com/v4/spreadsheets/',
                    'https://sheets.googleapis.com:bad/v4/spreadsheets/' + sheet,
                    'https://sheets.googleapis.com/v4/spreadsheets/' + sheet + '/values/%FF',
                    canonical + '/values/A1#other-sheet',
                    canonical + '/values/A1?spreadsheetId=other-sheet')):
                with self.subTest(negative_case=case), self.assertRaises(RuntimeError):
                    sandbox_runtime.validate_google_request(url, 'POST')

    def test_public_read_is_not_an_external_write_escape(self):
        self.assertEqual(sandbox_runtime.validate_public_read_request(
            'https://example.org/document.pdf', 'GET'), 'example.org')
        for url, method in [('https://example.org/document.pdf', 'POST'),
                            ('http://example.org/document.pdf', 'GET'),
                            ('https://127.0.0.1/document.pdf', 'PUT')]:
            with self.assertRaises(RuntimeError):
                sandbox_runtime.validate_public_read_request(url, method)

    def test_server_dispatch_attests_destination_without_route_allowlist(self):
        source = inspect.getsource(server.Handler._dispatch)
        self.assertIn('sandbox_runtime.attest_internal_target(DB_PATH', source)
        self.assertIn('SAFE_MODE and not SANDBOX_MODE', source)
        self.assertNotIn('sandbox_runtime.local_edit_allowed(', source)
        self.assertNotIn('sandbox_runtime.operational_route_allowed(', source)


if __name__ == '__main__':
    unittest.main()
