import json
import sqlite3
import unittest
from datetime import date, timedelta
from pathlib import Path

from uo_work_queue import default_protocol_period, get_current_qualification_summary, get_uo_work_queue


class UoWorkQueueTests(unittest.TestCase):
    def test_default_protocol_period_on_monday_is_friday_through_sunday(self):
        self.assertEqual(default_protocol_period(date(2026, 8, 31)), ("2026-08-28", "2026-08-30"))

    def test_default_protocol_period_on_weekday_is_previous_day(self):
        self.assertEqual(default_protocol_period(date(2026, 8, 26)), ("2026-08-25", "2026-08-25"))

    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        self.con.create_function("CASEFOLD", 1, lambda value: str(value or "").casefold(), deterministic=True)
        self.con.create_function(
            "NORMALIZE_NAME", 1,
            lambda value: " ".join(str(value or "").casefold().replace("-", " ").split()),
            deterministic=True,
        )
        self.con.create_function(
            "DIGITS", 1, lambda value: "".join(ch for ch in str(value or "") if ch.isdigit()),
            deterministic=True,
        )
        self.con.executescript("""
          CREATE TABLE frameworks(id TEXT PRIMARY KEY,pretty_id TEXT,dk_code TEXT,status TEXT,raw_json TEXT);
          CREATE TABLE framework_officers(framework_id TEXT,officer TEXT,category TEXT);
          CREATE TABLE submissions(id TEXT PRIMARY KEY,framework_id TEXT,supplier_name TEXT,supplier_code TEXT,date_published TEXT,qualification_id TEXT);
          CREATE TABLE qualifications(id TEXT PRIMARY KEY,status TEXT);
          CREATE TABLE registry_contracts(qualification_id TEXT,status TEXT);
          CREATE TABLE application_fields(submission_id TEXT PRIMARY KEY,protocol_officer TEXT,protocol_date TEXT DEFAULT '',protocol_decision TEXT DEFAULT '',marketplace_decision TEXT DEFAULT '');
          CREATE TABLE supplier_managers(id INTEGER PRIMARY KEY,manager_tax_id TEXT);
          CREATE TABLE submission_nazk_controls(id INTEGER PRIMARY KEY,submission_id TEXT,supplier_code TEXT,manager_id INTEGER,manager_name TEXT,nazk_certificate_required INTEGER,nazk_certificate_checked INTEGER,created_at TEXT);
          CREATE TABLE supplier_registry_summary(supplier_code TEXT PRIMARY KEY,supplier_name TEXT,active_count INTEGER);
          CREATE TABLE supplier_nazk_checks(id INTEGER PRIMARY KEY,supplier_code TEXT,manager_id INTEGER,manager_name TEXT,workflow_status TEXT,started_at TEXT);
          CREATE TABLE nazk_registry(source_id TEXT PRIMARY KEY,full_name TEXT,sentence_date TEXT);
          CREATE TABLE violation_reports(id TEXT PRIMARY KEY,report_id TEXT,date_published TEXT,defendant_period_end TEXT,author_name TEXT,author_code TEXT,defendant_name TEXT,defendant_code TEXT,reason TEXT,raw_json TEXT,authority_code TEXT);
          CREATE TABLE violation_report_reviews(report_id TEXT PRIMARY KEY,review_status TEXT,assigned_officer TEXT);
        """)
        end_year = date.today().year + 1
        self.con.execute("INSERT INTO frameworks VALUES ('f1','UA-F-1','12340000-0','active',?)", (json.dumps({"qualificationPeriod": {"endDate": f"{end_year}-12-31T00:00:00"}}),))
        self.con.execute("INSERT INTO framework_officers VALUES ('f1','Світлана НАМЯСЕНКО','ЇЖА')")
        self.con.execute("INSERT INTO qualifications VALUES ('q-pending','pending')")
        self.con.execute("INSERT INTO qualifications VALUES ('q-complete','active')")
        current_year = date.today().year
        self.today = date.today().isoformat()
        self.con.execute("INSERT INTO submissions VALUES ('s1','f1','ТОВ Один','11111111',?,'q-pending')", (f"{self.today}T09:00:00",))
        self.con.execute("INSERT INTO submissions VALUES ('s2','f1','ТОВ Два','22222222','2026-08-23T09:00:00','q-complete')")
        self.con.execute("INSERT INTO application_fields(submission_id,protocol_officer) VALUES ('s1','Світлана НАМЯСЕНКО')")
        self.con.execute("INSERT INTO application_fields(submission_id,protocol_officer) VALUES ('s2','')")
        self.con.execute("INSERT INTO supplier_managers VALUES (1,'1234567890')")
        self.con.execute("INSERT INTO supplier_registry_summary VALUES ('11111111','ТОВ Один',1)")
        self.con.execute("INSERT INTO supplier_registry_summary VALUES ('22222222','ТОВ Два',0)")
        self.con.commit()

    def tearDown(self):
        self.con.close()

    def queue(self, **filters):
        return get_uo_work_queue(self.con, filters, "Світлана НАМЯСЕНКО")

    def add_nazk_decision(self, *, date_value="2099-01-01", manager_name="КЕРІВНИК"):
        self.con.execute(
            "INSERT INTO nazk_registry VALUES (?,?,?)",
            (f"nazk-{date_value}-{manager_name}", manager_name, date_value),
        )

    def test_pending_qualification_is_not_an_individual_queue_task(self):
        self.assertEqual(self.queue(type="qualification")["total"], 0)

    def test_completed_qualification_is_not_task(self):
        ids = {item["source_id"] for item in self.queue(type="qualification")["items"]}
        self.assertNotIn("s2", ids)

    def test_current_pending_qualification_is_grouped_by_officer(self):
        summary = get_current_qualification_summary(self.con)
        self.assertEqual(summary["total"], 1)
        self.assertEqual(summary["officers"], [{"officer": "Світлана НАМЯСЕНКО", "applications": 1}])
        self.assertEqual(summary["categories"], [{"category": "ЇЖА", "applications": 1}])

    def test_officer_and_category_filters_are_independent_and_composable(self):
        self.assertEqual(get_current_qualification_summary(self.con, {"category": "ЇЖА"})["total"], 1)
        self.assertEqual(get_current_qualification_summary(self.con, {"category": "ІНШІ"})["total"], 0)
        self.assertEqual(get_current_qualification_summary(
            self.con, {"officer": "Світлана НАМЯСЕНКО", "category": "ЇЖА"}
        )["total"], 1)

    def test_current_block_starts_after_left_to_and_has_no_end_date(self):
        self.con.execute("INSERT INTO submissions VALUES ('s-yesterday','f1','ТОВ Учора','55555555','2026-08-25T09:00:00','q-pending')")
        self.con.execute("INSERT INTO application_fields(submission_id,protocol_officer) VALUES ('s-yesterday','Світлана НАМЯСЕНКО')")
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        self.con.execute("INSERT INTO submissions VALUES ('s-future','f1','ТОВ Далі','88888888',?,'q-pending')", (f"{tomorrow}T09:00:00",))
        self.con.execute("INSERT INTO application_fields(submission_id,protocol_officer) VALUES ('s-future','Світлана НАМЯСЕНКО')")
        left_to = (date.today() - timedelta(days=1)).isoformat()
        summary = get_current_qualification_summary(self.con, {"protocol_to": left_to})
        self.assertEqual(summary["from"], self.today)
        self.assertEqual(summary["to"], "")
        self.assertEqual(summary["total"], 2)

    def test_protocol_block_uses_received_date_selected_by_user(self):
        self.con.execute("INSERT INTO submissions VALUES ('s-protocol','f1','ТОВ Період','66666666','2026-08-25T12:00:00','q-pending')")
        self.con.execute("INSERT INTO application_fields(submission_id,protocol_officer) VALUES ('s-protocol','Світлана НАМЯСЕНКО')")
        summary = get_current_qualification_summary(self.con, {
            "protocol_from": "2026-08-25", "protocol_to": "2026-08-25"
        })
        self.assertEqual(summary["protocol"]["total"], 1)

    def test_publication_control_uses_synced_status_without_local_action(self):
        self.con.executemany("INSERT INTO qualifications VALUES (?,?)", [
            ("q-admitted", "active"), ("q-rejected", "unsuccessful"), ("q-waiting", "pending")
        ])
        self.con.executemany("INSERT INTO submissions VALUES (?,?,?,?,?,?)", [
            ("s-admitted", "f1", "ТОВ Допущено", "101", "2026-08-24T09:00:00", "q-admitted"),
            ("s-rejected", "f1", "ТОВ Відхилено", "102", "2026-08-24T10:00:00", "q-rejected"),
            ("s-waiting", "f1", "ТОВ Очікує", "103", "2026-08-24T11:00:00", "q-waiting"),
        ])
        summary = get_current_qualification_summary(self.con, {
            "protocol_from": "2026-08-24", "protocol_to": "2026-08-24"
        })
        self.assertEqual(summary["protocol"]["total"], 3)
        self.assertEqual(summary["publication_control"], {
            "admitted": 1, "rejected": 1, "awaiting_sync": 1
        })
        self.assertEqual(sum(summary["publication_control"].values()), summary["protocol"]["total"])

    def test_officer_cards_merge_case_variants_from_directory_sources(self):
        self.con.execute("INSERT INTO submissions VALUES ('s-case','f1','ТОВ Регістр','77777777',?,'q-pending')", (f"{self.today}T12:00:00",))
        self.con.execute("INSERT INTO application_fields(submission_id,protocol_officer) VALUES ('s-case','ДМИТРО САВВА')")
        self.con.execute("UPDATE application_fields SET protocol_officer='Дмитро САВВА' WHERE submission_id='s1'")
        summary = get_current_qualification_summary(self.con)
        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["officers"], [{"officer": "Дмитро САВВА", "applications": 2}])
        self.assertEqual(sum(item["applications"] for item in summary["officers"]), summary["total"])

    def test_queue_drilldown_preserves_the_matching_time_cohort(self):
        source = Path("app.js").read_text(encoding="utf-8")
        start = source.index("function openApplicationsFromQueue")
        drilldown = source[start:source.index("$('#queueQualificationCards')", start)]
        self.assertIn("addCalendarDays($('#queueProtocolTo').value,1)", drilldown)
        self.assertIn("$('#dateToFilter').value=''", drilldown)
        self.assertIn("$('#dateFromFilter').value=$('#queueProtocolFrom').value", drilldown)
        self.assertIn("$('#dateToFilter').value=$('#queueProtocolTo').value", drilldown)
        self.assertNotIn("localIsoDate", drilldown)

    def test_registry_refresh_keeps_drilldown_filters(self):
        source = Path("app.js").read_text(encoding="utf-8")
        start = source.index("async function loadRows()")
        loader = source[start:source.index("function bindStaticMulti", start)]
        self.assertIn("saveFilterState()", loader)
        self.assertIn("currentFilterParams()", loader)
        self.assertNotIn("dateFromFilter').value=''", loader)

    def test_old_or_completed_framework_qualification_is_excluded_from_summary(self):
        current_year = date.today().year
        self.con.execute("INSERT INTO frameworks VALUES ('f2','UA-F-2','12340000-0','complete',?)", (json.dumps({"qualificationPeriod": {"endDate": f"{current_year + 1}-12-31T00:00:00"}}),))
        self.con.execute("INSERT INTO submissions VALUES ('s3','f2','ТОВ Три','33333333',?,'q-pending')", (f"{self.today}T09:00:00",))
        self.con.execute("INSERT INTO submissions VALUES ('s4','f1','ТОВ Старе','44444444',?,'q-pending')", (f"{current_year - 1}-08-24T09:00:00",))
        self.assertEqual(get_current_qualification_summary(self.con)["total"], 1)

    def test_pending_submission_nazk_is_task(self):
        self.add_nazk_decision()
        self.con.execute("INSERT INTO submission_nazk_controls VALUES (1,'s1','11111111',1,'КЕРІВНИК',1,0,'2026-08-24')")
        self.assertEqual(self.queue(type="submission_nazk")["total"], 1)

    def test_admitted_historical_submission_is_not_application_nazk_task(self):
        self.add_nazk_decision(date_value="2026-09-01")
        self.con.execute("INSERT INTO registry_contracts VALUES ('q-complete','active')")
        self.con.execute("INSERT INTO submission_nazk_controls VALUES (1,'s2','22222222',1,'КЕРІВНИК',1,0,'2026-08-24')")
        before = self.con.execute("SELECT COUNT(*) FROM submission_nazk_controls").fetchone()[0]
        self.assertEqual(self.queue(type="submission_nazk")["total"], 0)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM submission_nazk_controls").fetchone()[0], before)

    def test_nazk_decision_on_or_before_submission_does_not_create_retro_task(self):
        self.add_nazk_decision(date_value="2020-01-01")
        self.con.execute("INSERT INTO submission_nazk_controls VALUES (1,'s1','11111111',1,'КЕРІВНИК',1,0,'2026-08-24')")
        self.assertEqual(self.queue(type="submission_nazk")["total"], 0)

    def test_nazk_decision_on_submission_date_does_not_create_retro_task(self):
        self.add_nazk_decision(date_value=self.today)
        self.con.execute("INSERT INTO submission_nazk_controls VALUES (1,'s1','11111111',1,'КЕРІВНИК',1,0,'2026-08-24')")
        self.assertEqual(self.queue(type="submission_nazk")["total"], 0)

    def test_checked_submission_nazk_disappears(self):
        self.con.execute("INSERT INTO submission_nazk_controls VALUES (1,'s1','11111111',1,'КЕРІВНИК',1,1,'2026-08-24')")
        self.assertEqual(self.queue(type="submission_nazk")["total"], 0)

    def test_unchecked_submission_nazk_in_completed_framework_is_not_task(self):
        self.con.execute("UPDATE frameworks SET status='complete' WHERE id='f1'")
        self.con.execute("INSERT INTO submission_nazk_controls VALUES (1,'s1','11111111',1,'КЕРІВНИК',1,0,'2026-08-24')")
        self.assertEqual(self.queue(type="submission_nazk")["total"], 0)

    def test_postqualification_supplier_nazk_is_owned_by_operational_tasks(self):
        self.add_nazk_decision()
        self.con.execute("INSERT INTO supplier_nazk_checks VALUES (1,'11111111',1,'КЕРІВНИК','waiting_response','2026-08-20')")
        self.assertEqual(self.queue(type="supplier_nazk")["total"], 0)
        self.assertFalse(any(item["task_type"] == "supplier_nazk" for item in self.queue()["items"]))

    def test_supplier_nazk_task_requires_decision_newer_than_an_application(self):
        self.add_nazk_decision(date_value="2020-01-01")
        self.con.execute("INSERT INTO supplier_nazk_checks VALUES (1,'11111111',1,'КЕРІВНИК','waiting_response','2026-08-20')")
        self.assertEqual(self.queue(type="supplier_nazk")["total"], 0)

    def test_inactive_supplier_is_not_task(self):
        self.con.execute("INSERT INTO supplier_nazk_checks VALUES (2,'22222222',1,'КЕРІВНИК','waiting_response','2026-08-20')")
        self.assertEqual(self.queue(type="supplier_nazk")["total"], 0)

    def test_pending_violation_is_task(self):
        self.con.execute("INSERT INTO violation_reports VALUES ('v1','UA-D-1','2026-08-20','2026-08-22','Замовник','333','ТОВ Один','11111111','contractBreach','{\"decisions\":[]}','40996564')")
        result = self.queue(type="violation_report")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["subject_name"], "ТОВ Один")
        self.assertEqual(result["items"][0]["subject_code"], "11111111")
        self.assertEqual(result["items"][0]["customer_name"], "Замовник")
        self.assertNotIn("Очікуємо пояснення постачальника", result["items"][0]["reason"])

    def test_foreign_cpo_request_is_informational_not_workload(self):
        self.con.execute("INSERT INTO violation_reports VALUES ('foreign','UA-D-FOREIGN','2026-08-20','2026-08-22','Інша ЦЗО','333','ТОВ Один','11111111','contractBreach','{\"decisions\":[]}','32348248')")
        owned=lambda row: str(row["authority_code"] or "") == "40996564"
        result=get_uo_work_queue(self.con,{"type":"violation_report"},"Світлана НАМЯСЕНКО",owned)
        self.assertEqual(result["total"],0)
        self.assertEqual(result["kpi"]["violation_report"],0)

    def test_reviewed_violation_is_not_an_unfinished_task(self):
        self.con.execute("INSERT INTO violation_reports VALUES ('v1','UA-D-1','2026-08-20','2026-08-22','Замовник','333','ТОВ Один','11111111','contractBreach','{\"decisions\":[]}','40996564')")
        self.con.execute("INSERT INTO violation_report_reviews VALUES ('v1','reviewed','Світлана НАМЯСЕНКО')")
        self.assertEqual(self.queue(type="violation_report")["total"], 0)

    def test_violation_queue_ui_maps_reason_and_status_labels(self):
        source = Path("app.js").read_text(encoding="utf-8")
        self.assertIn("contractBreach:'пп. 1 п. 49'", source)
        self.assertIn("signingRefusal:'пп. 2 п. 49'", source)
        self.assertIn("goodsNonCompliance:'пп. 3 п. 49'", source)
        self.assertIn("in_review:'На розгляді'", source)
        self.assertIn("queueReasonLabel(item.reason)", source)
        self.assertIn("violationReviewStatusLabels[item.status]", source)
        self.assertIn("item.customer_name", source)
        self.assertNotIn("Постачальник / замовник", Path("index.html").read_text(encoding="utf-8"))

    def test_official_violation_is_not_task(self):
        raw = json.dumps({"decisions": [{"id": "d1"}]})
        self.con.execute("INSERT INTO violation_reports VALUES ('v1','UA-D-1','2026-08-20','2026-08-22','Замовник','333','ТОВ Один','11111111','contractBreach',?,'40996564')", (raw,))
        self.assertEqual(self.queue(type="violation_report")["total"], 0)

    def test_one_subject_can_have_three_tasks(self):
        self.add_nazk_decision()
        self.con.execute("INSERT INTO submission_nazk_controls VALUES (1,'s1','11111111',1,'КЕРІВНИК',1,0,'2026-08-24')")
        self.con.execute("INSERT INTO supplier_nazk_checks VALUES (1,'11111111',1,'КЕРІВНИК','needs_review','2026-08-20')")
        tasks = [item for item in self.queue()["items"] if item["subject_code"] == "11111111"]
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["task_type"], "submission_nazk")

    def test_repeat_get_has_stable_unique_ids(self):
        first = [item["task_id"] for item in self.queue()["items"]]
        second = [item["task_id"] for item in self.queue()["items"]]
        self.assertEqual(first, second)
        self.assertEqual(len(first), len(set(first)))

    def test_kpi_matches_filtered_list(self):
        result = self.queue(type="qualification")
        self.assertEqual(result["kpi"]["total"], result["total"])
        self.assertEqual(result["kpi"]["qualification"], result["total"])

    def test_mine_all_and_unassigned(self):
        self.add_nazk_decision()
        self.con.execute("INSERT INTO supplier_nazk_checks VALUES (1,'11111111',1,'КЕРІВНИК','waiting_response','2026-08-20')")
        self.assertEqual(self.queue(mine="1")["total"], 0)
        self.assertEqual(self.queue(responsible_user="__unassigned__")["total"], 0)
        self.assertEqual(self.queue()["total"], 0)

    def test_task_has_deep_link_source(self):
        self.add_nazk_decision()
        self.con.execute("INSERT INTO submission_nazk_controls VALUES (1,'s1','11111111',1,'КЕРІВНИК',1,0,'2026-08-24')")
        task = self.queue(type="submission_nazk")["items"][0]
        self.assertEqual(task["source_view"], "applications")
        self.assertEqual(task["source_params"]["submission_id"], "s1")


if __name__ == "__main__":
    unittest.main()
