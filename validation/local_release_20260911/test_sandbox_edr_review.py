import sqlite3
import unittest
from unittest import mock
import urllib.request

import edr_sync_v2 as sync
import sandbox_edr_review
import sandbox_runtime
import server
try:
    from test_edr_sync_v2 import database, row, snapshot
except ImportError:
    from validation.local_release_20260911.test_edr_sync_v2 import database, row, snapshot


class SandboxEdrReviewTests(unittest.TestCase):
    def test_runtime_google_status_uses_only_narrow_sandbox_scope(self):
        con = mock.MagicMock()
        con.execute.return_value.fetchone.return_value = None
        con.__enter__.return_value = con
        with mock.patch.object(server, 'sandbox_runtime', sandbox_runtime, create=True), \
             mock.patch.object(server, 'SANDBOX_MODE', True), \
             mock.patch.object(server, 'db', return_value=con), \
             mock.patch.object(server, 'google_oauth_status', return_value={'configured': True}), \
             mock.patch.dict(sandbox_runtime.os.environ,
                             {'PQM_SANDBOX': '1', 'PQM_SANDBOX_EDR_GOOGLE': '1'}):
            enabled = server.google_integration_status()
        self.assertTrue(enabled['enabled'])
        self.assertEqual(enabled['configuration_source'], 'sandbox_edr_scope')
        with mock.patch.object(server, 'sandbox_runtime', sandbox_runtime, create=True), \
             mock.patch.object(server, 'SANDBOX_MODE', True), \
             mock.patch.object(server, 'db', return_value=con), \
             mock.patch.object(server, 'google_oauth_status', return_value={'configured': True}), \
             mock.patch.dict(sandbox_runtime.os.environ,
                             {'PQM_SANDBOX': '1', 'PQM_SANDBOX_EDR_GOOGLE': '0'}):
            self.assertFalse(server.google_integration_status()['enabled'])

    def test_complete_detail_and_clear_without_preview_write(self):
        con = database()
        con.execute("""INSERT INTO supplier_edr_profiles
          (supplier_code,full_name,edr_status,edr_checked_at,edr_officer,
           termination_decision_details,edr_notes,synced_at)
          VALUES('12345678','OLD NAME','Неактуально','2026-09-15','OLD OFFICER',
                 'OLD TERMINATION','OLD NOTE','old')""")
        con.commit()
        google = row(checked='16.09.2026', officer='NEW OFFICER')
        google[6] = ''
        google[12] = ''
        source = snapshot(google)
        before = con.total_changes
        preview = sync.build_preview(con, source)
        details = sandbox_edr_review.details(preview)
        self.assertEqual(con.total_changes, before)
        self.assertEqual(next(x for x in details if x['field'] == 'verification_pair')['action'], 'accept_google_pair')
        self.assertEqual(next(x for x in details if x['field'] == 'termination_decision_details')['action'], 'clear')
        self.assertEqual(next(x for x in details if x['field'] == 'edr_notes')['action'], 'clear')
        self.assertEqual(sandbox_edr_review.summary_additions(preview, details)['m_note_clears'], 1)
        self.assertEqual(len(details), len(sandbox_edr_review.details(preview)))

    def test_state_digest_rejects_stale_pqm_before_business_write(self):
        con = database()
        con.execute("INSERT INTO supplier_edr_profiles(supplier_code,synced_at) VALUES('12345678','old')")
        source = snapshot(row())
        reviewed = sync.build_preview(con, source)
        digest = sync.preview_state_digest(reviewed)
        con.execute("UPDATE supplier_edr_profiles SET full_name='CHANGED' WHERE supplier_code='12345678'")
        count = con.total_changes
        with self.assertRaisesRegex(RuntimeError, 'PQM state changed'):
            sync.apply(con, source, source['source_fingerprint'], confirmed=True, actor='test',
                       synced_at='2026-09-26T10:00:00', expected_state_digest=digest)
        self.assertEqual(con.total_changes, count)

    def test_sandbox_sheet_identity_changes_fingerprint(self):
        values = {'ФОП': [list(sync.HEADERS), row()], 'ЮО': [list(sync.HEADERS)]}
        sandbox = sync.source_snapshot(values, spreadsheet_id=sandbox_runtime.SANDBOX_EDR_SPREADSHEET_ID)
        production = sync.source_snapshot(values)
        self.assertNotEqual(sandbox['source_fingerprint'], production['source_fingerprint'])

    def test_scoped_route_never_allows_unrelated_google_or_prod(self):
        previous = dict(sandbox_runtime.os.environ)
        try:
            sandbox_runtime.os.environ['PQM_SANDBOX'] = '1'
            sandbox_runtime.os.environ['PQM_SANDBOX_EDR_GOOGLE'] = '1'
            self.assertTrue(sandbox_runtime.edr_google_route_allowed('POST', '/api/supplier-edr-sync/preview'))
            self.assertTrue(sandbox_runtime.edr_google_route_allowed('POST', '/api/supplier-edr-sync'))
            self.assertFalse(sandbox_runtime.edr_google_route_allowed('POST', '/api/supplier-nazk-review-sync'))
            self.assertFalse(sandbox_runtime.edr_google_route_allowed('POST', '/api/admin/runtime-features/google'))
            self.assertFalse(sandbox_runtime.edr_google_route_allowed('GET', '/api/supplier-edr-sync'))
        finally:
            sandbox_runtime.os.environ.clear()
            sandbox_runtime.os.environ.update(previous)

    def test_scoped_google_transport_accepts_only_sandbox_reads_and_oauth_token(self):
        with mock.patch.dict(sandbox_runtime.os.environ,
                             {'PQM_SANDBOX': '1', 'PQM_SANDBOX_EDR_GOOGLE': '1'}):
            sheet = sandbox_runtime.SANDBOX_EDR_SPREADSHEET_ID
            self.assertEqual(sandbox_runtime.validate_google_request(
                f'https://sheets.googleapis.com/v4/spreadsheets/{sheet}/values/%27ФОП%27%21A%3AO?majorDimension=ROWS',
                'GET'), sandbox_runtime.GOOGLE_SHEETS_HOST)
            self.assertEqual(sandbox_runtime.validate_google_request(
                'https://oauth2.googleapis.com/token', 'POST'), sandbox_runtime.GOOGLE_TOKEN_HOST)
            for url, method in [
                ('https://oauth2.googleapis.com/token', 'GET'),
                ('https://sheets.googleapis.com/v4/spreadsheets/PROD/values/%27ФОП%27%21A%3AO?majorDimension=ROWS', 'GET'),
                (f'https://sheets.googleapis.com/v4/spreadsheets/{sheet}/values/%27ФОП%27%21A%3AO?majorDimension=ROWS', 'POST'),
                ('https://www.googleapis.com/drive/v3/files', 'GET'),
            ]:
                with self.subTest(url=url, method=method), self.assertRaises(RuntimeError):
                    sandbox_runtime.validate_google_request(url, method)

    def test_google_transport_rejects_unapproved_request_before_network(self):
        with mock.patch.dict(sandbox_runtime.os.environ,
                             {'PQM_SANDBOX': '1', 'PQM_SANDBOX_EDR_GOOGLE': '1'}):
            with mock.patch.object(urllib.request, 'build_opener') as opener:
                with self.assertRaises(RuntimeError):
                    with sandbox_runtime.google_open(urllib.request.Request('https://sheets.googleapis.com/v4/spreadsheets/PROD/values/X')):
                        pass
                opener.assert_not_called()

    def test_review_details_not_truncated_after_500_suppliers(self):
        con = database()
        google_rows = []
        for number in range(501):
            code = str(10000000 + number)
            con.execute('INSERT INTO supplier_edr_profiles(supplier_code,synced_at) VALUES (?,?)', (code, 'old'))
            google_rows.append(row(code=code))
        values = {'ФОП': [list(sync.HEADERS), *google_rows], 'ЮО': [list(sync.HEADERS)]}
        source = sync.source_snapshot(values, spreadsheet_id=sandbox_runtime.SANDBOX_EDR_SPREADSHEET_ID)
        before = con.total_changes
        preview = sync.build_preview(con, source)
        details = sandbox_edr_review.details(preview)
        self.assertGreaterEqual(len(details), 501)
        self.assertEqual(len({item['supplier_code'] for item in details}), 501)
        self.assertEqual(con.total_changes, before)


if __name__ == '__main__':
    unittest.main()
