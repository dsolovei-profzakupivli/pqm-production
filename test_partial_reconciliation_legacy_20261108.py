import base64
import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import google_writer_execution as execution


REQUEST_ID = '592128d9837d4b71bbeb330ef8aabf4b'
FINGERPRINT = '816c6424279bff220878b0c4'
ACTOR = 'legacy-test-operator'
RECONCILIATION_ID = 'a' * 32
NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
PARTIAL_OPERATIONS = {6, 12, 14, 17, 25}


def digest(value):
    return base64.urlsafe_b64encode(hashlib.sha256(value).digest()).decode().rstrip('=')


def serial(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    parsed = parsed.astimezone(execution.KYIV).replace(tzinfo=None)
    return (parsed - datetime(1899, 12, 30)).total_seconds() / 86400


class LegacyAppendOnlyReconciliation20261108Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent, prefix='legacy-append-recon-')
        self.path = str(Path(self.temp.name) / 'sandbox.sqlite3')
        with closing(sqlite3.connect(self.path)) as con, con:
            execution.migrate(con)
        self.details = self._make_details()
        stored = execution.store_preview_plan(self.path, REQUEST_ID, ACTOR, self.details, now=NOW)
        claim = execution.claim_run(self.path, 'SANDBOX', REQUEST_ID, ACTOR, 'manual',
            manual_authorized=True, plan_scope='APPEND_ONLY',
            plan_digest=self.details['append_only_digest'], details_digest=stored['details_digest'], now=NOW)
        self.assertTrue(claim['claimed'])
        # The legacy run predates receipt-recovery auto-continuation metadata.
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("UPDATE google_writer_runs SET result_json=json_remove(result_json,'$.auto_continue_chunks') WHERE request_id=?",
                        (REQUEST_ID,))
        execution.hold_unknown_run(self.path, REQUEST_ID, attempted_chunk=0,
            digest=self.details['append_only_digest'], checkpoint_digest=None)

    def tearDown(self):
        self.temp.cleanup()

    def _make_details(self):
        appends = []
        for index in range(1, 327):
            tab = 'ФОП' if index <= 17 or index > 25 else 'ЮО'
            code = f'TESTCODE{index:04d}'
            verification_date = f'2026-11-{(index % 27) + 1:02d}T12:00:00+02:00'
            appends.append({
                'operation': 'APPEND', 'tab': tab, 'code': code,
                'cells': [
                    {'column': 'A', 'new_value': f'=FRESHNESS_{index:04d}', 'formula': True},
                    {'column': 'B', 'new_value': code, 'formula': False},
                    {'column': 'C', 'new_value': f'NAME_{index:04d}', 'formula': False},
                    {'column': 'D', 'new_value': 'PERSON', 'formula': False},
                    {'column': 'E', 'new_value': '', 'formula': False},
                    {'column': 'F', 'new_value': 'STATUS', 'formula': False},
                    {'column': 'H', 'new_value': '2026-11-08', 'formula': False},
                    {'column': 'I', 'new_value': verification_date, 'formula': False},
                    {'column': 'L', 'new_value': 'ACTIVE', 'formula': False},
                ],
            })
        return {
            'version': 1, 'environment': 'SANDBOX',
            'plan_digest': digest(b'legacy full plan'),
            'append_only_digest': digest(b'legacy append-only plan'),
            'counts': {'append': 326, 'update': 2, 'conflict': 2, 'error': 0},
            'appends': appends,
            'updates': [{'operation': 'UPDATE', 'cells': []}, {'operation': 'UPDATE', 'cells': []}],
            'conflicts': [{'reason': 'fixed'}, {'reason': 'fixed'}], 'errors': [],
        }

    def _prepare(self, reconciliation_id=RECONCILIATION_ID, fingerprint=FINGERPRINT):
        return execution.prepare_partial_reconciliation(
            self.path, 'SANDBOX', reconciliation_id, fingerprint, 'new-sandbox-admin', now=NOW)

    def _matrices(self, *, partial=False):
        tabs = {'ФОП': [], 'ЮО': []}
        for operation_number, item in enumerate(self.details['appends'][:25], 1):
            row = [''] * 15
            for cell in item['cells']:
                index = ord(cell['column']) - ord('A')
                value = cell['new_value']
                if cell['column'] in {'H', 'I'}:
                    value = serial(value if cell['column'] == 'I' else '2026-11-08T00:00:00+02:00')
                    if partial and cell['column'] == 'I' and operation_number in PARTIAL_OPERATIONS:
                        value += 1
                row[index] = value
            tabs[item['tab']].append(row)
        return tabs

    def _receipt(self, prepared):
        profile = execution.partial_reconciliation_profile(FINGERPRINT)
        return {
            'environment': 'SANDBOX', 'scriptId': execution.IDENTITIES['SANDBOX'][0],
            'spreadsheetId': execution.IDENTITIES['SANDBOX'][1], 'contract': execution.CONTRACT,
            'requestId': REQUEST_ID, 'status': 'RECONCILED_PARTIAL',
            'reconciliationId': RECONCILIATION_ID, 'requestFingerprint': FINGERPRINT,
            'evidenceDigest': prepared['evidence_digest'], 'digest': self.details['append_only_digest'],
            'counts': profile['result_counts'], **profile['receipt_fields'],
        }

    def test_v1_20_plus_5_evidence_is_retired_and_v2_25_plus_0_is_active(self):
        history = execution.PARTIAL_RECONCILIATION_PROFILE_HISTORY[FINGERPRINT + ':v1']
        self.assertEqual(history['status'], 'RETIRED_INVALID_DATE_NORMALIZATION_EVIDENCE')
        self.assertEqual(history['profile']['evidence'], execution._PARTIAL_RECONCILIATION_LEGACY_20261108_EVIDENCE)
        self.assertEqual(history['profile']['evidence']['audit']['full_matches'], 20)
        self.assertEqual(history['profile']['evidence']['audit']['partial_rows'], 5)
        self.assertEqual(history['profile']['evidence']['audit']['partial_columns'], {'I': 5})

        profile = execution.partial_reconciliation_profile(FINGERPRINT)
        self.assertEqual(profile['profile_version'], 2)
        self.assertEqual(profile['expected_i_mismatch_operations'], [])
        self.assertNotEqual(profile['evidence'], history['profile']['evidence'])
        self.assertEqual(execution.request_id_fingerprint(REQUEST_ID), FINGERPRINT)
        self.assertNotIn('source_digest', self.details)
        plan = execution.load_legacy_reconciliation_live_audit_plan(self.path, FINGERPRINT)
        self.assertNotIn('source_digest', plan['expected_rows'][0])
        audit = execution.audit_legacy_reconciliation_first_chunk(
            FINGERPRINT, plan['expected_rows'], self._matrices())
        self.assertEqual(audit, profile['evidence']['audit'])
        prepared = self._prepare()
        self.assertEqual(prepared['evidence'], profile['evidence'])
        self.assertEqual(prepared['evidence']['audit']['full_matches'], 25)
        self.assertEqual(prepared['evidence']['audit']['partial_rows'], 0)
        self.assertEqual(prepared['evidence']['audit']['partial_operation_numbers'], [])
        self.assertEqual(prepared['evidence']['audit']['partial_columns'], {'I': 0})
        self.assertEqual(prepared['evidence']['recovery_disposition'],
                         'FULL_FIRST_CHUNK_MATCH_NO_REAPPEND_NEW_PREVIEW_REQUIRED')
        self.assertEqual(prepared['evidence']['saved_preview_source_digest'], {
            'present': False, 'historical_schema': 'PRE_SOURCE_DIGEST', 'substitute_used': False})
        result = execution.finalize_partial_reconciliation(
            self.path, RECONCILIATION_ID, 'new-sandbox-admin', self._receipt(prepared), now=NOW)
        self.assertEqual(result['status'], 'RECONCILED_PARTIAL')
        with closing(sqlite3.connect(self.path)) as con:
            run = con.execute('SELECT status,result_json FROM google_writer_runs WHERE request_id=?',
                              (REQUEST_ID,)).fetchone()
            journal_count = con.execute('SELECT COUNT(*) FROM google_writer_chunk_journal WHERE run_id=?',
                                        (REQUEST_ID,)).fetchone()[0]
            evidence_raw = con.execute('SELECT evidence_json FROM google_writer_run_reconciliations WHERE request_id=?',
                                       (REQUEST_ID,)).fetchone()[0]
        self.assertEqual(run[0], 'partial')
        saved_result = json.loads(run[1])
        self.assertEqual(saved_result['status'], 'RECONCILED_PARTIAL')
        self.assertEqual(journal_count, 0)
        self.assertEqual(json.loads(evidence_raw), profile['evidence'])
        self.assertFalse(profile['receipt_fields']['checkpointPresent'])
        self.assertFalse(profile['receipt_fields']['resumeAuthorized'])
        self.assertEqual(profile['receipt_fields']['nextAction'], 'NEW_PREVIEW_REQUIRED')

    def test_only_fixed_legacy_profile_accepts_absent_source_digest(self):
        profile = execution.partial_reconciliation_profile(FINGERPRINT)
        self.assertTrue(profile['legacy_source_digest_absence'])
        self.assertFalse(execution._validate_saved_preview_source_digest(
            self.details, REQUEST_ID, profile))
        other_profile = {'expected_first_chunk_by_tab': {'ФОП': 17, 'ЮО': 8}, 'evidence': {}}
        with self.assertRaisesRegex(RuntimeError, 'source digest is unavailable'):
            execution._validate_saved_preview_source_digest(self.details, 'f' * 32, other_profile)
        new_profile = execution.partial_reconciliation_profile('30331b560493209210f1e507')
        self.assertFalse(new_profile.get('legacy_source_digest_absence', False))

    def test_v1_receipt_counts_cannot_finalize_the_active_v2_intent(self):
        prepared = self._prepare()
        receipt = self._receipt(prepared)
        legacy = execution.PARTIAL_RECONCILIATION_PROFILE_HISTORY[FINGERPRINT + ':v1']['profile']
        receipt['counts'] = legacy['result_counts']
        receipt.update(legacy['receipt_fields'])
        with self.assertRaisesRegex(PermissionError, 'counters do not match'):
            execution.finalize_partial_reconciliation(
                self.path, RECONCILIATION_ID, 'new-sandbox-admin', receipt, now=NOW)

    def test_legacy_preview_with_present_invalid_source_digest_is_rejected(self):
        with closing(sqlite3.connect(self.path)) as con, con:
            saved = con.execute(
                'SELECT details_json FROM google_writer_preview_plans WHERE request_id=?',
                (REQUEST_ID,),
            ).fetchone()[0]
            details = json.loads(saved)
            details['source_digest'] = 'malformed-but-preserved-for-test'
            details_raw = json.dumps(details, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
            details_digest = execution._preview_details_digest(details)
            con.execute(
                'UPDATE google_writer_preview_plans SET details_json=?,details_digest=? WHERE request_id=?',
                (details_raw, details_digest, REQUEST_ID),
            )
            state = json.loads(con.execute(
                'SELECT result_json FROM google_writer_runs WHERE request_id=?', (REQUEST_ID,)
            ).fetchone()[0])
            state['details_digest'] = details_digest
            con.execute('UPDATE google_writer_runs SET result_json=? WHERE request_id=?',
                        (json.dumps(state, sort_keys=True), REQUEST_ID))
        with self.assertRaisesRegex(RuntimeError, 'source-digest absence differs'):
            execution.load_legacy_reconciliation_live_audit_plan(self.path, FINGERPRINT)

    def test_changed_non_i_value_or_wrong_i_operation_fails_closed(self):
        matrices = self._matrices()
        matrices['ФОП'][0][2] = 'CHANGED'
        with self.assertRaises(RuntimeError):
            execution.audit_legacy_reconciliation_first_chunk(FINGERPRINT,
                self.details['appends'][:25], matrices)
        matrices = self._matrices()
        op = self.details['appends'][0]
        row = matrices[op['tab']][0]
        row[8] = serial(op['cells'][7]['new_value']) + 1
        with self.assertRaises(RuntimeError):
            execution.audit_legacy_reconciliation_first_chunk(FINGERPRINT,
                self.details['appends'][:25], matrices)

    def test_date_i_mismatch_and_other_cell_mismatch_still_fail_closed(self):
        matrices = self._matrices(partial=True)
        with self.assertRaisesRegex(RuntimeError, 'evidence changed'):
            execution.audit_legacy_reconciliation_first_chunk(
                FINGERPRINT, self.details['appends'][:25], matrices)

    def test_dmy_datetime_date_only_and_serial_comparison_preserve_precision(self):
        epoch = datetime(1899, 12, 30)
        expected_timestamp = datetime(2026, 11, 8, 9, 5, 10)
        timestamp_serial = (expected_timestamp - epoch).total_seconds() / 86400
        self.assertTrue(execution._legacy_sheet_value_matches(
            '08.11.2026 09:05:10', timestamp_serial, 'I'))
        self.assertFalse(execution._legacy_sheet_value_matches(
            '08.11.2026 09:05:10', timestamp_serial + 1 / 86400, 'I'))

        date_only_serial = (datetime(2026, 11, 8) - epoch).total_seconds() / 86400
        self.assertTrue(execution._legacy_sheet_value_matches(
            '08.11.2026', date_only_serial, 'I'))
        self.assertFalse(execution._legacy_sheet_value_matches(
            '08.11.2026', date_only_serial + 1 / 86400, 'I'))
        matrices = self._matrices()
        matrices['ФОП'][0][2] = 'CHANGED'
        with self.assertRaisesRegex(RuntimeError, 'evidence changed'):
            execution.audit_legacy_reconciliation_first_chunk(
                FINGERPRINT, self.details['appends'][:25], matrices)

    def test_missing_duplicate_wrong_tab_formula_and_protected_changes_fail_closed(self):
        for mutation in ('missing', 'duplicate', 'wrong_tab', 'formula', 'protected'):
            matrices = self._matrices()
            if mutation == 'missing':
                matrices['ФОП'].pop(0)
            elif mutation == 'duplicate':
                matrices['ФОП'].append(list(matrices['ФОП'][0]))
            elif mutation == 'wrong_tab':
                matrices['ФОП'][0], matrices['ЮО'][0] = matrices['ЮО'][0], matrices['ФОП'][0]
            elif mutation == 'formula':
                matrices['ФОП'][0][0] = '=WRONG'
            else:
                matrices['ФОП'][0][6] = 'UNEXPECTED'
            with self.subTest(mutation=mutation), self.assertRaises(RuntimeError):
                execution.audit_legacy_reconciliation_first_chunk(FINGERPRINT,
                    self.details['appends'][:25], matrices)

    def test_request_id_fingerprint_digest_checkpoint_and_other_profile_are_rejected(self):
        with self.assertRaises(PermissionError):
            execution.prepare_partial_reconciliation(self.path, 'SANDBOX', RECONCILIATION_ID,
                '30331b560493209210f1e507', 'new-sandbox-admin', now=NOW)
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("UPDATE google_writer_runs SET result_json=json_set(result_json,'$.attempted_checkpoint_digest',?) WHERE request_id=?",
                        (digest(b'not-null'), REQUEST_ID))
        with self.assertRaises(RuntimeError):
            self._prepare()
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("UPDATE google_writer_runs SET result_json=json_set(result_json,'$.attempted_checkpoint_digest',NULL) WHERE request_id=?",
                        (REQUEST_ID,))
            con.execute("UPDATE google_writer_preview_plans SET append_only_digest=? WHERE request_id=?",
                        (digest(b'changed digest'), REQUEST_ID))
        with self.assertRaises(RuntimeError):
            self._prepare()
        with closing(sqlite3.connect(self.path)) as con:
            count = con.execute('SELECT COUNT(*) FROM google_writer_run_reconciliations').fetchone()[0]
        self.assertEqual(count, 0)


if __name__ == '__main__':
    unittest.main()
