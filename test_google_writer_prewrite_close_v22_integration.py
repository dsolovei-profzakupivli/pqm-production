"""Mock end-to-end coverage for Render -> Apps Script v22 -> SQLite closure."""
import base64
from contextlib import closing
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import google_writer_execution as writer
import sandbox_runtime as runtime


REQUEST_ID = 'b11433e8efb84b4492bf2df7c7c25908'
CLOSE_ID = 'c' * 32
ACTOR = 'sandbox-admin'
REASON = 'Verified prewrite failure on isolated mock evidence.'
SECRET = 'mock-v22-shared-secret-' + 'x' * 32
DEPLOYMENT = 'TEST_SANDBOX_DEPLOYMENT_0123456789'
SCRIPT_PATH = (Path(__file__).parent / 'scripts/pqm-google-writer/mirror-alignment/sandbox/'
               'prewrite-close-v22.test.cjs')
NODE_EXE = shutil.which('node')
NODE_RUNTIME_ENV = {key: os.environ[key] for key in ('PATH', 'SystemRoot', 'WINDIR', 'TEMP', 'TMP')
                    if os.environ.get(key)}


def digest(raw):
    if isinstance(raw, str):
        raw = raw.encode('utf-8')
    return base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).decode('ascii').rstrip('=')


class AppsScriptBridge:
    """Runs the real Apps Script dispatcher under Node's isolated mock services."""
    def __init__(self, *, timeout_after_first_execution=False):
        self.properties = None
        self.calls = []
        self.sheet_writes = 0
        self.payload_units = 0
        self.timeout_after_first_execution = timeout_after_first_execution
        self.error = None
        self.last_result = None

    def open(self, request, timeout):
        self.calls.append(request)
        runtime.validate_execution_request(request, 'SANDBOX', *writer.IDENTITIES['SANDBOX'][:2], DEPLOYMENT)
        body = json.loads(request.data)
        envelope = body['parameters'][0]
        self.payload_units = len(envelope['payload'])
        signed = json.loads(envelope['payload'])
        self.assert_contract(body, signed)
        initial = self.properties or {
            'PQM_EXECUTION_SHARED_SECRET': SECRET,
            'PQM_EXECUTION_UNCERTAIN': REQUEST_ID,
            'PQM_EXECUTION_RUN_' + REQUEST_ID: json.dumps({
                'state': 'ready', 'planScope': 'APPEND_ONLY', 'chunkJournalVersion': 1,
                'digest': signed['expectedDigest'], 'nextChunk': 0, 'inflight': None,
                'inflightManifest': None, 'uncertainChunk': None, 'steps': [],
                'aggregate': {'append': 0, 'update': 0, 'batches': 0}, 'result': None,
            }, separators=(',', ':')),
        }
        try:
            completed = subprocess.run(
                [NODE_EXE or 'node', str(SCRIPT_PATH), '--bridge'],
                input=json.dumps({'secret': SECRET, 'envelope': envelope, 'properties': initial}),
                text=True, capture_output=True, check=False, timeout=30, env=NODE_RUNTIME_ENV)
        except Exception as exc:
            self.error = type(exc).__name__ + ': ' + str(exc)
            raise
        if completed.returncode:
            self.error = completed.stderr.strip() or 'mock dispatcher exited unsuccessfully'
            raise AssertionError('Mock Apps Script failed: ' + completed.stderr.strip())
        result = json.loads(completed.stdout)
        self.last_result = result
        self.properties = result['properties']
        self.sheet_writes += result['sheetWrites']
        if result['sheetWrites'] != 0:
            raise AssertionError('Apps Script closure wrote to Sheets')
        if result['receipt']['status'] != 'ADMIN_CLOSED_PREWRITE_NO_WRITE':
            raise AssertionError('Mock Apps Script returned a wrong closure status')
        if self.timeout_after_first_execution and len(self.calls) == 1:
            raise TimeoutError('mock response lost after remote completion')
        return io.BytesIO(json.dumps({'done': True, 'response': {'result': result['receipt']}}).encode())

    @staticmethod
    def assert_contract(body, payload):
        assert body['function'] == 'pqmSandboxAllScopeExecution20261109'
        assert body['devMode'] is False
        assert payload['action'] == 'close_prewrite_failure'
        assert payload['requestId'] == REQUEST_ID
        assert payload['closeId'] == CLOSE_ID
        assert payload['planScope'] == 'APPEND_ONLY'
        assert len(payload['legacyManifestRows']) == 25
        assert 8192 < len(body['parameters'][0]['payload']) <= 32768


class PrewriteCloseV22IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent, prefix='prewrite-close-v22-')
        self.addCleanup(self.temp.cleanup)
        self.db_path = str(Path(self.temp.name) / 'sandbox.sqlite3')
        with closing(__import__('sqlite3').connect(self.db_path)) as con, con:
            writer.migrate(con)
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.client = None
        self.plan_digest = digest(b'mock APPEND_ONLY plan')
        self.full_digest = digest(b'mock full Preview plan')
        self.source_digest = digest(b'mock source')
        rows = []
        for index in range(25):
            tab = 'ФОП' if index < 21 else 'ЮО'
            row = index + 2
            code = str(index + 1).zfill(10)
            rows.append({'operation': 'APPEND', 'tab': tab, 'row': row, 'code': code,
                'cells': [{'column': 'A', 'new_value': '=' + ('x' * 220), 'formula': True},
                          {'column': 'B', 'new_value': code, 'formula': False}]})
        details = {'version': 1, 'environment': 'SANDBOX', 'plan_digest': self.full_digest,
            'append_only_digest': self.plan_digest, 'source_digest': self.source_digest,
            'counts': {'append': 25, 'update': 0, 'conflict': 0, 'error': 0},
            'appends': rows, 'updates': [], 'conflicts': [], 'errors': []}
        snapshot = writer.store_preview_plan(self.db_path, REQUEST_ID, ACTOR, details)
        writer.claim_run(self.db_path, 'SANDBOX', REQUEST_ID, ACTOR, 'manual',
            manual_authorized=True, plan_scope='APPEND_ONLY', plan_digest=self.plan_digest,
            details_digest=snapshot['details_digest'])
        writer.prepare_append_chunk(self.db_path, REQUEST_ID, ACTOR, self.plan_digest,
            snapshot['details_digest'], 0, now=self.now)
        original_result = json.dumps({'status': 'PRECALL_REJECTED_NO_REMOTE_CALL',
            'plan_scope': 'APPEND_ONLY', 'plan_digest': self.plan_digest,
            'safe_error': {'stage': 'execution_api_response', 'category': 'execution_api_http_error',
                           'http_status': 400}}, sort_keys=True)
        with closing(__import__('sqlite3').connect(self.db_path)) as con, con:
            con.execute("UPDATE google_writer_runs SET status='failed_safe',finished_at=?,result_json=? WHERE request_id=?",
                (self.now.isoformat(), original_result, REQUEST_ID))
        self.original_result = original_result
        self.runtime_env = {
            'PQM_SANDBOX': '1', 'RENDER_SERVICE_ID': 'srv-dalfd77f3r2c7392uub0',
            'PQM_SANDBOX_EXECUTION_READY': '1',
            'PQM_SANDBOX_EXECUTION_DEPLOYMENT_ID': DEPLOYMENT,
            'PQM_SANDBOX_EDR_GOOGLE': '1',
        }
        self.env_patch = patch.dict(os.environ, self.runtime_env, clear=True)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def client_for(self, bridge):
        now = self.now
        token_provider = lambda env: {'environment': env, 'access_token': 'MOCK_TOKEN',
            'scopes': sorted(writer.PROJECT_SCOPES), 'expires_at': now.timestamp() + 3600}
        return writer.ExecutionClient('SANDBOX', DEPLOYMENT, SECRET, token_provider,
            configured=True, opener=lambda request, timeout: self.render_transport(
                request, timeout, bridge), clock=lambda: now)

    @contextmanager
    def render_transport(self, request, timeout, bridge):
        yield bridge.open(request, timeout)

    def run_close(self, bridge):
        self.client = self.client_for(bridge)
        original_finalize = writer.finalize_admin_close_prewrite
        def traced_finalize(*args, **kwargs):
            try:
                return original_finalize(*args, **kwargs)
            except Exception as exc:
                receipt = args[3] if len(args) > 3 else kwargs.get('receipt', {})
                with closing(__import__('sqlite3').connect(self.db_path)) as con:
                    con.row_factory = __import__('sqlite3').Row
                    intent = con.execute('SELECT * FROM google_writer_prewrite_closures WHERE close_id=?',
                        (CLOSE_ID,)).fetchone()
                fields = ('environment','scriptId','spreadsheetId','contract','requestId','status',
                    'closeId','planScope','disposition','evidenceDigest','reasonDigest','chunkId',
                    'chunkDigest','chunkIndex','targetIdentityDigest','actor')
                expected = {'environment':'SANDBOX','scriptId':writer.IDENTITIES['SANDBOX'][0],
                    'spreadsheetId':writer.IDENTITIES['SANDBOX'][1],'contract':writer.CONTRACT,
                    'requestId':REQUEST_ID,'status':'ADMIN_CLOSED_PREWRITE_NO_WRITE','closeId':CLOSE_ID,
                    'planScope':'APPEND_ONLY','disposition':'PREWRITE_FAILURE_CONFIRMED_NO_SHEET_WRITE',
                    'evidenceDigest':intent['evidence_digest'],'reasonDigest':intent['reason_digest'],
                    'chunkId':intent['chunk_id'],'chunkDigest':intent['chunk_digest'],'chunkIndex':0,
                    'targetIdentityDigest':intent['target_identity_digest'],'actor':ACTOR}
                mismatches = [key for key in fields if receipt.get(key) != expected[key]]
                if receipt.get('prewriteStage') != 'append_inflight_save': mismatches.append('prewriteStage')
                if receipt.get('proofType') != 'LEGACY_V1_WRITEAHEAD_OVERSIZE': mismatches.append('proofType')
                if type(receipt.get('writeAheadBytes')) is not int or receipt.get('writeAheadBytes', 0) <= 8000: mismatches.append('writeAheadBytes')
                if receipt.get('checkpointMaxBytes') != 8000: mismatches.append('checkpointMaxBytes')
                if not writer.is_canonical_sha256_b64url(receipt.get('runRecordDigest')): mismatches.append('runRecordDigest')
                if not isinstance(receipt.get('closedAt'), str): mismatches.append('closedAt')
                if receipt.get('digest') != writer._prewrite_close_receipt_digest(receipt): mismatches.append('receiptDigest')
                bridge.error = 'SQLite finalization ' + type(exc).__name__ + ': ' + ','.join(mismatches or ['other'])
                raise
        try:
            with patch.object(writer, 'finalize_admin_close_prewrite', side_effect=traced_finalize):
                return writer.close_confirmed_prewrite_failure(self.db_path, self.client,
                    REQUEST_ID, ACTOR, CLOSE_ID, REASON)
        except writer.ExecutionOutcomeUnknown as exc:
            if bridge.timeout_after_first_execution and len(bridge.calls) == 1:
                raise
            if bridge.error:
                raise AssertionError(bridge.error) from None
            if bridge.last_result is not None:
                raise AssertionError('Apps Script returned but Render rejected the response contract: ' +
                    str(exc) + ' ' + repr(getattr(exc, 'safe_error', None))) from None
            raise
        except writer.AdminCloseFinalizationUnknown:
            if bridge.error:
                raise AssertionError(bridge.error) from None
            raise

    def assert_closed(self, *, idempotent):
        with closing(__import__('sqlite3').connect(self.db_path)) as con:
            run = con.execute('SELECT status,finished_at,result_json FROM google_writer_runs WHERE request_id=?',
                (REQUEST_ID,)).fetchone()
            intent = con.execute('SELECT state,close_id,receipt_json FROM google_writer_prewrite_closures WHERE request_id=?',
                (REQUEST_ID,)).fetchone()
            chunk = con.execute('SELECT status FROM google_writer_chunk_journal WHERE run_id=?',
                (REQUEST_ID,)).fetchone()
            intent_count = con.execute('SELECT COUNT(*) FROM google_writer_prewrite_closures').fetchone()[0]
        self.assertEqual(run, ('closed_prewrite', self.now.isoformat(), self.original_result))
        self.assertEqual(intent[0:2], ('closed_prewrite', CLOSE_ID))
        self.assertEqual(chunk[0], 'prepared')
        self.assertEqual(intent_count, 1)
        receipt = json.loads(intent[2])
        self.assertEqual(receipt['status'], 'ADMIN_CLOSED_PREWRITE_NO_WRITE')
        self.assertEqual(receipt['idempotent'], idempotent)

    def test_full_render_apps_script_receipt_sqlite_closure_is_no_append(self):
        bridge = AppsScriptBridge()
        result = self.run_close(bridge)
        self.assertEqual(result['status'], 'ADMIN_CLOSED_PREWRITE_NO_WRITE')
        self.assertEqual(result['close_id'], CLOSE_ID)
        self.assertEqual(len(bridge.calls), 1)
        self.assertGreater(bridge.payload_units, 8192)
        self.assertLessEqual(bridge.payload_units, 32768)
        self.assertEqual(bridge.sheet_writes, 0)
        self.assertIn('PQM_EXECUTION_PREWRITE_CLOSED_' + REQUEST_ID, bridge.properties)
        self.assertNotIn('PQM_EXECUTION_UNCERTAIN', bridge.properties)
        self.assert_closed(idempotent=False)

    def test_lost_response_retains_hold_then_same_close_id_replay_finalizes_idempotently(self):
        bridge = AppsScriptBridge(timeout_after_first_execution=True)
        with self.assertRaises(writer.ExecutionOutcomeUnknown):
            self.run_close(bridge)
        with closing(__import__('sqlite3').connect(self.db_path)) as con:
            self.assertEqual(con.execute('SELECT status FROM google_writer_runs WHERE request_id=?',
                (REQUEST_ID,)).fetchone()[0], 'failed_safe')
            intent = con.execute('SELECT state,close_id FROM google_writer_prewrite_closures WHERE request_id=?',
                (REQUEST_ID,)).fetchone()
            self.assertEqual(intent, ('prepared', CLOSE_ID))
        self.assertIn('PQM_EXECUTION_PREWRITE_CLOSED_' + REQUEST_ID, bridge.properties)
        self.assertNotIn('PQM_EXECUTION_UNCERTAIN', bridge.properties)
        result = self.run_close(bridge)
        self.assertEqual(result['status'], 'ADMIN_CLOSED_PREWRITE_NO_WRITE')
        self.assertEqual(len(bridge.calls), 2)
        self.assertEqual(bridge.sheet_writes, 0)
        self.assert_closed(idempotent=True)


if __name__ == '__main__':
    unittest.main()
