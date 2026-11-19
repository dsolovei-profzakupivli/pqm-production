"""Current integrated Writer/UI contract v26; historical v1-v25 stay immutable."""
from hashlib import sha256
import json
from pathlib import Path
import re
import unittest

from validation.integrated_snapshot_archive import canonical_eol


ROOT = Path(__file__).resolve().parent
MANIFEST = Path("validation/local_release_20261116/pqm_sync_ui_integrated_v26.json")
MANIFEST_SHA256 = "6ac2833c9cb664f1e18e8370833d71153646d63199819a009a28479ef50ce0ed"
PREVIOUS_MANIFEST = Path("validation/local_release_20261116/pqm_sync_ui_integrated_v25.json")
PREVIOUS_MANIFEST_SHA256 = "c553b5147d66bcc1fdbbfa32a90afa5ffb4f1bb873b190c6906d3502176e791b"
PREVIOUS_HISTORY_RUNNER = Path("validation/run_integrated_writer_ui_v25_history.py")
PREVIOUS_CANDIDATE = "76333071ac0977c7c5d31c5ea6142597f2f7508c"
NORMALIZED_PREVIOUS_TESTS = {
    f"test_google_writer_integrated_candidate_integrity_v{version}.py"
    for version in range(10, 26)
}
V26_CHANGES = {
    ".github/workflows/release-checks.yml",
    "app.js",
    "filter_panels_ui.js",
    "queue_statistics_ui.js",
    "test_release_gate_infrastructure.py",
    "ui_final.css",
    "uo_work_page.css",
    "validation/application_filter_drawer.test.cjs",
    "validation/edr_monitoring_drawer.test.cjs",
    "validation/edr_monitoring_filter_state.cjs",
    "validation/edr_ui_state.test.cjs",
    "validation/local_release_20260911/test_release_test_package.py",
    "validation/queue_statistics_ui.test.cjs",
    "validation/uo_work_page_layout_browser.cjs",
    "validation/docker_release_gate.py",
    "validation/release_test_package_v1.json",
    "validation/run_integrated_writer_ui_v25_history.py",
    "validation/run_local_release.py",
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


class GoogleWriterIntegratedCandidateIntegrityV26(unittest.TestCase):
    def test_v26_pins_current_candidate_and_preserves_v1_v25_contracts(self):
        manifest_bytes = normalized((ROOT / MANIFEST).read_bytes())
        self.assertEqual(sha256(manifest_bytes).hexdigest(), MANIFEST_SHA256)
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        previous_bytes = normalized((ROOT / PREVIOUS_MANIFEST).read_bytes())
        self.assertEqual(sha256(previous_bytes).hexdigest(), PREVIOUS_MANIFEST_SHA256)
        previous = json.loads(previous_bytes.decode("utf-8"))

        self.assertEqual(manifest["contract"], "pqm-google-writer-sync-ui-integrated")
        self.assertEqual(manifest["version"], 26)
        self.assertEqual(manifest["previous_candidate_commit"], PREVIOUS_CANDIDATE)
        self.assertEqual(manifest["previous_manifest"], PREVIOUS_MANIFEST.as_posix())
        self.assertEqual(manifest["previous_manifest_sha256"], PREVIOUS_MANIFEST_SHA256)
        additions = {
            PREVIOUS_MANIFEST.as_posix(),
            PREVIOUS_HISTORY_RUNNER.as_posix(),
            Path(__file__).name,
        }
        expected_scope = set(previous["scope"]) | additions | V26_CHANGES
        self.assertEqual(set(manifest["scope"]), expected_scope)
        self.assertEqual(set(manifest["files"]), expected_scope)

        for relative, expected in previous["files"].items():
            if relative in V26_CHANGES:
                continue
            data = (ROOT / relative).read_bytes()
            if relative in NORMALIZED_PREVIOUS_TESTS:
                data = normalized_previous_test(data)
            else:
                data = normalized(data)
            with self.subTest(unchanged_from_v25=relative):
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

    def test_v25_runs_on_its_exact_snapshot_and_v26_pins_current_candidate(self):
        workflow = (ROOT / ".github/workflows/release-checks.yml").read_text(encoding="utf-8")
        local_runner = (ROOT / "validation/run_local_release.py").read_text(encoding="utf-8")
        history_runner = (ROOT / PREVIOUS_HISTORY_RUNNER).read_text(encoding="utf-8")
        package = json.loads(
            (ROOT / "validation/release_test_package_v1.json").read_text(encoding="utf-8")
        )

        self.assertIn("version=25", history_runner)
        self.assertIn(PREVIOUS_CANDIDATE, history_runner)
        self.assertIn("PQM_INTEGRATED_V25_SNAPSHOT_ARCHIVE_OUT", workflow)
        self.assertIn("PQM_INTEGRATED_V25_SNAPSHOT_ARCHIVE_SHA256", workflow)
        self.assertIn("integrated_v25_history", local_runner)
        self.assertIn("integrated_v26_current", local_runner)
        self.assertEqual(package["integrated_history_versions"], list(range(1, 26)))
        self.assertEqual(package["integrity_test_versions"], list(range(1, 27)))
        self.assertIn("test_google_writer_integrated_candidate_integrity_v26", workflow)
        current_command = workflow.split(
            "test_google_writer_integrated_candidate_integrity_v26 " + chr(92), 1
        )[1].split("- name: Install Playwright", 1)[0]
        self.assertNotIn("test_google_writer_integrated_candidate_integrity_v25", current_command)
        self.assertIn(
            "--mount \"type=bind,src=$RUNNER_TEMP/pqm-integrated-v25-snapshot.zip",
            workflow,
        )
        self.assertIn("PQM_INTEGRATED_V25_SNAPSHOT_ARCHIVE=/tmp/pqm-integrated-v25-snapshot.zip", workflow)


if __name__ == "__main__":
    unittest.main()
