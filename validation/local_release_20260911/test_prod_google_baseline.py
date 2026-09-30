"""No live Google, PROD DB, or write route is used by these tests."""
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import prod_google_baseline as baseline
import edr_sync_v2
import server


class ProdGoogleBaselineTests(unittest.TestCase):
    def test_read_only_connection_runs_real_verification_officer_projection(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "projection.sqlite3"
            with closing(sqlite3.connect(path)) as setup:
                setup.executescript("""
                  CREATE TABLE supplier_edr_verification_events(
                    id INTEGER PRIMARY KEY, supplier_code TEXT, event_type TEXT,
                    occurred_at TEXT, officer TEXT);
                  CREATE TABLE supplier_edr_profiles(
                    supplier_code TEXT, edr_checked_at TEXT, edr_officer TEXT, synced_at TEXT);
                  CREATE TABLE submissions(
                    id INTEGER PRIMARY KEY, supplier_code TEXT, date_published TEXT);
                  CREATE TABLE application_fields(
                    submission_id INTEGER, protocol_date TEXT, protocol_officer TEXT,
                    protocol_decision TEXT);
                  CREATE TABLE authorized_officers(full_name TEXT);
                  INSERT INTO authorized_officers VALUES ('Sample OFFICER');
                  INSERT INTO supplier_edr_verification_events
                    (supplier_code,event_type,occurred_at,officer)
                    VALUES ('001','legacy_google_registry','2026-09-04','sample officer');
                """)
                setup.commit()
            with closing(baseline.open_read_only(path)) as readonly:
                self.assertEqual(readonly.execute("PRAGMA query_only").fetchone()[0], 1)
                self.assertEqual(readonly.total_changes, 0)
                self.assertEqual(readonly.execute(
                    "SELECT NORMALIZE_NAME('Sample OFFICER')").fetchone()[0],
                    "sample officer")
                projection = edr_sync_v2.current_verification_projections(readonly, ["001"])
                self.assertEqual(projection["001"]["verification_date"], "2026-09-04")
                self.assertEqual(projection["001"]["verification_officer"], "Sample OFFICER")
                self.assertEqual(readonly.total_changes, 0)

    def row(self, **changes):
        value = dict(supplier_code="001", source_tab="ФОП", source_row=2,
                     e="Припинено", g="Decision", i="2026-09-04", j="2026-09-02",
                     k="Record", l="Officer", m="Google note",
                     duplicate_google_identity=False)
        value.update(changes)
        return value

    def payload(self, rows):
        return {"spreadsheet_id": "prod-registry", "source_digest": baseline.digest(rows),
                "records": rows}

    def test_spreadsheet_digest_and_bound_fail_closed(self):
        payload = self.payload([self.row()])
        with self.assertRaisesRegex(ValueError, "NOT_CONFIGURED"):
            baseline.validate(payload, {})
        with self.assertRaisesRegex(ValueError, "SPREADSHEET_ID_MISMATCH"):
            baseline.validate(payload, {baseline.SPREADSHEET_ENV: "wrong"})
        self.assertEqual(len(baseline.validate(payload, {baseline.SPREADSHEET_ENV: "prod-registry"})), 1)
        payload["source_digest"] = "tampered"
        with self.assertRaisesRegex(ValueError, "DIGEST_MISMATCH"):
            baseline.validate(payload, {baseline.SPREADSHEET_ENV: "prod-registry"})
        rows = [self.row(source_row=index + 2) for index in range(501)]
        with self.assertRaisesRegex(ValueError, "BATCH_LIMIT"):
            baseline.validate(self.payload(rows), {baseline.SPREADSHEET_ENV: "prod-registry"})

    def test_route_disabled_auth_required_and_no_write_route(self):
        for path in server.GOOGLE_MIGRATION_DISABLED_PATHS:
            self.assertNotEqual(path, baseline.PATH)
        handler = SimpleNamespace(path=baseline.PATH, command="POST", send_json=lambda data, status=200:
                                  (data, status), _authorize_supplier_registry_integration=lambda: False)
        with patch.dict(os.environ, {baseline.ENABLE_ENV: ""}):
            self.assertEqual(server.Handler._dispatch(handler, lambda: None)[1], 404)
        with patch.dict(os.environ, {baseline.ENABLE_ENV: "1"}), patch.object(server, "IS_WEB_ENV", True):
            self.assertIsNone(server.Handler._dispatch(handler, lambda: self.fail("unauthorized")))
            handler._authorize_supplier_registry_integration = lambda: True
            called = []
            server.Handler._dispatch(handler, lambda: called.append(True))
            self.assertEqual(called, [True])
            self.assertEqual(handler.auth_role, "integration")
        oversized = SimpleNamespace(path=baseline.PATH,
            headers={"Content-Length": str(baseline.MAX_BODY_BYTES + 1)},
            send_json=lambda data, status=200: (data, status))
        self.assertEqual(server.Handler._do_POST(oversized)[1], 413)

    def test_read_only_classification_and_sensitive_output(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "baseline.sqlite3"
            con = sqlite3.connect(path)
            con.executescript("""
              CREATE TABLE supplier_edr_profiles(supplier_code TEXT, source_sheet TEXT,
                termination_decision_details TEXT, termination_record_date TEXT,
                termination_record_number TEXT, edr_notes TEXT);
              CREATE TABLE submissions(supplier_code TEXT);
              CREATE TABLE supplier_registry_summary(supplier_code TEXT);
              CREATE TABLE supplier_edr_verification_events(supplier_code TEXT,event_type TEXT,
                occurred_at TEXT,officer TEXT,source TEXT,source_sheet TEXT,source_row INTEGER,
                snapshot_json TEXT);
              INSERT INTO submissions VALUES ('001'),('002'),('003'),('005'),('006'),('007'),('009'),('010'),('011');
              INSERT INTO supplier_edr_profiles VALUES ('001','ФОП','','','','');
              INSERT INTO supplier_edr_profiles VALUES ('002','ЮО','Decision','2026-09-02','Record','');
              INSERT INTO supplier_edr_profiles VALUES ('005','ФОП','','','','');
              INSERT INTO supplier_edr_profiles VALUES ('006','ФОП','','','','');
              INSERT INTO supplier_edr_profiles VALUES ('007','ФОП','','','','');
              INSERT INTO supplier_edr_profiles VALUES ('009','ФОП','','','','');
              INSERT INTO supplier_edr_profiles VALUES ('010','ФОП','','','','');
              INSERT INTO supplier_edr_profiles VALUES ('011','ФОП','','','',''),('011','ФОП','','','','');
            """)
            con.execute("INSERT INTO supplier_edr_verification_events VALUES (?,?,?,?,?,?,?,?)",
                        ("001", "legacy_google_registry", "2026-09-04", "Officer",
                         "legacy_google_registry", "ФОП", 2, "{}"))
            con.execute("INSERT INTO supplier_edr_verification_events VALUES (?,?,?,?,?,?,?,?)",
                        ("002", "manual_edr", "2026-09-04", "Officer",
                         "manual", "ЮО", 3, json.dumps({"edr_status": "Припинено"})))
            factual_snapshot = {"source": "legacy_google_registry", "verification_date": "2026-09-04",
                "verification_officer": "Officer", "source_tab": "ФОП", "source_row": 11,
                "source_digest": "a" * 64, "factual_edr_status": "Припинено",
                "factual_spreadsheet_id": "prod-registry", "factual_source_tab": "ФОП",
                "factual_source_row": 11, "factual_source_digest": "a" * 64,
                "factual_provenance_version": 1}
            con.execute("INSERT INTO supplier_edr_verification_events VALUES (?,?,?,?,?,?,?,?)",
                        ("010", "legacy_google_registry", "2026-09-04", "Officer",
                         "legacy_google_registry", "ФОП", 11, json.dumps(factual_snapshot)))
            con.commit(); con.close()
            rows = [self.row(), self.row(supplier_code="002", source_tab="ЮО", source_row=3,
                                         i="2026-09-04", g="Decision", j="2026-09-02", k="Record", m=""),
                    self.row(supplier_code="003", source_tab="ФОП", source_row=4,
                             e="Зареєстровано", i="2026-09-05", g="", j="", k="", m=""),
                    self.row(supplier_code="004", source_tab="ФОП", source_row=5,
                             e="Неактуально", i="", l="", g="", j="", k="", m=""),
                    self.row(supplier_code="005", source_row=6, e="Зареєстровано", g="", j="", k="", m=""),
                    self.row(supplier_code="006", source_row=7, e="Зареєстровано", g="", j="", k="", m=""),
                    self.row(supplier_code="007", source_row=8, e="Зареєстровано", g="", j="", k="", m=""),
                    self.row(supplier_code="008", source_row=9, e="Зареєстровано", g="", j="", k="", m="",
                             duplicate_google_identity=True),
                    self.row(supplier_code="009", source_row=10, e="Зареєстровано", g="Partial", j="", k="", m=""),
                    self.row(supplier_code="010", source_row=11, g="", j="", k="", m=""),
                    self.row(supplier_code="011", source_row=12, g="", j="", k="", m="")]
            with closing(baseline.open_read_only(path)) as readonly:
                with patch.dict(os.environ, {baseline.SPREADSHEET_ENV: "prod-registry"}), \
                     patch.object(baseline.edr_sync_v2, "canonical_prozorro_statuses",
                                  return_value={"001": "Активний", "002": "Неактивний", "003": "Активний",
                                                "005": "Активний", "006": "Активний", "007": "Активний",
                                                "009": "Активний", "010": "Активний"}), \
                     patch.object(baseline.edr_sync_v2, "active_qualification_dates", return_value={}), \
                     patch.object(baseline.edr_sync_v2, "current_verification_projections",
                                  return_value={"001": {"verification_date": "2026-09-04"},
                                                "002": {"verification_date": "2026-09-04"},
                                                "003": {"verification_date": "2026-09-01"},
                                                "005": {"verification_date": ""},
                                                "006": {"verification_date": "2026-09-04"},
                                                "007": {"verification_date": "2026-09-05"},
                                                "009": {"verification_date": "2026-09-04"},
                                                "010": {"verification_date": "2026-09-04"}}):
                    result = baseline.audit(readonly, self.payload(rows),
                                            {baseline.SPREADSHEET_ENV: "prod-registry"})
                self.assertEqual(readonly.execute("PRAGMA query_only").fetchone()[0], 1)
                with self.assertRaises(sqlite3.OperationalError):
                    readonly.execute("INSERT INTO submissions VALUES ('x')")
            self.assertEqual(result["verification"]["equivalent_event"], 3)
            self.assertEqual(result["verification"]["existing_il_only_overlap"], 1)
            self.assertEqual(result["verification"]["existing_factual_overlap"], 1)
            self.assertEqual(result["verification"]["google_newer_than_pqm"], 1)
            self.assertEqual(result["verification"]["pqm_missing_google_present"], 1)
            self.assertEqual(result["verification"]["same_date"], 2)
            self.assertEqual(result["verification"]["google_older"], 1)
            self.assertEqual(result["verification"]["planned_phase1"], 2)
            self.assertEqual(result["verification"]["duplicate_google_identity"], 1)
            self.assertEqual(result["verification"]["duplicate_pqm_identity"], 1)
            self.assertEqual(result["factual_e"]["special"]["existing_exact_factual"], 2)
            self.assertEqual(result["termination_notes"]["fields"]["g"]["google_present_pqm_missing"], 2)
            self.assertEqual(result["termination_notes"]["fields"]["g"]["exact"], 1)
            self.assertEqual(result["termination_notes"]["block"]["complete"], 2)
            self.assertEqual(result["termination_notes"]["block"]["partial"], 1)
            self.assertEqual(result["termination_notes"]["block"]["blocked_missing_profile"], 2)
            self.assertNotIn("Decision", json.dumps(result))
            self.assertNotIn("Officer", json.dumps(result))
            self.assertNotIn("Google note", json.dumps(result))
            self.assertEqual((result["db_writes"], result["google_writes"]), (0, 0))


if __name__ == "__main__":
    unittest.main()
