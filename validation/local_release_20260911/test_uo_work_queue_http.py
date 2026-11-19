"""HTTP integration coverage for the read-only UO work queue summaries."""
from contextlib import closing, contextmanager
import gc
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import server


class UoWorkQueueHttpTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            prefix="pqm-uo-work-http-", ignore_cleanup_errors=True
        )
        self.db_path = Path(self.temporary.name) / "test.sqlite3"
        self.addCleanup(self.temporary.cleanup)
        self.addCleanup(gc.collect)
        self.patches = [
            patch.object(server, "DB_PATH", self.db_path),
            patch.object(server, "AUTH_ENABLED", False),
            patch.object(server, "LOCAL_ROLE_IMPERSONATION", True),
            patch.object(server, "IS_WEB_ENV", False),
            patch.object(server, "SANDBOX_MODE", False),
            patch.object(server, "SAFE_MODE", False),
            patch.object(server, "CURRENT_USER", "Тестова УО"),
        ]
        for active_patch in self.patches:
            active_patch.start()
            self.addCleanup(active_patch.stop)

        server.init_db()
        server.init_reference_tables(self.db_path)
        self._seed()

        original_db = server.db

        @contextmanager
        def closed_db():
            with closing(original_db()) as connection:
                with connection:
                    yield connection

        self.db_patch = patch.object(server, "db", closed_db)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.http.daemon_threads = False
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop_http)

        self.classifications = {
            "supplier-fop": {"entity_type": "individual_entrepreneur"},
            "supplier-fop-old": {"entity_type": "individual_entrepreneur"},
            "supplier-legal": {"entity_type": "legal_entity"},
            "supplier-foreign": {"entity_type": "foreign_legal_entity"},
            "supplier-unknown": {"entity_type": "unknown"},
            "supplier-fop-second": {"entity_type": "individual_entrepreneur"},
        }

    def _seed(self):
        records = [
            ("fop", "supplier-fop", "individual_entrepreneur", "2026-11-12", "Олена ЄРЬОМІНА", "protocol-a", "admit"),
            ("fop-old", "supplier-fop-old", "individual_entrepreneur", "2026-11-10", "Олена ЄРЬОМІНА", "protocol-b", ""),
            ("legal", "supplier-legal", "legal_entity", "2026-11-12", "Дмитро САВВА", "protocol-a", "reject"),
            ("foreign", "supplier-foreign", "foreign_legal_entity", "2026-11-12", "Тетяна ФЕДЧЕНКО", "protocol-c", ""),
            ("unknown", "supplier-unknown", "unknown", "2026-11-12", "Світлана НАМЯСЕНКО", "protocol-c", ""),
        ]
        with closing(server.db()) as connection:
            for index, (key, code, _kind, received, review, protocol, decision) in enumerate(records):
                framework_id = f"framework-{key}"
                submission_id = f"submission-{key}"
                qualification_id = f"qualification-{key}"
                connection.execute(
                    "INSERT INTO frameworks(id,pretty_id,title,dk_code,status,raw_json,synced_at) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (framework_id, f"UA-F-{key}", f"Закупівля {key}", f"{index + 1:02d}000000-0",
                     "active", "{}", "2026-11-17"),
                )
                connection.execute(
                    "INSERT INTO framework_officers(framework_id,officer,category,synced_at) VALUES(?,?,?,?)",
                    (framework_id, review, "ЇЖА" if index % 2 == 0 else "ВУГІЛЛЯ", "2026-11-17"),
                )
                connection.execute(
                    "INSERT INTO framework_service_directory(pretty_id,framework_id,responsible_officer,source,synced_at) VALUES(?,?,?,'Google Sheets: Оголошення',?)",
                    (f"UA-F-{key}", framework_id, review, "2026-11-17"),
                )
                connection.execute(
                    "INSERT INTO qualifications(id,framework_id,submission_id,status,raw_json,synced_at) "
                    "VALUES(?,?,?,?,?,?)",
                    (qualification_id, framework_id, submission_id,
                     "active" if decision == "admit" else "unsuccessful" if decision == "reject" else "pending",
                     "{}", "2026-11-17"),
                )
                connection.execute(
                    "INSERT INTO submissions(id,framework_id,supplier_name,supplier_code,date_published,"
                    "qualification_id,raw_json,synced_at) VALUES(?,?,?,?,?,?,?,?)",
                    (submission_id, framework_id, f"Постачальник {key}", code, f"{received}T09:00:00",
                     qualification_id, "{}", "2026-11-17"),
                )
                connection.execute(
                    "INSERT INTO application_fields(submission_id,review_officer,protocol_officer,protocol_decision) "
                    "VALUES(?,?,?,?)",
                    (submission_id, review, protocol, decision),
                )
            connection.commit()

    def _stop_http(self):
        self.http.shutdown()
        self.thread.join()
        self.http.server_close()

    def get(self, params=None):
        return self.get_path("/api/uo-work-queue", params)

    def get_path(self, path, params=None):
        query = urllib.parse.urlencode(params or {}, doseq=True)
        url = f"http://127.0.0.1:{self.http.server_port}{path}"
        if query:
            url += "?" + query
        request = urllib.request.Request(
            url, headers={"Connection": "close", "X-PQM-Local-Role": "officer"}
        )
        try:
            response = urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    def _with_classification(self, callback):
        with patch("supplier_classification.build_index", return_value=self.classifications):
            return callback()

    def _with_manual_classification(self, rows, callback):
        with patch("supplier_manual_classification.build_index", return_value=rows):
            return self._with_classification(callback)

    @staticmethod
    def _total(items):
        return sum(int(item.get("total", 0)) for item in items)

    def test_application_statistics_without_entity_type_returns_success(self):
        status, payload = self.get({"summary": "application-statistics"})
        self.assertEqual(status, 200, payload)
        self.assertEqual(self._total(payload["items"]), 5)
        self.assertEqual(payload["totals"], {"total": 5, "active": 1, "unsuccessful": 1, "pending": 3})
        self.assertEqual(sum(item["submitted"] for item in payload["trend"]), 5)
        self.assertEqual(payload["filter_options"]["dk_code"], ["01000000-0", "02000000-0", "03000000-0", "04000000-0", "05000000-0"])

    def test_application_history_without_filters_returns_success(self):
        status, payload = self.get_path("/api/application-history")
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["total"], 5)
        self.assertEqual(len(payload["items"]), 5)
        self.assertIn("review_officers", payload)

    def test_statistics_normalizes_only_null_and_missing_qualification_and_reports_status_anomalies(self):
        cases = [
            ("null-status", "anomaly-qualification-null", None, "anomaly-qualification-null", "admit"),
            ("no-qualification", "anomaly-qualification-absent", None, "no-linked-qualification", "reject"),
            ("empty-status", "anomaly-qualification-empty", "", "anomaly-qualification-empty", ""),
            ("unknown-status", "anomaly-qualification-unknown", "paused", "anomaly-qualification-unknown", ""),
        ]
        with server.db() as connection:
            for index, (key, qualification_id, qualification_status, submission_qualification_id, protocol_decision) in enumerate(cases):
                framework_id = f"framework-{key}"
                submission_id = f"submission-{key}"
                connection.execute(
                    "INSERT INTO frameworks(id,pretty_id,title,dk_code,status,raw_json,synced_at) VALUES(?,?,?,?,?,?,?)",
                    (framework_id, f"UA-F-{key}", key, "01000000-0", "active", "{}", "2026-11-17"),
                )
                connection.execute(
                    "INSERT INTO framework_officers(framework_id,officer,category,synced_at) VALUES(?,?,?,?)",
                    (framework_id, "УО ТЕСТ", "ЇЖА", "2026-11-17"),
                )
                if key != "no-qualification":
                    connection.execute(
                        "INSERT INTO qualifications(id,framework_id,submission_id,status,raw_json,synced_at) VALUES(?,?,?,?,?,?)",
                        (qualification_id, framework_id, submission_id, qualification_status, "{}", "2026-11-17"),
                    )
                connection.execute(
                    "INSERT INTO submissions(id,framework_id,supplier_name,supplier_code,date_published,qualification_id,raw_json,synced_at) VALUES(?,?,?,?,?,?,?,?)",
                    (submission_id, framework_id, key, f"supplier-{key}", "2026-11-12T12:00:00",
                     submission_qualification_id, "{}", "2026-11-17"),
                )
                connection.execute(
                    "INSERT INTO application_fields(submission_id,protocol_decision) VALUES(?,?)",
                    (submission_id, protocol_decision),
                )
            connection.commit()

        status, payload = self.get({
            "summary": "application-statistics", "date_from": "2026-11-10", "date_to": "2026-11-12",
        })
        self.assertEqual(status, 200, payload)
        # The seeded data has 1 admitted, 1 rejected, 3 pending; only NULL and
        # a missing qualification join add to pending. Local PQM decisions do not.
        self.assertEqual(payload["totals"], {"total": 9, "active": 1, "unsuccessful": 1, "pending": 5})
        self.assertEqual(payload["diagnostics"]["null_status"], 1)
        self.assertEqual(payload["diagnostics"]["missing_qualification"], 1)
        self.assertEqual(payload["diagnostics"]["empty_status"], 1)
        self.assertEqual(payload["diagnostics"]["unknown_status"], 1)
        self.assertEqual(payload["diagnostics"]["unknown_values"], [{"status": "paused", "total": 1}])
        self.assertEqual(sum(item["submitted"] for item in payload["trend"]), 9)
        self.assertEqual(sum(item["pending"] for item in payload["trend"]), 5)
        self.assertEqual(sum(item["empty_status"] for item in payload["trend"]), 1)
        self.assertEqual(sum(item["unknown_status"] for item in payload["trend"]), 1)

    def test_statistics_filters_apply_to_kpis_table_options_and_trend_together(self):
        with server.db() as connection:
            connection.execute(
                "INSERT INTO frameworks(id,pretty_id,title,dk_code,status,raw_json,synced_at) VALUES(?,?,?,?,?,?,?)",
                ("framework-fop-second", "UA-F-fop-second", "Друга закупівля ФОП", "06000000-0", "active", "{}", "2026-11-17"),
            )
            connection.execute(
                "INSERT INTO framework_officers(framework_id,officer,category,synced_at) VALUES(?,?,?,?)",
                ("framework-fop-second", "Олена ЄРЬОМІНА", "ЇЖА", "2026-11-17"),
            )
            connection.execute(
                "INSERT INTO qualifications(id,framework_id,submission_id,status,raw_json,synced_at) VALUES(?,?,?,?,?,?)",
                ("qualification-fop-second", "framework-fop-second", "submission-fop-second", "pending", "{}", "2026-11-17"),
            )
            connection.execute(
                "INSERT INTO submissions(id,framework_id,supplier_name,supplier_code,date_published,qualification_id,raw_json,synced_at) VALUES(?,?,?,?,?,?,?,?)",
                ("submission-fop-second", "framework-fop-second", "Другий ФОП", "supplier-fop-second", "2026-11-12T10:00:00", "qualification-fop-second", "{}", "2026-11-17"),
            )
            connection.execute(
                "INSERT INTO application_fields(submission_id,review_officer,protocol_officer,protocol_decision) VALUES(?,?,?,?)",
                ("submission-fop-second", "Олена ЄРЬОМІНА", "protocol-a", "reject"),
            )
            connection.commit()
        status, payload = self._with_classification(lambda: self.get({
            "summary": "application-statistics",
            "date_from": "2026-11-12", "date_to": "2026-11-12",
            "entity_type": "individual_entrepreneur",
            "category": "ЇЖА", "review_officer": "Олена ЄРЬОМІНА",
            "protocol_officer": "protocol-a", "dk_code": ["01000000-0", "06000000-0"],
        }))
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["totals"], {"total": 2, "active": 1, "unsuccessful": 0, "pending": 1})
        self.assertEqual(sum(item["submitted"] for item in payload["trend"]), payload["totals"]["total"])
        self.assertEqual(self._total(payload["items"]), payload["totals"]["total"])
        self.assertEqual({item["review_officer"] for item in payload["items"]}, {"Олена ЄРЬОМІНА"})
        self.assertEqual({item["dk_code"] for item in payload["items"]}, {"01000000-0", "06000000-0"})
        self.assertEqual(payload["trend"][0]["date"], "2026-11-12", "all trend series use submission received date")

    def test_application_statistics_filters_every_supported_entity_type(self):
        expected = {
            "individual_entrepreneur": 2,
            "legal_entity": 1,
            "foreign_legal_entity": 1,
            "unknown": 1,
        }
        for entity_type, total in expected.items():
            with self.subTest(entity_type=entity_type):
                status, payload = self._with_classification(lambda: self.get({
                    "summary": "application-statistics", "entity_type": entity_type,
                }))
                self.assertEqual(status, 200, payload)
                self.assertEqual(self._total(payload["items"]), total)

    def test_application_statistics_combines_type_and_dates_and_keeps_client_dimensions(self):
        status, payload = self._with_classification(lambda: self.get({
            "summary": "application-statistics",
            "entity_type": "individual_entrepreneur",
            "date_from": "2026-11-11",
            "date_to": "2026-11-12",
            # These dimensions remain available for the existing client-side filters.
            "dk_code": "01000000-0",
            "category": "ЇЖА",
        }))
        self.assertEqual(status, 200, payload)
        self.assertEqual(self._total(payload["items"]), 1)
        self.assertEqual(payload["items"][0]["dk_code"], "01000000-0")
        self.assertIn("category", payload["items"][0])

    def test_statistics_drilldown_counts_match_real_registry_route_for_both_groupings(self):
        drill_rows = [
            ("drill-active", "supplier-drill-active", "active", "УО ПРОТОКОЛУ А", "ПРОТОКОЛЬНА А", "01000000-0"),
            ("drill-rejected", "supplier-drill-rejected", "unsuccessful", "УО ПРОТОКОЛУ А", "ПРОТОКОЛЬНА А", "06000000-0"),
            ("drill-active-blank", "supplier-drill-active-blank", "active", "", "ПРОТОКОЛЬНА А", "01000000-0"),
            ("drill-rejected-blank", "supplier-drill-rejected-blank", "unsuccessful", "", "ПРОТОКОЛЬНА А", "06000000-0"),
            ("drill-null", "supplier-drill-null", None, "", "ПРОТОКОЛЬНА Б", "01000000-0"),
            ("drill-missing", "supplier-drill-missing", None, "", "ПРОТОКОЛЬНА Б", "06000000-0"),
        ]
        with server.db() as connection:
            for index, (key, code, status_value, direct_protocol, framework_protocol, dk_code) in enumerate(drill_rows):
                self.classifications[code] = {"entity_type": "individual_entrepreneur"}
                framework_id = f"framework-{key}"
                submission_id = f"submission-{key}"
                qualification_id = f"qualification-{key}"
                connection.execute(
                    "INSERT INTO frameworks(id,pretty_id,title,dk_code,status,raw_json,synced_at) VALUES(?,?,?,?,?,?,?)",
                    (framework_id, f"UA-F-{key}", key, dk_code, "active", "{}", "2026-11-17"),
                )
                connection.execute(
                    "INSERT INTO framework_officers(framework_id,officer,category,synced_at) VALUES(?,?,?,?)",
                    (framework_id, framework_protocol, "ЇЖА", "2026-11-17"),
                )
                connection.execute(
                    "INSERT INTO framework_service_directory(pretty_id,framework_id,responsible_officer,source,synced_at) VALUES(?,?,?,'Google Sheets: Оголошення',?)",
                    (f"UA-F-{key}", framework_id, framework_protocol, "2026-11-17"),
                )
                if key != "drill-missing":
                    connection.execute(
                        "INSERT INTO qualifications(id,framework_id,submission_id,status,raw_json,synced_at) VALUES(?,?,?,?,?,?)",
                        (qualification_id, framework_id, submission_id, status_value, "{}", "2026-11-17"),
                    )
                connection.execute(
                    "INSERT INTO submissions(id,framework_id,supplier_name,supplier_code,date_published,qualification_id,raw_json,synced_at) VALUES(?,?,?,?,?,?,?,?)",
                    (submission_id, framework_id, key, code, f"2026-11-12T{9 + index:02d}:00:00",
                     None if key == "drill-missing" else qualification_id, "{}", "2026-11-17"),
                )
                connection.execute(
                    "INSERT INTO application_fields(submission_id,review_officer,protocol_officer) VALUES(?,?,?)",
                    (submission_id, "Олена ЄРЬОМІНА", direct_protocol),
                )
            connection.commit()

        filters = {
            "date_from": "2026-11-10", "date_to": "2026-11-12",
            "entity_type": "individual_entrepreneur", "category": "ЇЖА",
            "review_officer": "Олена ЄРЬОМІНА", "dk_code": ["01000000-0", "06000000-0"],
        }
        status_labels = {"active": "Допущено", "unsuccessful": "Відхилено", "pending": "Очікує рішення"}
        for group_by in ("review_officer", "protocol_officer"):
            with self.subTest(group_by=group_by):
                status, statistics = self._with_classification(lambda: self.get({
                    "summary": "application-statistics", **filters,
                }))
                self.assertEqual(status, 200, statistics)
                names = sorted({item[group_by] or "" for item in statistics["items"]})
                for name in names:
                    for status_code in ("active", "unsuccessful", "pending", ""):
                        expected = sum(
                            int(item["total"] or 0) for item in statistics["items"]
                            if (item[group_by] or "") == name
                            and (not status_code or item["status"] == status_code)
                        )
                        registry_filters = {
                            **filters,
                            group_by: name or "__unassigned__",
                            "page": "1", "size": "50",
                        }
                        if status_code:
                            registry_filters["status"] = status_labels[status_code]
                        registry_status, registry = self._with_classification(
                            lambda: self.get_path("/api/applications", registry_filters))
                        self.assertEqual(registry_status, 200, registry)
                        metric = status_code or "total"
                        self.assertEqual(
                            registry["total"], expected,
                            f"{group_by}={name or 'Не визначено'}, metric={metric}",
                        )

    def test_registry_http_uses_pending_fallback_but_not_for_completed_blank_protocol_fields(self):
        with server.db() as connection:
            for key, status_value in (("pending", "pending"), ("active", "active"), ("rejected", "unsuccessful"),
                                      ("manual", "pending"), ("review-blank", "pending")):
                framework_id, submission_id, qualification_id = f"assigned-{key}", f"assigned-sub-{key}", f"assigned-q-{key}"
                connection.execute(
                    "INSERT INTO frameworks(id,pretty_id,title,dk_code,status,raw_json,synced_at) VALUES(?,?,?,?,?,?,?)",
                    (framework_id, f"UA-F-assigned-{key}", key, "01000000-0", "active", "{}", "2026-11-17"),
                )
                connection.execute(
                    "INSERT INTO framework_service_directory(pretty_id,framework_id,responsible_officer,source,synced_at) VALUES(?,?,?,'PQM',?)",
                    (f"UA-F-assigned-{key}", framework_id, "УО ВІДБОРУ", "2026-11-17"),
                )
                connection.execute(
                    "INSERT INTO qualifications(id,framework_id,submission_id,status,raw_json,synced_at) VALUES(?,?,?,?,?,?)",
                    (qualification_id, framework_id, submission_id, status_value, "{}", "2026-11-17"),
                )
                connection.execute(
                    "INSERT INTO submissions(id,framework_id,supplier_name,supplier_code,date_published,qualification_id,raw_json,synced_at) VALUES(?,?,?,?,?,?,?,?)",
                    (submission_id, framework_id, key, f"assigned-{key}", "2026-11-12T12:00:00", qualification_id, "{}", "2026-11-17"),
                )
                connection.execute(
                    "INSERT INTO application_fields(submission_id,review_officer,protocol_officer) VALUES(?,?,?)",
                    (submission_id, "" if key == "review-blank" else "ІНША УО РОЗГЛЯДУ",
                     "РУЧНА УО" if key == "manual" else ""),
                )
            connection.commit()

        status, registry = self.get_path("/api/applications", {"size": 100, "date_from": "2026-11-12"})
        self.assertEqual(status, 200, registry)
        records = {item["id"]: item for item in registry["items"]}
        self.assertEqual(records["assigned-sub-pending"]["protocol_officer"], "УО ВІДБОРУ")
        self.assertEqual(records["assigned-sub-active"]["protocol_officer"], "Не визначено")
        self.assertEqual(records["assigned-sub-rejected"]["protocol_officer"], "Не визначено")
        self.assertEqual(records["assigned-sub-manual"]["protocol_officer"], "РУЧНА УО")
        self.assertEqual(records["assigned-sub-review-blank"]["review_officer"], "Не визначено")
        self.assertTrue(all(records[f"assigned-sub-{key}"]["review_officer"] == "ІНША УО РОЗГЛЯДУ"
                            for key in ("pending", "active", "rejected", "manual")))

        for status_label, submission_id in (("Очікує рішення", "assigned-sub-pending"),
                                            ("Допущено", "assigned-sub-active"),
                                            ("Відхилено", "assigned-sub-rejected")):
            filtered_status, filtered = self.get_path("/api/applications", {
                "status": status_label, "protocol_officer": "Не визначено" if status_label != "Очікує рішення" else "УО ВІДБОРУ",
                "review_officer": "ІНША УО РОЗГЛЯДУ", "size": 100,
            })
            self.assertEqual(filtered_status, 200, filtered)
            self.assertEqual([item["id"] for item in filtered["items"]], [submission_id])

        with server.db() as connection:
            connection.execute(
                "UPDATE framework_service_directory SET responsible_officer='НОВА УО ВІДБОРУ' WHERE framework_id='assigned-pending'"
            )
            connection.commit()
        changed_status, changed = self.get_path("/api/applications", {
            "protocol_officer": "НОВА УО ВІДБОРУ", "status": "Очікує рішення", "size": 100,
        })
        self.assertEqual(changed_status, 200, changed)
        self.assertEqual([item["id"] for item in changed["items"]], ["assigned-sub-pending"])
        stats_status, stats = self.get({
            "summary": "application-statistics", "date_from": "2026-11-12", "date_to": "2026-11-12",
        })
        self.assertEqual(stats_status, 200, stats)
        assigned_total = sum(int(item["total"] or 0) for item in stats["items"]
                             if item["protocol_officer"] == "НОВА УО ВІДБОРУ")
        registry_status, registry = self.get_path("/api/applications", {
            "protocol_officer": "НОВА УО ВІДБОРУ", "status": "Очікує рішення",
            "date_from": "2026-11-12", "date_to": "2026-11-12", "size": 100,
        })
        self.assertEqual(registry_status, 200, registry)
        self.assertEqual(assigned_total, registry["total"])
        self.assertEqual(assigned_total, 1)
        manual_status, manual = self.get_path("/api/applications", {
            "protocol_officer": "РУЧНА УО", "size": 100,
        })
        self.assertEqual(manual_status, 200, manual)
        self.assertEqual([item["id"] for item in manual["items"]], ["assigned-sub-manual"])
        review_blank_status, review_blank = self.get_path("/api/applications", {
            "review_officer": "Не визначено", "size": 100,
        })
        self.assertEqual(review_blank_status, 200, review_blank)
        self.assertEqual([item["id"] for item in review_blank["items"]], ["assigned-sub-review-blank"])

    def test_registry_entity_type_uses_manual_classification_for_rows_counts_and_stats(self):
        self.classifications["supplier-fop-second"] = {"entity_type": "individual_entrepreneur"}
        with server.db() as connection:
            framework_id = "framework-manual-fop"
            submission_id = "submission-manual-fop"
            qualification_id = "qualification-manual-fop"
            connection.execute(
                "INSERT INTO frameworks(id,pretty_id,title,dk_code,status,raw_json,synced_at) VALUES(?,?,?,?,?,?,?)",
                (framework_id, "UA-F-manual-fop", "Ручний ФОП", "06000000-0", "active", "{}", "2026-11-17"),
            )
            connection.execute(
                "INSERT INTO framework_officers(framework_id,officer,category,synced_at) VALUES(?,?,?,?)",
                (framework_id, "ПРОТОКОЛЬНА А", "ЇЖА", "2026-11-17"),
            )
            connection.execute(
                "INSERT INTO qualifications(id,framework_id,submission_id,status,raw_json,synced_at) VALUES(?,?,?,?,?,?)",
                (qualification_id, framework_id, submission_id, "pending", "{}", "2026-11-17"),
            )
            connection.execute(
                "INSERT INTO submissions(id,framework_id,supplier_name,supplier_code,date_published,qualification_id,raw_json,synced_at) VALUES(?,?,?,?,?,?,?,?)",
                (submission_id, framework_id, "Друга заявка", "supplier-fop-second", "2026-11-12T10:00:00",
                 qualification_id, "{}", "2026-11-17"),
            )
            connection.execute(
                "INSERT INTO application_fields(submission_id,review_officer,protocol_officer) VALUES(?,?,?)",
                (submission_id, "Дмитро САВВА", "protocol-a"),
            )
            connection.commit()

        manual = {
            "supplier-legal": {
                "supplier_code": "supplier-legal", "subject_type": "individual_entrepreneur",
                "residency": "UA", "google_group": "fop", "revision": 1, "is_active": 1,
                "changed_by": "test", "changed_officer_id": 1, "changed_officer_name": "Test",
                "changed_at": "2026-11-17T00:00:00Z",
            },
        }
        filters = {
            "date_from": "2026-11-12", "date_to": "2026-11-12",
            "entity_type": "individual_entrepreneur", "category": "ЇЖА",
            "review_officer": "Дмитро САВВА", "protocol_officer": "protocol-a",
            "dk_code": ["03000000-0", "06000000-0"],
        }
        def requests():
            stats_status, stats = self.get({"summary": "application-statistics", **filters})
            registry_status, registry = self.get_path("/api/applications", filters)
            rejected_status, rejected = self.get_path("/api/applications", {**filters, "status": "Відхилено"})
            upper_status, upper = self.get_path("/api/stats", filters)
            return (stats_status, stats, registry_status, registry,
                    rejected_status, rejected, upper_status, upper)
        result = self._with_manual_classification(manual, requests)
        stats_status, stats, registry_status, registry, rejected_status, rejected, upper_status, upper = result
        self.assertEqual(stats_status, 200, stats)
        self.assertEqual(registry_status, 200, registry)
        self.assertEqual(rejected_status, 200, rejected)
        self.assertEqual(upper_status, 200, upper)
        self.assertEqual(stats["totals"], {"total": 2, "active": 0, "unsuccessful": 1, "pending": 1})
        self.assertEqual(registry["total"], 2)
        self.assertEqual(rejected["total"], stats["totals"]["unsuccessful"])
        self.assertEqual(upper["applications"], 2)
        self.assertEqual(upper["rejected"], 1)
        self.assertEqual(upper["pending"], 1)

    def test_registry_entity_type_scopes_pagination_and_top_kpis_including_manual_override(self):
        for index in range(11):
            code = f"supplier-page-fop-{index}"
            self.classifications[code] = {"entity_type": "individual_entrepreneur"}
        self.classifications["supplier-page-manual"] = {"entity_type": "legal_entity"}
        self.classifications["supplier-page-other"] = {"entity_type": "legal_entity"}
        with server.db() as connection:
            for index, (code, status_value) in enumerate([
                *((f"supplier-page-fop-{index}", ("active", "unsuccessful", "pending")[index % 3]) for index in range(11)),
                ("supplier-page-manual", "unsuccessful"),
                ("supplier-page-other", "active"),
            ]):
                framework_id = f"framework-page-{index}"
                submission_id = f"submission-page-{index}"
                qualification_id = f"qualification-page-{index}"
                connection.execute(
                    "INSERT INTO frameworks(id,pretty_id,title,dk_code,status,raw_json,synced_at) VALUES(?,?,?,?,?,?,?)",
                    (framework_id, f"UA-F-page-{index}", "Пагінація за типом", "01000000-0", "active", "{}", "2026-11-17"),
                )
                connection.execute(
                    "INSERT INTO framework_officers(framework_id,officer,category,synced_at) VALUES(?,?,?,?)",
                    (framework_id, "УО тест", "КАТЕГОРІЯ ТИПУ", "2026-11-17"),
                )
                connection.execute(
                    "INSERT INTO qualifications(id,framework_id,submission_id,status,raw_json,synced_at) VALUES(?,?,?,?,?,?)",
                    (qualification_id, framework_id, submission_id, status_value, "{}", "2026-11-17"),
                )
                connection.execute(
                    "INSERT INTO submissions(id,framework_id,supplier_name,supplier_code,date_published,qualification_id,raw_json,synced_at) VALUES(?,?,?,?,?,?,?,?)",
                    (submission_id, framework_id, code, code, f"2026-11-12T{index + 1:02d}:00:00", qualification_id, "{}", "2026-11-17"),
                )
                connection.execute(
                    "INSERT INTO application_fields(submission_id) VALUES(?)", (submission_id,)
                )
            connection.commit()

        manual = {
            "supplier-page-manual": {
                "supplier_code": "supplier-page-manual", "subject_type": "individual_entrepreneur",
                "residency": "UA", "google_group": "fop", "revision": 1, "is_active": 1,
                "changed_by": "test", "changed_officer_id": 1, "changed_officer_name": "Test",
                "changed_at": "2026-11-17T00:00:00Z",
            },
        }
        filters = {
            "entity_type": "individual_entrepreneur", "category": "КАТЕГОРІЯ ТИПУ",
            "date_from": "2026-11-12", "date_to": "2026-11-12",
        }
        def requests():
            first_status, first = self.get_path("/api/applications", {**filters, "page": "1", "size": "10"})
            second_status, second = self.get_path("/api/applications", {**filters, "page": "2", "size": "10"})
            upper_status, upper = self.get_path("/api/stats", filters)
            selection_status, selection = self.get_path("/api/applications/selection", filters)
            cleared_status, cleared = self.get_path("/api/applications", {
                "category": filters["category"], "date_from": filters["date_from"], "date_to": filters["date_to"],
            })
            return (first_status, first, second_status, second, upper_status, upper,
                    selection_status, selection, cleared_status, cleared)
        result = self._with_manual_classification(manual, requests)
        (first_status, first, second_status, second, upper_status, upper,
         selection_status, selection, cleared_status, cleared) = result
        self.assertEqual((first_status, second_status, upper_status, selection_status, cleared_status), (200, 200, 200, 200, 200))
        self.assertEqual(first["total"], 12)
        self.assertEqual(first["pages"], 2)
        self.assertEqual(len(first["items"]), 10)
        self.assertEqual(second["total"], 12)
        self.assertEqual(second["pages"], 2)
        self.assertEqual(len(second["items"]), 2)
        self.assertIn("supplier-page-manual", {item["supplier_code"] for item in first["items"] + second["items"]})
        self.assertEqual(upper["applications"], 12)
        self.assertEqual(upper["admitted"] + upper["rejected"] + upper["pending"], 12)
        self.assertEqual(selection["total"], 12)
        self.assertEqual(len(selection["items"]), 12, "select-all endpoint uses the same effective supplier type")
        self.assertEqual(cleared["total"], 13, "clearing supplier type restores all matching classifications")

    def test_review_progress_without_type_preserves_default_grouping(self):
        status, payload = self.get({
            "summary": "review-progress", "date_from": "2026-11-10", "date_to": "2026-11-12",
        })
        self.assertEqual(status, 200, payload)
        self.assertEqual(self._total(payload["items"]), 5)
        self.assertEqual({item["review_officer"] for item in payload["items"]}, {
            "Олена ЄРЬОМІНА", "Дмитро САВВА", "Тетяна ФЕДЧЕНКО", "Світлана НАМЯСЕНКО",
        })

    def test_review_progress_accepts_type_with_dates_and_protocol_grouping(self):
        status, payload = self._with_classification(lambda: self.get({
            "summary": "review-progress",
            "entity_type": "individual_entrepreneur",
            "date_from": "2026-11-11",
            "date_to": "2026-11-12",
            "group_by": "protocol_officer",
        }))
        self.assertEqual(status, 200, payload)
        self.assertEqual(self._total(payload["items"]), 1)
        self.assertEqual(payload["items"][0]["protocol_officer"], "PROTOCOL-A")

    def test_invalid_type_returns_controlled_client_error(self):
        invalid_type = "not-a-supported-type"
        requests = (
            self.get({"summary": "application-statistics", "entity_type": invalid_type}),
            self.get_path("/api/applications", {"entity_type": invalid_type}),
            self.get_path("/api/applications/selection", {"entity_type": invalid_type}),
            self.get_path("/api/stats", {"entity_type": invalid_type}),
        )
        for status, payload in requests:
            self.assertEqual(status, 400, payload)
            self.assertEqual(payload["error"], "Невідомий тип постачальника")

    def test_existing_work_queue_route_without_summary_remains_available(self):
        status, payload = self.get()
        self.assertEqual(status, 200, payload)
        self.assertIn("items", payload)
        self.assertIn("total", payload)


if __name__ == "__main__":
    unittest.main()
