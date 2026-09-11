import inspect
import json
import tempfile
import unittest
from pathlib import Path

import server


class ApplicationPageFirstTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.old_db = server.DB_PATH
        server.DB_PATH = Path(self.temp.name) / "test.sqlite3"
        server.init_db()
        server.init_reference_tables(server.DB_PATH)
        with server.db() as con:
            con.execute(
                """INSERT INTO frameworks(id,pretty_id,title,dk_code,status,raw_json,synced_at)
                   VALUES ('framework-page','UA-F-PAGE','Тестова назва відбору','12345678-9',
                           'active','{}',?)""",
                (server.now_iso(),),
            )
            con.execute(
                """INSERT INTO supplier_edr_profiles
                   (supplier_code,manager_name,edr_checked_at,synced_at)
                   VALUES ('12-34','КЕРІВНИК З ЄДР','2026-08-20',?)""",
                (server.now_iso(),),
            )
            for index in range(60):
                submission_id = f"submission-{index:02d}"
                qualification_id = f"qualification-{index:02d}"
                con.execute(
                    """INSERT INTO qualifications
                       (id,framework_id,submission_id,status,documents_json,raw_json,synced_at)
                       VALUES (?,?,?,'pending','[]','{}',?)""",
                    (qualification_id, "framework-page", submission_id, server.now_iso()),
                )
                con.execute(
                    """INSERT INTO submissions
                       (id,framework_id,supplier_code,supplier_name,qualification_id,
                        date_published,documents_json,raw_json,synced_at)
                       VALUES (?,?,?,?,?,?,?,'{}',?)""",
                    (submission_id, "framework-page", "1234", f"Постачальник {index}",
                     qualification_id, f"2026-08-{index // 24 + 1:02d}T{index % 24:02d}:00:00",
                     json.dumps([]), server.now_iso()),
                )
                con.execute("INSERT INTO application_fields(submission_id) VALUES (?)",
                            (submission_id,))

    def tearDown(self):
        server.DB_PATH = self.old_db
        self.temp.cleanup()

    def test_page_order_and_edr_enrichment_are_preserved(self):
        result = server.list_applications({
            "page": ["1"], "size": ["10"], "sort": ["receivedDate"],
            "direction": ["desc"],
        })
        self.assertEqual(result["total"], 60)
        self.assertEqual([row["id"] for row in result["items"]],
                         [f"submission-{index:02d}" for index in range(59, 49, -1)])
        self.assertTrue(all(row["edr_fallback_manager"] == "КЕРІВНИК З ЄДР"
                            for row in result["items"]))
        self.assertTrue(all(row["edr_fallback_checked_at"] == "2026-08-20"
                            for row in result["items"]))

    def test_framework_title_search_keeps_same_page_semantics(self):
        result = server.list_applications({
            "page": ["1"], "size": ["10"], "search": ["назва відбору"],
        })
        self.assertEqual(result["total"], 60)
        self.assertEqual(len(result["items"]), 10)

    def test_expensive_edr_join_is_not_part_of_page_selection(self):
        source = inspect.getsource(server.list_applications)
        page_query = source.split("records = [dict(row) for row in con.execute", 1)[1].split(
            "supplier_codes =", 1
        )[0]
        self.assertNotIn("JOIN supplier_edr_profiles", page_query)
        self.assertIn("LIMIT ? OFFSET ?", page_query)

    def test_marketplace_decision_filter_supports_empty_and_multiple_values(self):
        clause, args = server.application_filter({
            "marketplace_decision": ["__empty__,reject"],
        })
        self.assertIn("COALESCE(af.marketplace_decision,'') IN (?,?)", clause)
        self.assertEqual(args, ["", "reject"])

    def test_marketplace_decision_filter_combines_with_existing_filters(self):
        clause, args = server.application_filter({
            "marketplace_decision": ["admit"],
            "status": ["Допущено"],
            "category": ["Їжа"],
        })
        self.assertIn("COALESCE(af.marketplace_decision,'') IN (?)", clause)
        self.assertIn("COALESCE(q.status,'pending') IN (?)", clause)
        self.assertIn("COALESCE(fo.category,'')=?", clause)
        self.assertEqual(args, ["admit", "Їжа", "active"])

    def test_search_whitelist_contains_manager_and_contract_details(self):
        clause, args = server.application_filter({"search": ["договір 42"]})
        self.assertIn("CASEFOLD(af.manager_name)", clause)
        self.assertIn("CASEFOLD(af.contract_details)", clause)
        self.assertEqual(len(args), len(server.APPLICATION_SEARCH_FIELDS))

    def test_search_field_registry_drives_sql_and_user_labels(self):
        fields = server.APPLICATION_SEARCH_FIELDS
        self.assertTrue(all({"key", "label", "sql"} <= set(field) for field in fields))
        self.assertIn("ПІБ керівника", {field["label"] for field in fields})
        self.assertIn("реквізити договору", {field["label"] for field in fields})

    def test_profile_layout_preserves_pin_and_kpi_order(self):
        raw = server._profile_layout_json(
            [{"key": "number", "visible": True, "order": 1, "width": 65, "pin": "left"},
             {"key": "participant", "visible": True, "order": 2, "width": 275, "pin": ""}],
            ["pending", "applications", "officers"],
        )
        layout = json.loads(raw)
        self.assertEqual(layout["columns"][0]["pin"], "left")
        self.assertEqual(layout["columns"][0]["width"], 65)
        self.assertEqual(layout["kpis"], ["pending", "applications", "officers"])

    def test_pending_effective_officer_prefers_manual_protocol_officer(self):
        with server.db() as con:
            con.execute("INSERT INTO framework_officers(framework_id,officer,synced_at) VALUES (?,?,?)",
                        ("framework-page", "УО ВІДБОРУ", server.now_iso()))
            con.execute("UPDATE application_fields SET protocol_officer=? WHERE submission_id=?",
                        ("РУЧНА УО", "submission-00"))
        manual = server.list_applications({"officer": ["РУЧНА УО"], "size": ["10"]})
        fallback = server.list_applications({"officer": ["УО ВІДБОРУ"], "size": ["100"]})
        self.assertEqual([item["id"] for item in manual["items"]], ["submission-00"])
        self.assertNotIn("submission-00", {item["id"] for item in fallback["items"]})
        self.assertEqual(manual["items"][0]["protocol_officer"], "РУЧНА УО")


if __name__ == "__main__":
    unittest.main()
