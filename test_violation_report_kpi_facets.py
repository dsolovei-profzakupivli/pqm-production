"""Symmetric appeals KPI facets on a disposable synthetic DB only."""
from contextlib import closing
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
import gc
from unittest.mock import patch
from zoneinfo import ZoneInfo

import server
import validation.local_release_20260911.test_formed_protocols as protocol_fixture


class ViolationReportKpiFacetTests(unittest.TestCase):
    def setUp(self):
        self.temp_parent = tempfile.TemporaryDirectory(
            dir=Path(__file__).resolve().parent, ignore_cleanup_errors=True)
        self.addCleanup(self.temp_parent.cleanup)
        self.fixture = protocol_fixture.FormedProtocolTests()
        with patch("tempfile.tempdir", self.temp_parent.name):
            self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.addCleanup(gc.collect)
        rows = [
            # authority, status, reason, date, description, supplier
            ("A", "pending", "r1", "2026-10-01", "needle", "111"),
            ("A", "pending", "r1", "2026-10-02", "needle", "111"),
            ("A", "satisfied", "r1", "2026-10-03", "needle", "111"),
            ("A", "declined", "r2", "2026-10-04", "other", "222"),
            ("A", "answered", "r2", "2026-10-05", "needle", "111"),
            ("A", "draft", "r2", "2026-10-06", "other", "222"),
            ("A", "cancelled", "r2", "2026-10-07", "other", "222"),
            ("B", "pending", "r1", "2026-10-01", "needle", "111"),
            ("B", "satisfied", "r1", "2026-10-03", "needle", "111"),
            ("B", "declined", "r2", "2026-10-04", "other", "222"),
            ("B", "answered", "r2", "2026-10-05", "needle", "111"),
            ("B", "draft", "r2", "2026-10-06", "other", "222"),
            ("B", "cancelled", "r2", "2026-10-07", "other", "222"),
            ("B", "future_status", "r2", "2026-10-08", "other", "222"),
        ]
        with closing(server.db()) as con:
            with con:
                for i, (authority, status, reason, published, description, supplier) in enumerate(rows):
                    con.execute("""INSERT INTO violation_reports
                      (id,report_id,status,date_published,authority_name,authority_code,reason,
                       description,defendant_code,raw_json,synced_at)
                      VALUES(?,?,?,?,?,?,?,?,?,'{}','fixture')""",
                      (f"r{i}", f"R-{i}-{description}", status, published,
                       f"Authority {authority}", authority, reason, description, supplier))

    @staticmethod
    def query(**filters):
        return server.list_violation_reports({key: [str(value)] for key, value in filters.items()})

    def test_facets_cross_filter_each_other_and_keep_additional_statuses_in_total(self):
        all_rows = self.query()
        self.assertEqual(14, all_rows["total"])
        self.assertEqual((3, 2, 2), (all_rows["pending"], all_rows["satisfied"], all_rows["declined"]))
        self.assertEqual({"A": 7, "B": 7}, {x["authority_code"]: x["count"] for x in all_rows["authorities"]})

        admin_a = self.query(authority_code="A")
        self.assertEqual(7, admin_a["total"])
        self.assertEqual((2, 1, 1), (admin_a["pending"], admin_a["satisfied"], admin_a["declined"]))
        self.assertEqual({"A": 7, "B": 7}, {x["authority_code"]: x["count"] for x in admin_a["authorities"]})
        # answered/draft/cancelled are also part of the total, but have no dedicated KPI.
        self.assertEqual(3, admin_a["total"] - admin_a["pending"] - admin_a["satisfied"] - admin_a["declined"])

        decision_pending = self.query(status="pending")
        self.assertEqual(3, decision_pending["total"])
        self.assertEqual((3, 2, 2), (decision_pending["pending"], decision_pending["satisfied"], decision_pending["declined"]))
        self.assertEqual({"A": 2, "B": 1}, {x["authority_code"]: x["count"] for x in decision_pending["authorities"]})

        both = self.query(authority_code="A", status="pending")
        self.assertEqual(2, both["total"])
        self.assertEqual((2, 1, 1), (both["pending"], both["satisfied"], both["declined"]))
        self.assertEqual({"A": 2, "B": 1}, {x["authority_code"]: x["count"] for x in both["authorities"]})

    def test_shared_search_reason_date_and_supplier_filters_apply_to_both_facets(self):
        data = self.query(search="needle", reason="r1", date_from="2026-10-02",
                          date_to="2026-10-03", supplier_code="111",
                          authority_code="A", status="satisfied")
        self.assertEqual(1, data["total"])
        self.assertEqual(["R-2-needle"], [item["report_id"] for item in data["items"]])
        self.assertEqual((1, 1, 0), (data["pending"], data["satisfied"], data["declined"]))
        self.assertEqual({"A": 1, "B": 1}, {x["authority_code"]: x["count"] for x in data["authorities"]})

    def test_facets_are_independent_of_pagination(self):
        first = self.query(page=1, size=10)
        second = self.query(page=2, size=10)
        self.assertEqual(14, first["total"])
        self.assertEqual(14, second["total"])
        self.assertEqual((3, 2, 2), (first["pending"], first["satisfied"], first["declined"]))
        self.assertEqual((3, 2, 2), (second["pending"], second["satisfied"], second["declined"]))
        self.assertEqual({"A": 7, "B": 7}, {x["authority_code"]: x["count"] for x in first["authorities"]})
        self.assertEqual(first["authorities"], second["authorities"])
        self.assertNotEqual([x["id"] for x in first["items"]], [x["id"] for x in second["items"]])

    def test_response_expired_remains_a_shared_filter(self):
        with closing(server.db()) as con:
            with con:
                con.execute("""INSERT INTO violation_reports
                  (id,report_id,status,date_published,authority_name,authority_code,reason,
                   description,defendant_code,defendant_period_end,raw_json,synced_at)
                  VALUES('expired','R-EXPIRED','pending','2026-10-02','PQM','40996564',
                    'r1','needle','111','2026-10-15','{}','fixture')""")
        moment = datetime(2026, 10, 18, 12, tzinfo=ZoneInfo("Europe/Kyiv"))
        with patch.object(server, "datetime", wraps=datetime) as clock:
            clock.now.return_value = moment
            data = self.query(response_expired="1", authority_code="40996564")
        self.assertEqual(1, data["total"])
        self.assertEqual((1, 0, 0), (data["pending"], data["satisfied"], data["declined"]))
        self.assertEqual(["R-EXPIRED"], [item["report_id"] for item in data["items"]])

    def test_response_contract_sort_order_and_pagination_boundaries(self):
        first = self.query(page=1, size=10)
        second = self.query(page=2, size=10)
        self.assertEqual({"items", "total", "pending", "satisfied", "declined", "page", "size",
                          "pages", "statuses", "reasons", "authorities", "sync"}, set(first))
        self.assertEqual((14, 10, 2, 1), (first["total"], len(first["items"]), first["pages"], first["page"]))
        self.assertEqual((14, 4, 2, 2), (second["total"], len(second["items"]), second["pages"], second["page"]))
        self.assertEqual(["answered", "cancelled", "declined", "draft", "future_status", "pending", "satisfied"], first["statuses"])
        self.assertEqual(["r1", "r2"], first["reasons"])
        self.assertIsInstance(first["sync"], dict)
        self.assertTrue({"id", "report_id", "status", "date_published", "authority_code", "reason",
                         "defendant_code", "evidence_documents", "decision_documents", "defendant_statements",
                         "blocking_marker", "protocol_summary"} <= set(first["items"][0]))

        observed_desc = [(item["date_published"], item["report_id"]) for item in first["items"]]
        self.assertEqual([
            ("2026-10-08", "R-13-other"), ("2026-10-07", "R-6-other"),
            ("2026-10-07", "R-12-other"), ("2026-10-06", "R-5-other"),
            ("2026-10-06", "R-11-other"), ("2026-10-05", "R-4-needle"),
            ("2026-10-05", "R-10-needle"), ("2026-10-04", "R-9-other"),
            ("2026-10-04", "R-3-other"), ("2026-10-03", "R-8-needle"),
        ], observed_desc)
        pending = self.query(status="pending", size=10)
        self.assertEqual(["R-0-needle", "R-7-needle", "R-1-needle"], [item["report_id"] for item in pending["items"]])

        clamped = self.query(page=0, size=1)
        self.assertEqual((1, 10, 2, 10), (clamped["page"], clamped["size"], clamped["pages"], len(clamped["items"])))
        capped = self.query(page=1, size=999)
        self.assertEqual((200, 14), (capped["size"], len(capped["items"])))

    def test_unclassified_statuses_remain_in_facets_and_totals(self):
        answered = self.query(status="answered")
        self.assertEqual(2, answered["total"])
        # Decision KPIs omit their own selected-status facet, by design.
        self.assertEqual((3, 2, 2), (answered["pending"], answered["satisfied"], answered["declined"]))
        self.assertEqual({"A": 1, "B": 1}, {item["authority_code"]: item["count"] for item in answered["authorities"]})
        all_rows = self.query()
        self.assertEqual(14, all_rows["total"])
        self.assertEqual(7, all_rows["total"] - all_rows["pending"] - all_rows["satisfied"] - all_rows["declined"])

    def test_malformed_pagination_values_raise_without_changing_query_behavior(self):
        with self.assertRaises(ValueError):
            self.query(page="not-an-integer")
        with self.assertRaises(ValueError):
            self.query(size="not-an-integer")

    def test_read_authorization_and_http_route_remain_outside_allowlisted_function(self):
        self.assertEqual("appeals.read", server.auth_access.permission_key("GET", "/api/violation-reports"))
        source = Path(server.__file__).read_text(encoding="utf-8")
        self.assertIn('if parsed.path == "/api/violation-reports":', source)
        self.assertIn("return self.send_json(list_violation_reports(urllib.parse.parse_qs(parsed.query)))", source)
        self.assertIn("if not self.auth_access['active'] or (permission and not self.auth_access['permissions'].get(permission, False)):", source)


if __name__ == "__main__":
    unittest.main()
