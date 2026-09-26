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


if __name__ == '__main__':
    unittest.main()
