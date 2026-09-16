import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import nazk_registry_evidence as evidence
import reference_directories as refs


class DurableRegistryEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "fixture.sqlite3"
        refs.init_reference_tables(self.path)
        self.con = sqlite3.connect(self.path)
        self.con.executescript("""
          CREATE TABLE supplier_nazk_checks(id INTEGER PRIMARY KEY,result TEXT,workflow_status TEXT);
          INSERT INTO supplier_nazk_checks VALUES(112,NULL,'needs_review');
          CREATE TABLE supplier_nazk_check_matches(
            check_id INTEGER NOT NULL REFERENCES supplier_nazk_checks(id) ON DELETE CASCADE,
            nazk_source_id TEXT NOT NULL REFERENCES nazk_registry(source_id),
            match_status TEXT NOT NULL DEFAULT 'candidate',created_at TEXT NOT NULL,
            PRIMARY KEY(check_id,nazk_source_id));
          CREATE INDEX ix_supplier_nazk_matches_source ON supplier_nazk_check_matches(nazk_source_id);
          INSERT INTO nazk_registry(source_id,full_name) VALUES('current','CURRENT PERSON');
          INSERT INTO supplier_nazk_check_matches VALUES(112,'current','candidate','2026-09-11');
          INSERT INTO supplier_nazk_check_matches VALUES(112,'missing','candidate','2026-09-11');
        """)
        self.record = dict.fromkeys(evidence.FIELDS)
        self.record.update(source_id="missing", full_name="HISTORICAL PERSON", raw_json='{"id":"missing"}')
        self.recovery = {"missing": {"record": self.record, "artifact_sha256": "a" * 64,
                         "artifact_name": "web-audit.json", "observed_at": "2026-09-13T00:00:00Z",
                         "relations": [{"check_id": 112, "nazk_source_id": "missing",
                         "match_status": "candidate", "created_at": "2026-09-11"}]}}
        self.plan = evidence.make_plan(self.con, self.recovery, "2026-09-16T00:00:00Z")

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def apply(self, plan=None):
        plan = plan or self.plan
        return evidence.apply_plan(self.con, plan, evidence.digest(plan))

    def test_repair_preserves_every_link_and_factual_field_and_is_idempotent(self):
        before = evidence.source_state(self.con)
        result = self.apply()
        self.assertEqual(result["relation_changes"], 0)
        self.assertEqual(evidence.source_state(self.con), before)
        self.assertEqual(self.con.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(self.con.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        changes = self.con.total_changes
        self.assertEqual(self.apply()["source_inserts"], 0)
        self.assertEqual(self.con.total_changes, changes)
        self.assertEqual(self.con.execute(f"SELECT COUNT(*) FROM {evidence.RECEIPTS}").fetchone()[0], 1)

    def test_history_never_becomes_a_current_match(self):
        self.apply()
        self.assertIsNone(self.con.execute("SELECT 1 FROM nazk_registry WHERE source_id='missing'").fetchone())
        records = {r["source_id"]: r for r in evidence.registry_records(self.con, 112)}
        self.assertFalse(records["missing"]["current_registry_present"])
        self.assertEqual(records["missing"]["registry_source"], "historical_web_snapshot")
        self.assertEqual(records["missing"]["full_name"], "HISTORICAL PERSON")
        self.assertTrue(records["current"]["current_registry_present"])

    def test_manifest_mismatch_writes_nothing(self):
        changes = self.con.total_changes
        with self.assertRaisesRegex(ValueError, "hash"):
            evidence.apply_plan(self.con, self.plan, "wrong")
        self.assertEqual(self.con.total_changes, changes)
        self.assertEqual(evidence.parent(self.con), "nazk_registry")

    def test_changed_preconditions_stop(self):
        self.con.execute("UPDATE supplier_nazk_checks SET workflow_status='waiting_response'")
        self.con.commit()
        with self.assertRaisesRegex(ValueError, "preconditions"):
            self.apply()
        self.assertEqual(evidence.parent(self.con), "nazk_registry")

    def test_wrong_historical_link_stops(self):
        recovery = copy.deepcopy(self.recovery)
        recovery["missing"]["relations"][0]["check_id"] = 999
        with self.assertRaisesRegex(ValueError, "historical relations"):
            evidence.make_plan(self.con, recovery, "now")

    def test_unrelated_fk_error_stops(self):
        self.con.execute("INSERT INTO supplier_nazk_check_matches VALUES(999,'current','candidate','now')")
        self.con.commit()
        with self.assertRaisesRegex(ValueError, "unexpected FK"):
            evidence.make_plan(self.con, self.recovery, "now")

    def test_sql_failure_rolls_back_schema_and_data(self):
        with patch.object(evidence, "install_capture_trigger", side_effect=RuntimeError("injected")):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                self.apply()
        self.assertEqual(evidence.parent(self.con), "nazk_registry")
        self.assertIsNone(self.con.execute("SELECT name FROM sqlite_master WHERE name=?", (evidence.TABLE,)).fetchone())
        self.assertEqual(evidence.digest(evidence.source_state(self.con)), self.plan["state_sha256"])

    def test_evidence_and_receipts_cannot_be_rewritten(self):
        self.apply()
        for table in (evidence.TABLE, evidence.RECEIPTS):
            for sql in (f"DELETE FROM {table}", f"UPDATE {table} SET rowid=rowid"):
                with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                    self.con.execute(sql)
                self.con.rollback()

    def test_new_link_requires_current_source_not_just_history(self):
        self.apply()
        self.con.execute("INSERT INTO supplier_nazk_checks VALUES(113,NULL,'needs_review')")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "current registry"):
            self.con.execute("INSERT INTO supplier_nazk_check_matches VALUES(113,'missing','candidate','now')")
        self.con.execute("INSERT INTO nazk_registry(source_id,full_name) VALUES('new','NEW PERSON')")
        self.con.execute("INSERT INTO supplier_nazk_check_matches VALUES(113,'new','candidate','now')")
        self.assertIsNotNone(self.con.execute(f"SELECT 1 FROM {evidence.TABLE} WHERE source_id='new'").fetchone())
        self.con.commit()

    def test_current_refresh_retains_evidence_links_and_does_not_write_checks(self):
        self.apply()
        before = evidence.source_state(self.con)
        callback = Mock()
        with patch.object(refs, "_fetch", return_value=b'[{"id":"new","indLastNameOnOffenseMoment":"OTHER"}]'):
            refs.refresh_nazk(self.path, on_complete=callback)
        self.assertEqual(refs.reference_status(self.path)["nazk"]["status"], "ok")
        self.assertEqual(evidence.source_state(self.con)["checks"], before["checks"])
        self.assertEqual(evidence.source_state(self.con)["matches"], before["matches"])
        self.assertEqual(self.con.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertFalse(next(r for r in evidence.registry_records(self.con, 112) if r["source_id"] == "current")["current_registry_present"])
        callback.assert_called_once()

    def test_legacy_refresh_fails_closed_and_does_not_call_workflow(self):
        callback = Mock()
        with patch.object(refs, "_fetch", return_value=b'[{"id":"new"}]'):
            refs.refresh_nazk(self.path, on_complete=callback)
        self.assertEqual(refs.reference_status(self.path)["nazk"]["status"], "error")
        self.assertIsNotNone(self.con.execute("SELECT 1 FROM nazk_registry WHERE source_id='current'").fetchone())
        callback.assert_not_called()

    def test_empty_duplicate_or_missing_ids_leave_current_registry_unchanged(self):
        self.apply()
        for payload in ([], [{"id": "x"}, {"id": "x"}], [{"name": "bad"}], [42]):
            callback = Mock()
            with patch.object(refs, "_fetch", return_value=json.dumps(payload).encode()):
                refs.refresh_nazk(self.path, on_complete=callback)
            self.assertEqual(refs.reference_status(self.path)["nazk"]["status"], "error")
            self.assertIsNotNone(self.con.execute("SELECT 1 FROM nazk_registry WHERE source_id='current'").fetchone())
            callback.assert_not_called()

    def test_schema_init_is_not_an_automatic_migration(self):
        before = evidence.source_state(self.con)
        evidence.ensure_schema(self.con)
        evidence.install_capture_trigger(self.con)
        self.assertEqual(evidence.source_state(self.con), before)
        self.assertEqual(evidence.parent(self.con), "nazk_registry")
        self.assertEqual(self.con.execute(f"SELECT COUNT(*) FROM {evidence.TABLE}").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
