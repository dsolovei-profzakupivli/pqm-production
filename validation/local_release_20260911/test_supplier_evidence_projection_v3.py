"""Synthetic read adapter acceptance. Natural lifecycle live status: LIVE_PENDING."""
import json
import os
from pathlib import Path
import sqlite3
import time
import tracemalloc
import unittest
from unittest.mock import Mock, patch

import supplier_evidence_projection_v3 as adapter
import supplier_evidence_recording_v3 as recording
from test_supplier_evidence_shadow_hooks_v3 import setup

NOW = "2026-10-07T12:00:00+03:00"
OFFICER = "Світлана НАМЯСЕНКО"
ENV = {"PQM_SANDBOX": "1", "RENDER_SERVICE_ID": adapter.SANDBOX_ID}
TWELVE = "2077003493 2886810864 2981518432 3385014935 3602006515 3618208369 3624813159 30795712 39984849 41141768 45547692 46120124".split()


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, ENV)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.con = sqlite3.connect(":memory:")
        setup(self.con)
        self.addCleanup(self.con.close)
        self.con.execute("CREATE TABLE supplier_edr_profiles(supplier_code TEXT,edr_status TEXT)")

    def inclusion(self, code, identity="c1", status="active", expiry=None):
        self.con.execute("INSERT INTO registry_contracts VALUES (?,?,?,?,?,?,?)",
            (identity, code, "f", "q", status, json.dumps({"expiryDate": expiry}), NOW))

    def application(self, code, identity="s1", stamp="2026-09-18T17:19:52+03:00", officer=OFFICER, status="active"):
        self.con.execute("INSERT INTO submissions VALUES (?,?,?,?,?)", (identity, code, stamp, "Supplier", "q" + identity))
        self.con.execute("INSERT INTO qualifications VALUES (?,?,?)", ("q" + identity, identity, status))
        self.con.execute("INSERT INTO application_fields VALUES (?,?,?)", (identity, officer, "Manager"))

    def check(self, code="45054758", identity=8699, day="2026-10-06", native=True, snapshot=None):
        snapshot = snapshot or {"edr_status": "Припинено",
            "full_name": 'ФІЛІЯ "БОРИСПІЛЬСЬКЕ ЛІСОВЕ ГОСПОДАРСТВО" ДЕРЖАВНОГО СПЕЦІАЛІЗОВАНОГО ГОСПОДАРСЬКОГО ПІДПРИЄМСТВА "ЛІСИ УКРАЇНИ"',
            "short_name": "—", "manager_name": "СТАХОВ ПЕТРО ПЕТРОВИЧ"}
        self.con.execute("INSERT INTO supplier_edr_verification_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (identity, code, "manual_edr", day, OFFICER, "frozen-receipt", "", "ЮО", 10, "[]", "hash", json.dumps(snapshot), NOW))
        if native:
            self.native(code, "edr_check", day[:10], str(identity), snapshot=snapshot,
                system="legacy_edr_ledger", stamp=day if "T" in day else None)

    def native(self, code, kind, day, identity, snapshot=None, system="prozorro", officer=OFFICER, stamp=None):
        actor = adapter._actor(kind, officer)
        provenance = {"supplier_level": True}
        if kind == "admission":
            provenance.update(submission_id=identity, qualification_id="q" + identity,
                submission_date_published=stamp)
        if kind in {"suspension", "resumption", "exclusion", "expiry"}:
            stamp = stamp or day + "T12:00:00+03:00"
            provenance.update(source_object="contract", source_id=identity, source_field="status",
                time_evidence="expiry_boundary" if kind == "expiry" else "source_transition",
                inclusion_id="c1", effective_active_before=1, effective_active_after=0)
        recording.append_event(self.con, supplier_code=code, kind=kind,
            effective_date=day, source_event_at=stamp, recorded_at=NOW,
            environment="sandbox", actor=actor, source_system=system,
            source_event_id=identity, snapshot=snapshot or {},
            provenance=provenance)

    def read(self, code):
        return adapter.project_supplier(self.con, code, as_of_at=NOW)

    def test_45054758_mirror_is_one_check(self):
        self.inclusion("45054758")
        self.check()
        result = self.read("45054758")
        self.assertEqual(result["logical_verification_count"], 1)
        self.assertEqual(result["current_event"]["event_id"], result["last_verification_event"]["event_id"])
        self.assertEqual(result["last_verification_date"], "2026-10-06")
        self.assertEqual(list(result["legacy_native_links"].values()), [[8699]])
        self.assertEqual(result["gaps"], [])
        self.assertIsNone(result["current_event"]["source_event_at"])
        self.assertEqual(result["current_event"]["snapshot_hash"], "cc27355d70609dba0ab24015b260d83a125a4b2e42cd5a79cfebb6289f6afa10")

    def test_repeated_read_is_noop(self):
        self.inclusion("45054758")
        self.check()
        before = self.con.total_changes
        first = self.read("45054758")
        self.assertEqual(first, self.read("45054758"))
        self.assertEqual(before, self.con.total_changes)

    def test_twelve_stale_active(self):
        for code in TWELVE:
            self.inclusion(code, "c" + code)
            self.application(code, "s" + code)
            self.con.execute("INSERT INTO supplier_edr_profiles VALUES (?,?)", (code, "Неактуально"))
        for code in TWELVE:
            with self.subTest(code=code):
                result = self.read(code)
                self.assertEqual(result["prozorro_status"], "Активний")
                self.assertEqual(result["edr_status_current"], "Зареєстровано")
                self.assertEqual(result["last_verification_date"], "2026-09-18")

    def test_three_same_day_admissions(self):
        code = TWELVE[0]
        self.inclusion(code)
        controls = [("e3edb5e958144b61b9d3320d23d2a120", "17:04:21.589075"),
            ("c1939b79afce43cfbef0eadf3a0566ff", "15:59:34.798180"),
            ("d27925ea7ed24af7bb4c1ec5deff4eb0", "17:19:52.579134")]
        for identity, stamp in controls:
            self.application(code, identity, "2026-09-18T" + stamp + "+03:00", "Тетяна ФЕДЧЕНКО")
        result = self.read(code)
        self.assertEqual(result["logical_verification_count"], 3)
        self.assertEqual(result["last_application"]["id"], controls[2][0])
        self.assertEqual(result["current_event"]["provenance"]["submission_id"], controls[2][0])

    def test_three_manual_admission_controls(self):
        controls = [("2077003493", "2026-09-18", "Тетяна ФЕДЧЕНКО"),
            ("2886810864", "2026-09-16", "Дмитро САВВА"),
            ("2981518432", "2026-09-22", "Дмитро САВВА")]
        for code, day, officer in controls:
            with self.subTest(code=code):
                self.inclusion(code, "c" + code)
                self.application(code, "s" + code, day + "T17:00:00+03:00", officer)
                result = self.read(code)
                self.assertEqual(result["last_verification_date"], day)
                self.assertEqual(result["last_verification_officer"], officer)

    def test_day_only_distinct_checks_explicit_ambiguity(self):
        self.inclusion("1")
        self.check("1", 1)
        snapshot = self.read("1")["factual_snapshot"]
        self.native("1", "edr_check", "2026-10-06", "2", system="manual_receipt", snapshot=snapshot)
        result = self.read("1")
        self.assertEqual(result["logical_verification_count"], 2)
        self.assertIsNone(result["last_verification_event"])
        self.assertIn("verification:ambiguous_same_day_events", result["gaps"])

    def test_missing_schema_is_not_created(self):
        con = sqlite3.connect(":memory:")
        self.addCleanup(con.close)
        setup(con, v3=False)
        before = con.execute("SELECT name FROM sqlite_master ORDER BY name").fetchall()
        result = adapter.project_supplier(con, "1", as_of_at=NOW)
        self.assertEqual(result["prozorro_status"], "Ще не в реєстрі")
        self.assertEqual(before, con.execute("SELECT name FROM sqlite_master ORDER BY name").fetchall())

    def test_read_gate_defaults_off_in_empty_environment(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(adapter.read_enabled())

    def test_profile_date_officer_not_promoted_to_event(self):
        self.inclusion("1")
        self.con.execute("INSERT INTO supplier_edr_profiles VALUES ('1','Неактуально')")
        result = self.read("1")
        self.assertEqual(result["logical_verification_count"], 0)
        self.assertIsNone(result["last_verification_date"])
        self.assertIn("missing_verification_evidence", result["gaps"])

    def test_natural_lifecycle_status_remains_live_pending(self):
        self.assertIn("LIVE_PENDING", Path(__file__).read_text(encoding="utf-8"))
        self.assertNotIn("LIVE_PASS", Path(adapter.__file__).read_text(encoding="utf-8"))

    def test_day_only_admissions_ambiguous_not_id_wins(self):
        self.inclusion("1")
        self.application("1", "z", "2026-09-18")
        self.application("1", "a", "2026-09-18")
        result = self.read("1")
        self.assertIsNone(result["current_event"])
        self.assertIn("latest_application:ambiguous_same_day_events", result["gaps"])

    def test_33345054_current_lifecycle_last_check_separate(self):
        self.inclusion("33345054", status="terminated")
        self.check("33345054", 8627, "2026-09-17", native=False)
        self.native("33345054", "exclusion", "2026-10-05", "protocol755", officer="Тестова УО SANDBOX")
        result = self.read("33345054")
        self.assertEqual(result["edr_status_current"], "Неактуально")
        self.assertEqual(result["visible_date"], "2026-10-05")
        self.assertEqual(result["last_verification_date"], "2026-09-17")
        self.assertEqual(result["last_verification_officer"], OFFICER)

    def test_suspended_freshness_from_verification(self):
        self.inclusion("1", status="suspended")
        self.check("1", day="2026-09-01")
        self.native("1", "suspension", "2026-10-05", "suspension")
        result = self.read("1")
        self.assertTrue(result["monitoring_eligible"])
        self.assertEqual(result["prozorro_status"], "Припинений")
        self.assertEqual(result["visible_actor"], "ЕСЗ")
        self.assertEqual(result["visible_date"], "2026-10-05")
        self.assertEqual(result["freshness"]["age_days"], 36)
        self.assertEqual(result["freshness"]["bucket"], "gt30")

    def test_resumption_current_date_not_freshness_date(self):
        self.inclusion("1")
        self.check("1", day="2026-09-01")
        self.native("1", "resumption", "2026-10-05", "resumption")
        result = self.read("1")
        self.assertEqual(result["visible_actor"], "ЕСЗ")
        self.assertEqual(result["visible_date"], "2026-10-05")
        self.assertEqual(result["last_verification_date"], "2026-09-01")

    def test_automatic_expiry_no_guessed_event(self):
        self.inclusion("1", expiry="2026-10-05T12:00:00+03:00")
        self.check("1", day="2026-09-01")
        result = self.read("1")
        self.assertEqual(result["prozorro_status"], "Неактивний")
        self.assertIsNone(result["current_event_date"])
        self.assertIn("missing_lifecycle_evidence", result["gaps"])
        self.native("1", "expiry", "2026-10-05", "expiry")
        result = self.read("1")
        self.assertEqual(result["visible_actor"], "ЕСЗ")
        self.assertEqual(result["visible_date"], "2026-10-05")

    def test_rejected_latest_application_preserves_check(self):
        self.inclusion("1")
        self.check("1", day="2026-09-01")
        self.application("1", stamp="2026-10-06T10:00:00+03:00", status="unsuccessful")
        result = self.read("1")
        self.assertEqual(result["logical_verification_count"], 1)
        self.assertEqual(result["last_verification_date"], "2026-09-01")
        self.assertEqual(result["last_application"]["id"], "s1")

    def test_partial_termination_active(self):
        self.inclusion("1", "old", "terminated")
        self.inclusion("1", "remaining")
        self.check("1")
        self.assertEqual(self.read("1")["prozorro_status"], "Активний")

    def test_never_admitted_date_blank_decision_actor(self):
        self.application("1", status="unsuccessful")
        result = self.read("1")
        self.assertEqual(result["prozorro_status"], "Ще не в реєстрі")
        self.assertEqual(result["edr_status_current"], "Неактуально")
        self.assertIsNone(result["visible_date"])
        self.assertEqual(result["visible_actor"], OFFICER)
        self.assertEqual(result["logical_verification_count"], 0)

    def test_never_admitted_canonical_fallback(self):
        self.application("1", status="unsuccessful", officer="")
        self.assertEqual(self.read("1")["visible_actor"], "Тестова УО SANDBOX")

    def test_pending_application_has_no_guessed_decision_actor(self):
        self.application("1", status="pending", officer="")
        result = self.read("1")
        self.assertIsNone(result["last_application"]["actor"])
        self.assertIsNone(result["visible_actor"])
        self.assertIsNone(result["last_application_decision"])

    def test_last_application_distinct_from_last_decision(self):
        self.application("1", "decided", status="unsuccessful")
        self.application("1", "pending", stamp="2026-10-06T10:00:00+03:00", status="pending", officer="")
        result = self.read("1")
        self.assertEqual(result["last_application"]["id"], "pending")
        self.assertEqual(result["last_application_decision"]["submission_id"], "decided")
        self.assertEqual(result["visible_actor"], OFFICER)
        self.assertIsNone(result["visible_date"])

    def test_literal_dash_preserved(self):
        self.inclusion("45054758")
        self.check()
        self.assertEqual(self.read("45054758")["factual_snapshot"]["short_name"], "—")

    def test_historical_gap_no_materialization(self):
        self.inclusion("1", status="suspended")
        self.check("1")
        recording.observe_gap(self.con, environment="sandbox", supplier_code="1",
            source_system="audit", source_object="contract", source_id="old",
            observed_at=NOW, payload={}, gaps=[dict(gap_type="suspension_date_unproven",
                gap_reason="No exact time", review_scope="history_only", remediation="provenance_review",
                known_event_date="", known_actor="", source={}, recommended_action="Review source")])
        before = self.con.total_changes
        result = self.read("1")
        self.assertIn("suspension_date_unproven", result["gaps"])
        self.assertEqual(result["provenance_gaps"][0]["known_event_date"], "")
        self.assertEqual(before, self.con.total_changes)
        self.assertIsNone(result["visible_date"])
        self.assertIsNone(result["current_event"])
        self.assertEqual(result["last_verification_date"], "2026-10-06")

    def test_archived_legacy_gap_remains_history_only(self):
        self.test_historical_gap_no_materialization()
        gap = self.con.execute("SELECT gap_id FROM supplier_evidence_gaps_v3").fetchone()[0]
        self.con.execute("INSERT INTO supplier_evidence_gap_resolutions_v3 VALUES (?,?,?,?,?)",
            (gap, "history_only", None, NOW, '{}'))
        result = self.read("1")
        self.assertEqual(result["provenance_gaps"][0]["review_scope"], "history_only")
        self.assertIn("suspension_date_unproven", result["gaps"])

    def test_conflicting_mirror_explicit_gap(self):
        self.inclusion("45054758")
        self.check(native=False)
        self.native("45054758", "edr_check", "2026-10-06", "8699", system="legacy_edr_ledger",
            snapshot={"edr_status": "Зареєстровано"})
        result = self.read("45054758")
        self.assertTrue(any(g.startswith("conflicting_source_event_identity:") for g in result["gaps"]))
        self.assertIsNone(result["current_event"])
        self.assertIsNone(result["last_verification_event"])

    def test_native_admission_does_not_duplicate_reconstruction(self):
        self.inclusion("1")
        self.application("1")
        self.native("1", "admission", "2026-09-18", "s1", system="application",
            stamp="2026-09-18T17:19:52+03:00", snapshot={"full_name": "Recorded name", "edr_status": "Зареєстровано"})
        self.assertEqual(self.read("1")["logical_verification_count"], 1)

    def test_same_day_distinct_checks_are_not_hash_deduplicated(self):
        self.inclusion("1")
        self.check("1", 1, "2026-10-06T10:00:00+03:00")
        self.check("1", 2, "2026-10-06T11:00:00+03:00")
        result = self.read("1")
        self.assertEqual(result["logical_verification_count"], 2)
        self.assertEqual(json.loads(result["current_event"]["source_event_id"])[1], "2")

    def test_readonly_sql_authorizer(self):
        self.inclusion("45054758")
        self.check()
        allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_PRAGMA}
        self.con.set_authorizer(lambda action, *_: sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY)
        self.read("45054758")

    def test_source_row_budget_fail_closed(self):
        self.inclusion("1")
        with patch.object(adapter, "MAX_SOURCE_ROWS", 0):
            with self.assertRaises(adapter.SourceBudgetExceeded):
                self.read("1")

    def test_source_byte_budget_fail_closed(self):
        self.application("1")
        with patch.object(adapter, "MAX_SOURCE_BYTES", 1):
            with self.assertRaises(adapter.SourceBudgetExceeded):
                self.read("1")

    def test_single_code_no_population_read(self):
        self.inclusion("45054758")
        self.check()
        self.con.executemany("INSERT INTO submissions VALUES (?,?,?,?,?)",
            [("other" + str(i), "999", NOW, "Other", None) for i in range(5000)])
        sql = []
        self.con.set_trace_callback(sql.append)
        tracemalloc.start()
        started = time.perf_counter()
        try:
            result = self.read("45054758")
            elapsed = time.perf_counter() - started
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertLess(elapsed, 2)
        self.assertLess(peak, 2 * 1024 * 1024)
        self.assertEqual(result["logical_verification_count"], 1)
        for query in sql:
            if query.lstrip().upper().startswith("SELECT"):
                self.assertIn("supplier_code", query)
                self.assertIn("45054758", query)
        self.assertNotIn("_edr_monitoring_rows", Path(adapter.__file__).read_text())
        print("PROJECTION_SINGLE_CODE_SYNTHETIC=" + json.dumps({
            "unrelated_suppliers_rows": 5000, "elapsed_ms": round(elapsed * 1000, 3),
            "python_peak_bytes": peak, "logical_verifications": result["logical_verification_count"]}))

    def test_api_semantic_fields_no_mutation(self):
        self.inclusion("1", status="suspended")
        self.check("1", day="2026-09-01")
        self.native("1", "suspension", "2026-10-05", "transition")
        result = self.read("1")
        fields = adapter.api_fields(result)["supplier_evidence_v3"]
        self.assertEqual(fields["current_event_date"], "2026-10-05")
        self.assertEqual(fields["last_verification_date"], "2026-09-01")
        fields["factual_snapshot"]["short_name"] = ""
        self.assertEqual(result["factual_snapshot"]["short_name"], "—")

    def test_read_gate_off_exact_legacy_parity_zero_sql(self):
        legacy = Mock(return_value={"unchanged": object()})
        with patch.dict(os.environ, {adapter.READ_FLAG: ""}), patch.object(adapter, "project_supplier", side_effect=AssertionError("unexpected v3 read")):
            sentinel = object()
            self.assertIs(adapter.read_or_legacy(sentinel, "45054758", as_of_at=NOW, legacy_reader=legacy), legacy.return_value)
            legacy.assert_called_once_with(sentinel, "45054758")

    def test_recording_flag_does_not_enable_read(self):
        with patch.dict(os.environ, {adapter.READ_FLAG: "", "PQM_SANDBOX_EVIDENCE_V3_SHADOW": "1"}):
            self.assertFalse(adapter.read_enabled())

    def test_read_gate_on_dispatch(self):
        self.inclusion("45054758")
        self.check()
        with patch.dict(os.environ, {adapter.READ_FLAG: "true"}):
            legacy = Mock(side_effect=AssertionError("legacy used"))
            self.assertEqual(adapter.read_or_legacy(self.con, "45054758", as_of_at=NOW, legacy_reader=legacy)["api_version"], adapter.API_VERSION)

    def test_prod_isolation_flag_on(self):
        for env in ({"PQM_SANDBOX": "0"}, {"RENDER_SERVICE_ID": "prod"}, {"RENDER_SERVICE_ID": ""}):
            with self.subTest(env=env), patch.dict(os.environ, {adapter.READ_FLAG: "true", **env}):
                self.assertFalse(adapter.read_enabled())
                with self.assertRaises(PermissionError):
                    self.read("45054758")

    def test_future_verification_not_current(self):
        self.inclusion("1")
        self.check("1", day="2026-10-08")
        result = self.read("1")
        self.assertIsNone(result["last_verification_date"])
        self.assertEqual(result["freshness"]["bucket"], "not_checked")
        self.assertTrue(any(g.startswith("future_evidence:") for g in result["gaps"]))

    def test_freshness_uses_kyiv_business_calendar(self):
        self.inclusion("45054758")
        self.check()
        result = adapter.project_supplier(self.con, "45054758", as_of_at="2026-10-06T22:30:00+00:00")
        self.assertEqual(result["freshness"]["age_days"], 1)

    def test_assessment_and_literal_identity_validation(self):
        for code, stamp in ((45054758, NOW), ("45054758", "2026-10-07"), ("4 OR 1=1", NOW)):
            with self.subTest(code=code), self.assertRaises(ValueError):
                adapter.project_supplier(self.con, code, as_of_at=stamp)


if __name__ == "__main__":
    unittest.main()
