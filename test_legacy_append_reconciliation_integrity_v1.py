"""Additive integrity contract for the 2026-11-08 legacy APPEND_ONLY profile."""
import hashlib
import json
import os
from pathlib import Path
import re
import unittest


MANIFEST = Path("validation/local_release_20261108/legacy_append_reconciliation_v1.json")
MANIFEST_SHA256 = "38f379c6df6798a41918708ef82a59f946c151120062a83d56fd4b372105740c"
TEST_FILE = "test_legacy_append_reconciliation_integrity_v1.py"


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
    raise RuntimeError("Cannot locate legacy APPEND_ONLY integrity root")


class LegacyAppendOnlyReconciliationIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.root = root_path()
        raw = canonical((self.root / MANIFEST).read_bytes())
        self.manifest = json.loads(raw.decode("utf-8"))
        self.assertEqual(hashlib.sha256(raw).hexdigest(), MANIFEST_SHA256)

    def test_additive_overlay_pins_profile_code_and_keeps_older_manifests_immutable(self):
        self.assertEqual(self.manifest["contract"], "pqm-sandbox-legacy-append-reconciliation")
        self.assertEqual(self.manifest["version"], 1)
        self.assertEqual(self.manifest["baseline"], "24554fefbfed9caf998c9ea142ce6dc7284f45cc")
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

    def test_fixed_evidence_and_regressions_keep_the_five_i_dates_unverified(self):
        source = canonical((self.root / "google_writer_execution.py").read_bytes()).decode("utf-8")
        app_script = canonical((self.root / "scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxExecution.gs").read_bytes()).decode("utf-8")
        tests = canonical((self.root / "test_partial_reconciliation_legacy_20261108.py").read_bytes()).decode("utf-8")
        for required in (
            "816c6424279bff220878b0c4", "592128d9837d4b71bbeb330ef8aabf4b",
            "'append': 326, 'update': 2, 'conflict': 2",
            "'full_matches': 20", "'partial_rows': 5", "'partial_columns': {'I': 5}",
            "'checkpointPresent': False", "'resumeAuthorized': False",
            "'nextAction': 'NEW_PREVIEW_REQUIRED'",
        ):
            with self.subTest(required=required):
                self.assertIn(required, source)
        for required in (
            "PQM_SANDBOX_PARTIAL_RECONCILIATION_LEGACY_20261108_FINGERPRINT_",
            "expectedRequestId:PQM_SANDBOX_PARTIAL_RECONCILIATION_LEGACY_20261108_REQUEST_ID_",
            "partialOperationNumbers:[6,12,14,17,25]",
        ):
            with self.subTest(app_script=required):
                self.assertIn(required, app_script)
        for required in (
            "test_fixed_profile_records_20_full_5_i_unverified_and_never_authorizes_resume",
            "test_missing_duplicate_wrong_tab_formula_and_protected_changes_fail_closed",
            "test_request_id_fingerprint_digest_checkpoint_and_other_profile_are_rejected",
        ):
            with self.subTest(test=required):
                self.assertIn(required, tests)

    def test_transport_is_reconcile_only_and_sheet_preflight_is_cached_get(self):
        runtime = canonical((self.root / "sandbox_runtime.py").read_bytes()).decode("utf-8")
        server = canonical((self.root / "server.py").read_bytes()).decode("utf-8")
        tests = canonical((self.root / "test_sandbox_execution_transport.py").read_bytes()).decode("utf-8")
        self.assertIn("'816c6424279bff220878b0c4'", runtime)
        self.assertIn("action == 'reconcile_partial'", runtime)
        self.assertIn("payload.get('requestFingerprint') in allowed_reconciliation_fingerprints", runtime)
        self.assertIn("def _google_writer_legacy_cached_sheets_token", server)
        self.assertIn('method="GET"', server)
        self.assertIn("def _google_writer_legacy_live_sheet_preflight", server)
        self.assertNotIn("_google_access_token()", server[server.index("def _google_writer_legacy_cached_sheets_token"):server.index("def _google_writer_legacy_read_sheet_values")])
        self.assertIn("test_legacy_profile_fingerprint_does_not_authorize_apply_or_resume", tests)


if __name__ == "__main__":
    unittest.main()
