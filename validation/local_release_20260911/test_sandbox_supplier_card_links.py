"""Supplier-card navigation never trusts a stale snapshot row or PROD sheet."""
import io
import json
import os
import unittest
from unittest.mock import patch

import sandbox_runtime
import server


class SandboxSupplierCardLinkTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(server, 'sandbox_runtime', sandbox_runtime, create=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        source = patch.object(server, 'SUPPLIER_EDR_SHEET_ID', sandbox_runtime.SANDBOX_EDR_SPREADSHEET_ID)
        source.start()
        self.addCleanup(source.stop)

    def test_current_literal_identity_resolves_tab_row_and_gid(self):
        values = {'ФОП': [['A', 'B'], ['', 'other']],
                  'ЮО': [['A', 'B'], ['', 'other'], ['', '00123456']]}
        metadata = {'sheets': [{'properties': {'title': 'ФОП', 'sheetId': 7}},
                               {'properties': {'title': 'ЮО', 'sheetId': 11}}]}
        with patch.object(server, 'SANDBOX_MODE', True), \
             patch.dict(os.environ, {'PQM_SANDBOX': '1', 'PQM_SANDBOX_EDR_GOOGLE': '1'}), \
             patch.object(server, '_google_sheet_values', side_effect=lambda tab: values[tab]) as read, \
             patch.object(server, '_google_access_token', return_value='test-token'), \
             patch.object(sandbox_runtime, 'google_open', return_value=io.BytesIO(json.dumps(metadata).encode())) as open_sheet:
            result = server.sandbox_supplier_google_row('00123456')
        self.assertEqual(read.call_count, 2)
        self.assertEqual(result['source_tab'], 'ЮО')
        self.assertEqual(result['url'],
                         f'https://docs.google.com/spreadsheets/d/{sandbox_runtime.SANDBOX_EDR_SPREADSHEET_ID}/edit#gid=11&range=B3')
        self.assertIn(sandbox_runtime.SANDBOX_EDR_SPREADSHEET_ID, open_sheet.call_args.args[0].full_url)

    def test_missing_or_ambiguous_literal_identity_fails_closed(self):
        with patch.object(server, 'SANDBOX_MODE', True), \
             patch.dict(os.environ, {'PQM_SANDBOX': '1', 'PQM_SANDBOX_EDR_GOOGLE': '1'}), \
             patch.object(server, '_google_sheet_values', side_effect=[[], []]):
            with self.assertRaises(KeyError):
                server.sandbox_supplier_google_row('00123456')
        with patch.object(server, 'SANDBOX_MODE', True), \
             patch.dict(os.environ, {'PQM_SANDBOX': '1', 'PQM_SANDBOX_EDR_GOOGLE': '1'}), \
             patch.object(server, '_google_sheet_values', side_effect=[[['', '00123456']], [['', '00123456']]]):
            with self.assertRaisesRegex(ValueError, 'ambiguous'):
                server.sandbox_supplier_google_row('00123456')

    def test_prod_or_unapproved_source_cannot_resolve(self):
        with patch.object(server, 'SANDBOX_MODE', False):
            with self.assertRaises(PermissionError):
                server.sandbox_supplier_google_row('00123456')
        with patch.object(server, 'SANDBOX_MODE', True), \
             patch.dict(os.environ, {'PQM_SANDBOX': '1', 'PQM_SANDBOX_EDR_GOOGLE': '0'}):
            with self.assertRaises(PermissionError):
                server.sandbox_supplier_google_row('00123456')
        metadata_url = (f'https://sheets.googleapis.com/v4/spreadsheets/{sandbox_runtime.SANDBOX_EDR_SPREADSHEET_ID}'
                        '?fields=sheets%28properties%28sheetId%2Ctitle%29%29')
        with patch.dict(os.environ, {'PQM_SANDBOX': '1', 'PQM_SANDBOX_EDR_GOOGLE': '1'}):
            self.assertEqual(sandbox_runtime.validate_google_request(metadata_url, 'GET'),
                             sandbox_runtime.GOOGLE_SHEETS_HOST)
            with self.assertRaises(RuntimeError):
                sandbox_runtime.validate_google_request(metadata_url.replace(
                    sandbox_runtime.SANDBOX_EDR_SPREADSHEET_ID, 'PROD-ID'), 'GET')

    def test_sandbox_503_diagnostics_are_sanitized_and_stage_specific(self):
        with patch.object(server, 'SANDBOX_MODE', True), \
             patch.dict(os.environ, {'PQM_SANDBOX': '1', 'PQM_SANDBOX_EDR_GOOGLE': '1'}), \
             patch.object(server, '_google_oauth_client', return_value=None), \
             patch.object(server, 'GOOGLE_OAUTH_CLIENT_ACCESS_ERROR', ''):
            self.assertEqual(server.sandbox_google_row_failure(PermissionError()),
                             {'code': 'sandbox_google_not_configured', 'phase': 'oauth_client'})
        with patch.object(server, 'SANDBOX_MODE', True), \
             patch.dict(os.environ, {'PQM_SANDBOX': '1', 'PQM_SANDBOX_EDR_GOOGLE': '1'}), \
             patch.object(server, '_google_oauth_client', return_value={'client_id': 'fixture'}), \
             patch.object(server, '_google_oauth_token', return_value=None):
            self.assertEqual(server.sandbox_google_row_failure(PermissionError()),
                             {'code': 'sandbox_token_unavailable', 'phase': 'oauth_token'})
        with patch.object(server, 'SANDBOX_MODE', True), \
             patch.dict(os.environ, {'PQM_SANDBOX': '1', 'PQM_SANDBOX_EDR_GOOGLE': '1'}), \
             patch.object(server, '_google_oauth_client', return_value={'client_id': 'fixture'}), \
             patch.object(server, '_google_oauth_token', return_value={'refresh_token': 'fixture'}):
            self.assertEqual(server.sandbox_google_row_failure(RuntimeError('sensitive detail')),
                             {'code': 'sandbox_transport_unavailable', 'phase': 'sandbox_transport'})
        with patch.object(server, 'SUPPLIER_EDR_SHEET_ID', 'wrong-source'):
            self.assertEqual(server.sandbox_google_row_failure(PermissionError()),
                             {'code': 'sandbox_source_guard', 'phase': 'source_preflight'})
        phase_error = server.GooglePhaseError.__new__(server.GooglePhaseError)
        phase_error.details = {'phase': 'sheets_values_read'}
        self.assertEqual(server.sandbox_google_row_failure(phase_error),
                         {'code': 'google_request_failed', 'phase': 'sheets_values_read'})

    def test_sandbox_route_preserves_success_missing_duplicate_disabled_and_503_statuses(self):
        handler = server.Handler.__new__(server.Handler)
        handler.path = '/api/sandbox/supplier-google-row/43151322'
        handler.send_json = lambda payload, status=200: (status, payload)
        with patch.object(server, 'SANDBOX_MODE', True), \
             patch.dict(os.environ, {'PQM_SANDBOX': '1', 'PQM_SANDBOX_EDR_GOOGLE': '1'}):
            with patch.object(server, 'sandbox_supplier_google_row', return_value={'source_tab': 'ЮО', 'url': 'fixture'}):
                status, body = handler._do_GET()
                self.assertEqual((status, body['source_tab']), (200, 'ЮО'))
            for error, expected in [(KeyError(), 404), (ValueError('ambiguous'), 409),
                                    (PermissionError(), 503)]:
                with self.subTest(error=type(error).__name__), \
                     patch.object(server, 'sandbox_supplier_google_row', side_effect=error), \
                     patch.object(server, 'sandbox_google_row_failure', return_value={
                         'code': 'sandbox_token_unavailable', 'phase': 'oauth_token'}):
                    status, body = handler._do_GET()
                    self.assertEqual(status, expected)
                    if status == 503:
                        self.assertEqual((body['code'], body['phase']),
                                         ('sandbox_token_unavailable', 'oauth_token'))
                        self.assertNotIn('fixture', str(body))
        with patch.object(server, 'SANDBOX_MODE', True), \
             patch.dict(os.environ, {'PQM_SANDBOX': '1', 'PQM_SANDBOX_EDR_GOOGLE': '0'}), \
             patch.object(server, 'sandbox_supplier_google_row') as lookup:
            self.assertEqual(handler._do_GET()[0], 404)
            lookup.assert_not_called()


if __name__ == '__main__':
    unittest.main()
