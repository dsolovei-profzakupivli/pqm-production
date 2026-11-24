"""Current candidate integrity v28; historical contracts v1-v27 stay immutable."""
from hashlib import sha256
import json
from pathlib import Path
import re
import unittest

from validation.integrated_snapshot_archive import canonical_eol

ROOT = Path(__file__).resolve().parent
MANIFEST = Path("validation/local_release_20261116/pqm_sync_ui_integrated_v28.json")
MANIFEST_SHA256 = "21686ca702f1e57d8ec4b6b38c00e75ba7e21c133f600a8a5b31f64d8a988eb8"
PREVIOUS_MANIFEST = Path("validation/local_release_20261116/pqm_sync_ui_integrated_v27.json")
PREVIOUS_MANIFEST_SHA256 = "d0d6e3124e64878d730b6c8fbe247ec9b0f24949cfe980d4390b5f752fad2f7d"
PREVIOUS_CANDIDATE = "caab241482d7ad96c0088d6878efaad7b0f9ad0a"
V26_MANIFEST_SHA256 = "d858aa19de810f8a40a935a528006f6d38537961ba4b1e97d31f6272323a62dc"
V26_SNAPSHOT_COMMIT = "e436c952b17fc79ccb8fc1f8c366cbbf18ca31fc"
PREVIOUS_HISTORY_RUNNER = Path("validation/run_integrated_writer_ui_v27_history.py")
V28_CHANGES = {
    ".github/workflows/release-checks.yml",
    "app.js",
    "edr_sync_v2.py",
    "server.py",
    "test_release_gate_infrastructure.py",
    "test_background_jobs_kill_switch.py",
    "validation/docker_release_gate.py",
    "test_google_writer_integrated_candidate_integrity_v28.py",
    "validation/local_release_20260911/test_google_runtime.py",
    "validation/release_test_package_v1.json",
    "validation/run_google_writer_update_append_v2_v26_history.py",
    "validation/run_integrated_writer_ui_v27_history.py",
    "validation/run_local_release.py",
}
NORMALIZED_INTEGRITY_TESTS = {
    f"test_google_writer_integrated_candidate_integrity_v{version}.py"
    for version in range(10, 29)
}


def normalized(data: bytes) -> bytes:
    return canonical_eol(data)


def normalized_test(data: bytes) -> bytes:
    return re.sub(
        rb'(?m)^MANIFEST_SHA256 = "(?:<manifest-sha256>|[0-9a-f]{64})"$',
        b'MANIFEST_SHA256 = "<manifest-sha256>"', normalized(data),
    )


class GoogleWriterIntegratedCandidateIntegrityV28(unittest.TestCase):
    def test_v28_pins_candidate_and_preserves_v1_v27_contracts(self):
        manifest_bytes = normalized((ROOT / MANIFEST).read_bytes())
        self.assertEqual(sha256(manifest_bytes).hexdigest(), MANIFEST_SHA256)
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        previous_bytes = normalized((ROOT / PREVIOUS_MANIFEST).read_bytes())
        self.assertEqual(sha256(previous_bytes).hexdigest(), PREVIOUS_MANIFEST_SHA256)
        previous = json.loads(previous_bytes.decode("utf-8"))
        self.assertEqual(manifest["contract"], "pqm-google-writer-sync-ui-integrated")
        self.assertEqual(manifest["version"], 28)
        self.assertEqual(manifest["previous_candidate_commit"], PREVIOUS_CANDIDATE)
        self.assertEqual(manifest["previous_manifest"], PREVIOUS_MANIFEST.as_posix())
        self.assertEqual(manifest["previous_manifest_sha256"], PREVIOUS_MANIFEST_SHA256)
        scope = set(previous["scope"]) | {
            PREVIOUS_MANIFEST.as_posix(), PREVIOUS_HISTORY_RUNNER.as_posix(),
            Path(__file__).name,
        } | V28_CHANGES
        self.assertEqual(set(manifest["scope"]), scope)
        self.assertEqual(set(manifest["files"]), scope)
        for relative, expected in previous["files"].items():
            if relative in V28_CHANGES:
                continue
            data = (ROOT / relative).read_bytes()
            if relative in NORMALIZED_INTEGRITY_TESTS:
                data = normalized_test(data)
            else:
                data = normalized(data)
            with self.subTest(unchanged_from_v27=relative):
                self.assertEqual(sha256(data).hexdigest(), expected)
        for relative, expected in manifest["files"].items():
            data = (ROOT / relative).read_bytes()
            data = normalized_test(data) if relative in NORMALIZED_INTEGRITY_TESTS else normalized(data)
            with self.subTest(current_pin=relative):
                self.assertEqual(sha256(data).hexdigest(), expected)

    def test_historical_routing_and_preview_export_contracts_are_mandatory(self):
        workflow = (ROOT / ".github/workflows/release-checks.yml").read_text(encoding="utf-8")
        local_runner = (ROOT / "validation/run_local_release.py").read_text(encoding="utf-8")
        v27_runner = (ROOT / PREVIOUS_HISTORY_RUNNER).read_text(encoding="utf-8")
        v2_runner = (ROOT / "validation/run_google_writer_update_append_v2_v26_history.py").read_text(encoding="utf-8")
        package = json.loads((ROOT / "validation/release_test_package_v1.json").read_text(encoding="utf-8"))
        self.assertIn("version=27", v27_runner)
        self.assertIn(PREVIOUS_CANDIDATE, v27_runner)
        self.assertIn(V26_SNAPSHOT_COMMIT, v2_runner)
        self.assertIn(V26_MANIFEST_SHA256, v2_runner)
        self.assertIn("PQM_UPDATE_APPEND_V2_V26_FULL_ARCHIVE", v2_runner)
        self.assertIn("PQM_INTEGRATED_V27_SNAPSHOT_ARCHIVE_OUT", workflow)
        self.assertIn("run_google_writer_update_append_v2_v26_history.py", workflow)
        self.assertIn("integrated_v27_history", local_runner)
        self.assertIn("update_append_v2_v26", local_runner)
        self.assertIn("integrated_v28_current", local_runner)
        self.assertEqual(package["integrated_history_versions"], list(range(1, 28)))
        self.assertEqual(package["integrity_test_versions"], list(range(1, 29)))
        self.assertIn("test_google_writer_integrated_candidate_integrity_v28", workflow)
        self.assertIn("test_google_writer_update_append_v2_integrity", v2_runner)


if __name__ == "__main__":
    unittest.main()
