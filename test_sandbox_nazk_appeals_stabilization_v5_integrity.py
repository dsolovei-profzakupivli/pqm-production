"""Exact additive contract for supplier-filtered Zakupivli.Pro links."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from validation.local_release_20260911 import sandbox_protocol_integrity_variant as integrity

ROOT = integrity.dst_parent_root()


class SupplierFilteredZakupivliIntegrityTests(unittest.TestCase):
    def test_v5_is_additive_and_keeps_v4_manifest_immutable(self):
        contracts = integrity.load_contracts()
        v4 = next(item for item in contracts
                  if item["variant_id"] == integrity.STABILIZATION_V4_VARIANT_ID)
        current = next(item for item in contracts
                       if item["variant_id"] == integrity.STABILIZATION_V5_VARIANT_ID)
        raw_v4 = integrity.STABILIZATION_V4_CONTRACT.read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(hashlib.sha256(raw_v4).hexdigest(), integrity.STABILIZATION_V4_CONTRACT_SHA256)
        self.assertEqual(set(current["approved_scope"]) - set(v4["approved_scope"]),
                         integrity.STABILIZATION_V5_SCOPE)
        self.assertEqual(set(current["product_files"]), set(v4["product_files"]) |
                         integrity.STABILIZATION_V5_PRODUCT_OVERRIDES |
                         integrity.STABILIZATION_V5_PRODUCT_ADDITIONS)
        self.assertEqual(set(current["guarded_files"]), set(v4["guarded_files"]) |
                         (integrity.STABILIZATION_V5_PRODUCT_OVERRIDES & set(v4["guarded_files"])) |
                         integrity.STABILIZATION_V5_PRODUCT_ADDITIONS)
        self.assertEqual(current["variant_id"], integrity.STABILIZATION_VARIANT_ID)
        self.assertFalse(integrity.manifest_tree_matches(v4))
        self.assertTrue(integrity.manifest_tree_matches(current, ROOT))
        self.assertTrue(integrity.exact_variant_tree_matches())

    def test_link_uses_only_supplier_code_and_safe_general_list_fallback(self):
        app = (ROOT / "app.js").read_text(encoding="utf-8")
        start = app.index("function zakupivliComplaintLink(item)")
        end = app.index("\nfunction requestBlockingBadge(", start)
        helper = app[start:end]
        self.assertIn("item?.defendant_code", helper)
        self.assertNotIn("item?.id", helper)
        self.assertNotIn("item?.author_code", helper)
        self.assertIn("/complaints/list", helper)
        self.assertIn("?defendant_srn=", helper)
        self.assertIn("complaints/list',href", helper)
        self.assertIn("target=\"_blank\" rel=\"noopener noreferrer\"", helper)
        self.assertIn("Звернення щодо постачальника на Zakupivli.Pro", helper)
        self.assertIn("/assets/zakupivli-pro-mark.svg", helper)

    def test_single_byte_mutation_of_every_new_file_is_rejected(self):
        current = next(item for item in integrity.load_contracts()
                       if item["variant_id"] == integrity.STABILIZATION_V5_VARIANT_ID)
        paths = (integrity.STABILIZATION_V5_PRODUCT_OVERRIDES |
                 integrity.STABILIZATION_V5_PRODUCT_ADDITIONS)
        all_pinned = set().union(*(set(current[key]) for key in
                                   ("product_files", "protected_files", "guarded_files")))
        with tempfile.TemporaryDirectory(dir=ROOT / "validation") as temporary:
            tree = Path(temporary)
            for relative in all_pinned:
                target = tree / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / relative).read_bytes())
            self.assertTrue(integrity.manifest_tree_matches(current, tree))
            for relative in sorted(paths):
                with self.subTest(path=relative):
                    target = tree / relative
                    original = target.read_bytes()
                    changed = bytearray(original)
                    changed[0] ^= 1
                    target.write_bytes(changed)
                    self.assertFalse(integrity.manifest_tree_matches(current, tree))
                    target.write_bytes(original)
                    self.assertTrue(integrity.manifest_tree_matches(current, tree))


if __name__ == "__main__":
    unittest.main()
