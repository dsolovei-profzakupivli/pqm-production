"""Exact additive integrity guard for the bounded, local Appeals scenario projection."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from validation.local_release_20260911 import sandbox_protocol_integrity_variant as integrity

ROOT = integrity.ROOT


class AppealsScenarioApiIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.contracts = integrity.load_contracts()
        self.current = next(c for c in self.contracts
                            if c["variant_id"] == integrity.STABILIZATION_VARIANT_ID)
        self.appeals = next(c for c in self.contracts
                            if c["variant_id"] == integrity.APPEALS_API_VARIANT_ID)
        self.scroll = next(c for c in self.contracts
                           if c["variant_id"] == integrity.SCROLL_VARIANT_ID)
        self.integrated = next(c for c in self.contracts
                               if c["variant_id"] == integrity.INTEGRATED_VARIANT_ID)

    def test_additive_contract_is_exact_and_historical_integrated_contract_is_unchanged(self):
        self.assertEqual(len(self.contracts), 28)
        self.assertEqual(self.current["baseline_sha"], integrity.APPEALS_API_BASELINE)
        self.assertEqual(set(self.appeals["approved_scope"]) - set(self.integrated["approved_scope"]),
                         integrity.APPEALS_API_SCOPE)
        self.assertEqual(set(self.appeals["product_files"]),
                         set(self.integrated["product_files"]) |
                         integrity.APPEALS_API_PRODUCT_OVERRIDES |
                         integrity.APPEALS_API_PRODUCT_ADDITIONS)
        self.assertTrue(integrity.manifest_tree_matches(self.current))
        self.assertFalse(integrity.manifest_tree_matches(self.integrated))
        self.assertFalse(integrity.manifest_tree_matches(self.scroll))
        self.assertFalse(integrity.manifest_tree_matches(self.appeals))
        self.assertTrue(integrity.exact_variant_tree_matches())
        self.assertEqual(
            self.appeals["protected_files"]["server.py"]["personal_theme_normalized_sha256"],
            "7ddf919cc4d38cec04e2056df7c582358aa317e294dece6ce3167ff01fd8b306")
        for section in ("product_files", "guarded_files"):
            for path, old in self.integrated[section].items():
                if path not in (integrity.APPEALS_API_PRODUCT_OVERRIDES | integrity.SCROLL_PRODUCTS |
                                integrity.APPEALS_API_PRODUCT_ADDITIONS |
                                integrity.APPEALS_API_GUARD_OVERRIDES |
                                integrity.STABILIZATION_V2_PRODUCT_OVERRIDES |
                                integrity.STABILIZATION_V2_PRODUCT_ADDITIONS |
                                integrity.STABILIZATION_V3_PRODUCT_OVERRIDES |
                                integrity.STABILIZATION_V3_PRODUCT_ADDITIONS |
                                integrity.STABILIZATION_V4_PRODUCT_OVERRIDES |
                                integrity.STABILIZATION_V4_PRODUCT_ADDITIONS |
                                integrity.STABILIZATION_V5_PRODUCT_OVERRIDES |
                                integrity.STABILIZATION_V5_PRODUCT_ADDITIONS):
                    self.assertEqual(self.current[section][path], old, path)

    def test_every_added_product_byte_mutation_is_rejected(self):
        added = (integrity.APPEALS_API_PRODUCT_OVERRIDES | integrity.SCROLL_PRODUCTS |
                 integrity.APPEALS_API_PRODUCT_ADDITIONS | integrity.STABILIZATION_PRODUCT_OVERRIDES |
                 integrity.STABILIZATION_PRODUCT_ADDITIONS |
                 integrity.STABILIZATION_V2_PRODUCT_OVERRIDES |
                 integrity.STABILIZATION_V2_PRODUCT_ADDITIONS |
                 integrity.STABILIZATION_V3_PRODUCT_OVERRIDES |
                 integrity.STABILIZATION_V3_PRODUCT_ADDITIONS |
                 integrity.STABILIZATION_V4_PRODUCT_OVERRIDES |
                 integrity.STABILIZATION_V4_PRODUCT_ADDITIONS |
                 integrity.STABILIZATION_V5_PRODUCT_OVERRIDES |
                 integrity.STABILIZATION_V5_PRODUCT_ADDITIONS)
        with tempfile.TemporaryDirectory(dir=ROOT / "validation") as temporary:
            tree = Path(temporary)
            for relative in set(self.current["product_files"]) | set(self.current["guarded_files"]):
                target = tree / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / relative).read_bytes())
            self.assertTrue(integrity.manifest_tree_matches(self.current, tree))
            for relative in sorted(added):
                with self.subTest(path=relative):
                    target = tree / relative
                    original = target.read_bytes()
                    changed = bytearray(original)
                    changed[0] ^= 1
                    target.write_bytes(changed)
                    self.assertFalse(integrity.manifest_tree_matches(self.current, tree))
                    target.write_bytes(original)
                    self.assertTrue(integrity.manifest_tree_matches(self.current, tree))


if __name__ == "__main__":
    unittest.main()
