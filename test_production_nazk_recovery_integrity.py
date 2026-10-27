"""Additive exact integrity contract for the Production NAZK hotfix."""
import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = ROOT / "validation/production_nazk_recovery_autoclose_v1.json"
MANIFEST_SHA256 = "bc01a5a66d7384ffddefb7347f2c4a6eb4e802a3b75aff707a920cca1536bf4d"
EXPECTED_FILES = {
    "reference_directories.py",
    "scheduler_runtime.py",
    "server.py",
    "operational_tasks.py",
    "validation/local_release_20260911/test_production_nazk_recovery.py",
    "test_production_ui_release_integrity.py",
    "test_production_scenario_projection_integrity.py",
    "validation/local_release_20260911/test_production_nazk_sync_hook.py",
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


class ProductionNazkRecoveryIntegrityTests(unittest.TestCase):
    def test_additive_manifest_is_pinned_and_historical_contracts_are_unchanged(self):
        raw = MANIFEST_PATH.read_bytes()
        self.assertEqual(hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest(), MANIFEST_SHA256)
        manifest = json.loads(raw)
        self.assertEqual(manifest["baseline"], "3eb465fad28272051478999683605e673a2bdfb1")
        self.assertEqual(set(manifest["files"]), EXPECTED_FILES)
        self.assertEqual(len(manifest["historical_integrity_sha256"]), 8)
        for name, expected in manifest["historical_integrity_sha256"].items():
            with self.subTest(historical=name):
                self.assertEqual(sha((ROOT / name).read_bytes()), expected)

    def test_product_and_regression_files_match_exact_manifest_and_mutations_fail(self):
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        self.assertEqual(set(manifest["files"]), EXPECTED_FILES)
        for name, expected in manifest["files"].items():
            data = (ROOT / name).read_bytes()
            with self.subTest(file=name):
                self.assertEqual(sha(data), expected)
                changed = bytes([data[0] ^ 1]) + data[1:]
                self.assertNotEqual(sha(changed), expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
