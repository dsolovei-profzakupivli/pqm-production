"""Additive v3 guard; historical v1/v2 classification contracts stay pinned."""
import hashlib
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).parent
MANIFEST = ROOT / "supplier_classification_v3_contract.json"
PINNED_MANIFEST_SHA256 = "03a24b75896d4ed4d05dab4ab0248f77c723bf61eb76eefcac5efc3a9c64a622"
SELF_FILE = "test_supplier_classification_v3_integrity.py"
TEXT_SUFFIXES = {".py", ".js", ".cjs", ".gs", ".html", ".css", ".json", ".md", ".sql", ".txt", ".yml", ".yaml"}


def canonical(relative, raw):
    if relative == SELF_FILE:
        raw = re.sub(rb'PINNED_MANIFEST_SHA256 = "[0-9a-f]{64}"',
                     b'PINNED_MANIFEST_SHA256 = "' + b"0" * 64 + b'"', raw)
    return raw.replace(b"\r\n", b"\n") if Path(relative).suffix.lower() in TEXT_SUFFIXES else raw


def sha(relative, raw):
    return hashlib.sha256(canonical(relative, raw)).hexdigest()


class SupplierClassificationV3IntegrityTests(unittest.TestCase):
    def setUp(self):
        raw = canonical(MANIFEST.name, MANIFEST.read_bytes())
        self.assertEqual(hashlib.sha256(raw).hexdigest(), PINNED_MANIFEST_SHA256)
        self.manifest = json.loads(raw.decode("utf-8"))

    def test_exact_v3_tree_and_baseline(self):
        self.assertEqual(self.manifest["parent"], "12f5eadc63199342209af33c60a5de4f868ec566")
        actual = {relative: sha(relative, (ROOT / relative).read_bytes())
                  for relative in self.manifest["files"]}
        self.assertEqual(set(actual), set(self.manifest["files"]))
        self.assertEqual(actual, self.manifest["files"])

    def test_historical_manifests_are_byte_unchanged(self):
        for relative, expected in self.manifest["historical_manifests"].items():
            self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), expected, relative)

    def test_product_contract_versions_routing_and_write_ownership(self):
        classifier = (ROOT / "supplier_classification.py").read_text(encoding="utf-8")
        self.assertIn("VERSION = 'subject-nature-20261031-v3'", classifier)
        for relative, needle in (
            ("scripts/pqm-google-writer/PqmGoogleBusinessMatrix.gs", "item.classification_version !== 'subject-nature-20261031-v3'"),
            ("scripts/pqm-google-writer/PqmGoogleWriter.gs", "x.classification_version !== 'subject-nature-20261031-v3'"),
            ("scripts/pqm-google-writer/PqmSandboxPreviewDependencies.gs", "x.classification_version !== 'subject-nature-20261031-v3'"),
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn(needle, source)
            self.assertNotIn("subject-nature-20261030-v2'", source)
        deps = (ROOT / "scripts/pqm-google-writer/PqmSandboxPreviewDependencies.gs").read_text(encoding="utf-8")
        self.assertIn("var PQM_GOOGLE_OWNED = [1, 2, 3, 4, 5, 7, 8, 11]", deps)
        self.assertIn("var PQM_GOOGLE_APPEND_OWNED = [1, 2, 3, 4, 5, 7, 8, 11]", deps)
        matrix = (ROOT / "scripts/pqm-google-writer/PqmGoogleBusinessMatrix.gs").read_text(encoding="utf-8")
        self.assertIn("item.entity_type === 'individual_entrepreneur' ? 'ФОП'", matrix)
        self.assertIn("item.entity_type === 'legal_entity' ? 'ЮО'", matrix)

    def test_semantic_mutations_are_rejected(self):
        for relative in self.manifest["mutation_targets"]:
            data = (ROOT / relative).read_bytes()
            self.assertTrue(data)
            variants = (bytes([data[0] ^ 1]) + data[1:], data + b"X", data[:-1])
            expected = self.manifest["files"][relative]
            for altered in variants:
                with self.subTest(path=relative, size=len(altered)):
                    self.assertNotEqual(sha(relative, altered), expected)


if __name__ == "__main__":
    unittest.main()
