"""Current integrated Writer/UI contract v25; historical v1-v24 stay immutable."""
from hashlib import sha256
import json
from pathlib import Path
import re
import unittest

from validation.integrated_snapshot_archive import canonical_eol


ROOT = Path(__file__).resolve().parent
MANIFEST = Path("validation/local_release_20261116/pqm_sync_ui_integrated_v25.json")
MANIFEST_SHA256 = "c553b5147d66bcc1fdbbfa32a90afa5ffb4f1bb873b190c6906d3502176e791b"
PREVIOUS_MANIFEST = Path("validation/local_release_20261116/pqm_sync_ui_integrated_v24.json")
PREVIOUS_MANIFEST_SHA256 = "2bbb2f2c9db047b813af9b9df98f13be6bf9de39da821a66735fec5cd4b904cf"
PREVIOUS_HISTORY_RUNNER = Path("validation/run_integrated_writer_ui_v24_history.py")
PREVIOUS_CANDIDATE = "d01416a196634a0e3ebd4b4e0e24ad1e73dbc3f6"
NORMALIZED_PREVIOUS_TESTS = {
    f"test_google_writer_integrated_candidate_integrity_v{version}.py"
    for version in range(10, 25)
}
V25_CHANGES = {
    ".github/workflows/release-checks.yml",
    "app.js",
    "filter_panels_ui.js",
    "filters.css",
    "index.html",
    "queue_statistics_ui.js",
    "registry_popovers.js",
    "test_release_gate_infrastructure.py",
    "ui_final.css",
    "uo_work_page.css",
    "validation/application_filter_drawer.test.cjs",
    "validation/application_filter_drawer_browser.cjs",
    "validation/edr_monitoring_drawer.test.cjs",
    "validation/local_release_20260911/test_registry_ux_cleanup.py",
    "validation/local_release_20260911/test_release_test_package.py",
    "validation/docker_release_gate.py",
    "validation/release_test_package_v1.json",
    "validation/run_integrated_writer_ui_v24_history.py",
    "validation/run_local_release.py",
    "validation/registry_popover_tabs_browser.cjs",
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


class GoogleWriterIntegratedCandidateIntegrityV25(unittest.TestCase):
    def test_v25_pins_current_candidate_and_preserves_v1_v24_contracts(self):
        manifest_bytes = normalized((ROOT / MANIFEST).read_bytes())
        self.assertEqual(sha256(manifest_bytes).hexdigest(), MANIFEST_SHA256)
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        previous_bytes = normalized((ROOT / PREVIOUS_MANIFEST).read_bytes())
        self.assertEqual(sha256(previous_bytes).hexdigest(), PREVIOUS_MANIFEST_SHA256)
        previous = json.loads(previous_bytes.decode("utf-8"))

        self.assertEqual(manifest["contract"], "pqm-google-writer-sync-ui-integrated")
        self.assertEqual(manifest["version"], 25)
        self.assertEqual(manifest["previous_candidate_commit"], PREVIOUS_CANDIDATE)
        self.assertEqual(manifest["previous_manifest"], PREVIOUS_MANIFEST.as_posix())
        self.assertEqual(manifest["previous_manifest_sha256"], PREVIOUS_MANIFEST_SHA256)
        additions = {
            PREVIOUS_MANIFEST.as_posix(),
            PREVIOUS_HISTORY_RUNNER.as_posix(),
            Path(__file__).name,
        }
        expected_scope = set(previous["scope"]) | additions | V25_CHANGES
        self.assertEqual(set(manifest["scope"]), expected_scope)
        self.assertEqual(set(manifest["files"]), expected_scope)

        for relative, expected in previous["files"].items():
            if relative in V25_CHANGES:
                continue
            data = (ROOT / relative).read_bytes()
            if relative in NORMALIZED_PREVIOUS_TESTS:
                data = normalized_previous_test(data)
            else:
                data = normalized(data)
            with self.subTest(unchanged_from_v24=relative):
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

    def test_v24_runs_on_its_exact_snapshot_and_v25_pins_current_candidate(self):
        workflow = (ROOT / ".github/workflows/release-checks.yml").read_text(encoding="utf-8")
        local_runner = (ROOT / "validation/run_local_release.py").read_text(encoding="utf-8")
        history_runner = (ROOT / PREVIOUS_HISTORY_RUNNER).read_text(encoding="utf-8")
        package = json.loads(
            (ROOT / "validation/release_test_package_v1.json").read_text(encoding="utf-8")
        )

        self.assertIn("version=24", history_runner)
        self.assertIn(PREVIOUS_CANDIDATE, history_runner)
        self.assertIn("PQM_INTEGRATED_V24_SNAPSHOT_ARCHIVE_OUT", workflow)
        self.assertIn("PQM_INTEGRATED_V24_SNAPSHOT_ARCHIVE_SHA256", workflow)
        self.assertIn("integrated_v24_history", local_runner)
        self.assertIn("integrated_v25_current", local_runner)
        self.assertEqual(package["integrated_history_versions"], list(range(1, 25)))
        self.assertEqual(package["integrity_test_versions"], list(range(1, 26)))
        self.assertIn("test_google_writer_integrated_candidate_integrity_v25", workflow)
        current_command = workflow.split(
            "test_google_writer_integrated_candidate_integrity_v25 " + chr(92), 1
        )[1].split("- name: Install Playwright", 1)[0]
        self.assertNotIn("test_google_writer_integrated_candidate_integrity_v24", current_command)
        self.assertIn(
            "--mount \"type=bind,src=$RUNNER_TEMP/pqm-integrated-v24-snapshot.zip",
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
