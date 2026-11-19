"""Additive contract for the historical no-source-digest APPEND_ONLY profile."""

import hashlib
import json
import os
from pathlib import Path
import re
import unittest


MANIFEST = Path("validation/local_release_20261108/legacy_append_reconciliation_v2.json")
MANIFEST_SHA256 = "7aecd4a1eee8c35cbe8210336203030a2c1f1d77709e6bce5e9d01a588eb43dc"
TEST_FILE = "test_legacy_append_reconciliation_integrity_v2.py"


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
    raise RuntimeError("Cannot locate legacy source-digest absence integrity root")


class LegacyAppendOnlyReconciliationIntegrityV2Tests(unittest.TestCase):
    def setUp(self):
        self.root = root_path()
        raw = canonical((self.root / MANIFEST).read_bytes())
        self.manifest = json.loads(raw.decode("utf-8"))
        self.assertEqual(hashlib.sha256(raw).hexdigest(), MANIFEST_SHA256)

    def test_v2_pins_the_legacy_only_absence_exception_and_preserves_v1(self):
        self.assertEqual(self.manifest["contract"], "pqm-sandbox-legacy-source-digest-absence")
        self.assertEqual(self.manifest["version"], 2)
        self.assertEqual(self.manifest["baseline"], "1111eb963844245336c107d5e4d8e0b8887dfe81")
        self.assertEqual(set(self.manifest["files"]), set(self.manifest["scope"]))
        for relative, expected in self.manifest["files"].items():
            raw = (self.root / relative).read_bytes()
            normalized = canonical_self(raw) if relative == TEST_FILE else raw if relative.endswith(".zip") else canonical(raw)
            with self.subTest(path=relative):
                self.assertEqual(hashlib.sha256(normalized).hexdigest(), expected)
        for relative, expected in self.manifest["preserved_manifests"].items():
            with self.subTest(preserved_manifest=relative):
                self.assertEqual(hashlib.sha256(canonical((self.root / relative).read_bytes())).hexdigest(), expected)

    def test_only_the_fixed_legacy_profile_records_absent_source_digest(self):
        source = canonical((self.root / "google_writer_execution.py").read_bytes()).decode("utf-8")
        apps_script = canonical((self.root / "scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxExecution.gs").read_bytes()).decode("utf-8")
        regressions = canonical((self.root / "test_partial_reconciliation_legacy_20261108.py").read_bytes()).decode("utf-8")
        for required in (
            "'legacy_source_digest_absence': True",
            "'historical_schema': 'PRE_SOURCE_DIGEST'",
            "'substitute_used': False",
            "if 'source_digest' in details:",
            "if not is_canonical_sha256_b64url(details.get('source_digest')):",
            "test_only_fixed_legacy_profile_accepts_absent_source_digest",
            "test_legacy_preview_with_present_invalid_source_digest_is_rejected",
        ):
            with self.subTest(required=required):
                self.assertIn(required, source + regressions)
        self.assertIn("saved_preview_source_digest:{present:false,historical_schema:'PRE_SOURCE_DIGEST',substitute_used:false}", apps_script)


if __name__ == "__main__":
    unittest.main()
