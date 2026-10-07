"""Synthetic source-parity regressions; no live reassessment/backfill."""
import json
import os
import unittest
from unittest.mock import patch

import supplier_evidence_projection_v3 as adapter
import supplier_evidence_shadow_hooks_v3 as hooks
import supplier_evidence_recording_v3 as recording
import test_supplier_evidence_projection_v3 as fixtures

NOW = fixtures.NOW


SIX = [
    ("33897714", "7d80c3532c3346ff8d9a1d0d7ee30a70", "2026-09-16", "Дмитро САВВА", None),
    ("3151613633", "48df19b0ed28482d9f0e21ba2dc766b0", "2026-09-10", "Олена ЄРЬОМІНА", 1864),
    ("41850560", "30ad216ed0924961820666dbd88133fa", "2026-09-23", "Дмитро САВВА", None),
    ("22818209", "6c06a2425fc14050a9a85d7b27349e18", "2026-09-21", "Дмитро САВВА", None),
    ("40730562", "d569b57262e743c986aff78eb79eb41d", "2026-09-01", "Світлана НАМЯСЕНКО", 8088),
    ("14107262", "58990ae5ff524eaf921c82ec178e11ea", "2026-09-18", "Світлана НАМЯСЕНКО", 8165),
]


class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.fx = fixtures.ProjectionTests("runTest")
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.con = self.fx.con
        self.flag = patch.dict(os.environ, {hooks.FLAG: "1"})
        self.flag.start()
        self.addCleanup(self.flag.stop)

    def seed(self, case):
        code, sid, day, officer, ledger_id = case
        self.fx.inclusion(code, identity="c" + code)
        stamp = ("2026-01-01" if ledger_id else day) + "T10:23:03.852267+03:00"
        self.fx.application(code, identity=sid, stamp=stamp, officer=officer)
        if ledger_id:
            self.fx.legacy_google(code, identity=ledger_id, day=day, officer=officer)

    def count(self, table):
        return self.con.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]

    def gap(self, code, history=False):
        return recording.observe_gap(self.con, environment="sandbox", supplier_code=code,
            source_system="fixture", source_object="supplier", source_id="gap" + code + str(history),
            observed_at=NOW, payload={}, gaps=[dict(
                gap_type="transition_date_unproven" if history else "missing_verification_evidence",
                gap_reason="fixture", review_scope="history_only" if history else "active",
                remediation="provenance_review" if history else "factual_verification",
                recommended_action="fixture")])

    def test_six_live_regressions_baseline_no_gap_no_backfill(self):
        for case in SIX:
            with self.subTest(code=case[0]):
                self.seed(case)
                code, _, day, officer, _ = case
                p = hooks._project(self.con, code, NOW)
                v = p["last_verification_event"]
                self.assertEqual(v["effective_date"], day)
                self.assertEqual(v["actor"]["actor_display"], officer)
                self.assertNotIn("missing_verification_evidence", p["gaps"])
        self.assertEqual(self.count("supplier_evidence_events_v3"), 0)
        self.assertEqual(self.count("supplier_evidence_gaps_v3"), 0)

    def test_future_rejection_boundary_resolves_external_gap_once(self):
        for case in SIX:
            with self.subTest(code=case[0]):
                self.seed(case)
                code = case[0]
                self.gap(code)
                self.gap(code, history=True)
                sid = "reject" + code
                self.fx.application(code, identity=sid, stamp="2026-10-07T09:00:00+03:00", status="unsuccessful")
                hooks.application_decision(self.con, sid, "reject", NOW)
                row = self.con.execute("SELECT r.evidence_event_id,r.assessment_json FROM supplier_evidence_gap_resolutions_v3 r JOIN supplier_evidence_gaps_v3 g ON g.gap_id=r.gap_id JOIN supplier_evidence_observations_v3 o ON o.observation_id=g.observation_id WHERE o.supplier_code=?", (code,)).fetchone()
                self.assertIsNotNone(row)
                self.assertIsNone(row[0])  # External proof, not a fabricated native FK.
                proof = json.loads(row[1])["evidence_reference"]
                self.assertEqual(proof["effective_date"], case[2])
                self.assertEqual(proof["supplier_code"], code)
                n = self.con.total_changes
                hooks.application_decision(self.con, sid, "reject", NOW)
                self.assertEqual(self.count("supplier_evidence_gap_resolutions_v3"), SIX.index(case) + 1)
                self.assertGreaterEqual(self.con.total_changes, n)  # Cache refresh allowed on boundary replay.
        self.assertEqual(self.count("supplier_evidence_events_v3"), 0)
        self.assertEqual(self.count("supplier_evidence_gap_resolutions_v3"), 6)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM supplier_evidence_gaps_v3 g JOIN supplier_evidence_gap_resolutions_v3 r ON r.gap_id=g.gap_id WHERE g.review_scope='history_only'").fetchone()[0], 0)

    def test_get_never_resolves_persisted_gap(self):
        self.seed(SIX[0])
        self.gap(SIX[0][0])
        before = self.con.total_changes
        p = self.fx.read(SIX[0][0])
        self.assertIsNotNone(p["last_verification_event"])
        self.assertIn("missing_verification_evidence", p["gaps"])
        self.assertEqual(self.con.total_changes, before)
        self.assertEqual(self.count("supplier_evidence_gap_resolutions_v3"), 0)

    def test_malformed_google_fails_closed_without_import_time_fallback(self):
        self.fx.inclusion("1")
        self.fx.legacy_google("1", changes={"source_digest": "bad"})
        p = hooks._project(self.con, "1", NOW)
        self.assertIsNone(p["last_verification_event"])
        self.assertEqual(self.count("supplier_evidence_events_v3"), 0)
        self.assertEqual(self.count("supplier_evidence_gaps_v3"), 1)

    def test_rejection_and_normalization_are_not_verification(self):
        self.fx.inclusion("1")
        self.fx.application("1", status="unsuccessful")
        self.fx.legacy_google("1", changes={"attribution_only": True})
        p = hooks._project(self.con, "1", NOW)
        self.assertIsNone(p["last_verification_event"])

    def test_google_facts_remain_carried_not_reverified(self):
        self.seed(SIX[1])
        p = hooks._project(self.con, SIX[1][0], NOW)
        v = p["last_verification_event"]
        self.assertFalse(v["provenance"]["factual_snapshot_present"])
        self.assertFalse(v["provenance"]["factual_context"]["verified_by_this_event"])

    def test_contract_before_admission_hook_needs_no_gap_or_reordering(self):
        case = SIX[0]
        self.seed(case)  # Qualification and application already in source snapshot.
        code = case[0]
        item = dict(id="c" + code, status="active", suppliers=[dict(identifier=dict(id=code))])
        hooks.contract_written(self.con, item=item, previous=None, recorded_at=NOW)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM supplier_evidence_gaps_v3 WHERE gap_type='missing_verification_evidence'").fetchone()[0], 0)
        self.assertEqual(self.count("supplier_evidence_events_v3"), 0)
        hooks.application_decision(self.con, case[1], "admit", NOW)
        self.assertEqual(self.count("supplier_evidence_events_v3"), 1)
        self.assertEqual(self.count("supplier_evidence_gap_resolutions_v3"), 0)

    def test_canonical_selector_shared_not_read_dispatch(self):
        self.seed(SIX[0])
        with patch.object(adapter, "verification_evidence", wraps=adapter.verification_evidence) as shared:
            hooks._project(self.con, SIX[0][0], NOW)
            self.assertEqual(shared.call_count, 1)
        self.assertFalse(adapter.read_enabled())

    def test_shared_selector_prod_isolation_before_db_read(self):
        with patch.dict(os.environ, {"RENDER_SERVICE_ID": "prod"}), self.assertRaises(PermissionError):
            adapter.verification_evidence(None, "1", as_of=NOW[:10])

    def test_transaction_rollback_removes_external_resolution_and_cache(self):
        self.seed(SIX[0])
        self.gap(SIX[0][0])
        self.con.commit()
        self.con.execute("BEGIN")
        hooks._project(self.con, SIX[0][0], NOW)
        self.assertEqual(self.count("supplier_evidence_gap_resolutions_v3"), 1)
        self.con.rollback()
        self.assertEqual(self.count("supplier_evidence_gap_resolutions_v3"), 0)
        self.assertEqual(self.count("supplier_evidence_current_v3"), 0)

    def test_newer_known_gap_not_closed_by_older_baseline(self):
        self.seed(SIX[0])
        recording.observe_gap(self.con, environment="sandbox", supplier_code=SIX[0][0],
            source_system="fixture", source_object="supplier", source_id="newer-gap",
            observed_at=NOW, payload={}, gaps=[dict(gap_type="missing_verification_evidence",
                gap_reason="fixture", review_scope="active", remediation="factual_verification",
                known_event_date="2026-10-07", recommended_action="fixture")])
        hooks._project(self.con, SIX[0][0], NOW)
        self.assertEqual(self.count("supplier_evidence_gap_resolutions_v3"), 0)

    def test_source_budget_failure_in_selector_has_zero_writes(self):
        self.seed(SIX[0])
        before = self.con.total_changes
        with patch.object(adapter, "MAX_SOURCE_ROWS", 0), self.assertRaises(adapter.SourceBudgetExceeded):
            hooks._legacy_verification_baseline(self.con, SIX[0][0], set(), NOW[:10])
        self.assertEqual(self.con.total_changes, before)

    def test_source_budget_failure_rolls_back_actual_admission_boundary(self):
        self.seed(SIX[0])
        self.con.commit()
        self.con.execute("BEGIN")
        with patch.object(adapter, "MAX_SOURCE_ROWS", 0), self.assertLogs(hooks.LOG, level="ERROR") as logs:
            hooks.application_decision(self.con, SIX[0][1], "admit", NOW)
        self.assertIn("SourceBudgetExceeded", logs.output[0])
        self.assertEqual(self.count("supplier_evidence_events_v3"), 0)
        self.assertEqual(self.count("supplier_evidence_current_v3"), 0)
        self.assertEqual(self.count("supplier_evidence_gap_resolutions_v3"), 0)

    def test_unchanged_boundary_does_not_repeat_resolution(self):
        self.seed(SIX[0])
        self.gap(SIX[0][0])
        hooks._project(self.con, SIX[0][0], NOW)
        first = self.con.execute("SELECT * FROM supplier_evidence_gap_resolutions_v3").fetchall()
        hooks._project(self.con, SIX[0][0], "2026-10-08T12:00:00+03:00")
        self.assertEqual(self.con.execute("SELECT * FROM supplier_evidence_gap_resolutions_v3").fetchall(), first)

    def test_synthetic_manual_and_lifecycle_mirror_not_baseline(self):
        self.fx.inclusion("1")
        self.fx.check("1", native=False, snapshot={"edr_status": "Зареєстровано", "synthetic": True})
        self.assertEqual(hooks._legacy_verification_baseline(self.con, "1", set(), NOW[:10]), [])

    def test_no_chronology_id_tiebreak_for_same_timestamp(self):
        self.fx.inclusion("1")
        self.fx.application("1", identity="a", officer="Олена ЄРЬОМІНА")
        self.fx.application("1", identity="z", officer="Дмитро САВВА")
        p = hooks._project(self.con, "1", NOW)
        self.assertIsNone(p["last_verification_event"])
        self.assertEqual(self.count("supplier_evidence_events_v3"), 0)

    def test_synthetic_35_admissions_and_42_rejections_keep_semantics(self):
        for i in range(35):
            code = str(10000000 + i)
            self.fx.inclusion(code, identity="c" + code)
            self.fx.application(code, identity="admit" + code)
            hooks.application_decision(self.con, "admit" + code, "admit", NOW)
        for i in range(42):
            code = str(10000000 + i) if i < 11 else str(20000000 + i)
            sid = "reject" + str(i)
            self.fx.application(code, identity=sid, stamp="2026-10-07T09:00:00+03:00", status="unsuccessful")
            before = self.con.execute("SELECT last_verification_event_id FROM supplier_evidence_current_v3 WHERE supplier_code=?", (code,)).fetchone()
            hooks.application_decision(self.con, sid, "reject", NOW)
            if i < 11:
                after = self.con.execute("SELECT last_verification_event_id FROM supplier_evidence_current_v3 WHERE supplier_code=?", (code,)).fetchone()
                self.assertEqual(before, after)
        self.assertEqual(self.count("supplier_evidence_events_v3"), 35)
        observations = self.con.execute("SELECT payload_json FROM supplier_evidence_observations_v3 WHERE source_object='rejection'").fetchall()
        self.assertEqual(len(observations), 42)
        self.assertEqual(sum(json.loads(row[0])["ever_admitted"] for row in observations), 11)
        self.assertEqual(self.count("supplier_evidence_gaps_v3"), 0)


if __name__ == "__main__":
    unittest.main()
