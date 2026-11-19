"""Current integrated Writer/UI contract v20; historical v1-v19 remain immutable."""
from hashlib import sha256
import json
from pathlib import Path
import re
import unittest

from validation.integrated_snapshot_archive import canonical_eol


ROOT = Path(__file__).resolve().parent
MANIFEST = Path("validation/local_release_20261116/pqm_sync_ui_integrated_v20.json")
MANIFEST_SHA256 = "ae9659dfc316746cc285c8716bdc0da6357f640934a959e0f05b6a912fb341af"
PREVIOUS_MANIFEST = Path("validation/local_release_20261116/pqm_sync_ui_integrated_v19.json")
PREVIOUS_MANIFEST_SHA256 = "08a4a7cea501a9ff2b4a948431063806b2af0132ebefa4e385263878eb0499b5"
PREVIOUS_HISTORY_RUNNER = Path("validation/run_integrated_writer_ui_v19_history.py")
PREVIOUS_CANDIDATE = "00f369ad12583f38d612f7efcdd28e3094d97be1"
NORMALIZED_PREVIOUS_TESTS = {
    f"test_google_writer_integrated_candidate_integrity_v{version}.py"
    for version in range(10, 20)
}
V20_CHANGES = {
    ".github/workflows/release-checks.yml",
    "app.js",
    "filters.css",
    "history_columns.js",
    "history_ui.js",
    "index.html",
    "queue_statistics_ui.js",
    "styles.css",
    "test_release_gate_infrastructure.py",
    "ui_final.css",
    "ui_improvements.css",
    "ui_improvements_boot.js",
    "uo_work_page.css",
    "validation/queue_statistics_ui.test.cjs",
    "validation/release_test_package_v1.json",
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


class GoogleWriterIntegratedCandidateIntegrityV20(unittest.TestCase):
    def test_v20_pins_current_candidate_and_preserves_v1_v19_contracts(self):
        manifest_bytes = normalized((ROOT / MANIFEST).read_bytes())
        self.assertEqual(sha256(manifest_bytes).hexdigest(), MANIFEST_SHA256)
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        previous_bytes = normalized((ROOT / PREVIOUS_MANIFEST).read_bytes())
        self.assertEqual(sha256(previous_bytes).hexdigest(), PREVIOUS_MANIFEST_SHA256)
        previous = json.loads(previous_bytes.decode("utf-8"))

        self.assertEqual(manifest["contract"], "pqm-google-writer-sync-ui-integrated")
        self.assertEqual(manifest["version"], 20)
        self.assertEqual(manifest["previous_candidate_commit"], PREVIOUS_CANDIDATE)
        self.assertEqual(manifest["previous_manifest"], PREVIOUS_MANIFEST.as_posix())
        self.assertEqual(manifest["previous_manifest_sha256"], PREVIOUS_MANIFEST_SHA256)
        additions = {
            PREVIOUS_MANIFEST.as_posix(),
            PREVIOUS_HISTORY_RUNNER.as_posix(),
            Path(__file__).name,
        }
        expected_scope = set(previous["scope"]) | additions | V20_CHANGES
        self.assertEqual(set(manifest["scope"]), expected_scope)
        self.assertEqual(set(manifest["files"]), expected_scope)

        for relative, expected in previous["files"].items():
            if relative in V20_CHANGES:
                continue
            data = (ROOT / relative).read_bytes()
            if relative in NORMALIZED_PREVIOUS_TESTS:
                data = normalized_previous_test(data)
            else:
                data = normalized(data)
            with self.subTest(unchanged_from_v19=relative):
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

    def test_v19_runs_on_exact_baseline_snapshot_and_v20_pins_current_checkout(self):
        workflow = (ROOT / ".github/workflows/release-checks.yml").read_text(encoding="utf-8")
        local_runner = (ROOT / "validation/run_local_release.py").read_text(encoding="utf-8")
        history_runner = (ROOT / PREVIOUS_HISTORY_RUNNER).read_text(encoding="utf-8")
        package = json.loads((ROOT / "validation/release_test_package_v1.json").read_text(encoding="utf-8"))

        self.assertIn("version=19", history_runner)
        self.assertIn(PREVIOUS_CANDIDATE, history_runner)
        self.assertIn("PQM_INTEGRATED_V19_SNAPSHOT_ARCHIVE_OUT", workflow)
        self.assertIn("PQM_INTEGRATED_V19_SNAPSHOT_ARCHIVE_SHA256", workflow)
        self.assertIn("integrated_v19_history", local_runner)
        self.assertIn("integrated_v20_current", local_runner)
        self.assertEqual(package["integrated_history_versions"], list(range(1, 20)))
        self.assertEqual(package["integrity_test_versions"], list(range(1, 21)))
        current_marker = "test_google_writer_integrated_candidate_integrity_v20 " + chr(92)
        current_tests = workflow.split(current_marker, 1)[1].split("- name: Install Playwright", 1)[0]
        self.assertNotIn("test_google_writer_integrated_candidate_integrity_v19", current_tests)
        self.assertIn("--mount \"type=bind,src=$RUNNER_TEMP/pqm-integrated-v19-snapshot.zip", workflow)


if __name__ == "__main__":
    unittest.main()
