"""Candidate integrity v27; historical integrated contracts v1-v26 remain immutable."""
from hashlib import sha256
import json
from pathlib import Path
import re
import unittest

from validation.integrated_snapshot_archive import canonical_eol

ROOT = Path(__file__).resolve().parent
MANIFEST = Path("validation/local_release_20261116/pqm_sync_ui_integrated_v27.json")
MANIFEST_SHA256 = "d0d6e3124e64878d730b6c8fbe247ec9b0f24949cfe980d4390b5f752fad2f7d"
PREVIOUS_MANIFEST = Path("validation/local_release_20261116/pqm_sync_ui_integrated_v26.json")
PREVIOUS_MANIFEST_SHA256 = "d858aa19de810f8a40a935a528006f6d38537961ba4b1e97d31f6272323a62dc"
PREVIOUS_HISTORY_RUNNER = Path("validation/run_integrated_writer_ui_v26_history.py")
PREVIOUS_CANDIDATE = "e436c952b17fc79ccb8fc1f8c366cbbf18ca31fc"
NORMALIZED_PREVIOUS_TESTS = {
    f"test_google_writer_integrated_candidate_integrity_v{version}.py"
    for version in range(10, 27)
}
V27_CHANGES = {
    ".github/workflows/release-checks.yml",
    "app.js",
    "edr_sync_v2.py",
    "index.html",
    "server.py",
    "test_release_gate_infrastructure.py",
    "validation/docker_release_gate.py",
    "validation/local_release_20260911/test_google_runtime.py",
    "validation/local_release_20260911/test_permanent_edr_sync_safety.py",
    "validation/release_test_package_v1.json",
    "validation/run_local_release.py",
}


def normalized(data: bytes) -> bytes:
    return canonical_eol(data)


def normalized_test(data: bytes) -> bytes:
    return re.sub(
        rb'(?m)^MANIFEST_SHA256 = "(?:<manifest-sha256>|[0-9a-f]{64})"$',
        b'MANIFEST_SHA256 = "<manifest-sha256>"', normalized(data),
    )


class GoogleWriterIntegratedCandidateIntegrityV27(unittest.TestCase):
    def test_v27_pins_candidate_and_preserves_v1_v26_contracts(self):
        manifest_bytes = normalized((ROOT / MANIFEST).read_bytes())
        self.assertEqual(sha256(manifest_bytes).hexdigest(), MANIFEST_SHA256)
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        previous_bytes = normalized((ROOT / PREVIOUS_MANIFEST).read_bytes())
        self.assertEqual(sha256(previous_bytes).hexdigest(), PREVIOUS_MANIFEST_SHA256)
        previous = json.loads(previous_bytes.decode("utf-8"))
        self.assertEqual(manifest["contract"], "pqm-google-writer-sync-ui-integrated")
        self.assertEqual(manifest["version"], 27)
        self.assertEqual(manifest["previous_candidate_commit"], PREVIOUS_CANDIDATE)
        self.assertEqual(manifest["previous_manifest"], PREVIOUS_MANIFEST.as_posix())
        self.assertEqual(manifest["previous_manifest_sha256"], PREVIOUS_MANIFEST_SHA256)
        scope = set(previous["scope"]) | {PREVIOUS_MANIFEST.as_posix(), PREVIOUS_HISTORY_RUNNER.as_posix(), Path(__file__).name} | V27_CHANGES
        self.assertEqual(set(manifest["scope"]), scope)
        self.assertEqual(set(manifest["files"]), scope)
        for relative, expected in previous["files"].items():
            if relative in V27_CHANGES:
                continue
            data = (ROOT / relative).read_bytes()
            data = normalized_test(data) if relative in NORMALIZED_PREVIOUS_TESTS else normalized(data)
            with self.subTest(unchanged_from_v26=relative):
                self.assertEqual(sha256(data).hexdigest(), expected)
        for relative, expected in manifest["files"].items():
            data = (ROOT / relative).read_bytes()
            data = normalized_test(data) if relative == Path(__file__).name or relative in NORMALIZED_PREVIOUS_TESTS else normalized(data)
            with self.subTest(current_pin=relative):
                self.assertEqual(sha256(data).hexdigest(), expected)

    def test_v26_runs_on_exact_snapshot_and_v27_is_current_overlay(self):
        workflow = (ROOT / ".github/workflows/release-checks.yml").read_text(encoding="utf-8")
        local_runner = (ROOT / "validation/run_local_release.py").read_text(encoding="utf-8")
        history_runner = (ROOT / PREVIOUS_HISTORY_RUNNER).read_text(encoding="utf-8")
        package = json.loads((ROOT / "validation/release_test_package_v1.json").read_text(encoding="utf-8"))
        self.assertIn("version=26", history_runner)
        self.assertIn(PREVIOUS_CANDIDATE, history_runner)
        self.assertIn("PQM_INTEGRATED_V26_SNAPSHOT_ARCHIVE_OUT", workflow)
        self.assertIn("PQM_INTEGRATED_V26_SNAPSHOT_ARCHIVE_SHA256", workflow)
        self.assertIn("integrated_v26_history", local_runner)
        self.assertIn("integrated_v27_current", local_runner)
        self.assertEqual(package["integrated_history_versions"], list(range(1, 27)))
        self.assertEqual(package["integrity_test_versions"], list(range(1, 28)))
        self.assertIn("test_google_writer_integrated_candidate_integrity_v27", workflow)
        self.assertIn("pqm-integrated-v26-snapshot.zip", workflow)


if __name__ == "__main__":
    unittest.main()
