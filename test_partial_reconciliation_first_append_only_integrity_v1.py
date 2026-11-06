"""Additive integrity contract for the first APPEND_ONLY audit-only reconciliation."""
import hashlib
import json
import os
from pathlib import Path
import re
import unittest


MANIFEST = Path("validation/local_release_20260911/partial_reconciliation_first_append_only_v1.json")
MANIFEST_SHA256 = "23354f89f8f74c620039b516534a920ce41645e491edf928dba796993f5699d3"
TEST_FILE = "test_partial_reconciliation_first_append_only_integrity_v1.py"


def canonical(data):
    return data.replace(b"\r\n", b"\n")


def canonical_self(data):
    return re.sub(rb'MANIFEST_SHA256 = "(?:<manifest-sha256>|[0-9a-f]{64})"',
                  b'MANIFEST_SHA256 = "<manifest-sha256>"', canonical(data))


def root_path():
    configured = os.environ.get("PQM_RELEASE_SOURCE_ROOT")
    if configured:
        return Path(configured).resolve()
    here = Path(__file__).resolve()
    for candidate in (here.parent, *here.parents):
        if (candidate / MANIFEST).is_file() and (candidate / "google_writer_execution.py").is_file():
            return candidate
    raise RuntimeError("Cannot locate first APPEND_ONLY reconciliation integrity root")


class FirstAppendOnlyReconciliationIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.root = root_path()
        self.manifest_bytes = canonical((self.root / MANIFEST).read_bytes())
        self.manifest = json.loads(self.manifest_bytes.decode("utf-8"))

    def test_additive_manifest_pins_exact_scope_and_preserves_historical_pins(self):
        self.assertEqual(hashlib.sha256(self.manifest_bytes).hexdigest(), MANIFEST_SHA256)
        self.assertEqual(self.manifest["contract"], "pqm-sandbox-partial-reconciliation-first-append-only")
        self.assertEqual(self.manifest["version"], 1)
        self.assertEqual(self.manifest["baseline"], "067e2e85f679b9333a854204bca1421fcd2ef426")
        self.assertEqual(self.manifest["normalization"], "CRLF-to-LF only for text files")
        scope = {
            "google_writer_execution.py",
            "scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxExecution.gs",
            "scripts/pqm-google-writer/mirror-alignment/sandbox/partial-reconciliation.test.cjs",
            "test_google_writer_partial_reconciliation.py",
            "test_partial_reconciliation_first_append_only_integrity_v1.py",
        }
        self.assertEqual(set(self.manifest["files"]), scope)
        for relative, expected in self.manifest["files"].items():
            raw = (self.root / relative).read_bytes()
            data = canonical_self(raw) if relative == TEST_FILE else canonical(raw)
            with self.subTest(path=relative):
                self.assertEqual(hashlib.sha256(data).hexdigest(), expected)
        for relative, expected in self.manifest["preserved_manifests"].items():
            with self.subTest(historical_manifest=relative):
                self.assertEqual(hashlib.sha256(canonical((self.root / relative).read_bytes())).hexdigest(), expected)

    def test_fixed_profile_matches_confirmed_uncertain_no_checkpoint_audit(self):
        import google_writer_execution as execution

        request_id = "ab1d69b6d7c6427f8abdffea35830948"
        fingerprint = execution.request_id_fingerprint(request_id)
        self.assertEqual(fingerprint, "30331b560493209210f1e507")
        profile = execution.partial_reconciliation_profile(fingerprint)
        self.assertIsNotNone(profile)
        self.assertEqual(profile["evidence"], {
            "evidence_version": 1,
            "plan_scope": "APPEND_ONLY",
            "initial_plan": {"append": 351},
            "attempted_chunk": 0,
            "checkpoint_present": False,
            "audit_type": "READ_ONLY_SAVED_PREVIEW_AND_SHEETS",
            "audit": {
                "full_matches": 25,
                "partial_or_wrong_tab": 0,
                "missing": 0,
                "duplicates": 0,
                "saved_preview_binding": "PASS",
                "writes_performed": 0,
            },
            "recovery_disposition": "AUDIT_EVIDENCE_ONLY_NEW_PREVIEW_REQUIRED",
        })
        self.assertEqual(profile["result_counts"], {
            "audit_confirmed_existing_append_rows": 25,
            "checkpoint_receipts": 0,
        })
        self.assertEqual(profile["receipt_fields"], {
            "checkpointPresent": False,
            "resumeAuthorized": False,
            "nextAction": "NEW_PREVIEW_REQUIRED",
        })
        self.assertTrue(profile["require_saved_append_only_preview"])

    def test_legacy_reconciliation_profiles_remain_separate_and_unchanged(self):
        import google_writer_execution as execution

        first = execution.partial_reconciliation_profile("9be34ff2df1e661346176eeb")
        second = execution.partial_reconciliation_profile("18a4aba10c1c13ab3bf59f56")
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(first["result_counts"], {
            "verified_append_rows": 50,
            "unverified_original_updates": 2,
            "accepted_date_only_formats": 12,
        })
        self.assertEqual(first["evidence"]["initial_plan"], {"append": 451, "update": 2, "conflict": 2})
        self.assertEqual(first["evidence"]["updates_disposition"], "RECOMPUTE_WITH_NEW_PREVIEW")
        self.assertEqual(second["evidence"]["verified_append_rows"], 50)
        self.assertEqual(second["evidence"]["verified_append_by_tab"], {"ФОП": 46, "ЮО": 4})
        self.assertEqual(second["evidence"]["duplicate_rows"], 0)
        self.assertEqual(second["evidence"]["updates_disposition"], "UNVERIFIED_NO_HISTORIC_PLAN")
        self.assertEqual(set(execution.PARTIAL_RECONCILIATION_PROFILES), {
            "9be34ff2df1e661346176eeb",
            "18a4aba10c1c13ab3bf59f56",
            "30331b560493209210f1e507",
        })

    def test_apps_script_source_and_node_regression_cover_zero_step_hold(self):
        source = canonical((self.root / "scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxExecution.gs").read_bytes()).decode("utf-8")
        node_tests = canonical((self.root / "scripts/pqm-google-writer/mirror-alignment/sandbox/partial-reconciliation.test.cjs").read_bytes()).decode("utf-8")
        self.assertIn("PQM_SANDBOX_PARTIAL_RECONCILIATION_APPEND_ONLY_FINGERPRINT_", source)
        self.assertIn("requireUncertainFirstChunk:true", source)
        self.assertIn("run.state==='uncertain'", source)
        self.assertIn("run.steps.length===0", source)
        self.assertIn("checkpointPresent:false", source)
        self.assertIn("audit_confirmed_existing_append_rows:25,checkpoint_receipts:0", node_tests)
        self.assertIn("assert.equal(f.spreadsheetWrites,0)", node_tests)
        self.assertIn("assert.equal(f.dailySyncCalls,0)", node_tests)


if __name__ == "__main__":
    unittest.main()
