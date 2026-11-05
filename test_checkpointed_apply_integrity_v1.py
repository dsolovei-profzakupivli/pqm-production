"""Additive integrity contract for bounded, resumable Apply checkpoints."""
import hashlib
import json
from pathlib import Path
import re
import unittest

MANIFEST = Path("validation/local_release_20260911/checkpointed_apply_v1.json")
MANIFEST_SHA256 = "fc8364697946ad8669c0f87f13112c6c9836007c5e3f40d58009fbe60f885b7e"


def canonical_self(raw):
    return re.sub(rb'MANIFEST_SHA256 = "[^"]*"',
                  b'MANIFEST_SHA256 = "<manifest-sha256>"', raw.replace(b"\r\n", b"\n"))


class CheckpointedApplyIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent
        self.manifest_raw = (self.root / MANIFEST).read_bytes().replace(b"\r\n", b"\n")
        self.manifest = json.loads(self.manifest_raw.decode("utf-8"))

    def test_additive_manifest_and_exact_source_scope(self):
        self.assertEqual(hashlib.sha256(self.manifest_raw).hexdigest(), MANIFEST_SHA256)
        self.assertEqual(self.manifest["contract"], "pqm-sandbox-checkpointed-apply")
        self.assertEqual(self.manifest["version"], 1)
        self.assertEqual(self.manifest["baseline"], "dfaba3d1ff890f7565f83af7c73aaaf1e07a1a4b")
        expected_paths = {
            "execution_apply_contract.py", "google_writer_execution.py", "sandbox_runtime.py",
            "scripts/pqm-google-writer/mirror-alignment/shared/PqmExecutionCheckpoint.gs",
            "scripts/pqm-google-writer/mirror-alignment/sandbox/PqmEnvironmentGuard.gs",
            "scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxAppendApply.gs",
            "scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxControlledApply.gs",
            "scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxExecution.gs",
            "scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxFullApply.gs",
            "scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxPreview.gs",
            "scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxPreviewDependencies.gs",
            "scripts/pqm-google-writer/mirror-alignment/sandbox/PqmVerificationDatetime.gs",
            "test_google_writer_execution.py", "test_sandbox_execution_transport.py",
            "scripts/pqm-google-writer/sandbox-full-apply.test.cjs",
            "test_partial_apply_reconciliation_integrity_v2.py",
            "test_checkpointed_apply_integrity_v1.py",
            "partial_apply_reconciliation_v2_exact_2ece9de.zip",
        }
        self.assertEqual(set(self.manifest["files"]), expected_paths)
        self.assertEqual(hashlib.sha256(canonical_self((self.root / Path(__file__).name).read_bytes())).hexdigest(),
                         self.manifest["integrity_test_sha256_lf"])
        for relative, expected in self.manifest["files"].items():
            with self.subTest(path=relative):
                raw = (self.root / relative).read_bytes()
                if relative == Path(__file__).name:
                    raw = canonical_self(raw)
                elif not relative.endswith(".zip"):
                    raw = raw.replace(b"\r\n", b"\n")
                self.assertEqual(hashlib.sha256(raw).hexdigest(), expected)

    def test_prior_v2_manifest_and_pins_are_preserved(self):
        prior = self.root / "validation/local_release_20260911/partial_apply_reconciliation_v2.json"
        expected = self.manifest["preserved_v2_manifest_sha256"]
        self.assertEqual(hashlib.sha256(prior.read_bytes().replace(b"\r\n", b"\n")).hexdigest(), expected)

    def test_shared_engine_is_sandbox_only_and_production_receipt_stays_legacy(self):
        capability = (self.root / "execution_apply_contract.py").read_text(encoding="utf-8")
        client = (self.root / "google_writer_execution.py").read_text(encoding="utf-8")
        self.assertIn("CHECKPOINT_APPLY_ENVIRONMENTS = frozenset({'SANDBOX'})", capability)
        self.assertIn("if not checkpoint_apply_enabled(getattr(client,'environment',None)):", client)
        self.assertIn("result = client.invoke('apply',request_id,actor,trigger=trigger,digest=digest,", client)

    def test_byte_mutations_of_pinned_files_are_rejected(self):
        for relative, expected in self.manifest["files"].items():
            raw = (self.root / relative).read_bytes().replace(b"\r\n", b"\n")
            for mutation in (raw + b"\x00", raw[:-1]):
                with self.subTest(path=relative, mutation=len(mutation)):
                    self.assertNotEqual(hashlib.sha256(mutation).hexdigest(), expected)

if __name__ == "__main__":
    unittest.main()
