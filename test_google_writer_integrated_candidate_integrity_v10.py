"""Current integrated Writer/UI integrity contract v10; v1-v9 stay immutable."""
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
import unittest
import zipfile

from validation.integrated_snapshot_archive import (
    SnapshotArchiveError,
    canonical_eol,
    validate_snapshot_archive,
    verify_fixture_sha256,
)


ROOT = Path(__file__).resolve().parent
MANIFEST = Path("validation/local_release_20261116/pqm_sync_ui_integrated_v10.json")
MANIFEST_SHA256 = "f06808711ce9e961dce3b0c31c2bca084d170493d1ae83d4c421ce8c312c4727"
PREVIOUS_MANIFEST = Path("validation/local_release_20261116/pqm_sync_ui_integrated_v9.json")
PREVIOUS_MANIFEST_SHA256 = "612c268e3555beecf79d9a32d2041d621e7b599cc7a42b8d89e3feecc52f1254"
PREVIOUS_TEST = "test_google_writer_integrated_candidate_integrity_v9.py"
PREVIOUS_CANDIDATE = "8e74484d3961b70355a4868c72336e22fad9d8de"
V9_HISTORY_RUNNER = Path("validation/run_integrated_writer_ui_v9_history.py")
V9_HISTORY_FIXTURE = Path("validation/fixtures/pqm_sync_ui_integrated_v9_8e74484.zip")
V9_HISTORY_FIXTURE_SHA256 = "c6f04f1b5d149f487445e34089a2eaf06ab9e27346d856bf59ec46e5bc944550"
V10_CHANGES = {
    ".github/workflows/release-checks.yml",
    "index.html",
    "queue_statistics_ui.js",
    "server.py",
    "test_release_gate_infrastructure.py",
    "validation/integrated_snapshot_archive.py",
    "validation/local_release_20260911/test_uo_work_queue.py",
    "validation/queue_statistics_ui.test.cjs",
    "validation/run_local_release.py",
    "validation/run_integrated_writer_ui_v9_history.py",
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


def normalized_v9_test(data):
    return re.sub(
        rb'(?m)^MANIFEST_SHA256 = "(?:<manifest-sha256>|[0-9a-f]{64})"$',
        b'MANIFEST_SHA256 = "<manifest-sha256>"',
        normalized(data),
    )


class GoogleWriterIntegratedCandidateIntegrityV10(unittest.TestCase):
    def test_v10_pins_current_candidate_and_preserves_v1_v9_contracts(self):
        manifest_bytes = normalized((ROOT / MANIFEST).read_bytes())
        self.assertEqual(sha256(manifest_bytes).hexdigest(), MANIFEST_SHA256)
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        previous_bytes = normalized((ROOT / PREVIOUS_MANIFEST).read_bytes())
        self.assertEqual(sha256(previous_bytes).hexdigest(), PREVIOUS_MANIFEST_SHA256)
        previous = json.loads(previous_bytes.decode("utf-8"))

        self.assertEqual(manifest["contract"], "pqm-google-writer-sync-ui-integrated")
        self.assertEqual(manifest["version"], 10)
        self.assertEqual(manifest["previous_candidate_commit"], PREVIOUS_CANDIDATE)
        self.assertEqual(manifest["previous_manifest"], PREVIOUS_MANIFEST.as_posix())
        self.assertEqual(manifest["previous_manifest_sha256"], PREVIOUS_MANIFEST_SHA256)
        expected_scope = set(previous["scope"]) | {
            PREVIOUS_MANIFEST.as_posix(),
            V9_HISTORY_RUNNER.as_posix(),
            V9_HISTORY_FIXTURE.as_posix(),
            Path(__file__).name,
        }
        self.assertEqual(set(manifest["scope"]), expected_scope)
        self.assertEqual(set(manifest["files"]), expected_scope)

        for relative, expected in previous["files"].items():
            if relative in V10_CHANGES:
                continue
            data = (ROOT / relative).read_bytes()
            if relative == PREVIOUS_TEST:
                data = normalized_v9_test(data)
            else:
                data = normalized(data)
            with self.subTest(unchanged_from_v9=relative):
                self.assertEqual(sha256(data).hexdigest(), expected)

        for relative, expected in manifest["files"].items():
            data = (ROOT / relative).read_bytes()
            actual = sha256(
                normalized_self(data) if relative == Path(__file__).name else normalized(data)
            ).hexdigest()
            with self.subTest(current_pin=relative):
                self.assertEqual(actual, expected)

    def test_type_filter_uses_existing_classes_without_future_manual_type(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        expected = (
            'value="individual_entrepreneur"',
            'value="legal_entity"',
            'value="foreign_legal_entity"',
            'value="unknown"',
        )
        for value in expected:
            with self.subTest(type_value=value):
                self.assertIn(value, html)
        self.assertNotIn("Тестові / неіснуючі", html)

    def test_v9_is_routed_to_its_pinned_revision_and_v10_runs_on_current_checkout(self):
        workflow = (ROOT / ".github/workflows/release-checks.yml").read_text(encoding="utf-8")
        runner = (ROOT / "validation/run_integrated_writer_ui_v9_history.py").read_text(encoding="utf-8")
        self.assertIn("8e74484d3961b70355a4868c72336e22fad9d8de", runner)
        self.assertIn("run_integrated_writer_ui_v9_history.py", workflow)
        self.assertIn("test_google_writer_integrated_candidate_integrity_v10", workflow)

    def test_v9_history_fixture_is_exact_and_matches_its_v9_manifest(self):
        archive = (ROOT / V9_HISTORY_FIXTURE).read_bytes()
        verify_fixture_sha256(archive, V9_HISTORY_FIXTURE_SHA256, "git version pinned fixture")
        try:
            validate_snapshot_archive(
                archive,
                manifest_relative=PREVIOUS_MANIFEST.as_posix(),
                expected_manifest_sha256=PREVIOUS_MANIFEST_SHA256,
                git_version_text="git version pinned fixture",
                self_normalize_paths={PREVIOUS_TEST},
            )
        except SnapshotArchiveError as exc:
            self.fail(f"v9 snapshot fixture does not match its immutable manifest: {exc}")
        with zipfile.ZipFile(BytesIO(archive)) as bundle:
            self.assertIn(PREVIOUS_TEST, bundle.namelist())


if __name__ == "__main__":
    unittest.main()
