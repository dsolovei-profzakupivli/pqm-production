"""Exact additive v4 candidate plus byte-for-byte historical reconstruction."""
import copy
import tempfile
import unittest
from pathlib import Path

from validation.local_release_20260911 import sandbox_protocol_integrity_variant as guard


class ExperienceV4IntegrityTests(unittest.TestCase):
    def test_exact_candidate_and_all_historical_manifests_are_pinned(self):
        contracts = guard.load_contracts()
        self.assertEqual(len(contracts), 34)
        current, previous = contracts[-1], contracts[-2]
        self.assertEqual(current["variant_id"], guard.EXPERIENCE_V4_ID)
        self.assertTrue(guard.manifest_tree_matches(current))
        self.assertFalse(guard.manifest_tree_matches(previous))
        self.assertTrue(guard.manifest_tree_matches(previous, guard.experience_parent_root()))
        for name, expected in current["historical_manifest_sha256"].items():
            self.assertEqual(guard.sha256((guard.ROOT / name).read_bytes().replace(b"\r\n", b"\n")), expected, name)

    def test_every_product_guard_and_protected_one_byte_mutation_is_rejected(self):
        current = guard.load_contracts()[-1]
        names = set().union(*(set(current[k]) for k in ("product_files", "guarded_files", "protected_files")))
        with tempfile.TemporaryDirectory(dir=guard.ROOT / "validation") as tmp:
            root = Path(tmp)
            for name in names:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((guard.ROOT / name).read_bytes())
            self.assertTrue(guard.manifest_tree_matches(current, root))
            for name in sorted(names):
                target = root / name
                raw = target.read_bytes()
                target.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
                with self.subTest(file=name): self.assertFalse(guard.manifest_tree_matches(current, root))
                target.write_bytes(raw)
            self.assertTrue(guard.manifest_tree_matches(current, root))

    def test_partial_forged_manifest_and_protected_ast_mutations_fail_closed(self):
        current = guard.load_contracts()[-1]
        forged = copy.deepcopy(current)
        forged["product_files"].pop("contract_experience_v4.py")
        self.assertFalse(guard.manifest_tree_matches(forged))
        projection = current["server_projection"]
        server = (guard.ROOT / "server.py").read_bytes()
        baseline = (guard.ROOT / projection["parent_server_fixture"]).read_bytes()
        approved = projection["approved_function_ast_sha256"]
        self.assertTrue(guard._nazk_server_ast_projection_matches(server, baseline, approved))
        for before, after in ((b"algorithm_version=4", b"algorithm_version=3"),
                              (b"def amcu_blocks_submission(", b"def amcu_blocks_submissioN("),
                              (b"require_current: bool = False", b"require_current: bool = True")):
            changed = server.replace(before, after, 1)
            self.assertNotEqual(changed, server)
            self.assertFalse(guard._nazk_server_ast_projection_matches(changed, baseline, approved))


if __name__ == "__main__": unittest.main()
