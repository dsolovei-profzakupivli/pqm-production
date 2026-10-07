"""Synthetic parity runner safety; real lifecycle acceptance remains LIVE_PENDING."""
import inspect
import io
import json
import os
import sqlite3
import time
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
import tracemalloc
import unittest
from unittest.mock import patch

from tools import supplier_evidence_parity_v3 as runner
import test_supplier_evidence_projection_v3 as fixtures


class ParityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ProjectionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.con = self.fixture.con
        self.con.row_factory = sqlite3.Row
        self.flags = patch.dict(os.environ, {runner.adapter.READ_FLAG: "", "PQM_SANDBOX_EVIDENCE_V3_SHADOW": "1"})
        self.flags.start()
        self.addCleanup(self.flags.stop)

    def run_case(self, codes):
        if not self.con.execute("PRAGMA query_only").fetchone()[0]:
            self.con.execute("PRAGMA query_only=ON")
        return runner.run(self.con, codes, as_of_at=fixtures.NOW)

    def c2(self):
        self.fixture.inclusion("45054758")
        self.fixture.check()

    def legacy_schema(self):
        for name in ("edr_checked_at", "edr_officer", "synced_at"):
            self.con.execute("ALTER TABLE supplier_edr_profiles ADD COLUMN " + name + " TEXT")
        self.con.execute("ALTER TABLE application_fields ADD COLUMN protocol_decision TEXT")
        self.con.execute("ALTER TABLE application_fields ADD COLUMN protocol_date TEXT")
        self.con.execute("ALTER TABLE qualifications ADD COLUMN decision_date TEXT")

    def test_actual_targeted_legacy_reader_c2_parity(self):
        self.c2()
        self.fixture.application("45054758", "s1", "2023-03-08T15:49:05+02:00")
        self.legacy_schema()
        self.con.execute("UPDATE application_fields SET protocol_decision='admit',protocol_date='08.03.2023'")
        self.con.execute("UPDATE qualifications SET decision_date='2023-03-08'")
        self.con.execute("UPDATE registry_contracts SET qualification_id='qs1'")
        self.con.execute("INSERT INTO supplier_edr_profiles(supplier_code,edr_status) VALUES ('45054758','Припинено')")
        row = self.run_case(["45054758"])["rows"][0]
        self.assertEqual(row["legacy"]["last_verification_date"], "2026-10-06")
        self.assertEqual(row["legacy"]["verification_identity"]["id"], 8699)
        self.assertEqual(row["legacy"]["freshness"]["bucket"], "lt30")
        self.assertEqual(row["legacy"]["edr_status"], "Припинено")
        self.assertIn("TRUE_PARITY", row["classifications"])
        self.assertNotIn("UNEXPECTED_MISMATCH", row["classifications"])

    def test_empty_unknown_overlap_not_true_parity(self):
        row = self.run_case(["45088216"])["rows"][0]
        self.assertNotIn("TRUE_PARITY", row["classifications"])

    def test_known_missing_legacy_verification_is_expected_reconstruction(self):
        code = "2077003493"
        self.fixture.inclusion(code)
        self.fixture.application(code, officer="Тетяна ФЕДЧЕНКО")
        self.legacy_schema()
        self.con.execute("INSERT INTO supplier_edr_profiles(supplier_code,edr_status) VALUES (?,?)", (code, "Неактуально"))
        row = self.run_case([code])["rows"][0]
        self.assertIsNone(row["legacy"]["last_verification_date"])
        self.assertIn("EXPECTED_V3_CORRECTION", row["classifications"])
        self.assertIn("LEGACY_STALE", row["classifications"])
        self.assertNotIn("UNEXPECTED_MISMATCH", row["classifications"])

    def test_no_native_tables_created(self):
        self.con.close()
        self.fixture.con = self.con = sqlite3.connect(":memory:")
        fixtures.setup(self.con, v3=False)
        self.con.row_factory = sqlite3.Row
        self.con.execute("CREATE TABLE supplier_edr_profiles(supplier_code TEXT,edr_status TEXT)")
        self.fixture.inclusion("45054758")
        self.fixture.check(native=False)
        self.run_case(["45054758"])
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM sqlite_master WHERE name LIKE 'supplier_evidence_%'").fetchone()[0], 0)
        self.addCleanup(self.con.close)

    def test_entire_bounded_cohort_memory(self):
        for i, code in enumerate(runner.CODES):
            self.fixture.inclusion(code, "c" + str(i))
            self.fixture.application(code, "s" + str(i))
        tracemalloc.start()
        result = self.run_case(runner.CODES)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        self.assertEqual(result["unique_suppliers"], 33)
        self.assertLess(peak, 2 * 1024 * 1024)
        print("PARITY_MEMORY_BOUNDED_COHORT", json.dumps({"peak_python_bytes": peak, "timing_ms": result["timing_ms"]}))

    def test_frozen_cohort_limit_and_codes(self):
        self.assertEqual(len(runner.CODES), 33)
        self.assertLessEqual(len(runner.CODES), 37)
        self.assertEqual(runner.selected_codes(["45054758", "45054758"]), ("45054758",))
        for codes in ([], ["unknown"], [str(i) for i in range(38)]):
            with self.assertRaises(ValueError):
                runner.selected_codes(codes)

    def test_c2_single_logical_check_literal_dash(self):
        self.c2()
        p = self.run_case(["45054758"])["rows"][0]["v3"]
        self.assertEqual(p["logical_verification_count"], 1)
        self.assertEqual(p["last_verification_date"], "2026-10-06")
        self.assertEqual(p["factual_snapshot"]["short_name"], "—")
        self.assertEqual(p["freshness"]["bucket"], "lt30")
        self.assertEqual(p["current_event"], p["last_verification"])

    def test_repeated_parity_read_no_write_or_duplicate(self):
        self.c2()
        before = self.con.total_changes
        for _ in range(2):
            result = self.run_case(["45054758"])
            self.assertEqual(result["rows"][0]["v3"]["logical_verification_count"], 1)
        self.assertEqual(before, self.con.total_changes)

    def test_stored_stale_is_labelled_not_authoritative_ui(self):
        code = runner.COHORTS["stale_active"][0]
        self.fixture.inclusion(code)
        self.fixture.application(code)
        self.con.execute("INSERT INTO supplier_edr_profiles VALUES (?,?)", (code, "Неактуально"))
        row = self.run_case([code])["rows"][0]
        self.assertIn("EXPECTED_V3_CORRECTION", row["classifications"])
        self.assertIn("LEGACY_STALE", row["classifications"])
        self.assertIn("NOT_authoritative_UI", row["legacy"]["projection_source"])

    def test_twelve_and_manual_controls(self):
        for i, code in enumerate(runner.COHORTS["stale_active"]):
            date, officer = runner.MANUAL_CONTROLS.get(code, ("2026-09-18", fixtures.OFFICER))
            self.fixture.inclusion(code, "c" + str(i))
            self.fixture.application(code, "s" + str(i), date + "T17:00:00+03:00", officer)
            self.con.execute("INSERT INTO supplier_edr_profiles VALUES (?,?)", (code, "Неактуально"))
        tracemalloc.start()
        result = self.run_case(runner.COHORTS["stale_active"])
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        self.assertLess(peak, 2 * 1024 * 1024)
        print("PARITY_MEMORY_TWELVE", json.dumps({"peak_python_bytes": peak, "timing_ms": result["timing_ms"]}))
        self.assertEqual(result["timing_ms"]["stale_controls_measured"], 12)
        for row in result["rows"]:
            self.assertEqual(row["v3"]["edr_status"], "Зареєстровано")
            self.assertTrue(row.get("manual_control_pass", True))

    def test_three_same_day_events_chronology_not_id_order(self):
        code = "2077003493"
        self.fixture.inclusion(code)
        for ident, clock in (("e3edb5e958144b61b9d3320d23d2a120", "17:04:21.589075"),
            ("c1939b79afce43cfbef0eadf3a0566ff", "15:59:34.798180"),
            ("d27925ea7ed24af7bb4c1ec5deff4eb0", "17:19:52.579134")):
            self.fixture.application(code, ident, "2026-09-18T" + clock + "+03:00", "Тетяна ФЕДЧЕНКО")
        p = self.run_case([code])["rows"][0]["v3"]
        self.assertEqual(p["logical_verification_count"], 3)
        self.assertIn("d27925ea7ed24af7bb4c1ec5deff4eb0", p["current_event"]["source_event_id"])

    def test_google_frozen_context_does_not_invent_verification(self):
        row = self.run_case(["45088216"])["rows"][0]
        self.assertIn("GOOGLE_ONLY_NOT_IMPORTED", row["classifications"])
        self.assertIsNone(row["v3"]["last_verification"])
        self.assertEqual(row["frozen_audit_context"][0]["verification_date"], "2026-10-05")

    def test_c2_newer_than_google_pending(self):
        self.c2()
        row = self.run_case(["45054758"])["rows"][0]
        self.assertTrue(row["frozen_audit_context"][0]["superseded_by_current_verification"])

    def test_333_policy_without_evidence_remains_gap(self):
        self.fixture.inclusion("33345054", status="terminated")
        self.fixture.check("33345054", 8627, "2026-09-17", native=False)
        self.con.execute("INSERT INTO supplier_edr_profiles VALUES (?,?)", ("33345054", "Неактуально"))
        row = self.run_case(["33345054"])["rows"][0]
        self.assertIsNone(row["v3"]["current_event_date"])
        self.assertEqual(row["v3"]["last_verification_date"], "2026-09-17")
        self.assertIn("MISSING_PROVENANCE", row["classifications"])
        self.assertNotIn("TRUE_PARITY", row["classifications"])
        self.assertIn("missing_lifecycle_evidence", row["unresolved_evidence_gaps"])
        self.assertIsNone(row["v3"]["current_event_actor"])
        self.assertIn("NOT_materialized_event", row["frozen_audit_context"][0]["source"])
        p = row["v3"]
        # An archived gap with the same name does not prove the missing current event.
        p["provenance_gaps"] = [{"gap_type": "missing_lifecycle_evidence", "review_scope": "history_only"}]
        result = runner.compare("33345054", row["legacy"], p)
        self.assertIn("MISSING_PROVENANCE", result["classifications"])
        self.assertNotIn("TRUE_PARITY", result["classifications"])
        self.assertFalse(result["current_event_evidence_known"])

    def test_history_only_gap_keeps_independent_known_parity(self):
        self.c2()
        p = runner.compact_projection(runner.adapter.project_supplier(self.con, "45054758", as_of_at=fixtures.NOW))
        p["gaps"] = ["termination_date_unproven"]
        p["provenance_gaps"] = [{"gap_type": "termination_date_unproven", "review_scope": "history_only"}]
        old = {k: p[k] for k in ("edr_status", "prozorro_status", "monitoring_eligible", "last_verification_date", "last_verification_officer", "last_application_date", "freshness")}
        result = runner.compare("45054758", old, p)
        self.assertIn("TRUE_PARITY", result["classifications"])
        self.assertIn("MISSING_PROVENANCE", result["classifications"])
        self.assertNotIn("UNEXPECTED_MISMATCH", result["classifications"])
        self.assertEqual(result["unresolved_evidence_gaps"], [])
        self.assertIn("edr_status", result["known_equal_fields"])

    def test_same_gap_type_active_scope_is_not_hidden_by_history_only(self):
        self.c2()
        p = runner.compact_projection(runner.adapter.project_supplier(self.con, "45054758", as_of_at=fixtures.NOW))
        p["gaps"] = ["termination_date_unproven"]
        p["provenance_gaps"] = [{"gap_type": "termination_date_unproven", "review_scope": scope} for scope in ("history_only", "manual_review")]
        result = runner.compare("45054758", {"edr_status": p["edr_status"]}, p)
        self.assertNotIn("TRUE_PARITY", result["classifications"])
        self.assertEqual(result["unresolved_evidence_gaps"], ["termination_date_unproven"])

    def test_333_when_explicit_lifecycle_exists(self):
        self.fixture.inclusion("33345054", status="terminated")
        self.fixture.check("33345054", 8627, "2026-09-17", native=False)
        self.fixture.native("33345054", "exclusion", "2026-10-05", "755", officer="Тестова УО SANDBOX")
        p = self.run_case(["33345054"])["rows"][0]["v3"]
        self.assertEqual(p["current_event_date"], "2026-10-05")
        self.assertEqual(p["last_verification_date"], "2026-09-17")

    def test_never_admitted_blank_visible_i_no_check(self):
        for i, code in enumerate(runner.COHORTS["never_admitted"]):
            self.fixture.application(code, "s" + str(i), officer="" if i == 0 else fixtures.OFFICER, status="unsuccessful")
        result = self.run_case(runner.COHORTS["never_admitted"])
        for row in result["rows"]:
            p = row["v3"]
            self.assertEqual(p["prozorro_status"], "Ще не в реєстрі")
            self.assertEqual(p["edr_status"], "Неактуально")
            self.assertIsNone(p["visible_date"])
            self.assertIsNotNone(p["last_application_date"])
            self.assertEqual(p["logical_verification_count"], 0)
        self.assertEqual(result["rows"][0]["v3"]["visible_actor"], "Тестова УО SANDBOX")

    def test_suspended_no_fabricated_current_date(self):
        self.fixture.inclusion("44368854", status="suspended")
        self.fixture.check("44368854", 1, "2026-09-11", native=False)
        p = self.run_case(["44368854"])["rows"][0]["v3"]
        self.assertTrue(p["monitoring_eligible"])
        self.assertIsNone(p["current_event_date"])
        self.assertIn("suspension_date_unproven", p["gaps"])
        self.assertEqual(p["freshness"]["age_days"], 26)

    def test_partial_termination_active_with_frozen_history_gap(self):
        code = runner.COHORTS["multi_inclusion"][0]
        self.fixture.inclusion(code, "active")
        self.fixture.inclusion(code, "terminated", status="terminated")
        self.fixture.application(code)
        row = self.run_case([code])["rows"][0]
        self.assertEqual(row["v3"]["prozorro_status"], "Активний")
        self.assertEqual(row["frozen_audit_context"][0]["gap"], "termination_date_unproven")

    def test_google_or_gap_does_not_hide_unexpected_mismatch(self):
        self.c2()
        self.con.execute("INSERT INTO supplier_edr_profiles VALUES (?,?)", ("45054758", "Зареєстровано"))
        row = self.run_case(["45054758"])["rows"][0]
        self.assertIn("UNEXPECTED_MISMATCH", row["classifications"])
        self.assertIn("GOOGLE_ONLY_NOT_IMPORTED", row["classifications"])

    def test_reference_budgets_fail_before_consumer(self):
        self.c2()
        with patch.object(runner.adapter, "MAX_SOURCE_ROWS", 0), patch.object(runner.adapter, "project_supplier") as consumer:
            with self.assertRaisesRegex(ValueError, "budget"):
                self.run_case(["45054758"])
            consumer.assert_not_called()

    def test_bytes_budget_fail_before_consumer(self):
        self.c2()
        with patch.object(runner.adapter, "MAX_SOURCE_BYTES", 8), patch.object(runner.adapter, "project_supplier") as consumer:
            with self.assertRaisesRegex(ValueError, "budget"):
                self.run_case(["45054758"])
            consumer.assert_not_called()

    def test_native_snapshot_budget_checked_before_materialization(self):
        self.fixture.native("45054758", "edr_check", "2026-10-06", "8699", system="legacy_edr_ledger",
            snapshot={"edr_status": "Припинено", "full_name": "x" * (2 * 1024 * 1024)})
        with patch.object(runner.adapter, "project_supplier") as consumer:
            with self.assertRaisesRegex(ValueError, "supplier_evidence_events_v3"):
                self.run_case(["45054758"])
            consumer.assert_not_called()

    def test_output_budget_fail_closed(self):
        self.c2()
        with patch.object(runner, "MAX_OUTPUT_BYTES", 10):
            with self.assertRaisesRegex(ValueError, "output budget"):
                self.run_case(["45054758"])

    def test_no_heavy_legacy_functions_called(self):
        self.c2()
        with patch.object(runner.legacy, "canonical_prozorro_statuses", side_effect=AssertionError("population")), \
             patch.object(runner.legacy, "canonical_supplier_edr_states", side_effect=AssertionError("population")), \
             patch.object(runner.legacy, "active_qualification_dates", side_effect=AssertionError("population")):
            self.run_case(["45054758"])

    def test_read_gate_off_recording_on_isolation(self):
        self.c2()
        before = self.con.total_changes
        self.run_case(["45054758"])
        self.assertEqual(before, self.con.total_changes)
        self.assertFalse(runner.adapter.read_enabled())
        self.assertEqual(os.getenv("PQM_SANDBOX_EVIDENCE_V3_SHADOW"), "1")

    def test_read_gate_on_stop(self):
        with patch.dict(os.environ, {runner.adapter.READ_FLAG: "1"}):
            with self.assertRaisesRegex(ValueError, "OFF"):
                self.run_case(["45054758"])

    def test_prod_guard(self):
        with patch.dict(os.environ, {"RENDER_SERVICE_ID": "prod"}):
            with self.assertRaisesRegex(ValueError, "SANDBOX"):
                self.run_case(["45054758"])

    def test_sql_read_authorizer(self):
        self.c2()
        self.con.execute("PRAGMA query_only=ON")
        allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}
        self.con.set_authorizer(lambda action, a, b, *rest: sqlite3.SQLITE_OK if action in allowed or
            action == sqlite3.SQLITE_PRAGMA and (a == "table_info" or a == "query_only" and b is None) else sqlite3.SQLITE_DENY)
        self.run_case(["45054758"])
        self.con.set_authorizer(None)

    def test_population_not_materialized_memory(self):
        self.c2()
        self.con.executemany("INSERT INTO supplier_edr_profiles VALUES (?,?)", (("other" + str(i), "Неактуально") for i in range(10000)))
        queries = []
        self.con.set_trace_callback(queries.append)
        tracemalloc.start()
        start = time.perf_counter()
        result = self.run_case(["45054758"])
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        self.con.set_trace_callback(None)
        self.assertLess(peak, 2 * 1024 * 1024)
        self.assertLess(time.perf_counter() - start, 5)
        self.assertEqual(result["unique_suppliers"], 1)
        self.assertTrue(all("WHERE" in q.upper() and "45054758" in q for q in queries if q.lstrip().upper().startswith("SELECT") and "sqlite_master" not in q))
        print("PARITY_MEMORY_SINGLE_SUPPLIER", json.dumps({"peak_python_bytes": peak, "elapsed_ms": (time.perf_counter()-start)*1000}))

    def test_no_stage2b_or_runtime_import(self):
        source = inspect.getsource(runner)
        self.assertNotIn("import server", source)
        self.assertNotIn("import supplier_evidence_shadow_v3_stage2b", source)
        self.assertNotIn("_edr_monitoring_rows(", source)

    def test_cli_readonly_file_stdout_and_handle_closed(self):
        self.c2()
        self.con.commit()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fixture.sqlite3"
            disk = sqlite3.connect(path)
            self.con.backup(disk)
            disk.close()
            before = path.read_bytes()
            output = io.StringIO()
            with patch.object(runner.sys, "argv", ["parity", "--db", str(path), "--as-of-at", fixtures.NOW,
                "--codes", "45054758"]), redirect_stdout(output):
                runner.main()
            result = json.loads(output.getvalue())
            self.assertEqual(result["DB_WRITES"], 0)
            self.assertEqual(before, path.read_bytes())
            self.assertEqual(result["unique_suppliers"], 1)

    def test_zoned_assessment_required(self):
        self.con.execute("PRAGMA query_only=ON")
        with self.assertRaisesRegex(ValueError, "zoned"):
            runner.run(self.con, ["45054758"], as_of_at="2026-10-07T12:00:00")

    def test_non_readonly_connection_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "query_only"):
            runner.run(self.con, ["45054758"], as_of_at=fixtures.NOW)


if __name__ == "__main__":
    unittest.main()
