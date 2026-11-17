"""Current integrated Writer/UI contract v7; v1-v6 remain immutable."""
import hashlib
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parent
MANIFEST = Path("validation/local_release_20261116/pqm_sync_ui_integrated_v7.json")
MANIFEST_SHA256 = "a52cd0a107f22d88f58d2f4db91534ae46fb4f58c932bdad7387fbd1c9b7e252"
TEST_FILE = "test_google_writer_integrated_candidate_integrity_v7.py"
PREVIOUS_MANIFEST = Path("validation/local_release_20261116/pqm_sync_ui_integrated_v6.json")
PREVIOUS_TEST = "test_google_writer_integrated_candidate_integrity_v6.py"
PREVIOUS_SNAPSHOT = "8e0dc787d0d1db8211fefcf531f722508d3d2d74"
PREVIOUS_MANIFEST_SHA256 = "db2bcf83ad9b6bc2b7734176807b00a3359776951ac0779264d0eca2955d6aa9"
ALLOWED_V7_CHANGES = {
    ".github/workflows/release-checks.yml",
    "app.js",
    "index.html",
    "queue_statistics_ui.js",
    "styles.css",
    "test_release_gate_infrastructure.py",
    "validation/queue_statistics_ui.test.cjs",
    "validation/run_local_release.py",
}


def canonical(data):
    return data.replace(b"\r\n", b"\n")


def canonical_self(data):
    return re.sub(
        rb"(?m)^MANIFEST_SHA256 = \"(?:<manifest-sha256>|[0-9a-f]{64})\"$",
        b'MANIFEST_SHA256 = "<manifest-sha256>"',
        canonical(data),
    )


def canonical_previous_test(data):
    return re.sub(
        rb"(?m)^MANIFEST_SHA256 = '(?:<manifest-sha256>|[0-9a-f]{64})'$",
        b"MANIFEST_SHA256 = '<manifest-sha256>'",
        canonical(data),
    )


class GoogleWriterIntegratedCandidateIntegrityV7(unittest.TestCase):
    def test_v7_manifest_pins_current_candidate_and_preserves_v1_v6_contracts(self):
        raw = canonical((ROOT / MANIFEST).read_bytes())
        self.assertEqual(hashlib.sha256(raw).hexdigest(), MANIFEST_SHA256)
        manifest = json.loads(raw.decode("utf-8"))
        previous_raw = canonical((ROOT / PREVIOUS_MANIFEST).read_bytes())
        self.assertEqual(hashlib.sha256(previous_raw).hexdigest(), PREVIOUS_MANIFEST_SHA256)
        previous = json.loads(previous_raw.decode("utf-8"))
        self.assertEqual(manifest["contract"], "pqm-google-writer-sync-ui-integrated")
        self.assertEqual(manifest["version"], 7)
        self.assertEqual(manifest["previous_candidate_commit"], PREVIOUS_SNAPSHOT)
        expected_scope = set(previous["scope"]) | {
            PREVIOUS_MANIFEST.as_posix(),
            "validation/fixtures/pqm_sync_ui_integrated_v6_8e0dc78.zip",
            "validation/run_integrated_writer_ui_v6_history.py",
            TEST_FILE,
        }
        self.assertEqual(set(manifest["scope"]), expected_scope)
        self.assertEqual(set(manifest["files"]), expected_scope)
        self.assertEqual(
            hashlib.sha256(canonical_previous_test((ROOT / PREVIOUS_TEST).read_bytes())).hexdigest(),
            previous["files"][PREVIOUS_TEST],
        )
        for relative, expected in previous["files"].items():
            if relative not in ALLOWED_V7_CHANGES and relative != PREVIOUS_TEST:
                with self.subTest(unchanged_from_v6=relative):
                    actual = hashlib.sha256(canonical((ROOT / relative).read_bytes())).hexdigest()
                    self.assertEqual(actual, expected)
        for relative, expected in manifest["files"].items():
            data = (ROOT / relative).read_bytes()
            normalized = canonical_self(data) if relative == TEST_FILE else canonical(data)
            with self.subTest(path=relative):
                self.assertEqual(hashlib.sha256(normalized).hexdigest(), expected)

    def test_ui_regression_test_is_in_the_mandatory_release_workflow(self):
        workflow = (ROOT / ".github/workflows/release-checks.yml").read_text(encoding="utf-8")
        runner = (ROOT / "validation/run_local_release.py").read_text(encoding="utf-8")
        self.assertIn("validation/queue_statistics_ui.test.cjs", workflow)
        self.assertIn("test_google_writer_integrated_candidate_integrity_v7", workflow)
        self.assertIn("test_google_writer_integrated_candidate_integrity_v7", runner)
        self.assertIn("run_integrated_writer_ui_v6_history.py", workflow)
        self.assertIn("run_integrated_writer_ui_v6_history.py", runner)


if __name__ == "__main__":
    unittest.main()
