"""Additive integrity overlay for Apps Script legacy evidence v2 alignment."""

import hashlib
import json
import os
from pathlib import Path
import re
import unittest


MANIFEST = Path("validation/local_release_20261109/legacy_reconciliation_evidence_v2.json")
MANIFEST_SHA256 = "7694d1c0a720702a71d6a5a9ee380381298b8bd1aecab6ff32838d5fd56a03d5"
TEST_FILE = "test_legacy_reconciliation_evidence_v2_integrity.py"
REQUEST_ID = "592128d9837d4b71bbeb330ef8aabf4b"
FINGERPRINT = "816c6424279bff220878b0c4"
GOLDEN_EVIDENCE_DIGEST = "fZMBd2VUbFFwRrZ67z4ODWzcoSA2yWVOPw8jAFEGmss"


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
        if (candidate / "google_writer_execution.py").is_file():
            return candidate
    raise RuntimeError("Cannot locate legacy reconciliation evidence source root")


class LegacyReconciliationEvidenceV2IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.root = root_path()

    def test_active_apps_script_profile_and_golden_digest_are_exact(self):
        source = canonical((self.root / "scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxExecution.gs").read_bytes()).decode("utf-8")
        node_test = canonical((self.root / "scripts/pqm-google-writer/mirror-alignment/sandbox/legacy-reconciliation-evidence-v2.test.cjs").read_bytes()).decode("utf-8")
        self.assertIn(FINGERPRINT, source)
        self.assertIn(REQUEST_ID, source)
        self.assertIn("evidence_version:2", source)
        self.assertIn("full_matches:25,partial_rows:0", source)
        self.assertIn("partial_operation_numbers:[],partial_columns:{I:0}", source)
        self.assertIn("RETIRED_INVALID_DATE_NORMALIZATION_EVIDENCE", source)
        self.assertIn("full_matches:20", source)
        self.assertIn("partial_rows:5", source)
        self.assertIn(GOLDEN_EVIDENCE_DIGEST, node_test)
        self.assertIn("resumeAuthorized:false", source)
        self.assertIn("nextAction:'NEW_PREVIEW_REQUIRED'", source)

    def test_overlay_pins_current_v2_sources_and_preserves_historical_manifests(self):
        manifest_path = self.root / MANIFEST
        if not manifest_path.is_file():
            self.skipTest("candidate disposable regression copy omits the additive overlay manifest; CI runs this overlay at checkout root")
        raw = canonical(manifest_path.read_bytes())
        self.assertEqual(hashlib.sha256(raw).hexdigest(), MANIFEST_SHA256)
        manifest = json.loads(raw.decode("utf-8"))
        self.assertEqual(manifest["contract"], "pqm-sandbox-legacy-reconciliation-apps-script-evidence-v2")
        self.assertEqual(manifest["version"], 1)
        self.assertEqual(manifest["request_id"], REQUEST_ID)
        self.assertEqual(manifest["fingerprint"], FINGERPRINT)
        self.assertEqual(set(manifest["files"]), set(manifest["scope"]))
        for relative, expected in manifest["files"].items():
            content = (self.root / relative).read_bytes()
            normalized = canonical_self(content) if relative == TEST_FILE else canonical(content)
            with self.subTest(path=relative):
                self.assertEqual(hashlib.sha256(normalized).hexdigest(), expected)
        for relative, expected in manifest["preserved_manifests"].items():
            with self.subTest(preserved_manifest=relative):
                self.assertEqual(hashlib.sha256(canonical((self.root / relative).read_bytes())).hexdigest(), expected)


if __name__ == "__main__":
    unittest.main()
