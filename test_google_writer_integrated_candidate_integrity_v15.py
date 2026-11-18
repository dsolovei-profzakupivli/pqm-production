"""Current integrated Writer/UI integrity contract v15; v1-v14 stay immutable."""
from hashlib import sha256
import json
from pathlib import Path
import re
import unittest

from validation.integrated_snapshot_archive import canonical_eol


ROOT = Path(__file__).resolve().parent
MANIFEST = Path("validation/local_release_20261116/pqm_sync_ui_integrated_v15.json")
MANIFEST_SHA256 = "5097d801488b83b4bcae85650d7074ea1a13e755e390880258eb382ce0378977"
PREVIOUS_MANIFEST = Path("validation/local_release_20261116/pqm_sync_ui_integrated_v14.json")
PREVIOUS_MANIFEST_SHA256 = "24ebc7786cfe49722b9427eea5425102f5697198aecbbc83dfd156c1a226d727"
PREVIOUS_TEST = "test_google_writer_integrated_candidate_integrity_v14.py"
PREVIOUS_HISTORY_RUNNER = Path("validation/run_integrated_writer_ui_v14_history.py")
PREVIOUS_CANDIDATE = "c7fb5addfe21829a199d2b6db7f54ec03dee24ca"
NORMALIZED_PREVIOUS_TESTS = {
    "test_google_writer_integrated_candidate_integrity_v10.py",
    "test_google_writer_integrated_candidate_integrity_v11.py",
    "test_google_writer_integrated_candidate_integrity_v12.py",
    "test_google_writer_integrated_candidate_integrity_v13.py",
    "test_google_writer_integrated_candidate_integrity_v14.py",
}
V15_CHANGES = {
    "AGENTS.md",
    ".github/workflows/release-checks.yml",
    "app.js",
    "index.html",
    "queue_statistics_ui.js",
    "server.py",
    "supplier_manual_classification.py",
    "test_release_gate_infrastructure.py",
    "uo_work_page.css",
    "uo_work_progress.py",
    "validation/local_release_20260911/test_uo_work_queue_http.py",
    "validation/local_release_20260911/test_release_test_package.py",
    "validation/queue_statistics_ui.test.cjs",
    "validation/uo_work_page_layout_browser.cjs",
    "validation/release_test_package_v1.json",
    "validation/run_local_release.py",
}


def normalized(data):
    return canonical_eol(data)


def normalized_self(data):
    return re.sub(
        rb'(?m)^MANIFEST_SHA256 = "(?:<manifest-sha256>|[0-9a-f]{64})"$',
        b'MANIFEST_SHA256 = "<manifest-sha256>"',
        normalized(data),
    )


def normalized_previous_test(data):
    return re.sub(
        rb'(?m)^MANIFEST_SHA256 = "(?:<manifest-sha256>|[0-9a-f]{64})"$',
        b'MANIFEST_SHA256 = "<manifest-sha256>"',
        normalized(data),
    )


class GoogleWriterIntegratedCandidateIntegrityV15(unittest.TestCase):
    def test_v15_pins_current_candidate_and_preserves_v1_v14_contracts(self):
        manifest_bytes = normalized((ROOT / MANIFEST).read_bytes())
        self.assertEqual(sha256(manifest_bytes).hexdigest(), MANIFEST_SHA256)
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        previous_bytes = normalized((ROOT / PREVIOUS_MANIFEST).read_bytes())
        self.assertEqual(sha256(previous_bytes).hexdigest(), PREVIOUS_MANIFEST_SHA256)
        previous = json.loads(previous_bytes.decode("utf-8"))

        self.assertEqual(manifest["contract"], "pqm-google-writer-sync-ui-integrated")
        self.assertEqual(manifest["version"], 15)
        self.assertEqual(manifest["previous_candidate_commit"], PREVIOUS_CANDIDATE)
        self.assertEqual(manifest["previous_manifest"], PREVIOUS_MANIFEST.as_posix())
        self.assertEqual(manifest["previous_manifest_sha256"], PREVIOUS_MANIFEST_SHA256)
        additions = {
            PREVIOUS_MANIFEST.as_posix(),
            PREVIOUS_HISTORY_RUNNER.as_posix(),
            Path(__file__).name,
            "AGENTS.md",
            "supplier_manual_classification.py",
        }
        expected_scope = set(previous["scope"]) | additions
        self.assertEqual(set(manifest["scope"]), expected_scope)
        self.assertEqual(set(manifest["files"]), expected_scope)

        for relative, expected in previous["files"].items():
            if relative in V15_CHANGES:
                continue
            data = (ROOT / relative).read_bytes()
            if relative in NORMALIZED_PREVIOUS_TESTS:
                data = normalized_previous_test(data)
            else:
                data = normalized(data)
            with self.subTest(unchanged_from_v14=relative):
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

    def test_v14_is_historical_v15_is_current_and_browser_gate_is_complete(self):
        workflow = (ROOT / ".github/workflows/release-checks.yml").read_text(encoding="utf-8")
        local_runner = (ROOT / "validation/run_local_release.py").read_text(encoding="utf-8")
        history_runner = (ROOT / PREVIOUS_HISTORY_RUNNER).read_text(encoding="utf-8")
        package_registry = json.loads(
            (ROOT / "validation/release_test_package_v1.json").read_text(encoding="utf-8")
        )

        self.assertIn("version=14", history_runner)
        self.assertIn("766d1ed9354e1af56e19d50d50c818ff701dd85e", history_runner)
        self.assertIn("PQM_INTEGRATED_V14_SNAPSHOT_ARCHIVE_OUT", workflow)
        self.assertIn("PQM_INTEGRATED_V14_SNAPSHOT_ARCHIVE_SHA256", workflow)
        self.assertIn("integrated_v14_history", local_runner)
        self.assertIn("integrated_v15_current", local_runner)
        self.assertEqual(package_registry["integrated_history_versions"], list(range(1, 15)))
        self.assertEqual(package_registry["integrity_test_versions"], list(range(1, 16)))
        current_marker = "test_google_writer_integrated_candidate_integrity_v15 " + chr(92)
        current_tests = workflow.split(current_marker, 1)[1].split(
            "- name: Install Playwright", 1
        )[0]
        self.assertIn("validation.local_release_20260911.test_uo_work_queue_http", current_tests)
        self.assertIn("validation/queue_statistics_ui.test.cjs", workflow)
        self.assertNotIn("test_google_writer_integrated_candidate_integrity_v14", current_tests)
        self.assertIn("npm install --prefix \"$RUNNER_TEMP/pqm-playwright\"", workflow)
        self.assertIn('node_modules/.bin/playwright" install --with-deps chromium', workflow)
        browser_block = workflow.split("- name: Run Appeals browser regressions", 1)[1].split("- name:", 1)[0]
        self.assertIn("node validation/uo_work_page_layout_browser.cjs", browser_block)
        self.assertIn("dst=/tmp/pqm-integrated-v14-snapshot.zip,readonly", workflow)
        self.assertNotIn("COPY .git", workflow)


if __name__ == "__main__":
    unittest.main()
