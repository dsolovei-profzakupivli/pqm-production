"""Focused parity and file-backed snapshot-cache coverage."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import edr_sync_v2
import supplier_identity
import supplier_registry_integration as integration


class SupplierRegistryCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "registry.sqlite3"
        self.con = sqlite3.connect(self.path)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.create_function("DIGITS", 1, edr_sync_v2.normalize_code)
        self.con.executescript("""
          CREATE TABLE submissions(id TEXT PRIMARY KEY,supplier_code TEXT,supplier_name TEXT,date_published TEXT,
            status TEXT,raw_json TEXT,synced_at TEXT);
          CREATE TABLE application_fields(submission_id TEXT PRIMARY KEY,manager_name TEXT,protocol_officer TEXT,
            protocol_decision TEXT DEFAULT '',protocol_date TEXT DEFAULT '');
          CREATE TABLE qualifications(id TEXT PRIMARY KEY,submission_id TEXT,status TEXT);
          CREATE TABLE frameworks(id TEXT PRIMARY KEY,status TEXT,raw_json TEXT);
          CREATE TABLE registry_contracts(id TEXT PRIMARY KEY,supplier_code TEXT,status TEXT,framework_id TEXT);
          CREATE TABLE supplier_registry_summary(supplier_code TEXT PRIMARY KEY,supplier_name TEXT);
          CREATE TABLE supplier_edr_profiles(supplier_code TEXT PRIMARY KEY,full_name TEXT,manager_name TEXT,
            source_sheet TEXT,edr_checked_at TEXT DEFAULT '',edr_officer TEXT DEFAULT '',source_row INTEGER DEFAULT 0,
            synced_at TEXT DEFAULT '');
          CREATE TABLE supplier_edr_verification_events(id INTEGER PRIMARY KEY,supplier_code TEXT,event_type TEXT,
            occurred_at TEXT,officer TEXT,source TEXT,source_submission_id TEXT,source_sheet TEXT,source_row INTEGER,
            created_at TEXT);
          CREATE TABLE supplier_managers(id INTEGER PRIMARY KEY,supplier_code TEXT,manager_name TEXT,is_current INTEGER,
            updated_at TEXT,created_at TEXT);
        """)
        self.con.execute("INSERT INTO frameworks VALUES('f','active',?)",
                         (json.dumps({"qualificationPeriod": {"endDate": "2099-01-01"}}),))
        self.add("11111111", "OLD NAME", "2026-01-01", "s1")
        self.add("11111111", "LATEST NAME", "2026-02-01", "s2", decision="admit", officer="УО 1")
        self.add("22222222", "PROFILE FALLBACK", "2026-03-01", "s3")
        self.con.execute("INSERT INTO supplier_edr_profiles(supplier_code,full_name,source_sheet,edr_checked_at,edr_officer) VALUES(?,?,?,?,?)",
                         ("22222222", "ЕДР CURRENT NAME", "ЮО", "2026-03-04", "УО 2"))
        self.con.execute("INSERT INTO supplier_edr_verification_events(supplier_code,event_type,occurred_at,officer) VALUES(?,?,?,?)",
                         ("11111111", "manual_edr", "2026-03-05", "УО 3"))
        self.con.commit()
        integration.reset_full_registry_cache()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.con.close)

    def add(self, code, name, published, submission_id, decision="", officer=""):
        raw = json.dumps({"tenderers": [{"identifier": {"scheme": "UA-EDR"}}]})
        self.con.execute("INSERT INTO submissions VALUES(?,?,?,?,?,?,?)",
                         (submission_id, code, name, published, "active", raw, published))
        self.con.execute("INSERT INTO application_fields VALUES(?,?,?,?,?)",
                         (submission_id, "", officer, decision, ""))
        self.con.execute("INSERT OR REPLACE INTO supplier_registry_summary VALUES(?,?)", (code, name))

    def test_batch_name_helper_returns_only_verified_edr_names(self):
        codes = ["11111111", "22222222"]
        columns = {row[1] for row in self.con.execute("PRAGMA table_info(supplier_edr_profiles)")}
        names = integration._current_names(self.con, codes, columns)
        events = integration._current_verification_events(self.con, codes)
        self.assertIsNone(names["11111111"])
        self.assertEqual(names["22222222"], "ЕДР CURRENT NAME")
        for code in codes:
            self.assertEqual(events[code], edr_sync_v2.current_verification_event(self.con, code))

    def test_response_contract_and_cache_hit(self):
        with patch.object(integration, "_build_full_registry", wraps=integration._build_full_registry) as build:
            first = integration.full_registry(self.con)
            second = integration.full_registry(self.con)
        self.assertEqual(build.call_count, 1)
        self.assertEqual(first, second)
        self.assertEqual(set(first), {"generated_at", "count", "items"})
        self.assertEqual(set(first["items"][0]), {
            "supplier_code", "entity_type", "supplier_name", "current_manager_name", "prozorro_status",
            "prozorro_status_canonical", "prozorro_status_google", "monitoring_eligible", "freshness_marker",
            "last_application_date", "last_approved_application_date", "last_approved_application_uo",
            "verification_date", "verification_officer", "verification_event_type"})

    def test_file_revision_invalidates_snapshot(self):
        with patch.object(integration, "_build_full_registry", wraps=integration._build_full_registry) as build:
            integration.full_registry(self.con)
            before = integration.database_revision(self.con)
            self.con.execute("UPDATE submissions SET supplier_name='CHANGED NAME' WHERE id='s2'")
            self.con.commit()
            self.assertNotEqual(before, integration.database_revision(self.con))
            refreshed = integration.full_registry(self.con)
        self.assertEqual(build.call_count, 2)
        self.assertEqual(next(item for item in refreshed["items"] if item["supplier_code"] == "11111111")["supplier_name"], "")


if __name__ == "__main__":
    unittest.main()
