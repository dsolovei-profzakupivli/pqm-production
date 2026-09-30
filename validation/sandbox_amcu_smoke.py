"""Offline policy tests: never fetch a registry or open a working database."""
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from io import BytesIO
from openpyxl import Workbook
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sandbox_amcu as amcu
import reference_directories as ref


class Policy(unittest.TestCase):
    @staticmethod
    def excel_bytes():
        book = Workbook()
        sheet = book.active
        sheet.append(['Ідентифікаційний код', 'Суб’єкт порушення', 'Дата рішення', '№ рішення', 'Орган, що прийняв'])
        sheet.append(['12345678', 'ТОВ ТЕСТ', '24.09.2026', '42', 'АМКУ'])
        output = BytesIO()
        book.save(output)
        return output.getvalue()

    def test_routes_and_default_disabled(self):
        with patch.dict(os.environ, {'PQM_SANDBOX': '1', 'PQM_SANDBOX_AMCU_READ': '0'}):
            self.assertFalse(amcu.route_allowed('POST', '/api/amcu-registry/refresh'))
            with self.assertRaises(RuntimeError):
                ref._amcu_rows_bounded()
        with patch.dict(os.environ, {'PQM_SANDBOX': '1', 'PQM_SANDBOX_AMCU_READ': '1',
                                     'PQM_SANDBOX_OPERATIONAL': '0'}):
            self.assertFalse(amcu.route_allowed('POST', '/api/amcu-registry/upload'))
        with patch.dict(os.environ, {'PQM_SANDBOX': '1', 'PQM_SANDBOX_AMCU_READ': '1',
                                     'PQM_SANDBOX_OPERATIONAL': '1'}):
            self.assertTrue(amcu.route_allowed('POST', '/api/amcu-registry/refresh'))
            self.assertTrue(amcu.route_allowed('POST', '/api/amcu-registry/upload'))
            for path in ('/api/nazk-registry/refresh', '/api/sync'):
                self.assertFalse(amcu.route_allowed('POST', path))
            self.assertFalse(amcu.route_allowed('GET', '/api/amcu-registry/refresh'))
            with self.assertRaises(ValueError):
                ref._amcu_rows_bounded(b'xlsx', 'invalid.txt')
        self.assertFalse(amcu.permitted_process('subprocess.Popen', ('sh', ['sh'], None, None)))

    def test_sandbox_upload_reuses_shared_parser_without_database_or_network(self):
        with patch.dict(os.environ, {'PQM_SANDBOX': '1', 'PQM_SANDBOX_AMCU_READ': '1',
                                     'PQM_SANDBOX_OPERATIONAL': '1'}), \
             patch('sandbox_runtime.validate_environment', return_value=None):
            source, rows = ref._amcu_rows_bounded(self.excel_bytes(), 'official.xlsx')
            self.assertEqual(source, 'official.xlsx')
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][5], '2026-09-24')
            with self.assertRaises(RuntimeError):
                ref._amcu_rows_bounded(b'not an xlsx', 'official.xlsx')

    def test_sources(self):
        for url in (ref.AMCU_PAGE, ref.AMCU_OPEN_DATA_API,
                    'https://amcu.gov.ua/static-objects/amcu/sites/1/2026/file.xlsx',
                    f'https://data.gov.ua/dataset/{ref.AMCU_OPEN_DATA_ID}/resource/id/download/file.xlsx'):
            self.assertIn(amcu.validate_url(url), {'amcu.gov.ua', 'data.gov.ua'})
        for url in ('http://amcu.gov.ua/static-objects/amcu/file.xlsx',
                    'https://amcu.gov.ua.evil.test/file.xlsx', 'https://127.0.0.1/file.xlsx',
                    'https://amcu.gov.ua:443/static-objects/amcu/file.xlsx',
                    'https://user@amcu.gov.ua/static-objects/amcu/file.xlsx',
                    'https://amcu.gov.ua/static-objects/amcu/../secret.xlsx',
                    'https://amcu.gov.ua/static-objects/amcu/%2e/file.xlsx',
                    'https://amcu.gov.ua/static-objects/amcu/file.xlsx?token=secret'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                amcu.validate_url(url)

    def test_worker_denies_network_database_and_process_outside_scope(self):
        script = '''
import socket, sqlite3, subprocess
import sandbox_amcu
sandbox_amcu.install_worker_transport()
for action in (lambda: socket.create_connection(('127.0.0.1',443)),
               lambda: socket.getaddrinfo('amcu.gov.ua',443),
               lambda: sqlite3.connect(':memory:'),
               lambda: subprocess.run(['true'])):
    try: action()
    except RuntimeError: pass
    else: raise AssertionError('Worker escaped transport scope')
print('OK')
'''
        result = subprocess.run([sys.executable, '-B', '-c', script],
                                cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('OK', result.stdout)

    def test_upload_worker_denies_all_network(self):
        script = '''
import socket, sqlite3
import sandbox_amcu
sandbox_amcu.install_worker_transport(allow_download=False)
for action in (lambda: socket.getaddrinfo('amcu.gov.ua',443),
               lambda: socket.create_connection(('127.0.0.1',443)),
               lambda: sqlite3.connect(':memory:')):
    try: action()
    except RuntimeError: pass
    else: raise AssertionError('Upload worker escaped isolation')
print('OK')
'''
        result = subprocess.run([sys.executable, '-B', '-c', script],
                                cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('OK', result.stdout)


if __name__ == '__main__':
    unittest.main()
