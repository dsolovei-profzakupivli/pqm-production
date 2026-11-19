"""Exact additive integrity contract for the combined NAZK and Appeals fixes."""
import tempfile
import unittest
from pathlib import Path

from validation.local_release_20260911 import sandbox_protocol_integrity_variant as integrity

ROOT = integrity.dst_parent_root()


class StabilizationIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.contracts = integrity.load_contracts()
        self.current = next(c for c in self.contracts
                            if c["variant_id"] == integrity.STABILIZATION_VARIANT_ID)
        self.integrated = next(c for c in self.contracts
                               if c["variant_id"] == integrity.INTEGRATED_VARIANT_ID)
        self.scroll = next(c for c in self.contracts
                           if c["variant_id"] == integrity.SCROLL_VARIANT_ID)
        self.appeals = next(c for c in self.contracts
                            if c["variant_id"] == integrity.APPEALS_API_VARIANT_ID)

    def test_manifest_composes_both_exact_children_without_rewriting_history(self):
        self.assertEqual(len(self.contracts), 35)
        self.assertEqual(self.current["baseline_sha"],
                         "fc719b07f7ce6bd43fcdf9815795f0f2906901e8")
        self.assertEqual(set(self.current["approved_scope"]) - set(self.integrated["approved_scope"]),
                         integrity.SCROLL_SCOPE | integrity.APPEALS_API_SCOPE |
                         integrity.STABILIZATION_SCOPE | integrity.STABILIZATION_V2_SCOPE |
                         integrity.STABILIZATION_V3_SCOPE | integrity.STABILIZATION_V4_SCOPE |
                         integrity.STABILIZATION_V5_SCOPE)
        expected_products = (set(self.integrated["product_files"]) | integrity.SCROLL_PRODUCTS |
                             integrity.APPEALS_API_PRODUCT_OVERRIDES |
                             integrity.APPEALS_API_PRODUCT_ADDITIONS |
                             integrity.STABILIZATION_PRODUCT_OVERRIDES |
                             integrity.STABILIZATION_PRODUCT_ADDITIONS |
                             integrity.STABILIZATION_V2_PRODUCT_OVERRIDES |
                             integrity.STABILIZATION_V2_PRODUCT_ADDITIONS |
                             integrity.STABILIZATION_V3_PRODUCT_OVERRIDES |
                             integrity.STABILIZATION_V3_PRODUCT_ADDITIONS |
                             integrity.STABILIZATION_V4_PRODUCT_OVERRIDES |
                             integrity.STABILIZATION_V4_PRODUCT_ADDITIONS |
                             integrity.STABILIZATION_V5_PRODUCT_OVERRIDES |
                             integrity.STABILIZATION_V5_PRODUCT_ADDITIONS)
        self.assertEqual(set(self.current["product_files"]), expected_products)
        self.assertFalse(integrity.manifest_tree_matches(self.integrated))
        self.assertFalse(integrity.manifest_tree_matches(self.scroll))
        self.assertFalse(integrity.manifest_tree_matches(self.appeals))
        self.assertTrue(integrity.manifest_tree_matches(self.current, ROOT))
        self.assertTrue(integrity.exact_variant_tree_matches())

    def test_every_pinned_product_guard_and_protected_byte_mutation_is_rejected(self):
        paths = set().union(*(set(self.current[key]) for key in
                              ("product_files", "protected_files", "guarded_files")))
        with tempfile.TemporaryDirectory(dir=ROOT / "validation") as temporary:
            tree = Path(temporary)
            for relative in paths:
                target = tree / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / relative).read_bytes())
            self.assertTrue(integrity.manifest_tree_matches(self.current, tree))
            for relative in sorted(paths):
                with self.subTest(path=relative):
                    target = tree / relative
                    original = target.read_bytes()
                    changed = bytearray(original)
                    if changed:
                        changed[0] ^= 1
                    else:
                        changed.extend(b"!")
                    target.write_bytes(changed)
                    self.assertFalse(integrity.manifest_tree_matches(self.current, tree))
                    target.write_bytes(original)
                    self.assertTrue(integrity.manifest_tree_matches(self.current, tree))

    def test_table_widths_and_non_scope_modules_remain_at_integrated_bytes(self):
        for relative in ("table_widths_ui.js", "operational_tasks.py", "nazk_workflow.py",
                         "scheduler_runtime.py", "halloween.js", "registry_popovers.js"):
            source = self.current if relative == "operational_tasks.py" else self.integrated
            expected = (source["product_files"].get(relative) or
                        source["guarded_files"].get(relative) or
                        source["protected_files"].get(relative))
            self.assertIsNotNone(expected, relative)
            actual = integrity.sha256(integrity.canonical_content(relative,
                                     (ROOT / relative).read_bytes()))
            self.assertEqual(actual, expected["sha256"], relative)


if __name__ == "__main__":
    unittest.main()
