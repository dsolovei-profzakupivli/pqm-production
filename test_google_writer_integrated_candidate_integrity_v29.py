"""Current candidate integrity v29; historical contracts v1-v28 stay immutable."""
from hashlib import sha256
import json
from pathlib import Path
import re
import unittest

from validation.integrated_snapshot_archive import canonical_eol

ROOT = Path(__file__).resolve().parent
MANIFEST = Path("validation/local_release_20261116/pqm_sync_ui_integrated_v29.json")
MANIFEST_SHA256 = "90db005f3aca6fae6f622885627b948f859cbb84d7fdca7e1ef9934a7c6212c7"
PREVIOUS_MANIFEST = Path("validation/local_release_20261116/pqm_sync_ui_integrated_v28.json")
PREVIOUS_MANIFEST_SHA256 = "21686ca702f1e57d8ec4b6b38c00e75ba7e21c133f600a8a5b31f64d8a988eb8"
PREVIOUS_CANDIDATE = "1e75aa05c1b2c2018a28b13d158283414843473d"
PREVIOUS_HISTORY_RUNNER = Path("validation/run_integrated_writer_ui_v28_history.py")
V29_CHANGES = {
    ".github/workflows/release-checks.yml",
    "edr_sync_v2.py",
    "test_release_gate_infrastructure.py",
    "validation/docker_release_gate.py",
    "validation/local_release_20260911/test_google_runtime.py",
    "validation/local_release_20260911/test_permanent_edr_sync_safety.py",
    "validation/release_test_package_v1.json",
    "validation/run_local_release.py",
    "validation/run_integrated_writer_ui_v28_history.py",
    "test_google_writer_integrated_candidate_integrity_v29.py",
}
NORMALIZED_INTEGRITY_TESTS = {
    f"test_google_writer_integrated_candidate_integrity_v{version}.py"
    for version in range(10, 30)
}


def normalized(data: bytes) -> bytes:
    return canonical_eol(data)


def normalized_test(data: bytes) -> bytes:
    return re.sub(
        rb'(?m)^MANIFEST_SHA256 = "(?:<manifest-sha256>|[0-9a-f]{64})"$',
        b'MANIFEST_SHA256 = "<manifest-sha256>"', normalized(data),
    )


class GoogleWriterIntegratedCandidateIntegrityV29(unittest.TestCase):
    def test_v29_pins_candidate_and_preserves_v1_v28_contracts(self):
        manifest_bytes = normalized((ROOT / MANIFEST).read_bytes())
        self.assertEqual(sha256(manifest_bytes).hexdigest(), MANIFEST_SHA256)
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        previous_bytes = normalized((ROOT / PREVIOUS_MANIFEST).read_bytes())
        self.assertEqual(sha256(previous_bytes).hexdigest(), PREVIOUS_MANIFEST_SHA256)
        previous = json.loads(previous_bytes.decode("utf-8"))
        self.assertEqual(manifest["contract"], "pqm-google-writer-sync-ui-integrated")
        self.assertEqual(manifest["version"], 29)
        self.assertEqual(manifest["previous_candidate_commit"], PREVIOUS_CANDIDATE)
        self.assertEqual(manifest["previous_manifest"], PREVIOUS_MANIFEST.as_posix())
        self.assertEqual(manifest["previous_manifest_sha256"], PREVIOUS_MANIFEST_SHA256)
        scope = set(previous["scope"]) | {
            PREVIOUS_MANIFEST.as_posix(), PREVIOUS_HISTORY_RUNNER.as_posix(),
            Path(__file__).name,
        } | V29_CHANGES
        self.assertEqual(set(manifest["scope"]), scope)
        self.assertEqual(set(manifest["files"]), scope)
        for relative, expected in previous["files"].items():
            if relative in V29_CHANGES:
                continue
            data = (ROOT / relative).read_bytes()
            data = normalized_test(data) if relative in NORMALIZED_INTEGRITY_TESTS else normalized(data)
            with self.subTest(unchanged_from_v28=relative):
                self.assertEqual(sha256(data).hexdigest(), expected)
        for relative, expected in manifest["files"].items():
            data = (ROOT / relative).read_bytes()
            data = normalized_test(data) if relative in NORMALIZED_INTEGRITY_TESTS else normalized(data)
            with self.subTest(current_pin=relative):
                self.assertEqual(sha256(data).hexdigest(), expected)

    def test_v28_history_and_shared_date_reason_contract_are_mandatory(self):
        workflow = (ROOT / ".github/workflows/release-checks.yml").read_text(encoding="utf-8")
        local_runner = (ROOT / "validation/run_local_release.py").read_text(encoding="utf-8")
        history_runner = (ROOT / PREVIOUS_HISTORY_RUNNER).read_text(encoding="utf-8")
        package = json.loads((ROOT / "validation/release_test_package_v1.json").read_text(encoding="utf-8"))
        sync_source = (ROOT / "edr_sync_v2.py").read_text(encoding="utf-8")
        self.assertIn("version=28", history_runner)
        self.assertIn(PREVIOUS_CANDIDATE, history_runner)
        self.assertIn(PREVIOUS_MANIFEST_SHA256, history_runner)
        self.assertIn("PQM_INTEGRATED_V28_SNAPSHOT_ARCHIVE_OUT", workflow)
        self.assertIn("PQM_INTEGRATED_V28_SNAPSHOT_ARCHIVE=/tmp/pqm-integrated-v28-snapshot.zip", workflow)
        self.assertIn("integrated_v28_history", local_runner)
        self.assertIn("integrated_v29_current", local_runner)
        self.assertIn("test_google_writer_integrated_candidate_integrity_v29", workflow)
        self.assertEqual(package["integrated_history_versions"], list(range(1, 29)))
        self.assertEqual(package["integrity_test_versions"], list(range(1, 30)))
        self.assertIn(PREVIOUS_HISTORY_RUNNER.name, package["supplemental_validation_files"])
        self.assertIn('"current_verification_date_missing"', sync_source)
        self.assertIn('"malformed_current_verification_datetime"', sync_source)


if __name__ == "__main__":
    unittest.main()
