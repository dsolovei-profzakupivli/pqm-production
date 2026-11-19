"""Portable, fail-closed tests for immutable Git snapshot archive staging."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
import unittest
import zipfile
from io import BytesIO

from validation.integrated_git_snapshot import (
    load_staged_snapshot_archive,
    snapshot_archive_for_runner,
)
from validation.integrated_snapshot_archive import canonical_eol


MANIFEST_PATH = "validation/local_release_20261116/synthetic_snapshot.json"
SOURCE_PATH = "validation/snapshot_payload.txt"


def make_archive(payload: bytes, *, include_source=True, manifest_payload=None) -> tuple[bytes, str]:
    pinned = canonical_eol(manifest_payload if manifest_payload is not None else payload)
    manifest = {
        "contract": "synthetic-integrated-snapshot",
        "scope": [SOURCE_PATH],
        "files": {SOURCE_PATH: hashlib.sha256(pinned).hexdigest()},
    }
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr(MANIFEST_PATH, manifest_bytes)
        if include_source:
            bundle.writestr(SOURCE_PATH, payload)
    return stream.getvalue(), hashlib.sha256(manifest_bytes).hexdigest()


class IntegratedSnapshotStagingTests(unittest.TestCase):
    def write_archive(self, folder: Path, archive: bytes) -> Path:
        path = folder / "snapshot.zip"
        path.write_bytes(archive)
        return path

    def load(self, path: Path, archive: bytes, manifest_sha: str):
        return load_staged_snapshot_archive(
            path,
            expected_archive_sha256=hashlib.sha256(archive).hexdigest(),
            manifest_relative=MANIFEST_PATH,
            expected_manifest_sha256=manifest_sha,
        )

    def test_staged_snapshot_works_without_git_and_checks_file_pins(self):
        archive, manifest_sha = make_archive(b"snapshot payload\n")
        with tempfile.TemporaryDirectory(prefix="pqm-no-git-snapshot-") as temporary:
            root = Path(temporary)
            staged = self.write_archive(root, archive)
            self.assertFalse((root / ".git").exists())
            with patch.dict(os.environ, {
                "PQM_INTEGRATED_V10_SNAPSHOT_ARCHIVE": str(staged),
                "PQM_INTEGRATED_V10_SNAPSHOT_ARCHIVE_SHA256": hashlib.sha256(archive).hexdigest(),
            }), patch("validation.integrated_git_snapshot.subprocess.run",
                      side_effect=AssertionError("staged path must not invoke Git")):
                actual, source = snapshot_archive_for_runner(
                    root,
                    version=10,
                    commit="historical-commit",
                    manifest_relative=MANIFEST_PATH,
                    expected_manifest_sha256=manifest_sha,
                )
            self.assertEqual(actual, archive)
            self.assertEqual(source, "verified staged Git snapshot archive")

    def test_modified_file_is_rejected_even_with_matching_transport_sha(self):
        archive, manifest_sha = make_archive(b"expected\n")
        tampered, _ = make_archive(b"modified\n", manifest_payload=b"expected\n")
        with tempfile.TemporaryDirectory(prefix="pqm-modified-snapshot-") as temporary:
            path = self.write_archive(Path(temporary), tampered)
            with self.assertRaisesRegex(RuntimeError, "file SHA mismatch"):
                self.load(path, tampered, manifest_sha)

    def test_incomplete_archive_is_rejected(self):
        archive, manifest_sha = make_archive(b"expected\n", include_source=False)
        with tempfile.TemporaryDirectory(prefix="pqm-incomplete-snapshot-") as temporary:
            path = self.write_archive(Path(temporary), archive)
            with self.assertRaisesRegex(RuntimeError, "file set mismatch"):
                self.load(path, archive, manifest_sha)

    def test_substituted_archive_is_rejected(self):
        expected_archive, expected_manifest_sha = make_archive(b"expected\n")
        substituted, _ = make_archive(b"substituted\n")
        with tempfile.TemporaryDirectory(prefix="pqm-substituted-snapshot-") as temporary:
            path = self.write_archive(Path(temporary), substituted)
            with self.assertRaisesRegex(RuntimeError, "manifest SHA mismatch"):
                self.load(path, substituted, expected_manifest_sha)
            path.write_bytes(substituted)
            with self.assertRaisesRegex(RuntimeError, "archive SHA-256 mismatch"):
                load_staged_snapshot_archive(
                    path,
                    expected_archive_sha256=hashlib.sha256(expected_archive).hexdigest(),
                    manifest_relative=MANIFEST_PATH,
                    expected_manifest_sha256=expected_manifest_sha,
                )

    def test_lf_and_crlf_payloads_validate_against_same_content_pin(self):
        lf, manifest_sha = make_archive(b"alpha\nbeta\n")
        crlf, crlf_manifest_sha = make_archive(b"alpha\r\nbeta\r\n")
        self.assertEqual(manifest_sha, crlf_manifest_sha)
        with tempfile.TemporaryDirectory(prefix="pqm-eol-snapshot-") as temporary:
            root = Path(temporary)
            lf_path = root / "lf.zip"
            crlf_path = root / "crlf.zip"
            lf_path.write_bytes(lf)
            crlf_path.write_bytes(crlf)
            for path, archive in ((lf_path, lf), (crlf_path, crlf)):
                with self.subTest(archive=path.name):
                    _actual, manifest = load_staged_snapshot_archive(
                        path,
                        expected_archive_sha256=hashlib.sha256(archive).hexdigest(),
                        manifest_relative=MANIFEST_PATH,
                        expected_manifest_sha256=manifest_sha,
                    )
                    self.assertEqual(manifest["scope"], [SOURCE_PATH])


if __name__ == "__main__":
    unittest.main()
