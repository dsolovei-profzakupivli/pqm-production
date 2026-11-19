"""Additive integrity contract for NAZK recovery plus qualification reconciliation."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from validation.local_release_20260911 import sandbox_protocol_integrity_variant as guard

import messages_integrity
guard = messages_integrity.historical_guard(guard.ROOT)
ROOT = guard.ROOT


class SandboxNazkRecoveryQualificationIntegrityTests(unittest.TestCase):
    def test_integrated_manifest_is_exact_and_v2_history_is_immutable(self):
        contracts = guard.load_contracts()
        recovery_v2 = next(c for c in contracts if c["variant_id"] == guard.DST_RECOVERY_VARIANT_ID)
        integrated_v3 = next(c for c in contracts
                             if c["variant_id"] == guard.DST_RECOVERY_QUALIFICATION_VARIANT_ID)
        integrated = next(c for c in contracts
                          if c["variant_id"] == guard.DST_RECOVERY_QUALIFICATION_TEST_FIX_VARIANT_ID)
        alignment = contracts[-1]
        self.assertEqual(len(contracts), 33)
        self.assertEqual(integrated_v3["variant_id"], guard.DST_RECOVERY_QUALIFICATION_VARIANT_ID)
        self.assertEqual(integrated_v3["baseline_sha"], "990483222f7e65517befc285516a9d80aee2580d")
        self.assertEqual(integrated["variant_id"], guard.DST_RECOVERY_QUALIFICATION_TEST_FIX_VARIANT_ID)
        self.assertEqual(integrated["baseline_sha"], integrated_v3["baseline_sha"])
        self.assertEqual(set(integrated["approved_scope"]) - set(integrated_v3["approved_scope"]),
                         guard.DST_RECOVERY_QUALIFICATION_TEST_FIX_SCOPE)
        self.assertEqual(set(integrated["approved_scope"]) - set(recovery_v2["approved_scope"]),
                         guard.DST_RECOVERY_QUALIFICATION_SCOPE |
                         guard.DST_RECOVERY_QUALIFICATION_TEST_FIX_SCOPE)
        self.assertEqual(set(integrated["product_files"]),
                         set(recovery_v2["product_files"]) | guard.DST_RECOVERY_QUALIFICATION_PRODUCT_ADDITIONS)
        self.assertEqual(set(integrated["guarded_files"]),
                         set(integrated_v3["guarded_files"]) |
                         guard.DST_RECOVERY_QUALIFICATION_TEST_FIX_GUARDED_ADDITIONS)
        self.assertTrue(guard.manifest_tree_matches(integrated, guard.dst_recovery_v4_root()))
        self.assertTrue(guard.manifest_tree_matches(recovery_v2, guard.dst_recovery_v2_root()))
        self.assertFalse(guard.manifest_tree_matches(recovery_v2))
        self.assertFalse(guard.manifest_tree_matches(integrated_v3))
        raw = guard.DST_RECOVERY_CONTRACT.read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(hashlib.sha256(raw).hexdigest(), guard.DST_RECOVERY_CONTRACT_SHA256)
        raw_v3 = guard.DST_RECOVERY_QUALIFICATION_CONTRACT.read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(hashlib.sha256(raw_v3).hexdigest(), guard.DST_RECOVERY_QUALIFICATION_CONTRACT_SHA256)
        raw_v4 = guard.DST_RECOVERY_QUALIFICATION_TEST_FIX_CONTRACT.read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(hashlib.sha256(raw_v4).hexdigest(),
                         guard.DST_RECOVERY_QUALIFICATION_TEST_FIX_CONTRACT_SHA256)
        self.assertEqual(alignment["variant_id"], guard.DST_RECOVERY_INTEGRITY_ALIGNMENT_VARIANT_ID)
        self.assertTrue(guard.manifest_tree_matches(alignment))
        self.assertEqual(alignment["historical_manifest_sha256"][
            "test_sandbox_dst_hotfix_recovery_integrated_v4.json"],
            guard.DST_RECOVERY_QUALIFICATION_TEST_FIX_CONTRACT_SHA256)

    def test_server_legacy_projections_and_approved_functions_are_separately_pinned(self):
        alignment = guard.load_contracts()[-1]
        projection = alignment["server_projection"]
        server = (ROOT / "server.py").read_bytes()
        self.assertEqual(guard.nazk_server_projection_hashes(server, alignment),
                         projection["historical_projection_sha256"])
        with self.subTest("protected historical function mutation"):
            changed = server.replace(b"def amcu_blocks_submission(",
                                     b"def amcu_blocks_submissioN(", 1)
            self.assertNotEqual(changed, server)
            self.assertFalse(guard._nazk_server_ast_projection_matches(
                changed, (ROOT / projection["parent_server_fixture"]).read_bytes(),
                projection["approved_function_ast_sha256"]))
        with self.subTest("approved NAZK section mutation"):
            changed = server.replace(b"require_current: bool = False",
                                     b"require_current: bool = True", 1)
            self.assertNotEqual(changed, server)
            self.assertFalse(guard._nazk_server_ast_projection_matches(
                changed, (ROOT / projection["parent_server_fixture"]).read_bytes(),
                projection["approved_function_ast_sha256"]))

    def test_one_byte_change_in_every_integrated_delta_file_is_rejected(self):
        contract = guard.load_contracts()[-1]
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
