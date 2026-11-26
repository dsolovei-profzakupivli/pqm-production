"""Immutable V2 contract pins and V1 snapshot/migration preservation checks."""
import hashlib
import json
import os
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import server


MANIFEST = Path("validation/production_edr_integration_v2.json")
MANIFEST_SHA256 = "b45850370f4d51dfe2a6c20a3bc303b349b73e8eba080fcda308513ea23371ea"
V1_MANIFEST_SHA256 = "0a8711b9ad178be88195865b225d2c86c07772e7c90702f84c8e25d4c51c49a2"
V1_ARCHIVE = Path("validation/fixtures/production_edr_candidate_v1.zip")
V1_UNCHANGED_TESTS_ARCHIVE = Path("validation/fixtures/production_edr_v1_unmodified_tests.zip")


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def normalized_sha(path, raw=None):
    raw = path.read_bytes() if raw is None else raw
    if path.suffix.lower() in {".py", ".js", ".cjs", ".css", ".html", ".json", ".md", ".txt", ".yaml", ".yml"}:
        raw = raw.replace(b"\r\n", b"\n")
    return sha256(raw)


class ProductionEdrIntegrationIntegrityV2(unittest.TestCase):
    def test_candidate_and_immutable_history_pins(self):
        raw = MANIFEST.read_bytes()
        self.assertEqual(sha256(raw), MANIFEST_SHA256)
        manifest = json.loads(raw)
        self.assertEqual(manifest["contract_id"], "pqm_production_edr_integration_v2")
        self.assertEqual(manifest["v1_manifest_sha256"], V1_MANIFEST_SHA256)
        self.assertEqual(manifest["v1_candidate_only_modules"], [
            "test_production_documents_integrity.py",
            "test_production_edr_display_toasts_integrity.py",
            "test_production_edr_google_nazk_daily_sync_integrity_v2.py",
            "test_production_edr_google_nazk_integrity.py",
        ])
        for section in ("candidate_paths", "protected_paths"):
            source_root = Path(os.environ.get("PQM_PRODUCTION_EDR_SOURCE_ROOT") or Path.cwd())
            for relative, expected in manifest[section].items():
                with self.subTest(section=section, path=relative):
                    candidate = source_root / relative
                    if not candidate.is_file() and section == "protected_paths":
                        name = candidate.name
                        renamed = {*manifest["v1_candidate_only_modules"],
                                   "test_production_edr_integration_integrity_v1.py"}
                        if name in renamed:
                            candidate = candidate.with_name("v1_baseline_" + name)
                    self.assertEqual(normalized_sha(candidate), expected)

    def test_v1_candidate_snapshot_is_complete_and_preserves_migration_sources(self):
        self.assertEqual(sha256(V1_ARCHIVE.read_bytes()),
                         json.loads(MANIFEST.read_bytes())["v1_candidate_archive_sha256"])
        manifest = json.loads(MANIFEST.read_bytes())
        self.assertEqual(sha256(V1_UNCHANGED_TESTS_ARCHIVE.read_bytes()),
                         manifest["v1_unchanged_tests_archive_sha256"])
        with zipfile.ZipFile(V1_UNCHANGED_TESTS_ARCHIVE) as archive:
            self.assertEqual(set(archive.namelist()), set(manifest["v1_unchanged_test_paths"]))
            for relative in manifest["v1_unchanged_test_paths"]:
                self.assertEqual(normalized_sha(Path(relative), archive.read(relative)),
                                 manifest["v1_unchanged_test_sha256"][relative])
        v1_manifest_raw = Path("validation/production_edr_integration_v1.json").read_bytes()
        self.assertEqual(sha256(v1_manifest_raw), V1_MANIFEST_SHA256)
        v1_manifest = json.loads(v1_manifest_raw)
        with zipfile.ZipFile(V1_ARCHIVE) as archive:
            self.assertEqual({name for name in archive.namelist() if not name.endswith("/")},
                             set(v1_manifest["candidate_paths"]))
            for relative in ("edr_sync_v2.py", "edr_sync_review.py", "google_verification_contract.py"):
                old = archive.read(relative)
                self.assertEqual(normalized_sha(Path(relative), old),
                                 normalized_sha(Path(relative)))

    def test_apply_grant_is_default_off_in_production_web_mode(self):
        with patch.dict(server.os.environ, {"PQM_ENV": "web", "PQM_SANDBOX": "0"}, clear=True), \
             patch.object(server, "SANDBOX_MODE", False):
            self.assertFalse(server.production_edr_apply_enabled())


if __name__ == "__main__":
    unittest.main()
