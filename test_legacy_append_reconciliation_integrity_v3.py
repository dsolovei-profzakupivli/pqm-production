"""Additive integrity contract for the corrected 25+0 legacy reconciliation profile."""

import hashlib
import json
import os
from pathlib import Path
import re
import unittest


MANIFEST = Path("validation/local_release_20261108/legacy_append_reconciliation_v3.json")
MANIFEST_SHA256 = "d5c1b6d44d24e18076a2f95e2ab803476731719982f27d92e81de0a584235890"
TEST_FILE = "test_legacy_append_reconciliation_integrity_v3.py"


def canonical(data):
    return data.replace(b"\r\n", b"\n")


def canonical_self(data):
    return re.sub(rb'(?m)^MANIFEST_SHA256 = "(?:<manifest-sha256>|[0-9a-f]{64})"$',
                  b'MANIFEST_SHA256 = "<manifest-sha256>"', canonical(data))


def root_path():
    configured = os.environ.get("PQM_RELEASE_SOURCE_ROOT")
    if configured:
        return Path(configured).resolve()
    here = Path(__file__).resolve()
    for candidate in (here.parent, *here.parents):
        if (candidate / MANIFEST).is_file() and (candidate / "google_writer_execution.py").is_file():
            return candidate
    raise RuntimeError("Cannot locate corrected legacy reconciliation integrity root")


class LegacyAppendReconciliationIntegrityV3Tests(unittest.TestCase):
    def setUp(self):
        self.root = root_path()
        raw = canonical((self.root / MANIFEST).read_bytes())
        self.manifest = json.loads(raw.decode("utf-8"))
        self.assertEqual(hashlib.sha256(raw).hexdigest(), MANIFEST_SHA256)

    def test_v3_pins_the_additive_profile_without_mutating_v1_or_v2(self):
        self.assertEqual(self.manifest["contract"], "pqm-sandbox-legacy-append-reconciliation-date-normalization-correction")
        self.assertEqual(self.manifest["version"], 3)
        self.assertEqual(self.manifest["baseline"], "628484eb15933cc7c2bf73d470c22e5787a99b54")
        self.assertEqual(set(self.manifest["files"]), set(self.manifest["scope"]))
        for relative, expected in self.manifest["files"].items():
            raw = (self.root / relative).read_bytes()
            normalized = (canonical_self(raw) if relative == TEST_FILE else
                          raw if relative.endswith(".zip") else canonical(raw))
            with self.subTest(path=relative):
                self.assertEqual(hashlib.sha256(normalized).hexdigest(), expected)
        for relative, expected in self.manifest["preserved_manifests"].items():
            with self.subTest(preserved_manifest=relative):
                self.assertEqual(hashlib.sha256(canonical((self.root / relative).read_bytes())).hexdigest(), expected)
        for relative, expected in self.manifest.get("preserved_artifacts", {}).items():
            with self.subTest(preserved_artifact=relative):
                self.assertEqual(hashlib.sha256((self.root / relative).read_bytes()).hexdigest(), expected)

    def test_historical_20_plus_5_is_retired_and_active_profile_is_exact_25_plus_0(self):
        source = canonical((self.root / "google_writer_execution.py").read_bytes()).decode("utf-8")
        app_script = canonical((self.root / "scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxExecution.gs").read_bytes()).decode("utf-8")
        python_tests = canonical((self.root / "test_partial_reconciliation_legacy_20261108.py").read_bytes()).decode("utf-8")
        node_tests = canonical((self.root / "scripts/pqm-google-writer/mirror-alignment/sandbox/partial-reconciliation.test.cjs").read_bytes()).decode("utf-8")
        runner = canonical((self.root / "validation/run_local_release.py").read_bytes()).decode("utf-8")
        transport_tests = canonical((self.root / "test_sandbox_execution_transport.py").read_bytes()).decode("utf-8")

        for required in (
            "816c6424279bff220878b0c4", "592128d9837d4b71bbeb330ef8aabf4b",
            "RETIRED_INVALID_DATE_NORMALIZATION_EVIDENCE",
            "'full_matches': 20", "'partial_rows': 5", "'partial_columns': {'I': 5}",
            "'evidence_version': 2", "'full_matches': 25", "'partial_rows': 0",
            "'partial_columns': {'I': 0}", "FULL_FIRST_CHUNK_MATCH_NO_REAPPEND_NEW_PREVIEW_REQUIRED",
            "'expected_i_mismatch_operations': []", "'resumeAuthorized': False",
            "'nextAction': 'NEW_PREVIEW_REQUIRED'",
        ):
            with self.subTest(python_source=required):
                self.assertIn(required, source)
        for required in (
            "PQM_SANDBOX_PARTIAL_RECONCILIATION_LEGACY_20261108_V1_STATUS_",
            "RETIRED_INVALID_DATE_NORMALIZATION_EVIDENCE",
            "evidence_version:1", "full_matches:20", "partial_rows:5", "partial_columns:{I:5}",
            "evidence_version:2", "full_matches:25", "partial_rows:0", "partial_columns:{I:0}",
            "FULL_FIRST_CHUNK_MATCH_NO_REAPPEND_NEW_PREVIEW_REQUIRED",
            "resumeAuthorized:false", "nextAction:'NEW_PREVIEW_REQUIRED'",
        ):
            with self.subTest(app_script=required):
                self.assertIn(required, app_script)
        for required in (
            "test_v1_20_plus_5_evidence_is_retired_and_v2_25_plus_0_is_active",
            "test_v1_receipt_counts_cannot_finalize_the_active_v2_intent",
            "test_date_i_mismatch_and_other_cell_mismatch_still_fail_closed",
            "test_dmy_datetime_date_only_and_serial_comparison_preserve_precision",
        ):
            with self.subTest(python_test=required):
                self.assertIn(required, python_tests)
        for required in (
            "legacy v2 audit records 25 full matches and closes the hold without APPEND or Resume",
            "legacy v1 20+5 evidence is retained only as retired history and is rejected for execution",
            "assert.equal(f.spreadsheetWrites,0)", "assert.equal(f.dailySyncCalls,0)",
        ):
            with self.subTest(node_test=required):
                self.assertIn(required, node_tests)
        for required in (
            "def test_legacy_326_profile_is_allowlisted_only_for_its_exact_reconciliation(self):",
            "self.assertEqual(result['counts']['fully_matching_rows'],25)",
            "self.assertEqual(result['counts']['partial_rows'],0)",
            "self.assertEqual(result['counts']['unverified_column_i_rows'],0)",
            "def test_arbitrary_fingerprint_is_rejected_before_network_even_for_registered_profile(self):",
        ):
            with self.subTest(transport_test=required):
                self.assertIn(required, transport_tests)
        for required in (
            "test_legacy_append_reconciliation_integrity_v2",
            "run_legacy_append_reconciliation_v2_history.py",
            "legacy_append_reconciliation_v2_exact_98eb5d5.zip",
        ):
            with self.subTest(history_runner=required):
                self.assertIn(required, runner)


if __name__ == "__main__":
    unittest.main()
