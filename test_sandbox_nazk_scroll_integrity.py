"""Additive exact integrity coverage for the bounded NAZK scroll fix."""
import tempfile
import unittest
from pathlib import Path

from validation.local_release_20260911 import sandbox_protocol_integrity_variant as integrity

ROOT = integrity.ROOT


class NazkScrollIntegrityTests(unittest.TestCase):
    def test_scroll_variant_is_additive_and_old_contracts_remain_registered(self):
        contracts = integrity.load_contracts()
        current = next(c for c in contracts if c["variant_id"] == integrity.STABILIZATION_VARIANT_ID)
        scroll = next(c for c in contracts if c["variant_id"] == integrity.SCROLL_VARIANT_ID)
        appeals = next(c for c in contracts if c["variant_id"] == integrity.APPEALS_API_VARIANT_ID)
        integrated = next(c for c in contracts if c["variant_id"] == integrity.INTEGRATED_VARIANT_ID)
        self.assertEqual(current["variant_id"], integrity.STABILIZATION_VARIANT_ID)
        self.assertEqual(current["baseline_sha"], integrity.SCROLL_BASELINE)
        self.assertEqual(set(scroll["product_files"]), set(integrated["product_files"]) |
                         integrity.SCROLL_PRODUCTS)
        self.assertEqual(set(appeals["product_files"]), set(integrated["product_files"]) |
                         integrity.APPEALS_API_PRODUCT_OVERRIDES | integrity.APPEALS_API_PRODUCT_ADDITIONS)
        self.assertEqual(set(current["product_files"]), set(integrated["product_files"]) |
                         integrity.SCROLL_PRODUCTS | integrity.APPEALS_API_PRODUCT_OVERRIDES |
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
        self.assertTrue(integrity.manifest_tree_matches(current))
        self.assertTrue(integrity.exact_variant_tree_matches())
        self.assertFalse(integrity.manifest_tree_matches(integrated))
        self.assertFalse(integrity.manifest_tree_matches(scroll))
        self.assertFalse(integrity.manifest_tree_matches(appeals))
        self.assertTrue(integrity.INTEGRATED_CONTRACT.is_file())
        self.assertTrue(integrity.PREVIEW_CONTRACT.is_file())

    def test_scroll_product_mutations_are_rejected_without_relaxing_other_guards(self):
        current = next(c for c in integrity.load_contracts()
                       if c["variant_id"] == integrity.STABILIZATION_VARIANT_ID)
        all_paths = set().union(*(set(current[key]) for key in
                                  ("product_files", "protected_files", "guarded_files")))
        with tempfile.TemporaryDirectory(dir=ROOT / "validation") as directory:
            tree = Path(directory)
            for relative in all_paths:
                target = tree / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / relative).read_bytes())
            self.assertTrue(integrity.manifest_tree_matches(current, tree))
            for relative in sorted(integrity.SCROLL_PRODUCTS):
                with self.subTest(path=relative):
                    target = tree / relative
                    original = target.read_bytes()
                    changed = bytearray(original)
                    changed[0] ^= 1
                    target.write_bytes(changed)
                    self.assertFalse(integrity.manifest_tree_matches(current, tree))
                    target.write_bytes(original)
                    self.assertTrue(integrity.manifest_tree_matches(current, tree))

    def test_table_widths_dom_stability_and_other_task_modules_stay_at_integrated_bytes(self):
        current = next(c for c in integrity.load_contracts()
                       if c["variant_id"] == integrity.STABILIZATION_VARIANT_ID)
        for relative in ("table_widths_ui.js", "app.js", "operational_tasks.py",
                         "nazk_workflow.py", "scheduler_runtime.py"):
            with self.subTest(path=relative):
                self.assertEqual(
                    integrity.sha256(integrity.canonical_content(relative, (ROOT / relative).read_bytes())),
                    current["product_files"].get(relative, current["guarded_files"].get(relative,
                        current["protected_files"].get(relative, {}))).get("sha256"),
                )
        self.assertEqual(integrity.sha256(integrity.canonical_content("server.py", (ROOT / "server.py").read_bytes())),
                         current["product_files"]["server.py"]["sha256"])


if __name__ == "__main__":
    unittest.main()
