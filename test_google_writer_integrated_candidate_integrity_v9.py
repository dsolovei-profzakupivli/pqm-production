"""Current integrated Writer/UI contract v9; v1-v8 remain immutable."""
from hashlib import sha256
import json
from pathlib import Path
import re
import unittest

from validation.integrated_snapshot_archive import (
    canonical_eol,
    validate_snapshot_archive,
    verify_fixture_sha256,
)


ROOT = Path(__file__).resolve().parent
MANIFEST = Path("validation/local_release_20261116/pqm_sync_ui_integrated_v9.json")
MANIFEST_SHA256 = "612c268e3555beecf79d9a32d2041d621e7b599cc7a42b8d89e3feecc52f1254"
PREVIOUS_MANIFEST = Path("validation/local_release_20261116/pqm_sync_ui_integrated_v8.json")
PREVIOUS_MANIFEST_SHA256 = "027783c537408f24656f7498d6d6bb6422a7db6b49e441e0d56fb2369e5b29d2"
PREVIOUS_TEST = "test_google_writer_integrated_candidate_integrity_v8.py"
PREVIOUS_CANDIDATE = "3b73ac89c6983662d7d8f0336e400373f337ea19"
V8_SNAPSHOT = "b7d8279ab8616553140ce7012685242631f6b1c3"
PREVIOUS_ARCHIVE = Path("validation/fixtures/pqm_sync_ui_integrated_v8_b7d8279.zip")
PREVIOUS_ARCHIVE_SHA256 = "6e190bdbbaa60e1bed371481a01162111c5060b2acdd94ba231ccbf6b09621d1"
PREVIOUS_HISTORY_RUNNER = Path("validation/run_integrated_writer_ui_v8_history.py")
ALLOWED_V9_CHANGES = {
    ".github/workflows/release-checks.yml",
    "app.js",
    "index.html",
    "queue_statistics_ui.js",
    "server.py",
    "test_release_gate_infrastructure.py",
    "validation/queue_statistics_ui.test.cjs",
    "validation/run_local_release.py",
    "validation/integrated_snapshot_archive.py",
}
V9_ADDITIONS = {
    "test_google_writer_integrated_candidate_integrity_v9.py",
    "validation/external_kpi_filters.cjs",
    "validation/fixtures/pqm_sync_ui_integrated_v8_b7d8279.zip",
    "validation/local_release_20260911/test_uo_work_queue.py",
    "validation/local_release_20261116/pqm_sync_ui_integrated_v8.json",
    "validation/run_integrated_writer_ui_v8_history.py",
    "validation/uo_work_page_layout_browser.cjs",
    "uo_work_page.css",
    "uo_work_progress.py",
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


class GoogleWriterIntegratedCandidateIntegrityV9(unittest.TestCase):
    def test_v9_pins_current_candidate_and_preserves_v1_v8_contracts(self):
        manifest_bytes = normalized((ROOT / MANIFEST).read_bytes())
        self.assertEqual(sha256(manifest_bytes).hexdigest(), MANIFEST_SHA256)
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        previous_bytes = normalized((ROOT / PREVIOUS_MANIFEST).read_bytes())
        self.assertEqual(sha256(previous_bytes).hexdigest(), PREVIOUS_MANIFEST_SHA256)
        previous = json.loads(previous_bytes.decode("utf-8"))
        self.assertEqual(manifest["contract"], "pqm-google-writer-sync-ui-integrated")
        self.assertEqual(manifest["version"], 9)
        self.assertEqual(manifest["previous_candidate_commit"], PREVIOUS_CANDIDATE)
        expected_scope = set(previous["scope"]) | {
            PREVIOUS_MANIFEST.as_posix(),
            PREVIOUS_ARCHIVE.as_posix(),
            PREVIOUS_HISTORY_RUNNER.as_posix(),
            *V9_ADDITIONS,
        }
        self.assertEqual(set(manifest["scope"]), expected_scope)
        self.assertEqual(set(manifest["files"]), expected_scope)

        previous_test = (ROOT / PREVIOUS_TEST).read_bytes()
        self.assertEqual(
            sha256(normalized_previous_test(previous_test)).hexdigest(),
            previous["files"][PREVIOUS_TEST],
        )
        for relative, expected in previous["files"].items():
            if relative in ALLOWED_V9_CHANGES or relative == PREVIOUS_TEST:
                continue
            with self.subTest(unchanged_from_v8=relative):
                self.assertEqual(
                    sha256(normalized((ROOT / relative).read_bytes())).hexdigest(),
                    expected,
                )

        for relative, expected in manifest["files"].items():
            data = (ROOT / relative).read_bytes()
            actual = sha256(normalized_self(data) if relative == Path(__file__).name else normalized(data)).hexdigest()
            with self.subTest(current_pin=relative):
                self.assertEqual(actual, expected)

    def test_v8_contract_runs_from_its_exact_immutable_snapshot(self):
        fixture_bytes = (ROOT / PREVIOUS_ARCHIVE).read_bytes()
        verify_fixture_sha256(fixture_bytes, PREVIOUS_ARCHIVE_SHA256, "git version pinned fixture")
        validate_snapshot_archive(
            fixture_bytes,
            manifest_relative=PREVIOUS_MANIFEST.as_posix(),
            expected_manifest_sha256=PREVIOUS_MANIFEST_SHA256,
            git_version_text="git version pinned fixture",
            self_normalize_paths={PREVIOUS_TEST},
        )
        runner = (ROOT / PREVIOUS_HISTORY_RUNNER).read_text(encoding="utf-8")
        self.assertIn(V8_SNAPSHOT, runner)
        self.assertIn("test_google_writer_integrated_candidate_integrity_v8", runner)
        self.assertIn(PREVIOUS_ARCHIVE.name, runner)
        workflow = (ROOT / ".github/workflows/release-checks.yml").read_text(encoding="utf-8")
        self.assertIn(PREVIOUS_HISTORY_RUNNER.as_posix(), workflow)
        self.assertIn("test_google_writer_integrated_candidate_integrity_v9", workflow)
        self.assertLess(workflow.index(PREVIOUS_HISTORY_RUNNER.as_posix()),
                        workflow.index("test_google_writer_integrated_candidate_integrity_v9"))

    def test_work_uo_browser_regression_is_part_of_release_gate(self):
        workflow = (ROOT / ".github/workflows/release-checks.yml").read_text(encoding="utf-8")
        self.assertIn("node validation/uo_work_page_layout_browser.cjs", workflow)


if __name__ == "__main__":
    unittest.main()
