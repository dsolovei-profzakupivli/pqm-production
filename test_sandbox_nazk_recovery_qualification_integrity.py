"""Additive integrity contract for NAZK recovery plus qualification reconciliation."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from validation.local_release_20260911 import sandbox_protocol_integrity_variant as guard

ROOT = guard.ROOT


class SandboxNazkRecoveryQualificationIntegrityTests(unittest.TestCase):
    def test_integrated_manifest_is_exact_and_v2_history_is_immutable(self):
        contracts = guard.load_contracts()
        recovery_v2 = next(c for c in contracts if c["variant_id"] == guard.DST_RECOVERY_VARIANT_ID)
        integrated = contracts[-1]
        self.assertEqual(len(contracts), 31)
        self.assertEqual(integrated["variant_id"], guard.DST_RECOVERY_QUALIFICATION_VARIANT_ID)
        self.assertEqual(integrated["baseline_sha"], "990483222f7e65517befc285516a9d80aee2580d")
        self.assertEqual(set(integrated["approved_scope"]) - set(recovery_v2["approved_scope"]),
                         guard.DST_RECOVERY_QUALIFICATION_SCOPE)
        self.assertEqual(set(integrated["product_files"]),
                         set(recovery_v2["product_files"]) | guard.DST_RECOVERY_QUALIFICATION_PRODUCT_ADDITIONS)
        self.assertEqual(set(integrated["guarded_files"]),
                         set(recovery_v2["guarded_files"]) | guard.DST_RECOVERY_QUALIFICATION_GUARDED_ADDITIONS)
        self.assertTrue(guard.manifest_tree_matches(integrated))
        self.assertTrue(guard.manifest_tree_matches(recovery_v2, guard.dst_recovery_v2_root()))
        self.assertFalse(guard.manifest_tree_matches(recovery_v2))
        raw = guard.DST_RECOVERY_CONTRACT.read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(hashlib.sha256(raw).hexdigest(), guard.DST_RECOVERY_CONTRACT_SHA256)

    def test_one_byte_change_in_every_integrated_delta_file_is_rejected(self):
        contract = guard.load_contracts()[-1]
        paths = (guard.DST_RECOVERY_QUALIFICATION_PRODUCT_OVERRIDES |
                 guard.DST_RECOVERY_QUALIFICATION_PRODUCT_ADDITIONS |
                 guard.DST_RECOVERY_QUALIFICATION_GUARDED_ADDITIONS |
                 {"validation/docker_release_gate.py",
                  "validation/local_release_20260911/sandbox_protocol_integrity_variant.py",
                  "test_sandbox_dst_hotfix_integrity.py",
                  "test_sandbox_appeals_scenario_api_integrity.py",
                  "test_sandbox_nazk_appeals_stabilization_integrity.py",
                  "test_sandbox_nazk_preview_integrity.py",
                  "test_sandbox_nazk_recovery_integrity.py"})
        with tempfile.TemporaryDirectory(dir=ROOT / "validation") as temporary:
            tree = Path(temporary)
            names = set().union(*(set(contract.get(k, {})) for k in
                                  ("product_files", "guarded_files", "protected_files")))
            for relative in names:
                target = tree / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / relative).read_bytes())
            self.assertTrue(guard.manifest_tree_matches(contract, tree))
            for relative in sorted(paths):
                with self.subTest(path=relative):
                    target = tree / relative
                    original = target.read_bytes()
                    changed = bytearray(original)
                    changed[0] ^= 1
                    target.write_bytes(changed)
                    self.assertFalse(guard.manifest_tree_matches(contract, tree))
                    target.write_bytes(original)
                    self.assertTrue(guard.manifest_tree_matches(contract, tree))

    def test_arbitrary_or_partial_integrated_manifest_is_rejected(self):
        contract = guard.load_contracts()[-1]
        forged = copy.deepcopy(contract)
        forged["product_files"]["server.py"]["sha256"] = "0" * 64
        self.assertFalse(guard.manifest_tree_matches(forged))
        partial = copy.deepcopy(contract)
        partial["guarded_files"].pop("scheduler_runtime.py")
        self.assertFalse(guard.manifest_tree_matches(partial))


if __name__ == "__main__":
    unittest.main()
