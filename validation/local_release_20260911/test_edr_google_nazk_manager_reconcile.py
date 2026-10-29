import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import edr_sync_v2
import nazk_workflow
import operational_tasks
import server
try:
    from test_edr_sync_v2 import row, snapshot
except ModuleNotFoundError:
    from validation.local_release_20260911.test_edr_sync_v2 import row, snapshot

CODE = "38261938"
MANAGER_OLD = "ДОВБЕНКО ВОЛОДИМИР ВІТАЛІЙОВИЧ"
MANAGER_NEW = "ПАРФЕНЮК СЕРГІЙ СЕРГІЙОВИЧ"


class EdrGoogleNazkManagerReconcileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.old_db = server.DB_PATH
        server.DB_PATH = Path(self.temp.name) / "google-nazk.sqlite3"
        server.init_db()
        server.init_reference_tables(server.DB_PATH)
        with server.db() as con:
            con.execute("""INSERT INTO supplier_registry_summary
              (supplier_code,supplier_name,active_count,refreshed_at) VALUES (?,?,1,?)""",
              (CODE, "ТОВ ВП УКРКАБЕЛЬ", server.now_iso()))
            con.execute("""INSERT INTO frameworks
              (id,pretty_id,status,raw_json,synced_at) VALUES
              ('fw-38261938','UA-F-E2E-38261938','active',?,?)""",
              (json.dumps({"qualificationPeriod": {"endDate": "2099-12-31T00:00:00Z"}}), server.now_iso()))
            con.execute("""INSERT INTO submissions
              (id,framework_id,supplier_name,supplier_code,date_published,status,qualification_id,raw_json,synced_at)
              VALUES ('sub-38261938','fw-38261938','ТОВ ВП УКРКАБЕЛЬ',?,'2026-01-01','active','q-38261938','{}',?)""",
              (CODE, server.now_iso()))
            con.execute("""INSERT INTO qualifications
              (id,framework_id,submission_id,status,decision_date,raw_json,synced_at)
              VALUES ('q-38261938','fw-38261938','sub-38261938','active','2026-01-02','{}',?)""",
              (server.now_iso(),))
            con.execute("""INSERT INTO registry_contracts
              (id,framework_id,qualification_id,supplier_code,status,raw_json,synced_at)
              VALUES ('rc-38261938','fw-38261938','q-38261938',?,'active','{}',?)""",
              (CODE, server.now_iso()))
            con.execute("""INSERT INTO supplier_edr_profiles
              (supplier_code,manager_name,edr_status,edr_checked_at,edr_officer,synced_at)
              VALUES (?,?, 'Зареєстровано','2026-10-22','УО тест','2026-10-22')""",
              (CODE, MANAGER_OLD))
            server.sync_current_supplier_manager(con, CODE, MANAGER_OLD, "ЄДР", "2026-10-22")
            con.execute("""INSERT INTO nazk_registry
              (source_id,full_name,offense_name,court_case_number,sentence_date,punishment_start,decision_url,raw_json)
              VALUES ('nazk-old-manager',?,'synthetic offense','case-1','2025-01-01','2025-02-01','https://example.test/old','{}')""",
              (MANAGER_OLD,))
            state = nazk_workflow.reconcile_active_supplier_nazk(
                con, apply=True, supplier_codes=[CODE])
            self.assertEqual(state["potential_needs_review"], 1)
            created = operational_tasks.materialize_nazk_tasks(con, "test", supplier_codes=[CODE])
            self.assertEqual(created["created"], 1)
            self.old_check_id = state["items"][0]["check_id"]
            self.old_task = con.execute("""SELECT id,task_key FROM operational_tasks
              WHERE task_type='nazk_check' AND supplier_code=?""", (CODE,)).fetchone()
            self.assertIsNotNone(self.old_task)

    def tearDown(self):
        server.DB_PATH = self.old_db
        self.temp.cleanup()

    def _apply_manager_change(self, *, new_manager_has_match, active_qualification=True):
        with server.db() as con:
            if new_manager_has_match:
                con.execute("""INSERT INTO nazk_registry
                  (source_id,full_name,offense_name,court_case_number,sentence_date,punishment_start,decision_url,raw_json)
                  VALUES ('nazk-new-manager',?,'synthetic offense','case-2','2025-03-01','2025-04-01','https://example.test/new','{}')""",
                  (MANAGER_NEW,))
            if not active_qualification:
                con.execute("UPDATE registry_contracts SET status='terminated' WHERE id='rc-38261938'")
            values = row(code=CODE, checked="23.10.2026", officer="УО тест", manager=MANAGER_NEW)
            source = snapshot(values)
            before_network = con.total_changes
            with patch("server.urllib.request.urlopen", side_effect=AssertionError("unexpected external request")), \
                 patch.object(server, "refresh_nazk", side_effect=AssertionError("unexpected NAZK refresh")):
                result = edr_sync_v2.apply(
                    con, source, source["source_fingerprint"], confirmed=True,
                    actor="synthetic regression", synced_at="2026-10-24T10:00:00+03:00",
                    sync_manager=server.sync_current_supplier_manager,
                    enrich_manager=server.enrich_current_supplier_manager,
                    establish_manager=server.establish_current_supplier_manager,
                    reestablish_manager=server.reestablish_current_supplier_manager,
                    refresh_manager_controls=server.refresh_current_submission_nazk_controls,
                    reconcile_manager_nazk=server.reconcile_supplier_nazk_after_edr_manager_change)
            self.assertGreater(con.total_changes, before_network)
            old_task = con.execute("SELECT status,resolution_code FROM operational_tasks WHERE id=?",
                                   (self.old_task["id"],)).fetchone()
            old_match_count = con.execute("SELECT COUNT(*) FROM supplier_nazk_check_matches WHERE check_id=?",
                                          (self.old_check_id,)).fetchone()[0]
            all_tasks = con.execute("""SELECT id,task_key,status,resolution_code,
                 CAST(json_extract(source_context,'$.nazk_check_id') AS INTEGER) check_id
                 FROM operational_tasks WHERE task_type='nazk_check' AND supplier_code=? ORDER BY id""",
                 (CODE,)).fetchall()
            active_tasks = [task for task in all_tasks if task["status"] not in {"completed", "cancelled"}]
            return result, old_task, old_match_count, all_tasks, active_tasks

    def test_case_38261938_changed_manager_without_new_nazk_match_closes_old_task_and_keeps_history(self):
        result, old_task, old_match_count, tasks, active = self._apply_manager_change(
            new_manager_has_match=False)
        self.assertEqual(result["nazk_manager_reconciliations"], 1)
        self.assertEqual(tuple(old_task), ("cancelled", "manager_changed"))
        self.assertEqual(old_match_count, 1)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(active, [])

    def test_case_38261938_new_manager_match_and_active_qualification_create_one_new_cycle(self):
        result, old_task, old_match_count, tasks, active = self._apply_manager_change(
            new_manager_has_match=True)
        self.assertEqual(tuple(old_task), ("cancelled", "manager_changed"))
        self.assertEqual(old_match_count, 1)
        self.assertEqual(len(tasks), 2)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["check_id"], 2)
        self.assertIn(active[0]["check_id"], {task["check_id"] for task in tasks})
        self.assertTrue(any(task["task_key"].endswith(":nazk-new-manager")
                            and task["check_id"] == active[0]["check_id"] for task in tasks))
        with server.db() as con:
            repeated = server.reconcile_supplier_nazk_after_edr_manager_change(con, CODE)
            operational_tasks.materialize_nazk_tasks(con, "repeat", supplier_codes=[CODE])
            self.assertEqual(repeated["tasks_created"], 0)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM operational_tasks WHERE task_type='nazk_check' AND supplier_code=?", (CODE,)).fetchone()[0], 2)
            self.assertEqual(con.execute("SELECT COUNT(DISTINCT task_key) FROM operational_tasks WHERE task_type='nazk_check' AND supplier_code=?", (CODE,)).fetchone()[0], 2)

    def test_case_38261938_no_effective_active_qualification_means_no_new_task(self):
        result, old_task, old_match_count, tasks, active = self._apply_manager_change(
            new_manager_has_match=True, active_qualification=False)
        self.assertEqual(tuple(old_task), ("cancelled", "manager_changed"))
        self.assertEqual(old_match_count, 1)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(active, [])

    def test_current_manager_task_is_cancelled_when_effective_qualifications_disappear(self):
        with server.db() as con:
            con.execute("UPDATE registry_contracts SET status='terminated' WHERE id='rc-38261938'")
            result = server.reconcile_supplier_nazk_after_edr_manager_change(con, CODE)
            task = con.execute("SELECT status,resolution_code FROM operational_tasks WHERE id=?",
                               (self.old_task["id"],)).fetchone()
            events = con.execute("SELECT event_type,metadata FROM operational_task_events WHERE task_id=?",
                                 (self.old_task["id"],)).fetchall()
            match_count = con.execute("SELECT COUNT(*) FROM supplier_nazk_check_matches WHERE check_id=?",
                                      (self.old_check_id,)).fetchone()[0]
        self.assertEqual(result["skipped"], "no_effective_active_qualifications")
        self.assertEqual(result["cancelled_inactive_supplier"], 1)
        self.assertEqual(tuple(task), ("cancelled", "no_active_qualifications"))
        self.assertIn("cancelled_no_active_qualifications", [event["event_type"] for event in events])
        self.assertEqual(match_count, 1)


if __name__ == "__main__":
    unittest.main()
