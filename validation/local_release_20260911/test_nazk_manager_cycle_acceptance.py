import json
import tempfile
import unittest
from pathlib import Path

import nazk_workflow
import operational_tasks
import server


class NazkManagerCycleAcceptanceTests(unittest.TestCase):
    CODE = "12345678"
    MANAGER_A = "ІВАНЕНКО ОЛЕКСАНДР ПЕТРОВИЧ"
    MANAGER_B = "ПЕТРЕНКО БОРИС ІВАНОВИЧ"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.old_db = server.DB_PATH
        server.DB_PATH = Path(self.temp.name) / "nazk-cycle.sqlite3"
        server.init_db()
        server.init_reference_tables(server.DB_PATH)
        with server.db() as con:
            con.execute(
                """INSERT INTO supplier_registry_summary
                   (supplier_code,supplier_name,active_count,refreshed_at)
                   VALUES (?,?,1,?)""",
                (self.CODE, "ТЕСТОВИЙ ПОСТАЧАЛЬНИК", server.now_iso()),
            )

    def tearDown(self):
        server.DB_PATH = self.old_db
        self.temp.cleanup()

    def add_manager(self, con, name, *, current):
        return con.execute(
            """INSERT INTO supplier_managers
               (supplier_code,manager_name,normalized_name,is_current,source,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?)""",
            (self.CODE, name, nazk_workflow.normalize_name(name), int(current), "test",
             server.now_iso(), server.now_iso()),
        ).lastrowid

    def add_fact(self, con, source_id, person, fact_date):
        con.execute(
            """INSERT INTO nazk_registry
               (source_id,full_name,court_case_number,sentence_date,punishment_start,raw_json)
               VALUES (?,?,?,?,?,?)""",
            (source_id, person, source_id, fact_date, fact_date,
             json.dumps({"decision_date": fact_date, "effective_date": fact_date})),
        )

    def add_factual(self, con, manager_id, person, source_id, *, result="refuted"):
        check_id = con.execute(
            """INSERT INTO supplier_nazk_checks
               (supplier_code,manager_id,manager_name,workflow_status,result,started_at,completed_at,
                evidence_date,covered_nazk_date,is_legacy,created_at,created_by,updated_at,updated_by)
               VALUES (?,?,?,'completed',?,'2026-08-01','2026-08-01','2026-08-01',
                       '2026-08-01',0,?,'УО',?,'УО')""",
            (self.CODE, manager_id, person, result, server.now_iso(), server.now_iso()),
        ).lastrowid
        con.execute(
            """INSERT INTO supplier_nazk_check_matches
               (check_id,nazk_source_id,match_status,created_at)
               VALUES (?,?,'candidate',?)""",
            (check_id, source_id, server.now_iso()),
        )
        return check_id

    def add_historical_qualification(self, con, date, manager_name=None):
        framework_id = f"framework-{date}"
        submission_id = f"submission-{date}"
        qualification_id = f"qualification-{date}"
        con.execute(
            """INSERT INTO frameworks(id,pretty_id,status,raw_json,synced_at)
               VALUES (?,?, 'complete', ?, ?)""",
            (framework_id, framework_id,
             json.dumps({"qualificationPeriod": {"endDate": "2026-07-31T00:00:00"}}),
             server.now_iso()),
        )
        con.execute(
            """INSERT INTO submissions
               (id,framework_id,supplier_code,supplier_name,qualification_id,date_published,
                documents_json,raw_json,synced_at)
               VALUES (?,?,?,?,?,?,'[]','{}',?)""",
            (submission_id, framework_id, self.CODE, "ТЕСТОВИЙ ПОСТАЧАЛЬНИК",
             qualification_id, date, server.now_iso()),
        )
        con.execute(
            """INSERT INTO qualifications
               (id,framework_id,submission_id,status,decision_date,documents_json,raw_json,synced_at)
               VALUES (?,?,?,'active',?,'[]','{}',?)""",
            (qualification_id, framework_id, submission_id, date, server.now_iso()),
        )
        if manager_name is not None:
            con.execute(
                "INSERT INTO application_fields(submission_id,manager_name) VALUES (?,?)",
                (submission_id, manager_name),
            )

    def apply_and_materialize(self, con):
        state = nazk_workflow.reconcile_supplier_nazk(con, self.CODE, apply=True)
        operational_tasks.materialize_nazk_tasks(
            con, "acceptance fixture", supplier_codes=[self.CODE],
            active_applications={self.CODE: [{"id": "current-active-submission"}]},
            supplier_names={self.CODE: "ТЕСТОВИЙ ПОСТАЧАЛЬНИК"},
        )
        active_tasks = con.execute(
            """SELECT COUNT(*) FROM operational_tasks
               WHERE supplier_code=? AND task_type='nazk_check'
                 AND status NOT IN ('completed','cancelled')""",
            (self.CODE,),
        ).fetchone()[0]
        return state, active_tasks

    def test_case_a_new_manager_old_registry_fact_requires_new_cycle(self):
        with server.db() as con:
            manager_a = self.add_manager(con, self.MANAGER_A, current=True)
            self.add_fact(con, "fact-a", self.MANAGER_A, "2026-04-01")
            self.add_factual(con, manager_a, self.MANAGER_A, "fact-a")
            self.add_historical_qualification(con, "2026-07-01", self.MANAGER_A)
            changed = server.sync_current_supplier_manager(
                con, self.CODE, self.MANAGER_B, source="ЄДР", observed_at="2026-09-01T00:00:00+00:00")
            self.add_fact(con, "fact-b", self.MANAGER_B, "2026-05-01")
            state, active_tasks = self.apply_and_materialize(con)
        self.assertTrue(changed["changed"])
        self.assertTrue(state["created"])
        self.assertEqual(active_tasks, 1)

    def test_case_b_same_manager_same_factual_fact_does_not_repeat(self):
        with server.db() as con:
            manager_id = self.add_manager(con, self.MANAGER_A, current=True)
            self.add_fact(con, "fact-a", self.MANAGER_A, "2026-05-01")
            factual_id = self.add_factual(con, manager_id, self.MANAGER_A, "fact-a")
            state = nazk_workflow.reconcile_supplier_nazk(con, self.CODE, apply=True)
            check_count = con.execute("SELECT COUNT(*) FROM supplier_nazk_checks").fetchone()[0]
        self.assertEqual(state["check_id"], factual_id)
        self.assertIsNone(state["action"])
        self.assertEqual(check_count, 1)

    def test_case_c_same_manager_new_registry_source_requires_new_cycle(self):
        with server.db() as con:
            manager_id = self.add_manager(con, self.MANAGER_A, current=True)
            self.add_fact(con, "fact-old", self.MANAGER_A, "2026-05-01")
            self.add_factual(con, manager_id, self.MANAGER_A, "fact-old")
            self.add_fact(con, "fact-new", self.MANAGER_A, "2026-09-01")
            state, active_tasks = self.apply_and_materialize(con)
            linked = {row[0] for row in con.execute(
                "SELECT nazk_source_id FROM supplier_nazk_check_matches WHERE check_id=?", (state["check_id"],))}
        self.assertTrue(state["created"])
        self.assertEqual(linked, {"fact-old", "fact-new"})
        self.assertEqual(active_tasks, 1)

    def test_case_d_other_manager_qualification_never_covers_current_person(self):
        with server.db() as con:
            self.add_manager(con, self.MANAGER_A, current=False)
            self.add_manager(con, self.MANAGER_B, current=True)
            self.add_historical_qualification(con, "2026-07-01", self.MANAGER_A)
            self.add_fact(con, "fact-b", self.MANAGER_B, "2026-05-01")
            state, active_tasks = self.apply_and_materialize(con)
        self.assertTrue(state["created"])
        self.assertEqual(active_tasks, 1)

    def test_case_e_unknown_historical_manager_does_not_auto_close(self):
        with server.db() as con:
            self.add_manager(con, self.MANAGER_B, current=True)
            self.add_historical_qualification(con, "2026-07-01", manager_name=None)
            self.add_fact(con, "fact-b", self.MANAGER_B, "2026-05-01")
            state, active_tasks = self.apply_and_materialize(con)
        self.assertEqual(state["state"], "needs_review")
        self.assertTrue(state["created"])
        self.assertEqual(active_tasks, 1)

    def test_case_f_nonfactual_old_manager_result_does_not_block_new_manager(self):
        with server.db() as con:
            old_id = self.add_manager(con, self.MANAGER_A, current=False)
            self.add_manager(con, self.MANAGER_B, current=True)
            self.add_fact(con, "fact-a", self.MANAGER_A, "2026-04-01")
            self.add_fact(con, "fact-b", self.MANAGER_B, "2026-05-01")
            old_check = con.execute(
                """INSERT INTO supplier_nazk_checks
                   (supplier_code,manager_id,manager_name,workflow_status,result,started_at,is_legacy,
                    created_at,created_by,updated_at,updated_by)
                   VALUES (?,?,?,'not_current',NULL,'2026-08-01',0,?,'УО',?,'УО')""",
                (self.CODE, old_id, self.MANAGER_A, server.now_iso(), server.now_iso()),
            ).lastrowid
            con.execute(
                """INSERT INTO supplier_nazk_check_matches
                   (check_id,nazk_source_id,match_status,created_at)
                   VALUES (?,?,'candidate',?)""", (old_check, "fact-a", server.now_iso()))
            state, active_tasks = self.apply_and_materialize(con)
        self.assertTrue(state["created"])
        self.assertEqual(active_tasks, 1)

    def test_case_g_format_only_manager_change_keeps_same_covered_identity(self):
        canonical = "ІВАНЕНКО-ПЕТРО ОЛЕКСАНДРОВИЧ"
        formatted = "  іваненко петро   олександрович  "
        with server.db() as con:
            manager_id = self.add_manager(con, canonical, current=True)
            self.add_fact(con, "fact-a", canonical, "2026-05-01")
            factual_id = self.add_factual(con, manager_id, canonical, "fact-a")
            changed = server.sync_current_supplier_manager(
                con, self.CODE, formatted, source="ЄДР", observed_at="2026-09-01T00:00:00+00:00")
            state = nazk_workflow.reconcile_supplier_nazk(con, self.CODE, apply=True)
            current_id = con.execute(
                "SELECT id FROM supplier_managers WHERE supplier_code=? AND is_current=1", (self.CODE,)
            ).fetchone()[0]
            check_count = con.execute("SELECT COUNT(*) FROM supplier_nazk_checks").fetchone()[0]
        self.assertFalse(changed["changed"])
        self.assertEqual(current_id, manager_id)
        self.assertEqual(state["check_id"], factual_id)
        self.assertEqual(check_count, 1)


if __name__ == "__main__":
    unittest.main()
