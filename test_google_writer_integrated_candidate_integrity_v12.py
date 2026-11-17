"""Current integrated Writer/UI integrity contract v12; v1-v11 remain immutable."""
from hashlib import sha256
import json
from pathlib import Path
import re
import unittest

from validation.integrated_snapshot_archive import canonical_eol


ROOT = Path(__file__).resolve().parent
MANIFEST = Path("validation/local_release_20261116/pqm_sync_ui_integrated_v12.json")
MANIFEST_SHA256 = "f59ad8b9e1404935efa3020b164b47e2324e9635afb441dacb1b4933f6e598d8"
PREVIOUS_MANIFEST = Path("validation/local_release_20261116/pqm_sync_ui_integrated_v11.json")
PREVIOUS_MANIFEST_SHA256 = "e96321367b2e724f7dc452e35b9f418741ced4a2e8525191a505f7db6c190c3b"
PREVIOUS_TEST = "test_google_writer_integrated_candidate_integrity_v11.py"
NORMALIZED_TESTS = {
    "test_google_writer_integrated_candidate_integrity_v10.py",
    PREVIOUS_TEST,
}
PREVIOUS_HISTORY_RUNNER = Path("validation/run_integrated_writer_ui_v11_history.py")
PREVIOUS_CANDIDATE = "b2804d6e20e6b81b128508f285eb71e807f01ddf"
V12_CHANGES = {
    ".github/workflows/release-checks.yml",
    "test_release_gate_infrastructure.py",
    "validation/run_local_release.py",
    "validation/run_integrated_writer_ui_v10_history.py",
    "validation/integrated_git_snapshot.py",
    "validation/run_integrated_writer_ui_v11_history.py",
    "validation/local_release_20260911/test_integrated_snapshot_staging.py",
}


def normalized(data):
    return canonical_eol(data)


def normalized_self(data):
    data = normalized(data)
    return re.sub(
        rb'(?m)^MANIFEST_SHA256 = "(?:<manifest-sha256>|[0-9a-f]{64})"$',
        b'MANIFEST_SHA256 = "<manifest-sha256>"',
        data,
    )


def normalized_previous_test(data):
    return re.sub(
        rb'(?m)^MANIFEST_SHA256 = "(?:<manifest-sha256>|[0-9a-f]{64})"$',
        b'MANIFEST_SHA256 = "<manifest-sha256>"',
        normalized(data),
    )


class GoogleWriterIntegratedCandidateIntegrityV12(unittest.TestCase):
    def test_v12_pins_current_candidate_and_preserves_v1_v11_contracts(self):
        manifest_bytes = normalized((ROOT / MANIFEST).read_bytes())
        self.assertEqual(sha256(manifest_bytes).hexdigest(), MANIFEST_SHA256)
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        previous_bytes = normalized((ROOT / PREVIOUS_MANIFEST).read_bytes())
        self.assertEqual(sha256(previous_bytes).hexdigest(), PREVIOUS_MANIFEST_SHA256)
        previous = json.loads(previous_bytes.decode("utf-8"))

        self.assertEqual(manifest["contract"], "pqm-google-writer-sync-ui-integrated")
        self.assertEqual(manifest["version"], 12)
        self.assertEqual(manifest["previous_candidate_commit"], PREVIOUS_CANDIDATE)
        self.assertEqual(manifest["previous_manifest"], PREVIOUS_MANIFEST.as_posix())
        self.assertEqual(manifest["previous_manifest_sha256"], PREVIOUS_MANIFEST_SHA256)
        additions = {
            PREVIOUS_MANIFEST.as_posix(),
            PREVIOUS_HISTORY_RUNNER.as_posix(),
            Path(__file__).name,
            "validation/integrated_git_snapshot.py",
            "validation/local_release_20260911/test_integrated_snapshot_staging.py",
        }
        expected_scope = set(previous["scope"]) | additions
        self.assertEqual(set(manifest["scope"]), expected_scope)
        self.assertEqual(set(manifest["files"]), expected_scope)

        for relative, expected in previous["files"].items():
            if relative in V12_CHANGES:
                continue
            data = (ROOT / relative).read_bytes()
            if relative in NORMALIZED_TESTS:
                data = normalized_previous_test(data)
            else:
                data = normalized(data)
            with self.subTest(unchanged_from_v11=relative):
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

    def test_history_archives_are_staged_from_git_and_mounted_read_only(self):
        workflow = (ROOT / ".github/workflows/release-checks.yml").read_text(encoding="utf-8")
        local_runner = (ROOT / "validation/run_local_release.py").read_text(encoding="utf-8")
        v10_runner = (ROOT / "validation/run_integrated_writer_ui_v10_history.py").read_text(encoding="utf-8")
        v11_runner = (ROOT / PREVIOUS_HISTORY_RUNNER).read_text(encoding="utf-8")
        snapshot_helper = (ROOT / "validation/integrated_git_snapshot.py").read_text(encoding="utf-8")

        for version, runner in ((10, v10_runner), (11, v11_runner)):
            self.assertIn(f"version={version}", runner)
            self.assertIn(f"PQM_INTEGRATED_V{version}_SNAPSHOT_ARCHIVE_SHA256", workflow)
            self.assertIn(f"PQM_INTEGRATED_V{version}_SNAPSHOT_ARCHIVE_OUT", workflow)
        self.assertIn('prefix = f"PQM_INTEGRATED_V{version}_SNAPSHOT_ARCHIVE"', snapshot_helper)
        self.assertIn("snapshot_archive_for_runner", v10_runner)
        self.assertIn("snapshot_archive_for_runner", v11_runner)
        self.assertIn("integrated_v10_history", local_runner)
        self.assertIn("integrated_v11_history", local_runner)
        self.assertIn("integrated_v12_current", local_runner)
        self.assertNotIn("COPY .git", workflow)
        self.assertIn("dst=/tmp/pqm-integrated-v10-snapshot.zip,readonly", workflow)
        self.assertIn("dst=/tmp/pqm-integrated-v11-snapshot.zip,readonly", workflow)


if __name__ == "__main__":
    unittest.main()
