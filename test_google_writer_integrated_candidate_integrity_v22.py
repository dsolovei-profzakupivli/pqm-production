"""Current integrated Writer/UI contract v22; historical v1-v21 remain immutable."""
from hashlib import sha256
import json
from pathlib import Path
import re
import unittest

from validation.integrated_snapshot_archive import canonical_eol


ROOT = Path(__file__).resolve().parent
MANIFEST = Path("validation/local_release_20261116/pqm_sync_ui_integrated_v22.json")
MANIFEST_SHA256 = "fbe60d95b335aa9da53dbe161c8fb67cdf3679722472156655c27cdf77877b59"
PREVIOUS_MANIFEST = Path("validation/local_release_20261116/pqm_sync_ui_integrated_v21.json")
PREVIOUS_MANIFEST_SHA256 = "d0136fe5103543c9594c8581f600c2ff7a0657c521e965fdb5cb350b04df49b6"
PREVIOUS_HISTORY_RUNNER = Path("validation/run_integrated_writer_ui_v21_history.py")
PREVIOUS_CANDIDATE = "2ca88abe5cfcd83afec90f3f6b4a8c0015c3c807"
NORMALIZED_PREVIOUS_TESTS = {
    f"test_google_writer_integrated_candidate_integrity_v{version}.py"
    for version in range(10, 22)
}
V22_CHANGES = {
    ".github/workflows/release-checks.yml",
    "test_release_gate_infrastructure.py",
    "validation/release_test_package_v1.json",
    "validation/run_local_release.py",
    "validation/local_release_20260911/test_release_test_package.py",
    "validation/ui_improvements_browser.cjs",
    "validation/table_widths_native_browser.cjs",
    "validation/run_integrated_writer_ui_v21_history.py",
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


class GoogleWriterIntegratedCandidateIntegrityV22(unittest.TestCase):
    def test_v22_pins_current_candidate_and_preserves_v1_v21_contracts(self):
        manifest_bytes = normalized((ROOT / MANIFEST).read_bytes())
        self.assertEqual(sha256(manifest_bytes).hexdigest(), MANIFEST_SHA256)
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        previous_bytes = normalized((ROOT / PREVIOUS_MANIFEST).read_bytes())
        self.assertEqual(sha256(previous_bytes).hexdigest(), PREVIOUS_MANIFEST_SHA256)
        previous = json.loads(previous_bytes.decode("utf-8"))

        self.assertEqual(manifest["contract"], "pqm-google-writer-sync-ui-integrated")
        self.assertEqual(manifest["version"], 22)
        self.assertEqual(manifest["previous_candidate_commit"], PREVIOUS_CANDIDATE)
        self.assertEqual(manifest["previous_manifest"], PREVIOUS_MANIFEST.as_posix())
        self.assertEqual(manifest["previous_manifest_sha256"], PREVIOUS_MANIFEST_SHA256)
        additions = {
            PREVIOUS_MANIFEST.as_posix(),
            PREVIOUS_HISTORY_RUNNER.as_posix(),
            Path(__file__).name,
        }
        expected_scope = set(previous["scope"]) | additions | V22_CHANGES
        self.assertEqual(set(manifest["scope"]), expected_scope)
        self.assertEqual(set(manifest["files"]), expected_scope)

        for relative, expected in previous["files"].items():
            if relative in V22_CHANGES:
                continue
            data = (ROOT / relative).read_bytes()
            if relative in NORMALIZED_PREVIOUS_TESTS:
                data = normalized_previous_test(data)
            else:
                data = normalized(data)
            with self.subTest(unchanged_from_v21=relative):
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

    def test_v21_runs_on_exact_baseline_snapshot_and_v22_pins_current_checkout(self):
        workflow = (ROOT / ".github/workflows/release-checks.yml").read_text(encoding="utf-8")
        local_runner = (ROOT / "validation/run_local_release.py").read_text(encoding="utf-8")
        history_runner = (ROOT / PREVIOUS_HISTORY_RUNNER).read_text(encoding="utf-8")
        package = json.loads((ROOT / "validation/release_test_package_v1.json").read_text(encoding="utf-8"))

        self.assertIn("version=21", history_runner)
        self.assertIn(PREVIOUS_CANDIDATE, history_runner)
        self.assertIn("PQM_INTEGRATED_V21_SNAPSHOT_ARCHIVE_OUT", workflow)
        self.assertIn("PQM_INTEGRATED_V21_SNAPSHOT_ARCHIVE_SHA256", workflow)
        self.assertIn("integrated_v21_history", local_runner)
        self.assertIn("integrated_v22_current", local_runner)
        self.assertEqual(package["integrated_history_versions"], list(range(1, 22)))
        self.assertEqual(package["integrity_test_versions"], list(range(1, 23)))
        current_marker = "test_google_writer_integrated_candidate_integrity_v22 " + chr(92)
        current_tests = workflow.split(current_marker, 1)[1].split("- name: Install Playwright", 1)[0]
        self.assertNotIn("test_google_writer_integrated_candidate_integrity_v21", current_tests)
        self.assertIn("--mount \"type=bind,src=$RUNNER_TEMP/pqm-integrated-v21-snapshot.zip", workflow)


if __name__ == "__main__":
    unittest.main()
