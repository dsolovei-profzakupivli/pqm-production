"""Additive exact integrity contract for the NAZK crash/lease recovery fix."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from validation.local_release_20260911 import sandbox_protocol_integrity_variant as guard

ROOT = guard.ROOT


class SandboxNazkRecoveryIntegrityTests(unittest.TestCase):
    def test_recovery_variant_is_additive_and_keeps_dst_v1_immutable(self):
        contracts = guard.load_contracts()
        dst_v1 = next(item for item in contracts if item["variant_id"] == guard.DST_VARIANT_ID)
        current = next(item for item in contracts if item["variant_id"] == guard.DST_RECOVERY_VARIANT_ID)
        self.assertEqual(current["baseline_sha"], "94c5e37693ef2855aaf9bc848ca2af1b3965cb25")
        self.assertEqual(set(current["approved_scope"]) - set(dst_v1["approved_scope"]),
                         guard.DST_RECOVERY_SCOPE)
        self.assertTrue(guard.manifest_tree_matches(current, guard.dst_recovery_v2_root()))
        self.assertFalse(guard.manifest_tree_matches(dst_v1))
        stabilization_v5 = next(item for item in contracts
                                if item["variant_id"] == guard.STABILIZATION_V5_VARIANT_ID)
        self.assertTrue(guard.manifest_tree_matches(stabilization_v5, guard.dst_parent_root()))
        raw = guard.DST_RECOVERY_CONTRACT.read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(hashlib.sha256(raw).hexdigest(), guard.DST_RECOVERY_CONTRACT_SHA256)
        self.assertEqual(current["product_files"]["table_widths_ui.js"],
                         dst_v1["product_files"]["table_widths_ui.js"])

    def test_one_byte_mutation_of_recovery_delta_is_rejected(self):
        current = guard.load_contracts()[-1]
        paths = (guard.DST_RECOVERY_QUALIFICATION_PRODUCT_OVERRIDES |
                 guard.DST_RECOVERY_QUALIFICATION_PRODUCT_ADDITIONS |
                 guard.DST_RECOVERY_QUALIFICATION_GUARDED_ADDITIONS |
                 guard.DST_RECOVERY_QUALIFICATION_TEST_FIX_FILES |
                 guard.DST_RECOVERY_QUALIFICATION_TEST_FIX_GUARDED_ADDITIONS |
                 {"validation/docker_release_gate.py",
                  "validation/local_release_20260911/sandbox_protocol_integrity_variant.py",
                  "test_sandbox_dst_hotfix_integrity.py",
                  "test_sandbox_appeals_scenario_api_integrity.py",
                  "test_sandbox_nazk_appeals_stabilization_integrity.py",
                  "test_sandbox_nazk_preview_integrity.py",
                  "test_sandbox_nazk_recovery_integrity.py"})
        with tempfile.TemporaryDirectory(dir=ROOT / "validation") as temporary:
            tree = Path(temporary)
            names = set().union(*(set(current[key]) for key in
                                  ("product_files", "guarded_files", "protected_files")))
            for relative in names:
                target = tree / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / relative).read_bytes())
            self.assertTrue(guard.manifest_tree_matches(current, tree))
            for relative in sorted(paths):
                with self.subTest(path=relative):
                    target = tree / relative
                    original = target.read_bytes()
                    changed = bytearray(original)
                    changed[0] ^= 1
                    target.write_bytes(changed)
                    self.assertFalse(guard.manifest_tree_matches(current, tree))
                    target.write_bytes(original)
                    self.assertTrue(guard.manifest_tree_matches(current, tree))

    def test_integrated_variant_is_additive_and_historical_v2_manifest_is_immutable(self):
        contracts = guard.load_contracts()
        recovery_v2 = next(item for item in contracts if item["variant_id"] == guard.DST_RECOVERY_VARIANT_ID)
        integrated = next(item for item in contracts
                          if item["variant_id"] == guard.DST_RECOVERY_QUALIFICATION_VARIANT_ID)
        current = contracts[-1]
        self.assertEqual(len(contracts), 34)
        self.assertEqual(integrated["baseline_sha"], "990483222f7e65517befc285516a9d80aee2580d")
        self.assertEqual(set(integrated["approved_scope"]) - set(recovery_v2["approved_scope"]),
                         guard.DST_RECOVERY_QUALIFICATION_SCOPE)
        self.assertEqual(set(integrated["product_files"]),
                         set(recovery_v2["product_files"]) | guard.DST_RECOVERY_QUALIFICATION_PRODUCT_ADDITIONS)
        self.assertEqual(set(integrated["guarded_files"]),
                         set(recovery_v2["guarded_files"]) | guard.DST_RECOVERY_QUALIFICATION_GUARDED_ADDITIONS)
        self.assertFalse(guard.manifest_tree_matches(integrated))
        self.assertTrue(guard.manifest_tree_matches(current))
        self.assertTrue(guard.manifest_tree_matches(recovery_v2, guard.dst_recovery_v2_root()))
        raw_v2 = guard.DST_RECOVERY_CONTRACT.read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(hashlib.sha256(raw_v2).hexdigest(), guard.DST_RECOVERY_CONTRACT_SHA256)

    def test_partial_or_arbitrary_manifest_is_not_accepted(self):
        current = guard.load_contracts()[-1]
        forged = copy.deepcopy(current)
        forged["product_files"]["server.py"]["sha256"] = "0" * 64
        self.assertFalse(guard.manifest_tree_matches(forged))
        partial = copy.deepcopy(current)
        partial["guarded_files"].pop("scheduler_runtime.py")
        self.assertFalse(guard.manifest_tree_matches(partial))


if __name__ == "__main__":
    unittest.main()
