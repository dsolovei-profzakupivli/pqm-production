"""Additive contract for the local writer + supplier classification integration."""
import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).parent
MANIFEST = ROOT / "google_writer_supplier_types_integration_v1.json"
PINNED_MANIFEST_SHA256 = "a7d25d3114015d0c6aa31afd429f2f9ba39721cdb1f6b60e09e9723c444b8f53"
TEXT_SUFFIXES = {".py", ".js", ".cjs", ".gs", ".html", ".css", ".json", ".md", ".sql", ".txt", ".yml", ".yaml"}


def canonical(relative, raw):
    return raw.replace(b"\r\n", b"\n") if Path(relative).suffix.lower() in TEXT_SUFFIXES else raw


def sha(relative, raw):
    return hashlib.sha256(canonical(relative, raw)).hexdigest()


class GoogleWriterSupplierTypesIntegrationIntegrity(unittest.TestCase):
    def setUp(self):
        manifest_bytes = canonical(MANIFEST.name, MANIFEST.read_bytes())
        self.assertEqual(hashlib.sha256(manifest_bytes).hexdigest(), PINNED_MANIFEST_SHA256)
        self.manifest = json.loads(manifest_bytes.decode("utf-8"))

    def test_exact_integration_tree_and_source_baselines(self):
        self.assertEqual(self.manifest["parent_baseline"], "6b9830b010ddd2339e316775572d88c630cdfb6b")
        self.assertEqual(self.manifest["source_candidates"], {
            "google_writer_update_append": "64f7fda1660c228cbe49c502c6a053fb10c19db1",
            "supplier_classification": "6b9830b010ddd2339e316775572d88c630cdfb6b",
        })
        self.assertEqual(self.manifest["integrity_test"], "test_google_writer_supplier_types_integrity.py")
        self.assertEqual(set(self.manifest["contract_files"]), {
            "google_writer_supplier_types_integration_v1.json",
            "test_google_writer_supplier_types_integrity.py"})
        self.assertEqual(set(self.manifest["changed_paths"]), set(self.manifest["files"]))
        actual = {relative: sha(relative, (ROOT / relative).read_bytes())
                  for relative in self.manifest["files"]}
        self.assertEqual(actual, self.manifest["files"])

    def test_source_integrity_overlays_are_exact_and_fail_closed(self):
        self.assertEqual(set(self.manifest["source_integrity_overlays"]), {
            "classification", "writer"})
        for overlay in self.manifest["source_integrity_overlays"].values():
            relative = overlay["fixture"]
            self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), overlay["sha256"])
            self.assertGreater(overlay["members"], 0)

    def test_all_historical_manifests_keep_their_pinned_hashes(self):
        historical = self.manifest["historical_manifests"]
        self.assertGreaterEqual(len(historical), 31)
        for relative, expected in historical.items():
            with self.subTest(path=relative):
                self.assertEqual(sha(relative, (ROOT / relative).read_bytes()), expected)

    def test_mutations_of_integrated_files_are_rejected(self):
        for relative in self.manifest["mutation_targets"]:
            raw = (ROOT / relative).read_bytes()
            expected = self.manifest["files"][relative]
            variants = (bytes([raw[0] ^ 1]) + raw[1:], raw + b"X", raw[:-1])
            for variant in variants:
                with self.subTest(path=relative, size=len(variant)):
                    self.assertNotEqual(sha(relative, variant), expected)

    def test_routing_and_protected_write_contract_are_pinned(self):
        planner = (ROOT / "scripts/pqm-google-writer/PqmGoogleBusinessMatrix.gs").read_text(encoding="utf-8")
        deps = (ROOT / "scripts/pqm-google-writer/PqmSandboxPreviewDependencies.gs").read_text(encoding="utf-8")
        classifier = (ROOT / "supplier_classification.py").read_text(encoding="utf-8")
        self.assertIn("classification_version !== 'subject-nature-20261030-v2'", planner)
        self.assertIn("item.entity_type === 'individual_entrepreneur' ? 'ФОП'", planner)
        self.assertIn("item.entity_type === 'legal_entity' ? 'ЮО'", planner)
        self.assertIn("classification_target_missing", planner)
        self.assertIn("var PQM_GOOGLE_OWNED = [1, 2, 3, 4, 5, 7, 8, 11]", deps)
        self.assertIn("var PQM_GOOGLE_APPEND_OWNED = [1, 2, 3, 4, 5, 7, 8, 11]", deps)
        self.assertIn("def classify(", classifier)
        self.assertIn("identifier_text_conflict", classifier)
        registry = (ROOT / "supplier_registry_integration.py").read_text(encoding="utf-8")
        self.assertIn('"google_writer_eligible": bool(latest_decision),', registry)


if __name__ == "__main__":
    unittest.main()
