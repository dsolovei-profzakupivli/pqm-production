"""V31 pins the Apply fix and UX while routing V30 through its exact snapshot."""
from hashlib import sha256
import json
from pathlib import Path
import re
import unittest

from validation.integrated_snapshot_archive import canonical_eol

ROOT = Path(__file__).resolve().parent
MANIFEST = Path("validation/local_release_20261116/pqm_sync_ui_integrated_v31.json")
MANIFEST_SHA256 = "f9149e87a410f8bf3527dc6edbd85da5a408ed260959d94da07cf6293555d006"
PREVIOUS_MANIFEST = Path("validation/local_release_20261116/pqm_sync_ui_integrated_v30.json")
PREVIOUS_MANIFEST_SHA256 = "2ae6efcec557efdbe99dce5411824aa01b9391087ea2b1d0f32453a832921bce"
PREVIOUS_CANDIDATE = "3a0d3bbacc0237fd0916bcfdb9b8e2b7c01fba40"
V31_CHANGES = {
    ".github/workflows/release-checks.yml",
    "app.js",
    "edr_sync_v2.py",
    "index.html",
    "server.py",
    "styles.css",
    "test_google_writer_integrated_candidate_integrity_v31.py",
    "test_release_gate_infrastructure.py",
    "validation/document_release_history_v2.py",
    "validation/docker_release_gate.py",
    "validation/docker_release_gate_csv_ui_v3.py",
    "validation/local_release_20260911/test_supplier_edr_apply_v31.py",
    "validation/local_release_20260911/test_edr_sync_v2.py",
    "validation/release_test_package_integrated_v11.json",
    "validation/run_local_release.py",
    "validation/run_integrated_writer_ui_v30_history.py",
    "validation/supplier_edr_apply_modal_browser.cjs",
    "validation/fixtures/document_release_parent_0678d46_addendum_v31.zip",
    "validation/fixtures/document_release_v1_source_6e0a9ef_addendum_v31.zip",
}
NORMALIZED_TESTS = {
    f"test_google_writer_integrated_candidate_integrity_v{version}.py"
    for version in range(10, 32)
}


def normalized(data: bytes) -> bytes:
    return canonical_eol(data)


def normalized_test(data: bytes) -> bytes:
    return re.sub(
        rb'(?m)^MANIFEST_SHA256 = "(?:<manifest-sha256>|[0-9a-f]{64})"$',
        b'MANIFEST_SHA256 = "<manifest-sha256>"', normalized(data),
    )


class GoogleWriterIntegratedCandidateIntegrityV31(unittest.TestCase):
    def test_v31_pins_candidate_and_preserves_historical_v30(self):
        manifest_bytes = normalized((ROOT / MANIFEST).read_bytes())
        self.assertEqual(sha256(manifest_bytes).hexdigest(), MANIFEST_SHA256)
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        previous_bytes = normalized((ROOT / PREVIOUS_MANIFEST).read_bytes())
        self.assertEqual(sha256(previous_bytes).hexdigest(), PREVIOUS_MANIFEST_SHA256)
        previous = json.loads(previous_bytes.decode("utf-8"))
        self.assertEqual(manifest["contract"], "pqm-google-writer-sync-ui-integrated")
        self.assertEqual(manifest["version"], 31)
        self.assertEqual(manifest["previous_candidate_commit"], PREVIOUS_CANDIDATE)
        self.assertEqual(manifest["previous_manifest"], PREVIOUS_MANIFEST.as_posix())
        self.assertEqual(manifest["previous_manifest_sha256"], PREVIOUS_MANIFEST_SHA256)
        expected_scope = set(previous["scope"]) | {PREVIOUS_MANIFEST.as_posix()} | V31_CHANGES
        self.assertEqual(set(manifest["scope"]), expected_scope)
        self.assertEqual(set(manifest["files"]), expected_scope)
        for relative, expected in previous["files"].items():
            if relative in V31_CHANGES:
                continue
            data = (ROOT / relative).read_bytes()
            data = normalized_test(data) if relative in NORMALIZED_TESTS else normalized(data)
            with self.subTest(unchanged_from_v30=relative):
                self.assertEqual(sha256(data).hexdigest(), expected)
        for relative, expected in manifest["files"].items():
            data = (ROOT / relative).read_bytes()
            data = normalized_test(data) if relative in NORMALIZED_TESTS else normalized(data)
            with self.subTest(candidate_pin=relative):
                self.assertEqual(sha256(data).hexdigest(), expected)

    def test_v30_exact_snapshot_and_current_container_gate_parity(self):
        package = json.loads((ROOT / "validation/release_test_package_integrated_v11.json").read_text(encoding="utf-8"))
        self.assertEqual(package["integrated_history_versions"], list(range(1, 31)))
        self.assertEqual(package["integrity_test_versions"], list(range(1, 32)))
        runner = (ROOT / "validation/run_integrated_writer_ui_v30_history.py").read_text(encoding="utf-8")
        self.assertIn("18547958823754a808f8cd09761904abbd2d9c83", runner)
        self.assertIn("snapshot_archive_for_runner", runner)
        workflow = (ROOT / ".github/workflows/release-checks.yml").read_text(encoding="utf-8")
        predeploy = (ROOT / "validation/docker_release_gate_csv_ui_v3.py").read_text(encoding="utf-8")
        self.assertIn("--entrypoint python pqm-ci:tested", workflow)
        self.assertIn("-B validation/docker_release_gate_csv_ui_v3.py", workflow)
        self.assertIn("def main():", predeploy)
        self.assertIn("node validation/supplier_edr_apply_modal_browser.cjs", workflow)

    def test_apply_keeps_calendar_history_separate_from_priority_instant(self):
        server = (ROOT / "server.py").read_text(encoding="utf-8")
        sync = (ROOT / "edr_sync_v2.py").read_text(encoding="utf-8")
        self.assertIn("_supplier_manager_priority_instant", server)
        self.assertIn("google_verification_contract.google_verification_instant", server)
        self.assertIn("source_timestamp: str | None = None", server)
        self.assertIn("item[\"edr_checked_at\"])", sync)
        self.assertIn("progress_callback=progress", server)


if __name__ == "__main__":
    unittest.main()
