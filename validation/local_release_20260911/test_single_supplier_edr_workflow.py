"""Offline single-supplier Google EDR workflow; no network or live Apply."""
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import edr_sync_v2
import server


class SingleSupplierEdrWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.old_db = server.DB_PATH
        server.DB_PATH = Path(self.temp.name) / 'workflow.sqlite3'
        server.init_db()
        server.init_reference_tables(server.DB_PATH)
        with server.db() as con:
            con.execute("""INSERT INTO frameworks(id,pretty_id,status,raw_json,synced_at)
              VALUES('f','UA-F-TEST','active','{}',?)""", (server.now_iso(),))
            con.execute("""INSERT INTO submissions
              (id,framework_id,supplier_code,supplier_name,date_published,raw_json,synced_at)
              VALUES('s','f','46130719','ІСТОРИЧНА НАЗВА','2026-09-27',?,?)""",
              (json.dumps({'tenderers': [{'identifier': {'id': '46130719', 'scheme': 'UA-EDR'}}]}),
               server.now_iso()))
            con.execute("""INSERT INTO application_fields(submission_id,protocol_decision)
              VALUES('s','admit')""")

    def tearDown(self):
        server.DB_PATH = self.old_db
        self.temp.cleanup()

    @staticmethod
    def source(full, short, status='✅ Зареєстровано'):
        values = ['', '46130719', 'ІСТОРИЧНА НАЗВА', 'КЕРІВНИК', status,
                  'Активний', '', '', '27.09.2026', '', '', 'УО', '', full, short]
        return edr_sync_v2.source_snapshot({'ФОП': [list(edr_sync_v2.HEADERS)],
                                            'ЮО': [list(edr_sync_v2.HEADERS), values]})

    def apply(self, source):
        with server.db() as con:
            return edr_sync_v2.apply(con, source, source['source_fingerprint'],
                                     confirmed=True, actor='offline-test', synced_at=server.now_iso())

    def test_new_row_preview_apply_card_lookup_and_repeat_noop(self):
        with server.db() as con:
            item = next(x for x in server.supplier_registry_integration.full_registry(con)['items']
                        if x['supplier_code'] == '46130719')
        self.assertEqual(item['entity_type'], 'legal_entity')
        self.assertTrue(item['monitoring_eligible'])
        with server.db() as con:
            self.assertIsNone(con.execute("SELECT 1 FROM supplier_edr_profiles WHERE supplier_code='46130719'").fetchone())
        source = self.source('НОВА ПОВНА', 'НОВА СКОРОЧЕНА')
        with server.db() as con:
            before = con.total_changes
            preview = edr_sync_v2.build_preview(con, source)
            self.assertEqual(con.total_changes, before)
        self.assertEqual(preview['summary']['conflicts'], 0)
        self.assertTrue(preview['items'][0]['apply_allowed'])
        self.assertFalse(preview['items'][0]['existing_profile'])
        self.assertEqual(self.apply(source)['inserted'], 1)
        card = server.supplier_profile('46130719')
        edr = card['edr_profile']
        self.assertEqual((edr['full_name'], edr['short_name'], edr['edr_status']),
                         ('НОВА ПОВНА', 'НОВА СКОРОЧЕНА', 'Зареєстровано'))
        self.assertEqual((edr['source_sheet'], edr['source_row']), ('ЮО', 2))
        self.assertEqual(edr['edr_officer'], 'УО')
        self.assertEqual(server.edr_sync_v2.canonical_edr_status(edr['edr_status']), 'Зареєстровано')
        with server.db() as con:
            self.assertEqual(con.execute("SELECT supplier_name FROM submissions WHERE id='s'").fetchone()[0],
                             'ІСТОРИЧНА НАЗВА')
        repeated = self.apply(source)
        self.assertEqual(repeated['updated_profiles'], 0)
        self.assertEqual(repeated['verification_events'], 0)
        values = {'ФОП': [['name', 'code']], 'ЮО': [['name', 'code'], ['supplier', '46130719']]}
        metadata = {'sheets': [{'properties': {'title': 'ЮО', 'sheetId': 20}}]}
        sandbox_runtime = SimpleNamespace(SANDBOX_EDR_SPREADSHEET_ID='offline-sheet',
                                          edr_google_enabled=lambda: True,
                                          google_open=lambda *_args, **_kwargs:
                                          io.BytesIO(json.dumps(metadata).encode()))
        with patch.object(server, 'SANDBOX_MODE', True), \
             patch.dict(os.environ, {'PQM_SANDBOX': '1', 'PQM_SANDBOX_EDR_GOOGLE': '1'}), \
             patch.object(server, 'sandbox_runtime', sandbox_runtime, create=True), \
             patch.object(server, 'SUPPLIER_EDR_SHEET_ID', 'offline-sheet'), \
             patch.object(server, '_google_sheet_values', side_effect=lambda tab: values[tab]), \
             patch.object(server, '_google_access_token', return_value='offline-token'):
            self.assertTrue(server.sandbox_supplier_google_row('46130719')['url'].endswith('#gid=20&range=B2'))
            with self.assertRaises(KeyError):
                server.sandbox_supplier_google_row('00000000')
            values['ФОП'].append(['duplicate', '46130719'])
            with self.assertRaisesRegex(ValueError, 'ambiguous'):
                server.sandbox_supplier_google_row('46130719')

    def test_existing_profile_preview_apply_card_and_noop(self):
        first = self.source('ПЕРША ПОВНА', 'ПЕРША КОРОТКА', 'Зареєстровано')
        self.apply(first)
        second = self.source('ОНОВЛЕНА ПОВНА', 'ОНОВЛЕНА КОРОТКА')
        with server.db() as con:
            preview = edr_sync_v2.build_preview(con, second)
        item = preview['items'][0]
        self.assertEqual(item['current_profile']['full_name'], 'ПЕРША ПОВНА')
        self.assertEqual(item['incoming']['full_name'], 'ОНОВЛЕНА ПОВНА')
        self.assertEqual(item['current_profile']['short_name'], 'ПЕРША КОРОТКА')
        self.assertEqual(item['incoming']['short_name'], 'ОНОВЛЕНА КОРОТКА')
        self.assertEqual(self.apply(second)['updated_profiles'], 1)
        card = server.supplier_profile('46130719')['edr_profile']
        self.assertEqual((card['full_name'], card['short_name'], card['edr_status']),
                         ('ОНОВЛЕНА ПОВНА', 'ОНОВЛЕНА КОРОТКА', 'Зареєстровано'))
        repeated = self.apply(second)
        self.assertEqual(repeated['updated_profiles'], 0)
        self.assertEqual(repeated['verification_events'], 0)


if __name__ == '__main__':
    unittest.main()
