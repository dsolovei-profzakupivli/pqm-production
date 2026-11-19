"""Current integrated Writer/UI integrity contract v13; v1-v12 remain immutable."""
from hashlib import sha256
import json
from pathlib import Path
import re
import unittest

from validation.integrated_snapshot_archive import canonical_eol


ROOT = Path(__file__).resolve().parent
MANIFEST = Path("validation/local_release_20261116/pqm_sync_ui_integrated_v13.json")
MANIFEST_SHA256 = "73dd8da248bf96fb925af4e606c4895bef6c59e55216d0bfa95fa11b244d10da"
PREVIOUS_MANIFEST = Path("validation/local_release_20261116/pqm_sync_ui_integrated_v12.json")
PREVIOUS_MANIFEST_SHA256 = "f59ad8b9e1404935efa3020b164b47e2324e9635afb441dacb1b4933f6e598d8"
PREVIOUS_TEST = "test_google_writer_integrated_candidate_integrity_v12.py"
PREVIOUS_HISTORY_RUNNER = Path("validation/run_integrated_writer_ui_v12_history.py")
PREVIOUS_CANDIDATE = "f8def8951eb9f95f1a5139bd7138681c4c1a9d7b"
NORMALIZED_TESTS = {
    "test_google_writer_integrated_candidate_integrity_v10.py",
    "test_google_writer_integrated_candidate_integrity_v11.py",
    PREVIOUS_TEST,
}
V13_CHANGES = {
    ".github/workflows/release-checks.yml",
    "test_release_gate_infrastructure.py",
    "validation/run_local_release.py",
    "validation/run_integrated_writer_ui_v12_history.py",
    "validation/release_test_package.py",
    "validation/release_test_package_v1.json",
    "validation/local_release_20260911/test_release_test_package.py",
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


class GoogleWriterIntegratedCandidateIntegrityV13(unittest.TestCase):
    def test_v13_pins_current_candidate_and_preserves_v1_v12_contracts(self):
        manifest_bytes = normalized((ROOT / MANIFEST).read_bytes())
        self.assertEqual(sha256(manifest_bytes).hexdigest(), MANIFEST_SHA256)
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        previous_bytes = normalized((ROOT / PREVIOUS_MANIFEST).read_bytes())
        self.assertEqual(sha256(previous_bytes).hexdigest(), PREVIOUS_MANIFEST_SHA256)
        previous = json.loads(previous_bytes.decode("utf-8"))

        self.assertEqual(manifest["contract"], "pqm-google-writer-sync-ui-integrated")
        self.assertEqual(manifest["version"], 13)
        self.assertEqual(manifest["previous_candidate_commit"], PREVIOUS_CANDIDATE)
        self.assertEqual(manifest["previous_manifest"], PREVIOUS_MANIFEST.as_posix())
        self.assertEqual(manifest["previous_manifest_sha256"], PREVIOUS_MANIFEST_SHA256)
        additions = {
            PREVIOUS_MANIFEST.as_posix(),
            PREVIOUS_HISTORY_RUNNER.as_posix(),
            Path(__file__).name,
            "validation/release_test_package.py",
            "validation/release_test_package_v1.json",
            "validation/local_release_20260911/test_release_test_package.py",
        }
        expected_scope = set(previous["scope"]) | additions
        self.assertEqual(set(manifest["scope"]), expected_scope)
        self.assertEqual(set(manifest["files"]), expected_scope)

        for relative, expected in previous["files"].items():
            if relative in V13_CHANGES:
                continue
            data = (ROOT / relative).read_bytes()
            if relative in NORMALIZED_TESTS:
                data = normalized_previous_test(data)
            else:
                data = normalized(data)
            with self.subTest(unchanged_from_v12=relative):
                self.assertEqual(sha256(data).hexdigest(), expected)

        for relative, expected in manifest["files"].items():
            data = (ROOT / relative).read_bytes()
            if relative == Path(__file__).name:
                data = normalized_self(data)
            elif relative in NORMALIZED_TESTS:
                data = normalized_previous_test(data)
            else:
                data = normalized(data)
            with self.subTest(current_pin=relative):
                self.assertEqual(sha256(data).hexdigest(), expected)

    def test_v12_is_historical_and_v13_is_current(self):
        workflow = (ROOT / ".github/workflows/release-checks.yml").read_text(encoding="utf-8")
        local_runner = (ROOT / "validation/run_local_release.py").read_text(encoding="utf-8")
        history_runner = (ROOT / PREVIOUS_HISTORY_RUNNER).read_text(encoding="utf-8")
        package_registry = json.loads(
            (ROOT / "validation/release_test_package_v1.json").read_text(encoding="utf-8")
        )

        self.assertIn("version=12", history_runner)
        self.assertIn("PQM_INTEGRATED_V12_SNAPSHOT_ARCHIVE_SHA256", workflow)
        self.assertIn("PQM_INTEGRATED_V12_SNAPSHOT_ARCHIVE_OUT", workflow)
        self.assertIn("integrated_v12_history", local_runner)
        self.assertIn("integrated_v13_current", local_runner)
        self.assertEqual(package_registry["integrated_history_versions"], list(range(1, 13)))
        self.assertIn("run_integrated_writer_ui_v10_history.py",
                      package_registry["supplemental_validation_files"]
                      + [f"run_integrated_writer_ui_v{i}_history.py"
                         for i in package_registry["integrated_history_versions"]])
        current_tests = workflow.split(
            "test_google_writer_integrated_candidate_integrity_v13 \\", 1
        )[1].split("- name: Install Playwright", 1)[0]
        self.assertNotIn("test_google_writer_integrated_candidate_integrity_v12", current_tests)
        self.assertIn("dst=/tmp/pqm-integrated-v12-snapshot.zip,readonly", workflow)
        self.assertNotIn("COPY .git", workflow)


if __name__ == "__main__":
    unittest.main()
