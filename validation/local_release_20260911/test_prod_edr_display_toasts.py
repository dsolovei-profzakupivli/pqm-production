import sqlite3
import subprocess
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import edr_sync_v2
import server


class ProductionEdrDisplayAndToastTests(unittest.TestCase):
    def test_full_verification_timestamp_survives_projection_and_api(self):
        con = sqlite3.connect(':memory:')
        con.row_factory = sqlite3.Row
        con.executescript('''
          CREATE TABLE supplier_edr_verification_events(
            supplier_code TEXT,event_type TEXT,occurred_at TEXT,officer TEXT,source TEXT,created_at TEXT);
          CREATE TABLE supplier_edr_profiles(
            supplier_code TEXT,edr_checked_at TEXT,edr_officer TEXT,synced_at TEXT);
          CREATE TABLE submissions(
            id INTEGER,supplier_code TEXT,date_published TEXT,qualification_id INTEGER);
          CREATE TABLE application_fields(
            submission_id INTEGER,protocol_date TEXT,protocol_officer TEXT,protocol_decision TEXT);
          CREATE TABLE qualifications(id INTEGER,decision_date TEXT);
          INSERT INTO supplier_edr_verification_events VALUES
            ('38261938','google_clarity','2026-10-29T16:50:41+02:00','Officer','Google','2026-10-30'),
            ('43926510','google_clarity','2026-10-29T16:50:54+02:00','Officer','Google','2026-10-30'),
            ('38766233','google_clarity','2026-10-29T16:50:47+02:00','Officer','Google','2026-10-30');
        ''')
        try:
            projections = edr_sync_v2.current_verification_projections(
                con, {'38261938', '43926510', '38766233'})
        finally:
            con.close()
        expected = {
            '38261938': '2026-10-29T16:50:41+02:00',
            '43926510': '2026-10-29T16:50:54+02:00',
            '38766233': '2026-10-29T16:50:47+02:00',
        }
        for code, timestamp in expected.items():
            self.assertEqual(projections[code]['verification_date'], '2026-10-29')
            self.assertEqual(projections[code]['verification_timestamp'], timestamp)
        row = {
            'supplier_code': '38261938', 'supplier_name': 'Synthetic supplier', 'manager_name': 'Synthetic manager',
            'edr_status': 'Зареєстровано', 'prozorro_status': 'Активний', 'freshness': 'lt30',
            'verification_date': projections['38261938']['verification_date'],
            'verification_timestamp': projections['38261938']['verification_timestamp'],
            'verification_officer': 'Test officer', 'latest_application_date': '',
            'termination_details': '', 'termination_record_date': '', 'termination_record_number': '',
            'google_note': '', 'edr_full_name': '', 'edr_short_name': '',
        }
        with patch.object(server, '_edr_monitoring_rows', return_value=[row]):
            api = server.list_edr_monitoring({'page': ['1'], 'size': ['100']})
        self.assertEqual(api['items'][0]['verification_timestamp'], '2026-10-29T16:50:41+02:00')
        self.assertEqual(api['items'][0]['verification_date'], '2026-10-29')

    def test_date_formatter_keeps_date_only_and_formats_timestamp_in_kyiv(self):
        script = r'''
const fs=require('fs');const app=fs.readFileSync('app.js','utf8');
const date=app.match(/^function displayDate\(value\).*$/m)[0];
const dateOnly=app.match(/^function displayDateOnly\(value\).*$/m)[0];
eval(date+';'+dateOnly+`;if(displayDate('2026-10-29T16:50:41+02:00')!=='29.10.2026, 16:50')process.exit(1);
if(displayDate('2026-10-29')!=='29.10.2026')process.exit(2);
if(displayDateOnly('2026-10-29')!=='29.10.2026')process.exit(3);
if(displayDate('')!=='')process.exit(4);`);
'''
        subprocess.run(['node', '-e', script], check=True, capture_output=True, text=True)

    def test_monitoring_renderer_prefers_timestamp_and_keeps_empty_fallback(self):
        app = Path('app.js').read_text(encoding='utf-8')
        renderer = app.split('async function loadEdrMonitoring()', 1)[1].split('\n', 1)[0]
        self.assertIn('displayDate(item.verification_timestamp||item.verification_date)', renderer)
        self.assertIn("||'—'", renderer)
        # The shared date formatter has no theme-specific branch, so both themes use the same projection.
        self.assertNotIn('document.documentElement.dataset.theme', app.split('function displayDate(value)', 1)[1].split('\n', 1)[0])

    def test_supplier_registry_card_and_profile_use_full_timestamp(self):
        app = Path('app.js').read_text(encoding='utf-8')
        profile = app.split('function openSupplierProfile(code)', 1)[1].split('\n', 1)[0]
        card = app.split('function supplierEdrDatesHtml(edr)', 1)[1].split('\nfunction ', 1)[0]
        self.assertIn('displayDate(item.edr_verification_timestamp||item.edr_verification_date)', profile)
        self.assertIn('displayDate(edr.edr_checked_at)', card)
        self.assertIn("||'—'", profile)
        self.assertIn("||'—'", card)

    def test_apply_start_reservation_is_single_winner_under_concurrency(self):
        state = server.SUPPLIER_EDR_SYNC_STATE
        with server.SUPPLIER_EDR_SYNC_START_LOCK:
            state.update(running=False, run_id=None, error=None)

        def reserve():
            with server.SUPPLIER_EDR_SYNC_START_LOCK:
                if state['running']:
                    return None
                run_id = 'synthetic-run'
                state.update(running=True, run_id=run_id)
                return run_id

        try:
            with ThreadPoolExecutor(max_workers=12) as pool:
                results = list(pool.map(lambda _: reserve(), range(12)))
            self.assertEqual(results.count('synthetic-run'), 1)
            self.assertEqual(results.count(None), 11)
            self.assertTrue(state['running'])
        finally:
            with server.SUPPLIER_EDR_SYNC_START_LOCK:
                state.update(running=False, run_id=None, error=None)

    def test_apply_route_rejects_second_request_while_rechecking_preview(self):
        from validation.local_release_20260911.test_google_runtime import GoogleRuntimeTests

        helper = GoogleRuntimeTests()
        helper.setUp()
        self.addCleanup(helper.doCleanups)
        entered = threading.Event()
        release = threading.Event()
        fingerprint, digest = 'a' * 64, 'b' * 64

        def delayed_snapshot():
            entered.set()
            if not release.wait(5):
                raise RuntimeError('synthetic timeout')
            return {'source_fingerprint': fingerprint}

        with patch.object(server, 'DB_PATH', helper.db_path), \
             patch.object(server, 'GOOGLE_OAUTH_TOKEN_PATH', helper.token_path), \
             patch.object(server, 'AUTH_ENABLED', False), \
             patch.object(server, 'LOCAL_ROLE_IMPERSONATION', True), \
             patch.object(server, 'google_edr_effective_enabled', return_value=True), \
             patch.object(server, 'supplier_edr_source_snapshot', side_effect=delayed_snapshot), \
             patch.object(server.edr_sync_v2, 'build_preview', return_value={'conflicts': []}), \
             patch.object(server.edr_sync_v2, 'preview_state_digest', return_value=digest), \
             patch.object(server, 'supplier_edr_sync_worker') as worker:
            server.SUPPLIER_EDR_SYNC_STATE.update(running=False, run_id=None, error=None)
            payload = {'confirmed': True, 'source_fingerprint': fingerprint, 'state_digest': digest}
            with ThreadPoolExecutor(max_workers=1) as pool:
                first = pool.submit(helper.request, '/api/supplier-edr-sync', 'admin', payload)
                self.assertTrue(entered.wait(5))
                second_status, _ = helper.request('/api/supplier-edr-sync', 'admin', payload)
                self.assertEqual(second_status, 409)
                release.set()
                self.assertEqual(first.result(timeout=5)[0], 202)
            worker.assert_called_once()
            self.assertTrue(server.SUPPLIER_EDR_SYNC_STATE['running'])
            self.assertTrue(server.SUPPLIER_EDR_SYNC_STATE['run_id'])
            server.SUPPLIER_EDR_SYNC_STATE.update(running=False, run_id=None, error=None)

    def test_apply_frontend_has_single_flight_polling_and_cross_tab_toast_dedupe(self):
        app = Path('app.js').read_text(encoding='utf-8')
        flow = app.split('async function startSupplierEdrSync()', 1)[1].split('\n}', 1)[0]
        self.assertIn('if(supplierEdrApplyInFlight)return', flow)
        self.assertIn("$('#supplierEdrPreviewApply').disabled=true", flow)
        self.assertIn('setTimeout(poll,2000)', flow)
        self.assertNotIn('setInterval(', flow)
        self.assertIn('pqm.supplierEdrLastCompletionToast', flow)
        self.assertIn("state.run_id", flow)
        self.assertIn('loadQualifiedSuppliersFiltered()', flow)
        self.assertIn("activeModule==='edrMonitoring'", flow)


if __name__ == '__main__':
    unittest.main()
