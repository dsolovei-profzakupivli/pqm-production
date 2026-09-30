import unittest
import sqlite3
import tempfile
from contextlib import contextmanager, closing
from pathlib import Path
from unittest.mock import patch

import winner_decisions


def award(award_id, status, supplier="22222222", lot=None, notice=None):
    item = {"id": award_id, "status": status, "qualified": status in {"active", "cancelled"},
            "suppliers": [{"identifier": {"id": supplier}}]}
    if status == "cancelled":
        item["date"] = "2026-09-23T11:39:00+03:00"
    if lot:
        item["lotID"] = lot
    if notice:
        item["documents"] = [{"id": award_id + "-notice", "documentType": "notice",
                              "datePublished": notice, "url": "https://example.test/" + award_id}]
    return item


class WinnerDecisionsTests(unittest.TestCase):
    def setUp(self):
        self.report = {"id": "report-1", "tender_id": "tender-1",
                       "defendant_code": "22222222", "date_created": "2026-09-23T12:00:00+03:00"}

    def test_control_case_notice_date_survives_cancellation(self):
        tender = {"awards": [
            {**award("first", "cancelled", notice="2026-09-21T09:28:37+03:00"),
             "qualified": True, "period": {"startDate": "2026-09-18T10:00:05+03:00"}},
            award("second", "unsuccessful", notice="2026-09-23T11:42:00+03:00"),
        ]}
        result = winner_decisions.historical_decision(tender, self.report, snapshot_at="capture")
        self.assertEqual(result["decision_date"], "2026-09-21")
        self.assertIsNone(result["decision_datetime"])
        self.assertEqual(result["precision"], "date")
        self.assertTrue(result["later_cancelled"])
        self.assertEqual(result["evidence_document"]["id"], "first-notice")
        self.assertFalse(winner_decisions.current_winner_state(tender, self.report)["active_winner"])

    def test_no_notice_does_not_turn_period_start_into_decision(self):
        tender = {"awards": [{**award("first", "active"),
                              "period": {"startDate": "2026-09-18T10:00:05+03:00"}}]}
        self.assertIsNone(winner_decisions.historical_decision(tender, self.report, snapshot_at="capture"))

    def test_electronic_protocol_links_bind_to_exact_awards_and_notice_times(self):
        tender_id = "30bc165d549d4ad3bb4855280e515f01"
        first = "070af0f3ed7a4edabd5b3f002f1f5129"
        rejected = "81ee0d85d179456f8e324d1bb5f160b1"
        first_notice = {"id": "d791e3400de349cdbea2e74f1688f7c9",
                        "documentType": "notice",
                        "datePublished": "2026-09-21T09:28:37.604079+03:00"}
        rejected_notice = {"id": "6a1f256ac2e643b38eb3d34dd84e22d0",
                           "documentType": "notice",
                           "datePublished": "2026-09-23T11:42:49.560567+03:00"}
        winner_url = winner_decisions.electronic_protocol_url(
            tender_id, first, first_notice, decision="winner")
        rejection_url = winner_decisions.electronic_protocol_url(
            tender_id, rejected, rejected_notice, decision="rejection")
        self.assertEqual(winner_url,
            "https://prozorro.gov.ua/pdf/determining_winner_of_procurement?"
            "dateModified=2026-09-21T09%253A28%253A37.604079%252B03%253A00&"
            "url=https%253A%252F%252Fpublic-api.prozorro.gov.ua%252Fapi%252F2.5%252F"
            f"tenders%252F{tender_id}%252Fawards%252F{first}")
        self.assertEqual(rejection_url,
            "https://prozorro.gov.ua/pdf/tender_rejection_protocol?"
            "dateModified=2026-09-23T11%253A42%253A49.560567%252B03%253A00&"
            "url=https%253A%252F%252Fpublic-api.prozorro.gov.ua%252Fapi%252F2.5%252F"
            f"tenders%252F{tender_id}%252Fawards%252F{rejected}")
        revised_notice = {**first_notice,
                          "dateModified": "2026-09-21T09:29:01.000000+03:00"}
        self.assertIn("dateModified=2026-09-21T09%253A29%253A01.000000%252B03%253A00",
                      winner_decisions.electronic_protocol_url(
                          tender_id, first, revised_notice, decision="winner"))
        for bad_notice in ({}, {"id": "sig", "type": "notice", "date_published": "2026-09-21"},
                           {"id": "pdf", "type": "rejectionProtocol",
                            "date_published": "2026-09-21T09:28:37+03:00"}):
            self.assertEqual(winner_decisions.electronic_protocol_url(
                tender_id, first, bad_notice, decision="winner"), "")
        self.assertEqual(winner_decisions.electronic_protocol_url(
            tender_id, "other-award", first_notice, decision="winner"), "")

    def test_context_displays_publication_time_but_deadlines_use_decision_day(self):
        import server
        tender_id = "30bc165d549d4ad3bb4855280e515f01"
        first = "070af0f3ed7a4edabd5b3f002f1f5129"
        rejected = "81ee0d85d179456f8e324d1bb5f160b1"
        winner = award(first, "cancelled", supplier="3434910316",
                       notice="2026-09-21T09:28:37.604079+03:00")
        winner["documents"][0]["id"] = "d791e3400de349cdbea2e74f1688f7c9"
        winner["period"] = {"startDate": "2026-09-18T10:00:05+03:00"}
        rejection = award(rejected, "unsuccessful", supplier="3434910316",
                          notice="2026-09-23T11:42:49.560567+03:00")
        rejection["qualified"] = False
        report = {"id": "", "tender_id": tender_id, "defendant_code": "3434910316",
                  "date_created": "2026-09-23T11:44:00+03:00", "reason": "signingRefusal"}
        with patch.object(server, "api_get", return_value={"data": {
                "tenderID": "UA-2026-09-15-012926-a", "awards": [winner, rejection],
                "tenderPeriod": {"endDate": "2026-09-18T10:00:00+03:00"},
                "contracts": [], "items": []}}):
            context = server.build_procurement_context(report)
        self.assertEqual(context["winner_selected_at"],
                         "2026-09-21T09:28:37.604079+03:00")
        self.assertEqual(context["historical_winner_decision"]["decision_date"],
                         "2026-09-21")
        self.assertIsNone(context["historical_winner_decision"]["decision_datetime"])
        self.assertEqual(context["written_refusal_deadline"], "2026-09-24")
        self.assertEqual(context["day_5"], "2026-09-26")
        self.assertFalse(context["active_winner"])
        self.assertIn(first, context["winner_notice_url"])
        self.assertIn(rejected, context["rejection_decision_url"])

    def test_same_day_cancellation_needs_ordered_timestamps(self):
        previous = award("first", "cancelled", notice="2026-09-21T09:28:37+03:00")
        previous["date"] = "2026-09-21T11:39:00+03:00"
        self.assertEqual(winner_decisions.historical_decision(
            {"awards": [previous]}, self.report, snapshot_at="capture")["decision_date"],
            "2026-09-21")
        previous["date"] = "2026-09-21T09:00:00+03:00"
        self.assertIsNone(winner_decisions.historical_decision(
            {"awards": [previous]}, self.report, snapshot_at="capture"))

    def test_repeated_active_is_separate_decision_and_unsuccessful_is_not(self):
        tender = {"awards": [award("first", "cancelled", notice="2026-09-20"),
                             award("rejected", "unsuccessful", notice="2026-09-21"),
                             award("again", "active", notice="2026-09-22")]}
        result = winner_decisions.historical_decision(tender, self.report, snapshot_at="capture")
        self.assertEqual(result["award_id"], "again")
        self.assertTrue(winner_decisions.current_winner_state(tender, self.report)["active_winner"])

    def test_supplier_and_lot_isolation(self):
        tender = {"awards": [award("right", "active", lot="lot-1", notice="2026-09-21"),
                             award("other-lot", "active", lot="lot-2", notice="2026-09-22"),
                             award("other-supplier", "active", "33333333", "lot-1", "2026-09-23")]}
        self.assertIsNone(winner_decisions.historical_decision(tender, self.report, snapshot_at="capture"))
        result = winner_decisions.historical_decision(
            tender, {**self.report, "lot_id": "lot-1"}, snapshot_at="capture")
        self.assertEqual(result["award_id"], "right")

    def test_context_deadlines_use_notice_date_not_award_review_start(self):
        import server
        tender = {"tenderID": "UA-TEST", "awards": [{
            **award("first", "active", notice="2026-09-21T09:28:37+03:00"),
            "period": {"startDate": "2026-09-18T10:00:05+03:00"},
        }], "contracts": [], "items": []}
        report = {**self.report, "id": "", "report_id": "UA-D-TEST",
                  "date_published": "2026-09-23T12:00:00+03:00"}
        with patch.object(server, "api_get", return_value={"data": tender}):
            context = server.build_procurement_context(report)
        self.assertEqual(context["winner_selected_at"], "2026-09-21")
        self.assertEqual(context["written_refusal_deadline"], "2026-09-24")
        self.assertEqual(context["day_5"], "2026-09-26")
        self.assertTrue(context["current_winner_state"]["active_winner"])
        control = server.violation_deadline_control({"date_published": report["date_published"],
                                                    "defendant_period_end": "2026-09-28"})
        self.assertEqual(control["admin_deadline"], server._add_working_days(
            server._parse_prozorro_date(report["date_published"]), 10))

    def test_persisted_snapshot_is_not_replaced_by_later_award(self):
        import server
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "winner.sqlite3"
            with closing(sqlite3.connect(path)) as connection:
                with connection:
                    connection.execute("""CREATE TABLE violation_winner_decision_snapshots
                      (report_id TEXT PRIMARY KEY, decision_json TEXT, created_at TEXT NOT NULL)""")
                    connection.execute("INSERT INTO violation_winner_decision_snapshots VALUES ('report-1',NULL,'created')")
            @contextmanager
            def local_db():
                connection = sqlite3.connect(path)
                connection.row_factory = sqlite3.Row
                try:
                    with connection:
                        yield connection
                finally:
                    connection.close()
            first = {"awards": [award("first", "active", notice="2026-09-21")]}
            later = {"awards": [award("first", "cancelled", notice="2026-09-21"),
                                award("again", "active", notice="2026-09-22")]}
            with patch.object(server, "db", local_db):
                initial = server._report_winner_decision(self.report, first)
                frozen = server._report_winner_decision(self.report, later)
            self.assertEqual(initial["award_id"], "first")
            self.assertEqual(frozen["award_id"], "first")
            self.assertEqual(frozen["decision_date"], "2026-09-21")
            self.assertTrue(frozen["later_cancelled"])

    def test_read_path_snapshot_write_attests_each_destination(self):
        import server
        import sandbox_runtime
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            owned = data / "pqm_sandbox.sqlite3"
            prod = data / "pqm_prod.sqlite3"
            unknown = data / "unknown.sqlite3"
            failed = data / "failed.sqlite3"
            for target in (owned, prod, unknown, failed):
                with closing(sqlite3.connect(target)) as connection:
                    connection.execute("""CREATE TABLE violation_winner_decision_snapshots
                      (report_id TEXT PRIMARY KEY, decision_json TEXT, created_at TEXT NOT NULL)""")
                    connection.execute("INSERT INTO violation_winner_decision_snapshots VALUES ('report-1',NULL,'created')")
                    connection.commit()

            def local_db():
                connection = sqlite3.connect(server.DB_PATH)
                connection.row_factory = sqlite3.Row
                return connection

            tender = {"awards": [award("first", "active", notice="2026-09-21")],
                      "contracts": [], "items": []}
            with patch.object(server, "SANDBOX_MODE", True), \
                 patch.object(server, "db", side_effect=local_db), \
                 patch.object(server, "api_get", return_value={"data": tender}), \
                 patch.object(sandbox_runtime, "validate_environment",
                              return_value=(data, owned, "fixture")), \
                 patch.object(sandbox_runtime, "_verify_existing"):
                with patch.object(server, "DB_PATH", owned):
                    context = server.build_procurement_context(self.report)
                    self.assertEqual(context["winner_selected_at"], "2026-09-21")
                with closing(sqlite3.connect(owned)) as connection:
                    self.assertIsNotNone(connection.execute(
                        "SELECT decision_json FROM violation_winner_decision_snapshots").fetchone()[0])
                for target in (prod, unknown):
                    with self.subTest(target=target), patch.object(server, "DB_PATH", target):
                        with self.assertRaises(RuntimeError):
                            server.build_procurement_context(self.report)
                    with closing(sqlite3.connect(target)) as connection:
                        self.assertIsNone(connection.execute(
                            "SELECT decision_json FROM violation_winner_decision_snapshots").fetchone()[0])
                with patch.object(server, "DB_PATH", failed), \
                     patch.object(sandbox_runtime, "attest_internal_target",
                                  side_effect=RuntimeError("attestation failed")):
                    with self.assertRaisesRegex(RuntimeError, "attestation failed"):
                        server.build_procurement_context(self.report)
                with closing(sqlite3.connect(failed)) as connection:
                    self.assertIsNone(connection.execute(
                        "SELECT decision_json FROM violation_winner_decision_snapshots").fetchone()[0])

    def test_existing_report_without_eligibility_marker_is_not_backfilled(self):
        import server
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "old.sqlite3"
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("""CREATE TABLE violation_winner_decision_snapshots
                  (report_id TEXT PRIMARY KEY, decision_json TEXT, created_at TEXT NOT NULL)""")
                connection.commit()
            @contextmanager
            def local_db():
                connection = sqlite3.connect(path)
                connection.row_factory = sqlite3.Row
                try:
                    with connection:
                        yield connection
                finally:
                    connection.close()
            with patch.object(server, "db", local_db):
                decision = server._report_winner_decision(
                    self.report, {"awards": [award("first", "active", notice="2026-09-21")]})
            self.assertEqual(decision["decision_date"], "2026-09-21")
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(connection.execute(
                    "SELECT COUNT(*) FROM violation_winner_decision_snapshots").fetchone()[0], 0)

    def test_public_request_route_matches_existing_pqm_and_known_ua_d(self):
        import server
        self.assertEqual(
            server.violation_request_public_url(
                "UA-2026-03-09-002732-a-b1", "UA-D-2026-04-13-000004"),
            "https://prozorro.gov.ua/uk/contract/UA-2026-03-09-002732-a-b1/"
            "violation-reports#report-UA-D-2026-04-13-000004",
        )
        self.assertEqual(server.violation_request_public_url("", "UA-D-2026-04-13-000004"), "")

    def test_only_exact_award_readable_protocol_is_linkable(self):
        sign = {"id": "sig", "documentType": "notice", "title": "sign.p7s",
                "url": "https://example.test/sign", "datePublished": "2026-09-21"}
        readable = {"id": "pdf", "documentType": "evaluationReports", "title": "Протокол рішення.pdf",
                    "url": "https://example.test/protocol", "datePublished": "2026-09-21"}
        first = award("winner", "active", notice="2026-09-21")
        first["documents"] = [sign, readable]
        decision = winner_decisions.historical_decision(
            {"awards": [first, award("other", "active", "33333333", notice="2026-09-22")]},
            self.report, snapshot_at="capture")
        self.assertEqual(decision["evidence_document"]["id"], "sig")
        self.assertEqual(decision["protocol_document"]["id"], "pdf")
        self.assertIsNone(winner_decisions.protocol_document({"documents": [sign]}))

    def test_rejection_document_binding_fails_closed_when_ambiguous(self):
        first = {**award("r1", "unsuccessful"), "qualified": False,
                 "date": "2026-09-22T10:00:00+03:00"}
        later = {**award("r2", "unsuccessful"), "qualified": False,
                 "date": "2026-09-23T11:42:00+03:00"}
        self.assertIsNone(winner_decisions.relevant_rejection(
            {"awards": [first, later]}, self.report))
        self.assertEqual(winner_decisions.relevant_rejection(
            {"awards": [first, later]}, {**self.report, "rejection_award_id": "r1"})["id"], "r1")
        self.assertEqual(winner_decisions.relevant_rejection(
            {"awards": [first, later]}, {**self.report,
                                          "date_created": "2026-09-22T12:00:00+03:00"})["id"], "r1")


if __name__ == "__main__":
    unittest.main()
