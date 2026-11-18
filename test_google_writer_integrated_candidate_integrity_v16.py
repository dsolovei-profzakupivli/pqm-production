"""Current integrated Writer/UI contract v16; historical v1-v15 remain immutable."""
from hashlib import sha256
import json
from pathlib import Path
import re
import unittest

from validation.integrated_snapshot_archive import canonical_eol


ROOT = Path(__file__).resolve().parent
MANIFEST = Path("validation/local_release_20261116/pqm_sync_ui_integrated_v16.json")
MANIFEST_SHA256 = "859050d7353edf2d776679ce7a12b0cbbd158f7b1a314e2a88234422a5699488"
PREVIOUS_MANIFEST = Path("validation/local_release_20261116/pqm_sync_ui_integrated_v15.json")
PREVIOUS_MANIFEST_SHA256 = "5097d801488b83b4bcae85650d7074ea1a13e755e390880258eb382ce0378977"
PREVIOUS_TEST = "test_google_writer_integrated_candidate_integrity_v15.py"
PREVIOUS_HISTORY_RUNNER = Path("validation/run_integrated_writer_ui_v15_history.py")
PREVIOUS_CANDIDATE = "86fe0d85bc36f431af6708918c07add73144f9db"
NORMALIZED_PREVIOUS_TESTS = {
    f"test_google_writer_integrated_candidate_integrity_v{version}.py"
    for version in range(10, 16)
}
V16_CHANGES = {
    ".github/workflows/release-checks.yml",
    "app.js",
    "index.html",
    "application_officers.py",
    "server.py",
    "test_release_gate_infrastructure.py",
    "uo_work_progress.py",
    "uo_work_queue.py",
    "validation/local_release_20260911/test_application_page_first.py",
    "validation/local_release_20260911/test_final_local_stabilization.py",
    "validation/local_release_20260911/test_nazk_workflow.py",
    "validation/local_release_20260911/test_uo_work_queue.py",
    "validation/local_release_20260911/test_uo_work_queue_http.py",
    "validation/local_release_20260911/test_release_test_package.py",
    "validation/queue_statistics_ui.test.cjs",
    "validation/release_test_package_v1.json",
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


class GoogleWriterIntegratedCandidateIntegrityV16(unittest.TestCase):
    def test_v16_pins_current_candidate_and_preserves_v1_v15_contracts(self):
        manifest_bytes = normalized((ROOT / MANIFEST).read_bytes())
        self.assertEqual(sha256(manifest_bytes).hexdigest(), MANIFEST_SHA256)
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        previous_bytes = normalized((ROOT / PREVIOUS_MANIFEST).read_bytes())
        self.assertEqual(sha256(previous_bytes).hexdigest(), PREVIOUS_MANIFEST_SHA256)
        previous = json.loads(previous_bytes.decode("utf-8"))

        self.assertEqual(manifest["contract"], "pqm-google-writer-sync-ui-integrated")
        self.assertEqual(manifest["version"], 16)
        self.assertEqual(manifest["previous_candidate_commit"], PREVIOUS_CANDIDATE)
        self.assertEqual(manifest["previous_manifest"], PREVIOUS_MANIFEST.as_posix())
        self.assertEqual(manifest["previous_manifest_sha256"], PREVIOUS_MANIFEST_SHA256)
        additions = {
            PREVIOUS_MANIFEST.as_posix(),
            PREVIOUS_HISTORY_RUNNER.as_posix(),
            Path(__file__).name,
        }
        expected_scope = set(previous["scope"]) | additions | V16_CHANGES
        self.assertEqual(set(manifest["scope"]), expected_scope)
        self.assertEqual(set(manifest["files"]), expected_scope)

        for relative, expected in previous["files"].items():
            if relative in V16_CHANGES:
                continue
            data = (ROOT / relative).read_bytes()
            if relative in NORMALIZED_PREVIOUS_TESTS:
                data = normalized_previous_test(data)
            else:
                data = normalized(data)
            with self.subTest(unchanged_from_v15=relative):
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

    def test_v15_is_snapshot_v16_is_current_and_all_integrity_routes_are_preserved(self):
        workflow = (ROOT / ".github/workflows/release-checks.yml").read_text(encoding="utf-8")
        local_runner = (ROOT / "validation/run_local_release.py").read_text(encoding="utf-8")
        history_runner = (ROOT / PREVIOUS_HISTORY_RUNNER).read_text(encoding="utf-8")
        package_registry = json.loads(
            (ROOT / "validation/release_test_package_v1.json").read_text(encoding="utf-8")
        )

        self.assertIn("version=15", history_runner)
        self.assertIn(PREVIOUS_CANDIDATE, history_runner)
        self.assertIn("PQM_INTEGRATED_V15_SNAPSHOT_ARCHIVE_OUT", workflow)
        self.assertIn("PQM_INTEGRATED_V15_SNAPSHOT_ARCHIVE_SHA256", workflow)
        self.assertIn("integrated_v15_history", local_runner)
        self.assertIn("integrated_v16_current", local_runner)
        self.assertEqual(package_registry["integrated_history_versions"], list(range(1, 16)))
        self.assertEqual(package_registry["integrity_test_versions"], list(range(1, 17)))
        self.assertIn("application_officers.py", package_registry["root_level_release_files"])
        current_marker = "test_google_writer_integrated_candidate_integrity_v16 " + chr(92)
        current_tests = workflow.split(current_marker, 1)[1].split(
            "- name: Install Playwright", 1
        )[0]
        self.assertIn("validation.local_release_20260911.test_uo_work_queue_http", current_tests)
        self.assertIn("test_release_gate_infrastructure.ReleaseGateInfrastructureTests", current_tests)
        self.assertNotIn("test_google_writer_integrated_candidate_integrity_v15", current_tests)
        self.assertIn("--mount \"type=bind,src=$RUNNER_TEMP/pqm-integrated-v15-snapshot.zip", workflow)
        self.assertIn("PQM_INTEGRATED_V15_SNAPSHOT_ARCHIVE=/tmp/pqm-integrated-v15-snapshot.zip", workflow)
