"""Additive integrity contract for the Sandbox durable receipt-recovery patch."""

import hashlib
import json
import os
from pathlib import Path
import re
import unittest
import zipfile


MANIFEST = Path("validation/local_release_20261108/google_writer_receipt_recovery_v1.json")
MANIFEST_SHA256 = "1bf602126203ed397c120e24ab3883b0831015bc7cee97d05ecdba78273371ad"
TEST_FILE = "test_google_writer_receipt_recovery_integrity_v1.py"
V1_MANIFEST = "validation/local_release_20261107/partial_reconciliation_prepared_retry_v1.json"
V1_FIXTURE = "validation/fixtures/prepared_append_only_retry_v1_exact_d386586.zip"


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
    raise RuntimeError("Cannot locate receipt-recovery integrity root")


class GoogleWriterReceiptRecoveryIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.root = root_path()
        raw = canonical((self.root / MANIFEST).read_bytes())
        self.manifest = json.loads(raw.decode("utf-8"))
        self.assertEqual(hashlib.sha256(raw).hexdigest(), MANIFEST_SHA256)

    def test_additive_overlay_pins_current_scope_and_preserves_history(self):
        self.assertEqual(self.manifest["contract"], "pqm-sandbox-google-writer-receipt-recovery")
        self.assertEqual(self.manifest["version"], 1)
        self.assertEqual(self.manifest["baseline"], "2c11e43af185d6ea77316ffc2ca6697220dfe0e8")
        self.assertEqual(self.manifest["normalization"], "CRLF-to-LF only for text files")
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

    def test_prepared_retry_v1_fixture_keeps_its_original_pins(self):
        v1 = json.loads((self.root / V1_MANIFEST).read_text(encoding="utf-8"))
        self.assertEqual(v1["baseline"], "1fd48f48b974d86c99b5371e840e73b1b45cc2ce")
        with zipfile.ZipFile(self.root / V1_FIXTURE) as archive:
            source = archive.read("google_writer_execution.py").replace(b"\r\n", b"\n")
            self.assertEqual(hashlib.sha256(source).hexdigest(),
                             v1["files"]["google_writer_execution.py"])
        self.assertEqual(hashlib.sha256(canonical((self.root / V1_MANIFEST).read_bytes())).hexdigest(),
                         self.manifest["preserved_manifests"][V1_MANIFEST])

    def test_326_append_recovery_test_covers_fourteen_pages_and_aggregate_receipt(self):
        tests = canonical((self.root / "test_google_writer_durable_append_recovery.py").read_bytes()).decode("utf-8")
        source = canonical((self.root / "google_writer_execution.py").read_bytes()).decode("utf-8")
        for required in (
            "test_326_append_pages_recover_lost_response_and_auto_continue_without_replay",
            "range(14)",
            "(14,0)",
            "self.assertEqual(result[\"counts\"][\"append\"],326)",
        ):
            with self.subTest(required=required):
                self.assertIn(required, tests)
        self.assertIn("return result", source)
        self.assertIn("verified_totals", source)

    def test_append_metadata_and_protected_update_contract_are_pinned(self):
        script = canonical((self.root / "scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxAppendApply.gs").read_bytes()).decode("utf-8")
        metadata_test = canonical((self.root / "scripts/pqm-google-writer/mirror-alignment/sandbox/durable-append-metadata.test.cjs").read_bytes()).decode("utf-8")
        self.assertIn("pqmSandboxInstallAppendServiceColumns20261108", script)
        self.assertIn("PQM_SANDBOX_APPEND_SERVICE_FIRST_COLUMN_ = 16", script)
        self.assertIn("startColumnIndex: PQM_SANDBOX_APPEND_SERVICE_FIRST_COLUMN_", script)
        self.assertIn("Europe/Kyiv", script)
        self.assertIn("startColumnIndex === 16", metadata_test)
        self.assertIn("endColumnIndex === 19", metadata_test)
        self.assertIn("column P is untouched", metadata_test)
        self.assertIn("UPDATE entries cannot be passed", metadata_test)


if __name__ == "__main__":
    unittest.main()
