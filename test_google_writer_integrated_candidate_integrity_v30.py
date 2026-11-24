"""V30 pins the integrated Sandbox tree and preserves both historical lineages."""
from hashlib import sha256
import json
from pathlib import Path
import re
import unittest

from validation.integrated_snapshot_archive import canonical_eol

ROOT = Path(__file__).resolve().parent
MANIFEST = Path("validation/local_release_20261116/pqm_sync_ui_integrated_v30.json")
MANIFEST_SHA256 = "2ae6efcec557efdbe99dce5411824aa01b9391087ea2b1d0f32453a832921bce"
PREVIOUS_MANIFEST = Path("validation/local_release_20261116/pqm_sync_ui_integrated_v28.json")
PREVIOUS_MANIFEST_SHA256 = "da17790c32b9a4dccd6c9a06324d6ab0fdc3d1c84123c7fe7737ac8cd4c45728"
PREVIOUS_CANDIDATE = "229f86e19cfc9e38fadf00714d16fc4b3ae3b602"
V30_CHANGES = {
    '.github/workflows/release-checks.yml',
    'app.js',
    'edr_sync_v2.py',
    'index.html',
    'queue_statistics_ui.js',
    'server.py',
    'sandbox_runtime.py',
    'test_background_jobs_kill_switch.py',
    'test_google_writer_integrated_candidate_integrity_v29.py',
    'test_google_writer_integrated_candidate_integrity_v30.py',
    'test_release_gate_infrastructure.py',
    'test_google_writer_integrated_candidate_integrity_v28.py',
    'test_google_writer_integrated_candidate_integrity_v7.py',
    'test_google_writer_integrated_candidate_integrity_v8.py',
    'test_google_writer_integrated_candidate_integrity_v9.py',
    'validation/document_release_history_v2.py',
    'validation/docker_release_gate_csv_ui_v3.py',
    'validation/docker_release_gate.py',
    'validation/local_release_20260911/test_document_release_integrity_v1.py',
    'validation/fixtures/document_release_parent_0678d46_addendum_v1.zip',
    'validation/fixtures/document_release_v1_source_6e0a9ef.zip',
    'validation/local_release_20260911/test_google_runtime.py',
    'validation/local_release_20260911/test_permanent_edr_sync_safety.py',
    'validation/local_release_20261116/pqm_sync_ui_integrated_v29.json',
    'validation/release_test_package.py',
    'validation/release_test_package_integrated_v11.json',
    'validation/run_google_writer_update_append_v2_v26_history.py',
    'validation/run_integrated_writer_ui_v27_candidate_history.py',
    'validation/run_integrated_writer_ui_v28_candidate_history.py',
    'validation/run_integrated_writer_ui_v28_history.py',
    'validation/run_integrated_writer_ui_v29_history.py',
    'validation/run_local_release.py',
}
NORMALIZED_TESTS = {
    f"test_google_writer_integrated_candidate_integrity_v{version}.py"
    for version in range(10, 31)
}


def normalized(data: bytes) -> bytes:
    return canonical_eol(data)


def normalized_test(data: bytes) -> bytes:
    return re.sub(
        rb'(?m)^MANIFEST_SHA256 = "(?:<manifest-sha256>|[0-9a-f]{64})"$',
        b'MANIFEST_SHA256 = "<manifest-sha256>"', normalized(data),
    )


class GoogleWriterIntegratedCandidateIntegrityV30(unittest.TestCase):
    def test_v30_pins_integrated_tree_and_preserves_sandbox_v28(self):
        manifest_bytes = normalized((ROOT / MANIFEST).read_bytes())
        self.assertEqual(sha256(manifest_bytes).hexdigest(), MANIFEST_SHA256)
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        previous_bytes = normalized((ROOT / PREVIOUS_MANIFEST).read_bytes())
        self.assertEqual(sha256(previous_bytes).hexdigest(), PREVIOUS_MANIFEST_SHA256)
        previous = json.loads(previous_bytes.decode("utf-8"))
        self.assertEqual(manifest["contract"], "pqm-google-writer-sync-ui-integrated")
        self.assertEqual(manifest["version"], 30)
        self.assertEqual(manifest["previous_candidate_commit"], PREVIOUS_CANDIDATE)
        self.assertEqual(manifest["previous_manifest"], PREVIOUS_MANIFEST.as_posix())
        self.assertEqual(manifest["previous_manifest_sha256"], PREVIOUS_MANIFEST_SHA256)
        expected_scope = set(previous["scope"]) | {PREVIOUS_MANIFEST.as_posix(), Path(__file__).name} | V30_CHANGES
        self.assertEqual(set(manifest["scope"]), expected_scope)
        self.assertEqual(set(manifest["files"]), expected_scope)
        for relative, expected in previous["files"].items():
            if relative in V30_CHANGES:
                continue
            data = (ROOT / relative).read_bytes()
            data = normalized_test(data) if relative in NORMALIZED_TESTS else normalized(data)
            with self.subTest(unchanged_from_sandbox_v28=relative):
                self.assertEqual(sha256(data).hexdigest(), expected)
        for relative, expected in manifest["files"].items():
            data = (ROOT / relative).read_bytes()
            data = normalized_test(data) if relative in NORMALIZED_TESTS else normalized(data)
            with self.subTest(integrated_pin=relative):
                self.assertEqual(sha256(data).hexdigest(), expected)

    def test_two_v27_v28_lineages_and_v29_are_routed_to_exact_snapshots(self):
        package_path = ROOT / "validation/release_test_package_integrated_v11.json"
        package = json.loads(package_path.read_text(encoding="utf-8"))
        self.assertEqual(package["integrated_history_versions"], list(range(1, 30)))
        self.assertEqual(package["integrity_test_versions"], list(range(1, 31)))
        runners = {
            "validation/run_integrated_writer_ui_v27_history.py": "644dbe87809637215cf05c72cead99183033877d",
            "validation/run_integrated_writer_ui_v28_history.py": "175d474a75cd236e6fbe3b5042c79c318460e118",
            "validation/run_integrated_writer_ui_v27_candidate_history.py": "caab241482d7ad96c0088d6878efaad7b0f9ad0a",
            "validation/run_integrated_writer_ui_v28_candidate_history.py": "1e75aa05c1b2c2018a28b13d158283414843473d",
            "validation/run_integrated_writer_ui_v29_history.py": "50b41ea963186e0c77867e18432497a2defb02b6",
        }
        for relative, commit in runners.items():
            content = (ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(runner=relative):
                self.assertIn(commit, content)
                self.assertIn("snapshot_archive_for_runner", content)
        self.assertEqual(
            sha256(normalized((ROOT / "validation/local_release_20261116/pqm_sync_ui_integrated_v29.json").read_bytes())).hexdigest(),
            "90db005f3aca6fae6f622885627b948f859cbb84d7fdca7e1ef9934a7c6212c7",
        )

    def test_sandbox_sync_guards_and_v29_sync_contracts_are_present(self):
        server = (ROOT / "server.py").read_text(encoding="utf-8")
        sync = (ROOT / "edr_sync_v2.py").read_text(encoding="utf-8")
        workflow = (ROOT / ".github/workflows/release-checks.yml").read_text(encoding="utf-8")
        runner = (ROOT / "validation/run_local_release.py").read_text(encoding="utf-8")
        for token in (
            'if current_plan["conflicts"] and not SANDBOX_MODE',
            "summary", "eligible",
            "/api/supplier-edr-sync/conflicts.xlsx",
            "last_result_summary",
        ):
            self.assertIn(token, server)
        for token in (
            "fop_name_enrichment_fields",
            "CONFLICT_REASON_DETAILS",
            "malformed_current_verification_datetime",
            "current_verification_date_missing",
        ):
            self.assertIn(token, sync)
        self.assertIn("dd.mm.yyyy hh:mm:ss", server)
        self.assertIn("PQM_INTEGRATED_V127_SNAPSHOT_ARCHIVE", workflow)
        self.assertIn("PQM_INTEGRATED_V128_SNAPSHOT_ARCHIVE", workflow)
        self.assertIn("PQM_INTEGRATED_V29_SNAPSHOT_ARCHIVE", workflow)
        self.assertIn("PQM_UPDATE_APPEND_V2_V26_FULL_ARCHIVE", workflow)
        self.assertIn("UnhandledThreadExceptionMonitor", runner)
        self.assertIn("GIT_CONFIG_VALUE_", runner)


if __name__ == "__main__":
    unittest.main()
