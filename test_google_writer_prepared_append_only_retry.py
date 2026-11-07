"""Regression coverage for idempotently re-entering a prepared APPEND_ONLY intent."""

import base64
import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import google_writer_execution as execution


REQUEST_ID = "ab1d69b6d7c6427f8abdffea35830948"
RECONCILIATION_ID = "23da3b07224e43bfa07725e41339a99f"
ACTOR = "sandbox-admin"
NOW = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)


class PreparedAppendOnlyRetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent, prefix="prepared-append-only-retry-")
        self.path = str(Path(self.temp.name) / "sandbox.sqlite3")
        self.fingerprint = execution.request_id_fingerprint(REQUEST_ID)
        self.profile = execution.partial_reconciliation_profile(self.fingerprint)
        self.assertIsNotNone(self.profile)
        with closing(sqlite3.connect(self.path)) as con, con:
            execution.migrate(con)
        self.details = self._details()
        snapshot = execution.store_preview_plan(self.path, REQUEST_ID, "original-operator", self.details)
        claim = execution.claim_run(
            self.path, "SANDBOX", REQUEST_ID, "original-operator", "manual",
            manual_authorized=True, plan_scope="APPEND_ONLY",
            plan_digest=self.details["append_only_digest"], details_digest=snapshot["details_digest"],
        )
        self.assertTrue(claim["claimed"])
        execution.hold_unknown_run(
            self.path, REQUEST_ID, attempted_chunk=0,
            digest=self.details["append_only_digest"], checkpoint_digest=None,
        )
        self.prepared = execution.prepare_partial_reconciliation(
            self.path, "SANDBOX", RECONCILIATION_ID, self.fingerprint, ACTOR, now=NOW
        )

    def tearDown(self):
        self.temp.cleanup()

    def _details(self):
        full = base64.urlsafe_b64encode(hashlib.sha256(b"full plan").digest()).decode().rstrip("=")
        append_only = base64.urlsafe_b64encode(hashlib.sha256(b"append-only plan").digest()).decode().rstrip("=")
        appends = [
            {"operation": "APPEND", "tab": "ФОП", "cells": [{"column": "A", "formula": True}]}
            for _ in range(351)
        ]
        return {
            "version": 1, "environment": "SANDBOX", "plan_digest": full,
            "append_only_digest": append_only,
            "counts": {"append": 351, "update": 2, "conflict": 2, "error": 0},
            "appends": appends, "updates": [{"operation": "UPDATE", "cells": []} for _ in range(2)],
            "conflicts": [{"reason": "routing_mismatch"} for _ in range(2)], "errors": [],
        }

    def _audit_row(self):
        with closing(sqlite3.connect(self.path)) as con:
            return con.execute(
                """SELECT reconciliation_id,request_id,environment,actor,request_fingerprint,
                          evidence_digest,evidence_json,state,original_status,original_result_json,
                          original_actor,original_trigger,original_revision,original_started_at,
                          apps_script_receipt_json
                   FROM google_writer_run_reconciliations WHERE reconciliation_id=?""",
                (RECONCILIATION_ID,),
            ).fetchone()

    def _run(self):
        with closing(sqlite3.connect(self.path)) as con:
            return con.execute(
                "SELECT status,result_json FROM google_writer_runs WHERE request_id=?", (REQUEST_ID,)
            ).fetchone()

    def _retry(self, *, reconciliation_id=RECONCILIATION_ID, fingerprint=None):
        return execution.prepare_partial_reconciliation(
            self.path, "SANDBOX", reconciliation_id, fingerprint or self.fingerprint, ACTOR, now=NOW
        )

    def _synthetic_reconciliation_client(self, prepared, captured):
        def opener(request, timeout):
            body = json.loads(request.data)
            message = json.loads(body["parameters"][0]["payload"])
            captured.append({"action": message.get("action"),
                             "reconciliation_id": message.get("reconciliationId"),
                             "request_fingerprint": message.get("requestFingerprint"),
                             "expected_digest_is_null": message.get("expectedDigest") is None,
                             "timeout": timeout})
            result = {key: message[key] for key in
                      ("environment", "scriptId", "spreadsheetId", "contract", "requestId")}
            result.update(
                status="RECONCILED_PARTIAL", digest=self.details["append_only_digest"],
                reconciliationId=RECONCILIATION_ID, requestFingerprint=self.fingerprint,
                evidenceDigest=prepared["evidence_digest"], counts=self.profile["result_counts"],
                **self.profile["receipt_fields"],
            )
            return io.BytesIO(json.dumps({"done": True, "response": {"result": result}}).encode())

        return execution.ExecutionClient(
            "SANDBOX", "TEST_DEPLOYMENT_NOT_CLOUD", "TEST_ONLY_SECRET_0123456789_ABCDEFGHIJ",
            lambda env: {"environment": env, "access_token": "TEST_ONLY",
                         "scopes": sorted(execution.PROJECT_SCOPES),
                         "expires_at": NOW.timestamp() + 3600},
            configured=True, opener=opener, clock=lambda: NOW,
        )

    def test_retry_after_http_503_reuses_prepared_intent_without_new_row_or_evidence(self):
        before = self._audit_row()
        run_before = self._run()
        self.assertEqual(before[7], "prepared")
        self.assertEqual(before[14], "{}")

        retry = self._retry()

        self.assertTrue(retry["idempotent"])
        self.assertEqual(retry["state"], "prepared")
        self.assertEqual(self._audit_row(), before)
        self.assertEqual(self._run(), run_before)
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM google_writer_run_reconciliations").fetchone()[0], 1)
        self.assertEqual(retry["evidence"], self.profile["evidence"])

    def test_same_id_retry_dispatches_reconciliation_only_and_finalizes_partial(self):
        retry = self._retry()
        captured = []
        client = self._synthetic_reconciliation_client(retry, captured)
        result = client.invoke(
            "reconcile_partial", REQUEST_ID, ACTOR, trigger="manual", manual_authorized=True,
            reconciliation_id=RECONCILIATION_ID, request_fingerprint=self.fingerprint,
            evidence=retry["evidence"],
        )
        self.assertEqual(captured, [{
            "action": "reconcile_partial", "reconciliation_id": RECONCILIATION_ID,
            "request_fingerprint": self.fingerprint, "expected_digest_is_null": True, "timeout": 390,
        }])
        self.assertFalse(result["checkpointPresent"])
        self.assertFalse(result["resumeAuthorized"])
        self.assertEqual(result["nextAction"], "NEW_PREVIEW_REQUIRED")
        finalized = execution.finalize_partial_reconciliation(
            self.path, RECONCILIATION_ID, ACTOR, result, now=NOW
        )
        self.assertEqual(finalized["status"], "RECONCILED_PARTIAL")
        audit = self._audit_row()
        self.assertEqual(audit[7], "reconciled_partial")
        self.assertEqual(audit[14] == "{}", False)
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM google_writer_run_reconciliations").fetchone()[0], 1)

    def test_different_reconciliation_id_cannot_reuse_prepared_intent(self):
        before = self._audit_row()
        with self.assertRaises(RuntimeError):
            self._retry(reconciliation_id="a" * 32)
        self.assertEqual(self._audit_row(), before)

    def test_different_supported_fingerprint_cannot_reuse_prepared_intent(self):
        before = self._audit_row()
        with self.assertRaises(RuntimeError):
            self._retry(fingerprint="18a4aba10c1c13ab3bf59f56")
        self.assertEqual(self._audit_row(), before)

    def test_changed_evidence_or_evidence_digest_rejects_same_id_without_mutation(self):
        for column, value in (("evidence_json", "{}"), ("evidence_digest", "A" * 43)):
            with self.subTest(column=column):
                with closing(sqlite3.connect(self.path)) as con, con:
                    con.execute(
                        f"UPDATE google_writer_run_reconciliations SET {column}=? WHERE reconciliation_id=?",
                        (value, RECONCILIATION_ID),
                    )
                before = self._audit_row()
                with self.assertRaises(RuntimeError):
                    self._retry()
                self.assertEqual(self._audit_row(), before)

    def test_changed_saved_preview_digest_or_scope_rejects_same_id(self):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute(
                "UPDATE google_writer_runs SET result_json=json_set(result_json,'$.plan_scope','ALL') WHERE request_id=?",
                (REQUEST_ID,),
            )
        before = self._audit_row()
        with self.assertRaises(RuntimeError):
            self._retry()
        self.assertEqual(self._audit_row(), before)

        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute(
                "UPDATE google_writer_runs SET result_json=json_set(result_json,'$.plan_scope','APPEND_ONLY',"
                "'$.plan_digest',?) WHERE request_id=?",
                ("A" * 43, REQUEST_ID),
            )
        before = self._audit_row()
        with self.assertRaises(RuntimeError):
            self._retry()
        self.assertEqual(self._audit_row(), before)

    def test_changed_run_status_or_result_rejects_same_id(self):
        before = self._audit_row()
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("UPDATE google_writer_runs SET status='partial' WHERE request_id=?", (REQUEST_ID,))
        with self.assertRaises(RuntimeError):
            self._retry()
        self.assertEqual(self._audit_row(), before)


if __name__ == "__main__":
    unittest.main()
