"""Additive source-pin contract for retrying the existing APPEND_ONLY intent."""

import hashlib
import json
import os
from pathlib import Path
import re
import unittest
import zipfile


MANIFEST = Path("validation/local_release_20261107/partial_reconciliation_prepared_retry_v1.json")
MANIFEST_SHA256 = "9af626c5970e486be10e05869e3dcd060e773819820550a30f23205987be4905"
TEST_FILE = "test_partial_reconciliation_prepared_append_only_retry_integrity_v1.py"


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
    raise RuntimeError("Cannot locate prepared APPEND_ONLY retry integrity root")


class PreparedAppendOnlyRetryIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.root = root_path()
        raw = canonical((self.root / MANIFEST).read_bytes())
        self.manifest = json.loads(raw.decode("utf-8"))
        self.assertEqual(hashlib.sha256(raw).hexdigest(), MANIFEST_SHA256)

    def test_additive_overlay_pins_retry_fix_and_preserves_prior_manifests(self):
        self.assertEqual(self.manifest["contract"], "pqm-sandbox-prepared-append-only-retry")
        self.assertEqual(self.manifest["version"], 1)
        self.assertEqual(self.manifest["baseline"], "1fd48f48b974d86c99b5371e840e73b1b45cc2ce")
        self.assertEqual(self.manifest["normalization"], "CRLF-to-LF only for text files")
        self.assertEqual(set(self.manifest["files"]), {
            "google_writer_execution.py",
            "test_google_writer_prepared_append_only_retry.py",
            TEST_FILE,
            "validation/run_local_release.py",
            "validation/run_partial_reconciliation_first_append_only_v1_history.py",
            "validation/fixtures/partial_reconciliation_first_append_only_v1_exact_1fd48f4.zip",
        })
        for relative, expected in self.manifest["files"].items():
            raw = (self.root / relative).read_bytes()
            normalized = (canonical_self(raw) if relative == TEST_FILE else
                          raw if relative.endswith(".zip") else canonical(raw))
            with self.subTest(path=relative):
                self.assertEqual(hashlib.sha256(normalized).hexdigest(), expected)
        for relative, expected in self.manifest["preserved_manifests"].items():
            with self.subTest(preserved_manifest=relative):
                self.assertEqual(hashlib.sha256(canonical((self.root / relative).read_bytes())).hexdigest(), expected)

    def test_old_first_profile_source_is_retained_in_exact_fixture(self):
        fixture_path = self.root / "validation/fixtures/partial_reconciliation_first_append_only_v1_exact_1fd48f4.zip"
        manifest_path = self.root / "validation/local_release_20260911/partial_reconciliation_first_append_only_v1.json"
        old_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        with zipfile.ZipFile(fixture_path) as archive:
            old_source = archive.read("google_writer_execution.py")
            old_apps_script = archive.read(
                "scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxExecution.gs"
            )
        self.assertEqual(hashlib.sha256(canonical(old_source)).hexdigest(),
                         old_manifest["files"]["google_writer_execution.py"])
        self.assertEqual(hashlib.sha256(canonical(old_apps_script)).hexdigest(),
                         old_manifest["files"]["scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxExecution.gs"])

    def test_retry_branch_is_strict_and_historical_overlay_runs_on_its_fixture(self):
        source = canonical((self.root / "google_writer_execution.py").read_bytes()).decode("utf-8")
        runner = canonical((self.root / "validation/run_local_release.py").read_bytes()).decode("utf-8")
        self.assertIn("require_saved_append_only_preview", source)
        self.assertIn("prior['original_result_json'] == run['result_json']", source)
        self.assertIn("prior['apps_script_receipt_json'] != '{}'", source)
        self.assertIn("prior['evidence_json']", source)
        self.assertIn("prior['request_fingerprint']", source)
        self.assertIn("test_partial_reconciliation_first_append_only_integrity_v1", runner)
        helper_copy_block = runner.split("for helper_name in (", 1)[1].split("fixture_target=", 1)[0]
        self.assertIn("'run_partial_reconciliation_first_append_only_v1_history.py'", helper_copy_block)

    def test_regression_cases_cover_http_503_retry_and_security_mismatches(self):
        tests = canonical((self.root / "test_google_writer_prepared_append_only_retry.py").read_bytes()).decode("utf-8")
        for required in (
            "test_retry_after_http_503_reuses_prepared_intent_without_new_row_or_evidence",
            "test_same_id_retry_dispatches_reconciliation_only_and_finalizes_partial",
            "test_different_reconciliation_id_cannot_reuse_prepared_intent",
            "test_different_supported_fingerprint_cannot_reuse_prepared_intent",
            "test_changed_evidence_or_evidence_digest_rejects_same_id_without_mutation",
            "test_changed_saved_preview_digest_or_scope_rejects_same_id",
            "test_changed_run_status_or_result_rejects_same_id",
            "checkpointPresent",
            "resumeAuthorized",
            "NEW_PREVIEW_REQUIRED",
        ):
            with self.subTest(required=required):
                self.assertIn(required, tests)


if __name__ == "__main__":
    unittest.main()
