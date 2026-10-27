"""Additive integrity contract for the NAZK Linux failure/recovery gate."""
import ast
import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = ROOT / "validation/production_nazk_recovery_autoclose_v2.json"
MANIFEST_SHA256 = "f5e1e9417281b909b937398cb8741f705f2a71ac852c14524e7408e8a68476f8"
PARENT_MANIFEST_SHA256 = "bc01a5a66d7384ffddefb7347f2c4a6eb4e802a3b75aff707a920cca1536bf4d"
EXPECTED_FILES = {"validation/nazk_scheduler_failure_smoke.py"}
EXPECTED_GATE_MODULES = {
    "validation.local_release_20260911.test_production_nazk_recovery",
    "validation.local_release_20260911.test_production_nazk_sync_hook",
    "validation.local_release_20260911.test_operational_tasks",
    "validation.local_release_20260911.test_nazk_task_relevance",
    "validation.local_release_20260911.test_reference_directories",
    "test_production_ui_release_integrity",
    "test_production_dst_hotfix_integrity",
    "test_production_declension_preview_integrity",
    "test_production_scenario_projection_integrity",
    "test_production_nazk_recovery_integrity",
    "test_production_nazk_recovery_followup_integrity",
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


class ProductionNazkRecoveryFollowupIntegrityTests(unittest.TestCase):
    def test_additive_v2_manifest_is_exact_and_keeps_v1_immutable(self):
        raw = MANIFEST_PATH.read_bytes()
        self.assertEqual(sha(raw), MANIFEST_SHA256)
        manifest = json.loads(raw)
        self.assertEqual(manifest["name"], "production-nazk-recovery-autoclose-v2")
        self.assertEqual(manifest["baseline"], "3eb465fad28272051478999683605e673a2bdfb1")
        self.assertEqual(manifest["parent_manifest"], "validation/production_nazk_recovery_autoclose_v1.json")
        self.assertEqual(manifest["parent_manifest_sha256"], PARENT_MANIFEST_SHA256)
        self.assertEqual(sha((ROOT / manifest["parent_manifest"]).read_bytes()), PARENT_MANIFEST_SHA256)
        self.assertEqual(set(manifest["files"]), EXPECTED_FILES)

    def test_linux_smoke_pins_fencing_cleanup_and_full_nazk_suite(self):
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        for name, expected in manifest["files"].items():
            data = (ROOT / name).read_bytes()
            with self.subTest(file=name):
                self.assertEqual(sha(data), expected)
                changed = bytes([data[0] ^ 1]) + data[1:]
                self.assertNotEqual(sha(changed), expected)

        source = (ROOT / "validation/nazk_scheduler_failure_smoke.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        assignment = next(node for node in tree.body if isinstance(node, ast.Assign) and
                          any(isinstance(target, ast.Name) and target.id == "NAZK_GATE_MODULES"
                              for target in node.targets))
        self.assertEqual(set(ast.literal_eval(assignment.value)), EXPECTED_GATE_MODULES)
        docker_gate = (ROOT / "validation/docker_release_gate.py").read_text(encoding="utf-8")
        self.assertIn("validation/nazk_scheduler_failure_smoke.py", docker_gate)
        self.assertIn("require_current", source)
        self.assertIn("test_nazk_finish_rejects_non_owner_token", source)
        self.assertIn("test_other_scheduler_finish_keeps_legacy_default", source)
        self.assertIn("test_status_write_failure_still_calls_failure_cleanup_only", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
