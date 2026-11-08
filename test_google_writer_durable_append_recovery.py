"""Durable, idempotent Sandbox APPEND_ONLY journal and recovery tests."""

import base64
import collections
import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import google_writer_execution as execution


ACTOR = "sandbox-operator"
NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


def digest(value):
    return base64.urlsafe_b64encode(hashlib.sha256(value).digest()).decode("ascii").rstrip("=")


class DurableAppendRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent, prefix="writer-durable-recovery-")
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "writer.sqlite3")
        with closing(sqlite3.connect(self.path)) as con:
            execution.migrate(con)
            con.commit()
        self.run_id = "a" * 32
        self.env_patch = patch.dict(os.environ, {"PQM_SANDBOX_AUTO_CONTINUE_CHUNKS": "0"})
        self.env_patch.start(); self.addCleanup(self.env_patch.stop)
        self.full_digest = digest(b"full"); self.append_digest = digest(b"append")
        self.source_digest = digest(b"source")
        self.details = self._details(50)
        self.snapshot = execution.store_preview_plan(self.path, self.run_id, ACTOR, self.details, now=NOW)

    def _details(self, count):
        appends = []
        for i in range(count):
            code = f"{i + 1:010d}"
            appends.append({"operation": "APPEND", "tab": "ФОП", "code": code, "cells": [
                {"column": "A", "formula": True, "new_value": "=TODAY()"},
                {"column": "B", "formula": False, "new_value": code},
            ]})
        return {"version": 1, "environment": "SANDBOX", "plan_digest": self.full_digest,
            "append_only_digest": self.append_digest, "source_digest": self.source_digest,
            "counts": {"append": count, "update": 0, "conflict": 0, "error": 0},
            "appends": appends, "updates": [], "conflicts": [], "errors": []}

    def _claim(self):
        return execution.claim_run(self.path, "SANDBOX", self.run_id, ACTOR, "manual",
            manual_authorized=True, plan_scope="APPEND_ONLY", plan_digest=self.append_digest,
            details_digest=self.snapshot["details_digest"], now=NOW)

    def _chunk_row(self, index=0):
        with closing(sqlite3.connect(self.path)) as con:
            row = con.execute("""SELECT chunk_id,chunk_digest,plan_id,plan_digest,status,expected_json
                                FROM google_writer_chunk_journal WHERE run_id=? AND chunk_index=?""",
                              (self.run_id, index)).fetchone()
        self.assertIsNotNone(row)
        return row

    def _receipt(self, index, *, status, append, more, checkpoint=None):
        row = self._chunk_row(index)
        self.assertEqual(row[4], "inflight")
        return {"status": status, "digest": row[3], "planScope": "APPEND_ONLY",
            "chunkIndex": index, "nextChunk": index + 1, "more": more, "phase": "append",
            "checkpointDigest": checkpoint or digest(f"checkpoint-{index}".encode()),
            "chunkId": row[0], "chunkDigest": row[1], "planId": row[2],
            "counts": {"append": append, "update": 0, "conflict": 0, "error": 0,
                       "remaining_safe": max(0, len(self.details["appends"]) - (index + 1) * 25),
                       "batches": 1}}

    def _client(self, side_effect):
        client = Mock(environment="SANDBOX")
        client.invoke.side_effect = side_effect
        return client

    def test_saved_preview_remains_reviewable_after_ttl_but_apply_ticket_has_no_ttl(self):
        loaded = execution.load_preview_plan(self.path, self.run_id, ACTOR, self.full_digest,
            details_digest=self.snapshot["details_digest"], now=NOW + timedelta(days=365))
        self.assertTrue(loaded["review_only_expiry"])
        self.assertIsNone(loaded["expires_at"])
        client = Mock(environment="SANDBOX", shared_secret="synthetic-secret", clock=lambda: NOW)
        ticket = execution.preview_ticket(client, self.run_id, ACTOR, self.full_digest,
            parent_digest=self.full_digest, details_digest=self.snapshot["details_digest"])
        self.assertNotIn("expires_at", execution.verify_ticket(client, ticket, ACTOR))

    def test_write_ahead_chunk_is_immutable_and_duplicate_inflight_claim_is_rejected(self):
        self._claim()
        first = execution.prepare_append_chunk(self.path, self.run_id, ACTOR, self.append_digest,
            self.snapshot["details_digest"], 0, now=NOW)
        again = execution.prepare_append_chunk(self.path, self.run_id, ACTOR, self.append_digest,
            self.snapshot["details_digest"], 0, now=NOW + timedelta(seconds=1))
        self.assertEqual(first["chunk_id"], again["chunk_id"])
        self.assertTrue(execution.mark_append_chunk_inflight(self.path, first["chunk_id"], now=NOW))
        with self.assertRaises(RuntimeError):
            execution.prepare_append_chunk(self.path, self.run_id, ACTOR, self.append_digest,
                self.snapshot["details_digest"], 0, now=NOW + timedelta(seconds=2))
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM google_writer_chunk_journal").fetchone()[0], 1)

    def test_lost_response_is_recovered_by_exact_receipt_without_second_apply(self):
        self._claim()
        calls = []
        def call(action, *args, **kwargs):
            calls.append(action)
            if action == "apply": raise execution.ExecutionOutcomeUnknown("synthetic lost response")
            return self._receipt(0, status="CHUNK_RECOVERED", append=25, more=True)
        client = self._client(call)
        result = execution.execute_claimed(self.path, client, self.run_id, ACTOR,
            digest=self.append_digest, manual_authorized=True, plan_scope="APPEND_ONLY",max_append_chunks=1)
        self.assertEqual(calls, ["apply", "recover_append_chunk"])
        self.assertEqual(result["status"], "HALTED_AFTER_VERIFIED_CHECKPOINTS")
        state = execution.chunk_journal_state(self.path, self.run_id)
        self.assertEqual((state["verified_chunks"], state["unknown_chunks"]), (1, 0))
        with closing(sqlite3.connect(self.path)) as con:
            status, progress = con.execute("SELECT status,result_json FROM google_writer_runs").fetchone()
        self.assertEqual(status, "partial")
        self.assertEqual(json.loads(progress)["verified_totals"]["append"], 25)

    def test_proven_zero_write_allows_exactly_one_same_chunk_attempt(self):
        self._claim()
        calls = []
        def call(action, *args, **kwargs):
            calls.append(action)
            if action == "apply" and calls.count("apply") == 1:
                raise execution.ExecutionOutcomeUnknown("synthetic timeout")
            if action == "recover_append_chunk":
                row = self._chunk_row(0)
                return {"status": "CHUNK_NOT_APPLIED", "digest": self.append_digest,
                    "planScope": "APPEND_ONLY", "chunkIndex": 0, "nextChunk": 0,
                    "chunkId": row[0], "chunkDigest": row[1], "planId": row[2],
                    "counts": {"append": 0, "update": 0, "batches": 0}}
            return self._receipt(0, status="APPLY_CHUNK_VERIFIED", append=25, more=True)
        client = self._client(call)
        result = execution.execute_claimed(self.path, client, self.run_id, ACTOR,
            digest=self.append_digest, manual_authorized=True, plan_scope="APPEND_ONLY",max_append_chunks=1)
        self.assertEqual(calls, ["apply", "recover_append_chunk", "apply"])
        self.assertEqual(result["status"], "HALTED_AFTER_VERIFIED_CHECKPOINTS")
        self.assertEqual(execution.chunk_journal_state(self.path, self.run_id)["verified_chunks"], 1)

    def test_ambiguous_recovery_stays_held_and_does_not_replay_apply(self):
        self._claim(); calls = []
        def call(action, *args, **kwargs):
            calls.append(action)
            raise execution.ExecutionOutcomeUnknown("synthetic unknown")
        result = execution.execute_claimed(self.path, self._client(call), self.run_id, ACTOR,
            digest=self.append_digest, manual_authorized=True, plan_scope="APPEND_ONLY")
        self.assertEqual(result["status"], "OUTCOME_UNKNOWN_HOLD_NO_RETRY")
        self.assertEqual(calls, ["apply", "recover_append_chunk"])
        self.assertEqual(execution.chunk_journal_state(self.path, self.run_id)["unknown_chunks"], 1)

    def test_unknown_chunk_can_be_read_only_recovered_after_worker_restart(self):
        self._claim()
        def initial(action, *args, **kwargs):
            if action == "apply": raise execution.ExecutionOutcomeUnknown("lost")
            raise execution.ExecutionOutcomeUnknown("recovery transport unavailable")
        initial_result = execution.execute_claimed(self.path, self._client(initial), self.run_id, ACTOR,
            digest=self.append_digest, manual_authorized=True, plan_scope="APPEND_ONLY")
        self.assertEqual(initial_result["status"], "OUTCOME_UNKNOWN_HOLD_NO_RETRY")
        calls = []
        def recovered(action, *args, **kwargs):
            calls.append(action)
            self.assertEqual(action, "recover_append_chunk")
            return self._receipt(0, status="CHUNK_RECOVERED", append=25, more=True)
        result = execution.recover_interrupted_append_chunk(self.path, self._client(recovered),
            self.run_id, ACTOR, now=NOW + timedelta(seconds=1))
        self.assertEqual(result["status"], "HALTED_AFTER_VERIFIED_CHECKPOINTS")
        self.assertEqual(calls, ["recover_append_chunk"])
        self.assertEqual(execution.chunk_journal_state(self.path, self.run_id)["unknown_chunks"], 0)

    def test_interrupted_running_chunk_waits_for_stale_window_and_uses_recovery_lease(self):
        self._claim()
        chunk = execution.prepare_append_chunk(self.path, self.run_id, ACTOR, self.append_digest,
            self.snapshot["details_digest"], 0, now=NOW)
        execution.mark_append_chunk_inflight(self.path, chunk["chunk_id"], now=NOW)
        self.assertIsNone(execution.claim_interrupted_append_chunk_recovery(self.path, self.run_id,
            now=NOW + timedelta(seconds=899)))
        claimed = execution.claim_interrupted_append_chunk_recovery(self.path, self.run_id,
            now=NOW + timedelta(seconds=901))
        self.assertEqual(claimed["chunk_id"], chunk["chunk_id"])
        self.assertIsNone(execution.claim_interrupted_append_chunk_recovery(self.path, self.run_id,
            now=NOW + timedelta(seconds=902)))
        self.assertIsNone(execution.claim_interrupted_append_chunk_recovery(self.path, self.run_id,
            now=NOW + timedelta(seconds=1500)))
        claimed_again = execution.claim_interrupted_append_chunk_recovery(self.path, self.run_id,
            now=NOW + timedelta(seconds=1502))
        self.assertEqual(claimed_again["chunk_id"], chunk["chunk_id"])

    def test_auto_continues_only_after_verified_checkpoint_and_never_sends_updates(self):
        self.env_patch.stop()
        self.env_patch = patch.dict(os.environ,{"PQM_SANDBOX_AUTO_CONTINUE_CHUNKS":"1"})
        self.env_patch.start();self.addCleanup(self.env_patch.stop)
        self._claim(); calls = []
        def call(action, *args, **kwargs):
            calls.append((action, kwargs.get("chunk_index")))
            if action == "resume_check":
                remaining = self.details["appends"][25:]
                return {"status": "RESUME_READY", "digest": self.append_digest,
                    "planScope": "APPEND_ONLY", "chunkIndex": 1, "nextChunk": 1,
                    "checkpointDigest": kwargs["expected_checkpoint_digest"],
                    "counts": {"append": len(remaining), "update": 0},
                    "planDetails": {"version": 1, "environment": "SANDBOX",
                        "plan_digest": self.append_digest, "remaining_plan_digest": digest(b"remaining"),
                        "appends": remaining, "updates": [], "conflicts": [], "errors": []}}
            index = kwargs["chunk_index"]
            return self._receipt(index, status="APPLY_CHUNK_VERIFIED" if index == 0 else "COMPLETE",
                append=25, more=index == 0)
        result = execution.execute_claimed(self.path, self._client(call), self.run_id, ACTOR,
            digest=self.append_digest, manual_authorized=True, plan_scope="APPEND_ONLY", max_append_chunks=1)
        self.assertEqual(result["status"], "COMPLETE")
        self.assertEqual(calls, [("apply", 0), ("resume_check", 1), ("apply", 1)])
        with closing(sqlite3.connect(self.path)) as con:
            progress = json.loads(con.execute("SELECT result_json FROM google_writer_runs").fetchone()[0])
        self.assertEqual(progress["counts"]["update"], 0)
        self.assertEqual(progress["counts"]["append"], 50)

    def test_326_append_pages_recover_lost_response_and_auto_continue_without_replay(self):
        self.env_patch.stop()
        self.env_patch = patch.dict(os.environ,{"PQM_SANDBOX_AUTO_CONTINUE_CHUNKS":"1"})
        self.env_patch.start();self.addCleanup(self.env_patch.stop)
        self.run_id = "b" * 32
        self.details = self._details(326)
        for index, item in enumerate(self.details["appends"]):
            item["tab"] = "ФОП" if index % 2 == 0 else "ЮО"
        self.snapshot = execution.store_preview_plan(self.path,self.run_id,ACTOR,self.details,now=NOW)
        self._claim()
        calls=[];apply_counts=collections.Counter();lost_chunk=2

        def call(action,*_args,**kwargs):
            index=kwargs.get("chunk_index")
            calls.append((action,index))
            if action=="resume_check":
                remaining=self.details["appends"][index*25:]
                return {"status":"RESUME_READY","digest":self.append_digest,
                    "planScope":"APPEND_ONLY","chunkIndex":index,"nextChunk":index,
                    "checkpointDigest":kwargs["expected_checkpoint_digest"],
                    "counts":{"append":len(remaining),"update":0},
                    "planDetails":{"version":1,"environment":"SANDBOX",
                        "plan_digest":self.append_digest,"remaining_plan_digest":digest(b"remaining"),
                        "appends":remaining,"updates":[],"conflicts":[],"errors":[]}}
            if action=="apply":
                apply_counts[index]+=1
                if index==lost_chunk:
                    raise execution.ExecutionOutcomeUnknown("synthetic lost HTTP response after write")
                count=min(25,len(self.details["appends"])-index*25)
                more=(index+1)*25<len(self.details["appends"])
                return self._receipt(index,status="APPLY_CHUNK_VERIFIED" if more else "COMPLETE",
                    append=count,more=more)
            if action=="recover_append_chunk":
                count=min(25,len(self.details["appends"])-index*25)
                more=(index+1)*25<len(self.details["appends"])
                return self._receipt(index,status="CHUNK_RECOVERED",append=count,more=more)
            raise AssertionError("unexpected Execution API action")

        result=execution.execute_claimed(self.path,self._client(call),self.run_id,ACTOR,
            digest=self.append_digest,manual_authorized=True,plan_scope="APPEND_ONLY",max_append_chunks=4)
        self.assertEqual(result["status"],"COMPLETE")
        self.assertEqual(result["counts"]["append"],326)
        self.assertEqual(result["counts"]["update"],0)
        # 326 records require fourteen 25-row chunks (the last holds one row).
        self.assertEqual(apply_counts,collections.Counter({index:1 for index in range(14)}))
        self.assertEqual(calls.count(("recover_append_chunk",lost_chunk)),1)
        self.assertEqual(sum(action=="resume_check" for action,_index in calls),3)
        state=execution.chunk_journal_state(self.path,self.run_id)
        self.assertEqual((state["verified_chunks"],state["unknown_chunks"]),(14,0))
        with closing(sqlite3.connect(self.path)) as con:
            status,raw=con.execute("SELECT status,result_json FROM google_writer_runs WHERE request_id=?",
                (self.run_id,)).fetchone()
        progress=json.loads(raw)
        self.assertEqual(status,"complete")
        self.assertEqual(progress["counts"]["append"],326)
        self.assertEqual(progress["counts"]["update"],0)


if __name__ == "__main__":
    unittest.main()
