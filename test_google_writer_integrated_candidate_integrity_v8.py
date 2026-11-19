"""Cross-platform byte-safe checks for integrated historical Git ZIP snapshots."""
import hashlib
import io
import json
from pathlib import Path
import re
import unittest
import warnings
import zipfile

from validation.integrated_snapshot_archive import (
    SnapshotArchiveError,
    validate_snapshot_archive,
    verify_fixture_sha256,
)


ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = Path("validation/local_release_20261116/pqm_sync_ui_integrated_v8.json")
MANIFEST_SHA256 = "027783c537408f24656f7498d6d6bb6422a7db6b49e441e0d56fb2369e5b29d2"
PREVIOUS_MANIFEST = Path("validation/local_release_20261116/pqm_sync_ui_integrated_v7.json")
PREVIOUS_MANIFEST_SHA256 = "a52cd0a107f22d88f58d2f4db91534ae46fb4f58c932bdad7387fbd1c9b7e252"
ALLOWED_V8_CHANGES = {
    ".github/workflows/release-checks.yml",
    "test_release_gate_infrastructure.py",
    "validation/run_local_release.py",
    "validation/run_integrated_writer_ui_v6_history.py",
}


def _snapshot(file_bytes: bytes, *, line_ending: bytes = b"\n", extra=(), omit=(),
              duplicate=False, traversal=(), malformed_manifest=False,
              invalid_manifest=False):
    expected = hashlib.sha256(file_bytes.replace(b"\r\n", b"\n")).hexdigest()
    manifest = {
        "contract": "archive-test",
        "scope": ["payload.txt"],
        "files": {"payload.txt": expected},
    }
    if invalid_manifest:
        manifest["scope"] = ["payload.txt", "payload.txt"]
    manifest_bytes = (b"{ definitely not json }" if malformed_manifest else
                      json.dumps(manifest, sort_keys=True).encode("utf-8").replace(b"\n", line_ending))
    expected_manifest = hashlib.sha256(manifest_bytes.replace(b"\r\n", b"\n")).hexdigest()
    output = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("validation/manifest.json", manifest_bytes)
            if "payload.txt" not in omit:
                bundle.writestr("payload.txt", file_bytes)
                if duplicate:
                    bundle.writestr("payload.txt", file_bytes)
            for name, data in extra:
                bundle.writestr(name, data)
            for name, data in traversal:
                bundle.writestr(name, data)
    return output.getvalue(), expected_manifest


class IntegratedSnapshotArchiveV8Tests(unittest.TestCase):
    def _validate(self, archive, manifest_sha):
        return validate_snapshot_archive(
            archive,
            manifest_relative="validation/manifest.json",
            expected_manifest_sha256=manifest_sha,
            git_version_text="git version test-fixture",
        )

    def test_lf_and_crlf_archives_validate_to_the_same_pinned_content(self):
        lf, lf_manifest = _snapshot(b"alpha\nbeta\n", line_ending=b"\n")
        crlf, crlf_manifest = _snapshot(b"alpha\r\nbeta\r\n", line_ending=b"\r\n")
        self._validate(lf, lf_manifest)
        self._validate(crlf, crlf_manifest)

    def test_modified_file_content_is_rejected_with_archive_and_git_diagnostics(self):
        archive, manifest_sha = _snapshot(b"expected\n")
        # Preserve the pinned manifest while changing only the archived payload.
        with zipfile.ZipFile(io.BytesIO(archive)) as source:
            manifest = source.read("validation/manifest.json")
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as bundle:
            bundle.writestr("validation/manifest.json", manifest)
            bundle.writestr("payload.txt", b"changed\n")
        changed = output.getvalue()
        with self.assertRaisesRegex(SnapshotArchiveError, "file SHA mismatch") as raised:
            self._validate(changed, manifest_sha)
        self.assertIn(hashlib.sha256(changed).hexdigest(), str(raised.exception))
        self.assertIn("git version test-fixture", str(raised.exception))

    def test_extra_file_is_rejected(self):
        archive, manifest_sha = _snapshot(b"ok\n", extra=(("surprise.txt", b"x"),))
        with self.assertRaisesRegex(SnapshotArchiveError, "file set mismatch"):
            self._validate(archive, manifest_sha)

    def test_missing_file_is_rejected(self):
        archive, manifest_sha = _snapshot(b"ok\n", omit=("payload.txt",))
        with self.assertRaisesRegex(SnapshotArchiveError, "file set mismatch"):
            self._validate(archive, manifest_sha)

    def test_duplicate_member_is_rejected(self):
        archive, manifest_sha = _snapshot(b"ok\n", duplicate=True)
        with self.assertRaisesRegex(SnapshotArchiveError, "duplicate member"):
            self._validate(archive, manifest_sha)

    def test_traversal_path_is_rejected(self):
        for unsafe in ("../escape.txt", "./dot-segment.txt"):
            with self.subTest(path=unsafe):
                archive, manifest_sha = _snapshot(b"ok\n", traversal=((unsafe, b"x"),))
                with self.assertRaisesRegex(SnapshotArchiveError, "unsafe path"):
                    self._validate(archive, manifest_sha)

    def test_invalid_manifest_json_is_rejected(self):
        archive, manifest_sha = _snapshot(b"ok\n", malformed_manifest=True)
        with self.assertRaisesRegex(SnapshotArchiveError, "not valid UTF-8 JSON"):
            self._validate(archive, manifest_sha)

    def test_manifest_with_duplicate_scope_entry_is_rejected(self):
        archive, manifest_sha = _snapshot(b"ok\n", invalid_manifest=True)
        with self.assertRaisesRegex(SnapshotArchiveError, "duplicate paths"):
            self._validate(archive, manifest_sha)

    def test_fixture_archive_requires_exact_sha256(self):
        archive, _ = _snapshot(b"fixture\n")
        digest = hashlib.sha256(archive).hexdigest()
        verify_fixture_sha256(archive, digest, "git version fixture")
        with self.assertRaisesRegex(SnapshotArchiveError, "fixture ZIP SHA mismatch"):
            verify_fixture_sha256(archive, "0" * 64, "git version fixture")

    def test_current_v8_manifest_pins_all_files(self):
        raw = (ROOT / MANIFEST_PATH).read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(hashlib.sha256(raw).hexdigest(), MANIFEST_SHA256)
        manifest = json.loads(raw.decode("utf-8"))
        self.assertEqual(set(manifest["scope"]), set(manifest["files"]))
        for relative, expected in manifest["files"].items():
            data = (ROOT / relative).read_bytes().replace(b"\r\n", b"\n")
            if relative == Path(__file__).name:
                data = re.sub(
                    rb'(?m)^MANIFEST_SHA256 = "(?:<manifest-sha256>|[0-9a-f]{64})"$',
                    b'MANIFEST_SHA256 = "<manifest-sha256>"', data,
                )
            with self.subTest(path=relative):
                self.assertEqual(hashlib.sha256(data).hexdigest(), expected)

    def test_v7_remains_pinned_and_runs_from_immutable_snapshot(self):
        previous_raw = (ROOT / PREVIOUS_MANIFEST).read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(hashlib.sha256(previous_raw).hexdigest(), PREVIOUS_MANIFEST_SHA256)
        previous = json.loads(previous_raw.decode("utf-8"))
        current = json.loads((ROOT / MANIFEST_PATH).read_text(encoding="utf-8"))
        expected_scope = set(previous["scope"]) | {
            PREVIOUS_MANIFEST.as_posix(),
            "validation/fixtures/pqm_sync_ui_integrated_v7_9b3dd33.zip",
            "validation/run_integrated_writer_ui_v7_history.py",
            "validation/integrated_snapshot_archive.py",
            Path(__file__).name,
        }
        self.assertEqual(set(current["scope"]), expected_scope)
        self.assertEqual(set(current["files"]), expected_scope)
        for relative, expected in previous["files"].items():
            if relative in ALLOWED_V8_CHANGES:
                continue
            data = (ROOT / relative).read_bytes().replace(b"\r\n", b"\n")
            if relative == "test_google_writer_integrated_candidate_integrity_v7.py":
                data = re.sub(
                    rb'(?m)^MANIFEST_SHA256 = "(?:<manifest-sha256>|[0-9a-f]{64})"$',
                    b'MANIFEST_SHA256 = "<manifest-sha256>"', data,
                )
            self.assertEqual(hashlib.sha256(data).hexdigest(), expected, relative)
        workflow = (ROOT / ".github/workflows/release-checks.yml").read_text(encoding="utf-8")
        self.assertIn("validation/run_integrated_writer_ui_v7_history.py", workflow)
        self.assertIn("test_google_writer_integrated_candidate_integrity_v8", workflow)
        self.assertNotIn("test_google_writer_integrated_candidate_integrity_v7 \\", workflow)


if __name__ == "__main__":
    unittest.main()
