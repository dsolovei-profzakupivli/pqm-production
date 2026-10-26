import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import server


class ViolationScenarioContextCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.old_db = server.DB_PATH
        server.DB_PATH = Path(self.temp.name) / "scenario-cache.sqlite3"
        server.init_db()
        self.report = {
            "id": "synthetic-scenario-report",
            "violationReportID": "UA-D-2026-10-26-000001",
            "status": "pending",
            "dateCreated": "2026-10-20T09:00:00+03:00",
            "datePublished": "2026-10-20T10:00:00+03:00",
            "dateModified": "2026-10-20T10:00:00+03:00",
            "tender_id": "synthetic-tender",
            "author": {"identifier": {"id": "11111111"}, "name": "Замовник"},
            "defendants": [{"identifier": {"id": "22222222"}, "name": "Постачальник"}],
            "authority": {"identifier": {"id": "40996564"}, "name": "Адміністратор"},
            "defendantStatements": [],
            "details": {"reason": "contractBreach", "description": "Синтетичне звернення"},
            "decisions": [],
        }
        with patch.object(server, "_resolve_violation_tender", return_value=("UA-TEST", "")):
            server.save_violation_report(self.report)
        with server.db() as con:
            con.execute("""INSERT INTO violation_report_reviews
                (report_id,review_status,decision_justification,updated_at,updated_by)
                VALUES (?,?,?,?,?)""", ("synthetic-scenario-report", "in_review",
                "Збережене синтетичне обґрунтування", "2026-10-26T09:00:00+03:00", "Тест"))

    def tearDown(self):
        server.DB_PATH = self.old_db
        self.temp.cleanup()

    def _stored_inputs(self):
        with server.db() as con:
            report = dict(con.execute("SELECT * FROM violation_reports WHERE id=?",
                                      ("synthetic-scenario-report",)).fetchone())
            review = dict(con.execute("SELECT * FROM violation_report_reviews WHERE report_id=?",
                                      ("synthetic-scenario-report",)).fetchone())
        return report, review

    def _context(self, modified=None, observed=None):
        observed = observed or time_ns()
        modified = modified or (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        return {
            "rejection_ambiguous": False,
            "rejected_before_deadline": False,
            "rejection_present": False,
            "contract_deadline_expired": True,
            "day_5_shifted": False,
            "performance_security_required": False,
            "_scenario_context_metadata": {
                "source_updated_at": modified,
                "observed_at_ns": observed,
            },
        }

    def test_detail_context_is_cached_and_list_reuses_it_without_network_or_writes(self):
        report, review = self._stored_inputs()
        context = self._context()
        saved = server._save_violation_scenario_context_snapshot(report, review, context)
        self.assertIsNotNone(saved)
        self.assertEqual(saved["rejection_present"], False)
        with server.db() as con:
            legacy_before = {
                table: [tuple(row) for row in con.execute(f"SELECT * FROM {table} ORDER BY rowid")]
                for table in ("violation_reports", "violation_report_reviews",
                              "violation_report_review_events", "violation_winner_decision_snapshots")
            }
        server.init_db()
        with server.db() as con:
            self.assertEqual([row[1] for row in con.execute(
                "PRAGMA table_info(violation_scenario_context_snapshots)")], [
                "report_id", "snapshot_version", "report_external_id", "reason", "tender_id",
                "input_fingerprint", "source_updated_at", "source_updated_at_ns", "observed_at_ns",
                "captured_at", "context_hash", "context_json",
            ])
            legacy_after = {
                table: [tuple(row) for row in con.execute(f"SELECT * FROM {table} ORDER BY rowid")]
                for table in legacy_before
            }
        self.assertEqual(legacy_after, legacy_before, "Additive migration must preserve historical appeal data")
        with server.db() as con:
            before = {
                table: [tuple(row) for row in con.execute(f"SELECT * FROM {table} ORDER BY rowid")]
                for table in ("violation_scenario_context_snapshots", "violation_report_reviews",
                              "violation_report_review_events", "violation_winner_decision_snapshots")
            }
        with patch.object(server, "api_get", side_effect=AssertionError("list API must not call Prozorro")):
            result = server.list_violation_reports({"page": ["1"], "size": ["10"]})
        item = next(value for value in result["items"] if value["id"] == "synthetic-scenario-report")
        self.assertEqual(item["scenario_summary"],
            "Сценарій: строк, визначений п. 66 Порядку № 822, сплив; відхилення не зафіксовано; "
            "забезпечення виконання договору — не вимагається; пояснення постачальника — відсутні; "
            "ЦКУ — не застосовується.")
        self.assertEqual(item["decision_justification"], "Збережене синтетичне обґрунтування")
        with server.db() as con:
            after = {
                table: [tuple(row) for row in con.execute(f"SELECT * FROM {table} ORDER BY rowid")]
                for table in before
            }
        self.assertEqual(after, before, "List read must not write reviews, snapshots, or history")

    def test_reopening_is_idempotent_and_stale_context_cannot_replace_newer_context(self):
        report, review = self._stored_inputs()
        now = datetime.now(timezone.utc)
        newest = self._context((now - timedelta(hours=1)).isoformat())
        candidate = server._scenario_context_from_card(report, review, newest)
        self.assertIsNotNone(candidate)
        raw_report = dict(report)
        raw_report["defendant_statements"] = json.loads(raw_report["raw_json"]).get("defendantStatements") or []
        self.assertEqual(candidate["input_fingerprint"],
                         server._scenario_report_fingerprint(raw_report, server._review_dict(review)))
        server._save_violation_scenario_context_snapshot(report, review, newest)
        with server.db() as con:
            first_observed = con.execute(
                "SELECT observed_at_ns FROM violation_scenario_context_snapshots WHERE report_id=?",
                ("synthetic-scenario-report",)).fetchone()[0]
        repeated = server._save_violation_scenario_context_snapshot(report, review, newest)
        self.assertIsNotNone(repeated)
        with server.db() as con:
            current_row = dict(con.execute("SELECT * FROM violation_scenario_context_snapshots WHERE report_id=?",
                                           ("synthetic-scenario-report",)).fetchone())
        self.assertEqual(current_row["observed_at_ns"], first_observed)
        self.assertIsNotNone(server._validated_scenario_context_snapshot(current_row, report, review))
        older = self._context((now - timedelta(hours=2)).isoformat(), observed=first_observed)
        older_candidate = server._scenario_context_from_card(report, review, older)
        self.assertIsNotNone(older_candidate)
        retained = server._save_violation_scenario_context_snapshot(report, review, older)
        self.assertEqual(retained["rejection_present"], False)
        with server.db() as con:
            row = dict(con.execute("SELECT * FROM violation_scenario_context_snapshots WHERE report_id=?",
                                   ("synthetic-scenario-report",)).fetchone())
        self.assertEqual(row["source_updated_at"], (now - timedelta(hours=1)).isoformat())
        self.assertEqual(row["observed_at_ns"], first_observed)

    def test_fingerprint_mismatch_and_invalid_identity_do_not_expose_cached_scenario(self):
        report, review = self._stored_inputs()
        context = self._context()
        self.assertIsNotNone(server._save_violation_scenario_context_snapshot(report, review, context))
        changed = dict(report, date_modified="2026-10-21T10:00:00+03:00")
        with server.db() as con:
            row = dict(con.execute("SELECT * FROM violation_scenario_context_snapshots WHERE report_id=?",
                                   ("synthetic-scenario-report",)).fetchone())
        self.assertIsNone(server._validated_scenario_context_snapshot(row, changed, review))
        wrong_external_id = dict(report, report_id="not-a-UA-D-id")
        self.assertIsNone(server._scenario_context_from_card(wrong_external_id, review, context))


def time_ns():
    return int(datetime.now(timezone.utc).timestamp() * 1_000_000_000)


if __name__ == "__main__":
    unittest.main()
