"""Version 2 current-source contract for Google Writer and EDR mirror authority."""
import hashlib
import json
import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "validation/local_release_20260911/google_writer_update_append_v2.json"
PINNED_MANIFEST_SHA256_LF = "26af0547da5fe3170f5d76b96a88da07de6c26c111a3a12ab2bdb1411700cd84"
HISTORICAL_V1_MANIFEST = ROOT / "validation/local_release_20260911/google_writer_update_append_v1.json"
HISTORICAL_V1_TEST = ROOT / "validation/local_release_20260911/test_google_writer_update_append_integrity.py"
HISTORICAL_V1_MANIFEST_SHA256_LF = "ad8df0ead516fbdc6fd1f51e9f2abca0acf2b4244c395aaad730594a868ee2d7"
TEXT_SUFFIXES = {".py", ".js", ".cjs", ".gs", ".html", ".css", ".json", ".md", ".sql", ".txt", ".yml", ".yaml"}


def canonical(relative: Path, data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n") if relative.suffix.lower() in TEXT_SUFFIXES else data


def sha256_lf(relative: Path, data: bytes) -> str:
    return hashlib.sha256(canonical(relative, data)).hexdigest()


class GoogleWriterUpdateAppendV2Integrity(unittest.TestCase):
    def setUp(self):
        raw = canonical(MANIFEST, MANIFEST.read_bytes())
        self.assertEqual(hashlib.sha256(raw).hexdigest(), PINNED_MANIFEST_SHA256_LF)
        self.manifest = json.loads(raw.decode("utf-8"))

    def test_contract_is_additive_and_pins_the_b988_current_candidate(self):
        self.assertEqual(self.manifest["baseline"], "b988f140af37c45bd5461735cf40d18cd00d741a")
        self.assertEqual(self.manifest["contract"], "pqm-google-writer-update-append")
        self.assertEqual(self.manifest["version"], 2)
        self.assertEqual(self.manifest["normalization"], "CRLF-to-LF only for text files")
        self.assertEqual(set(self.manifest), {
            "baseline", "contract", "files", "normalization", "version", "behavior", "behavior_tests",
            "history",
        })
        self.assertEqual(self.manifest["history"], {
            "v1_manifest": "validation/local_release_20260911/google_writer_update_append_v1.json",
            "v1_manifest_sha256_lf": HISTORICAL_V1_MANIFEST_SHA256_LF,
            "v1_test_sha256_lf": "fd87cd808a6ba87097b812933202cef5917cd6977777b7015966ad0fc09b312b",
            "v1_baseline": "64f7fda1660c228cbe49c502c6a053fb10c19db1",
            "v1_is_immutable": True,
        })
        v1_bytes = canonical(HISTORICAL_V1_MANIFEST, HISTORICAL_V1_MANIFEST.read_bytes())
        self.assertEqual(hashlib.sha256(v1_bytes).hexdigest(), HISTORICAL_V1_MANIFEST_SHA256_LF)
        v1 = json.loads(v1_bytes.decode("utf-8"))
        self.assertEqual(v1["baseline"], "64f7fda1660c228cbe49c502c6a053fb10c19db1")
        self.assertEqual(v1["version"], 1)
        self.assertEqual(sha256_lf(HISTORICAL_V1_TEST.relative_to(ROOT), HISTORICAL_V1_TEST.read_bytes()),
                         self.manifest["history"]["v1_test_sha256_lf"])

    def test_exact_candidate_files_match_current_pins_and_mutations_fail(self):
        files = self.manifest["files"]
        self.assertEqual(set(files), {
            "scripts/pqm-google-writer/PqmGoogleBusinessMatrix.gs",
            "scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxPreviewDependencies.gs",
            "scripts/pqm-google-writer/update-append-business-matrix.test.cjs",
            "scripts/pqm-google-writer/sandbox-full-apply.test.cjs",
            "edr_sync_v2.py",
            "supplier_registry_integration.py",
            "validation/local_release_20260911/test_edr_sync_v2.py",
            "validation/local_release_20260911/test_permanent_edr_sync_safety.py",
        })
        for name, expected in files.items():
            relative = Path(name)
            raw = (ROOT / relative).read_bytes()
            normalized = canonical(relative, raw)
            with self.subTest(path=name):
                self.assertEqual(hashlib.sha256(normalized).hexdigest(), expected["sha256_lf"])
                self.assertEqual(set(expected), {"sha256_lf"})
                for changed in (normalized + b"\0", normalized[:-1]):
                    self.assertNotEqual(hashlib.sha256(changed).hexdigest(), expected["sha256_lf"])

    def test_behavior_contract_is_complete_and_preserves_other_rules(self):
        behavior = self.manifest["behavior"]
        self.assertEqual(set(behavior), {
            "google_writer_F_authority", "google_writer_F_date_independence", "google_writer_F_unknown_status",
            "google_owned_columns", "google_owned_direction", "google_owned_blanks", "google_owned_equal_values",
            "incomplete_source", "other_columns", "conflicts_and_write_protection", "eligibility_semantics",
        })
        self.assertEqual(behavior["google_writer_F_authority"], "PQM-to-Google Sheets only")
        self.assertEqual(behavior["google_writer_F_date_independence"], True)
        self.assertEqual(behavior["google_writer_F_unknown_status"], "no write")
        self.assertEqual(behavior["google_owned_columns"], ["G", "J", "K", "M"])
        self.assertEqual(behavior["google_owned_direction"], "Google Sheets-to-PQM only")
        self.assertEqual(behavior["google_owned_blanks"], "clear only when the row and source column are confirmed present")
        self.assertEqual(behavior["google_owned_equal_values"], "no-op")
        self.assertEqual(behavior["incomplete_source"], "never clear")
        self.assertEqual(behavior["other_columns"], "retain existing verification-date priorities")
        self.assertEqual(behavior["conflicts_and_write_protection"], "retain existing blocking and protected-cell checks")
        self.assertEqual(behavior["eligibility_semantics"], "eligible exactly when a decided application event is present")
        self.assertEqual(self.manifest["behavior_tests"], {
            "google_writer": "scripts/pqm-google-writer/update-append-business-matrix.test.cjs",
            "edr_sync": [
                "validation.local_release_20260911.test_edr_sync_v2",
                "validation.local_release_20260911.test_permanent_edr_sync_safety",
            ],
            "source_shape": "validation.test_google_writer_update_append_v2_integrity.GoogleWriterUpdateAppendV2Integrity.test_unavailable_tabs_and_invalid_headers_fail_before_a_source_snapshot_exists",
            "eligibility": "validation.test_google_writer_update_append_v2_integrity.GoogleWriterUpdateAppendV2Integrity.test_writer_eligibility_is_decided_event_based",
        })

    def test_writer_eligibility_is_decided_event_based(self):
        # Use the existing isolated SQLite fixture, but assert behavior of the
        # generated registry rather than a source-code substring.
        import supplier_registry_integration as integration
        import edr_sync_v2

        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.create_function("DIGITS", 1, edr_sync_v2.normalize_code)
        con.executescript("""
          CREATE TABLE submissions(id TEXT PRIMARY KEY,supplier_code TEXT,supplier_name TEXT,date_published TEXT,
            status TEXT,raw_json TEXT,synced_at TEXT,qualification_id TEXT);
          CREATE TABLE application_fields(submission_id TEXT PRIMARY KEY,manager_name TEXT,protocol_officer TEXT,
            protocol_decision TEXT DEFAULT '',protocol_date TEXT DEFAULT '');
          CREATE TABLE qualifications(id TEXT PRIMARY KEY,submission_id TEXT,status TEXT,decision_date TEXT);
          CREATE TABLE frameworks(id TEXT PRIMARY KEY,status TEXT,raw_json TEXT);
          CREATE TABLE registry_contracts(id TEXT PRIMARY KEY,supplier_code TEXT,status TEXT,framework_id TEXT,
            qualification_id TEXT);
          CREATE TABLE supplier_registry_summary(supplier_code TEXT PRIMARY KEY,supplier_name TEXT);
          CREATE TABLE supplier_edr_profiles(supplier_code TEXT PRIMARY KEY,full_name TEXT,manager_name TEXT,
            source_sheet TEXT,edr_status TEXT DEFAULT '',edr_checked_at TEXT DEFAULT '',edr_officer TEXT DEFAULT '',
            source_row INTEGER DEFAULT 0,synced_at TEXT DEFAULT '');
          CREATE TABLE supplier_edr_verification_events(id INTEGER PRIMARY KEY,supplier_code TEXT,event_type TEXT,
            occurred_at TEXT,officer TEXT,source TEXT,source_submission_id TEXT,source_sheet TEXT,source_row INTEGER,
            created_at TEXT,snapshot_json TEXT DEFAULT '{}');
          CREATE TABLE supplier_managers(id INTEGER PRIMARY KEY,supplier_code TEXT,manager_name TEXT,is_current INTEGER,
            updated_at TEXT,created_at TEXT);
        """)
        try:
            con.execute("INSERT INTO frameworks VALUES('f','active','{}')")
            rows = [
                ("s-decided", "11111111", "DECIDED", "2026-02-01", "q-decided"),
                ("s-undecided", "22222222", "UNDECIDED", "2026-03-01", None),
            ]
            for submission_id, code, name, day, qualification_id in rows:
                con.execute("INSERT INTO submissions VALUES(?,?,?,?,?,?,?,?)",
                            (submission_id, code, name, day, "active", "{}", day, qualification_id))
                con.execute("INSERT INTO application_fields VALUES(?,?,?,?,?)",
                            (submission_id, "", "", "", ""))
                con.execute("INSERT INTO supplier_registry_summary VALUES(?,?)", (code, name))
            con.execute("INSERT INTO qualifications VALUES('q-decided','s-decided','active','2026-02-02')")
            con.commit()
            items = {item["supplier_code"]: item for item in integration._build_full_registry(con)["items"]}
            self.assertIs(items["11111111"]["google_writer_eligible"], True)
            self.assertIs(items["22222222"]["google_writer_eligible"], False)
            eligible = integration.eligible_full_registry(con)
            self.assertEqual([item["supplier_code"] for item in eligible["items"]], ["11111111"])
        finally:
            con.close()

    def test_unavailable_tabs_and_invalid_headers_fail_before_a_source_snapshot_exists(self):
        import edr_sync_v2

        with self.assertRaises(ValueError):
            edr_sync_v2.source_snapshot({"ФОП": [list(edr_sync_v2.HEADERS)]})
        malformed_headers = list(edr_sync_v2.HEADERS)
        malformed_headers[12] = "Unexpected header"
        with self.assertRaises(ValueError):
            edr_sync_v2.source_snapshot({
                "ФОП": [malformed_headers],
                "ЮО": [list(edr_sync_v2.HEADERS)],
            })

    def test_writer_behavior_suite(self):
        result = subprocess.run(
            ["node", "--test", "scripts/pqm-google-writer/update-append-business-matrix.test.cjs"],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_edr_authority_date_conflict_and_incomplete_source_suites(self):
        tests = [
            "validation.local_release_20260911.test_edr_sync_v2.EdrSyncV2Tests.test_confirmed_blank_google_mirror_values_clear_pqm_values",
            "validation.local_release_20260911.test_edr_sync_v2.EdrSyncV2Tests.test_google_owned_gjkm_values_update_independently_of_verification_date",
            "validation.local_release_20260911.test_edr_sync_v2.EdrSyncV2Tests.test_confirmed_google_blanks_clear_mirrors_even_without_a_usable_verification_date",
            "validation.local_release_20260911.test_edr_sync_v2.EdrSyncV2Tests.test_mirror_values_update_when_other_edr_changes_are_blocked_by_missing_date",
            "validation.local_release_20260911.test_edr_sync_v2.EdrSyncV2Tests.test_approved_same_timestamp_conflict_applies_only_google_owned_mirrors",
            "validation.local_release_20260911.test_edr_sync_v2.EdrSyncV2Tests.test_unapproved_row_conflict_blocks_mirror_updates",
            "validation.local_release_20260911.test_edr_sync_v2.EdrSyncV2Tests.test_equal_google_mirror_values_are_noop",
            "validation.local_release_20260911.test_edr_sync_v2.EdrSyncV2Tests.test_missing_trailing_google_mirror_columns_are_not_treated_as_blank",
            "validation.local_release_20260911.test_edr_sync_v2.EdrSyncV2Tests.test_available_mirror_columns_apply_when_another_google_column_is_missing",
            "validation.local_release_20260911.test_edr_sync_v2.EdrSyncV2Tests.test_available_mirror_value_applies_when_verification_date_column_is_unavailable",
            "validation.local_release_20260911.test_permanent_edr_sync_safety.PermanentSyncSafetyTests.test_google_full_mirror_clears_newer_blanks_and_preserves_history",
            "validation.local_release_20260911.test_permanent_edr_sync_safety.PermanentSyncSafetyTests.test_each_gjkm_field_supports_both_directions_and_preview_shows_clear",
            "validation.local_release_20260911.test_permanent_edr_sync_safety.PermanentSyncSafetyTests.test_confirmed_gjkm_blanks_clear_independently_of_verification_timestamp",
            "validation.local_release_20260911.test_permanent_edr_sync_safety.PermanentSyncSafetyTests.test_missing_m_column_is_not_interpreted_as_an_explicit_blank",
            "validation.local_release_20260911.test_permanent_edr_sync_safety.PermanentSyncSafetyTests.test_gjkm_only_can_mirror_without_verification_pair",
            "validation.local_release_20260911.test_permanent_edr_sync_safety.PermanentSyncSafetyTests.test_same_day_google_date_only_is_midnight_and_cannot_replace_later_check",
            "validation.local_release_20260911.test_permanent_edr_sync_safety.PermanentSyncSafetyTests.test_newer_date_only_google_check_updates_facts_but_stays_date_only",
            "validation.local_release_20260911.test_permanent_edr_sync_safety.PermanentSyncSafetyTests.test_equal_date_only_manager_or_status_difference_is_blocked",
            "validation.local_release_20260911.test_permanent_edr_sync_safety.PermanentSyncSafetyTests.test_malformed_google_record_date_cannot_look_like_intentional_clear",
            "validation.local_release_20260911.test_permanent_edr_sync_safety.PermanentSyncSafetyTests.test_malformed_date_blocks_without_writes",
        ]
        result = subprocess.run([sys.executable, "-m", "unittest", "-v", *tests],
                                cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
