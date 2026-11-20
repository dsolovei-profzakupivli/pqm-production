"""Real EDR GET filtering on synthetic read-only projections, without live DBs."""
from http.server import ThreadingHTTPServer
import json
import threading
import unittest
from urllib.request import urlopen
from unittest.mock import patch
from pathlib import Path

import server


class EdrDkHttpTests(unittest.TestCase):
    def setUp(self):
        self.rows = [dict(supplier_code=code, supplier_name='Synthetic', manager_name='',
                          entity_type='legal_entity', prozorro_status='Допущено',
                          edr_status='Зареєстровано', freshness='current', verification_date='',
                          latest_application_date='', verification_officer='', google_note='')
                     for code in ['99003221', '99003222', '99003223']]
        self.dk = {'99003221': {'03210000-6'}, '99003222': {'03220000-9'},
                   '99003223': {'45000000-7'}}
        self.enterContext(patch.object(server, '_edr_monitoring_rows', return_value=self.rows))
        self.enterContext(patch.object(server, '_edr_monitoring_dk_map', return_value=self.dk))
        self.enterContext(patch.object(server, 'db', side_effect=AssertionError('No live database')))
        # Authorization has independent coverage; execute the shipped GET router itself.
        class FixtureHandler(server.Handler):
            def do_GET(self):
                self.auth_user = 'synthetic'
                self.auth_role = 'admin'
                return self._do_GET()
        self.http = ThreadingHTTPServer(('127.0.0.1', 0), FixtureHandler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.http.shutdown()
        self.thread.join(timeout=5)
        self.http.server_close()
        self.assertFalse(self.thread.is_alive())

    def get_codes(self, query):
        with urlopen(f'http://127.0.0.1:{self.http.server_port}/api/edr-monitoring?{query}', timeout=5) as response:
            payload = json.load(response)
        return sorted(item['supplier_code'] for item in payload['items'])

    def test_single_code_legacy_request(self):
        self.assertEqual(self.get_codes('dk_code=03220000-9'), ['99003222'])

    def test_multiple_comma_separated_codes_are_union(self):
        self.assertEqual(self.get_codes('dk_code=03210000-6,03220000-9'), ['99003221', '99003222'])

    def test_repeated_codes_are_union_without_duplicates(self):
        self.assertEqual(self.get_codes('dk_code=03210000-6&dk_code=03220000-9&dk_code=03210000-6'), ['99003221', '99003222'])

    def test_substring_is_not_a_supplier_id_or_exact_dk_selection(self):
        self.assertEqual(self.get_codes('dk_code=0322'), [])
        self.assertEqual(self.get_codes('search=0322'), ['99003221', '99003222', '99003223'])

    def test_clear_dk_restores_unscoped_result(self):
        self.assertEqual(self.get_codes('dk_code='), ['99003221', '99003222', '99003223'])

    def test_static_resources_come_from_one_source_and_disable_cache(self):
        for name in ['index.html', 'app.js', 'queue_statistics_ui.js',
                     'ui_improvements.js', 'filter_panels.css', 'halloween.css']:
            with self.subTest(asset=name):
                with urlopen(f'http://127.0.0.1:{self.http.server_port}/{name}', timeout=5) as response:
                    self.assertIn('no-store', response.headers['Cache-Control'])
                    actual = response.read()
                expected = (Path(server.ROOT) / name).read_bytes()
                if name == 'index.html' and server.SANDBOX_MODE:
                    import sandbox_runtime
                    expected = sandbox_runtime.decorate_html(expected)
                self.assertEqual(actual, expected)


if __name__ == '__main__':
    unittest.main()
