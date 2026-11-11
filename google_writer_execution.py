"""Isolated execution transport and fourth-job state. Never imports application startup."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import base64
import background_jobs
import hashlib
import hmac
import json
import math
import os
import re
import sqlite3
import stat
import tempfile
import threading
import urllib.request
import urllib.parse
import uuid
from zoneinfo import ZoneInfo
from pathlib import Path
from execution_digest import is_canonical_sha256_b64url
from execution_apply_contract import checkpoint_apply_enabled

KYIV = ZoneInfo('Europe/Kyiv')
JOB = 'google_writer'
CONTRACT = 'pqm-mirror-datetime-v1'
PREVIEW_PLAN_TTL_SECONDS = 300
PREVIEW_DETAIL_MAX_BYTES = 750_000
IDENTITIES = {
    'PROD': ('1TPR8GjoKeiWIlMJkXKpSM2X4rJrq8hIlFqMBn5kzyzurRbZPD_GZQOd6',
             '1rqghaEduW8Aer4ri36aysMurEdK2UH5laXKw_Oo1FKA', 'pqmProdExecution'),
    'SANDBOX': ('1Ht0jL2xQc3hsd6uWKui4uA6o1z2Oe_BAUbZq8HTXcw6C1Kpyi7JxNtmQ',
                '1lZtneKmCTvFcEL0erlJbegVzTTLNA-IKnjempn1G8Ww', 'pqmSandboxExecution'),
}
# Execution API requires every scope of the existing project, not just the writer.
PROJECT_SCOPES = frozenset({
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/script.external_request',
    'https://www.googleapis.com/auth/script.scriptapp',
    'https://www.googleapis.com/auth/script.container.ui',
    'https://www.googleapis.com/auth/userinfo.email',
})
_PARTIAL_RECONCILIATION_FIRST_FINGERPRINT = '9be34ff2df1e661346176eeb'
_PARTIAL_RECONCILIATION_SECOND_FINGERPRINT = '18a4aba10c1c13ab3bf59f56'
_PARTIAL_RECONCILIATION_FIRST_APPEND_ONLY_FINGERPRINT = '30331b560493209210f1e507'
_PARTIAL_RECONCILIATION_LEGACY_20261108_FINGERPRINT = '816c6424279bff220878b0c4'
_PARTIAL_RECONCILIATION_LEGACY_20261108_REQUEST_ID = '592128d9837d4b71bbeb330ef8aabf4b'
_PARTIAL_RECONCILIATION_FIRST_EVIDENCE = {
    'initial_plan': {'append': 451, 'update': 2, 'conflict': 2},
    'verified_append_rows': 50,
    'append_value_mismatches': 0,
    'duplicate_rows': 0,
    'routing_mismatches': 0,
    'protected_cell_mutations': 0,
    'date_only_format_exceptions': 12,
    'date_only_format_exceptions_approved': True,
    'updates_disposition': 'RECOMPUTE_WITH_NEW_PREVIEW',
}
_PARTIAL_RECONCILIATION_SECOND_EVIDENCE = {
    'initial_plan': {'append': 401, 'update': 2, 'conflict': 2},
    'verified_append_rows': 50,
    'verified_append_by_tab': {'ФОП': 46, 'ЮО': 4},
    'append_value_mismatches': 0,
    'duplicate_rows': 0,
    'routing_mismatches': 0,
    'protected_cell_mutations': 0,
    'formula_a_v1_2_matches': 50,
    'date_only_midnight_matches': 14,
    'blank_source_sheet_blank_rows': 36,
    'blank_sheet_source_date_state': {'empty_string': 36},
    'blank_sheet_source_precision_state': {'missing': 36},
    'required_diagnostic': 'pqm_sandbox_second_partial_apply_read_only_v3',
    'updates_disposition': 'UNVERIFIED_NO_HISTORIC_PLAN',
}
_PARTIAL_RECONCILIATION_FIRST_APPEND_ONLY_EVIDENCE = {
    'evidence_version': 1,
    'plan_scope': 'APPEND_ONLY',
    'initial_plan': {'append': 351},
    'attempted_chunk': 0,
    'checkpoint_present': False,
    'audit_type': 'READ_ONLY_SAVED_PREVIEW_AND_SHEETS',
    'audit': {
        'full_matches': 25,
        'partial_or_wrong_tab': 0,
        'missing': 0,
        'duplicates': 0,
        'saved_preview_binding': 'PASS',
        'writes_performed': 0,
    },
    'recovery_disposition': 'AUDIT_EVIDENCE_ONLY_NEW_PREVIEW_REQUIRED',
}
_PARTIAL_RECONCILIATION_LEGACY_20261108_EVIDENCE = {
    'evidence_version': 1,
    'request_id': _PARTIAL_RECONCILIATION_LEGACY_20261108_REQUEST_ID,
    'plan_scope': 'APPEND_ONLY',
    'initial_plan': {'append': 326, 'update': 2, 'conflict': 2},
    'attempted_chunk': 0,
    'checkpoint_present': False,
    'saved_preview_source_digest': {
        'present': False,
        'historical_schema': 'PRE_SOURCE_DIGEST',
        'substitute_used': False,
    },
    'audit_type': 'READ_ONLY_SAVED_PREVIEW_AND_LIVE_SHEETS',
    'audit': {
        'rows_found': 25,
        'full_matches': 20,
        'partial_rows': 5,
        'partial_operation_numbers': [6, 12, 14, 17, 25],
        'partial_columns': {'I': 5},
        'missing': 0,
        'duplicates': 0,
        'wrong_tab': 0,
        'formula_a_matches': 25,
        'protected_cell_mutations': 0,
        'saved_preview_binding': 'PASS',
        'writes_performed': 0,
    },
    'recovery_disposition': 'PARTIAL_ROWS_I_UNVERIFIED_NO_REAPPEND_NEW_PREVIEW_REQUIRED',
}
PARTIAL_RECONCILIATION_PROFILES = {
    _PARTIAL_RECONCILIATION_FIRST_FINGERPRINT: {
        'evidence': _PARTIAL_RECONCILIATION_FIRST_EVIDENCE,
        'result_counts': {
            'verified_append_rows': 50,
            'unverified_original_updates': 2,
            'accepted_date_only_formats': 12,
        },
    },
    _PARTIAL_RECONCILIATION_SECOND_FINGERPRINT: {
        'evidence': _PARTIAL_RECONCILIATION_SECOND_EVIDENCE,
        'result_counts': {
            'verified_append_rows': 50,
            'unverified_original_updates': 2,
            'verified_date_only_rows': 14,
            'blank_source_sheet_blank_rows': 36,
        },
    },
    _PARTIAL_RECONCILIATION_FIRST_APPEND_ONLY_FINGERPRINT: {
        'evidence': _PARTIAL_RECONCILIATION_FIRST_APPEND_ONLY_EVIDENCE,
        'result_counts': {
            'audit_confirmed_existing_append_rows': 25,
            'checkpoint_receipts': 0,
        },
        'receipt_fields': {
            'checkpointPresent': False,
            'resumeAuthorized': False,
            'nextAction': 'NEW_PREVIEW_REQUIRED',
        },
        'require_saved_append_only_preview': True,
        'expected_append_count': 351,
    },
    _PARTIAL_RECONCILIATION_LEGACY_20261108_FINGERPRINT: {
        'request_id': _PARTIAL_RECONCILIATION_LEGACY_20261108_REQUEST_ID,
        'evidence': _PARTIAL_RECONCILIATION_LEGACY_20261108_EVIDENCE,
        'result_counts': {
            'rows_found': 25,
            'fully_matching_rows': 20,
            'partial_rows': 5,
            'unverified_column_i_rows': 5,
            'checkpoint_receipts': 0,
        },
        'receipt_fields': {
            'checkpointPresent': False,
            'resumeAuthorized': False,
            'nextAction': 'NEW_PREVIEW_REQUIRED',
            'partialOperationNumbers': [6, 12, 14, 17, 25],
        },
        'require_saved_append_only_preview': True,
        'require_live_sheet_preflight': True,
        'expected_append_count': 326,
        'expected_plan_counts': {'append': 326, 'update': 2, 'conflict': 2, 'error': 0},
        'expected_first_chunk_by_tab': {'ФОП': 17, 'ЮО': 8},
        'expected_i_mismatch_operations': [6, 12, 14, 17, 25],
        'legacy_source_digest_absence': True,
    },
}
# Preserve the original 20+5 evidence as an audit record, but never select it
# for execution: its I-column mismatches came from a date-normalization defect
# in the first read-only auditor.
_PARTIAL_RECONCILIATION_LEGACY_20261108_PROFILE_V1 = PARTIAL_RECONCILIATION_PROFILES[
    _PARTIAL_RECONCILIATION_LEGACY_20261108_FINGERPRINT]
PARTIAL_RECONCILIATION_PROFILE_HISTORY = {
    _PARTIAL_RECONCILIATION_LEGACY_20261108_FINGERPRINT + ':v1': {
        'status': 'RETIRED_INVALID_DATE_NORMALIZATION_EVIDENCE',
        'profile': _PARTIAL_RECONCILIATION_LEGACY_20261108_PROFILE_V1,
    },
}
_PARTIAL_RECONCILIATION_LEGACY_20261108_V2_EVIDENCE = {
    'evidence_version': 2,
    'request_id': _PARTIAL_RECONCILIATION_LEGACY_20261108_REQUEST_ID,
    'plan_scope': 'APPEND_ONLY',
    'initial_plan': {'append': 326, 'update': 2, 'conflict': 2},
    'attempted_chunk': 0,
    'checkpoint_present': False,
    'saved_preview_source_digest': {
        'present': False,
        'historical_schema': 'PRE_SOURCE_DIGEST',
        'substitute_used': False,
    },
    'audit_type': 'READ_ONLY_SAVED_PREVIEW_AND_LIVE_SHEETS',
    'audit': {
        'rows_found': 25,
        'full_matches': 25,
        'partial_rows': 0,
        'partial_operation_numbers': [],
        'partial_columns': {'I': 0},
        'missing': 0,
        'duplicates': 0,
        'wrong_tab': 0,
        'formula_a_matches': 25,
        'protected_cell_mutations': 0,
        'saved_preview_binding': 'PASS',
        'writes_performed': 0,
    },
    'recovery_disposition': 'FULL_FIRST_CHUNK_MATCH_NO_REAPPEND_NEW_PREVIEW_REQUIRED',
}
_PARTIAL_RECONCILIATION_LEGACY_20261108_PROFILE_V2 = {
    'profile_version': 2,
    'request_id': _PARTIAL_RECONCILIATION_LEGACY_20261108_REQUEST_ID,
    'evidence': _PARTIAL_RECONCILIATION_LEGACY_20261108_V2_EVIDENCE,
    'result_counts': {
        'rows_found': 25,
        'fully_matching_rows': 25,
        'partial_rows': 0,
        'unverified_column_i_rows': 0,
        'checkpoint_receipts': 0,
    },
    'receipt_fields': {
        'checkpointPresent': False,
        'resumeAuthorized': False,
        'nextAction': 'NEW_PREVIEW_REQUIRED',
        'partialOperationNumbers': [],
    },
    'require_saved_append_only_preview': True,
    'require_live_sheet_preflight': True,
    'expected_append_count': 326,
    'expected_plan_counts': {'append': 326, 'update': 2, 'conflict': 2, 'error': 0},
    'expected_first_chunk_by_tab': {'ФОП': 17, 'ЮО': 8},
    'expected_i_mismatch_operations': [],
    'legacy_source_digest_absence': True,
}
# The active dispatch for this one fingerprint is additive v2. V1 remains
# available only through PARTIAL_RECONCILIATION_PROFILE_HISTORY above.
PARTIAL_RECONCILIATION_PROFILES[_PARTIAL_RECONCILIATION_LEGACY_20261108_FINGERPRINT] = (
    _PARTIAL_RECONCILIATION_LEGACY_20261108_PROFILE_V2)
# Backward-compatible aliases for the first reconciliation profile.
PARTIAL_RECONCILIATION_REQUEST_FINGERPRINT = _PARTIAL_RECONCILIATION_FIRST_FINGERPRINT
PARTIAL_RECONCILIATION_EVIDENCE = _PARTIAL_RECONCILIATION_FIRST_EVIDENCE


def partial_reconciliation_profile(request_fingerprint):
    """Return a fixed, Sandbox-only evidence profile; never accept caller-defined evidence."""
    return PARTIAL_RECONCILIATION_PROFILES.get(request_fingerprint)


def _validate_saved_preview_source_digest(details, request_id, profile):
    """Preserve the exact historical absence only for the pinned legacy request."""
    legacy_absence = profile.get('legacy_source_digest_absence') is True
    if legacy_absence:
        expected_evidence = {
            'present': False,
            'historical_schema': 'PRE_SOURCE_DIGEST',
            'substitute_used': False,
        }
        if (request_id != _PARTIAL_RECONCILIATION_LEGACY_20261108_REQUEST_ID or
                profile.get('evidence', {}).get('request_id') != request_id or
                profile.get('evidence', {}).get('saved_preview_source_digest') != expected_evidence):
            raise RuntimeError('Legacy source-digest absence profile identity rejected')
        if 'source_digest' in details:
            raise RuntimeError('Legacy Preview source-digest absence differs from fixed evidence')
        return False
    if profile.get('expected_first_chunk_by_tab'):
        if not is_canonical_sha256_b64url(details.get('source_digest')):
            raise RuntimeError('Saved APPEND_ONLY source digest is unavailable')
        return True
    return None


def _validate_partial_reconciliation_saved_run(con, request_id, profile):
    """Bind the special audit-only profile to the immutable saved APPEND_ONLY Preview."""
    run = con.execute('''SELECT environment,actor,trigger,status,result_json
                         FROM google_writer_runs WHERE request_id=?''', (request_id,)).fetchone()
    if (profile.get('request_id') and request_id != profile['request_id']):
        raise RuntimeError('APPEND_ONLY reconciliation request identity does not match its fixed profile')
    if (not run or run[0] != 'SANDBOX' or run[2] != 'manual' or
            run[3] != 'outcome_unknown'):
        raise RuntimeError('APPEND_ONLY reconciliation run identity or status changed')
    try:
        state = json.loads(run[4] or '{}')
    except (TypeError, json.JSONDecodeError):
        raise RuntimeError('APPEND_ONLY reconciliation run state is invalid') from None
    required_state = {
        'status': 'OUTCOME_UNKNOWN_HOLD_NO_RETRY',
        'outcome_unknown': True,
        'attempted_chunk': 0,
        'attempted_checkpoint_digest': None,
        'plan_scope': 'APPEND_ONLY',
    }
    # claim_run()/hold_unknown_run() persist operational progress metadata.
    # Accept only that closed set, and never let it imply checkpoint/resume.
    optional_state_keys = {'progress_state', 'last_progress_at',
        'last_confirmed_progress_at', 'planned_counts', 'auto_continue_chunks',
        'attempted_phase', 'safe_error'}
    expected_state_keys = set(required_state) | {'plan_digest', 'details_digest'}
    if (not isinstance(state, dict) or not expected_state_keys.issubset(state) or
            set(state) - expected_state_keys - optional_state_keys or
            any(state.get(key) != value for key, value in required_state.items())):
        raise RuntimeError('APPEND_ONLY reconciliation hold is not the expected no-checkpoint state')
    progress_state = state.get('progress_state')
    if progress_state is not None and progress_state not in {'preparing', 'remote_in_flight', 'verified'}:
        raise RuntimeError('APPEND_ONLY reconciliation progress state is invalid')
    for key in ('last_progress_at', 'last_confirmed_progress_at'):
        value = state.get(key)
        if value is not None:
            try:
                if not isinstance(value, str): raise ValueError
                datetime.fromisoformat(value.replace('Z', '+00:00'))
            except (TypeError, ValueError):
                raise RuntimeError('APPEND_ONLY reconciliation progress timestamp is invalid') from None
    planned = state.get('planned_counts')
    if planned is not None and (not isinstance(planned, dict) or
            set(planned) != {'append', 'update', 'conflict', 'error'} or
            any(type(value) is not int or value < 0 for value in planned.values())):
        raise RuntimeError('APPEND_ONLY reconciliation planned counts are invalid')
    if state.get('auto_continue_chunks') not in (None, False):
        raise RuntimeError('APPEND_ONLY reconciliation cannot authorize automatic continuation')
    if state.get('attempted_phase') not in (None, 'append'):
        raise RuntimeError('APPEND_ONLY reconciliation attempted phase is invalid')
    if state.get('safe_error') is not None and not isinstance(state.get('safe_error'), dict):
        raise RuntimeError('APPEND_ONLY reconciliation safe error metadata is invalid')
    snapshot = con.execute('''SELECT environment,actor,plan_digest,append_only_digest,
                                     details_digest,details_json
                              FROM google_writer_preview_plans WHERE request_id=?''',
                           (request_id,)).fetchone()
    if not snapshot or snapshot[0] != 'SANDBOX' or snapshot[1] != run[1]:
        raise RuntimeError('Saved APPEND_ONLY Preview identity is unavailable')
    if (not is_canonical_sha256_b64url(snapshot[2]) or
            not is_canonical_sha256_b64url(snapshot[3]) or
            not is_canonical_sha256_b64url(snapshot[4]) or
            state.get('plan_digest') != snapshot[3] or
            state.get('details_digest') != snapshot[4]):
        raise RuntimeError('Saved APPEND_ONLY Preview digest binding changed')
    try:
        details = json.loads(snapshot[5])
    except (TypeError, json.JSONDecodeError):
        raise RuntimeError('Saved APPEND_ONLY Preview details are invalid') from None
    expected_append_count = profile.get('expected_append_count', 351)
    expected_plan_counts = profile.get('expected_plan_counts')
    if (_preview_details_digest(details) != snapshot[4] or
            details.get('plan_digest') != snapshot[2] or
            details.get('append_only_digest') != snapshot[3] or
            details.get('environment') != 'SANDBOX' or details.get('version') != 1 or
            not isinstance(details.get('appends'), list) or len(details['appends']) != expected_append_count or
            not isinstance(details.get('counts'), dict) or details['counts'].get('append') != expected_append_count or
            (expected_plan_counts is not None and details['counts'] != expected_plan_counts) or
            (expected_plan_counts is not None and
             (not isinstance(details.get('updates'),list) or
              not isinstance(details.get('conflicts'),list) or
              not isinstance(details.get('errors'),list) or
              len(details['updates']) != expected_plan_counts['update'] or
              len(details.get('conflicts', [])) != expected_plan_counts['conflict'] or
              len(details['errors']) != expected_plan_counts['error'])) or
            any(not isinstance(item, dict) or item.get('operation') != 'APPEND'
                or not isinstance(item.get('cells'), list)
                or any(not isinstance(cell, dict) or cell.get('column') not in {'A','B','C','D','E','F','H','I','L'}
                       for cell in item['cells'])
                or not any(isinstance(cell, dict) and cell.get('column') == 'A' and cell.get('formula') is True
                           for cell in item['cells'])
                for item in details['appends'])):
        raise RuntimeError('Saved APPEND_ONLY Preview content does not match the fixed profile')
    if planned is not None and planned != {
            'append': len(details.get('appends', [])), 'update': 0,
            'conflict': len(details.get('conflicts', [])), 'error': len(details.get('errors', []))}:
        raise RuntimeError('APPEND_ONLY reconciliation planned counts differ from the saved Preview')
    if profile.get('expected_first_chunk_by_tab'):
        if any(item.get('tab') not in {'ФОП','ЮО'} or
               not isinstance(item.get('code'),str) or not item.get('code').strip()
               for item in details['appends']):
            raise RuntimeError('Saved APPEND_ONLY Preview identities do not match the fixed profile')
        _validate_saved_preview_source_digest(details, request_id, profile)
        by_tab = {tab: sum(item['tab'] == tab for item in details['appends'][:25])
                  for tab in ('ФОП','ЮО')}
        codes = [item['code'].strip() for item in details['appends']]
        if (by_tab != profile['expected_first_chunk_by_tab'] or
                len(set(codes)) != expected_append_count):
            raise RuntimeError('Saved APPEND_ONLY Preview composition does not match the fixed profile')
    return {'request_id': request_id, 'plan_digest': snapshot[2],
            'append_only_digest': snapshot[3], 'details_digest': snapshot[4],
            'append_count': len(details['appends']), 'details': details}


def load_legacy_reconciliation_live_audit_plan(path, request_fingerprint):
    """Read-only saved-plan loader for the fixed 2026-11-08 legacy profile."""
    profile = partial_reconciliation_profile(request_fingerprint)
    if not profile or not profile.get('require_live_sheet_preflight'):
        raise PermissionError('Live sheet audit is not enabled for this profile')
    expected_request_id = profile['request_id']
    if request_id_fingerprint(expected_request_id) != request_fingerprint:
        raise PermissionError('Legacy reconciliation fingerprint is invalid')
    uri = Path(path).resolve().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True, timeout=5)) as con:
        con.execute('PRAGMA query_only=ON')
        con.row_factory = sqlite3.Row
        run = con.execute('''SELECT request_id FROM google_writer_runs
                             WHERE environment='SANDBOX' AND status='outcome_unknown' ''').fetchall()
        if len(run) != 1 or run[0]['request_id'] != expected_request_id:
            raise RuntimeError('Legacy reconciliation run is no longer uniquely held')
        bound = _validate_partial_reconciliation_saved_run(con, expected_request_id, profile)
    return {
        'request_id': expected_request_id,
        'request_fingerprint': request_fingerprint,
        'plan_digest': bound['plan_digest'],
        'append_only_digest': bound['append_only_digest'],
        'details_digest': bound['details_digest'],
        'expected_rows': bound['details']['appends'][:25],
    }


def _legacy_sheet_date_serial(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        parsed = None
        for pattern in ('%d.%m.%Y %H:%M:%S', '%d.%m.%Y', '%Y-%m-%d'):
            try:
                parsed = datetime.strptime(value, pattern)
                break
            except ValueError:
                continue
        if parsed is None:
            return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(KYIV).replace(tzinfo=None)
    return (parsed - datetime(1899, 12, 30)).total_seconds() / 86400.0


def _legacy_sheet_value_matches(expected, actual, column):
    if expected is None:
        expected = ''
    if actual is None:
        actual = ''
    if column in {'H', 'I'}:
        serial = _legacy_sheet_date_serial(expected)
        if serial is not None and type(actual) in (int, float):
            return abs(serial - float(actual)) < 1e-7
    if isinstance(expected, bool):
        return isinstance(actual, bool) and expected is actual
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return type(actual) in (int, float) and not isinstance(actual, bool) and float(expected) == float(actual)
    return type(expected) is type(actual) and expected == actual


def audit_legacy_reconciliation_first_chunk(request_fingerprint, expected_rows, sheet_values):
    """Compare the first 25 saved APPENDs without exposing codes or cell values."""
    profile = partial_reconciliation_profile(request_fingerprint)
    if (not profile or not profile.get('require_live_sheet_preflight') or
            not isinstance(expected_rows, list) or len(expected_rows) != 25 or
            not isinstance(sheet_values, dict) or set(sheet_values) != {'ФОП', 'ЮО'}):
        raise ValueError('Legacy live audit input rejected')
    allowed_i = set(profile['expected_i_mismatch_operations'])
    code_locations = {}
    for tab in ('ФОП', 'ЮО'):
        matrix = sheet_values[tab]
        if not isinstance(matrix, list):
            raise ValueError('Legacy live audit sheet response rejected')
        for row_number, row in enumerate(matrix, 1):
            if not isinstance(row, list):
                raise ValueError('Legacy live audit row shape rejected')
            code = row[1] if len(row) > 1 else ''
            if isinstance(code, str) and code:
                code_locations.setdefault(code, []).append((tab, row_number, row))
    expected_codes = []
    missing = duplicates = wrong_tab = formula_matches = protected_mutations = 0
    full_matches = partial_rows = 0
    for operation_number, item in enumerate(expected_rows, 1):
        if (not isinstance(item, dict) or item.get('operation') != 'APPEND' or
                item.get('tab') not in {'ФОП', 'ЮО'} or
                not isinstance(item.get('code'), str) or not item['code'] or
                not isinstance(item.get('cells'), list)):
            raise ValueError('Legacy saved APPEND operation rejected')
        code = item['code']
        expected_codes.append(code)
        matches = code_locations.get(code, [])
        duplicates += max(0, len(matches) - 1)
        if not matches:
            missing += 1
            continue
        if len(matches) != 1 or matches[0][0] != item['tab']:
            wrong_tab += 1
            continue
        _, _, row = matches[0]
        row_matches = True
        i_mismatch = False
        for cell in item['cells']:
            if not isinstance(cell, dict) or cell.get('column') not in 'ABCDEFGHIJKLMNO':
                raise ValueError('Legacy saved APPEND cell rejected')
            column = cell['column']
            index = ord(column) - ord('A')
            expected = cell.get('new_value', '')
            actual = row[index] if index < len(row) else ''
            if column == 'A':
                if (cell.get('formula') is not True or not isinstance(expected, str) or
                        not expected.startswith('=') or actual != expected):
                    row_matches = False
                else:
                    formula_matches += 1
            elif column == 'I' and operation_number in allowed_i:
                if _legacy_sheet_value_matches(expected, actual, column):
                    # The fixed profile expects this column to differ. If it
                    # now matches, count the row as a full live match; the
                    # evidence equality check below will still stop
                    # reconciliation because the expected partial evidence
                    # has changed. Do not mislabel this as a tab mismatch.
                    pass
                else:
                    i_mismatch = True
            elif not _legacy_sheet_value_matches(expected, actual, column):
                row_matches = False
        # Columns G, J, K, M, N, O are outside the APPEND write contract.
        for column in (6, 9, 10, 12, 13, 14):
            if (column < len(row) and row[column] not in ('', None)):
                protected_mutations += 1
                row_matches = False
        if row_matches and i_mismatch and operation_number in allowed_i:
            partial_rows += 1
        elif row_matches and not i_mismatch:
            full_matches += 1
        else:
            wrong_tab += 1
    if len(set(expected_codes)) != 25:
        raise ValueError('Legacy saved APPEND identities are not unique')
    expected_tabs = {'ФОП': 17, 'ЮО': 8}
    if {tab: sum(item['tab'] == tab for item in expected_rows) for tab in expected_tabs} != expected_tabs:
        raise ValueError('Legacy saved APPEND routing changed')
    partial_operations = [i for i, item in enumerate(expected_rows, 1)
                          if item['tab'] in {'ФОП', 'ЮО'} and i in allowed_i]
    result = {
        'rows_found': 25 - missing,
        'full_matches': full_matches,
        'partial_rows': partial_rows,
        'partial_operation_numbers': partial_operations if partial_rows == 5 else [],
        'partial_columns': {'I': partial_rows},
        'missing': missing,
        'duplicates': duplicates,
        'wrong_tab': wrong_tab,
        'formula_a_matches': formula_matches,
        'protected_cell_mutations': protected_mutations,
        'saved_preview_binding': 'PASS',
        'writes_performed': 0,
    }
    if result != profile['evidence']['audit']:
        raise RuntimeError('Legacy live Google Sheets evidence changed; reconciliation stopped')
    return result


RENDER_SECRET_DIR = Path('/etc/secrets')
RENDER_SECRET_VERSION_POINTER = '..data'
RENDER_SECRET_VERSION_DIR_RE = re.compile(r'\.\.[0-9]{4}_[0-9]{2}_[0-9]{2}_[0-9]{2}_[0-9]{2}_[0-9]{2}\.[0-9]+')


def _credential_mode_allowed(mode, *, render_managed):
    """Private local files are 0600/0400; only Render's secret mount may be 0640."""
    permissions = stat.S_IMODE(mode)
    return permissions in (0o600, 0o400) or (render_managed and permissions == 0o640)


def _is_render_secret_path(path, secret_dir=None):
    secret_dir = Path(secret_dir or RENDER_SECRET_DIR)
    candidate = Path(os.path.abspath(os.fspath(path)))
    root = Path(os.path.abspath(os.fspath(secret_dir)))
    if candidate.parent != root or candidate.name in ('', '.', '..'):
        return False
    try:
        root_stat = os.lstat(root)
        if not stat.S_ISDIR(root_stat.st_mode) or stat.S_ISLNK(root_stat.st_mode):
            return False
        # Reject a symlinked parent component as well as a symlinked credential file.
        if root.parent != root and stat.S_ISLNK(os.lstat(root.parent).st_mode):
            return False
    except OSError:
        return False
    return True


def _open_regular_nofollow(path, flags):
    nofollow = getattr(os, 'O_NOFOLLOW', 0)
    cloexec = getattr(os, 'O_CLOEXEC', 0)
    fd = os.open(os.fspath(path), flags | nofollow | cloexec)
    try:
        opened = os.fstat(fd)
        named = os.lstat(path)
        if (not stat.S_ISREG(opened.st_mode) or stat.S_ISLNK(named.st_mode) or
                (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)):
            raise ValueError('Credential file identity rejected')
        return fd, opened
    except Exception:
        os.close(fd)
        raise


def _render_secret_mount_open(root):
    """Open the trusted, read-only Render Secret Files mount without following links."""
    nofollow = getattr(os, 'O_NOFOLLOW', 0)
    directory = getattr(os, 'O_DIRECTORY', 0)
    cloexec = getattr(os, 'O_CLOEXEC', 0)
    root_fd = os.open(os.fspath(root), os.O_RDONLY | directory | nofollow | cloexec)
    try:
        opened = os.fstat(root_fd)
        named = os.lstat(root)
        if (not stat.S_ISDIR(opened.st_mode) or stat.S_ISLNK(named.st_mode) or
                (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino) or
                not os.path.ismount(root) or
                not (os.statvfs(root).f_flag & getattr(os, 'ST_RDONLY', 1))):
            raise ValueError('Render Secret Files mount is not trusted')
        if root.parent != root and stat.S_ISLNK(os.lstat(root.parent).st_mode):
            raise ValueError('Render Secret Files parent is not trusted')
        return root_fd, opened
    except Exception:
        os.close(root_fd)
        raise


def _render_secret_target_parts(target, root):
    """Accept only a canonical target path contained beneath the mounted secret dir."""
    root_text = os.path.abspath(os.fspath(root))
    target_text = os.fspath(target)
    if os.path.isabs(target_text):
        if any(part in ('.', '..') for part in target_text.split(os.sep)):
            raise ValueError('Render Secret File target path is not canonical')
        normalized = os.path.normpath(target_text)
        try:
            if os.path.commonpath((root_text, normalized)) != root_text:
                raise ValueError('Render Secret File target escapes mount')
        except ValueError:
            raise ValueError('Render Secret File target escapes mount') from None
        relative = os.path.relpath(normalized, root_text)
    else:
        relative = target_text
    parts = relative.split(os.sep)
    if (not relative or relative in ('.', '..') or
            any(part in ('', '.', '..') for part in parts) or
            any('\\' in part or '\x00' in part for part in parts)):
        raise ValueError('Render Secret File target path is not canonical')
    return parts


def _open_render_secret_target(root_fd, parts):
    """Open each target component relative to pinned directory FDs, never following links."""
    nofollow = getattr(os, 'O_NOFOLLOW', 0)
    directory = getattr(os, 'O_DIRECTORY', 0)
    cloexec = getattr(os, 'O_CLOEXEC', 0)
    directory_fds = []
    current_fd = root_fd
    directory_ids = []
    try:
        for part in parts[:-1]:
            named = os.stat(part, dir_fd=current_fd, follow_symlinks=False)
            if not stat.S_ISDIR(named.st_mode) or stat.S_ISLNK(named.st_mode):
                raise ValueError('Nested Render Secret File symlink rejected')
            child_fd = os.open(part, os.O_RDONLY | directory | nofollow | cloexec,
                               dir_fd=current_fd)
            opened = os.fstat(child_fd)
            if (not stat.S_ISDIR(opened.st_mode) or
                    (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)):
                os.close(child_fd)
                raise ValueError('Render Secret File directory changed while opening')
            directory_fds.append(child_fd)
            directory_ids.append((opened.st_dev, opened.st_ino))
            current_fd = child_fd
        named = os.stat(parts[-1], dir_fd=current_fd, follow_symlinks=False)
        if not stat.S_ISREG(named.st_mode) or stat.S_ISLNK(named.st_mode):
            raise ValueError('Render Secret File target must be a regular file')
        target_fd = os.open(parts[-1], os.O_RDONLY | nofollow | cloexec, dir_fd=current_fd)
        opened = os.fstat(target_fd)
        if (not stat.S_ISREG(opened.st_mode) or
                (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)):
            os.close(target_fd)
            raise ValueError('Render Secret File target changed while opening')
        return target_fd, opened, directory_fds, tuple(directory_ids)
    except Exception:
        for fd in reversed(directory_fds):
            os.close(fd)
        raise


def _read_bounded_fd(fd, limit):
    chunks = []
    remaining = limit
    while remaining:
        chunk = os.read(fd, remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b''.join(chunks)


def _read_render_secret_symlink(path):
    """Read a direct secret link or Render's pinned ..data/versioned-dir projection."""
    root = Path(os.path.abspath(os.fspath(RENDER_SECRET_DIR)))
    candidate = Path(os.path.abspath(os.fspath(path)))
    if not _is_render_secret_path(candidate, root) or os.name == 'nt':
        raise ValueError('Credential symlink is not a Render Secret File')
    root_fd, root_before = _render_secret_mount_open(root)
    target_fd = None
    directory_fds = []
    try:
        link_name = candidate.name
        link_before = os.stat(link_name, dir_fd=root_fd, follow_symlinks=False)
        if not stat.S_ISLNK(link_before.st_mode):
            raise ValueError('Render Secret File link changed before reading')
        target_text = os.readlink(link_name, dir_fd=root_fd)
        version_pointer_before = None
        version_pointer_text = None
        versioned_target = target_text == f'{RENDER_SECRET_VERSION_POINTER}/{link_name}'
        if versioned_target:
            version_pointer_before = os.stat(RENDER_SECRET_VERSION_POINTER, dir_fd=root_fd,
                                             follow_symlinks=False)
            if not stat.S_ISLNK(version_pointer_before.st_mode):
                raise ValueError('Render Secret version pointer is not a symlink')
            version_pointer_text = os.readlink(RENDER_SECRET_VERSION_POINTER, dir_fd=root_fd)
            if (not RENDER_SECRET_VERSION_DIR_RE.fullmatch(version_pointer_text) or
                    '/' in version_pointer_text or '\\' in version_pointer_text):
                raise ValueError('Render Secret version pointer target rejected')
            parts = [version_pointer_text, link_name]
        else:
            parts = _render_secret_target_parts(target_text, root)
        target_fd, target_before, directory_fds, directory_ids = _open_render_secret_target(root_fd, parts)
        if (target_before.st_dev != root_before.st_dev or
                not _credential_mode_allowed(target_before.st_mode, render_managed=True)):
            raise ValueError('Render Secret File target permissions are not allowed')
        raw = _read_bounded_fd(target_fd, 65537)
        target_after = os.fstat(target_fd)
        if (len(raw) > 65536 or len(raw) != target_before.st_size or
                (target_before.st_dev, target_before.st_ino, target_before.st_size,
                 target_before.st_mtime_ns, target_before.st_ctime_ns) !=
                (target_after.st_dev, target_after.st_ino, target_after.st_size,
                 target_after.st_mtime_ns, target_after.st_ctime_ns)):
            raise ValueError('Render Secret File target changed while reading')
        link_after = os.stat(link_name, dir_fd=root_fd, follow_symlinks=False)
        if ((link_before.st_dev, link_before.st_ino) != (link_after.st_dev, link_after.st_ino) or
                not stat.S_ISLNK(link_after.st_mode) or
                os.readlink(link_name, dir_fd=root_fd) != target_text):
            raise ValueError('Render Secret File link changed while reading')
        if versioned_target:
            version_pointer_after = os.stat(RENDER_SECRET_VERSION_POINTER, dir_fd=root_fd,
                                            follow_symlinks=False)
            if ((version_pointer_before.st_dev, version_pointer_before.st_ino) !=
                    (version_pointer_after.st_dev, version_pointer_after.st_ino) or
                    not stat.S_ISLNK(version_pointer_after.st_mode) or
                    os.readlink(RENDER_SECRET_VERSION_POINTER, dir_fd=root_fd) != version_pointer_text):
                raise ValueError('Render Secret version pointer changed while reading')
        target_check_fd, target_check, check_fds, check_ids = _open_render_secret_target(root_fd, parts)
        try:
            if ((target_after.st_dev, target_after.st_ino) !=
                    (target_check.st_dev, target_check.st_ino) or directory_ids != check_ids):
                raise ValueError('Render Secret File target identity changed while reading')
        finally:
            os.close(target_check_fd)
            for fd in reversed(check_fds):
                os.close(fd)
        root_after = os.fstat(root_fd)
        root_named_after = os.lstat(root)
        if ((root_before.st_dev, root_before.st_ino) != (root_after.st_dev, root_after.st_ino) or
                (root_after.st_dev, root_after.st_ino) !=
                (root_named_after.st_dev, root_named_after.st_ino) or
                not os.path.ismount(root) or
                not (os.statvfs(root).f_flag & getattr(os, 'ST_RDONLY', 1))):
            raise ValueError('Render Secret Files mount changed while reading')
        return raw, target_before
    finally:
        if target_fd is not None:
            os.close(target_fd)
        for fd in reversed(directory_fds):
            os.close(fd)
        os.close(root_fd)


def _private_credential_copy(raw):
    """Atomically stage bytes in a process-private ephemeral directory (0600 file)."""
    temp_root = Path(tempfile.gettempdir())
    root_stat = os.lstat(temp_root)
    if not stat.S_ISDIR(root_stat.st_mode) or stat.S_ISLNK(root_stat.st_mode):
        raise ValueError('Private temporary root rejected')
    directory = Path(tempfile.mkdtemp(prefix='pqm-execution-oauth-', dir=temp_root))
    temporary = directory / 'credential.tmp'
    final = directory / 'credential.json'
    try:
        os.chmod(directory, 0o700)
        directory_stat = os.lstat(directory)
        if (not stat.S_ISDIR(directory_stat.st_mode) or stat.S_ISLNK(directory_stat.st_mode) or
                (hasattr(os, 'getuid') and directory_stat.st_uid != os.getuid()) or
                stat.S_IMODE(directory_stat.st_mode) != 0o700):
            raise ValueError('Private temporary directory rejected')
        fd = os.open(os.fspath(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0), 0o600)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, 'wb', closefd=False) as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temporary, final)
        fd, copied = _open_regular_nofollow(final, os.O_RDONLY)
        try:
            if (stat.S_IMODE(copied.st_mode) != 0o600 or
                    (hasattr(os, 'getuid') and copied.st_uid != os.getuid())):
                raise ValueError('Private temporary credential rejected')
            with os.fdopen(fd, 'rb', closefd=False) as stream:
                staged = stream.read(65537)
            if staged != raw or len(staged) > 65536:
                raise ValueError('Private credential copy verification failed')
            return staged
        finally:
            os.close(fd)
    finally:
        for path in (temporary, final):
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
        try:
            os.rmdir(directory)
        except OSError:
            # Never follow or recursively remove an unexpected replacement.
            pass


def _load_execution_credential(path):
    render_managed = _is_render_secret_path(path)
    if os.name != 'nt' and render_managed and stat.S_ISLNK(os.lstat(path).st_mode):
        raw, before = _read_render_secret_symlink(path)
        render_symlink = True
    else:
        fd, before = _open_regular_nofollow(path, os.O_RDONLY)
        try:
            if os.name != 'nt' and not _credential_mode_allowed(before.st_mode, render_managed=render_managed):
                raise ValueError('Credential permissions are not private')
            with os.fdopen(fd, 'rb', closefd=False) as stream:
                raw = stream.read(65537)
            after = os.fstat(fd)
            named_after = os.lstat(path)
            if (len(raw) > 65536 or len(raw) != before.st_size or
                    (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) !=
                    (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) or
                    stat.S_ISLNK(named_after.st_mode) or
                    (after.st_dev, after.st_ino) != (named_after.st_dev, named_after.st_ino)):
                raise ValueError('Credential file changed while reading')
        finally:
            os.close(fd)
        render_symlink = False
    if os.name != 'nt' and (render_symlink or stat.S_IMODE(before.st_mode) == 0o640):
        if not render_managed:
            raise ValueError('Group-readable credential is not a Render Secret File')
        raw = _private_credential_copy(raw)
    value = json.loads(raw.decode('utf-8'))
    if not isinstance(value, dict):
        raise ValueError('Credential JSON object required')
    return value


class ExecutionConfigurationError(ValueError):
    pass


class ExecutionPreflightError(ExecutionConfigurationError):
    """Known rejection before the Apps Script Execution API was called."""
    def __init__(self, message='Execution preflight rejected', *, safe_error=None):
        super().__init__(message)
        self.safe_error=safe_error if isinstance(safe_error,dict) else None


class ExecutionRemotePrewriteRejected(ExecutionConfigurationError):
    """Apps Script ran, but its safe stage diagnostic proves no Sheets write began."""
    def __init__(self, message='Apps Script rejected before Sheets write', *, safe_error=None):
        super().__init__(message)
        self.safe_error=safe_error if isinstance(safe_error,dict) else None


class ExecutionOutcomeUnknown(RuntimeError):
    """Never retry automatically: a transport error can follow committed writes."""
    def __init__(self, message='Execution outcome unknown; no automatic retry', *, safe_error=None):
        super().__init__(message)
        self.safe_error=safe_error if isinstance(safe_error,dict) else None


class AdminCloseFinalizationUnknown(RuntimeError):
    """Apps Script tombstone may exist while SQLite conservatively retains the hold."""


def _safe_apply_error(stage, exc):
    allowed={'Error','TypeError','RangeError','ReferenceError','ValueError','OperationalError','IntegrityError',
             'HTTPError','URLError','TimeoutError','ConnectionError'}
    name=type(exc).__name__
    if name not in allowed: name='Other'
    if isinstance(exc,sqlite3.Error): category='sqlite_persistence_error'
    elif isinstance(exc,ExecutionOutcomeUnknown): category='remote_outcome_unknown'
    elif isinstance(exc,urllib.error.HTTPError): category='execution_api_http_error'
    elif isinstance(exc,TimeoutError): category='transport_timeout'
    elif isinstance(exc,urllib.error.URLError): category='transport_error'
    else: category='apply_pipeline_error'
    remote=getattr(exc,'safe_error',None)
    if isinstance(remote,dict) and set(remote).issuperset({'stage','category','exception_type'}):
        result={'stage':remote['stage'],'category':remote['category'],
                'exception_type':remote['exception_type']}
        for key in ('http_status','primary_http_status','recovery_http_status',
                    'primary_stage','primary_category','recovery_stage','recovery_category'):
            value=remote.get(key)
            pattern=r'[a-z0-9_]{1,40}' if key.endswith('_category') else r'[a-z_]{1,40}'
            if (key.endswith('http_status') and type(value) is int and 100<=value<=599) or (
                    not key.endswith('http_status') and isinstance(value,str) and re.fullmatch(pattern,value)):
                result[key]=value
        return result
    result={'stage':str(stage)[:40],'category':category,'exception_type':name}
    if isinstance(exc,urllib.error.HTTPError) and type(exc.code) is int and 100<=exc.code<=599:
        result['http_status']=exc.code
    return result


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ExecutionOutcomeUnknown('Execution redirect rejected; reconcile before another Apply')


def transport_open(request, timeout, environment, deployment_id=None):
    """SANDBOX requests use the existing process guard, never a generic bypass."""
    sandbox = os.getenv('PQM_SANDBOX', '').lower() in ('1', 'true')
    if environment == 'SANDBOX' or sandbox:
        if environment != 'SANDBOX':
            raise ExecutionConfigurationError('Execution environment isolation rejected')
        import sandbox_runtime
        script, sheet, _ = IDENTITIES['SANDBOX']
        return sandbox_runtime.execution_open(request, timeout=timeout,
            environment=environment, script_id=script, spreadsheet_id=sheet,
            deployment_id=deployment_id or os.getenv('PQM_SANDBOX_EXECUTION_DEPLOYMENT_ID', ''))
    return urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout)


class DedicatedTokenProvider:
    """One environment-specific user OAuth credential. No authorization flow or service account."""
    def __init__(self, environment, path, project_id, *, opener=None, clock=None):
        self.environment, self.path, self.project_id = environment, path, project_id
        self.opener = opener or (lambda request, timeout: transport_open(request, timeout, self.environment))
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.cached = None

    def __call__(self, environment):
        if environment != self.environment or not self.path or not self.project_id:
            raise ExecutionConfigurationError('Dedicated execution credential identity absent')
        if self.cached and self.cached['expires_at'] - self.clock().timestamp() > 400:
            return self.cached
        try:
            value = _load_execution_credential(self.path)
            if (value.get('environment') != environment or value.get('gcp_project_id') != self.project_id or
                    value.get('type') == 'service_account' or
                    not PROJECT_SCOPES.issubset(set(value.get('scopes', [])))):
                raise ValueError('Credential attestation rejected')
            if float(value.get('expires_at', 0)) - self.clock().timestamp() > 400 and value.get('access_token'):
                self.cached = value
                return value
            if not all(value.get(k) for k in ('client_id','client_secret','refresh_token')):
                raise ValueError('Authorized refresh credential absent')
            payload = urllib.parse.urlencode({k:value[k] for k in ('client_id','client_secret','refresh_token')} |
                                             {'grant_type':'refresh_token'}).encode()
            request = urllib.request.Request('https://oauth2.googleapis.com/token',data=payload,method='POST',
                                             headers={'Content-Type':'application/x-www-form-urlencoded'})
            with self.opener(request,timeout=30) as response:
                result = json.loads(response.read(65536).decode())
            scopes = set(result.get('scope','').split()) if result.get('scope') else set(value['scopes'])
            if not result.get('access_token') or int(result.get('expires_in',0)) <= 400 or not PROJECT_SCOPES.issubset(scopes):
                raise ValueError('Refresh did not preserve required scopes/lifetime')
            self.cached = {**value,'access_token':result['access_token'],'scopes':sorted(scopes),
                           'expires_at':self.clock().timestamp()+int(result['expires_in'])}
            return self.cached
        except Exception:
            raise ExecutionConfigurationError('Dedicated execution OAuth credential unavailable') from None


class ExecutionClient:
    def __init__(self, environment, deployment_id, shared_secret, token_provider, *,
                 configured=False, opener=None, clock=None):
        self.environment = environment
        self.deployment_id = deployment_id
        self.shared_secret = shared_secret
        self.token_provider = token_provider
        self.configured = configured
        self.opener = opener or (lambda request, timeout: transport_open(request, timeout, self.environment, self.deployment_id))
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def validate(self):
        if (not self.configured or self.environment not in IDENTITIES or
                not re.fullmatch(r'[A-Za-z0-9_-]{20,256}', str(self.deployment_id or '')) or
                not isinstance(self.shared_secret, str) or len(self.shared_secret) < 32):
            raise ExecutionConfigurationError('Execution channel not independently configured and attested')

    def invoke(self, action, request_id, actor, *, trigger='manual', digest=None, plan_scope='ALL',
               manual_authorized=False, reconciliation_id=None,
               request_fingerprint=None, evidence=None, close_id=None,
               close_evidence_digest=None, reason_digest=None, chunk_index=0,
               expected_checkpoint_digest=None, chunk_id=None, chunk_digest=None, plan_id=None,
               chunk_phase=None, chunk_added_at=None, chunk_details_digest=None,
               prewrite_stage=None,target_identity_digest=None,target_identities=None,
               legacy_manifest_rows=None,legacy_manifest_projection_digest=None):
        manual_override = (manual_authorized is True and trigger == 'manual' and
                           isinstance(actor, str) and bool(actor.strip()))
        if background_jobs.disabled() and not manual_override:
            raise ExecutionConfigurationError('Background jobs disabled')
        self.validate()
        if action not in {'preview', 'apply', 'resume_check', 'recover_append_chunk', 'recover_apply_chunk', 'reconcile_partial', 'close_unknown_run','close_prewrite_failure','prewrite_close_preflight'} or trigger not in {'manual', 'scheduled'}:
            raise ValueError('Unsupported execution action')
        if not re.fullmatch(r'[0-9a-f]{32}', request_id) or not actor or len(actor) > 128:
            raise ValueError('Invalid execution identity')
        if action == 'apply' and not is_canonical_sha256_b64url(digest):
            raise ValueError('Reviewed Preview digest required')
        if action == 'apply' and (plan_scope not in {'ALL','APPEND_ONLY'} or
                (self.environment != 'SANDBOX' and plan_scope != 'ALL')):
            raise ValueError('Unsupported Apply scope for this environment')
        checkpoint_apply = action == 'apply' and checkpoint_apply_enabled(self.environment)
        if action == 'apply' and plan_scope == 'APPEND_ONLY' and not checkpoint_apply:
            raise ExecutionConfigurationError('APPEND_ONLY requires the Sandbox checkpoint protocol')
        checkpoint_protocol = (checkpoint_apply_enabled(self.environment) and action=='apply') or (
            self.environment=='SANDBOX' and checkpoint_apply_enabled(self.environment) and
            action in {'resume_check','recover_append_chunk','recover_apply_chunk'})
        if action == 'resume_check' and (not checkpoint_protocol or trigger!='manual' or
                manual_override is not True or plan_scope!='APPEND_ONLY' or
                not is_canonical_sha256_b64url(digest) or
                not is_canonical_sha256_b64url(expected_checkpoint_digest)):
            raise ValueError('Sandbox APPEND_ONLY resume preflight is invalid')
        if action=='recover_append_chunk' and (
                self.environment!='SANDBOX' or trigger!='manual' or manual_override is not True or
                plan_scope!='APPEND_ONLY' or not is_canonical_sha256_b64url(digest) or
                type(chunk_index) is not int or not 0<=chunk_index<=499 or
                not re.fullmatch(r'[0-9a-f]{32}',str(chunk_id or '')) or
                not is_canonical_sha256_b64url(chunk_digest) or
                not re.fullmatch(r'[0-9a-f]{32}',str(plan_id or ''))):
            raise ValueError('Sandbox APPEND_ONLY recovery preflight is invalid')
        if action=='recover_apply_chunk' and (
                self.environment!='SANDBOX' or trigger!='manual' or manual_override is not True or
                plan_scope!='ALL' or not is_canonical_sha256_b64url(digest) or
                type(chunk_index) is not int or not 0<=chunk_index<=499 or
                not re.fullmatch(r'[0-9a-f]{32}',str(chunk_id or '')) or
                not is_canonical_sha256_b64url(chunk_digest) or
                not re.fullmatch(r'[0-9a-f]{32}',str(plan_id or '')) or
                chunk_phase not in {'append','update'}):
            raise ValueError('Sandbox Apply chunk recovery preflight is invalid')
        if checkpoint_apply and (type(chunk_index) is not int or not 0 <= chunk_index <= 499):
            raise ValueError('Invalid Apply checkpoint index')
        if checkpoint_protocol and action == 'apply' and self.environment=='SANDBOX':
            if (type(chunk_index) is not int or not 0 <= chunk_index <= 499 or
                    (chunk_index == 0 and expected_checkpoint_digest is not None) or
                    (chunk_index > 0 and not is_canonical_sha256_b64url(expected_checkpoint_digest))):
                raise ValueError('Apply checkpoint receipt binding is required')
        chunk_binding=(chunk_id,chunk_digest,plan_id)
        if action in {'apply','recover_append_chunk','recover_apply_chunk','close_prewrite_failure','prewrite_close_preflight'} and self.environment=='SANDBOX' and any(value is not None for value in chunk_binding):
            if (not re.fullmatch(r'[0-9a-f]{32}',str(chunk_id or '')) or
                    not is_canonical_sha256_b64url(chunk_digest) or
                    not re.fullmatch(r'[0-9a-f]{32}',str(plan_id or ''))):
                raise ValueError('Durable Apply chunk binding is invalid')
            legacy_append=(action in {'recover_append_chunk','close_prewrite_failure','prewrite_close_preflight'} or (action=='apply' and plan_scope=='APPEND_ONLY'))
            if (legacy_append and (plan_scope!='APPEND_ONLY' or chunk_phase not in {None,'append'})) or (
                    not legacy_append and (chunk_phase not in {'append','update'} or
                        not is_canonical_sha256_b64url(chunk_details_digest) or
                        (chunk_phase=='append' and (not isinstance(chunk_added_at,str) or
                            not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}',chunk_added_at))) or
                        (chunk_phase=='update' and chunk_added_at is not None))):
                raise ValueError('Durable Apply chunk phase binding is invalid')
        elif any(value is not None for value in chunk_binding):
            raise ValueError('Durable chunk binding is Sandbox Apply only')
        evidence_digest = None
        reconciliation_profile = None
        if action == 'reconcile_partial':
            if trigger != 'manual' or manual_override is not True:
                raise ValueError('Partial reconciliation is manual-admin only')
            reconciliation_profile = partial_reconciliation_profile(request_fingerprint)
            if (not isinstance(reconciliation_id, str) or
                    not re.fullmatch(r'[0-9a-f]{32}', reconciliation_id) or
                    reconciliation_profile is None or
                    evidence != reconciliation_profile['evidence']):
                raise ValueError('Partial reconciliation evidence or identity rejected')
            evidence_raw = json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
            evidence_digest = base64.urlsafe_b64encode(
                hashlib.sha256(evidence_raw.encode('utf-8')).digest()).decode('ascii').rstrip('=')
        if action == 'close_unknown_run':
            if (self.environment != 'SANDBOX' or trigger != 'manual' or manual_override is not True or
                    plan_scope not in {'ALL','APPEND_ONLY'} or
                    not re.fullmatch(r'[0-9a-f]{32}',str(close_id or '')) or
                    not is_canonical_sha256_b64url(digest) or
                    not is_canonical_sha256_b64url(close_evidence_digest) or
                    not is_canonical_sha256_b64url(reason_digest)):
                raise ValueError('Administrative close identity or evidence rejected')
        if action in {'close_prewrite_failure','prewrite_close_preflight'}:
            if (self.environment!='SANDBOX' or trigger!='manual' or manual_override is not True or
                    plan_scope!='APPEND_ONLY' or
                    (action=='close_prewrite_failure' and not re.fullmatch(r'[0-9a-f]{32}',str(close_id or ''))) or
                    not is_canonical_sha256_b64url(digest) or
                    (action=='close_prewrite_failure' and (not is_canonical_sha256_b64url(close_evidence_digest) or
                     not is_canonical_sha256_b64url(reason_digest))) or
                    not is_canonical_sha256_b64url(target_identity_digest) or
                    prewrite_stage not in _PREWRITE_CLOSE_STAGES and prewrite_stage not in {
                        _PREWRITE_CLOSE_STAGE_SENTINEL,_LEGACY_PREWRITE_LIMIT_STAGE} or chunk_index!=0 or
                    not isinstance(target_identities,list) or not 1<=len(target_identities)<=APPEND_JOURNAL_PAGE_ROWS):
                raise ValueError('Sandbox prewrite close identity or evidence rejected')
            seen=set()
            for item in target_identities:
                if (not isinstance(item,dict) or set(item)!={'tab','code'} or item.get('tab') not in {'ФОП','ЮО'} or
                        not isinstance(item.get('code'),str) or not item['code'].strip() or item['code'].strip() in seen):
                    raise ValueError('Sandbox prewrite close target identities rejected')
                seen.add(item['code'].strip())
            if prewrite_stage==_LEGACY_PREWRITE_LIMIT_STAGE:
                if (request_id!=_LEGACY_PREWRITE_LIMIT_REQUEST_ID or not isinstance(legacy_manifest_rows,list) or
                        not 1<=len(legacy_manifest_rows)<=APPEND_JOURNAL_PAGE_ROWS or
                        not is_canonical_sha256_b64url(legacy_manifest_projection_digest)):
                    raise ValueError('Historical v1 manifest proof is not allowed for this run')
                projection=[{'tab':item.get('tab'),'row':item.get('row'),'code':item.get('code'),
                             'formulaA':item.get('formulaA')} for item in legacy_manifest_rows
                            if isinstance(item,dict)]
                if (len(projection)!=len(legacy_manifest_rows) or
                        any(set(item)!={'tab','row','code','formulaA'} for item in legacy_manifest_rows) or
                        _sha256_b64(_canonical_json(projection).encode('utf-8'))!=legacy_manifest_projection_digest or
                        [{'tab':item['tab'],'code':item['code']} for item in projection]!=target_identities or
                        any(type(item['row']) is not int or item['row']<2 or
                            not isinstance(item['formulaA'],str) or not item['formulaA'].startswith('=')
                            for item in projection)):
                    raise ValueError('Historical v1 manifest projection binding rejected')
            elif legacy_manifest_rows is not None or legacy_manifest_projection_digest is not None:
                raise ValueError('Legacy manifest projection is not valid for this prewrite stage')
        script, sheet, function = IDENTITIES[self.environment]
        api_function=function
        historical_profile_ids = {profile.get('request_id') for profile in PARTIAL_RECONCILIATION_PROFILES.values()
                                  if isinstance(profile, dict) and profile.get('request_id')}
        if (self.environment=='SANDBOX' and action=='apply' and
                checkpoint_apply_enabled(self.environment) and plan_scope=='ALL'):
            if request_id in historical_profile_ids:
                raise ValueError('Historical reconciliation request cannot use the new ALL-scope endpoint')
            if (not manual_override or not re.fullmatch(r'[0-9a-f]{32}',str(chunk_id or '')) or
                    not is_canonical_sha256_b64url(chunk_digest) or plan_id!=request_id or
                    not is_canonical_sha256_b64url(chunk_details_digest) or
                    chunk_phase not in {'append','update'} or
                    (chunk_phase=='append' and (not isinstance(chunk_added_at,str) or
                        not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}',chunk_added_at))) or
                    (chunk_phase=='update' and chunk_added_at is not None)):
                raise ValueError('Sandbox ALL-scope Apply requires its durable chunk binding')
            api_function='pqmSandboxAllScopeExecution20261109'
        elif action=='recover_apply_chunk':
            if request_id in historical_profile_ids:
                raise ValueError('Historical reconciliation request cannot use the new ALL-scope endpoint')
            api_function='pqmSandboxAllScopeExecution20261109'
        elif action in {'close_unknown_run','recover_append_chunk','close_prewrite_failure','prewrite_close_preflight'}:
            # The additive dispatcher checks the immutable closure tombstone
            # before delegating APPEND_ONLY recovery to the pinned legacy code.
            api_function='pqmSandboxAllScopeExecution20261109'
        issued = int(self.clock().timestamp())
        message = {'environment':self.environment, 'scriptId':script, 'spreadsheetId':sheet,
                   'contract':CONTRACT, 'action':action, 'requestId':request_id,
                   'actor':actor, 'trigger':trigger, 'issuedAt':issued, 'expiresAt':issued+300,
                   'expectedDigest':digest}
        if checkpoint_protocol:
            message['chunkIndex'] = chunk_index
            if self.environment=='SANDBOX': message['planScope'] = plan_scope
            if expected_checkpoint_digest is not None:
                message['expectedCheckpointDigest'] = expected_checkpoint_digest
        if action == 'close_unknown_run':
            message.update(closeId=close_id,closeEvidenceDigest=close_evidence_digest,
                           reasonDigest=reason_digest,planScope=plan_scope)
        if action in {'close_prewrite_failure','prewrite_close_preflight'}:
            message.update(closeId=close_id,closeEvidenceDigest=close_evidence_digest,
                reasonDigest=reason_digest,planScope='APPEND_ONLY',chunkIndex=0,
                prewriteStage=prewrite_stage,targetIdentityDigest=target_identity_digest,
                targetIdentities=target_identities)
            if prewrite_stage==_LEGACY_PREWRITE_LIMIT_STAGE:
                message.update(legacyManifestRows=legacy_manifest_rows,
                    legacyManifestProjectionDigest=legacy_manifest_projection_digest)
            if action=='prewrite_close_preflight':
                message.pop('closeId',None);message.pop('closeEvidenceDigest',None);message.pop('reasonDigest',None)
        if chunk_id is not None:
            message.update(chunkId=chunk_id,chunkDigest=chunk_digest,planId=plan_id)
            if chunk_phase is not None: message['chunkPhase']=chunk_phase
            if chunk_added_at is not None: message['chunkAddedAt']=chunk_added_at
            if chunk_details_digest is not None: message['chunkDetailsDigest']=chunk_details_digest
        if action == 'reconcile_partial':
            message.update(reconciliationId=reconciliation_id,
                           requestFingerprint=request_fingerprint,
                           evidence=evidence, evidenceDigest=evidence_digest)
        raw = json.dumps(message, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        signature = base64.urlsafe_b64encode(hmac.new(self.shared_secret.encode(), raw.encode(), hashlib.sha256).digest()).decode().rstrip('=')
        try:
            token = self.token_provider(self.environment)
        except Exception:
            if action in {'resume_check','prewrite_close_preflight'}:
                raise ExecutionPreflightError('Read-only execution credentials unavailable',
                    safe_error={'diagnostic_code':'OAUTH_TOKEN_SOURCE_FAILED'}) from None
            raise ExecutionPreflightError('Execution preflight rejected; Apps Script was not called') from None
        try:
            token_valid=(isinstance(token,dict) and token.get('environment')==self.environment and
                PROJECT_SCOPES.issubset(set(token.get('scopes',[]))) and
                float(token.get('expires_at',0))-self.clock().timestamp()>400 and
                bool(token.get('access_token')))
        except Exception:
            token_valid=False
        if not token_valid:
            if action in {'resume_check','prewrite_close_preflight'}:
                raise ExecutionPreflightError('Read-only execution credentials rejected',
                    safe_error={'diagnostic_code':'OAUTH_TOKEN_PREFLIGHT_REJECTED'})
            raise ExecutionPreflightError('Execution preflight rejected; Apps Script was not called')
        try:
            body = {'function':api_function, 'devMode':False,
                    'parameters':[{'payload':raw, 'signature':signature}]}
            # Current Google reference names this path parameter deploymentId.
            request = urllib.request.Request(
                'https://script.googleapis.com/v1/scripts/' + self.deployment_id + ':run',
                data=json.dumps(body).encode(), method='POST',
                headers={'Authorization':'Bearer '+token['access_token'], 'Content-Type':'application/json'})
        except Exception:
            if action in {'resume_check','prewrite_close_preflight'}:
                raise ExecutionPreflightError('Read-only Execution API request could not be built',
                    safe_error={'diagnostic_code':'EXECUTION_REQUEST_BUILD_FAILED'}) from None
            raise ExecutionPreflightError('Execution preflight rejected; Apps Script was not called') from None
        try:
            with self.opener(request, timeout=390) as response:
                data = json.loads(response.read(1024*1024).decode())
        except ExecutionConfigurationError:
            raise ExecutionPreflightError('Execution transport preflight rejected; Apps Script was not called') from None
        except urllib.error.HTTPError as exc:
            status_code=exc.code if type(exc.code) is int and 100<=exc.code<=599 else None
            if action in {'resume_check','prewrite_close_preflight'}:
                code=('EXECUTION_API_HTTP_'+str(status_code) if status_code else 'EXECUTION_API_HTTP_ERROR')
                raise ExecutionPreflightError('Read-only Execution API request was rejected',
                    safe_error={'diagnostic_code':code}) from None
            family='http_5xx' if status_code and status_code>=500 else 'http_4xx' if status_code and status_code>=400 else 'http_error'
            safe={'stage':'execution_api_response','category':family,'exception_type':'HTTPError'}
            if status_code:safe['http_status']=status_code
            raise ExecutionOutcomeUnknown('Execution API response was incomplete; recovery required',safe_error=safe) from None
        except urllib.error.URLError as exc:
            if action in {'resume_check','prewrite_close_preflight'}:
                reason=getattr(exc,'reason',None)
                code='EXECUTION_API_TRANSPORT_TIMEOUT' if isinstance(reason,TimeoutError) else 'EXECUTION_API_TRANSPORT_ERROR'
                raise ExecutionPreflightError('Read-only Execution API transport failed',
                    safe_error={'diagnostic_code':code}) from None
            reason=getattr(exc,'reason',None)
            category='transport_timeout' if isinstance(reason,TimeoutError) else 'transport_error'
            raise ExecutionOutcomeUnknown('Execution transport result was unknown; recovery required',
                safe_error={'stage':'execution_api_transport','category':category,'exception_type':'URLError'}) from None
        except TimeoutError:
            if action in {'resume_check','prewrite_close_preflight'}:
                raise ExecutionPreflightError('Read-only Execution API request timed out',
                    safe_error={'diagnostic_code':'EXECUTION_API_TRANSPORT_TIMEOUT'}) from None
            raise ExecutionOutcomeUnknown('Execution transport timed out; recovery required',
                safe_error={'stage':'execution_api_transport','category':'transport_timeout','exception_type':'TimeoutError'}) from None
        except OSError:
            if action in {'resume_check','prewrite_close_preflight'}:
                raise ExecutionPreflightError('Read-only Execution API transport failed',
                    safe_error={'diagnostic_code':'EXECUTION_API_TRANSPORT_ERROR'}) from None
            raise ExecutionOutcomeUnknown('Execution transport failed; no automatic retry; recovery required',
                safe_error={'stage':'execution_api_transport','category':'transport_error','exception_type':'OSError'}) from None
        except Exception:
            if action in {'resume_check','prewrite_close_preflight'}:
                raise ExecutionPreflightError('Read-only Execution API response was unreadable',
                    safe_error={'diagnostic_code':'EXECUTION_API_RESPONSE_UNREADABLE'}) from None
            raise ExecutionOutcomeUnknown('Execution outcome unknown; no automatic retry') from None
        if not isinstance(data,dict):
            if action in {'resume_check','prewrite_close_preflight'}:
                raise ExecutionPreflightError('Read-only Execution API returned an invalid response envelope',
                    safe_error={'diagnostic_code':'EXECUTION_API_RESPONSE_INVALID'})
            raise ExecutionOutcomeUnknown('Execution response was invalid; reconciliation required')
        if data.get('done') is not True or 'error' in data:
            if action in {'resume_check','prewrite_close_preflight'}:
                code=('APPS_SCRIPT_FUNCTION_ERROR' if isinstance(data,dict) and 'error' in data
                      else 'EXECUTION_API_RESPONSE_INCOMPLETE')
                raise ExecutionPreflightError('Read-only Apps Script execution did not return a result',
                    safe_error={'diagnostic_code':code})
            safe_error=None
            raw_error=data.get('error') if isinstance(data.get('error'),dict) else {}
            details=raw_error.get('details') if isinstance(raw_error,dict) else None
            candidates=details if isinstance(details,list) else [details]
            for item in candidates:
                message=item.get('errorMessage') if isinstance(item,dict) else None
                match=re.search(r'(?:^|\s)PQM_APPLY_DIAG:([a-z_]{1,40}):([A-Za-z]{1,24})',str(message or ''))
                if match:
                    safe_error={'stage':match.group(1),'category':'apps_script_stage_error',
                        'exception_type':match.group(2) if match.group(2) in {'Error','TypeError','RangeError','ReferenceError'} else 'Other'}
                    break
            if safe_error and safe_error['stage'] in {
                    'source_and_sheet_guard','chunk_selection','append_prewrite_guard','append_request_build',
                    'append_inflight_save','update_chunk_selection','update_inflight_save'}:
                raise ExecutionRemotePrewriteRejected('Apps Script ran but rejected before a Sheets write',
                                                       safe_error=safe_error)
            raise ExecutionOutcomeUnknown('Execution did not return a verified completion; reconciliation required',
                                          safe_error=safe_error)
        result = data.get('response', {}).get('result', {})
        if (not isinstance(result, dict) or result.get('environment') != self.environment or
                result.get('scriptId') != script or result.get('spreadsheetId') != sheet or
                result.get('contract') != CONTRACT or result.get('requestId') != request_id):
            if action in {'resume_check','prewrite_close_preflight'}:
                raise ExecutionPreflightError('Read-only Apps Script response identity rejected',
                    safe_error={'diagnostic_code':'EXECUTION_RESPONSE_IDENTITY_MISMATCH'})
            raise ExecutionOutcomeUnknown('Execution response identity mismatch; reconciliation required')
        if action=='prewrite_close_preflight':
            reason_codes=result.get('reasonCodes',[])
            contract_checks=(
                ('STATUS',result.get('status') not in {'READY','BLOCKED'}),
                ('DIGEST',result.get('digest')!=digest),
                ('SCOPE',result.get('planScope')!='APPEND_ONLY'),
                ('CHUNK_INDEX',result.get('chunkIndex')!=0),
                ('CHUNK_ID',result.get('chunkId')!=chunk_id),
                ('CHUNK_DIGEST',result.get('chunkDigest')!=chunk_digest),
                ('TARGET_IDENTITY',result.get('targetIdentityDigest')!=target_identity_digest),
                ('PREWRITE_STAGE',result.get('prewriteStage')!=prewrite_stage),
                ('TARGET_COUNT',result.get('targetCount')!=len(target_identities or [])),
                ('TARGET_CODE_MATCH_COUNT',type(result.get('targetCodeMatches')) is not int or
                    result['targetCodeMatches']<0),
                ('RUN_MARKER_MATCH_COUNT',type(result.get('runMarkerMatches')) is not int or
                    result['runMarkerMatches']<0),
                ('WRITE_AHEAD_BYTES',type(result.get('writeAheadBytes')) is not int or
                    result['writeAheadBytes']<0),
                ('CHECKPOINT_MAX_BYTES',type(result.get('checkpointMaxBytes')) is not int or
                    result['checkpointMaxBytes']<0),
                ('REASON_CODES',not isinstance(reason_codes,list) or
                    any(code not in _PREWRITE_PREFLIGHT_REASON_CODES for code in reason_codes)),
                ('READ_ONLY_MARKER',result.get('readOnly') is not True),
                ('READY_EVIDENCE',result.get('status')=='READY' and
                    (reason_codes or result.get('targetCodeMatches')!=0 or result.get('runMarkerMatches')!=0 or
                     not is_canonical_sha256_b64url(result.get('runRecordDigest')))),
            )
            invalid_contract=next((field for field,invalid in contract_checks if invalid),None)
            if invalid_contract:
                raise ExecutionPreflightError('Apps Script read-only prewrite evidence was incomplete',
                    safe_error={'diagnostic_code':'APPS_SCRIPT_PREFLIGHT_'+invalid_contract})
            if prewrite_stage==_LEGACY_PREWRITE_LIMIT_STAGE and result.get('status')=='READY' and (
                    result.get('proofType')!='LEGACY_V1_WRITEAHEAD_OVERSIZE' or
                    result['writeAheadBytes']<=_LEGACY_PREWRITE_LIMIT_BYTES or
                    result['checkpointMaxBytes']!=_LEGACY_PREWRITE_LIMIT_BYTES or
                    result.get('legacyManifestProjectionDigest')!=legacy_manifest_projection_digest):
                raise ExecutionPreflightError('Historical write-ahead size proof was incomplete',
                    safe_error={'diagnostic_code':'APPS_SCRIPT_LEGACY_SIZE_PROOF_INVALID'})
            if result.get('status')=='READY' and result.get('proofType')!='APPS_SCRIPT_LAST_ERROR' and prewrite_stage!=_LEGACY_PREWRITE_LIMIT_STAGE:
                raise ExecutionPreflightError('Apps Script prewrite reason is not verified',
                    safe_error={'diagnostic_code':'APPS_SCRIPT_PREWRITE_STAGE_UNVERIFIED'})
            return {'status':result['status'],'request_id_matches':True,'plan_binding':'PASS',
                'chunk_binding':'PASS','manifest_binding':'PASS','write_ahead_bytes':result['writeAheadBytes'],
                'checkpoint_max_bytes':result['checkpointMaxBytes'],'target_count':result['targetCount'],
                'target_code_matches':result['targetCodeMatches'],'run_marker_matches':result['runMarkerMatches'],
                'reason_codes':reason_codes,'read_only':True,'sqlite_writes':0,'sheets_writes':0,
                'properties_writes':0}
        if action == 'preview' and not is_canonical_sha256_b64url(result.get('digest')):
            raise ExecutionOutcomeUnknown('Invalid Preview receipt')
        plan_details = None
        if action == 'preview' and self.environment == 'SANDBOX':
            plan_details = result.get('planDetails')
            if (not isinstance(plan_details,dict) or plan_details.get('version') != 1 or
                    plan_details.get('environment') != 'SANDBOX' or
                    plan_details.get('plan_digest') != result.get('digest') or
                    not is_canonical_sha256_b64url(plan_details.get('append_only_digest')) or
                    not isinstance(plan_details.get('appends'),list) or
                    not isinstance(plan_details.get('updates'),list) or
                    not isinstance(plan_details.get('conflicts'),list) or
                    not isinstance(plan_details.get('errors'),list) or
                    not isinstance(plan_details.get('counts'),dict)):
                raise ExecutionOutcomeUnknown('Invalid Sandbox Preview detail receipt')
            if (len(plan_details['appends']) != int(result.get('counts',{}).get('append',-1)) or
                    len(plan_details['updates']) != int(result.get('counts',{}).get('update',-1)) or
                    len(plan_details['conflicts']) != int(result.get('counts',{}).get('conflict',-1)) or
                    len(plan_details['errors']) != int(result.get('counts',{}).get('error',-1)) or
                    any(plan_details['counts'].get(key)!=result.get('counts',{}).get(key)
                        for key in ('append','update','conflict','error'))):
                raise ExecutionOutcomeUnknown('Sandbox Preview detail counts mismatch')
            if len(json.dumps(plan_details,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')) > 750_000:
                raise ExecutionOutcomeUnknown('Sandbox Preview detail payload exceeds safe bound')
        if action=='recover_apply_chunk':
            if (result.get('digest')!=digest or result.get('planScope')!=plan_scope or
                    result.get('chunkIndex')!=chunk_index or
                    result.get('chunkId')!=chunk_id or result.get('chunkDigest')!=chunk_digest or
                    result.get('planId')!=plan_id or result.get('phase')!=chunk_phase or
                    result.get('status') not in {'CHUNK_RECOVERED','CHUNK_NOT_APPLIED','CHUNK_AMBIGUOUS'}):
                raise ExecutionOutcomeUnknown('Invalid read-only Apply recovery receipt')
            if result.get('status')=='CHUNK_RECOVERED' and (
                    not is_canonical_sha256_b64url(result.get('checkpointDigest')) or
                    result.get('nextChunk')!=chunk_index+1 or type(result.get('more')) is not bool):
                raise ExecutionOutcomeUnknown('Invalid recovered Apply checkpoint receipt')
            if result.get('status')=='CHUNK_NOT_APPLIED' and result.get('nextChunk')!=chunk_index:
                raise ExecutionOutcomeUnknown('Invalid not-applied recovery receipt')
        elif action in {'apply'} and checkpoint_apply_enabled(self.environment):
            if (result.get('digest') != digest or type(result.get('chunkIndex')) is not int or
                    result.get('chunkIndex') != chunk_index or
                    type(result.get('nextChunk')) is not int or result.get('nextChunk') != chunk_index + 1 or
                    type(result.get('more')) is not bool or
                    (self.environment=='SANDBOX' and not is_canonical_sha256_b64url(result.get('checkpointDigest'))) or
                    result.get('phase') not in {'append','update'} or
                    result.get('status') not in {'APPLY_CHUNK_VERIFIED','COMPLETE','COMPLETE_WITH_CONFLICTS'} or
                    (self.environment == 'SANDBOX' and result.get('planScope') != plan_scope) or
                    (result.get('status') == 'APPLY_CHUNK_VERIFIED') != result.get('more')):
                raise ExecutionOutcomeUnknown('Invalid Apply checkpoint receipt')
            if chunk_id is not None and any(result.get(key)!=value for key,value in {
                    'chunkId':chunk_id,'chunkDigest':chunk_digest,'planId':plan_id}.items()):
                raise ExecutionOutcomeUnknown('Apply chunk journal receipt mismatch')
            if chunk_id is not None and chunk_phase is not None and result.get('phase')!=chunk_phase:
                raise ExecutionOutcomeUnknown('Apply chunk phase receipt mismatch')
        resume_details = None
        if action == 'resume_check':
            resume_details = result.get('planDetails')
            counts = result.get('counts', {})
            if (result.get('status')!='RESUME_READY' or result.get('digest')!=digest or
                    result.get('planScope')!='APPEND_ONLY' or result.get('chunkIndex')!=chunk_index or
                    result.get('nextChunk')!=chunk_index or
                    result.get('checkpointDigest')!=expected_checkpoint_digest or
                    not isinstance(resume_details,dict) or resume_details.get('version')!=1 or
                    resume_details.get('environment')!='SANDBOX' or
                    resume_details.get('plan_digest')!=digest or
                    not is_canonical_sha256_b64url(resume_details.get('remaining_plan_digest')) or
                    not isinstance(resume_details.get('appends'),list) or not resume_details['appends'] or
                    resume_details.get('updates')!=[] or
                    not isinstance(resume_details.get('conflicts'),list) or
                    not isinstance(resume_details.get('errors'),list) or
                    counts.get('append')!=len(resume_details['appends']) or counts.get('update')!=0 or
                    counts.get('append')<=0):
                raise ExecutionPreflightError('Read-only checkpoint receipt rejected; no write was requested')
        if action == 'reconcile_partial' and (
                result.get('status') != 'RECONCILED_PARTIAL' or
                result.get('reconciliationId') != reconciliation_id or
                result.get('requestFingerprint') != request_fingerprint or
                result.get('evidenceDigest') != evidence_digest or
                not is_canonical_sha256_b64url(result.get('digest'))):
            raise ExecutionOutcomeUnknown('Invalid partial reconciliation receipt')
        if action == 'close_unknown_run' and (
                result.get('status') != 'ADMIN_CLOSED_UNKNOWN' or
                result.get('closeId') != close_id or
                result.get('planScope') != plan_scope or
                result.get('disposition') != 'OUTCOME_UNKNOWN_NOT_CONFIRMED' or
                result.get('evidenceDigest') != close_evidence_digest or
                result.get('reasonDigest') != reason_digest or
                result.get('actor') != actor or
                not is_canonical_sha256_b64url(result.get('runRecordDigest')) or
                not isinstance(result.get('closedAt'),str) or
                not is_canonical_sha256_b64url(result.get('digest')) or
                result.get('digest') != _close_receipt_digest(result)):
            raise ExecutionOutcomeUnknown('Apps Script administrative close receipt is invalid')
        prewrite_receipt_stage_ok=(result.get('prewriteStage') in _PREWRITE_CLOSE_STAGES
            if action=='close_prewrite_failure' and prewrite_stage==_PREWRITE_CLOSE_STAGE_SENTINEL
            else (result.get('prewriteStage')=='append_inflight_save'
                  if action=='close_prewrite_failure' and prewrite_stage==_LEGACY_PREWRITE_LIMIT_STAGE
                  else result.get('prewriteStage')==prewrite_stage))
        prewrite_proof_ok=(
            result.get('proofType')=='LEGACY_V1_WRITEAHEAD_OVERSIZE' and
            type(result.get('writeAheadBytes')) is int and result['writeAheadBytes']>_LEGACY_PREWRITE_LIMIT_BYTES and
            result.get('checkpointMaxBytes')==_LEGACY_PREWRITE_LIMIT_BYTES and
            result.get('legacyManifestProjectionDigest')==legacy_manifest_projection_digest
            if action=='close_prewrite_failure' and prewrite_stage==_LEGACY_PREWRITE_LIMIT_STAGE else
            result.get('proofType')=='APPS_SCRIPT_LAST_ERROR' and result.get('writeAheadBytes')==0 and
            result.get('checkpointMaxBytes')==0 and result.get('legacyManifestProjectionDigest')==''
            if action=='close_prewrite_failure' else True)
        if action=='close_prewrite_failure' and (
                result.get('status')!='ADMIN_CLOSED_PREWRITE_NO_WRITE' or
                result.get('requestId')!=request_id or result.get('closeId')!=close_id or
                result.get('planScope')!='APPEND_ONLY' or
                result.get('disposition')!='PREWRITE_FAILURE_CONFIRMED_NO_SHEET_WRITE' or
                result.get('evidenceDigest')!=close_evidence_digest or
                result.get('reasonDigest')!=reason_digest or result.get('chunkId')!=chunk_id or
                result.get('chunkDigest')!=chunk_digest or result.get('chunkIndex')!=0 or
                result.get('targetIdentityDigest')!=target_identity_digest or
                not prewrite_receipt_stage_ok or not prewrite_proof_ok or result.get('actor')!=actor or
                not is_canonical_sha256_b64url(result.get('runRecordDigest')) or
                not isinstance(result.get('closedAt'),str) or
                not is_canonical_sha256_b64url(result.get('digest')) or
                result.get('digest')!=_prewrite_close_receipt_digest(result)):
            raise ExecutionOutcomeUnknown('Apps Script prewrite close receipt is invalid')
        if action=='recover_append_chunk' and (
                result.get('status') not in {'CHUNK_RECOVERED','CHUNK_NOT_APPLIED'} or
                result.get('digest')!=digest or result.get('planScope')!='APPEND_ONLY' or
                result.get('chunkIndex')!=chunk_index or result.get('chunkId')!=chunk_id or
                result.get('chunkDigest')!=chunk_digest or result.get('planId')!=plan_id or
                type(result.get('nextChunk')) is not int or
                (result.get('status')=='CHUNK_RECOVERED' and
                 (result['nextChunk']!=chunk_index+1 or not is_canonical_sha256_b64url(result.get('checkpointDigest')))) or
                (result.get('status')=='CHUNK_NOT_APPLIED' and result['nextChunk']!=chunk_index)):
            raise ExecutionOutcomeUnknown('Invalid APPEND_ONLY chunk recovery receipt')
        if action == 'reconcile_partial' and reconciliation_profile.get('receipt_fields'):
            if (result.get('counts') != reconciliation_profile['result_counts'] or
                    any(result.get(key) != value for key, value in reconciliation_profile['receipt_fields'].items())):
                raise ExecutionOutcomeUnknown('Invalid audit-only reconciliation disposition receipt')
        # Return only technical receipts/counters; never remote errors, stack traces or secrets.
        safe = {key:result.get(key) for key in ('environment','scriptId','spreadsheetId','contract','requestId','status','digest')}
        counters = result.get('counts', {})
        if not isinstance(counters, dict) or any(type(v) not in (int,float) or not math.isfinite(v) or v < 0 or v != int(v) for v in counters.values()):
            raise ExecutionOutcomeUnknown('Invalid execution counters')
        safe['counts'] = {k:int(v) for k,v in counters.items() if k in {
            'append','update','conflict','error','remaining_safe','batches','skipped',
            'audit_confirmed_existing_append_rows','checkpoint_receipts','rows_found',
            'fully_matching_rows','partial_rows','unverified_column_i_rows'}}
        if action == 'apply' and checkpoint_apply_enabled(self.environment):
            safe.update(chunkIndex=chunk_index,nextChunk=result['nextChunk'],more=result['more'],phase=result.get('phase'))
            if self.environment == 'SANDBOX':
                safe['planScope'] = plan_scope
                safe['checkpointDigest'] = result['checkpointDigest']
            if chunk_id is not None:
                safe.update(chunkId=chunk_id,chunkDigest=chunk_digest,planId=plan_id)
        if action == 'resume_check':
            safe.update(planScope='APPEND_ONLY',chunkIndex=chunk_index,nextChunk=result['nextChunk'],
                        checkpointDigest=result['checkpointDigest'],planDetails=resume_details)
        if action=='recover_append_chunk':
            safe.update(planScope='APPEND_ONLY',chunkIndex=chunk_index,nextChunk=result['nextChunk'],
                        chunkId=chunk_id,chunkDigest=chunk_digest,planId=plan_id)
        if action=='close_unknown_run':
            safe.update(closeId=close_id,planScope=plan_scope,
                        disposition=result['disposition'],evidenceDigest=close_evidence_digest,
                        reasonDigest=reason_digest,runRecordDigest=result['runRecordDigest'],
                        closedAt=result['closedAt'],actor=actor,idempotent=bool(result.get('idempotent')))
            if result.get('status')=='CHUNK_RECOVERED': safe['checkpointDigest']=result['checkpointDigest']
        if action=='close_prewrite_failure':
            safe.update(closeId=close_id,planScope='APPEND_ONLY',disposition=result['disposition'],
                evidenceDigest=close_evidence_digest,reasonDigest=reason_digest,chunkId=chunk_id,
                chunkDigest=chunk_digest,targetIdentityDigest=target_identity_digest,
                prewriteStage=prewrite_stage,runRecordDigest=result['runRecordDigest'],
                closedAt=result['closedAt'],actor=actor,idempotent=bool(result.get('idempotent')),
                proofType=result['proofType'],writeAheadBytes=result['writeAheadBytes'],
                checkpointMaxBytes=result['checkpointMaxBytes'],
                legacyManifestProjectionDigest=result['legacyManifestProjectionDigest'])
        if action=='recover_apply_chunk':
            safe.update(planScope='ALL',chunkIndex=chunk_index,nextChunk=result['nextChunk'],
                more=result.get('more'),phase=chunk_phase,chunkId=chunk_id,
                chunkDigest=chunk_digest,planId=plan_id)
            if result.get('status')=='CHUNK_RECOVERED': safe['checkpointDigest']=result['checkpointDigest']
        if action == 'preview' and plan_details is not None:
            safe['planDetails'] = plan_details
        if action == 'reconcile_partial':
            safe.update(reconciliationId=reconciliation_id,
                        requestFingerprint=request_fingerprint,
                        evidenceDigest=evidence_digest)
            if reconciliation_profile.get('receipt_fields'):
                safe.update(reconciliation_profile['receipt_fields'])
        return safe


def request_id_fingerprint(request_id):
    if not isinstance(request_id, str) or not re.fullmatch(r'[0-9a-f]{32}', request_id):
        raise ValueError('Invalid request identity')
    return hashlib.sha256(request_id.encode('utf-8')).hexdigest()[:24]


def _preview_details_raw(details):
    return json.dumps(details,ensure_ascii=False,sort_keys=True,separators=(',',':'))


def _preview_details_digest(details):
    return base64.urlsafe_b64encode(hashlib.sha256(_preview_details_raw(details).encode('utf-8')).digest()).decode('ascii').rstrip('=')


def store_preview_plan(path, request_id, actor, details, *, now=None):
    """Persist one immutable Sandbox Preview snapshot for read-only inspection and scoped tickets."""
    if (not isinstance(request_id,str) or not re.fullmatch(r'[0-9a-f]{32}',request_id) or
            not isinstance(actor,str) or not actor.strip() or len(actor)>128 or
            not isinstance(details,dict) or details.get('environment')!='SANDBOX' or
            details.get('version')!=1 or not is_canonical_sha256_b64url(details.get('plan_digest')) or
            not is_canonical_sha256_b64url(details.get('append_only_digest')) or
            not isinstance(details.get('appends'),list) or not isinstance(details.get('updates'),list) or
            not isinstance(details.get('conflicts'),list) or not isinstance(details.get('errors'),list) or
            not isinstance(details.get('counts'),dict)):
        raise ValueError('Sandbox Preview snapshot rejected')
    counts=details['counts']
    append_columns={'A','B','C','D','E','F','H','I','L'}
    update_columns={'C','D','E','F','H','I','L'}
    if (any(type(counts.get(key)) is not int or counts.get(key)<0
            for key in ('append','update','conflict','error')) or
            counts.get('append')!=len(details['appends']) or counts.get('update')!=len(details['updates']) or
            counts.get('conflict')!=len(details['conflicts']) or counts.get('error')!=len(details['errors']) or
            any(not isinstance(item,dict) or item.get('operation')!='APPEND' or
                not isinstance(item.get('cells'),list) or
                any(not isinstance(cell,dict) or cell.get('column') not in append_columns for cell in item['cells']) or
                not any(cell.get('column')=='A' and cell.get('formula') is True for cell in item['cells'])
                for item in details['appends']) or
            any(not isinstance(item,dict) or item.get('operation')!='UPDATE' or
                not isinstance(item.get('cells'),list) or
                any(not isinstance(cell,dict) or cell.get('column') not in update_columns for cell in item['cells'])
                for item in details['updates'])):
        raise ValueError('Sandbox Preview snapshot operations or counts mismatch')
    raw=_preview_details_raw(details)
    if len(raw.encode('utf-8'))>PREVIEW_DETAIL_MAX_BYTES:
        raise ValueError('Sandbox Preview snapshot exceeds safe storage bound')
    digest=_preview_details_digest(details)
    source_digest=details.get('source_digest')
    if source_digest is not None and not is_canonical_sha256_b64url(source_digest):
        raise ValueError('Sandbox Preview source digest rejected')
    stamp=int((now or datetime.now(timezone.utc)).timestamp())
    with closing(sqlite3.connect(path,timeout=5)) as con, con:
        con.execute('PRAGMA foreign_keys=ON')
        try:
            con.execute('''INSERT INTO google_writer_preview_plans(
                request_id,environment,actor,plan_digest,append_only_digest,details_digest,details_json,created_at,expires_at)
                VALUES(?,'SANDBOX',?,?,?,?,?,?,?)''',
                (request_id,actor,details['plan_digest'],details['append_only_digest'],digest,raw,stamp,
                 stamp+PREVIEW_PLAN_TTL_SECONDS))
            # This journal intentionally outlives the five-minute Preview ticket.
            # It is an immutable audit copy, not an Apply authorization token.
            con.execute('''INSERT INTO google_writer_plan_journal(
                plan_id,request_id,environment,actor,plan_digest,append_only_digest,
                details_digest,source_digest,created_at,details_json)
                VALUES(?,?,'SANDBOX',?,?,?,?,?,?,?)''',
                (request_id,request_id,actor,details['plan_digest'],
                 details['append_only_digest'],digest,source_digest,stamp,raw))
        except sqlite3.IntegrityError:
            raise ValueError('Sandbox Preview request identity already has a snapshot or journal') from None
    # The database column remains for compatibility with older Sandbox rows,
    # but it is a review hint only. Sandbox Preview tickets do not expire;
    # every Apply recomputes live source/sheet state before claiming a run.
    return {'details_digest':digest,'expires_at':None,
            'review_only_expiry':True,'plan_id':request_id}


def load_preview_plan(path, request_id, actor, plan_digest, *, details_digest=None, now=None):
    if (not isinstance(request_id,str) or not re.fullmatch(r'[0-9a-f]{32}',request_id) or
            not isinstance(actor,str) or not is_canonical_sha256_b64url(plan_digest) or
            (details_digest is not None and not is_canonical_sha256_b64url(details_digest))):
        raise ValueError('Sandbox Preview snapshot identity rejected')
    stamp=int((now or datetime.now(timezone.utc)).timestamp())
    uri=Path(path).resolve().as_uri()+'?mode=ro'
    with closing(sqlite3.connect(uri,uri=True,timeout=5)) as con:
        con.execute('PRAGMA query_only=ON')
        con.row_factory=sqlite3.Row
        row=con.execute('''SELECT environment,actor,plan_digest,append_only_digest,details_digest,details_json,expires_at
            FROM google_writer_preview_plans WHERE request_id=?''',(request_id,)).fetchone()
    if (not row or row['environment']!='SANDBOX' or row['actor']!=actor or
            row['plan_digest']!=plan_digest or
            (details_digest is not None and row['details_digest']!=details_digest)):
        raise ValueError('Sandbox Preview snapshot missing, stale or unauthorized')
    try: details=json.loads(row['details_json'])
    except (TypeError,json.JSONDecodeError): raise ValueError('Sandbox Preview snapshot invalid') from None
    if (_preview_details_digest(details)!=row['details_digest'] or
            details.get('plan_digest')!=row['plan_digest'] or
            details.get('append_only_digest')!=row['append_only_digest']):
        raise ValueError('Sandbox Preview snapshot integrity mismatch')
    return {'details':details,'details_digest':row['details_digest'],
            'plan_digest':row['plan_digest'],'append_only_digest':row['append_only_digest'],
            'expires_at':None,'review_only_expiry':True}


def validate_preview_plan_scope(snapshot, ticket):
    """Fail-closed binding check shared by full and APPEND_ONLY Sandbox Apply routes."""
    if not isinstance(snapshot,dict) or not isinstance(ticket,dict):
        raise ValueError('Sandbox Preview scope rejected')
    details=snapshot.get('details')
    counts=details.get('counts') if isinstance(details,dict) else None
    appends=details.get('appends') if isinstance(details,dict) else None
    updates=details.get('updates') if isinstance(details,dict) else None
    if (not isinstance(details,dict) or not isinstance(counts,dict) or
            not isinstance(appends,list) or not isinstance(updates,list) or
            details.get('environment')!='SANDBOX' or
            details.get('version')!=1 or snapshot.get('plan_digest')!=details.get('plan_digest') or
            ticket.get('environment')!='SANDBOX' or ticket.get('parent_digest')!=snapshot.get('plan_digest') or
            ticket.get('details_digest')!=snapshot.get('details_digest') or
            counts.get('append')!=len(appends) or counts.get('update')!=len(updates)):
        raise ValueError('Sandbox Preview scope binding mismatch')
    scope=ticket.get('scope')
    if scope=='ALL':
        if ticket.get('digest')!=snapshot.get('plan_digest'):
            raise ValueError('Full Preview digest mismatch')
        return {'scope':'ALL','append':len(appends),'update':len(updates),
                'conflict':counts.get('conflict',0),'error':counts.get('error',0)}
    if scope!='APPEND_ONLY' or ticket.get('digest')!=snapshot.get('append_only_digest'):
        raise ValueError('APPEND_ONLY Preview digest mismatch')
    if (not isinstance(appends,list) or
            any(not isinstance(item,dict) or item.get('operation')!='APPEND' or
                not isinstance(item.get('cells'),list) or
                not any(isinstance(cell,dict) and cell.get('column')=='A' and cell.get('formula') is True
                        for cell in item['cells']) for item in appends)):
        raise ValueError('APPEND_ONLY snapshot contains an invalid operation')
    # UPDATEs remain visible in the parent detail snapshot but are deliberately
    # excluded from the scoped operation count and are never sent to Apps Script.
    return {'scope':'APPEND_ONLY','append':len(appends),'update':0,
            'conflict':counts.get('conflict',0),'error':counts.get('error',0)}


APPEND_JOURNAL_PAGE_ROWS = 25
APPEND_RECOVERY_STALE_SECONDS = 900
APPEND_RECOVERY_LEASE_SECONDS = 600
APPLY_CHUNK_UPDATE_PAGE_ROWS = 50
APPLY_CHUNK_UPDATE_PAGE_CELLS = 100
APPLY_CHUNKS_PER_WORKER = 4


def _canonical_json(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))


def _sha256_b64(value):
    return base64.urlsafe_b64encode(hashlib.sha256(value).digest()).decode('ascii').rstrip('=')


_CLOSE_RECEIPT_FIELDS = ('environment','scriptId','spreadsheetId','contract','requestId','status',
                         'closeId','planScope','disposition','evidenceDigest','reasonDigest',
                         'runRecordDigest','closedAt','actor')

_PREWRITE_CLOSE_STAGES = frozenset({'source_and_sheet_guard','chunk_selection','append_prewrite_guard',
    'append_request_build','append_inflight_save'})
_PREWRITE_PREFLIGHT_REASON_CODES = frozenset({'LOCAL_EVIDENCE_UNAVAILABLE','CLOSE_ALREADY_EXISTS',
    'APPS_SCRIPT_TOMBSTONE_EXISTS','LEGACY_CLOSE_EXISTS','UNCERTAINTY_MARKER_MISMATCH',
    'RUN_RECORD_INVALID','RUN_NOT_UNTOUCHED','PREWRITE_STAGE_UNVERIFIED','MANIFEST_NOT_OVERSIZED',
    'SHEET_BOUNDS_UNAVAILABLE','SHEET_READ_INCOMPLETE','TARGET_CODES_PRESENT','RUN_MARKER_PRESENT',
    'APPS_SCRIPT_CHECK_UNAVAILABLE','APPS_SCRIPT_EVIDENCE_REJECTED'})
_PREWRITE_CLOSE_STAGE_SENTINEL = 'APPS_SCRIPT_PREWRITE_GUARD_V1'
_LEGACY_PREWRITE_LIMIT_REQUEST_ID = 'b11433e8efb84b4492bf2df7c7c25908'
_LEGACY_PREWRITE_LIMIT_STAGE = 'LEGACY_V1_WRITEAHEAD_LIMIT_PROOF_V1'
_LEGACY_PREWRITE_LIMIT_BYTES = 8000
_PREWRITE_CLOSE_RECEIPT_FIELDS = ('environment','scriptId','spreadsheetId','contract','requestId','status',
    'closeId','planScope','disposition','evidenceDigest','reasonDigest','chunkId','chunkDigest',
    'chunkIndex','targetIdentityDigest','prewriteStage','runRecordDigest','closedAt','actor',
    'proofType','writeAheadBytes','checkpointMaxBytes','legacyManifestProjectionDigest')


def _close_receipt_digest(receipt):
    """Digest the immutable receipt fields in the shared Apps Script/Python order."""
    if not isinstance(receipt,dict) or any(not isinstance(receipt.get(key),str) for key in _CLOSE_RECEIPT_FIELDS):
        return None
    return _sha256_b64('\n'.join(receipt[key] for key in _CLOSE_RECEIPT_FIELDS).encode('utf-8'))


def _prewrite_close_receipt_digest(receipt):
    if (not isinstance(receipt,dict) or
            any(not isinstance(receipt.get(key),str) for key in _PREWRITE_CLOSE_RECEIPT_FIELDS
                if key not in {'chunkIndex','writeAheadBytes','checkpointMaxBytes'}) or
            type(receipt.get('chunkIndex')) is not int or type(receipt.get('writeAheadBytes')) is not int or
            type(receipt.get('checkpointMaxBytes')) is not int or
            (receipt.get('legacyManifestProjectionDigest') and
             not is_canonical_sha256_b64url(receipt.get('legacyManifestProjectionDigest')))):
        return None
    return _sha256_b64('\n'.join(str(receipt[key]) for key in _PREWRITE_CLOSE_RECEIPT_FIELDS).encode('utf-8'))


def _run_close_state(con, request_id):
    """Return the permanent close state; tolerate pre-migration read-only fixtures."""
    try:
        row=con.execute('SELECT state FROM google_writer_run_closures WHERE request_id=?',(request_id,)).fetchone()
    except sqlite3.OperationalError as exc:
        if 'no such table' in str(exc).lower(): return None
        raise
    if row: return row[0]
    try:
        row=con.execute('SELECT state FROM google_writer_prewrite_closures WHERE request_id=?',(request_id,)).fetchone()
    except sqlite3.OperationalError as exc:
        if 'no such table' in str(exc).lower(): return None
        raise
    return row[0] if row else None


def _apply_operation_projection(item):
    if not isinstance(item,dict) or not isinstance(item.get('cells'),list):
        raise ValueError('Apply operation projection is invalid')
    cells=[]
    for cell in item['cells']:
        if not isinstance(cell,dict) or not isinstance(cell.get('column'),str):
            raise ValueError('Apply operation cell projection is invalid')
        cells.append({'column':cell['column'],'new_value':cell.get('new_value'),
                      'formula':cell.get('formula') is True})
    return {'operation':item.get('operation'),'tab':item.get('tab'),'row':item.get('row'),
            'code':str(item.get('code') or '').strip(),'cells':cells}


def prepare_apply_chunk(path, request_id, actor, plan_digest, details_digest, scope, chunk_index,
                        *, now=None):
    """Write an immutable Sandbox ALL-scope chunk manifest before transport."""
    if (not re.fullmatch(r'[0-9a-f]{32}',str(request_id or '')) or not actor or
            not is_canonical_sha256_b64url(plan_digest) or
            not is_canonical_sha256_b64url(details_digest) or
            scope!='ALL' or type(chunk_index) is not int or
            not 0 <= chunk_index <= 499):
        raise ValueError('Apply chunk journal identity rejected')
    with closing(sqlite3.connect(path,timeout=5)) as con, con:
        con.execute('BEGIN IMMEDIATE')
        row=con.execute('''SELECT plan_id,actor,plan_digest,append_only_digest,details_digest,
                                  source_digest,details_json
                           FROM google_writer_plan_journal
                           WHERE request_id=? AND environment='SANDBOX' ''',(request_id,)).fetchone()
        expected_digest=row[2] if row and scope=='ALL' else row[3] if row else None
        if (not row or row[1]!=actor or expected_digest!=plan_digest or row[4]!=details_digest or
                not is_canonical_sha256_b64url(row[5])):
            raise ValueError('Durable Preview plan is unavailable or changed')
        try: details=json.loads(row[6])
        except (TypeError,json.JSONDecodeError):
            raise ValueError('Durable Preview plan is invalid') from None
        if (_preview_details_digest(details)!=details_digest or details.get('append_only_digest')!=row[3] or
                details.get('plan_digest')!=row[2] or details.get('source_digest')!=row[5] or
                details.get('environment')!='SANDBOX' or details.get('version')!=1):
            raise ValueError('Durable Preview digest binding failed')
        appends=details.get('appends'); updates=details.get('updates')
        if not isinstance(appends,list) or not isinstance(updates,list):
            raise ValueError('Durable Preview operations are invalid')
        phase='append'; added_at=None
        append_pages=(len(appends)+APPEND_JOURNAL_PAGE_ROWS-1)//APPEND_JOURNAL_PAGE_ROWS
        if scope=='APPEND_ONLY':
            selected=appends[chunk_index*APPEND_JOURNAL_PAGE_ROWS:(chunk_index+1)*APPEND_JOURNAL_PAGE_ROWS]
        elif chunk_index < append_pages:
            selected=appends[chunk_index*APPEND_JOURNAL_PAGE_ROWS:(chunk_index+1)*APPEND_JOURNAL_PAGE_ROWS]
        else:
            phase='update'
            ordered=sorted(updates,key=lambda item:(item.get('tab',''),item.get('row',0)))
            pages=[]; page=[]; cells=0
            for item in ordered:
                width=len(item.get('cells',[])) if isinstance(item,dict) else 0
                if page and (len(page)>=APPLY_CHUNK_UPDATE_PAGE_ROWS or cells+width>APPLY_CHUNK_UPDATE_PAGE_CELLS):
                    pages.append(page); page=[]; cells=0
                if width>APPLY_CHUNK_UPDATE_PAGE_CELLS:
                    raise ValueError('UPDATE operation exceeds the bounded chunk size')
                page.append(item); cells+=width
            if page: pages.append(page)
            update_index=chunk_index-append_pages
            selected=pages[update_index] if update_index<len(pages) else []
        if not selected:
            raise ValueError('Apply chunk is outside the immutable Preview plan')
        if any(not isinstance(item,dict) or item.get('operation')!=phase.upper() or
               item.get('tab') not in {'ФОП','ЮО'} or type(item.get('row')) is not int or
               not isinstance(item.get('code'),str) or not item['code'].strip() or
               not isinstance(item.get('cells'),list) or not item['cells'] for item in selected):
            raise ValueError('Apply chunk composition is invalid')
        identities=[(item['tab'],item['row']) for item in selected]
        if len(set(identities))!=len(identities):
            raise ValueError('Duplicate row identity in Apply chunk')
        if phase=='append':
            added_at=(now or datetime.now(KYIV)).astimezone(KYIV).isoformat(timespec='seconds')
        projected=[_apply_operation_projection(item) for item in selected]
        manifest={'version':1,'plan_id':row[0],'run_id':request_id,'scope':scope,
                  'plan_digest':plan_digest,'details_digest':details_digest,'source_digest':row[5],
                  'phase':phase,'chunk_index':chunk_index,'operations':projected}
        if added_at: manifest['added_at']=added_at
        expected_raw=_canonical_json(manifest)
        chunk_digest=_sha256_b64(expected_raw.encode('utf-8'))
        chunk_id=hashlib.sha256((request_id+'|'+row[0]+'|'+scope+'|'+phase+'|'+str(chunk_index)+'|'+chunk_digest).encode()).hexdigest()[:32]
        existing=con.execute('''SELECT chunk_digest,expected_json,status FROM google_writer_apply_chunk_journal
                                WHERE chunk_id=?''',(chunk_id,)).fetchone()
        if existing:
            if existing[0]!=chunk_digest or existing[1]!=expected_raw:
                raise RuntimeError('Apply chunk journal identity collision')
            if existing[2] in {'inflight','outcome_unknown'}:
                raise RuntimeError('Apply chunk outcome is unresolved; no retry')
            if existing[2]!='prepared':
                raise RuntimeError('Apply chunk is already confirmed; no replay')
            return {'chunk_id':chunk_id,'chunk_digest':chunk_digest,'plan_id':row[0],
                    'phase':phase,'added_at':added_at,'scope':scope,'details_digest':details_digest,
                    'source_digest':row[5],'status':existing[2]}
        stamp=(now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        con.execute('''INSERT INTO google_writer_apply_chunk_journal(
            chunk_id,plan_id,run_id,environment,scope,phase,plan_digest,source_digest,chunk_index,
            chunk_digest,status,expected_json,prepared_at)
            VALUES(?,?,?,'SANDBOX',?,?,?,?,?,?,'prepared',?,?)''',
            (chunk_id,row[0],request_id,scope,phase,plan_digest,row[5],chunk_index,
             chunk_digest,expected_raw,stamp))
    return {'chunk_id':chunk_id,'chunk_digest':chunk_digest,'plan_id':row[0],
            'phase':phase,'added_at':added_at,'scope':scope,'details_digest':details_digest,
            'source_digest':row[5],'status':'prepared'}


def mark_apply_chunk_inflight(path, chunk_id, *, now=None):
    stamp=(now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    with closing(sqlite3.connect(path,timeout=5)) as con, con:
        con.execute('BEGIN IMMEDIATE')
        changed=con.execute("UPDATE google_writer_apply_chunk_journal SET status='inflight',inflight_at=? WHERE chunk_id=? AND status='prepared'",
                            (stamp,chunk_id)).rowcount
        if changed!=1: raise RuntimeError('Apply chunk is not eligible for its first remote call')
        row=con.execute('''SELECT run_id,phase,chunk_index FROM google_writer_apply_chunk_journal WHERE chunk_id=?''',(chunk_id,)).fetchone()
        run=con.execute("SELECT result_json FROM google_writer_runs WHERE request_id=? AND status='running'",(row[0],)).fetchone()
        if not run: raise RuntimeError('Apply run no longer owns its journaled chunk')
        progress=json.loads(run[0] or '{}')
        progress.update(attempted_chunk=row[2],attempted_phase=row[1],progress_state='remote_in_flight',
                        last_progress_at=stamp)
        con.execute("UPDATE google_writer_runs SET result_json=? WHERE request_id=? AND status='running'",
                    (json.dumps(progress,sort_keys=True),row[0]))
    return True


def mark_apply_chunk_unknown(path, chunk_id):
    with closing(sqlite3.connect(path,timeout=5)) as con, con:
        con.execute("UPDATE google_writer_apply_chunk_journal SET status='outcome_unknown' WHERE chunk_id=? AND status='inflight'",
                    (chunk_id,))


def reset_apply_chunk_preflight(path, chunk_id):
    """Reset only when transport has proven that Apps Script was not called."""
    with closing(sqlite3.connect(path,timeout=5)) as con, con:
        con.execute('BEGIN IMMEDIATE')
        row=con.execute('SELECT run_id,phase,chunk_index FROM google_writer_apply_chunk_journal WHERE chunk_id=? AND status=\'inflight\'',
                        (chunk_id,)).fetchone()
        if not row: raise RuntimeError('Apply chunk preflight reset lost its compare-and-set')
        changed=con.execute("UPDATE google_writer_apply_chunk_journal SET status='prepared',inflight_at=NULL WHERE chunk_id=? AND status='inflight'",
                            (chunk_id,)).rowcount
        if changed!=1: raise RuntimeError('Apply chunk preflight reset lost its compare-and-set')
        run=con.execute("SELECT result_json FROM google_writer_runs WHERE request_id=? AND status='running'",(row[0],)).fetchone()
        if run:
            try: progress=json.loads(run[0] or '{}')
            except (TypeError,json.JSONDecodeError): progress={}
            progress.update(progress_state='preparing',attempted_chunk=None,attempted_phase=None,
                            last_progress_at=datetime.now(timezone.utc).isoformat())
            con.execute("UPDATE google_writer_runs SET result_json=? WHERE request_id=? AND status='running'",
                        (json.dumps(progress,sort_keys=True),row[0]))


def apply_chunk_journal_state(path, request_id):
    """Read-only aggregate; does not expose operation values or supplier identities."""
    uri=Path(path).resolve().as_uri()+'?mode=ro'
    with closing(sqlite3.connect(uri,uri=True,timeout=5)) as con:
        con.execute('PRAGMA query_only=ON')
        rows=con.execute('''SELECT phase,status,COUNT(*) FROM google_writer_apply_chunk_journal
                            WHERE run_id=? GROUP BY phase,status ORDER BY phase,status''',(request_id,)).fetchall()
    return {'chunks':[{'phase':r[0],'status':r[1],'count':r[2]} for r in rows],
            'verified_chunks':sum(r[2] for r in rows if r[1]=='verified'),
            'unknown_chunks':sum(r[2] for r in rows if r[1] in {'inflight','outcome_unknown'})}


def prepare_append_chunk(path, request_id, actor, plan_digest, details_digest, chunk_index,
                         *, page_rows=APPEND_JOURNAL_PAGE_ROWS, now=None):
    """Persist one immutable APPEND_ONLY chunk before any remote write is requested."""
    if (not re.fullmatch(r'[0-9a-f]{32}',str(request_id or '')) or not actor or
            not is_canonical_sha256_b64url(plan_digest) or
            not is_canonical_sha256_b64url(details_digest) or type(chunk_index) is not int or
            not 0 <= chunk_index <= 499 or page_rows != APPEND_JOURNAL_PAGE_ROWS):
        raise ValueError('Append chunk journal identity rejected')
    with closing(sqlite3.connect(path,timeout=5)) as con, con:
        con.execute('BEGIN IMMEDIATE')
        row=con.execute('''SELECT plan_id,actor,plan_digest,append_only_digest,details_digest,
                                  source_digest,details_json
                           FROM google_writer_plan_journal
                           WHERE request_id=? AND environment='SANDBOX' ''',(request_id,)).fetchone()
        if (not row or row[1]!=actor or row[3]!=plan_digest or row[4]!=details_digest or
                not is_canonical_sha256_b64url(row[5])):
            raise ValueError('Durable Preview plan is unavailable or changed')
        try: details=json.loads(row[6])
        except (TypeError,json.JSONDecodeError):
            raise ValueError('Durable Preview plan is invalid') from None
        if (_preview_details_digest(details)!=details_digest or
                details.get('append_only_digest')!=row[3] or
                details.get('plan_digest')!=row[2] or details.get('append_only_digest')!=plan_digest or
                details.get('environment')!='SANDBOX' or
                details.get('version')!=1 or details.get('updates') is None):
            raise ValueError('Durable Preview plan digest binding failed')
        appends=details.get('appends')
        if not isinstance(appends,list): raise ValueError('Durable APPEND plan is invalid')
        start=chunk_index*page_rows
        selected=appends[start:start+page_rows]
        if not selected:
            raise ValueError('Append chunk is outside the immutable plan')
        codes=[]
        for item in selected:
            if (not isinstance(item,dict) or item.get('operation')!='APPEND' or
                    item.get('tab') not in {'ФОП','ЮО'} or
                    not isinstance(item.get('code'),str) or not item['code'].strip() or
                    not isinstance(item.get('cells'),list)):
                raise ValueError('Append chunk composition is invalid')
            codes.append(item['code'].strip())
        if len(set(codes))!=len(codes):
            raise ValueError('Duplicate supplier identity in append chunk')
        expected={'version':1,'plan_id':row[0],'run_id':request_id,'scope':'APPEND_ONLY',
                  'plan_digest':plan_digest,'source_digest':row[5],
                  'chunk_index':chunk_index,'rows':selected}
        expected_raw=_canonical_json(expected)
        chunk_digest=_sha256_b64(expected_raw.encode('utf-8'))
        chunk_id=hashlib.sha256((request_id+'|'+row[0]+'|APPEND_ONLY|'+str(chunk_index)+'|'+chunk_digest).encode()).hexdigest()[:32]
        existing=con.execute('SELECT chunk_digest,expected_json,status FROM google_writer_chunk_journal WHERE chunk_id=?',
                              (chunk_id,)).fetchone()
        if existing:
            if existing[0]!=chunk_digest or existing[1]!=expected_raw:
                raise RuntimeError('Append chunk journal identity collision')
            if existing[2] in {'inflight','outcome_unknown'}:
                raise RuntimeError('Append chunk has an unresolved remote outcome; no retry')
            return {'chunk_id':chunk_id,'chunk_digest':chunk_digest,'plan_id':row[0],
                    'run_id':request_id,'status':existing[2],'expected':expected}
        stamp=(now or datetime.now(timezone.utc)).isoformat()
        con.execute('''INSERT INTO google_writer_chunk_journal(
            chunk_id,plan_id,run_id,environment,scope,plan_digest,source_digest,chunk_index,
            chunk_digest,status,expected_json,prepared_at)
            VALUES(?,?,?,'SANDBOX','APPEND_ONLY',?,?,?,?,'prepared',?,?)''',
            (chunk_id,row[0],request_id,plan_digest,row[5],chunk_index,chunk_digest,expected_raw,stamp))
    return {'chunk_id':chunk_id,'chunk_digest':chunk_digest,'plan_id':row[0],
            'run_id':request_id,'status':'prepared','expected':expected}


def mark_append_chunk_inflight(path, chunk_id, *, now=None):
    stamp=(now or datetime.now(timezone.utc)).isoformat()
    with closing(sqlite3.connect(path,timeout=5)) as con, con:
        con.execute('BEGIN IMMEDIATE')
        changed=con.execute("UPDATE google_writer_chunk_journal SET status='inflight',inflight_at=? WHERE chunk_id=? AND status='prepared'",
                            (stamp,chunk_id)).rowcount
        if changed!=1:
            row=con.execute('SELECT status FROM google_writer_chunk_journal WHERE chunk_id=?',(chunk_id,)).fetchone()
            if not row or row[0]!='verified':
                raise RuntimeError('Append chunk is not eligible for its first remote call')
            return False
        row=con.execute('SELECT run_id,chunk_index FROM google_writer_chunk_journal WHERE chunk_id=?',(chunk_id,)).fetchone()
        run=con.execute("SELECT result_json FROM google_writer_runs WHERE request_id=? AND status='running'",(row[0],)).fetchone()
        if not run: raise RuntimeError('Append run no longer owns its journaled chunk')
        progress=json.loads(run[0] or '{}')
        progress.update(attempted_chunk=row[1],attempted_phase='append',progress_state='remote_in_flight',
                        last_progress_at=stamp)
        con.execute("UPDATE google_writer_runs SET result_json=? WHERE request_id=? AND status='running'",
                    (json.dumps(progress,sort_keys=True),row[0]))
    return True


def mark_append_chunk_unknown(path, chunk_id):
    with closing(sqlite3.connect(path,timeout=5)) as con, con:
        con.execute("UPDATE google_writer_chunk_journal SET status='outcome_unknown' WHERE chunk_id=? AND status='inflight'",
                    (chunk_id,))


def reset_append_chunk_preflight(path, chunk_id):
    """Return to prepared only when transport proves Apps Script was not called."""
    with closing(sqlite3.connect(path,timeout=5)) as con, con:
        changed=con.execute("UPDATE google_writer_chunk_journal SET status='prepared',inflight_at=NULL WHERE chunk_id=? AND status='inflight'",
                            (chunk_id,)).rowcount
        if changed!=1:
            raise RuntimeError('Append chunk preflight reset lost its compare-and-set')


def chunk_journal_state(path, request_id):
    """Read-only summary used by recovery and support tooling; never returns supplier data."""
    uri=Path(path).resolve().as_uri()+'?mode=ro'
    with closing(sqlite3.connect(uri,uri=True,timeout=5)) as con:
        con.execute('PRAGMA query_only=ON')
        rows=con.execute('''SELECT chunk_index,status,COUNT(*) FROM google_writer_chunk_journal
                            WHERE run_id=? GROUP BY chunk_index,status ORDER BY chunk_index,status''',
                         (request_id,)).fetchall()
    return {'chunks':[{'chunk_index':r[0],'status':r[1],'count':r[2]} for r in rows],
            'verified_chunks':sum(r[2] for r in rows if r[1] in {'verified','reconciled'}),
            'unknown_chunks':sum(r[2] for r in rows if r[1] in {'inflight','outcome_unknown'})}


def claim_interrupted_append_chunk_recovery(path, request_id, *, now=None,
                                            stale_seconds=APPEND_RECOVERY_STALE_SECONDS,
                                            lease_seconds=APPEND_RECOVERY_LEASE_SECONDS):
    """CAS-claim a lost Sandbox APPEND_ONLY response for read-only recovery.

    A still-running execution is considered interrupted only after the Apps
    Script call plus its recovery call could have exhausted their bounded
    transport windows. No Apply is issued by this claim.
    """
    if (not re.fullmatch(r'[0-9a-f]{32}', str(request_id or '')) or
            type(stale_seconds) is not int or stale_seconds < 600 or
            type(lease_seconds) is not int or lease_seconds < 390):
        raise ValueError('Append recovery claim parameters rejected')
    clock=now or datetime.now(timezone.utc)
    if clock.tzinfo is None: raise ValueError('Aware recovery clock required')
    stamp=clock.astimezone(timezone.utc)
    stamp_raw=stamp.isoformat()
    with closing(sqlite3.connect(path,timeout=5)) as con, con:
        con.execute('BEGIN IMMEDIATE')
        if _run_close_state(con,request_id) is not None:
            return None
        run=con.execute('''SELECT environment,trigger,actor,status,result_json
                           FROM google_writer_runs WHERE request_id=?''',(request_id,)).fetchone()
        if not run or run[0]!='SANDBOX' or run[1]!='manual' or run[3] not in {'running','outcome_unknown'}:
            return None
        try: progress=json.loads(run[4] or '{}')
        except (TypeError,json.JSONDecodeError): return None
        if (not isinstance(progress,dict) or progress.get('plan_scope')!='APPEND_ONLY' or
                not is_canonical_sha256_b64url(progress.get('plan_digest'))):
            return None
        if con.execute('SELECT 1 FROM google_writer_run_reconciliations WHERE request_id=? LIMIT 1',
                       (request_id,)).fetchone():
            return None
        claimed_at=progress.get('recovery_claimed_at')
        if claimed_at:
            try:
                parsed=datetime.fromisoformat(claimed_at)
                if parsed.tzinfo is None: return None
                if (stamp-parsed.astimezone(timezone.utc)).total_seconds()<lease_seconds:
                    return None
            except (TypeError,ValueError): return None
        chunks=con.execute('''SELECT chunk_id,plan_id,run_id,scope,plan_digest,source_digest,
                                    chunk_index,chunk_digest,status,expected_json,inflight_at
                             FROM google_writer_chunk_journal
                             WHERE run_id=? AND status IN ('inflight','outcome_unknown')
                             ORDER BY chunk_index''',(request_id,)).fetchall()
        if len(chunks)!=1: return None
        chunk=chunks[0]
        if (chunk[2]!=request_id or chunk[3]!='APPEND_ONLY' or chunk[4]!=progress.get('plan_digest') or
                chunk[8] not in {'inflight','outcome_unknown'} or
                progress.get('attempted_chunk') not in (None,chunk[6])):
            return None
        if run[3]=='running':
            try:
                inflight=datetime.fromisoformat(chunk[10])
                if inflight.tzinfo is None or (stamp-inflight.astimezone(timezone.utc)).total_seconds()<stale_seconds:
                    return None
            except (TypeError,ValueError): return None
        try: expected=json.loads(chunk[9])
        except (TypeError,json.JSONDecodeError): return None
        plan=con.execute('''SELECT actor,plan_digest,append_only_digest,details_digest,source_digest,details_json
                            FROM google_writer_plan_journal WHERE plan_id=? AND request_id=?
                              AND environment='SANDBOX' ''',(chunk[1],request_id)).fetchone()
        if (not isinstance(expected,dict) or expected.get('run_id')!=request_id or
                expected.get('plan_id')!=chunk[1] or expected.get('plan_digest')!=chunk[4] or
                expected.get('source_digest')!=chunk[5] or expected.get('chunk_index')!=chunk[6] or
                not isinstance(expected.get('rows'),list) or not expected['rows'] or
                not plan or plan[0]!=run[2] or plan[2]!=chunk[4] or
                plan[4]!=chunk[5] or not is_canonical_sha256_b64url(plan[3]) or
                not is_canonical_sha256_b64url(plan[4])):
            return None
        try: details=json.loads(plan[5])
        except (TypeError,json.JSONDecodeError): return None
        index=chunk[6]*APPEND_JOURNAL_PAGE_ROWS
        if (not isinstance(details,dict) or not isinstance(details.get('appends'),list) or
                _preview_details_digest(details)!=plan[3] or
                details.get('append_only_digest')!=chunk[4] or details.get('plan_digest')!=plan[1] or
                details.get('source_digest')!=chunk[5] or
                details.get('appends',[])[index:index+APPEND_JOURNAL_PAGE_ROWS]!=expected['rows']):
            return None
        expected_raw=_canonical_json(expected)
        if (_sha256_b64(expected_raw.encode('utf-8'))!=chunk[7] or
                hashlib.sha256((request_id+'|'+chunk[1]+'|APPEND_ONLY|'+str(chunk[6])+'|'+chunk[7]).encode()).hexdigest()[:32]!=chunk[0]):
            return None
        con.execute("UPDATE google_writer_chunk_journal SET status='inflight' WHERE chunk_id=? AND status IN ('inflight','outcome_unknown')",
                    (chunk[0],))
        if con.execute('SELECT changes()').fetchone()[0]!=1: return None
        progress=progress|{'status':'APPEND_CHUNK_RECOVERY_CLAIMED','recovery_claimed_at':stamp_raw,
            'attempted_chunk':chunk[6],'plan_digest':chunk[4]}
        con.execute("UPDATE google_writer_runs SET status='running',finished_at=NULL,result_json=? WHERE request_id=? AND status IN ('running','outcome_unknown')",
                    (json.dumps(progress,sort_keys=True),request_id))
        if con.execute('SELECT changes()').fetchone()[0]!=1:
            raise RuntimeError('Append recovery run claim compare-and-set failed')
    return {'request_id':request_id,'actor':run[2],'plan_digest':chunk[4],
        'chunk_index':chunk[6],'chunk_id':chunk[0],'chunk_digest':chunk[7],
        'plan_id':chunk[1],'checkpoint_digest':progress.get('checkpoint_digest'),
        'prior_verified_chunks':int(progress.get('verified_chunks',0))}


def claim_interrupted_apply_chunk_recovery(path, request_id, *, now=None,
                                           stale_seconds=APPEND_RECOVERY_STALE_SECONDS,
                                           lease_seconds=APPEND_RECOVERY_LEASE_SECONDS):
    """Claim one immutable ALL-scope chunk for read-only Apps Script recovery."""
    if (not re.fullmatch(r'[0-9a-f]{32}',str(request_id or '')) or
            type(stale_seconds) is not int or stale_seconds<600 or
            type(lease_seconds) is not int or lease_seconds<390):
        raise ValueError('Apply recovery claim parameters rejected')
    clock=now or datetime.now(timezone.utc)
    if clock.tzinfo is None: raise ValueError('Aware recovery clock required')
    stamp=clock.astimezone(timezone.utc); stamp_raw=stamp.isoformat()
    with closing(sqlite3.connect(path,timeout=5)) as con, con:
        con.execute('BEGIN IMMEDIATE')
        if _run_close_state(con,request_id) is not None:
            return None
        run=con.execute('''SELECT environment,trigger,actor,status,result_json FROM google_writer_runs
                           WHERE request_id=?''',(request_id,)).fetchone()
        if not run or run[0]!='SANDBOX' or run[1]!='manual' or run[3] not in {'running','outcome_unknown'}:
            return None
        try: progress=json.loads(run[4] or '{}')
        except (TypeError,json.JSONDecodeError): return None
        plan_digest=progress.get('plan_digest') if isinstance(progress,dict) else None
        details_digest=progress.get('details_digest') if isinstance(progress,dict) else None
        if (not isinstance(progress,dict) or progress.get('plan_scope')!='ALL' or
                not is_canonical_sha256_b64url(plan_digest) or
                not is_canonical_sha256_b64url(details_digest)):
            return None
        if con.execute('SELECT 1 FROM google_writer_run_reconciliations WHERE request_id=? LIMIT 1',
                       (request_id,)).fetchone(): return None
        claimed_at=progress.get('recovery_claimed_at')
        if claimed_at:
            try:
                parsed=datetime.fromisoformat(claimed_at)
                if parsed.tzinfo is None or (stamp-parsed.astimezone(timezone.utc)).total_seconds()<lease_seconds:
                    return None
            except (TypeError,ValueError): return None
        rows=con.execute('''SELECT chunk_id,plan_id,run_id,scope,phase,plan_digest,source_digest,
                                   chunk_index,chunk_digest,status,expected_json,inflight_at
                            FROM google_writer_apply_chunk_journal
                            WHERE run_id=? AND scope='ALL' AND status IN ('inflight','outcome_unknown')
                            ORDER BY chunk_index''',(request_id,)).fetchall()
        if len(rows)!=1: return None
        chunk=rows[0]
        if (chunk[2]!=request_id or chunk[3]!='ALL' or chunk[5]!=plan_digest or
                progress.get('attempted_chunk') not in (None,chunk[7]) or
                progress.get('attempted_phase') not in (None,chunk[4])): return None
        if run[3]=='running':
            try:
                inflight=datetime.fromisoformat(chunk[11])
                if inflight.tzinfo is None or (stamp-inflight.astimezone(timezone.utc)).total_seconds()<stale_seconds:
                    return None
            except (TypeError,ValueError): return None
        plan=con.execute('''SELECT actor,plan_digest,append_only_digest,details_digest,source_digest,details_json
                            FROM google_writer_plan_journal WHERE plan_id=? AND request_id=?
                              AND environment='SANDBOX' ''',(chunk[1],request_id)).fetchone()
        if (not plan or plan[0]!=run[2] or plan[1]!=plan_digest or plan[3]!=details_digest or
                plan[4]!=chunk[6] or not is_canonical_sha256_b64url(plan[4])): return None
        try: details=json.loads(plan[5]); expected=json.loads(chunk[10])
        except (TypeError,json.JSONDecodeError): return None
        if (not isinstance(details,dict) or not isinstance(expected,dict) or
                details.get('environment')!='SANDBOX' or details.get('version')!=1 or
                _preview_details_digest(details)!=details_digest or details.get('plan_digest')!=plan_digest or
                details.get('source_digest')!=chunk[6] or details.get('append_only_digest')!=plan[2]): return None
        appends=details.get('appends'); updates=details.get('updates')
        if not isinstance(appends,list) or not isinstance(updates,list): return None
        append_pages=(len(appends)+APPEND_JOURNAL_PAGE_ROWS-1)//APPEND_JOURNAL_PAGE_ROWS
        if chunk[4]=='append':
            selected=appends[chunk[7]*APPEND_JOURNAL_PAGE_ROWS:(chunk[7]+1)*APPEND_JOURNAL_PAGE_ROWS]
            added_at=expected.get('added_at')
        else:
            ordered=sorted(updates,key=lambda item:(item.get('tab',''),item.get('row',0)))
            pages=[]; page=[]; cells=0
            for item in ordered:
                width=len(item.get('cells',[])) if isinstance(item,dict) else 0
                if page and (len(page)>=APPLY_CHUNK_UPDATE_PAGE_ROWS or cells+width>APPLY_CHUNK_UPDATE_PAGE_CELLS):
                    pages.append(page); page=[]; cells=0
                if width>APPLY_CHUNK_UPDATE_PAGE_CELLS: return None
                page.append(item); cells+=width
            if page: pages.append(page)
            update_index=chunk[7]-append_pages
            selected=pages[update_index] if 0<=update_index<len(pages) else []
            added_at=None
        projected=[_apply_operation_projection(item) for item in selected]
        manifest={'version':1,'plan_id':chunk[1],'run_id':request_id,'scope':'ALL',
            'plan_digest':plan_digest,'details_digest':details_digest,'source_digest':chunk[6],
            'phase':chunk[4],'chunk_index':chunk[7],'operations':projected}
        if added_at is not None: manifest['added_at']=added_at
        expected_raw=_canonical_json(manifest)
        expected_chunk_digest=_sha256_b64(expected_raw.encode('utf-8'))
        expected_chunk_id=hashlib.sha256((request_id+'|'+chunk[1]+'|ALL|'+chunk[4]+'|'+
            str(chunk[7])+'|'+expected_chunk_digest).encode()).hexdigest()[:32]
        if (not selected or chunk[8]!=expected_chunk_digest or chunk[0]!=expected_chunk_id or
                chunk[9] not in {'inflight','outcome_unknown'} or chunk[10]!=expected_raw): return None
        changed=con.execute("UPDATE google_writer_apply_chunk_journal SET status='inflight' WHERE chunk_id=? AND status=?",
                            (chunk[0],chunk[9])).rowcount
        if changed!=1: return None
        progress=progress|{'status':'APPLY_CHUNK_RECOVERY_CLAIMED','recovery_claimed_at':stamp_raw,
            'attempted_chunk':chunk[7],'attempted_phase':chunk[4],'plan_digest':plan_digest}
        changed=con.execute("UPDATE google_writer_runs SET status='running',finished_at=NULL,result_json=? WHERE request_id=? AND status=?",
                            (json.dumps(progress,sort_keys=True),request_id,run[3])).rowcount
        if changed!=1: raise RuntimeError('Apply recovery run claim compare-and-set failed')
    return {'request_id':request_id,'actor':run[2],'plan_digest':plan_digest,
        'details_digest':details_digest,'chunk_index':chunk[7],'chunk_id':chunk[0],
        'chunk_digest':chunk[8],'plan_id':chunk[1],'phase':chunk[4],
        'added_at':added_at,'checkpoint_digest':progress.get('checkpoint_digest')}


def claim_apply_continuation(path, request_id, actor, *, now=None):
    """CAS-claim only a fully journaled ALL-scope checkpoint chain for background continuation."""
    if not re.fullmatch(r'[0-9a-f]{32}',str(request_id or '')) or not actor:
        return None
    stamp=(now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    with closing(sqlite3.connect(path,timeout=5)) as con, con:
        con.execute('BEGIN IMMEDIATE')
        if _run_close_state(con,request_id) is not None:
            return None
        run=con.execute('''SELECT environment,trigger,actor,status,result_json FROM google_writer_runs
                           WHERE request_id=?''',(request_id,)).fetchone()
        if not run or (run[0],run[1],run[2],run[3])!=('SANDBOX','manual',actor,'partial'):return None
        try: progress=json.loads(run[4] or '{}')
        except (TypeError,json.JSONDecodeError):return None
        next_chunk=progress.get('next_chunk') if isinstance(progress,dict) else None
        digest=progress.get('plan_digest') if isinstance(progress,dict) else None
        checkpoint=progress.get('checkpoint_digest') if isinstance(progress,dict) else None
        if (not isinstance(progress,dict) or progress.get('status')!='HALTED_AFTER_VERIFIED_CHECKPOINTS' or
                progress.get('plan_scope')!='ALL' or progress.get('outcome_unknown') or
                progress.get('attempted_chunk') is not None or progress.get('auto_continue_chunks') is not True or
                type(next_chunk) is not int or not 1<=next_chunk<=499 or
                not is_canonical_sha256_b64url(digest) or not is_canonical_sha256_b64url(checkpoint) or
                con.execute('SELECT 1 FROM google_writer_run_reconciliations WHERE request_id=? LIMIT 1',
                            (request_id,)).fetchone()):return None
        plan=con.execute('''SELECT plan_id,plan_digest,details_digest,source_digest,details_json
                            FROM google_writer_plan_journal WHERE request_id=? AND environment='SANDBOX'
                              AND actor=?''',(request_id,actor)).fetchall()
        if len(plan)!=1:return None
        plan_id,plan_digest,details_digest,source_digest,details_raw=plan[0]
        if (plan_digest!=digest or not is_canonical_sha256_b64url(details_digest) or
                not is_canonical_sha256_b64url(source_digest)):return None
        try: details=json.loads(details_raw)
        except (TypeError,json.JSONDecodeError):return None
        if (not isinstance(details,dict) or _preview_details_digest(details)!=details_digest or
                details.get('plan_digest')!=digest or details.get('source_digest')!=source_digest or
                details.get('environment')!='SANDBOX'):return None
        appends=details.get('appends'); updates=details.get('updates')
        if not isinstance(appends,list) or not isinstance(updates,list):return None
        append_pages=(len(appends)+APPEND_JOURNAL_PAGE_ROWS-1)//APPEND_JOURNAL_PAGE_ROWS
        chunks=con.execute('''SELECT chunk_id,phase,plan_digest,source_digest,chunk_index,chunk_digest,
                                     status,expected_json,receipt_json
                              FROM google_writer_apply_chunk_journal WHERE run_id=? AND scope='ALL'
                              ORDER BY chunk_index''',(request_id,)).fetchall()
        if len(chunks)<next_chunk:return None
        chunks=chunks[:next_chunk]
        if [row[4] for row in chunks]!=list(range(next_chunk)):return None
        last_receipt=None
        for row in chunks:
            if row[6]!='verified' or row[2]!=digest or row[3]!=source_digest:return None
            try: expected=json.loads(row[7]); receipt=json.loads(row[8])
            except (TypeError,json.JSONDecodeError):return None
            if not isinstance(expected,dict) or not isinstance(receipt,dict):return None
            if row[4]<append_pages:
                expected_phase='append'
                selected=appends[row[4]*APPEND_JOURNAL_PAGE_ROWS:(row[4]+1)*APPEND_JOURNAL_PAGE_ROWS]
                added_at=expected.get('added_at')
                try:
                    parsed_added_at=datetime.fromisoformat(added_at)
                    if parsed_added_at.tzinfo is None:return None
                except (TypeError,ValueError):return None
            else:
                expected_phase='update';ordered=sorted(updates,key=lambda item:(item.get('tab',''),item.get('row',0)))
                pages=[];page=[];cells=0
                for item in ordered:
                    width=len(item.get('cells',[])) if isinstance(item,dict) else 0
                    if page and (len(page)>=APPLY_CHUNK_UPDATE_PAGE_ROWS or cells+width>APPLY_CHUNK_UPDATE_PAGE_CELLS):
                        pages.append(page);page=[];cells=0
                    if width>APPLY_CHUNK_UPDATE_PAGE_CELLS:return None
                    page.append(item);cells+=width
                if page:pages.append(page)
                update_index=row[4]-append_pages
                selected=pages[update_index] if 0<=update_index<len(pages) else []
                added_at=None
            expected_ops=[_apply_operation_projection(item) for item in selected]
            expected_manifest={'version':1,'plan_id':plan_id,'run_id':request_id,'scope':'ALL',
                'plan_digest':digest,'details_digest':details_digest,'source_digest':source_digest,
                'phase':expected_phase,'chunk_index':row[4],'operations':expected_ops}
            if added_at is not None:expected_manifest['added_at']=added_at
            if (not selected or row[1]!=expected_phase or expected!=expected_manifest or
                    expected.get('version')!=1 or expected.get('run_id')!=request_id or
                    expected.get('plan_id')!=plan_id or expected.get('scope')!='ALL' or
                    expected.get('plan_digest')!=digest or expected.get('details_digest')!=details_digest or
                    expected.get('source_digest')!=source_digest or expected.get('phase')!=row[1] or
                    expected.get('chunk_index')!=row[4] or not isinstance(expected.get('operations'),list) or
                    not expected['operations'] or _sha256_b64(_canonical_json(expected).encode())!=row[5] or
                    hashlib.sha256((request_id+'|'+plan_id+'|ALL|'+row[1]+'|'+str(row[4])+'|'+row[5]).encode()).hexdigest()[:32]!=row[0] or
                    receipt.get('digest')!=digest or receipt.get('planScope')!='ALL' or
                    receipt.get('chunkIndex')!=row[4] or receipt.get('nextChunk')!=row[4]+1 or
                    receipt.get('chunkId')!=row[0] or receipt.get('chunkDigest')!=row[5] or
                    receipt.get('planId')!=plan_id or receipt.get('phase')!=row[1] or
                    not is_canonical_sha256_b64url(receipt.get('checkpointDigest'))):return None
            ops=expected['operations']; counts=receipt.get('counts')
            if (not isinstance(counts,dict) or counts.get('append')!=(len(ops) if row[1]=='append' else 0) or
                    counts.get('update')!=(len(ops) if row[1]=='update' else 0)):return None
            last_receipt=receipt
        if (not last_receipt or last_receipt.get('nextChunk')!=next_chunk or
                last_receipt.get('checkpointDigest')!=checkpoint or last_receipt.get('more') is not True):return None
        progress=progress|{'status':'APPLY_CONTINUATION_CLAIMED','recovery_claimed_at':stamp,
            'attempted_chunk':None,'progress_state':'preparing','last_progress_at':stamp}
        changed=con.execute("UPDATE google_writer_runs SET status='running',finished_at=NULL,result_json=? WHERE request_id=? AND status='partial'",
            (json.dumps(progress,sort_keys=True),request_id)).rowcount
        if changed!=1:return None
    return {'request_id':request_id,'actor':actor,'plan_digest':digest,'next_chunk':next_chunk,
            'checkpoint_digest':checkpoint,'scope':'ALL'}


def continue_apply_checkpoint(path,client,request_id,actor,*,guard=lambda:True):
    claim=claim_apply_continuation(path,request_id,actor)
    if not claim:return {'status':'CONTINUATION_NOT_CLAIMED'}
    if not guard():
        finish_partial_after_checkpoints(path,request_id,verified_chunks=claim['next_chunk'],
            next_chunk=claim['next_chunk'],digest=claim['plan_digest'])
        return {'status':'HALTED_AFTER_VERIFIED_CHECKPOINTS','next_chunk':claim['next_chunk']}
    return execute_claimed(path,client,request_id,actor,trigger='manual',digest=claim['plan_digest'],
        guard=guard,manual_authorized=True,plan_scope='ALL',start_chunk=claim['next_chunk'],
        checkpoint_digest=claim['checkpoint_digest'],max_apply_chunks=APPLY_CHUNKS_PER_WORKER)


def reclaim_stale_apply_continuation(path, *, now=None, lease_seconds=APPEND_RECOVERY_LEASE_SECONDS):
    """Return a worker lease to partial only when no remote chunk was marked inflight."""
    if type(lease_seconds) is not int or lease_seconds<390:raise ValueError('Continuation lease rejected')
    clock=now or datetime.now(timezone.utc)
    if clock.tzinfo is None:raise ValueError('Aware continuation clock required')
    stamp=clock.astimezone(timezone.utc);reclaimed=[]
    with closing(sqlite3.connect(path,timeout=5)) as con, con:
        con.execute('BEGIN IMMEDIATE')
        rows=con.execute('''SELECT request_id,result_json FROM google_writer_runs
                            WHERE environment='SANDBOX' AND trigger='manual' AND status='running'
                            ''').fetchall()
        for request_id,raw in rows:
            try:state=json.loads(raw or '{}')
            except (TypeError,json.JSONDecodeError):continue
            if (not isinstance(state,dict) or state.get('plan_scope')!='ALL' or
                    state.get('status')!='APPLY_CONTINUATION_CLAIMED' or
                    state.get('auto_continue_chunks') is not True or state.get('attempted_chunk') is not None):continue
            try:
                lease=datetime.fromisoformat(state.get('recovery_claimed_at'))
                if lease.tzinfo is None or (stamp-lease.astimezone(timezone.utc)).total_seconds()<lease_seconds:continue
            except (TypeError,ValueError):continue
            unresolved=con.execute('''SELECT 1 FROM google_writer_apply_chunk_journal
                WHERE run_id=? AND scope='ALL' AND status IN ('inflight','outcome_unknown') LIMIT 1''',
                (request_id,)).fetchone()
            if unresolved:continue
            state.pop('recovery_claimed_at',None)
            state.update(status='HALTED_AFTER_VERIFIED_CHECKPOINTS',progress_state='verified',
                last_progress_at=stamp.isoformat(),attempted_chunk=None,attempted_phase=None)
            changed=con.execute("UPDATE google_writer_runs SET status='partial',finished_at=?,result_json=? WHERE request_id=? AND status='running'",
                (stamp.isoformat(),json.dumps(state,sort_keys=True),request_id)).rowcount
            if changed==1:reclaimed.append(request_id)
    return reclaimed


def _reconciliation_time(now=None):
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        raise ValueError('Aware reconciliation clock required')
    return value.astimezone(timezone.utc).isoformat()


def prepare_partial_reconciliation(path, environment, reconciliation_id,
                                   request_fingerprint, actor, *, now=None):
    """Persist a fail-closed reconciliation intent without releasing the unknown-run hold."""
    if environment != 'SANDBOX':
        raise PermissionError('Partial reconciliation is Sandbox-only')
    if (not isinstance(reconciliation_id, str) or
            not re.fullmatch(r'[0-9a-f]{32}', reconciliation_id) or
            partial_reconciliation_profile(request_fingerprint) is None or
            not isinstance(actor, str) or not actor.strip() or len(actor) > 128):
        raise ValueError('Partial reconciliation identity rejected')
    reconciliation_profile = partial_reconciliation_profile(request_fingerprint)
    evidence = reconciliation_profile['evidence']
    stamp = _reconciliation_time(now)
    evidence_raw = json.dumps(evidence, ensure_ascii=False,
                              sort_keys=True, separators=(',', ':'))
    evidence_digest = base64.urlsafe_b64encode(
        hashlib.sha256(evidence_raw.encode('utf-8')).digest()).decode('ascii').rstrip('=')
    with closing(sqlite3.connect(path, timeout=5)) as con, con:
        con.execute('BEGIN IMMEDIATE')
        con.row_factory = sqlite3.Row
        known = con.execute('SELECT 1 FROM sqlite_master WHERE type=? AND name=?',
                            ('table', 'google_writer_run_reconciliations')).fetchone()
        if not known:
            raise RuntimeError('Reconciliation storage is not initialized')
        existing = con.execute('''SELECT reconciliation_id,request_id,environment,actor,
                                         request_fingerprint,evidence_digest,evidence_json,state,
                                         original_status,original_result_json,original_actor,
                                         original_trigger,original_revision,original_started_at,
                                         apps_script_receipt_json
                                  FROM google_writer_run_reconciliations
                                  WHERE request_fingerprint=? OR reconciliation_id=?''',
                               (request_fingerprint, reconciliation_id)).fetchall()
        if existing:
            if len(existing) != 1:
                raise RuntimeError('Conflicting reconciliation history exists')
            prior = existing[0]
            if _run_close_state(con,prior['request_id']) is not None:
                raise RuntimeError('Administratively closed or closing run cannot be reconciled')
            if (prior['reconciliation_id'],prior['environment'],prior['actor'],
                    prior['request_fingerprint'],prior['evidence_digest'],prior['evidence_json']) != (
                    reconciliation_id,'SANDBOX',actor,request_fingerprint,
                    evidence_digest,evidence_raw):
                raise RuntimeError('Existing reconciliation does not match this retry')
            if (reconciliation_profile.get('require_saved_append_only_preview') and
                    prior['state'] == 'prepared'):
                _validate_partial_reconciliation_saved_run(con, prior['request_id'], reconciliation_profile)
            if prior['state'] not in {'prepared','reconciled_partial'}:
                raise RuntimeError('Reconciliation history is in an unknown state')
            run = con.execute('''SELECT status,result_json,actor,trigger,revision,started_at FROM google_writer_runs
                                 WHERE request_id=? AND environment='SANDBOX' ''',
                              (prior['request_id'],)).fetchone()
            if prior['state'] == 'prepared':
                unknown = con.execute('''SELECT request_id,status,result_json FROM google_writer_runs
                                         WHERE environment='SANDBOX' AND status='outcome_unknown' ''').fetchall()
                running = con.execute("SELECT COUNT(*) FROM google_writer_runs WHERE environment='SANDBOX' AND status='running'").fetchone()[0]
                original_identity_matches = bool(
                    run and prior['original_status'] == 'outcome_unknown' and
                    prior['original_result_json'] == run['result_json'] and
                    prior['original_actor'] == run['actor'] and
                    prior['original_trigger'] == run['trigger'] == 'manual' and
                    prior['original_revision'] == run['revision'] and
                    prior['original_started_at'] == run['started_at'])
                if reconciliation_profile.get('require_saved_append_only_preview'):
                    # The saved-Preview validator above checks the extended APPEND_ONLY
                    # run payload and its digest binding. Revalidate the original run
                    # snapshot without imposing the legacy minimal result_json shape.
                    run_result_matches = bool(
                        len(unknown) == 1 and original_identity_matches and
                        run['status'] == 'outcome_unknown' and
                        unknown[0]['result_json'] == prior['original_result_json'])
                else:
                    run_result_matches = bool(
                        original_identity_matches and run['status'] == 'outcome_unknown' and
                        run['result_json'] == '{"status": "OUTCOME_UNKNOWN_HOLD_NO_RETRY"}' and
                        prior['original_result_json'] == '{"status": "OUTCOME_UNKNOWN_HOLD_NO_RETRY"}')
                if (not run_result_matches or len(unknown) != 1 or
                        unknown[0]['request_id'] != prior['request_id'] or running or
                        prior['apps_script_receipt_json'] != '{}'):
                    raise RuntimeError('Prepared reconciliation no longer matches the blocked run')
            elif (not run or run['status'] != 'partial' or
                    json.loads(run['result_json']).get('reconciliation_id') != reconciliation_id):
                raise RuntimeError('Completed reconciliation conflicts with SQLite run state')
            return {'request_id': prior['request_id'], 'reconciliation_id': reconciliation_id,
                    'request_fingerprint': request_fingerprint, 'evidence_digest': evidence_digest,
                    'evidence': evidence, 'state': prior['state'], 'idempotent': True}
        unknown = con.execute('''SELECT request_id,environment,trigger,actor,revision,started_at,
                                      finished_at,status,result_json
                                 FROM google_writer_runs
                                 WHERE environment='SANDBOX' AND status='outcome_unknown'
                                 ORDER BY started_at''').fetchall()
        running = con.execute("SELECT COUNT(*) FROM google_writer_runs WHERE environment='SANDBOX' AND status='running'").fetchone()[0]
        if len(unknown) != 1 or running != 0:
            raise RuntimeError('Sandbox run state is not uniquely reconcilable')
        row = unknown[0]
        if request_id_fingerprint(row['request_id']) != request_fingerprint:
            raise PermissionError('Sandbox request fingerprint mismatch')
        if row['trigger'] != 'manual':
            raise RuntimeError('Sandbox run record does not match the confirmed partial-run contract')
        if reconciliation_profile.get('require_saved_append_only_preview'):
            _validate_partial_reconciliation_saved_run(con, row['request_id'], reconciliation_profile)
        elif row['result_json'] != '{"status": "OUTCOME_UNKNOWN_HOLD_NO_RETRY"}':
            raise RuntimeError('Sandbox run record does not match the confirmed partial-run contract')
        con.execute('''INSERT INTO google_writer_run_reconciliations(
                         reconciliation_id,request_id,environment,actor,request_fingerprint,
                         evidence_digest,evidence_json,state,prepared_at,original_status,
                         original_result_json,original_actor,original_trigger,original_revision,original_started_at)
                       VALUES(?,?,?,?,?,?,?,'prepared',?,?,?,?,?,?,?)''',
                    (reconciliation_id,row['request_id'],'SANDBOX',actor,request_fingerprint,
                     evidence_digest,evidence_raw,stamp,row['status'],row['result_json'],
                     row['actor'],row['trigger'],row['revision'],row['started_at']))
        return {'request_id': row['request_id'], 'reconciliation_id': reconciliation_id,
                'request_fingerprint': request_fingerprint, 'evidence_digest': evidence_digest,
                'evidence': evidence,
                'state': 'prepared', 'idempotent': False}


def finalize_partial_reconciliation(path, reconciliation_id, actor, receipt, *, now=None):
    """Release the SQLite hold only after a verified Apps Script reconciliation receipt."""
    if not isinstance(reconciliation_id, str) or not re.fullmatch(r'[0-9a-f]{32}', reconciliation_id):
        raise ValueError('Invalid reconciliation identity')
    stamp = _reconciliation_time(now)
    with closing(sqlite3.connect(path, timeout=5)) as con, con:
        con.execute('BEGIN IMMEDIATE')
        con.row_factory = sqlite3.Row
        audit = con.execute('SELECT * FROM google_writer_run_reconciliations WHERE reconciliation_id=?',
                            (reconciliation_id,)).fetchone()
        if not audit or audit['environment'] != 'SANDBOX' or audit['actor'] != actor:
            raise PermissionError('Reconciliation audit identity mismatch')
        required = {
            'environment': 'SANDBOX', 'scriptId': IDENTITIES['SANDBOX'][0],
            'spreadsheetId': IDENTITIES['SANDBOX'][1], 'contract': CONTRACT,
            'requestId': audit['request_id'], 'status': 'RECONCILED_PARTIAL',
            'reconciliationId': reconciliation_id,
            'requestFingerprint': audit['request_fingerprint'],
            'evidenceDigest': audit['evidence_digest']
        }
        if not isinstance(receipt, dict) or any(receipt.get(k) != v for k,v in required.items()) or not is_canonical_sha256_b64url(receipt.get('digest')):
            raise PermissionError('Apps Script reconciliation receipt mismatch')
        profile = partial_reconciliation_profile(audit['request_fingerprint'])
        if not profile:
            raise PermissionError('Reconciliation profile is no longer supported')
        expected_counts = profile['result_counts']
        if receipt.get('counts') != expected_counts:
            raise PermissionError('Apps Script reconciliation counters do not match the fixed profile')
        if any(receipt.get(key) != value for key, value in profile.get('receipt_fields', {}).items()):
            raise PermissionError('Apps Script reconciliation disposition does not match the fixed profile')
        if audit['state'] == 'reconciled_partial':
            run = con.execute('SELECT status,result_json FROM google_writer_runs WHERE request_id=? AND environment=?',
                              (audit['request_id'],'SANDBOX')).fetchone()
            if (not run or run['status'] != 'partial' or
                    json.loads(run['result_json']).get('reconciliation_id') != reconciliation_id):
                raise RuntimeError('Completed reconciliation history conflicts with run state')
            return {'status':'RECONCILED_PARTIAL','reconciliation_id':reconciliation_id,'idempotent':True}
        if audit['state'] != 'prepared':
            raise RuntimeError('Reconciliation is not prepared')
        run = con.execute('SELECT status,result_json FROM google_writer_runs WHERE request_id=? AND environment=?',
                          (audit['request_id'],'SANDBOX')).fetchone()
        if (not run or run['status'] != 'outcome_unknown' or
                run['result_json'] != audit['original_result_json']):
            raise RuntimeError('Original unknown run changed after preparation')
        running = con.execute("SELECT COUNT(*) FROM google_writer_runs WHERE environment='SANDBOX' AND status='running'").fetchone()[0]
        if running:
            raise RuntimeError('A Sandbox run is active during reconciliation')
        con.execute('''UPDATE google_writer_runs SET status='partial',finished_at=?,result_json=?
                       WHERE request_id=? AND environment='SANDBOX' AND status='outcome_unknown'
                         AND result_json=?''',
                    (stamp,json.dumps({'status':'RECONCILED_PARTIAL','reconciliation_id':reconciliation_id,
                                       'evidence_digest':audit['evidence_digest'],
                                       'original_status':'outcome_unknown'},sort_keys=True),
                     audit['request_id'],audit['original_result_json']))
        if con.execute('SELECT changes()').fetchone()[0] != 1:
            raise RuntimeError('Sandbox unknown-run compare-and-set failed')
        con.execute('''UPDATE google_writer_run_reconciliations
                       SET state='reconciled_partial',finished_at=?,apps_script_receipt_json=?
                       WHERE reconciliation_id=? AND state='prepared' ''',
                    (stamp,json.dumps(receipt,sort_keys=True,separators=(',',':')),reconciliation_id))
        if con.execute('SELECT changes()').fetchone()[0] != 1:
            raise RuntimeError('Reconciliation history compare-and-set failed')
        return {'status':'RECONCILED_PARTIAL','reconciliation_id':reconciliation_id,'idempotent':False}


def prepare_admin_close_unknown(path, environment, close_id, request_id, actor, reason, *, now=None):
    """Persist an idempotent close intent without changing the held run or its evidence."""
    if (environment!='SANDBOX' or not re.fullmatch(r'[0-9a-f]{32}',str(close_id or '')) or
            not re.fullmatch(r'[0-9a-f]{32}',str(request_id or '')) or
            not isinstance(actor,str) or not actor.strip() or len(actor)>128 or
            not isinstance(reason,str) or not 8<=len(reason.strip())<=500 or
            any(ord(char)<32 and char not in '\t' for char in reason)):
        raise ValueError('Administrative close identity or reason is invalid')
    reason=reason.strip()
    reason_digest=_sha256_b64(reason.encode('utf-8'))
    clock=now or datetime.now(timezone.utc)
    if clock.tzinfo is None: raise ValueError('Aware administrative close time required')
    stamp=clock.astimezone(timezone.utc).isoformat()
    with closing(sqlite3.connect(path,timeout=5)) as con, con:
        con.execute('BEGIN IMMEDIATE')
        con.row_factory=sqlite3.Row
        existing=con.execute('''SELECT * FROM google_writer_run_closures
                                WHERE close_id=? OR request_id=?''',(close_id,request_id)).fetchall()
        if existing:
            if len(existing)!=1:
                raise RuntimeError('Administrative close identity is not unique')
            saved=existing[0]
            if (saved['close_id']!=close_id or saved['request_id']!=request_id or
                    saved['actor']!=actor or saved['reason_digest']!=reason_digest or
                    saved['environment']!='SANDBOX'):
                raise PermissionError('A different administrative close intent already exists')
            return dict(saved)
        try:
            run=con.execute('''SELECT environment,trigger,actor,revision,started_at,finished_at,status,result_json
                               FROM google_writer_runs WHERE request_id=?''',(request_id,)).fetchone()
        except sqlite3.OperationalError as exc:
            if 'no such table' in str(exc).lower():
                raise RuntimeError('Google Writer run storage is unavailable') from None
            raise
        if (not run or run['environment']!='SANDBOX' or run['trigger']!='manual' or
                run['status']!='outcome_unknown' or not run['finished_at']):
            raise RuntimeError('Only a finished manual Sandbox outcome_unknown run can be closed')
        try: progress=json.loads(run['result_json'] or '{}')
        except (TypeError,json.JSONDecodeError): progress=None
        if (not isinstance(progress,dict) or
                (progress.get('outcome_unknown') is not True and
                 progress.get('status')!='OUTCOME_UNKNOWN_HOLD_NO_RETRY')):
            raise RuntimeError('Unknown-result evidence is missing or invalid')
        scope=progress.get('plan_scope')
        plan_digest=progress.get('plan_digest')
        attempted_chunk=progress.get('attempted_chunk')
        if (scope not in {'ALL','APPEND_ONLY'} or not is_canonical_sha256_b64url(plan_digest) or
                (attempted_chunk is not None and (type(attempted_chunk) is not int or not 0<=attempted_chunk<=499))):
            raise RuntimeError('Run scope or immutable plan binding is unavailable')
        if progress.get('recovery_claimed_at'):
            raise RuntimeError('Run has an active or unresolved recovery claim')
        unknown=con.execute("SELECT request_id FROM google_writer_runs WHERE environment='SANDBOX' AND status='outcome_unknown' ORDER BY request_id").fetchall()
        running=con.execute("SELECT COUNT(*) FROM google_writer_runs WHERE environment='SANDBOX' AND status='running'").fetchone()[0]
        if len(unknown)!=1 or unknown[0][0]!=request_id or running:
            raise RuntimeError('Sandbox execution lane is not uniquely held by this run')
        if con.execute('SELECT 1 FROM google_writer_run_reconciliations WHERE request_id=? LIMIT 1',
                       (request_id,)).fetchone():
            raise RuntimeError('A reconciliation intent or receipt conflicts with administrative close')
        if con.execute('SELECT 1 FROM google_writer_run_closures WHERE request_id=? LIMIT 1',
                       (request_id,)).fetchone():
            raise RuntimeError('A close intent already exists for this run')
        result_digest=_sha256_b64(run['result_json'].encode('utf-8'))
        identity={'environment':'SANDBOX','close_id':close_id,'request_id':request_id,
            'actor':actor,'scope':scope,'plan_digest':plan_digest,'attempted_chunk':attempted_chunk,
            'original_status':'outcome_unknown','original_result_digest':result_digest,
            'original_started_at':run['started_at'],'reason_digest':reason_digest}
        evidence_digest=_sha256_b64(_canonical_json(identity).encode('utf-8'))
        con.execute('''INSERT INTO google_writer_run_closures(
            close_id,request_id,environment,actor,reason,reason_digest,evidence_digest,plan_scope,
            plan_digest,attempted_chunk,original_status,original_result_digest,original_started_at,
            state,prepared_at,closed_at,receipt_json)
            VALUES(?,?,?,?,?,?,?,?,?,?,? ,?,?, 'prepared',?,NULL,'{}')''',
            (close_id,request_id,'SANDBOX',actor,reason,reason_digest,evidence_digest,scope,
             plan_digest,attempted_chunk,'outcome_unknown',result_digest,run['started_at'],stamp))
        return dict(con.execute('SELECT * FROM google_writer_run_closures WHERE close_id=?',(close_id,)).fetchone())


def finalize_admin_close_unknown(path, close_id, actor, receipt, *, now=None):
    """Mark the SQLite run terminal only after the matching Apps Script tombstone receipt."""
    if not re.fullmatch(r'[0-9a-f]{32}',str(close_id or '')) or not isinstance(actor,str) or not actor:
        raise ValueError('Administrative close identity is invalid')
    clock=now or datetime.now(timezone.utc)
    if clock.tzinfo is None: raise ValueError('Aware administrative close time required')
    stamp=clock.astimezone(timezone.utc).isoformat()
    with closing(sqlite3.connect(path,timeout=5)) as con, con:
        con.execute('BEGIN IMMEDIATE')
        con.row_factory=sqlite3.Row
        intent=con.execute('SELECT * FROM google_writer_run_closures WHERE close_id=?',(close_id,)).fetchone()
        if not intent or intent['actor']!=actor or intent['environment']!='SANDBOX':
            raise PermissionError('Administrative close audit identity mismatch')
        required={'environment':'SANDBOX','scriptId':IDENTITIES['SANDBOX'][0],
            'spreadsheetId':IDENTITIES['SANDBOX'][1],'contract':CONTRACT,
            'requestId':intent['request_id'],'status':'ADMIN_CLOSED_UNKNOWN',
            'closeId':close_id,'planScope':intent['plan_scope'],
            'disposition':'OUTCOME_UNKNOWN_NOT_CONFIRMED',
            'evidenceDigest':intent['evidence_digest'],'reasonDigest':intent['reason_digest'],
            'actor':actor}
        if (not isinstance(receipt,dict) or any(receipt.get(key)!=value for key,value in required.items()) or
                not is_canonical_sha256_b64url(receipt.get('runRecordDigest')) or
                not isinstance(receipt.get('closedAt'),str) or
                not is_canonical_sha256_b64url(receipt.get('digest')) or
                receipt.get('digest')!=_close_receipt_digest(receipt)):
            raise PermissionError('Apps Script administrative close receipt mismatch')
        run=con.execute('SELECT status,result_json,started_at FROM google_writer_runs WHERE request_id=? AND environment=?',
                        (intent['request_id'],'SANDBOX')).fetchone()
        if (not run or run['started_at']!=intent['original_started_at'] or
                _sha256_b64(run['result_json'].encode('utf-8'))!=intent['original_result_digest']):
            raise RuntimeError('Original unknown-run evidence changed after close preparation')
        if intent['state']=='closed_unknown':
            saved_receipt=json.loads(intent['receipt_json'])
            # Apps Script marks a same-ID replay as idempotent in the response;
            # that transport hint is deliberately outside the canonical receipt
            # digest, while all close bindings and the tombstone time remain bound.
            if (run['status']!='closed_unknown' or
                    _close_receipt_digest(saved_receipt)!=_close_receipt_digest(receipt)):
                raise RuntimeError('Closed-run audit conflicts with the saved receipt')
            return {'status':'ADMIN_CLOSED_UNKNOWN','close_id':close_id,
                    'request_id':intent['request_id'],'idempotent':True,
                    'disposition':'OUTCOME_UNKNOWN_NOT_CONFIRMED'}
        if intent['state']!='prepared' or run['status']!='outcome_unknown':
            raise RuntimeError('Run is no longer in its prepared unknown-result state')
        running=con.execute("SELECT COUNT(*) FROM google_writer_runs WHERE environment='SANDBOX' AND status='running'").fetchone()[0]
        if running:
            raise RuntimeError('A Sandbox Writer execution is active during close finalization')
        con.execute("UPDATE google_writer_runs SET status='closed_unknown' WHERE request_id=? AND environment='SANDBOX' AND status='outcome_unknown' AND result_json=?",
                    (intent['request_id'],run['result_json']))
        if con.execute('SELECT changes()').fetchone()[0]!=1:
            raise RuntimeError('Unknown-run close compare-and-set failed')
        receipt_raw=_canonical_json(receipt)
        con.execute("UPDATE google_writer_run_closures SET state='closed_unknown',closed_at=?,receipt_json=? WHERE close_id=? AND state='prepared'",
                    (stamp,receipt_raw,close_id))
        if con.execute('SELECT changes()').fetchone()[0]!=1:
            raise RuntimeError('Administrative close audit compare-and-set failed')
        return {'status':'ADMIN_CLOSED_UNKNOWN','close_id':close_id,
                'request_id':intent['request_id'],'idempotent':False,
                'disposition':'OUTCOME_UNKNOWN_NOT_CONFIRMED'}


def close_unknown_run(path, client, request_id, actor, close_id, reason):
    """Two-system close. An unknown Apps Script outcome leaves the SQLite hold intact."""
    intent=prepare_admin_close_unknown(path,'SANDBOX',close_id,request_id,actor,reason)
    if intent['state']=='closed_unknown':
        return {'status':'ADMIN_CLOSED_UNKNOWN','close_id':close_id,
                'request_id':request_id,'idempotent':True,
                'disposition':'OUTCOME_UNKNOWN_NOT_CONFIRMED'}
    receipt=client.invoke('close_unknown_run',request_id,actor,trigger='manual',digest=intent['plan_digest'],
        plan_scope=intent['plan_scope'],manual_authorized=True,close_id=close_id,
        close_evidence_digest=intent['evidence_digest'],reason_digest=intent['reason_digest'])
    try:
        return finalize_admin_close_unknown(path,close_id,actor,receipt)
    except (PermissionError,RuntimeError,sqlite3.Error):
        raise AdminCloseFinalizationUnknown('Apps Script close was acknowledged; SQLite hold remains until the same close ID is finalized') from None


def _prewrite_close_material(con, request_id, actor, close_id, reason, *, read_only=False):
    """Validate the immutable prewrite evidence and return only its bounded identity projection."""
    run=con.execute('''SELECT environment,trigger,actor,started_at,finished_at,status,result_json
                       FROM google_writer_runs WHERE request_id=?''',(request_id,)).fetchone()
    if not run or run[0]!='SANDBOX' or run[1]!='manual' or run[5]!='failed_safe' or not run[4]:
        raise RuntimeError('Only a finished manual Sandbox failed_safe run can use prewrite closure')
    try: result=json.loads(run[6] or '{}')
    except (TypeError,json.JSONDecodeError): result=None
    safe=result.get('safe_error') if isinstance(result,dict) else None
    stage=safe.get('stage') if isinstance(safe,dict) else None
    status=result.get('status') if isinstance(result,dict) else None
    if not isinstance(result,dict) or status not in {
            'APPS_SCRIPT_PREWRITE_REJECTED_NO_SHEET_WRITE','PRECALL_REJECTED_NO_REMOTE_CALL'}:
        raise RuntimeError('Durable failed_safe prewrite candidate evidence is missing')
    if status not in {'APPS_SCRIPT_PREWRITE_REJECTED_NO_SHEET_WRITE','PRECALL_REJECTED_NO_REMOTE_CALL'}:
        raise RuntimeError('Run result is not eligible for prewrite closure')
    if safe:
        if not isinstance(safe,dict):
            raise RuntimeError('Stored execution error evidence is invalid')
        if safe.get('category')=='apps_script_stage_error' and stage in _PREWRITE_CLOSE_STAGES:
            pass
        elif safe.get('category')=='execution_api_http_error' and type(safe.get('http_status')) is int and 400<=safe['http_status']<500:
            # Older Render code mislabeled some Execution API 4xx responses as pre-call.
            # Apps Script's locked run record and the sheet identity scan remain mandatory proof.
            stage=(_LEGACY_PREWRITE_LIMIT_STAGE if request_id==_LEGACY_PREWRITE_LIMIT_REQUEST_ID
                   else _PREWRITE_CLOSE_STAGE_SENTINEL)
        else:
            raise RuntimeError('Stored error does not establish a prewrite candidate')
    elif status in {'APPS_SCRIPT_PREWRITE_REJECTED_NO_SHEET_WRITE','PRECALL_REJECTED_NO_REMOTE_CALL'}:
        # Older v18 APPEND_ONLY handler had one generic uncertainty catch and no lastError.
        # Only this historical run may use the exact reconstructed v1 size proof below.
        stage=(_LEGACY_PREWRITE_LIMIT_STAGE if request_id==_LEGACY_PREWRITE_LIMIT_REQUEST_ID
               else _PREWRITE_CLOSE_STAGE_SENTINEL)
    if stage not in _PREWRITE_CLOSE_STAGES and stage not in {
            _PREWRITE_CLOSE_STAGE_SENTINEL,_LEGACY_PREWRITE_LIMIT_STAGE}:
        raise RuntimeError('Apps Script prewrite-stage evidence is missing or ambiguous')
    if result.get('plan_scope')!='APPEND_ONLY':
        raise RuntimeError('Prewrite closure is limited to APPEND_ONLY chunk zero')
    plan_digest=result.get('plan_digest')
    if not is_canonical_sha256_b64url(plan_digest):
        raise RuntimeError('Immutable APPEND_ONLY plan binding is unavailable')
    if result.get('outcome_unknown') or result.get('attempted_chunk') not in (None,0):
        raise RuntimeError('Run contains evidence of a possibly attempted chunk')
    if con.execute('SELECT 1 FROM google_writer_run_reconciliations WHERE request_id=? LIMIT 1',
                   (request_id,)).fetchone():
        raise RuntimeError('A reconciliation intent conflicts with prewrite closure')
    if con.execute('SELECT 1 FROM google_writer_run_closures WHERE request_id=? LIMIT 1',
                   (request_id,)).fetchone():
        raise RuntimeError('An unknown-outcome close intent conflicts with prewrite closure')
    other_active=con.execute("SELECT 1 FROM google_writer_runs WHERE environment='SANDBOX' AND status IN ('running','outcome_unknown') AND request_id<>? LIMIT 1",
                             (request_id,)).fetchone()
    if other_active:
        raise RuntimeError('Another active or unknown Sandbox run prevents lane release')
    plans=con.execute('''SELECT plan_id,plan_digest,append_only_digest,details_digest,source_digest,details_json
                         FROM google_writer_plan_journal WHERE request_id=? AND environment='SANDBOX'
                           AND actor=?''',(request_id,run[2])).fetchall()
    if len(plans)!=1:
        raise RuntimeError('Unique Sandbox Preview journal binding is unavailable')
    plan_id,stored_full_digest,stored_append_digest,details_digest,source_digest,details_raw=plans[0]
    # APPEND_ONLY run/chunk digests bind to the scoped append digest. The
    # Preview journal's plan_digest remains the full Preview digest; keep both
    # bindings explicit instead of comparing those intentionally distinct values.
    if (plan_id!=request_id or stored_append_digest!=plan_digest or
            not is_canonical_sha256_b64url(stored_full_digest) or
            not is_canonical_sha256_b64url(stored_append_digest) or
            not is_canonical_sha256_b64url(details_digest) or
            not is_canonical_sha256_b64url(source_digest)):
        raise RuntimeError('APPEND_ONLY Preview journal binding mismatch')
    try: details=json.loads(details_raw)
    except (TypeError,json.JSONDecodeError): details=None
    if (not isinstance(details,dict) or details.get('environment')!='SANDBOX' or
            details.get('plan_digest')!=stored_full_digest or
            details.get('append_only_digest')!=stored_append_digest or
            details.get('source_digest')!=source_digest or
            _preview_details_digest(details)!=details_digest or
            not isinstance(details.get('appends'),list) or not details['appends']):
        raise RuntimeError('APPEND_ONLY Preview details are invalid or do not match their digest')
    chunks=con.execute('''SELECT chunk_id,plan_id,plan_digest,source_digest,chunk_index,chunk_digest,status,expected_json
                          FROM google_writer_chunk_journal WHERE run_id=? ORDER BY chunk_index''',
                       (request_id,)).fetchall()
    if len(chunks)!=1:
        raise RuntimeError('Exactly one prepared first APPEND portion is required')
    chunk_id,c_plan_id,c_plan_digest,c_source_digest,index,chunk_digest,chunk_state,expected_raw=chunks[0]
    if (c_plan_id!=plan_id or c_plan_digest!=stored_append_digest or c_source_digest!=source_digest or
            index!=0 or chunk_state!='prepared'):
        raise RuntimeError('First APPEND portion is not durably prepared and untouched')
    try: expected=json.loads(expected_raw)
    except (TypeError,json.JSONDecodeError): expected=None
    if (not isinstance(expected,dict) or expected.get('version')!=1 or expected.get('run_id')!=request_id or
            expected.get('plan_id')!=plan_id or expected.get('scope')!='APPEND_ONLY' or
            expected.get('plan_digest')!=plan_digest or expected.get('source_digest')!=source_digest or
            expected.get('chunk_index')!=0 or not isinstance(expected.get('rows'),list) or
            not expected['rows'] or len(expected['rows'])>APPEND_JOURNAL_PAGE_ROWS or
            expected['rows']!=details['appends'][:APPEND_JOURNAL_PAGE_ROWS] or
            _sha256_b64(_canonical_json(expected).encode('utf-8'))!=chunk_digest):
        raise RuntimeError('Prepared chunk manifest does not match the immutable Preview')
    identities=[]; codes=set();legacy_manifest_rows=[]
    for item in expected['rows']:
        if not isinstance(item,dict):
            raise RuntimeError('Prepared portion contains an invalid APPEND operation')
        code=item.get('code') if isinstance(item,dict) else None
        tab=item.get('tab') if isinstance(item,dict) else None
        if (item.get('operation')!='APPEND' or tab not in {'ФОП','ЮО'} or
                not isinstance(code,str) or not code.strip() or code.strip() in codes):
            raise RuntimeError('Prepared portion contains invalid or duplicate APPEND identities')
        code=code.strip();codes.add(code);identities.append({'tab':tab,'code':code})
        if stage==_LEGACY_PREWRITE_LIMIT_STAGE:
            cells=item.get('cells')
            if isinstance(cells,list):
                formula_cell=next((cell for cell in cells if isinstance(cell,dict) and
                    cell.get('column') in {'A',0,'0'}),None)
                formula_a=formula_cell.get('new_value') if isinstance(formula_cell,dict) else None
            elif isinstance(cells,dict):
                formula_a=cells.get('0',cells.get(0,cells.get('A')))
            else: formula_a=None
            row_number=item.get('row')
            if (type(row_number) is not int or row_number<2 or not isinstance(formula_a,str) or
                    not formula_a.startswith('=')):
                raise RuntimeError('Exact legacy v1 write-ahead projection is unavailable')
            legacy_manifest_rows.append({'tab':tab,'row':row_number,'code':code,'formulaA':formula_a})
    legacy_projection_digest=(_sha256_b64(_canonical_json(legacy_manifest_rows).encode('utf-8'))
        if stage==_LEGACY_PREWRITE_LIMIT_STAGE else None)
    if (request_id==_LEGACY_PREWRITE_LIMIT_REQUEST_ID and stage==_LEGACY_PREWRITE_LIMIT_STAGE and
            len(identities)!=APPEND_JOURNAL_PAGE_ROWS):
        raise RuntimeError('Historical prewrite proof requires the complete first 25-row APPEND portion')
    identities_raw=_canonical_json([[item['tab'],item['code']] for item in identities]).encode('utf-8')
    identity_digest=_sha256_b64(identities_raw)
    reason_digest=None if read_only else _sha256_b64(reason.strip().encode('utf-8'))
    original_result_digest=_sha256_b64(run[6].encode('utf-8'))
    evidence={'environment':'SANDBOX','request_id':request_id,'actor':actor,
        'original_status':'failed_safe','original_started_at':run[3],
        'original_result_digest':original_result_digest,'plan_scope':'APPEND_ONLY','plan_digest':plan_digest,
        'details_digest':details_digest,'chunk_id':chunk_id,'chunk_digest':chunk_digest,'chunk_index':0,
        'prewrite_stage':stage,'target_identity_digest':identity_digest,'target_count':len(identities),
        'legacy_manifest_projection_digest':legacy_projection_digest}
    if not read_only:
        evidence.update(close_id=close_id,reason_digest=reason_digest)
    evidence_digest=None if read_only else _sha256_b64(_canonical_json(evidence).encode('utf-8'))
    return {'request_id':request_id,'actor':actor,'reason':None if read_only else reason.strip(),'reason_digest':reason_digest,
        'plan_scope':'APPEND_ONLY','plan_digest':plan_digest,'details_digest':details_digest,
        'chunk_id':chunk_id,'chunk_digest':chunk_digest,'chunk_index':0,'chunk_status':chunk_state,
        'prewrite_stage':stage,'target_identity_digest':identity_digest,'target_count':len(identities),
        'legacy_manifest_rows':legacy_manifest_rows if stage==_LEGACY_PREWRITE_LIMIT_STAGE else None,
        'legacy_manifest_projection_digest':legacy_projection_digest,
        'target_identities':identities,'original_status':'failed_safe',
        'original_result_digest':original_result_digest,'original_started_at':run[3],
        'evidence_digest':evidence_digest}


def prewrite_close_preflight(path, client, request_id, actor):
    """Read-only readiness check; never prepares an intent or releases the HOLD."""
    def blocked(*codes,diagnostic_code=None):
        result={'status':'BLOCKED','reason_codes':list(codes) or ['LOCAL_EVIDENCE_UNAVAILABLE'],
            'read_only':True,'sqlite_writes':0,'sheets_writes':0,'properties_writes':0}
        if isinstance(diagnostic_code,str) and re.fullmatch(r'[A-Z0-9_]{1,64}',diagnostic_code):
            result['diagnostic_code']=diagnostic_code
        return result
    if (getattr(client,'environment','SANDBOX')!='SANDBOX' or
            not re.fullmatch(r'[0-9a-f]{32}',str(request_id or '')) or
            not isinstance(actor,str) or not actor.strip() or len(actor)>128):
        return blocked('LOCAL_EVIDENCE_UNAVAILABLE')
    uri=Path(path).resolve().as_uri()+'?mode=ro'
    try:
        with closing(sqlite3.connect(uri,uri=True,timeout=5)) as con:
            con.execute('PRAGMA query_only=ON')
            con.execute('BEGIN')
            intent=con.execute('SELECT 1 FROM google_writer_prewrite_closures WHERE request_id=? LIMIT 1',
                                (request_id,)).fetchone()
            if intent:
                return blocked('CLOSE_ALREADY_EXISTS')
            material=_prewrite_close_material(con,request_id,actor,None,None,read_only=True)
    except (OSError,sqlite3.Error,ValueError,PermissionError,RuntimeError):
        return blocked('LOCAL_EVIDENCE_UNAVAILABLE')
    try:
        result=client.invoke('prewrite_close_preflight',request_id,actor,trigger='manual',
            digest=material['plan_digest'],plan_scope='APPEND_ONLY',manual_authorized=True,
            chunk_id=material['chunk_id'],chunk_digest=material['chunk_digest'],plan_id=request_id,
            chunk_index=0,prewrite_stage=material['prewrite_stage'],
            target_identity_digest=material['target_identity_digest'],target_identities=material['target_identities'],
            legacy_manifest_rows=material.get('legacy_manifest_rows'),
            legacy_manifest_projection_digest=material.get('legacy_manifest_projection_digest'))
    except ExecutionPreflightError as exc:
        safe=exc.safe_error if isinstance(exc.safe_error,dict) else {}
        diagnostic=safe.get('diagnostic_code')
        return blocked('APPS_SCRIPT_CHECK_UNAVAILABLE',diagnostic_code=(diagnostic
            if isinstance(diagnostic,str) else 'EXECUTION_PREFLIGHT_REJECTED'))
    except ExecutionConfigurationError:
        return blocked('APPS_SCRIPT_CHECK_UNAVAILABLE',diagnostic_code='EXECUTION_CONFIGURATION_REJECTED')
    except (ValueError,PermissionError,RuntimeError,sqlite3.Error):
        return blocked('APPS_SCRIPT_EVIDENCE_REJECTED')
    if not isinstance(result,dict) or result.get('read_only') is not True:
        return blocked('APPS_SCRIPT_EVIDENCE_REJECTED')
    if result.get('status')=='BLOCKED':
        return result
    if (result.get('status')!='READY' or result.get('request_id_matches') is not True or
            result.get('plan_binding')!='PASS' or result.get('chunk_binding')!='PASS' or
            result.get('manifest_binding')!='PASS' or result.get('target_code_matches')!=0 or
            result.get('run_marker_matches')!=0):
        return blocked('APPS_SCRIPT_EVIDENCE_REJECTED')
    return result


def prepare_admin_close_prewrite(path, environment, close_id, request_id, actor, reason, *, now=None):
    """Persist an audited close intent only after strict SQLite-side prewrite validation."""
    if (environment!='SANDBOX' or not re.fullmatch(r'[0-9a-f]{32}',str(close_id or '')) or
            not re.fullmatch(r'[0-9a-f]{32}',str(request_id or '')) or
            not isinstance(actor,str) or not actor.strip() or len(actor)>128 or
            not isinstance(reason,str) or not 8<=len(reason.strip())<=500 or
            any(ord(char)<32 and char not in '\t' for char in reason)):
        raise ValueError('Prewrite close identity or reason is invalid')
    clock=now or datetime.now(timezone.utc)
    if clock.tzinfo is None: raise ValueError('Aware prewrite close time required')
    stamp=clock.astimezone(timezone.utc).isoformat()
    with closing(sqlite3.connect(path,timeout=5)) as con, con:
        con.execute('BEGIN IMMEDIATE');con.row_factory=sqlite3.Row
        existing=con.execute('SELECT * FROM google_writer_prewrite_closures WHERE close_id=? OR request_id=?',
                             (close_id,request_id)).fetchall()
        if existing:
            if len(existing)!=1:
                raise RuntimeError('Prewrite close identity is not unique')
            saved=existing[0]
            reason_digest=_sha256_b64(reason.strip().encode('utf-8'))
            if (saved['close_id']!=close_id or saved['request_id']!=request_id or
                    saved['actor']!=actor or saved['reason_digest']!=reason_digest or
                    saved['environment']!='SANDBOX'):
                raise PermissionError('A different prewrite close intent already exists')
            if saved['state']=='closed_prewrite':
                return dict(saved)
            material=_prewrite_close_material(con,request_id,actor,close_id,reason)
            if saved['evidence_digest']!=material['evidence_digest']:
                raise RuntimeError('Prepared prewrite close evidence changed')
            material.update(state=saved['state'],prepared_at=saved['prepared_at'],closed_at=saved['closed_at'],
                            receipt_json=saved['receipt_json'])
            return material
        material=_prewrite_close_material(con,request_id,actor,close_id,reason)
        con.execute('''INSERT INTO google_writer_prewrite_closures(
            close_id,request_id,environment,actor,reason,reason_digest,evidence_digest,plan_scope,
            plan_digest,chunk_id,chunk_digest,chunk_index,target_identity_digest,prewrite_stage,
            original_status,original_result_digest,original_started_at,state,prepared_at,closed_at,receipt_json)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'prepared',?,NULL,'{}')''',
            (close_id,request_id,'SANDBOX',actor,material['reason'],material['reason_digest'],
             material['evidence_digest'],material['plan_scope'],material['plan_digest'],material['chunk_id'],
             material['chunk_digest'],material['chunk_index'],material['target_identity_digest'],
             material['prewrite_stage'],material['original_status'],material['original_result_digest'],
             material['original_started_at'],stamp))
        material.update(state='prepared',prepared_at=stamp,closed_at=None,receipt_json='{}')
        return material


def finalize_admin_close_prewrite(path, close_id, actor, receipt, *, now=None):
    """Release only a prewrite-failure hold after Apps Script's no-write tombstone receipt."""
    if not re.fullmatch(r'[0-9a-f]{32}',str(close_id or '')) or not isinstance(actor,str) or not actor:
        raise ValueError('Prewrite close identity is invalid')
    clock=now or datetime.now(timezone.utc)
    if clock.tzinfo is None: raise ValueError('Aware prewrite close time required')
    stamp=clock.astimezone(timezone.utc).isoformat()
    with closing(sqlite3.connect(path,timeout=5)) as con, con:
        con.execute('BEGIN IMMEDIATE');con.row_factory=sqlite3.Row
        intent=con.execute('SELECT * FROM google_writer_prewrite_closures WHERE close_id=?',(close_id,)).fetchone()
        if not intent or intent['actor']!=actor: raise PermissionError('Prewrite close intent not found')
        expected={'environment':'SANDBOX','scriptId':IDENTITIES['SANDBOX'][0],
            'spreadsheetId':IDENTITIES['SANDBOX'][1],'contract':CONTRACT,
            'requestId':intent['request_id'],'status':'ADMIN_CLOSED_PREWRITE_NO_WRITE',
            'closeId':close_id,'planScope':'APPEND_ONLY',
            'disposition':'PREWRITE_FAILURE_CONFIRMED_NO_SHEET_WRITE',
            'evidenceDigest':intent['evidence_digest'],'reasonDigest':intent['reason_digest'],
            'chunkId':intent['chunk_id'],'chunkDigest':intent['chunk_digest'],'chunkIndex':0,
            'targetIdentityDigest':intent['target_identity_digest'],
            'actor':actor}
        stage_ok=(receipt.get('prewriteStage') in _PREWRITE_CLOSE_STAGES if isinstance(receipt,dict) and
                  intent['prewrite_stage']==_PREWRITE_CLOSE_STAGE_SENTINEL else
                  isinstance(receipt,dict) and receipt.get('prewriteStage')==
                    ('append_inflight_save' if intent['prewrite_stage']==_LEGACY_PREWRITE_LIMIT_STAGE
                     else intent['prewrite_stage']))
        if intent['prewrite_stage']==_LEGACY_PREWRITE_LIMIT_STAGE:
            proof_ok=(isinstance(receipt,dict) and receipt.get('proofType')=='LEGACY_V1_WRITEAHEAD_OVERSIZE' and
                type(receipt.get('writeAheadBytes')) is int and
                receipt['writeAheadBytes']>_LEGACY_PREWRITE_LIMIT_BYTES and
                receipt.get('checkpointMaxBytes')==_LEGACY_PREWRITE_LIMIT_BYTES and
                is_canonical_sha256_b64url(receipt.get('legacyManifestProjectionDigest')))
        else:
            proof_ok=(isinstance(receipt,dict) and receipt.get('proofType')=='APPS_SCRIPT_LAST_ERROR' and
                receipt.get('writeAheadBytes')==0 and receipt.get('checkpointMaxBytes')==0 and
                receipt.get('legacyManifestProjectionDigest')=='')
        if (not isinstance(receipt,dict) or any(receipt.get(key)!=value for key,value in expected.items()) or
                not stage_ok or not proof_ok or
                not is_canonical_sha256_b64url(receipt.get('runRecordDigest')) or
                not isinstance(receipt.get('closedAt'),str) or
                not is_canonical_sha256_b64url(receipt.get('digest')) or
                receipt.get('digest')!=_prewrite_close_receipt_digest(receipt)):
            raise PermissionError('Apps Script prewrite close receipt mismatch')
        run=con.execute('''SELECT status,result_json,started_at FROM google_writer_runs
                           WHERE request_id=? AND environment='SANDBOX' ''',(intent['request_id'],)).fetchone()
        if (not run or run['started_at']!=intent['original_started_at'] or
                _sha256_b64(run['result_json'].encode('utf-8'))!=intent['original_result_digest']):
            raise RuntimeError('Original failed_safe run evidence changed after close preparation')
        if intent['state']=='closed_prewrite':
            saved=json.loads(intent['receipt_json'])
            if run['status']!='closed_prewrite' or _prewrite_close_receipt_digest(saved)!=_prewrite_close_receipt_digest(receipt):
                raise RuntimeError('Closed-prewrite audit conflicts with the saved receipt')
            return {'status':'ADMIN_CLOSED_PREWRITE_NO_WRITE','close_id':close_id,
                    'request_id':intent['request_id'],'idempotent':True,
                    'disposition':'PREWRITE_FAILURE_CONFIRMED_NO_SHEET_WRITE'}
        if intent['state']!='prepared' or run['status']!='failed_safe':
            raise RuntimeError('Run is no longer in its prepared failed_safe state')
        current_material=_prewrite_close_material(con,intent['request_id'],actor,close_id,intent['reason'])
        if (current_material['evidence_digest']!=intent['evidence_digest'] or
                current_material['original_result_digest']!=intent['original_result_digest'] or
                current_material['chunk_id']!=intent['chunk_id'] or
                current_material['chunk_digest']!=intent['chunk_digest'] or
                current_material['target_identity_digest']!=intent['target_identity_digest'] or
                current_material['prewrite_stage']!=intent['prewrite_stage'] or
                receipt.get('legacyManifestProjectionDigest')!=
                    (current_material.get('legacy_manifest_projection_digest') or '')):
            raise RuntimeError('Prewrite evidence changed before atomic close finalization')
        if con.execute("SELECT 1 FROM google_writer_runs WHERE environment='SANDBOX' AND status='running' LIMIT 1").fetchone():
            raise RuntimeError('A Sandbox Writer execution is active during prewrite close finalization')
        if con.execute('SELECT 1 FROM google_writer_run_reconciliations WHERE request_id=? LIMIT 1',(intent['request_id'],)).fetchone():
            raise RuntimeError('A reconciliation appeared during prewrite close')
        changed=con.execute("UPDATE google_writer_runs SET status='closed_prewrite' WHERE request_id=? AND environment='SANDBOX' AND status='failed_safe' AND result_json=?",
                            (intent['request_id'],run['result_json'])).rowcount
        if changed!=1: raise RuntimeError('Failed-safe prewrite close compare-and-set failed')
        receipt_raw=_canonical_json(receipt)
        changed=con.execute("UPDATE google_writer_prewrite_closures SET state='closed_prewrite',verified_prewrite_stage=?,closed_at=?,receipt_json=? WHERE close_id=? AND state='prepared'",
                            (receipt['prewriteStage'],stamp,receipt_raw,close_id)).rowcount
        if changed!=1: raise RuntimeError('Prewrite close audit compare-and-set failed')
        return {'status':'ADMIN_CLOSED_PREWRITE_NO_WRITE','close_id':close_id,
                'request_id':intent['request_id'],'idempotent':False,
                'disposition':'PREWRITE_FAILURE_CONFIRMED_NO_SHEET_WRITE'}


def close_confirmed_prewrite_failure(path, client, request_id, actor, close_id, reason):
    """Two-system prewrite close; ambiguous Apps Script response leaves both audits held."""
    intent=prepare_admin_close_prewrite(path,'SANDBOX',close_id,request_id,actor,reason)
    if intent['state']=='closed_prewrite':
        return {'status':'ADMIN_CLOSED_PREWRITE_NO_WRITE','close_id':close_id,
                'request_id':request_id,'idempotent':True,
                'disposition':'PREWRITE_FAILURE_CONFIRMED_NO_SHEET_WRITE'}
    receipt=client.invoke('close_prewrite_failure',request_id,actor,trigger='manual',digest=intent['plan_digest'],
        plan_scope='APPEND_ONLY',manual_authorized=True,close_id=close_id,
        close_evidence_digest=intent['evidence_digest'],reason_digest=intent['reason_digest'],
        chunk_id=intent['chunk_id'],chunk_digest=intent['chunk_digest'],plan_id=request_id,
        chunk_index=0,prewrite_stage=intent['prewrite_stage'],
        target_identity_digest=intent['target_identity_digest'],target_identities=intent['target_identities'],
        legacy_manifest_rows=intent.get('legacy_manifest_rows'),
        legacy_manifest_projection_digest=intent.get('legacy_manifest_projection_digest'))
    try:
        return finalize_admin_close_prewrite(path,close_id,actor,receipt)
    except (PermissionError,RuntimeError,sqlite3.Error):
        raise AdminCloseFinalizationUnknown('Apps Script prewrite tombstone was acknowledged; SQLite remains held until same close_id finalization') from None


def migrate(con):
    con.executescript('''
      CREATE TABLE IF NOT EXISTS google_writer_settings(
        singleton INTEGER PRIMARY KEY CHECK(singleton=1), enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN(0,1)),
        hour INTEGER NOT NULL DEFAULT 7 CHECK(hour BETWEEN 0 AND 23),
        minute INTEGER NOT NULL DEFAULT 0 CHECK(minute BETWEEN 0 AND 59),
        revision INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL DEFAULT '', actor TEXT NOT NULL DEFAULT '');
      INSERT OR IGNORE INTO google_writer_settings(singleton) VALUES(1);
      CREATE TABLE IF NOT EXISTS google_writer_settings_audit(
        id INTEGER PRIMARY KEY, revision INTEGER UNIQUE NOT NULL, before_json TEXT NOT NULL,
        after_json TEXT NOT NULL, actor TEXT NOT NULL, occurred_at TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS google_writer_runs(
        request_id TEXT PRIMARY KEY, environment TEXT NOT NULL, trigger TEXT NOT NULL,
        actor TEXT NOT NULL, revision INTEGER NOT NULL, started_at TEXT NOT NULL,
        finished_at TEXT, status TEXT NOT NULL, result_json TEXT NOT NULL DEFAULT '{}');
      CREATE UNIQUE INDEX IF NOT EXISTS ix_google_writer_single_lane
        ON google_writer_runs(environment) WHERE status IN ('running','outcome_unknown');
      CREATE TABLE IF NOT EXISTS google_writer_run_reconciliations(
        reconciliation_id TEXT PRIMARY KEY CHECK(length(reconciliation_id)=32),
        request_id TEXT NOT NULL UNIQUE,
        environment TEXT NOT NULL CHECK(environment='SANDBOX'),
        actor TEXT NOT NULL,
        request_fingerprint TEXT NOT NULL CHECK(length(request_fingerprint)=24),
        evidence_digest TEXT NOT NULL,
        evidence_json TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('prepared','reconciled_partial')),
        prepared_at TEXT NOT NULL,
        finished_at TEXT,
        original_status TEXT NOT NULL,
        original_result_json TEXT NOT NULL,
        original_actor TEXT NOT NULL,
        original_trigger TEXT NOT NULL,
        original_revision INTEGER NOT NULL,
        original_started_at TEXT NOT NULL,
        apps_script_receipt_json TEXT NOT NULL DEFAULT '{}');
      CREATE TABLE IF NOT EXISTS google_writer_run_closures(
        close_id TEXT PRIMARY KEY CHECK(length(close_id)=32),
        request_id TEXT NOT NULL UNIQUE,
        environment TEXT NOT NULL CHECK(environment='SANDBOX'),
        actor TEXT NOT NULL,
        reason TEXT NOT NULL,
        reason_digest TEXT NOT NULL,
        evidence_digest TEXT NOT NULL,
        plan_scope TEXT NOT NULL CHECK(plan_scope IN ('ALL','APPEND_ONLY')),
        plan_digest TEXT NOT NULL,
        attempted_chunk INTEGER,
        original_status TEXT NOT NULL CHECK(original_status='outcome_unknown'),
        original_result_digest TEXT NOT NULL,
        original_started_at TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('prepared','closed_unknown')),
        prepared_at TEXT NOT NULL,
        closed_at TEXT,
        receipt_json TEXT NOT NULL DEFAULT '{}');
      CREATE TABLE IF NOT EXISTS google_writer_prewrite_closures(
        close_id TEXT PRIMARY KEY CHECK(length(close_id)=32),
        request_id TEXT NOT NULL UNIQUE CHECK(length(request_id)=32),
        environment TEXT NOT NULL CHECK(environment='SANDBOX'),
        actor TEXT NOT NULL,
        reason TEXT NOT NULL,
        reason_digest TEXT NOT NULL,
        evidence_digest TEXT NOT NULL,
        plan_scope TEXT NOT NULL CHECK(plan_scope='APPEND_ONLY'),
        plan_digest TEXT NOT NULL,
        chunk_id TEXT NOT NULL CHECK(length(chunk_id)=32),
        chunk_digest TEXT NOT NULL,
        chunk_index INTEGER NOT NULL CHECK(chunk_index=0),
        target_identity_digest TEXT NOT NULL,
        prewrite_stage TEXT NOT NULL,
        verified_prewrite_stage TEXT,
        original_status TEXT NOT NULL CHECK(original_status='failed_safe'),
        original_result_digest TEXT NOT NULL,
        original_started_at TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('prepared','closed_prewrite')),
        prepared_at TEXT NOT NULL,
        closed_at TEXT,
        receipt_json TEXT NOT NULL DEFAULT '{}');
      CREATE INDEX IF NOT EXISTS ix_google_writer_prewrite_closures_state
        ON google_writer_prewrite_closures(state);
      CREATE TABLE IF NOT EXISTS google_writer_preview_plans(
        request_id TEXT PRIMARY KEY CHECK(length(request_id)=32),
        environment TEXT NOT NULL CHECK(environment='SANDBOX'),
        actor TEXT NOT NULL,
        plan_digest TEXT NOT NULL CHECK(length(plan_digest)=43),
        append_only_digest TEXT NOT NULL CHECK(length(append_only_digest)=43),
        details_digest TEXT NOT NULL CHECK(length(details_digest)=43),
        details_json TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL);
      CREATE INDEX IF NOT EXISTS ix_google_writer_preview_plans_expiry
        ON google_writer_preview_plans(expires_at);
      CREATE TABLE IF NOT EXISTS google_writer_plan_journal(
        plan_id TEXT PRIMARY KEY,
        request_id TEXT NOT NULL UNIQUE,
        environment TEXT NOT NULL CHECK(environment='SANDBOX'),
        actor TEXT NOT NULL,
        plan_digest TEXT NOT NULL,
        append_only_digest TEXT NOT NULL,
        details_digest TEXT NOT NULL,
        source_digest TEXT,
        created_at INTEGER NOT NULL,
        details_json TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS google_writer_chunk_journal(
        chunk_id TEXT PRIMARY KEY CHECK(length(chunk_id)=32),
        plan_id TEXT NOT NULL,
        run_id TEXT NOT NULL,
        environment TEXT NOT NULL CHECK(environment='SANDBOX'),
        scope TEXT NOT NULL CHECK(scope='APPEND_ONLY'),
        plan_digest TEXT NOT NULL,
        source_digest TEXT NOT NULL,
        chunk_index INTEGER NOT NULL CHECK(chunk_index BETWEEN 0 AND 499),
        chunk_digest TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('prepared','inflight','verified','outcome_unknown','reconciled')),
        expected_json TEXT NOT NULL,
        prepared_at TEXT NOT NULL,
        inflight_at TEXT,
        verified_at TEXT,
        receipt_json TEXT NOT NULL DEFAULT '{}',
        UNIQUE(run_id,chunk_index));
      CREATE INDEX IF NOT EXISTS ix_google_writer_chunk_journal_plan
        ON google_writer_chunk_journal(plan_id,chunk_index);
      CREATE TABLE IF NOT EXISTS google_writer_apply_chunk_journal(
        chunk_id TEXT PRIMARY KEY CHECK(length(chunk_id)=32),
        plan_id TEXT NOT NULL,
        run_id TEXT NOT NULL,
        environment TEXT NOT NULL CHECK(environment='SANDBOX'),
        scope TEXT NOT NULL CHECK(scope='ALL'),
        phase TEXT NOT NULL CHECK(phase IN ('append','update')),
        plan_digest TEXT NOT NULL,
        source_digest TEXT NOT NULL,
        chunk_index INTEGER NOT NULL CHECK(chunk_index BETWEEN 0 AND 499),
        chunk_digest TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('prepared','inflight','verified','outcome_unknown')),
        expected_json TEXT NOT NULL,
        prepared_at TEXT NOT NULL,
        inflight_at TEXT,
        verified_at TEXT,
        receipt_json TEXT NOT NULL DEFAULT '{}',
        UNIQUE(run_id,chunk_index));
      CREATE INDEX IF NOT EXISTS ix_google_writer_apply_chunk_plan
        ON google_writer_apply_chunk_journal(plan_id,chunk_index);
    ''')


def settings(con):
    try:
        row = con.execute('SELECT enabled,hour,minute,revision FROM google_writer_settings WHERE singleton=1').fetchone()
    except sqlite3.OperationalError as exc:
        if 'no such table' not in str(exc).lower(): raise
        row = None
    return dict(zip(('enabled','hour','minute','revision'),row)) if row else {'enabled':0,'hour':7,'minute':0,'revision':0}


def specification(payload):
    if (set(payload) != {'enabled','hour','minute'} or type(payload['enabled']) is not bool or
            type(payload['hour']) is not int or not 0 <= payload['hour'] <= 23 or
            type(payload['minute']) is not int or not 0 <= payload['minute'] <= 59):
        raise ValueError('Expected enabled boolean, hour 0–23, minute 0–59')
    return dict(payload)


def next_slot(config, now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None: raise ValueError('Aware scheduler clock required')
    current = now.astimezone(timezone.utc)
    day = current.astimezone(KYIV).date()
    for offset in range(8):
        wall = datetime.combine(day+timedelta(days=offset), datetime.min.time()).replace(hour=config['hour'],minute=config['minute'])
        candidates = sorted({wall.replace(tzinfo=KYIV,fold=f).astimezone(timezone.utc) for f in (0,1)
                             if wall.replace(tzinfo=KYIV,fold=f).astimezone(timezone.utc).astimezone(KYIV).replace(tzinfo=None)==wall})
        # Gap: skip that day's missing slot. Fold: use only the first occurrence.
        if candidates and candidates[0] > current: return candidates[0]
    raise ValueError('No future schedule slot')


def preview_settings(con, payload, now=None):
    after = specification(payload)
    return {'before':settings(con), 'after':after,
            'next_run':next_slot(after,now).astimezone(KYIV).isoformat(), 'timezone':'Europe/Kyiv'}


def save_settings(con, payload, expected_revision, actor, now=None):
    after = specification(payload)
    if type(expected_revision) is not int or not actor: raise ValueError('Revision and actor required')
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    before = settings(con)
    result = con.execute('''UPDATE google_writer_settings SET enabled=?,hour=?,minute=?,revision=revision+1,updated_at=?,actor=?
      WHERE singleton=1 AND revision=?''', (int(after['enabled']),after['hour'],after['minute'],stamp,actor,expected_revision))
    if result.rowcount != 1: raise RuntimeError('Schedule revision conflict')
    con.execute('INSERT INTO google_writer_settings_audit(revision,before_json,after_json,actor,occurred_at) VALUES(?,?,?,?,?)',
                (expected_revision+1,json.dumps(before),json.dumps(after),actor,stamp))
    return settings(con)


def claim_run(path, environment, request_id, actor, trigger, revision=None, now=None,
              manual_authorized=False, plan_scope='ALL', plan_digest=None, details_digest=None):
    manual_override = (manual_authorized is True and trigger == 'manual' and
                       isinstance(actor, str) and bool(actor.strip()))
    if background_jobs.disabled() and not manual_override:
        return {'claimed': False, 'status': 'background_jobs_disabled'}
    if environment not in IDENTITIES or trigger not in {'manual','scheduled'} or not re.fullmatch('[0-9a-f]{32}',request_id):
        raise ValueError('Invalid run identity')
    if (plan_scope not in {'ALL','APPEND_ONLY'} or
            (environment != 'SANDBOX' and plan_scope != 'ALL') or
            (plan_digest is not None and not is_canonical_sha256_b64url(plan_digest))):
        raise ValueError('Invalid run plan scope')
    if not Path(path).is_file(): raise ValueError('Existing execution database required')
    with closing(sqlite3.connect(path, timeout=5)) as con, con:
        con.execute('BEGIN IMMEDIATE')
        old = con.execute('SELECT environment,actor,trigger,status,result_json FROM google_writer_runs WHERE request_id=?',(request_id,)).fetchone()
        if old:
            close_state=_run_close_state(con,request_id)
            if close_state in {'closed_unknown','closed_prewrite'}:
                return {'claimed':False,'status':close_state,'result':json.loads(old[4])}
            if close_state=='prepared':
                return {'claimed':False,'status':'close_in_progress','result':json.loads(old[4])}
            if old[:3] != (environment,actor,trigger): raise PermissionError('Run identity reuse rejected')
            try: prior_meta=json.loads(old[4] or '{}')
            except (TypeError,json.JSONDecodeError): prior_meta={}
            if (prior_meta.get('plan_scope', 'ALL') != plan_scope or
                    (plan_digest is not None and prior_meta.get('plan_digest') not in (None,plan_digest))):
                raise PermissionError('Run plan scope or digest reuse rejected')
            return {'claimed':False,'status':old[3],'result':json.loads(old[4])}
        if environment=='SANDBOX':
            pending=con.execute('''SELECT r.request_id,r.result_json,pc.state
                FROM google_writer_runs r LEFT JOIN google_writer_prewrite_closures pc ON pc.request_id=r.request_id
                WHERE r.environment='SANDBOX' AND r.status='failed_safe' ''').fetchall()
            for held_id,raw_result,close_state in pending:
                try: saved=json.loads(raw_result or '{}')
                except (TypeError,json.JSONDecodeError): saved={}
                if (saved.get('status') in {'APPS_SCRIPT_PREWRITE_REJECTED_NO_SHEET_WRITE','PRECALL_REJECTED_NO_REMOTE_CALL'} and
                        saved.get('plan_scope')=='APPEND_ONLY' and close_state!='closed_prewrite'):
                    return {'claimed':False,'status':'prewrite_failure_close_required',
                            'request_id':held_id,'result':saved}
        if environment=='SANDBOX':
            resumable=con.execute("SELECT request_id,actor,result_json FROM google_writer_runs WHERE environment='SANDBOX' AND status='partial'").fetchall()
            for candidate in resumable:
                try: saved=json.loads(candidate[2] or '{}')
                except (TypeError,json.JSONDecodeError): saved={}
                if (saved.get('status')=='HALTED_AFTER_VERIFIED_CHECKPOINTS' and
                        saved.get('plan_scope') in {'APPEND_ONLY','ALL'} and
                        not saved.get('outcome_unknown') and not saved.get('attempted_chunk')):
                    required='append_only_resume_required' if saved.get('plan_scope')=='APPEND_ONLY' else 'verified_checkpoint_continuation_required'
                    return {'claimed':False,'status':required}
        config = settings(con)
        if trigger == 'scheduled' and (not config['enabled'] or revision != config['revision']):
            return {'claimed':False,'status':'schedule_changed'}
        try:
            if environment=='SANDBOX' and details_digest is not None and not is_canonical_sha256_b64url(details_digest):
                raise ValueError('Invalid Preview detail digest')
            initial={}
            if environment=='SANDBOX':
                initial={'plan_scope':plan_scope,'plan_digest':plan_digest,'details_digest':details_digest}
                if plan_digest and details_digest:
                    saved=con.execute('''SELECT details_json FROM google_writer_plan_journal
                        WHERE request_id=? AND environment='SANDBOX' AND actor=?
                          AND details_digest=? AND (plan_digest=? OR append_only_digest=?)''',
                        (request_id,actor,details_digest,plan_digest,plan_digest)).fetchone()
                    if saved:
                        try: saved_details=json.loads(saved[0])
                        except (TypeError,json.JSONDecodeError): saved_details={}
                        if isinstance(saved_details,dict):
                            initial['planned_counts']={'append':len(saved_details.get('appends',[]))
                                if isinstance(saved_details.get('appends'),list) else 0,
                                'update':(len(saved_details.get('updates',[]))
                                    if plan_scope=='ALL' and isinstance(saved_details.get('updates'),list) else 0),
                                'conflict':len(saved_details.get('conflicts',[]))
                                if isinstance(saved_details.get('conflicts'),list) else 0,
                                'error':len(saved_details.get('errors',[]))
                                if isinstance(saved_details.get('errors'),list) else 0}
                initial.update(progress_state='preparing',last_progress_at=(now or datetime.now(timezone.utc)).isoformat(),
                    last_confirmed_progress_at=None)
                continuation_enabled=(plan_scope in {'APPEND_ONLY','ALL'} and
                    os.getenv('PQM_SANDBOX_AUTO_CONTINUE_CHUNKS','1').strip().lower() not in {'0','false','no','off'})
                if continuation_enabled and details_digest:
                    digest_column='append_only_digest' if plan_scope=='APPEND_ONLY' else 'plan_digest'
                    journal=con.execute(f'''SELECT source_digest FROM google_writer_plan_journal
                                           WHERE request_id=? AND environment='SANDBOX' AND actor=?
                                             AND {digest_column}=? AND details_digest=?''',
                                        (request_id,actor,plan_digest,details_digest)).fetchone()
                    if journal and is_canonical_sha256_b64url(journal[0]):
                        initial['auto_continue_chunks']=True
            initial_result=json.dumps(initial,sort_keys=True)
            con.execute('INSERT INTO google_writer_runs(request_id,environment,trigger,actor,revision,started_at,status,result_json) VALUES(?,?,?,?,?,?,?,?)',
                        (request_id,environment,trigger,actor,config['revision'],(now or datetime.now(timezone.utc)).isoformat(),'running',initial_result))
        except sqlite3.IntegrityError:
            return {'claimed':False,'status':'another_run_or_unknown_outcome'}
        return {'claimed':True,'status':'running'}


def load_append_only_resume_candidate(path, request_id, actor):
    if not re.fullmatch(r'[0-9a-f]{32}',str(request_id or '')) or not actor:
        raise ValueError('Invalid continuation identity')
    uri=Path(path).resolve().as_uri()+'?mode=ro'
    with closing(sqlite3.connect(uri,uri=True,timeout=5)) as con:
        con.execute('PRAGMA query_only=ON')
        if _run_close_state(con,request_id) is not None:
            raise PermissionError('Administratively closed or closing run cannot be resumed')
        row=con.execute('''SELECT environment,actor,trigger,status,result_json FROM google_writer_runs
          WHERE request_id=?''',(request_id,)).fetchone()
    if not row or row[0]!='SANDBOX' or row[1]!=actor or row[2]!='manual' or row[3]!='partial':
        raise ValueError('No resumable Sandbox APPEND_ONLY run')
    try: progress=json.loads(row[4] or '{}')
    except (TypeError,json.JSONDecodeError): raise ValueError('Saved continuation checkpoint is invalid') from None
    if (not isinstance(progress,dict) or progress.get('status')!='HALTED_AFTER_VERIFIED_CHECKPOINTS' or
            progress.get('plan_scope')!='APPEND_ONLY' or progress.get('outcome_unknown') or
            progress.get('attempted_chunk') is not None or type(progress.get('next_chunk')) is not int or
            progress['next_chunk']<1 or progress.get('last_verified_chunk')!=progress['next_chunk']-1 or
            progress.get('checkpoint_digest') is None or
            not is_canonical_sha256_b64url(progress.get('checkpoint_digest')) or
            not is_canonical_sha256_b64url(progress.get('plan_digest')) or
            not isinstance(progress.get('verified_totals'),dict) or
            type(progress['verified_totals'].get('append')) is not int or
            progress['verified_totals']['append']<1 or
            progress['verified_totals'].get('update')!=0):
        raise ValueError('Saved continuation checkpoint is incomplete or uncertain')
    return {'request_id':request_id,'actor':actor,'plan_digest':progress['plan_digest'],
            'next_chunk':progress['next_chunk'],'checkpoint_digest':progress['checkpoint_digest'],
            'verified_totals':progress['verified_totals'],'details_digest':progress.get('details_digest')}


def claim_append_only_resume(path, candidate, *, now=None):
    request_id=candidate.get('request_id') if isinstance(candidate,dict) else None
    actor=candidate.get('actor') if isinstance(candidate,dict) else None
    if (not isinstance(candidate,dict) or not re.fullmatch(r'[0-9a-f]{32}',str(request_id or '')) or
            not actor or not is_canonical_sha256_b64url(candidate.get('plan_digest')) or
            not is_canonical_sha256_b64url(candidate.get('checkpoint_digest')) or
            type(candidate.get('next_chunk')) is not int or candidate['next_chunk']<1):
        raise ValueError('Invalid APPEND_ONLY resume claim')
    with closing(sqlite3.connect(path,timeout=5)) as con, con:
        con.execute('BEGIN IMMEDIATE')
        if _run_close_state(con,request_id) is not None:
            return {'claimed':False,'status':'closed_or_closing'}
        row=con.execute("SELECT environment,actor,trigger,status,result_json FROM google_writer_runs WHERE request_id=?",
                        (request_id,)).fetchone()
        if not row or row[:4]!=('SANDBOX',actor,'manual','partial'):
            return {'claimed':False,'status':'resume_state_changed'}
        active=con.execute("SELECT request_id FROM google_writer_runs WHERE environment='SANDBOX' AND status IN ('running','outcome_unknown') AND request_id<>? LIMIT 1",
                           (request_id,)).fetchone()
        if active:
            return {'claimed':False,'status':'another_run_or_unknown_outcome'}
        try: progress=json.loads(row[4] or '{}')
        except (TypeError,json.JSONDecodeError): return {'claimed':False,'status':'resume_checkpoint_invalid'}
        if (progress.get('status')!='HALTED_AFTER_VERIFIED_CHECKPOINTS' or
                progress.get('plan_scope')!='APPEND_ONLY' or progress.get('outcome_unknown') or
                progress.get('next_chunk')!=candidate['next_chunk'] or
                progress.get('plan_digest')!=candidate['plan_digest'] or
                progress.get('checkpoint_digest')!=candidate['checkpoint_digest']):
            return {'claimed':False,'status':'resume_checkpoint_changed'}
        progress=progress|{'status':'APPEND_ONLY_RESUME_CLAIMED',
                           'resume_attempts':int(progress.get('resume_attempts',0))+1,
                           'resume_claimed_at':(now or datetime.now(timezone.utc)).isoformat()}
        updated=con.execute("UPDATE google_writer_runs SET status='running',finished_at=NULL,result_json=? WHERE request_id=? AND status='partial'",
                            (json.dumps(progress,sort_keys=True),request_id))
        if updated.rowcount!=1: return {'claimed':False,'status':'resume_claim_race'}
    return {'claimed':True,'status':'running'}


def finish_run(path, request_id, status, result):
    if status not in {'complete','partial','failed_safe','outcome_unknown'}: raise ValueError('Unknown run status')
    result=dict(result) if isinstance(result,dict) else result
    with closing(sqlite3.connect(path,timeout=5)) as con, con:
        row=con.execute("SELECT result_json FROM google_writer_runs WHERE request_id=? AND status='running'",
                        (request_id,)).fetchone()
        if row:
            try: progress=json.loads(row[0] or '{}')
            except (TypeError,json.JSONDecodeError): progress={}
            totals=progress.get('verified_totals') if isinstance(progress,dict) else None
            if isinstance(totals,dict) and isinstance(result,dict):
                result=dict(result)
                last=result.get('counts',{}) if isinstance(result.get('counts'),dict) else {}
                result['counts']={**last,'append':int(totals.get('append',0)),
                    'update':int(totals.get('update',0)),'batches':int(totals.get('batches',0))}
            if isinstance(progress,dict) and isinstance(result,dict):
                result=dict(result)
                for key in ('planned_counts','last_recovered_error','last_progress_at',
                            'last_confirmed_progress_at','plan_scope','plan_digest','details_digest'):
                    if key in progress:result[key]=progress[key]
                result['progress_state']=status
        con.execute("UPDATE google_writer_runs SET status=?,finished_at=?,result_json=? WHERE request_id=? AND status='running'",
                    (status,datetime.now(timezone.utc).isoformat(),json.dumps(result),request_id))
    return result


def checkpoint_run(path, request_id, step_result):
    """Persist only a remotely verified chunk receipt while the run remains held."""
    with closing(sqlite3.connect(path,timeout=5)) as con, con:
        con.execute('BEGIN IMMEDIATE')
        row=con.execute("SELECT status,result_json FROM google_writer_runs WHERE request_id=? AND environment='SANDBOX'",
                        (request_id,)).fetchone()
        recovered_receipt = step_result.get('status')=='CHUNK_RECOVERED'
        allowed_run_status = {'running','outcome_unknown'} if recovered_receipt else {'running'}
        if not row or row[0] not in allowed_run_status:
            raise RuntimeError('Apply checkpoint no longer owns its run')
        previous=json.loads(row[1] or '{}')
        totals=previous.get('verified_totals',{'append':0,'update':0,'batches':0})
        for key in ('append','update','batches'):
            totals[key]=int(totals.get(key,0))+int(step_result.get('counts',{}).get(key,0))
        if (not is_canonical_sha256_b64url(step_result.get('checkpointDigest')) or
                step_result.get('planScope')!=previous.get('plan_scope','ALL') or
                (previous.get('plan_scope')=='APPEND_ONLY' and step_result.get('counts',{}).get('update',0)!=0)):
            raise RuntimeError('Apply checkpoint receipt was incomplete or outside its plan scope')
        chunk_id=step_result.get('chunkId')
        if chunk_id is not None:
            chunk=con.execute('''SELECT plan_id,run_id,scope,phase,plan_digest,chunk_digest,status,expected_json
                                 FROM google_writer_apply_chunk_journal WHERE chunk_id=?''',(chunk_id,)).fetchone()
            if chunk:
                try: expected=json.loads(chunk[7])
                except (TypeError,json.JSONDecodeError): expected=None
                counts=step_result.get('counts',{})
                operations=expected.get('operations',[]) if isinstance(expected,dict) else []
                expected_append=len(operations) if chunk[3]=='append' else 0
                expected_update=len(operations) if chunk[3]=='update' else 0
                if (not isinstance(expected,dict) or chunk[1]!=request_id or chunk[2]!=previous.get('plan_scope','ALL') or
                        chunk[5]!=step_result.get('chunkDigest') or chunk[4]!=step_result.get('digest') or
                        chunk[0]!=step_result.get('planId') or chunk[6]!='inflight' or
                        chunk[3]!=step_result.get('phase') or step_result.get('chunkIndex')!=expected.get('chunk_index') or
                        expected_append!=counts.get('append') or expected_update!=counts.get('update') or
                        step_result.get('planScope')!=chunk[2]):
                    raise RuntimeError('Apply chunk receipt did not match the durable write-ahead journal')
                receipt_raw=_canonical_json({key:step_result.get(key) for key in (
                    'status','digest','planScope','chunkIndex','nextChunk','more','phase','checkpointDigest',
                    'chunkId','chunkDigest','planId','counts')})
                if recovered_receipt:
                    changed=con.execute("UPDATE google_writer_apply_chunk_journal SET status='verified',verified_at=?,receipt_json=? WHERE chunk_id=? AND status IN ('inflight','outcome_unknown')",
                        (datetime.now(timezone.utc).isoformat(),receipt_raw,chunk_id)).rowcount
                else:
                    changed=con.execute("UPDATE google_writer_apply_chunk_journal SET status='verified',verified_at=?,receipt_json=? WHERE chunk_id=? AND status='inflight'",
                        (datetime.now(timezone.utc).isoformat(),receipt_raw,chunk_id)).rowcount
                if changed!=1: raise RuntimeError('Apply chunk journal receipt compare-and-set failed')
            else:
                chunk=con.execute('''SELECT plan_id,run_id,scope,plan_digest,chunk_digest,status,expected_json
                                     FROM google_writer_chunk_journal WHERE chunk_id=?''',(chunk_id,)).fetchone()
                try: expected=json.loads(chunk[6]) if chunk else None
                except (TypeError,json.JSONDecodeError): expected=None
                counts=step_result.get('counts',{})
                if (not chunk or chunk[1]!=request_id or chunk[2]!='APPEND_ONLY' or
                        chunk[5]!='inflight' or chunk[3]!=step_result.get('digest') or
                        step_result.get('planId')!=chunk[0] or
                        step_result.get('chunkDigest')!=chunk[4] or
                        not isinstance(expected,dict) or
                        counts.get('append')!=len(expected.get('rows',[])) or counts.get('update')!=0 or
                        step_result.get('phase')!='append'):
                    raise RuntimeError('Append chunk receipt did not match the durable write-ahead journal')
                receipt_raw=_canonical_json({key:step_result.get(key) for key in (
                    'status','digest','planScope','chunkIndex','nextChunk','more','phase','checkpointDigest',
                    'chunkId','chunkDigest','planId','counts')})
                changed=con.execute("UPDATE google_writer_chunk_journal SET status='verified',verified_at=?,receipt_json=? WHERE chunk_id=? AND status='inflight'",
                    (datetime.now(timezone.utc).isoformat(),receipt_raw,chunk_id)).rowcount
                if changed!=1: raise RuntimeError('Append chunk journal receipt compare-and-set failed')
        progress=previous|{'status':'APPLY_PROGRESS_CHECKPOINTED','next_chunk':step_result['nextChunk'],
                  'last_verified_chunk':step_result['chunkIndex'],'last_phase':step_result.get('phase'),
                  'last_step_counts':step_result.get('counts',{}),'verified_totals':totals,
                  'plan_digest':step_result.get('digest'), 'plan_scope':previous.get('plan_scope','ALL'),
                  'checkpoint_digest':step_result['checkpointDigest'],
                  'details_digest':previous.get('details_digest'),
                  'resume_attempts':int(previous.get('resume_attempts',0)),
                  'auto_continue_chunks':previous.get('auto_continue_chunks') is True,
                  'progress_state':'verified','attempted_chunk':None,
                  'last_progress_at':datetime.now(timezone.utc).isoformat(),
                  'last_confirmed_progress_at':datetime.now(timezone.utc).isoformat()}
        if recovered_receipt:
            recovery_error=step_result.get('_recovered_apply_error') or previous.get('safe_error')
            if isinstance(recovery_error,dict) and set(recovery_error).issuperset({'stage','category','exception_type'}):
                progress['last_recovered_error']=_safe_apply_error('apply_recovery',ExecutionOutcomeUnknown(
                    safe_error=recovery_error))
            progress.pop('safe_error',None)
        next_run_status='running' if recovered_receipt else row[0]
        con.execute("UPDATE google_writer_runs SET status=?,finished_at=NULL,result_json=? WHERE request_id=? AND status=?",
                    (next_run_status,json.dumps(progress,sort_keys=True),request_id,row[0]))
        if con.execute('SELECT changes()').fetchone()[0]!=1:
            raise RuntimeError('Apply checkpoint run compare-and-set failed')


def hold_unknown_run(path, request_id, *, attempted_chunk, digest, checkpoint_digest=None, chunk_id=None,
                     phase=None, safe_error=None):
    """Retain verified local checkpoints while holding an ambiguous remote step."""
    with closing(sqlite3.connect(path,timeout=5)) as con, con:
        con.execute('BEGIN IMMEDIATE')
        row=con.execute("SELECT status,result_json FROM google_writer_runs WHERE request_id=? AND environment='SANDBOX'",
                        (request_id,)).fetchone()
        if not row or row[0] != 'running':
            raise RuntimeError('Apply outcome hold no longer owns its run')
        previous=json.loads(row[1] or '{}')
        if not isinstance(previous,dict): previous={}
        held=previous|{'status':'OUTCOME_UNKNOWN_HOLD_NO_RETRY',
            'outcome_unknown':True,'attempted_chunk':attempted_chunk,'plan_digest':digest,
            'attempted_checkpoint_digest':checkpoint_digest,
            'attempted_phase':phase or previous.get('attempted_phase'),
            'safe_error':safe_error if isinstance(safe_error,dict) else previous.get('safe_error'),
            'last_progress_at':datetime.now(timezone.utc).isoformat()}
        con.execute("UPDATE google_writer_runs SET status='outcome_unknown',finished_at=?,result_json=? WHERE request_id=? AND status='running'",
                    (datetime.now(timezone.utc).isoformat(),json.dumps(held,sort_keys=True),request_id))
        if chunk_id:
            con.execute("UPDATE google_writer_chunk_journal SET status='outcome_unknown' WHERE chunk_id=? AND run_id=? AND status='inflight'",
                        (chunk_id,request_id))
            con.execute("UPDATE google_writer_apply_chunk_journal SET status='outcome_unknown' WHERE chunk_id=? AND run_id=? AND status='inflight'",
                        (chunk_id,request_id))


def finish_partial_after_checkpoints(path, request_id, *, verified_chunks, next_chunk, digest):
    """Stop safely after verified work while retaining its durable progress record."""
    with closing(sqlite3.connect(path,timeout=5)) as con, con:
        con.execute('BEGIN IMMEDIATE')
        row=con.execute("SELECT status,result_json FROM google_writer_runs WHERE request_id=? AND environment='SANDBOX'",
                        (request_id,)).fetchone()
        if not row or row[0] != 'running':
            raise RuntimeError('Apply partial completion no longer owns its run')
        previous=json.loads(row[1] or '{}')
        if not isinstance(previous,dict): previous={}
        stopped=previous|{'status':'HALTED_AFTER_VERIFIED_CHECKPOINTS',
            'verified_chunks':verified_chunks,'next_chunk':next_chunk,'plan_digest':digest}
        con.execute("UPDATE google_writer_runs SET status='partial',finished_at=?,result_json=? WHERE request_id=? AND status='running'",
                    (datetime.now(timezone.utc).isoformat(),json.dumps(stopped,sort_keys=True),request_id))


def continue_append_only_checkpoint(path, client, request_id, actor, *, digest, guard=lambda:True,
                                    manual_authorized=True, max_append_chunks=4):
    """Read-only remote checkpoint preflight, CAS claim, then continue only the next verified page."""
    candidate=load_append_only_resume_candidate(path,request_id,actor)
    checked=client.invoke('resume_check',request_id,actor,trigger='manual',digest=candidate['plan_digest'],
        plan_scope='APPEND_ONLY',manual_authorized=manual_authorized,chunk_index=candidate['next_chunk'],
        expected_checkpoint_digest=candidate['checkpoint_digest'])
    details=checked.get('planDetails') if isinstance(checked,dict) else None
    if (checked.get('status')!='RESUME_READY' or checked.get('digest')!=candidate['plan_digest'] or
            checked.get('checkpointDigest')!=candidate['checkpoint_digest'] or
            checked.get('nextChunk')!=candidate['next_chunk'] or not isinstance(details,dict) or
            details.get('updates')!=[] or not isinstance(details.get('appends'),list) or
            checked.get('counts',{}).get('append')!=len(details['appends']) or
            checked.get('counts',{}).get('update')!=0):
        raise ExecutionPreflightError('Checkpoint continuation preflight mismatch; no write was requested')
    claimed=claim_append_only_resume(path,candidate)
    if not claimed.get('claimed'):
        return {'status':'CONTINUATION_NOT_CLAIMED','reason':claimed.get('status')}
    return execute_claimed(path,client,request_id,actor,trigger='manual',digest=candidate['plan_digest'],
        guard=guard,manual_authorized=manual_authorized,plan_scope='APPEND_ONLY',
        start_chunk=candidate['next_chunk'],checkpoint_digest=candidate['checkpoint_digest'],
        max_append_chunks=max_append_chunks)


def execute_claimed(path, client, request_id, actor, *, trigger='manual', digest=None,
                    guard=lambda:True, manual_authorized=False, plan_scope='ALL',
                    start_chunk=0, checkpoint_digest=None, max_append_chunks=4,
                    max_apply_chunks=APPLY_CHUNKS_PER_WORKER):
    """One common writer for manual and scheduled calls, no automatic retry."""
    manual_override = (manual_authorized is True and trigger == 'manual' and
                       isinstance(actor, str) and bool(actor.strip()))
    if background_jobs.disabled() and not manual_override:
        return {'status': 'BACKGROUND_JOBS_DISABLED'}
    verified_steps=0
    chunk_index=start_chunk
    active_chunk_id=None
    active_phase=None
    stage='preflight'
    try:
        if not guard(): raise ExecutionConfigurationError('Execution guard changed before preview')
        if digest is None:
            digest = client.invoke('preview',request_id,actor,trigger=trigger,
                                   manual_authorized=manual_override)['digest']
        if not checkpoint_apply_enabled(getattr(client,'environment',None)):
            if (background_jobs.disabled() and not manual_override) or not guard():
                raise ExecutionConfigurationError('Execution guard changed before Apply')
            result=client.invoke('apply',request_id,actor,trigger=trigger,digest=digest,
                                 manual_authorized=manual_override)
            status='complete' if result['status']=='COMPLETE' else 'partial' if result['status'] in {
                'COMPLETE_WITH_CONFLICTS','PARTIAL_SAFE_OPERATIONS_REMAIN'} else 'outcome_unknown'
            finish_run(path,request_id,status,result)
            return result
        while True:
            if (background_jobs.disabled() and not manual_override) or not guard():
                raise ExecutionConfigurationError('Execution guard changed before next Apply checkpoint')
            chunk_binding={}
            stage='prepare_chunk'
            if getattr(client,'environment',None)=='SANDBOX' and plan_scope=='APPEND_ONLY':
                try:
                    with closing(sqlite3.connect(path,timeout=5)) as con:
                        run_state=con.execute('SELECT result_json FROM google_writer_runs WHERE request_id=? AND status=\'running\'',
                                              (request_id,)).fetchone()
                    run_meta=json.loads(run_state[0] or '{}') if run_state else {}
                    chunk=prepare_append_chunk(path,request_id,actor,digest,run_meta.get('details_digest'),chunk_index)
                    if chunk['status']!='prepared':
                        raise RuntimeError('Append chunk is not new; no remote replay is allowed')
                    if not mark_append_chunk_inflight(path,chunk['chunk_id']):
                        raise RuntimeError('Append chunk was already confirmed; no remote replay is allowed')
                    active_chunk_id=chunk['chunk_id']
                    active_phase='append'
                    chunk_binding={'chunk_id':chunk['chunk_id'],'chunk_digest':chunk['chunk_digest'],
                                   'plan_id':chunk['plan_id']}
                except Exception:
                    raise ExecutionPreflightError('Durable APPEND_ONLY chunk preflight rejected; no Apps Script call') from None
            elif getattr(client,'environment',None)=='SANDBOX' and plan_scope=='ALL':
                try:
                    with closing(sqlite3.connect(path,timeout=5)) as con:
                        run_state=con.execute('SELECT result_json FROM google_writer_runs WHERE request_id=? AND status=\'running\'',
                                              (request_id,)).fetchone()
                    run_meta=json.loads(run_state[0] or '{}') if run_state else {}
                    chunk=prepare_apply_chunk(path,request_id,actor,digest,run_meta.get('details_digest'),
                                              'ALL',chunk_index)
                    if chunk['status']!='prepared':
                        raise RuntimeError('Apply chunk is already in flight or confirmed; no remote replay')
                    mark_apply_chunk_inflight(path,chunk['chunk_id'])
                    active_chunk_id=chunk['chunk_id']
                    active_phase=chunk['phase']
                    chunk_binding={'chunk_id':chunk['chunk_id'],'chunk_digest':chunk['chunk_digest'],
                        'plan_id':chunk['plan_id'],'chunk_phase':chunk['phase'],
                        'chunk_added_at':chunk['added_at'],
                        'chunk_details_digest':chunk['details_digest']}
                except Exception:
                    raise ExecutionPreflightError('Durable Apply chunk preflight rejected; no Apps Script call') from None
            try:
                stage='apps_script_apply'
                result = client.invoke('apply',request_id,actor,trigger=trigger,digest=digest,
                                       plan_scope=plan_scope,manual_authorized=manual_override,chunk_index=chunk_index,
                                       expected_checkpoint_digest=checkpoint_digest,**chunk_binding)
            except ExecutionOutcomeUnknown as apply_error:
                if not chunk_binding:
                    raise
                if plan_scope=='ALL':
                    stage='apps_script_recovery'
                    try:
                        recovered=client.invoke('recover_apply_chunk',request_id,actor,trigger='manual',digest=digest,
                            plan_scope='ALL',manual_authorized=manual_override,chunk_index=chunk_index,**chunk_binding)
                    except Exception as recovery_error:
                        primary=_safe_apply_error('apps_script_apply',apply_error)
                        recovery=_safe_apply_error('apps_script_recovery',recovery_error)
                        raise ExecutionOutcomeUnknown('Apply and its read-only recovery both need review',safe_error={
                            'stage':recovery['stage'],'category':recovery['category'],
                            'exception_type':recovery['exception_type'],
                            'primary_stage':primary['stage'],'primary_category':primary['category'],
                            'recovery_stage':recovery['stage'],'recovery_category':recovery['category'],
                            **({'primary_http_status':primary['http_status']} if 'http_status' in primary else {}),
                            **({'http_status':recovery['http_status']} if 'http_status' in recovery else {})}) from None
                    if recovered.get('status') not in {'CHUNK_RECOVERED','CHUNK_NOT_APPLIED','CHUNK_AMBIGUOUS'}:
                        raise ExecutionOutcomeUnknown('Apply chunk recovery did not establish a safe state',
                            safe_error=apply_error.safe_error)
                    if recovered.get('status')!='CHUNK_RECOVERED':
                        raise ExecutionOutcomeUnknown('Apply chunk was not fully confirmed; no automatic retry',
                            safe_error=apply_error.safe_error or {
                                'stage':'read_only_recovery','category':recovered.get('status','ambiguous').lower(),
                                'exception_type':'ExecutionOutcomeUnknown'})
                    recovered['_recovered_apply_error']=apply_error.safe_error or _safe_apply_error('apps_script_apply',apply_error)
                    result=recovered
                else:
                    stage='apps_script_recovery'
                    try:
                        recovered=client.invoke('recover_append_chunk',request_id,actor,trigger='manual',digest=digest,
                            plan_scope='APPEND_ONLY',manual_authorized=manual_override,chunk_index=chunk_index,
                            chunk_id=chunk_binding['chunk_id'],chunk_digest=chunk_binding['chunk_digest'],
                            plan_id=chunk_binding['plan_id'])
                    except Exception as recovery_error:
                        primary=_safe_apply_error('apps_script_apply',apply_error)
                        recovery=_safe_apply_error('apps_script_recovery',recovery_error)
                        raise ExecutionOutcomeUnknown('Apply and its read-only recovery both need review',safe_error={
                            'stage':recovery['stage'],'category':recovery['category'],
                            'exception_type':recovery['exception_type'],
                            'primary_stage':primary['stage'],'primary_category':primary['category'],
                            'recovery_stage':recovery['stage'],'recovery_category':recovery['category'],
                            **({'primary_http_status':primary['http_status']} if 'http_status' in primary else {}),
                            **({'http_status':recovery['http_status']} if 'http_status' in recovery else {})}) from None
                    if recovered.get('status')!='CHUNK_RECOVERED':
                        raise ExecutionOutcomeUnknown('Append chunk recovery did not establish a safe state',
                            safe_error=apply_error.safe_error)
                    recovered['_recovered_apply_error']=apply_error.safe_error or _safe_apply_error('apps_script_apply',apply_error)
                    result=recovered
            if result['status'] in {'APPLY_CHUNK_VERIFIED','CHUNK_RECOVERED'}:
                stage='receipt_checkpoint_persist'
                checkpoint_run(path,request_id,result)
                active_chunk_id=None
                verified_steps+=1
                chunk_index=result['nextChunk']
                checkpoint_digest=result['checkpointDigest']
                if result['status']=='CHUNK_RECOVERED' and not result.get('more'):
                    final_status='complete' if result.get('counts',{}).get('conflict',0)==0 and result.get('counts',{}).get('error',0)==0 else 'partial'
                    return finish_run(path,request_id,final_status,result)
                if plan_scope=='APPEND_ONLY' and verified_steps>=max_append_chunks and result['more']:
                    finish_partial_after_checkpoints(path,request_id,verified_chunks=chunk_index,
                        next_chunk=chunk_index,digest=digest)
                    with closing(sqlite3.connect(path,timeout=5)) as con:
                        state_row=con.execute('SELECT result_json FROM google_writer_runs WHERE request_id=?',(request_id,)).fetchone()
                    try: auto_continue=bool(json.loads(state_row[0] or '{}').get('auto_continue_chunks'))
                    except (TypeError,json.JSONDecodeError): auto_continue=False
                    if auto_continue and guard():
                        try:
                            return continue_append_only_checkpoint(path,client,request_id,actor,digest=digest,
                                guard=guard,manual_authorized=manual_override,max_append_chunks=max_append_chunks)
                        except (ExecutionPreflightError,ExecutionConfigurationError,ExecutionOutcomeUnknown):
                            # Checkpoint is confirmed; failed continuation preflight is safe to defer.
                            return {'status':'HALTED_AFTER_VERIFIED_CHECKPOINTS','verified_chunks':chunk_index,
                                    'next_chunk':chunk_index,'checkpoint_digest':checkpoint_digest,
                                    'continuation_preflight':'DEFERRED_NO_WRITE'}
                    return {'status':'HALTED_AFTER_VERIFIED_CHECKPOINTS','verified_chunks':chunk_index,
                            'next_chunk':chunk_index,'checkpoint_digest':checkpoint_digest}
                if plan_scope=='ALL' and verified_steps>=max_apply_chunks and result['more']:
                    finish_partial_after_checkpoints(path,request_id,verified_chunks=chunk_index,
                        next_chunk=chunk_index,digest=digest)
                    return {'status':'HALTED_AFTER_VERIFIED_CHECKPOINTS','verified_chunks':chunk_index,
                        'next_chunk':chunk_index,'checkpoint_digest':checkpoint_digest}
                continue
            if result.get('chunkId'):
                stage='receipt_checkpoint_persist'
                checkpoint_run(path,request_id,result)
                active_chunk_id=None
            status = 'complete' if result['status']=='COMPLETE' else 'partial'
            return finish_run(path,request_id,status,result)
    except ExecutionRemotePrewriteRejected as remote_prewrite_error:
        if active_chunk_id:
            (reset_apply_chunk_preflight if plan_scope=='ALL' else reset_append_chunk_preflight)(path,active_chunk_id)
        if verified_steps or start_chunk>0:
            finish_partial_after_checkpoints(path,request_id,verified_chunks=chunk_index,
                next_chunk=chunk_index,digest=digest)
            return {'status':'HALTED_AFTER_VERIFIED_CHECKPOINTS','verified_chunks':chunk_index,
                    'next_chunk':chunk_index}
        diagnostic=_safe_apply_error(stage,remote_prewrite_error)
        result={'status':'APPS_SCRIPT_PREWRITE_REJECTED_NO_SHEET_WRITE','safe_error':diagnostic}
        finish_run(path,request_id,'failed_safe',result)
        return result
    except ExecutionPreflightError as preflight_error:
        if active_chunk_id:
            (reset_apply_chunk_preflight if plan_scope=='ALL' else reset_append_chunk_preflight)(path,active_chunk_id)
        if verified_steps or start_chunk>0:
            finish_partial_after_checkpoints(path,request_id,verified_chunks=chunk_index,
                next_chunk=chunk_index,digest=digest)
            return {'status':'HALTED_AFTER_VERIFIED_CHECKPOINTS','verified_chunks':chunk_index,
                    'next_chunk':chunk_index}
        diagnostic=_safe_apply_error(stage,preflight_error)
        finish_run(path,request_id,'failed_safe',{'status':'PRECALL_REJECTED_NO_REMOTE_CALL','safe_error':diagnostic})
        return {'status':'PRECALL_REJECTED_NO_REMOTE_CALL','safe_error':diagnostic}
    except ExecutionConfigurationError:
        if active_chunk_id:
            (reset_apply_chunk_preflight if plan_scope=='ALL' else reset_append_chunk_preflight)(path,active_chunk_id)
        if verified_steps or start_chunk>0:
            finish_partial_after_checkpoints(path,request_id,verified_chunks=chunk_index,
                next_chunk=chunk_index,digest=digest)
            return {'status':'HALTED_AFTER_VERIFIED_CHECKPOINTS','verified_chunks':chunk_index,
                    'next_chunk':chunk_index}
        finish_run(path,request_id,'failed_safe',{'status':'PRECALL_REJECTED_NO_REMOTE_CALL'})
        return {'status':'PRECALL_REJECTED_NO_REMOTE_CALL'}
    except ValueError:
        if active_chunk_id:
            (reset_apply_chunk_preflight if plan_scope=='ALL' else reset_append_chunk_preflight)(path,active_chunk_id)
        if verified_steps or start_chunk>0:
            finish_partial_after_checkpoints(path,request_id,verified_chunks=chunk_index,
                next_chunk=chunk_index,digest=digest)
            return {'status':'HALTED_AFTER_VERIFIED_CHECKPOINTS','verified_chunks':chunk_index,
                    'next_chunk':chunk_index}
        finish_run(path,request_id,'failed_safe',{'status':'PRECALL_REJECTED_NO_REMOTE_CALL'})
        return {'status':'PRECALL_REJECTED_NO_REMOTE_CALL'}
    except Exception as exc:
        hold_unknown_run(path,request_id,attempted_chunk=chunk_index,digest=digest,
                         checkpoint_digest=checkpoint_digest,chunk_id=active_chunk_id,
                         phase=active_phase,safe_error=_safe_apply_error(stage,exc))
        return {'status':'OUTCOME_UNKNOWN_HOLD_NO_RETRY'}


def status(path, environment, *, available=False, running=False, heartbeat=None, actor=None, now=None):
    uri=Path(path).resolve().as_uri()+'?mode=ro'
    with closing(sqlite3.connect(uri,uri=True,timeout=5)) as con:
        con.execute('PRAGMA query_only=ON')
        config = settings(con)
        try:
            con.row_factory=sqlite3.Row
            rows=[dict(row) for row in con.execute('''SELECT r.request_id,r.trigger,r.actor,r.revision,r.started_at,
              r.finished_at,r.status,r.result_json,c.close_id,c.closed_at,c.actor AS closed_by,
              c.reason AS close_reason,c.state AS close_state,pc.close_id AS prewrite_close_id,
              pc.closed_at AS prewrite_closed_at,pc.actor AS prewrite_closed_by,
              pc.reason AS prewrite_close_reason,pc.state AS prewrite_close_state
              FROM google_writer_runs r LEFT JOIN google_writer_run_closures c ON c.request_id=r.request_id
              LEFT JOIN google_writer_prewrite_closures pc ON pc.request_id=r.request_id
              WHERE r.environment=? ORDER BY r.started_at DESC LIMIT 20''',(environment,))]
        except sqlite3.OperationalError as exc:
            if 'no such table' not in str(exc).lower(): raise
            rows=[]
    for row in rows:
        row['result']=json.loads(row.pop('result_json'))
        result=row['result'] if isinstance(row.get('result'),dict) else {}
        safe=result.get('safe_error') if isinstance(result.get('safe_error'),dict) else {}
        status_candidate=(result.get('status') in {'APPS_SCRIPT_PREWRITE_REJECTED_NO_SHEET_WRITE','PRECALL_REJECTED_NO_REMOTE_CALL'} and
                          result.get('plan_scope')=='APPEND_ONLY')
        error_candidate=(not result.get('safe_error') or
            (safe.get('category')=='apps_script_stage_error' and safe.get('stage') in _PREWRITE_CLOSE_STAGES) or
            (safe.get('category')=='execution_api_http_error' and type(safe.get('http_status')) is int and
             400<=safe['http_status']<500))
        row['prewrite_close_eligible']=bool(environment=='SANDBOX' and row['status']=='failed_safe' and
            status_candidate and error_candidate and
            row.get('prewrite_close_state')!='closed_prewrite')
        planned=result.get('planned_counts') if isinstance(result.get('planned_counts'),dict) else {}
        verified=result.get('verified_totals') if isinstance(result.get('verified_totals'),dict) else {}
        result_counts=result.get('counts') if isinstance(result.get('counts'),dict) else {}
        confirmed={'append':int(verified.get('append',result_counts.get('append',0)) or 0),
                   'update':int(verified.get('update',result_counts.get('update',0)) or 0)}
        row['progress']={'state':result.get('progress_state') or row['status'],
            'phase':result.get('attempted_phase') or result.get('last_phase'),
            'planned':{'append':int(planned.get('append',0) or 0),'update':int(planned.get('update',0) or 0)},
            'confirmed':confirmed,
            'remaining':{'append':max(0,int(planned.get('append',0) or 0)-confirmed['append']),
                         'update':max(0,int(planned.get('update',0) or 0)-confirmed['update'])},
            'current_chunk':result.get('attempted_chunk',result.get('next_chunk')),
            'last_progress_at':result.get('last_progress_at'),
            'last_confirmed_progress_at':result.get('last_confirmed_progress_at'),
            'safe_error':result.get('safe_error') if isinstance(result.get('safe_error'),dict) else None,
            'last_recovered_error':result.get('last_recovered_error') if isinstance(result.get('last_recovered_error'),dict) else None}
        if environment=='SANDBOX':
            journal=[]
            try:
                with closing(sqlite3.connect(uri,uri=True,timeout=5)) as con:
                    con.execute('PRAGMA query_only=ON')
                    journal=con.execute('''SELECT phase,status,COUNT(*) FROM google_writer_apply_chunk_journal
                        WHERE run_id=? GROUP BY phase,status''',(row['request_id'],)).fetchall()
            except sqlite3.OperationalError as exc:
                if 'no such table' not in str(exc).lower(): raise
            row['progress']['chunks']=[{'phase':item[0],'state':item[1],'count':item[2]} for item in journal]
    last=rows[0] if rows else {}
    active_blocked=any(row['status'] in {'running','outcome_unknown'} for row in rows)
    # Unknown/active lanes are queried separately: an older hold must not be hidden by log limits.
    with closing(sqlite3.connect(uri,uri=True,timeout=5)) as con:
        con.execute('PRAGMA query_only=ON')
        try:
            active_blocked=bool(con.execute("SELECT 1 FROM google_writer_runs WHERE environment=? AND status IN ('running','outcome_unknown')",(environment,)).fetchone())
            resumable_rows=con.execute("SELECT request_id,actor,result_json FROM google_writer_runs WHERE environment='SANDBOX' AND status='partial'").fetchall() if environment=='SANDBOX' else []
            failed_safe_rows=con.execute("""SELECT r.request_id,r.result_json,pc.state
                FROM google_writer_runs r LEFT JOIN google_writer_prewrite_closures pc ON pc.request_id=r.request_id
                WHERE r.environment='SANDBOX' AND r.status='failed_safe'""").fetchall() if environment=='SANDBOX' else []
        except sqlite3.OperationalError as exc:
            if 'no such table' not in str(exc).lower(): raise
            resumable_rows=[];failed_safe_rows=[]
    resumable=[];continuable=[]
    for request_id,run_actor,raw_result in resumable_rows:
        try: progress=json.loads(raw_result or '{}')
        except (TypeError,json.JSONDecodeError): progress={}
        if (progress.get('status')=='HALTED_AFTER_VERIFIED_CHECKPOINTS' and
                progress.get('plan_scope')=='ALL' and not progress.get('outcome_unknown') and
                progress.get('attempted_chunk') is None and type(progress.get('next_chunk')) is int and
                is_canonical_sha256_b64url(progress.get('checkpoint_digest'))):
            continuable.append((request_id,run_actor))
        if (progress.get('status')=='HALTED_AFTER_VERIFIED_CHECKPOINTS' and
                progress.get('plan_scope')=='APPEND_ONLY' and not progress.get('outcome_unknown') and
                progress.get('attempted_chunk') is None and type(progress.get('next_chunk')) is int and
                is_canonical_sha256_b64url(progress.get('checkpoint_digest'))):
            resumable.append((request_id,run_actor))
    resume_available=any(run_actor==actor for _,run_actor in resumable) if actor else bool(resumable)
    prewrite_holds=[]
    for request_id,raw_result,close_state in failed_safe_rows:
        try: progress=json.loads(raw_result or '{}')
        except (TypeError,json.JSONDecodeError): progress={}
        safe=progress.get('safe_error') if isinstance(progress.get('safe_error'),dict) else {}
        if (progress.get('status') in {'APPS_SCRIPT_PREWRITE_REJECTED_NO_SHEET_WRITE','PRECALL_REJECTED_NO_REMOTE_CALL'} and
                progress.get('plan_scope')=='APPEND_ONLY' and
                close_state!='closed_prewrite'):
            prewrite_holds.append(request_id)
    blocked=active_blocked or bool(resumable) or bool(continuable) or bool(prewrite_holds)
    for row in rows:
        row['resume_available']=any(request_id==row['request_id'] and run_actor==actor
                                    for request_id,run_actor in resumable) if actor else False
    enabled=bool(config['enabled'] and available and running and not blocked)
    return {'job':JOB,'enabled':enabled,'configured_enabled':bool(config['enabled']),'hour':config['hour'],'minute':config['minute'],
            'revision':config['revision'],'timezone':'Europe/Kyiv','schedule':f"Щодня о {config['hour']:02}:{config['minute']:02}",
            'next_run':next_slot(config,now).astimezone(KYIV).isoformat() if enabled else None,
            'registered':running,'running':running,'heartbeat_at':heartbeat,'manageable':True,
            'configuration_source':'runtime','last_started_at':last.get('started_at'),'last_finished_at':last.get('finished_at'),
            'last_status':last.get('status','never'),'blocked':blocked,'active_blocked':active_blocked,
            'resume_available':resume_available,'prewrite_close_blocked':bool(prewrite_holds),
            'channel_ready':available,'runs':rows}


class Scheduler:
    """Fourth job only. No catch-up, no alterations to existing scheduler registry or leases."""
    def __init__(self,path,environment,client_factory,guard,*,clock=None):
        self.path,self.environment,self.client_factory,self.guard=path,environment,client_factory,guard
        self.clock=clock or (lambda:datetime.now(timezone.utc))
        self.wakeup=threading.Event();self.stop=threading.Event();self.mutex=threading.Lock()
        self.thread=None;self.heartbeat=None

    def start(self):
        if background_jobs.disabled():
            return False
        with self.mutex:
            if self.thread and self.thread.is_alive():
                self.wakeup.set();return False
            with closing(sqlite3.connect(self.path,timeout=5)) as con: config=settings(con)
            if not config['enabled'] or not self.guard(): return False
            self.stop.clear();self.wakeup.clear()
            self.thread=threading.Thread(target=self.loop,name='pqm-google-writer-scheduler',daemon=True)
            self.thread.start();return True

    def reschedule(self):
        self.wakeup.set()
        return self.start()

    def loop(self):
        target=None;revision=None
        while not self.stop.is_set() and not background_jobs.disabled():
            self.heartbeat=self.clock().isoformat()
            try:
                with closing(sqlite3.connect(self.path,timeout=5)) as con: config=settings(con)
                if not config['enabled'] or not self.guard(): return
                if target is None or config['revision'] != revision:
                    target=next_slot(config,self.clock());revision=config['revision']
                remaining=(target-self.clock().astimezone(timezone.utc)).total_seconds()
                if remaining>0:
                    self.wakeup.wait(min(remaining,30));self.wakeup.clear();continue
                # One stable slot identity across processes/restarts; revisions cannot produce duplicate Apply.
                run_id=hashlib.sha256((self.environment+':'+target.isoformat()).encode()).hexdigest()[:32]
                claimed=claim_run(self.path,self.environment,run_id,'scheduler','scheduled',revision,self.clock())
                if claimed['claimed'] and self.guard():
                    def current_guard():
                        with closing(sqlite3.connect(self.path,timeout=5)) as check:
                            latest=settings(check)
                        return not background_jobs.disabled() and self.guard() and bool(latest['enabled']) and latest['revision']==revision
                    execute_claimed(self.path,self.client_factory(),run_id,'scheduler',trigger='scheduled',guard=current_guard)
                elif claimed['claimed']:
                    finish_run(self.path,run_id,'failed_safe',{'status':'SAFETY_GUARD_CHANGED'})
                target=next_slot(config,self.clock())
            except Exception:
                # Do not repeat an uncertain cloud execution. Configuration/storage faults stop this listener.
                return


def recover_interrupted_append_chunk(path, client, request_id, actor, *, guard=lambda:True,
                                     now=None):
    """Recover one journaled lost response, then continue only from proof."""
    claim=claim_interrupted_append_chunk_recovery(path,request_id,now=now)
    if not claim:return {'status':'NOT_ELIGIBLE'}
    if not guard():
        hold_unknown_run(path,request_id,attempted_chunk=claim['chunk_index'],
            digest=claim['plan_digest'],checkpoint_digest=claim['checkpoint_digest'],
            chunk_id=claim['chunk_id'])
        return {'status':'HELD_GUARD_CHANGED'}
    try:
        result=client.invoke('recover_append_chunk',request_id,actor,trigger='manual',
            digest=claim['plan_digest'],plan_scope='APPEND_ONLY',manual_authorized=True,
            chunk_index=claim['chunk_index'],chunk_id=claim['chunk_id'],
            chunk_digest=claim['chunk_digest'],plan_id=claim['plan_id'])
        if result.get('status')=='CHUNK_NOT_APPLIED':
            raise ExecutionOutcomeUnknown('Read-only recovery proved no write, but automatic replay is prohibited',
                safe_error={'stage':'read_only_recovery','category':'no_write_proved_manual_review_required',
                            'exception_type':'ExecutionOutcomeUnknown'})
        if result.get('status')!='CHUNK_RECOVERED':
            raise ExecutionOutcomeUnknown('Read-only chunk recovery did not establish a safe state')
        checkpoint_run(path,request_id,result)
        if not result.get('more'):
            final='complete' if result.get('counts',{}).get('conflict',0)==0 and result.get('counts',{}).get('error',0)==0 else 'partial'
            return finish_run(path,request_id,final,result)
        finish_partial_after_checkpoints(path,request_id,verified_chunks=result['nextChunk'],
            next_chunk=result['nextChunk'],digest=claim['plan_digest'])
        with closing(sqlite3.connect(path,timeout=5)) as con:
            saved=con.execute('SELECT result_json FROM google_writer_runs WHERE request_id=?',(request_id,)).fetchone()
        try:auto_continue=json.loads(saved[0] or '{}').get('auto_continue_chunks') is True if saved else False
        except (TypeError,json.JSONDecodeError):auto_continue=False
        if auto_continue and guard():
            return continue_append_only_checkpoint(path,client,request_id,actor,
                digest=claim['plan_digest'],guard=guard,manual_authorized=True)
        return {'status':'HALTED_AFTER_VERIFIED_CHECKPOINTS','verified_chunks':result['nextChunk'],
            'next_chunk':result['nextChunk'],'checkpoint_digest':result['checkpointDigest']}
    except Exception:
        hold_unknown_run(path,request_id,attempted_chunk=claim['chunk_index'],
            digest=claim['plan_digest'],checkpoint_digest=claim['checkpoint_digest'],
            chunk_id=claim['chunk_id'])
        return {'status':'OUTCOME_UNKNOWN_HOLD_NO_RETRY'}


def recover_interrupted_apply_chunk(path, client, request_id, actor, *, guard=lambda:True,
                                    now=None):
    """Read-only recover one uncertain ALL chunk; continue only after exact receipt proof."""
    claim=claim_interrupted_apply_chunk_recovery(path,request_id,now=now)
    if not claim:return {'status':'NOT_ELIGIBLE'}
    if not guard():
        hold_unknown_run(path,request_id,attempted_chunk=claim['chunk_index'],
            digest=claim['plan_digest'],checkpoint_digest=claim['checkpoint_digest'],
            chunk_id=claim['chunk_id'],phase=claim['phase'])
        return {'status':'HELD_GUARD_CHANGED'}
    try:
        result=client.invoke('recover_apply_chunk',request_id,actor,trigger='manual',
            digest=claim['plan_digest'],plan_scope='ALL',manual_authorized=True,
            chunk_index=claim['chunk_index'],chunk_id=claim['chunk_id'],
            chunk_digest=claim['chunk_digest'],plan_id=claim['plan_id'],
            chunk_phase=claim['phase'],chunk_added_at=claim['added_at'],
            chunk_details_digest=claim['details_digest'])
        if result.get('status')=='CHUNK_NOT_APPLIED':
            raise ExecutionOutcomeUnknown('Read-only recovery proved no write; replay remains prohibited',
                safe_error={'stage':'read_only_recovery','category':'no_write_proved_manual_review_required',
                            'exception_type':'ExecutionOutcomeUnknown'})
        if result.get('status')!='CHUNK_RECOVERED':
            raise ExecutionOutcomeUnknown('Read-only Apply recovery did not establish a safe state',
                safe_error={'stage':'read_only_recovery','category':'ambiguous',
                            'exception_type':'ExecutionOutcomeUnknown'})
        checkpoint_run(path,request_id,result)
        if not result.get('more'):
            final='complete' if result.get('counts',{}).get('conflict',0)==0 and result.get('counts',{}).get('error',0)==0 else 'partial'
            return finish_run(path,request_id,final,result)
        with closing(sqlite3.connect(path,timeout=5)) as con:
            saved=con.execute('SELECT result_json FROM google_writer_runs WHERE request_id=?',(request_id,)).fetchone()
        try:auto_continue=json.loads(saved[0] or '{}').get('auto_continue_chunks') is True if saved else False
        except (TypeError,json.JSONDecodeError):auto_continue=False
        if auto_continue and guard():
            return execute_claimed(path,client,request_id,actor,trigger='manual',digest=claim['plan_digest'],
                guard=guard,manual_authorized=True,plan_scope='ALL',start_chunk=result['nextChunk'],
                checkpoint_digest=result['checkpointDigest'],max_apply_chunks=APPLY_CHUNKS_PER_WORKER)
        finish_partial_after_checkpoints(path,request_id,verified_chunks=result['nextChunk'],
            next_chunk=result['nextChunk'],digest=claim['plan_digest'])
        return {'status':'HALTED_AFTER_VERIFIED_CHECKPOINTS','verified_chunks':result['nextChunk'],
            'next_chunk':result['nextChunk'],'checkpoint_digest':result['checkpointDigest']}
    except Exception as exc:
        hold_unknown_run(path,request_id,attempted_chunk=claim['chunk_index'],
            digest=claim['plan_digest'],checkpoint_digest=claim['checkpoint_digest'],
            chunk_id=claim['chunk_id'],phase=claim['phase'],safe_error=_safe_apply_error('read_only_recovery',exc))
        return {'status':'OUTCOME_UNKNOWN_HOLD_NO_RETRY'}


class AppendOnlyContinuationWorker:
    """Sandbox-only watchdog for runs explicitly started by a human and checkpointed safely."""
    def __init__(self,path,client_factory,guard,*,environment='SANDBOX',interval_seconds=20):
        self.path=Path(path);self.client_factory=client_factory;self.guard=guard
        self.environment=environment;self.interval_seconds=max(5,int(interval_seconds))
        self.stop=threading.Event();self.thread=None

    def start(self):
        if self.environment!='SANDBOX' or self.thread is not None:return False
        self.thread=threading.Thread(target=self.loop,name='pqm-google-writer-continuation',daemon=True)
        self.thread.start();return True

    def eligible(self):
        uri=self.path.resolve().as_uri()+'?mode=ro'
        with closing(sqlite3.connect(uri,uri=True,timeout=5)) as con:
            con.execute('PRAGMA query_only=ON')
            rows=con.execute("SELECT request_id,actor,result_json FROM google_writer_runs WHERE environment='SANDBOX' AND status='partial' ORDER BY started_at").fetchall()
        candidates=[]
        for request_id,actor,raw in rows:
            try: state=json.loads(raw or '{}')
            except (TypeError,json.JSONDecodeError):continue
            if (isinstance(state,dict) and state.get('auto_continue_chunks') is True and
                    state.get('status')=='HALTED_AFTER_VERIFIED_CHECKPOINTS' and
                    state.get('plan_scope') in {'APPEND_ONLY','ALL'} and not state.get('outcome_unknown') and
                    state.get('attempted_chunk') is None):
                candidates.append((request_id,actor,state.get('plan_digest'),state.get('plan_scope')))
        return candidates

    def recoverable(self):
        uri=self.path.resolve().as_uri()+'?mode=ro'
        with closing(sqlite3.connect(uri,uri=True,timeout=5)) as con:
            con.execute('PRAGMA query_only=ON')
            rows=con.execute('''SELECT r.request_id,r.actor,r.status,r.result_json,
                                       c.status,c.inflight_at,c.scope,'APPEND_ONLY',r.started_at
                                FROM google_writer_runs r JOIN google_writer_chunk_journal c
                                  ON c.run_id=r.request_id
                                WHERE r.environment='SANDBOX' AND r.trigger='manual'
                                  AND r.status='running'
                                  AND c.status IN ('inflight','outcome_unknown')
                                UNION ALL
                                SELECT r.request_id,r.actor,r.status,r.result_json,
                                       c.status,c.inflight_at,c.scope,'ALL',r.started_at
                                FROM google_writer_runs r JOIN google_writer_apply_chunk_journal c
                                  ON c.run_id=r.request_id
                                WHERE r.environment='SANDBOX' AND r.trigger='manual'
                                  AND r.status='running' AND c.scope='ALL'
                                  AND c.status IN ('inflight','outcome_unknown')
            ORDER BY started_at''').fetchall()
        now=datetime.now(timezone.utc);found=[];seen=set()
        for request_id,actor,run_status,raw,chunk_status,inflight_at,scope,journal_kind,_started_at in rows:
            if request_id in seen: continue
            seen.add(request_id)
            try:state=json.loads(raw or '{}')
            except (TypeError,json.JSONDecodeError):continue
            if not isinstance(state,dict) or state.get('plan_scope')!=journal_kind:continue
            claimed_at=state.get('recovery_claimed_at')
            if claimed_at:
                try:
                    claimed=datetime.fromisoformat(claimed_at)
                    if claimed.tzinfo is None or (now-claimed.astimezone(timezone.utc)).total_seconds()<APPEND_RECOVERY_LEASE_SECONDS:
                        continue
                except (TypeError,ValueError):continue
            try:
                stamp=datetime.fromisoformat(inflight_at)
                if stamp.tzinfo and (now-stamp.astimezone(timezone.utc)).total_seconds()>=APPEND_RECOVERY_STALE_SECONDS:
                    found.append((request_id,actor,journal_kind))
            except (TypeError,ValueError):continue
        return found

    def run_once(self):
        if self.environment!='SANDBOX' or not self.guard():return 0
        try: reclaim_stale_apply_continuation(self.path)
        except Exception: return 0
        started=0;recovered_ids=set()
        for request_id,actor,scope in self.recoverable():
            if not self.guard():break
            try:
                if scope=='ALL':
                    recover_interrupted_apply_chunk(self.path,self.client_factory(),request_id,actor,guard=self.guard)
                else:
                    recover_interrupted_append_chunk(self.path,self.client_factory(),request_id,actor,guard=self.guard)
                started+=1
                recovered_ids.add(request_id)
            except Exception:
                continue
        for request_id,actor,digest,scope in self.eligible():
            if request_id in recovered_ids:continue
            if not self.guard():break
            try:
                if scope=='ALL':
                    continue_apply_checkpoint(self.path,self.client_factory(),request_id,actor,guard=self.guard)
                else:
                    continue_append_only_checkpoint(self.path,self.client_factory(),request_id,actor,
                        digest=digest,guard=self.guard,manual_authorized=True)
                started+=1
            except Exception:
                # Keep the confirmed checkpoint; next poll can retry only the read-only preflight.
                continue
        return started

    def loop(self):
        while not self.stop.is_set():
            self.run_once()
            self.stop.wait(self.interval_seconds)


def preview_ticket(client,request_id,actor,digest,*,plan_scope='ALL',parent_digest=None,details_digest=None):
    if plan_scope not in {'ALL','APPEND_ONLY'}:
        raise ValueError('Invalid Preview plan scope')
    if client.environment!='SANDBOX' and (plan_scope!='ALL' or parent_digest is not None or details_digest is not None):
        raise ValueError('Scoped Preview tickets are Sandbox-only')
    if plan_scope=='APPEND_ONLY' and (
            not is_canonical_sha256_b64url(parent_digest) or
            not is_canonical_sha256_b64url(details_digest) or
            not is_canonical_sha256_b64url(digest)):
        raise ValueError('Append-only ticket binding is incomplete')
    value={'environment':client.environment,'request_id':request_id,'actor':actor,'digest':digest}
    # Sandbox tickets remain usable for review; Apply always re-runs Preview and
    # rejects a stale plan before claiming a run. Production retains its old TTL.
    if client.environment!='SANDBOX':
        value['expires_at']=int(client.clock().timestamp())+300
    if client.environment=='SANDBOX' and details_digest is not None:
        if not is_canonical_sha256_b64url(details_digest) or not is_canonical_sha256_b64url(parent_digest or digest):
            raise ValueError('Sandbox Preview detail binding is invalid')
        value.update(scope=plan_scope,parent_digest=parent_digest or digest,details_digest=details_digest)
    raw=json.dumps(value,sort_keys=True,separators=(',',':')).encode()
    signature=hmac.new(client.shared_secret.encode(),b'PQM-PREVIEW-TICKET:'+raw,hashlib.sha256).digest()
    return base64.urlsafe_b64encode(raw).decode().rstrip('=')+'.'+base64.urlsafe_b64encode(signature).decode().rstrip('=')


def verify_ticket(client,ticket,actor):
    try:
        client.validate()
        encoded,signed=ticket.split('.')
        raw=base64.urlsafe_b64decode(encoded+'='*(-len(encoded)%4))
        signature=base64.urlsafe_b64decode(signed+'='*(-len(signed)%4))
        if not hmac.compare_digest(signature,hmac.new(client.shared_secret.encode(),b'PQM-PREVIEW-TICKET:'+raw,hashlib.sha256).digest()):
            raise ValueError('Ticket signature mismatch')
        value=json.loads(raw)
        has_expiry='expires_at' in value
        if (value['environment']!=client.environment or value['actor']!=actor or
                (has_expiry and (type(value['expires_at']) is not int or value['expires_at']<client.clock().timestamp())) or
                (client.environment!='SANDBOX' and not has_expiry) or
                not re.fullmatch('[0-9a-f]{32}',value['request_id']) or
                not is_canonical_sha256_b64url(value['digest'])):
            raise ValueError('Ticket context mismatch')
        scope=value.get('scope','ALL')
        if scope not in {'ALL','APPEND_ONLY'} or (client.environment!='SANDBOX' and scope!='ALL'):
            raise ValueError('Ticket scope mismatch')
        if 'details_digest' in value and (
                client.environment!='SANDBOX' or
                not is_canonical_sha256_b64url(value.get('details_digest')) or
                not is_canonical_sha256_b64url(value.get('parent_digest'))):
            raise ValueError('Ticket detail binding mismatch')
        if scope=='APPEND_ONLY' and 'details_digest' not in value:
            raise ValueError('Append-only ticket lacks detail binding')
        value['scope']=scope
        return value
    except Exception:
        raise ValueError('Reviewed Preview ticket is invalid or expired') from None


def append_only_resume_ticket(client, request_id, actor, digest, next_chunk,
                              checkpoint_digest, details_digest):
    if (client.environment!='SANDBOX' or not re.fullmatch(r'[0-9a-f]{32}',str(request_id or '')) or
            not actor or len(actor)>128 or not is_canonical_sha256_b64url(digest) or
            type(next_chunk) is not int or not 1<=next_chunk<=499 or
            not is_canonical_sha256_b64url(checkpoint_digest) or
            not is_canonical_sha256_b64url(details_digest)):
        raise ValueError('Append-only continuation ticket binding is invalid')
    issued=int(client.clock().timestamp())
    value={'environment':'SANDBOX','request_id':request_id,'actor':actor,'trigger':'manual',
           'action':'resume_append_only','scope':'APPEND_ONLY','digest':digest,
           'next_chunk':next_chunk,'checkpoint_digest':checkpoint_digest,
           'details_digest':details_digest,'issued_at':issued,'expires_at':issued+300}
    raw=json.dumps(value,sort_keys=True,separators=(',',':')).encode('utf-8')
    signature=hmac.new(client.shared_secret.encode(),b'PQM-APPEND-RESUME-TICKET:'+raw,hashlib.sha256).digest()
    return base64.urlsafe_b64encode(raw).decode().rstrip('=')+'.'+base64.urlsafe_b64encode(signature).decode().rstrip('=')


def verify_append_only_resume_ticket(client, ticket, actor):
    try:
        client.validate()
        if client.environment!='SANDBOX' or not isinstance(ticket,str) or len(ticket)>8192:
            raise ValueError('scope rejected')
        encoded,signed=ticket.split('.')
        raw=base64.urlsafe_b64decode(encoded+'='*(-len(encoded)%4))
        signature=base64.urlsafe_b64decode(signed+'='*(-len(signed)%4))
        expected=hmac.new(client.shared_secret.encode(),b'PQM-APPEND-RESUME-TICKET:'+raw,hashlib.sha256).digest()
        if not hmac.compare_digest(signature,expected): raise ValueError('signature rejected')
        value=json.loads(raw)
        now=client.clock().timestamp()
        if (not isinstance(value,dict) or value.get('environment')!='SANDBOX' or
                value.get('actor')!=actor or value.get('trigger')!='manual' or
                value.get('action')!='resume_append_only' or value.get('scope')!='APPEND_ONLY' or
                not re.fullmatch(r'[0-9a-f]{32}',value.get('request_id','')) or
                not is_canonical_sha256_b64url(value.get('digest')) or
                not is_canonical_sha256_b64url(value.get('checkpoint_digest')) or
                not is_canonical_sha256_b64url(value.get('details_digest')) or
                type(value.get('next_chunk')) is not int or not 1<=value['next_chunk']<=499 or
                type(value.get('issued_at')) is not int or type(value.get('expires_at')) is not int or
                value['issued_at']>now+30 or value['expires_at']<now or
                value['expires_at']-value['issued_at']>300):
            raise ValueError('ticket context rejected')
        return value
    except Exception:
        raise ValueError('APPEND_ONLY continuation ticket is invalid or expired') from None
