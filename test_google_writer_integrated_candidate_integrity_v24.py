"""Current integrated Writer/UI contract v24; historical v1-v23 stay immutable."""
from hashlib import sha256
import json
from pathlib import Path
import re
import unittest

from validation.integrated_snapshot_archive import canonical_eol


ROOT = Path(__file__).resolve().parent
MANIFEST = Path("validation/local_release_20261116/pqm_sync_ui_integrated_v24.json")
MANIFEST_SHA256 = "2bbb2f2c9db047b813af9b9df98f13be6bf9de39da821a66735fec5cd4b904cf"
PREVIOUS_MANIFEST = Path("validation/local_release_20261116/pqm_sync_ui_integrated_v23.json")
PREVIOUS_MANIFEST_SHA256 = "88cf0b074780d5ce5a1946ba849979254556be5d8020d477b9013ce931d24482"
PREVIOUS_HISTORY_RUNNER = Path("validation/run_integrated_writer_ui_v23_history.py")
PREVIOUS_CANDIDATE = "c6bac6226af3ed75e175b36aaa3a2dc55700b5af"
NORMALIZED_PREVIOUS_TESTS = {
    f"test_google_writer_integrated_candidate_integrity_v{version}.py"
    for version in range(10, 24)
}
V24_CHANGES = {
    ".github/workflows/release-checks.yml",
    "app.js",
    "index.html",
    "test_release_gate_infrastructure.py",
    "ui_final.css",
    "validation/edr_monitoring_drawer.test.cjs",
    "validation/local_release_20260911/test_release_test_package.py",
    "validation/release_test_package_v1.json",
    "validation/run_integrated_writer_ui_v23_history.py",
    "validation/run_local_release.py",
    "validation/uo_work_page_layout_browser.cjs",
}


def normalized(data: bytes) -> bytes:
    return canonical_eol(data)


def normalized_self(data: bytes) -> bytes:
    return re.sub(
        rb'(?m)^MANIFEST_SHA256 = "(?:<manifest-sha256>|[0-9a-f]{64})"$',
        b'MANIFEST_SHA256 = "<manifest-sha256>"',
        normalized(data),
    )


def normalized_previous_test(data: bytes) -> bytes:
    return re.sub(
        rb'(?m)^MANIFEST_SHA256 = "(?:<manifest-sha256>|[0-9a-f]{64})"$',
        b'MANIFEST_SHA256 = "<manifest-sha256>"',
        normalized(data),
    )


class GoogleWriterIntegratedCandidateIntegrityV24(unittest.TestCase):
    def test_v24_pins_current_candidate_and_preserves_v1_v23_contracts(self):
        manifest_bytes = normalized((ROOT / MANIFEST).read_bytes())
        self.assertEqual(sha256(manifest_bytes).hexdigest(), MANIFEST_SHA256)
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        previous_bytes = normalized((ROOT / PREVIOUS_MANIFEST).read_bytes())
        self.assertEqual(sha256(previous_bytes).hexdigest(), PREVIOUS_MANIFEST_SHA256)
        previous = json.loads(previous_bytes.decode("utf-8"))

        self.assertEqual(manifest["contract"], "pqm-google-writer-sync-ui-integrated")
        self.assertEqual(manifest["version"], 24)
        self.assertEqual(manifest["previous_candidate_commit"], PREVIOUS_CANDIDATE)
        self.assertEqual(manifest["previous_manifest"], PREVIOUS_MANIFEST.as_posix())
        self.assertEqual(manifest["previous_manifest_sha256"], PREVIOUS_MANIFEST_SHA256)
        additions = {
            PREVIOUS_MANIFEST.as_posix(),
            PREVIOUS_HISTORY_RUNNER.as_posix(),
            Path(__file__).name,
        }
        expected_scope = set(previous["scope"]) | additions | V24_CHANGES
        self.assertEqual(set(manifest["scope"]), expected_scope)
        self.assertEqual(set(manifest["files"]), expected_scope)

        for relative, expected in previous["files"].items():
            if relative in V24_CHANGES:
                continue
            data = (ROOT / relative).read_bytes()
            if relative in NORMALIZED_PREVIOUS_TESTS:
                data = normalized_previous_test(data)
            else:
                data = normalized(data)
            with self.subTest(unchanged_from_v23=relative):
                self.assertEqual(sha256(data).hexdigest(), expected)

        for relative, expected in manifest["files"].items():
            data = (ROOT / relative).read_bytes()
            if relative == Path(__file__).name:
                data = normalized_self(data)
            elif relative in NORMALIZED_PREVIOUS_TESTS:
                data = normalized_previous_test(data)
            else:
                data = normalized(data)
            with self.subTest(current_pin=relative):
                self.assertEqual(sha256(data).hexdigest(), expected)

    def test_v23_runs_on_its_exact_snapshot_and_v24_pins_the_drawer_candidate(self):
        workflow = (ROOT / ".github/workflows/release-checks.yml").read_text(encoding="utf-8")
        local_runner = (ROOT / "validation/run_local_release.py").read_text(encoding="utf-8")
        history_runner = (ROOT / PREVIOUS_HISTORY_RUNNER).read_text(encoding="utf-8")
        package = json.loads((ROOT / "validation/release_test_package_v1.json").read_text(encoding="utf-8"))

        self.assertIn("version=23", history_runner)
        self.assertIn(PREVIOUS_CANDIDATE, history_runner)
        self.assertIn("PQM_INTEGRATED_V23_SNAPSHOT_ARCHIVE_OUT", workflow)
        self.assertIn("PQM_INTEGRATED_V23_SNAPSHOT_ARCHIVE_SHA256", workflow)
        self.assertIn("integrated_v23_history", local_runner)
        self.assertIn("integrated_v24_current", local_runner)
        self.assertEqual(package["integrated_history_versions"], list(range(1, 24)))
        self.assertEqual(package["integrity_test_versions"], list(range(1, 25)))
        self.assertIn("edr_monitoring_drawer.test.cjs", package["supplemental_validation_files"])
        node_tests = workflow.split("node --test", 1)[1].split("snapshot=", 1)[0]
        self.assertIn("validation/edr_monitoring_drawer.test.cjs", node_tests)
        self.assertIn("test_google_writer_integrated_candidate_integrity_v24", workflow)
        self.assertNotIn("test_google_writer_integrated_candidate_integrity_v23 \\", workflow)
        self.assertIn("--mount \"type=bind,src=$RUNNER_TEMP/pqm-integrated-v23-snapshot.zip", workflow)


if __name__ == "__main__":
    unittest.main()
