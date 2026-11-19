"""Current integrated Writer/UI integrity contract v11; earlier versions are immutable."""
from hashlib import sha256
import json
from pathlib import Path
import re
import unittest

from validation.integrated_snapshot_archive import canonical_eol


ROOT = Path(__file__).resolve().parent
MANIFEST = Path("validation/local_release_20261116/pqm_sync_ui_integrated_v11.json")
MANIFEST_SHA256 = "e96321367b2e724f7dc452e35b9f418741ced4a2e8525191a505f7db6c190c3b"
PREVIOUS_MANIFEST = Path("validation/local_release_20261116/pqm_sync_ui_integrated_v10.json")
PREVIOUS_MANIFEST_SHA256 = "f06808711ce9e961dce3b0c31c2bca084d170493d1ae83d4c421ce8c312c4727"
PREVIOUS_TEST = "test_google_writer_integrated_candidate_integrity_v10.py"
PREVIOUS_HISTORY_RUNNER = Path("validation/run_integrated_writer_ui_v10_history.py")
PREVIOUS_CANDIDATE = "27f28b501d37ce125e2334af769f2d23f33355b5"
V11_CHANGES = {
    ".github/workflows/release-checks.yml",
    "server.py",
    "test_release_gate_infrastructure.py",
    "validation/queue_statistics_ui.test.cjs",
    "validation/local_release_20260911/test_uo_work_queue_http.py",
    "validation/run_local_release.py",
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


class GoogleWriterIntegratedCandidateIntegrityV11(unittest.TestCase):
    def test_v11_pins_current_candidate_and_preserves_v1_v10_contracts(self):
        manifest_bytes = normalized((ROOT / MANIFEST).read_bytes())
        self.assertEqual(sha256(manifest_bytes).hexdigest(), MANIFEST_SHA256)
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        previous_bytes = normalized((ROOT / PREVIOUS_MANIFEST).read_bytes())
        self.assertEqual(sha256(previous_bytes).hexdigest(), PREVIOUS_MANIFEST_SHA256)
        previous = json.loads(previous_bytes.decode("utf-8"))

        self.assertEqual(manifest["contract"], "pqm-google-writer-sync-ui-integrated")
        self.assertEqual(manifest["version"], 11)
        self.assertEqual(manifest["previous_candidate_commit"], PREVIOUS_CANDIDATE)
        self.assertEqual(manifest["previous_manifest"], PREVIOUS_MANIFEST.as_posix())
        self.assertEqual(manifest["previous_manifest_sha256"], PREVIOUS_MANIFEST_SHA256)
        expected_scope = set(previous["scope"]) | {
            PREVIOUS_MANIFEST.as_posix(),
            PREVIOUS_HISTORY_RUNNER.as_posix(),
            Path(__file__).name,
            "validation/local_release_20260911/test_uo_work_queue_http.py",
        }
        self.assertEqual(set(manifest["scope"]), expected_scope)
        self.assertEqual(set(manifest["files"]), expected_scope)

        for relative, expected in previous["files"].items():
            if relative in V11_CHANGES:
                continue
            data = (ROOT / relative).read_bytes()
            if relative == PREVIOUS_TEST:
                data = normalized_previous_test(data)
            else:
                data = normalized(data)
            with self.subTest(unchanged_from_v10=relative):
                self.assertEqual(sha256(data).hexdigest(), expected)

        for relative, expected in manifest["files"].items():
            data = (ROOT / relative).read_bytes()
            if relative == Path(__file__).name:
                data = normalized_self(data)
            elif relative == PREVIOUS_TEST:
                data = normalized_previous_test(data)
            else:
                data = normalized(data)
            actual = sha256(data).hexdigest()
            with self.subTest(current_pin=relative):
                self.assertEqual(actual, expected)

    def test_previous_overlay_runs_on_its_exact_git_snapshot(self):
        runner = (ROOT / PREVIOUS_HISTORY_RUNNER).read_text(encoding="utf-8")
        workflow = (ROOT / ".github/workflows/release-checks.yml").read_text(encoding="utf-8")
        local_runner = (ROOT / "validation/run_local_release.py").read_text(encoding="utf-8")
        self.assertIn(PREVIOUS_CANDIDATE, runner)
        self.assertIn("run_integrated_writer_ui_v10_history.py", workflow)
        self.assertIn("test_google_writer_integrated_candidate_integrity_v11", workflow)
        self.assertIn("run_integrated_writer_ui_v10_history.py", local_runner)
        self.assertIn("test_google_writer_integrated_candidate_integrity_v11", local_runner)


if __name__ == "__main__":
    unittest.main()
