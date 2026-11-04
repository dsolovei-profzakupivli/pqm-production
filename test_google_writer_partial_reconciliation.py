import base64
import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from contextlib import closing

import google_writer_execution as execution


TEST_REQUEST_ID = 'd' * 32
TEST_RECONCILIATION_ID = 'e' * 32
TEST_ACTOR = 'sandbox-admin'
TEST_DIGEST = base64.urlsafe_b64encode(hashlib.sha256(b'test plan').digest()).decode().rstrip('=')
TEST_NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)


class PartialReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.path = str(Path(self.temp.name) / 'sandbox.sqlite3')
        self.old_fingerprint = execution.PARTIAL_RECONCILIATION_REQUEST_FINGERPRINT
        execution.PARTIAL_RECONCILIATION_REQUEST_FINGERPRINT = execution.request_id_fingerprint(TEST_REQUEST_ID)
        with closing(sqlite3.connect(self.path)) as con, con:
            execution.migrate(con)
            con.execute('''INSERT INTO google_writer_runs(
              request_id,environment,trigger,actor,revision,started_at,finished_at,status,result_json)
              VALUES(?,?,?,?,?,?,?,?,?)''',(
                TEST_REQUEST_ID,'SANDBOX','manual','original-operator',3,
                '2026-11-03T12:00:00+00:00','2026-11-03T12:01:00+00:00',
                'outcome_unknown',json.dumps({'status':'OUTCOME_UNKNOWN_HOLD_NO_RETRY'})))

    def tearDown(self):
        execution.PARTIAL_RECONCILIATION_REQUEST_FINGERPRINT = self.old_fingerprint
        self.temp.cleanup()

    def prepare(self, reconciliation_id=TEST_RECONCILIATION_ID, fingerprint=None):
        return execution.prepare_partial_reconciliation(
            self.path,'SANDBOX',reconciliation_id,
            fingerprint or execution.PARTIAL_RECONCILIATION_REQUEST_FINGERPRINT,
            TEST_ACTOR,now=TEST_NOW)

    def receipt(self, prepared):
        return {
            'environment':'SANDBOX',
            'scriptId':execution.IDENTITIES['SANDBOX'][0],
            'spreadsheetId':execution.IDENTITIES['SANDBOX'][1],
            'contract':execution.CONTRACT,
            'requestId':prepared['request_id'],
            'status':'RECONCILED_PARTIAL',
            'reconciliationId':prepared['reconciliation_id'],
            'requestFingerprint':prepared['request_fingerprint'],
            'evidenceDigest':prepared['evidence_digest'],
            'digest':TEST_DIGEST,
            'counts':{'verified_append_rows':50,'unverified_original_updates':2,
                      'accepted_date_only_formats':12}
        }

    def state(self):
        with closing(sqlite3.connect(self.path)) as con:
            run=con.execute('SELECT status,result_json FROM google_writer_runs WHERE request_id=?',(TEST_REQUEST_ID,)).fetchone()
            audit=con.execute('''SELECT state,original_status,original_result_json,apps_script_receipt_json
              FROM google_writer_run_reconciliations WHERE request_id=?''',(TEST_REQUEST_ID,)).fetchone()
        return run,audit

    def test_prepare_keeps_unknown_hold_and_persists_original_evidence(self):
        prepared=self.prepare()
        run,audit=self.state()
        self.assertEqual(prepared['state'],'prepared')
        self.assertEqual(run[0],'outcome_unknown')
        self.assertEqual(json.loads(run[1]),{'status':'OUTCOME_UNKNOWN_HOLD_NO_RETRY'})
        self.assertEqual(audit[0:2],('prepared','outcome_unknown'))
        self.assertEqual(json.loads(audit[2]),{'status':'OUTCOME_UNKNOWN_HOLD_NO_RETRY'})
        self.assertEqual(audit[3],'{}')

    def test_mismatch_and_production_fail_before_any_reconciliation_record(self):
        with self.assertRaises(ValueError): self.prepare(fingerprint='0'*24)
        with self.assertRaises(PermissionError):
            execution.prepare_partial_reconciliation(self.path,'PROD',TEST_RECONCILIATION_ID,
              execution.PARTIAL_RECONCILIATION_REQUEST_FINGERPRINT,TEST_ACTOR,now=TEST_NOW)
        self.assertEqual(self.state()[0][0],'outcome_unknown')
        self.assertIsNone(self.state()[1])

    def test_concurrent_unknown_or_running_state_fails_closed(self):
        other='f'*32
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute('DROP INDEX ix_google_writer_single_lane')
            con.execute('''INSERT INTO google_writer_runs(request_id,environment,trigger,actor,revision,started_at,status,result_json)
              VALUES(?,?,?,?,?,?,?,?)''',(other,'SANDBOX','manual','other',3,'2026-11-03T12:02:00+00:00',
              'outcome_unknown','{}'))
        with self.assertRaises(RuntimeError): self.prepare()
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("DELETE FROM google_writer_runs WHERE request_id=?",(other,))
            con.execute("UPDATE google_writer_runs SET status='running' WHERE request_id=?",(TEST_REQUEST_ID,))
        with self.assertRaises(RuntimeError): self.prepare()
        self.assertIsNone(self.state()[1])

    def test_invalid_remote_receipt_keeps_sqlite_hold(self):
        prepared=self.prepare()
        bad=self.receipt(prepared)
        bad['evidenceDigest']='A'*43
        with self.assertRaises(PermissionError):
            execution.finalize_partial_reconciliation(self.path,TEST_RECONCILIATION_ID,TEST_ACTOR,bad,now=TEST_NOW)
        self.assertEqual(self.state()[0][0],'outcome_unknown')
        self.assertEqual(self.state()[1][0],'prepared')

    def test_finalize_is_audited_partial_and_idempotent(self):
        prepared=self.prepare()
        result=execution.finalize_partial_reconciliation(
            self.path,TEST_RECONCILIATION_ID,TEST_ACTOR,self.receipt(prepared),now=TEST_NOW)
        self.assertEqual(result['status'],'RECONCILED_PARTIAL')
        self.assertFalse(result['idempotent'])
        run,audit=self.state()
        self.assertEqual(run[0],'partial')
        self.assertEqual(json.loads(run[1])['status'],'RECONCILED_PARTIAL')
        self.assertEqual(audit[0:2],('reconciled_partial','outcome_unknown'))
        self.assertEqual(json.loads(audit[2]),{'status':'OUTCOME_UNKNOWN_HOLD_NO_RETRY'})
        self.assertNotEqual(audit[3],'{}')
        retry=self.prepare()
        self.assertTrue(retry['idempotent'])
        again=execution.finalize_partial_reconciliation(
            self.path,TEST_RECONCILIATION_ID,TEST_ACTOR,self.receipt(prepared),now=TEST_NOW)
        self.assertTrue(again['idempotent'])

    def test_different_reconciliation_id_cannot_take_over_prepared_run(self):
        self.prepare()
        with self.assertRaises(RuntimeError): self.prepare(reconciliation_id='a'*32)
        self.assertEqual(self.state()[0][0],'outcome_unknown')

    def test_execution_client_signs_the_exact_reconciliation_evidence_and_validates_receipt(self):
        self_id=TEST_REQUEST_ID
        evidence=execution.PARTIAL_RECONCILIATION_EVIDENCE
        evidence_raw=json.dumps(evidence,ensure_ascii=False,sort_keys=True,separators=(',',':'))
        evidence_digest=base64.urlsafe_b64encode(hashlib.sha256(evidence_raw.encode()).digest()).decode().rstrip('=')
        calls=[]
        def opener(request,timeout):
            calls.append((request,timeout))
            body=json.loads(request.data)
            message=json.loads(body['parameters'][0]['payload'])
            receipt={k:message[k] for k in ('environment','scriptId','spreadsheetId','contract','requestId')}
            receipt.update(status='RECONCILED_PARTIAL',digest=TEST_DIGEST,
                reconciliationId=TEST_RECONCILIATION_ID,
                requestFingerprint=execution.PARTIAL_RECONCILIATION_REQUEST_FINGERPRINT,
                evidenceDigest=evidence_digest,
                counts={'verified_append_rows':50,'unverified_original_updates':2,'accepted_date_only_formats':12})
            return io.BytesIO(json.dumps({'done':True,'response':{'result':receipt}}).encode())
        client=execution.ExecutionClient('SANDBOX','TEST_DEPLOYMENT_NOT_CLOUD',
          'TEST_ONLY_SECRET_0123456789_ABCDEFGHIJ',
          lambda env:{'environment':env,'access_token':'TEST_ONLY','scopes':sorted(execution.PROJECT_SCOPES),
                      'expires_at':TEST_NOW.timestamp()+3600},
          configured=True,opener=opener,clock=lambda:TEST_NOW)
        result=client.invoke('reconcile_partial',self_id,TEST_ACTOR,trigger='manual',manual_authorized=True,
          reconciliation_id=TEST_RECONCILIATION_ID,
          request_fingerprint=execution.PARTIAL_RECONCILIATION_REQUEST_FINGERPRINT,evidence=evidence)
        request,timeout=calls[0]
        message=json.loads(json.loads(request.data)['parameters'][0]['payload'])
        self.assertEqual(timeout,390)
        self.assertEqual(message['evidenceDigest'],evidence_digest)
        self.assertEqual(message['evidence'],evidence)
        self.assertEqual(result['status'],'RECONCILED_PARTIAL')
        self.assertNotIn('TEST_ONLY',json.dumps(result))
        with self.assertRaises(ValueError):
            client.invoke('reconcile_partial',self_id,TEST_ACTOR,trigger='scheduled',
              reconciliation_id=TEST_RECONCILIATION_ID,
              request_fingerprint=execution.PARTIAL_RECONCILIATION_REQUEST_FINGERPRINT,evidence=evidence)


if __name__ == '__main__':
    unittest.main()
