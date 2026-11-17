"""Create or consume verified Git snapshot archives for immutable history tests.

The archive is a transport format only. Its manifest and every scoped file are
validated independently, so callers never rely on an archive digest alone.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from io import BytesIO
import zipfile

try:  # Import both as a validation script and as the validation package.
    from .integrated_snapshot_archive import SnapshotArchiveError, validate_snapshot_archive
except ImportError:
    from integrated_snapshot_archive import SnapshotArchiveError, validate_snapshot_archive


def _git_blob(repository: Path, commit: str, path: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{commit}:{path}"], cwd=repository,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if result.returncode:
        raise RuntimeError(
            f"Could not read immutable snapshot file {path}: "
            f"{result.stderr.decode(errors='replace')}"
        )
    return result.stdout


def build_git_snapshot_archive(repository: Path, *, commit: str,
                               manifest_relative: str,
                               expected_manifest_sha256: str,
                               self_normalize_paths=()) -> tuple[bytes, str]:
    """Build a content-validated archive from exact Git blobs on a host checkout."""
    repository = Path(repository).resolve()
    try:
        manifest_bytes = _git_blob(repository, commit, manifest_relative)
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        scope = manifest["scope"]
        if not isinstance(scope, list) or any(not isinstance(item, str) for item in scope):
            raise ValueError("manifest scope is not a list of paths")
        paths = sorted(set(scope) | {manifest_relative})
        archive_buffer = BytesIO()
        with zipfile.ZipFile(archive_buffer, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6) as bundle:
            for path in paths:
                bundle.writestr(path, _git_blob(repository, commit, path))
        archive = archive_buffer.getvalue()
        version = subprocess.run(
            ["git", "--version"], cwd=repository, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        ).stdout.strip()
        validate_snapshot_archive(
            archive,
            manifest_relative=manifest_relative,
            expected_manifest_sha256=expected_manifest_sha256,
            git_version_text=version,
            self_normalize_paths=self_normalize_paths,
        )
        return archive, version
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError,
            SnapshotArchiveError, ValueError) as exc:
        raise RuntimeError(f"Immutable Git snapshot validation failed: {exc}") from exc


def load_staged_snapshot_archive(archive_path: Path, *, expected_archive_sha256: str,
                                 manifest_relative: str,
                                 expected_manifest_sha256: str,
                                 self_normalize_paths=()) -> tuple[bytes, dict]:
    """Read a staged archive and verify transport SHA plus all manifest pins."""
    archive_path = Path(archive_path)
    if not archive_path.is_file():
        raise RuntimeError(f"Verified immutable snapshot archive is unavailable: {archive_path}")
    if not re.fullmatch(r"[0-9a-f]{64}", str(expected_archive_sha256 or "")):
        raise RuntimeError("Expected immutable snapshot archive SHA-256 is missing or malformed")
    archive = archive_path.read_bytes()
    actual_archive_sha256 = hashlib.sha256(archive).hexdigest()
    if actual_archive_sha256 != expected_archive_sha256:
        raise RuntimeError(
            "Immutable snapshot archive SHA-256 mismatch: "
            f"expected={expected_archive_sha256}, actual={actual_archive_sha256}"
        )
    try:
        manifest = validate_snapshot_archive(
            archive,
            manifest_relative=manifest_relative,
            expected_manifest_sha256=expected_manifest_sha256,
            git_version_text="verified staged Git snapshot archive",
            self_normalize_paths=self_normalize_paths,
        )
    except SnapshotArchiveError as exc:
        raise RuntimeError(f"Staged immutable snapshot content validation failed: {exc}") from exc
    return archive, manifest


def snapshot_archive_for_runner(repository: Path, *, version: int, commit: str,
                                manifest_relative: str,
                                expected_manifest_sha256: str,
                                self_normalize_paths=()) -> tuple[bytes, str]:
    """Load the staged archive in containers, or build it from Git on the host.

    Version-specific environment names allow multiple history snapshots to be
    mounted into the same regression container without adding them to its image.
    """
    prefix = f"PQM_INTEGRATED_V{version}_SNAPSHOT_ARCHIVE"
    staged_path = os.environ.get(prefix, "").strip()
    if staged_path:
        expected_archive_sha = os.environ.get(prefix + "_SHA256", "").strip()
        archive, _manifest = load_staged_snapshot_archive(
            Path(staged_path),
            expected_archive_sha256=expected_archive_sha,
            manifest_relative=manifest_relative,
            expected_manifest_sha256=expected_manifest_sha256,
            self_normalize_paths=self_normalize_paths,
        )
        version_text = "verified staged Git snapshot archive"
    else:
        archive, version_text = build_git_snapshot_archive(
            repository,
            commit=commit,
            manifest_relative=manifest_relative,
            expected_manifest_sha256=expected_manifest_sha256,
            self_normalize_paths=self_normalize_paths,
        )

    output_path = os.environ.get(prefix + "_OUT", "").strip()
    if output_path:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(archive)
        output_sha = hashlib.sha256(archive).hexdigest()
        print(f"Integrated v{version} snapshot archive SHA-256: {output_sha}", flush=True)
    return archive, version_text
