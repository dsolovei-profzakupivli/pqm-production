"""Exact integrated UI/Admin integrity contract and one-byte rejection tests."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from validation.local_release_20260911 import sandbox_protocol_integrity_variant as integrity


ROOT = integrity.ROOT


class IntegratedSandboxUiIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.contract = integrity.load_contracts()[-1]
        self.paths = set().union(*(set(self.contract[name]) for name in
                                   ("product_files", "protected_files", "guarded_files")))

    def test_exact_candidate_matches_and_historical_admin_contract_is_not_rewritten(self):
        self.assertEqual(self.contract["variant_id"], integrity.UI_CANDIDATE_V2_ID)
        self.assertEqual(self.contract["baseline_sha"], "d457aae211bc0b88cdc66414b9e5765ac7ba350d")
        raw = integrity.UI_CANDIDATE_DELTA.read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(hashlib.sha256(raw).hexdigest(), integrity.UI_CANDIDATE_DELTA_SHA256)
        self.assertTrue(integrity.manifest_tree_matches(self.contract))
        self.assertTrue(integrity.exact_variant_tree_matches())
        previous = next(c for c in integrity.load_contracts()
                        if c["variant_id"] == "sandbox-admin-officer-link-v3")
        self.assertFalse(integrity.manifest_tree_matches(previous))
        historical_v1 = next(c for c in integrity.load_contracts()
                             if c["variant_id"] == integrity.UI_CANDIDATE_ID)
        self.assertEqual(historical_v1["baseline_sha"], self.contract["baseline_sha"])
        self.assertFalse(integrity.manifest_tree_matches(historical_v1))
        for path in self.paths:
            self.assertTrue(integrity.exact_variant_file_matches(path, (ROOT / path).read_bytes()), path)

    def test_every_single_byte_product_guard_and_protected_mutation_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "validation") as temp:
            tree = Path(temp)
            for path in self.paths:
                target = tree / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / path).read_bytes())
            self.assertTrue(integrity.manifest_tree_matches(self.contract, tree))
            for path in sorted(self.paths):
                with self.subTest(path=path):
                    target = tree / path
                    original = target.read_bytes()
                    changed = bytearray(original)
                    if changed:
                        changed[0] ^= 1
                    else:
                        changed.extend(b"!")
                    target.write_bytes(changed)
                    self.assertFalse(integrity.manifest_tree_matches(self.contract, tree))
                    target.write_bytes(original)
                    self.assertTrue(integrity.manifest_tree_matches(self.contract, tree))

    def test_candidate_scope_is_exact_and_historical_manifests_are_untouched(self):
        expected = (integrity.UI_CANDIDATE_PRODUCTS | integrity.UI_CANDIDATE_V2_PRODUCT_ADDITIONS |
                    integrity.UI_CANDIDATE_V2_PRODUCT_OVERRIDES)
        self.assertEqual(set(self.contract["product_files"]), expected)
        self.assertEqual(set(self.contract["approved_scope"]) - set(
            next(c for c in integrity.load_contracts()
                 if c["variant_id"] == "sandbox-admin-officer-link-v3")["approved_scope"]),
            integrity.UI_CANDIDATE_SCOPE | integrity.UI_CANDIDATE_V2_SCOPE)
        for path in (integrity.ADMIN_HISTORY_CONTRACT, integrity.ADMIN_CONTRACT,
                     integrity.ADMIN_V3_DELTA):
            self.assertTrue(path.is_file())


if __name__ == "__main__":
    unittest.main()
