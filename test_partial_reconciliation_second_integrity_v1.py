"""Additive pins for second-run partial reconciliation; historical contracts stay immutable."""
import hashlib
import json
import os
from pathlib import Path
import re
import unittest


MANIFEST = Path("validation/local_release_20260911/partial_reconciliation_second_run_v1.json")
MANIFEST_SHA256 = "700ebf70c46e00c4f6487dbd0b6120b9fbc06a6c8e5dbd64faa2fba23ee010e3"
TEST_FILE = "test_partial_reconciliation_second_integrity_v1.py"


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
    raise RuntimeError("Cannot locate second reconciliation integrity root")


class SecondPartialReconciliationIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.root = root_path()
        self.manifest_bytes = canonical((self.root / MANIFEST).read_bytes())
        self.manifest = json.loads(self.manifest_bytes.decode("utf-8"))

    def test_additive_manifest_scope_and_preserved_history(self):
        self.assertEqual(hashlib.sha256(self.manifest_bytes).hexdigest(), MANIFEST_SHA256)
        self.assertEqual(self.manifest["contract"], "pqm-sandbox-partial-reconciliation-second-run")
        self.assertEqual(self.manifest["version"], 1)
        self.assertEqual(self.manifest["baseline"], "95bcbd0a4fffe40f65e8d4e03426612d3a1eeb87")
        self.assertEqual(hashlib.sha256(canonical_self((self.root / TEST_FILE).read_bytes())).hexdigest(),
                         self.manifest["integrity_test_sha256_lf"])
        self.assertEqual(set(self.manifest["files"]), set(self.manifest["expected_file_scope"]))
        for relative, expected in self.manifest["files"].items():
            data = canonical_self((self.root / relative).read_bytes()) if relative == TEST_FILE else canonical((self.root / relative).read_bytes())
            with self.subTest(path=relative):
                self.assertEqual(hashlib.sha256(data).hexdigest(), expected)
        for relative, expected in self.manifest["preserved_manifests"].items():
            with self.subTest(historical_manifest=relative):
                self.assertEqual(hashlib.sha256(canonical((self.root / relative).read_bytes())).hexdigest(), expected)
        for relative, expected in self.manifest["preserved_sources"].items():
            with self.subTest(preserved_source=relative):
                self.assertEqual(hashlib.sha256(canonical((self.root / relative).read_bytes())).hexdigest(), expected)

    def test_second_run_profile_is_separate_and_first_history_is_retained(self):
        source = canonical((self.root / "google_writer_execution.py").read_bytes()).decode("utf-8")
        self.assertIn("9be34ff2df1e661346176eeb", source)
        self.assertIn("18a4aba10c1c13ab3bf59f56", source)
        self.assertIn("UNVERIFIED_NO_HISTORIC_PLAN", source)
        self.assertIn("verified_append_by_tab", source)
        self.assertIn("blank_sheet_source_precision_state", source)
        self.assertIn("evidence_digest", source)
        first = source.split("_PARTIAL_RECONCILIATION_SECOND_FINGERPRINT", 1)[0]
        self.assertIn("_PARTIAL_RECONCILIATION_FIRST_FINGERPRINT", first)
        contract = (self.root / "execution_apply_contract.py").read_text(encoding="utf-8")
        self.assertIn("CHECKPOINT_APPLY_ENVIRONMENTS = frozenset({'SANDBOX'})", contract)
        self.assertIn("return environment in CHECKPOINT_APPLY_ENVIRONMENTS", contract)
        self.assertIn("reconciled_partial", source)

    def test_mutated_sources_are_rejected(self):
        for relative, expected in self.manifest["files"].items():
            original = (self.root / relative).read_bytes()
            data = canonical_self(original) if relative == TEST_FILE else canonical(original)
            mutations = (bytes([data[0] ^ 1]) + data[1:], data + b"\x00", data[:-1])
            for mutation in mutations:
                with self.subTest(path=relative, length=len(mutation)):
                    self.assertNotEqual(hashlib.sha256(mutation).hexdigest(), expected)


if __name__ == "__main__":
    unittest.main()
