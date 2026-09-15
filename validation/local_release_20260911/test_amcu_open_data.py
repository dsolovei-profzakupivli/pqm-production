"""Offline AMCU adapter/source/freshness tests; synthetic data only."""
import copy
import io
import json
import sqlite3
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import reference_directories as ref


def workbook(code_headers=('ЄДРПОУ',)):
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active
    ws.append(['identifier', 'theEntityThatCommittedTheViolation', 'dateOfDecision', 'decisionNumber'])
    ws.append([*code_headers, "Суб'єкт господарювання, який вчинив порушення", 'Дата рішення у справі', '№ рішення у справі'])
    ws.append([*(['12345678'] * len(code_headers)), 'SYNTHETIC', '14.09.2026', '1'])
    result = io.BytesIO(); wb.save(result); wb.close()
    return result.getvalue()


class AmcuOpenDataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / 'synthetic.sqlite3'
        ref.init_reference_tables(self.db)
        self.old = ('old', '1', '', '', '1', '2026-09-10', 'AMCU', 'OLD', '12345678', '', '{}')
        self.new = ('new', '1', '', '', '2', '2026-09-14', 'AMCU', 'NEW', '12345678', '', '{}')
        with sqlite3.connect(self.db) as con:
            con.execute('INSERT INTO amcu_registry VALUES (?,?,?,?,?,?,?,?,?,?,?)', self.old)
            con.execute("UPDATE reference_sync_state SET row_count=1,source_updated_at='2026-09-11' WHERE source='amcu'")

    def tearDown(self):
        self.assertFalse(ref.AMCU_LOCK.locked())
        ref.AMCU_ERRORS.pop(str(self.db.resolve()), None)
        self.tmp.cleanup()

    def resource(self, day, stamp='2026-09-07', **overrides):
        rid = '2a69c909-3df8-4249-bd6b-1ff874ae708c'
        item = dict(id=rid, package_id=ref.AMCU_OPEN_DATA_ID, state='active', format='XLSX',
                    name=f'Зведені відомості станом на {day}.09.2026', description='',
                    last_modified=stamp, url=f'https://data.gov.ua/dataset/{ref.AMCU_OPEN_DATA_ID}/resource/{rid}/download/snapshot-{day}.xlsx')
        item.update(overrides)
        return item

    def metadata(self, resources):
        return dict(success=True, result=dict(id=ref.AMCU_OPEN_DATA_ID, private=False,
                    state='active', organization=dict(id=ref.AMCU_OPEN_DATA_ORG), resources=resources))

    def discovery(self, payload):
        with patch.object(ref, '_amcu_public_get', return_value=json.dumps(payload).encode()):
            return ref.discover_amcu_open_data()

    def rows(self):
        with sqlite3.connect(self.db) as con:
            return con.execute('SELECT * FROM amcu_registry').fetchall()

    def refresh(self, rows):
        with patch.object(ref, '_amcu_rows_bounded', return_value=('synthetic.xlsx', rows)):
            ref.refresh_amcu(self.db)
        return ref.reference_status(self.db)['amcu']

    def test_tested_code_alias_and_machine_header(self):
        rows = ref.parse_amcu_xlsx(workbook())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][4:6], ('1', '2026-09-14'))
        self.assertEqual(rows[0][7:9], ('SYNTHETIC', '12345678'))

    def test_original_code_header_still_supported(self):
        self.assertEqual(len(ref.parse_amcu_xlsx(workbook(('Ідентифікаційний код',)))), 1)

    def test_ambiguous_alias_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'заголовки'):
            ref.parse_amcu_xlsx(workbook(('ЄДРПОУ', 'ЄДРПОУ')))

    def test_latest_publication_not_array_order_or_modified_time(self):
        newest = self.resource('14', '2026-09-14')
        older = self.resource('07', '2026-09-15')
        self.assertEqual(self.discovery(self.metadata([newest, older])), newest['url'])

    def test_untrusted_private_or_wrong_dataset_is_rejected(self):
        base = self.metadata([self.resource('14')])
        changes = [dict(private=True), dict(id='wrong'), dict(state='deleted'), dict(organization={'id': 'wrong'})]
        for changeset in changes:
            with self.subTest(changeset=changeset), self.assertRaises(ValueError):
                candidate = copy.deepcopy(base); candidate['result'].update(changeset)
                self.discovery(candidate)

    def test_api_success_false_is_rejected(self):
        payload = self.metadata([self.resource('14')]); payload['success'] = False
        with self.assertRaises(ValueError):
            self.discovery(payload)

    def test_resource_without_unambiguous_date_is_rejected(self):
        for title in ('Набір без дати', '31.09.2026', '07.09.2026 та 14.09.2026', '14.09.2099'):
            with self.subTest(title=title), self.assertRaises(ValueError):
                self.discovery(self.metadata([self.resource('14', name=title)]))

    def test_external_resource_cannot_be_downloaded(self):
        with self.assertRaises(ValueError):
            self.discovery(self.metadata([self.resource('14', url='https://example.com/book.xlsx')]))
        with patch.object(ref.urllib.request, 'build_opener') as opener:
            for url in ('http://data.gov.ua/file.xlsx', 'https://127.0.0.1/private',
                        'https://data.gov.ua@evil.test/file.xlsx'):
                with self.subTest(url=url), self.assertRaises(ValueError):
                    ref._amcu_public_get(url, 100)
            opener.assert_not_called()

    def test_public_get_is_bounded_truthful_and_does_not_redirect(self):
        with patch.object(ref.urllib.request, 'build_opener') as opener:
            response = opener.return_value.open.return_value.__enter__.return_value
            response.read.return_value = b'123456'
            with self.assertRaisesRegex(ValueError, 'розмір'):
                ref._amcu_public_get(ref.AMCU_OPEN_DATA_API, 5)
            response.read.assert_called_once_with(6)
            request = opener.return_value.open.call_args.args[0]
            self.assertIn('PQM-WEB-TEST', request.get_header('User-agent'))
            self.assertIsNone(request.get_header('Authorization'))
            self.assertIsNone(request.get_header('Cookie'))
            handler = opener.call_args.args[0]
            self.assertIsNone(handler.redirect_request(None, None, 302, None, {}, 'https://evil.test'))

    def test_403_primary_uses_official_separate_dataset_once(self):
        error = urllib.error.HTTPError(ref.AMCU_PAGE, 403, 'Forbidden', {}, None)
        with patch.object(ref, 'discover_amcu_xlsx', side_effect=error), \
             patch.object(ref, 'discover_amcu_open_data', return_value='official-dataset') as discover, \
             patch.object(ref, '_amcu_public_get', return_value=workbook()) as fetch:
            source, rows = ref._download_amcu_rows()
        self.assertEqual(source, 'official-dataset')
        self.assertEqual(len(rows), 1)
        discover.assert_called_once(); fetch.assert_called_once()

    def test_successful_primary_does_not_fetch_fallback(self):
        with patch.object(ref, 'discover_amcu_xlsx', return_value='official-primary'), \
             patch.object(ref, '_fetch', return_value=workbook()), \
             patch.object(ref, 'discover_amcu_open_data') as fallback:
            self.assertEqual(ref._download_amcu_rows()[0], 'official-primary')
        fallback.assert_not_called()

    def test_both_source_errors_are_visible(self):
        with patch.object(ref, 'discover_amcu_xlsx', side_effect=ValueError('primary failed')), \
             patch.object(ref, 'discover_amcu_open_data', side_effect=ValueError('fallback failed')):
            with self.assertRaisesRegex(ValueError, 'primary failed.*fallback failed'):
                ref._download_amcu_rows()

    def test_stale_snapshot_is_terminal_and_preserves_source_timestamp(self):
        older = list(self.new); older[5] = '2026-09-04'
        state = self.refresh([older])
        self.assertEqual(state['status'], 'error')
        self.assertIn('застаріле', state['message'])
        self.assertEqual(state['source_updated_at'], '2026-09-11')
        self.assertEqual(state['row_count'], 1)
        self.assertEqual(self.rows(), [self.old])

    def test_newer_or_same_date_is_allowed(self):
        for date in ('2026-09-10', '2026-09-14'):
            row = list(self.new); row[5] = date
            self.assertEqual(self.refresh([row])['status'], 'ok')

    def test_invalid_future_missing_and_empty_rows_never_replace(self):
        for date in ('not-a-date', '2026-02-31', '2099-01-01', ''):
            row = list(self.new); row[5] = date
            self.assertEqual(self.refresh([row])['status'], 'error')
            self.assertEqual(self.rows(), [self.old])
        self.assertEqual(self.refresh([])['status'], 'error')
        row = list(self.new); row[8] = ''
        self.assertEqual(self.refresh([row])['status'], 'error')
        self.assertEqual(self.rows(), [self.old])

    def test_large_count_drop_rejected_but_small_rolling_change_allowed(self):
        with sqlite3.connect(self.db) as con:
            con.execute('DELETE FROM amcu_registry')
            con.executemany('INSERT INTO amcu_registry VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                            [(str(i), *self.old[1:]) for i in range(100)])
        self.assertEqual(self.refresh([self.new])['status'], 'error')
        self.assertEqual(len(self.rows()), 100)
        rows = [(str(i), *self.new[1:]) for i in range(95)]
        self.assertEqual(self.refresh(rows)['status'], 'ok')
        self.assertEqual(len(self.rows()), 95)


if __name__ == '__main__':
    unittest.main()
