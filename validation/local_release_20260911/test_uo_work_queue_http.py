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
        query = urllib.parse.urlencode(params or {}, doseq=True)
        url = f"http://127.0.0.1:{self.http.server_port}/api/uo-work-queue"
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

    @staticmethod
    def _total(items):
        return sum(int(item.get("total", 0)) for item in items)

    def test_application_statistics_without_entity_type_returns_success(self):
        status, payload = self.get({"summary": "application-statistics"})
        self.assertEqual(status, 200, payload)
        self.assertEqual(self._total(payload["items"]), 5)

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
        status, payload = self.get({
            "summary": "application-statistics", "entity_type": "not-a-supported-type",
        })
        self.assertEqual(status, 400, payload)
        self.assertEqual(payload["error"], "Невідомий тип постачальника")

    def test_existing_work_queue_route_without_summary_remains_available(self):
        status, payload = self.get()
        self.assertEqual(status, 200, payload)
        self.assertIn("items", payload)
        self.assertIn("total", payload)


if __name__ == "__main__":
    unittest.main()
