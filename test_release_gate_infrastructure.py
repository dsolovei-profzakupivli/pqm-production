"""Regression tests for local Release Gate staging and isolation adapters."""
import hashlib
import json
from pathlib import Path
import unittest
import zipfile

import validation.run_local_release as release


ROOT = Path(__file__).resolve().parent


class ReleaseGateInfrastructureTests(unittest.TestCase):
    def test_windows_sqlite_uri_is_normalized_without_changing_mode_or_other_uris(self):
        normalized = release.normalize_windows_sqlite_uri(r"file:C:\pqm-test\db.sqlite3?mode=ro")
        self.assertTrue(normalized.startswith("file:///"))
        self.assertTrue(normalized.endswith("?mode=ro"))
        self.assertEqual(release.normalize_windows_sqlite_uri("file:relative.sqlite3?mode=ro"),
                         "file:relative.sqlite3?mode=ro")
        self.assertEqual(release.normalize_windows_sqlite_uri("file:///tmp/pqm-test.sqlite3?mode=ro"),
                         "file:///tmp/pqm-test.sqlite3?mode=ro")
        self.assertEqual(release.normalize_windows_sqlite_uri(":memory:"), ":memory:")

    def test_historical_snapshot_ledger_is_complete_and_archive_hashes_match(self):
        ledger_path = ROOT / "validation/google_writer_historical_integrity_snapshots_v1.json"
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        archive_path = ROOT / ledger["archive"]
        self.assertEqual(hashlib.sha256(archive_path.read_bytes()).hexdigest(), ledger["archive_sha256"])
        self.assertGreaterEqual(len(ledger["snapshots"]), 11)
        with zipfile.ZipFile(archive_path) as archive:
            self.assertIsNone(archive.testzip())
            names = set(archive.namelist())
            for snapshot_id, snapshot in ledger["snapshots"].items():
                prefix = f"snapshots/{snapshot_id}/"
                self.assertIn(prefix + snapshot["test"], names)
                self.assertTrue(snapshot["commit"].startswith(tuple("0123456789abcdef")))
                self.assertEqual({name[len(prefix):] for name in names if name.startswith(prefix)},
                                 set(snapshot["files"]))
                for relative, expected in snapshot["files"].items():
                    with self.subTest(snapshot=snapshot_id, path=relative):
                        self.assertEqual(hashlib.sha256(archive.read(prefix + relative)).hexdigest(), expected)

    def test_historical_runner_fails_closed_instead_of_falling_back_to_current_files(self):
        runner = (ROOT / "validation/run_google_writer_historical_integrity_snapshots_v1.py").read_text(encoding="utf-8")
        self.assertIn("snapshot ledger missing; refusing candidate-source fallback", runner)
        self.assertIn("snapshot archive missing; refusing candidate-source fallback", runner)
        harness = (ROOT / "validation/run_local_release.py").read_text(encoding="utf-8")
        self.assertIn("run_google_writer_historical_integrity_snapshots_v1.py", harness)
        self.assertIn("google_writer_historical_integrity_snapshots_v1_compact.zip", harness)
        self.assertIn("google_writer_historical_integrity_snapshots_v1.json", harness)
        self.assertIn("PQM_RELEASE_INFRA_ROOT", harness)
        self.assertIn("Path(__file__).resolve().parents[1]).resolve()", harness)
        self.assertIn("sandbox_runtime_messages_integrated_v1_86ea864.py", harness)


if __name__ == "__main__":
    unittest.main()
