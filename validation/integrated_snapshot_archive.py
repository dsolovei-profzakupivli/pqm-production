"""Content-addressed validation for cross-platform historical Git ZIP snapshots."""
from __future__ import annotations

import hashlib
import json
import re
import stat
import subprocess
from pathlib import PurePosixPath
from typing import Mapping
import zipfile


class SnapshotArchiveError(RuntimeError):
    """A historical snapshot archive failed a fail-closed integrity check."""


SELF_MANIFEST_RULES = {
    "test_google_writer_integrated_candidate_integrity_v6.py": (
        re.compile(rb"(?m)^MANIFEST_SHA256 = '(?:<manifest-sha256>|[0-9a-f]{64})'$"),
        b"MANIFEST_SHA256 = '<manifest-sha256>'",
    ),
    "test_google_writer_integrated_candidate_integrity_v7.py": (
        re.compile(rb'(?m)^MANIFEST_SHA256 = "(?:<manifest-sha256>|[0-9a-f]{64})"$'),
        b'MANIFEST_SHA256 = "<manifest-sha256>"',
    ),
    "test_google_writer_integrated_candidate_integrity_v8.py": (
        re.compile(rb'(?m)^MANIFEST_SHA256 = "(?:<manifest-sha256>|[0-9a-f]{64})"$'),
        b'MANIFEST_SHA256 = "<manifest-sha256>"',
    ),
    "test_google_writer_integrated_candidate_integrity_v9.py": (
        re.compile(rb'(?m)^MANIFEST_SHA256 = "(?:<manifest-sha256>|[0-9a-f]{64})"$'),
        b'MANIFEST_SHA256 = "<manifest-sha256>"',
    ),
}


def canonical_eol(data: bytes) -> bytes:
    """Normalize CRLF to LF, matching the established integrity contracts."""
    return data.replace(b"\r\n", b"\n")


def canonical_pinned_file(path: str, data: bytes, self_normalize_paths=()) -> bytes:
    normalized = canonical_eol(data)
    rule = SELF_MANIFEST_RULES.get(path.rsplit("/", 1)[-1]) if path in self_normalize_paths else None
    if rule:
        normalized = rule[0].sub(rule[1], normalized)
    return normalized


def archive_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_version(repo) -> str:
    try:
        result = subprocess.run(
            ["git", "--version"], cwd=repo, check=False,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
    except OSError:
        return "unavailable"
    return result.stdout.strip() or "unavailable"


def _safe_relative_path(path: str) -> bool:
    if (not isinstance(path, str) or not path or "\\" in path or "\x00" in path
            or "//" in path):
        return False
    value = path[:-1] if path.endswith("/") else path
    raw_parts = value.split("/")
    if any(part in ("", ".", "..") for part in raw_parts):
        return False
    pure = PurePosixPath(value)
    return (
        not pure.is_absolute()
        and bool(pure.parts)
        and all(part not in ("", ".", "..") for part in pure.parts)
        and not (pure.parts and ":" in pure.parts[0])
    )


def _validated_manifest(manifest_bytes: bytes, manifest_relative: str,
                        expected_manifest_sha256: str) -> dict:
    normalized = canonical_eol(manifest_bytes)
    actual = archive_sha256(normalized)
    if actual != expected_manifest_sha256:
        raise SnapshotArchiveError(
            f"manifest SHA mismatch: expected={expected_manifest_sha256}, actual={actual}"
        )
    try:
        manifest = json.loads(normalized.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SnapshotArchiveError("manifest is not valid UTF-8 JSON") from exc
    if not isinstance(manifest, dict):
        raise SnapshotArchiveError("manifest root must be an object")
    scope = manifest.get("scope")
    files = manifest.get("files")
    if not isinstance(scope, list) or not all(_safe_relative_path(path) for path in scope):
        raise SnapshotArchiveError("manifest scope must contain safe relative file paths")
    if len(scope) != len(set(scope)):
        raise SnapshotArchiveError("manifest scope contains duplicate paths")
    if not isinstance(files, dict) or not all(
        _safe_relative_path(path)
        and isinstance(pin, str)
        and re.fullmatch(r"[0-9a-f]{64}", pin)
        for path, pin in files.items()
    ):
        raise SnapshotArchiveError("manifest files must map safe paths to full lowercase SHA-256 pins")
    if set(scope) != set(files):
        raise SnapshotArchiveError("manifest scope and file pins do not match exactly")
    if manifest_relative in files:
        raise SnapshotArchiveError("manifest must not recursively pin itself")
    if manifest_relative in scope:
        raise SnapshotArchiveError("manifest must not include itself in scope")
    return manifest


def validate_snapshot_archive(archive: bytes, *, manifest_relative: str,
                              expected_manifest_sha256: str,
                              git_version_text: str = "unavailable",
                              self_normalize_paths=()) -> dict:
    """Validate exact file membership and manifest-pinned bytes, independent of ZIP EOL bytes."""
    actual_archive_sha = archive_sha256(archive)
    context = f"archive_sha256={actual_archive_sha}; git={git_version_text}"
    try:
        if not _safe_relative_path(manifest_relative):
            raise SnapshotArchiveError("unsafe manifest path")
        with zipfile.ZipFile(__import__("io").BytesIO(archive)) as bundle:
            infos = bundle.infolist()
            raw_names = [info.filename for info in infos]
            if len(raw_names) != len(set(raw_names)):
                raise SnapshotArchiveError("archive contains duplicate member names")

            normalized_names = []
            for info in infos:
                name = info.filename
                if not _safe_relative_path(name):
                    raise SnapshotArchiveError(f"archive contains unsafe path: {name!r}")
                is_dir = info.is_dir()
                normalized = name[:-1] if is_dir and name.endswith("/") else name
                if normalized in normalized_names:
                    raise SnapshotArchiveError(f"archive contains duplicate normalized path: {normalized!r}")
                normalized_names.append(normalized)
                mode = (info.external_attr >> 16) & 0xFFFF
                kind = stat.S_IFMT(mode)
                allowed_kinds = (0, stat.S_IFDIR) if is_dir else (0, stat.S_IFREG)
                if kind not in allowed_kinds:
                    raise SnapshotArchiveError(f"archive contains non-regular member: {name!r}")
                if info.flag_bits & 0x1:
                    raise SnapshotArchiveError("encrypted archive members are not allowed")

            if len(normalized_names) != len(set(normalized_names)):
                raise SnapshotArchiveError("archive contains duplicate normalized paths")

            manifest_data = bundle.read(manifest_relative)
            manifest = _validated_manifest(
                manifest_data, manifest_relative, expected_manifest_sha256
            )
            expected_files = set(manifest["scope"]) | set(manifest["files"]) | {manifest_relative}
            actual_files = {info.filename for info in infos if not info.is_dir()}
            if actual_files != expected_files:
                missing = sorted(expected_files - actual_files)
                extra = sorted(actual_files - expected_files)
                raise SnapshotArchiveError(
                    f"archive file set mismatch: missing={missing}, extra={extra}"
                )

            expected_directories = set()
            for name in expected_files:
                parent = PurePosixPath(name).parent
                while str(parent) not in ("", "."):
                    expected_directories.add(str(parent) + "/")
                    parent = parent.parent
            actual_directories = {info.filename for info in infos if info.is_dir()}
            extra_directories = actual_directories - expected_directories
            if extra_directories:
                raise SnapshotArchiveError(
                    f"archive contains unexpected directories: {sorted(extra_directories)}"
                )

            info_by_name = {info.filename: info for info in infos if not info.is_dir()}
            pins: Mapping[str, str] = manifest["files"]
            for path, expected in pins.items():
                data = canonical_pinned_file(
                    path, bundle.read(info_by_name[path]), self_normalize_paths
                )
                actual = archive_sha256(data)
                if actual != expected:
                    raise SnapshotArchiveError(
                        f"file SHA mismatch for {path}: expected={expected}, actual={actual}"
                    )
            return manifest
    except SnapshotArchiveError as exc:
        raise SnapshotArchiveError(f"{exc}; {context}") from exc
    except (KeyError, OSError, TypeError, ValueError, zipfile.BadZipFile) as exc:
        raise SnapshotArchiveError(f"invalid snapshot ZIP: {exc}; {context}") from exc


def verify_fixture_sha256(archive: bytes, expected_sha256: str,
                          git_version_text: str = "unavailable") -> None:
    actual = archive_sha256(archive)
    if actual != expected_sha256:
        raise SnapshotArchiveError(
            f"fixture ZIP SHA mismatch: expected={expected_sha256}, actual={actual}; "
            f"git={git_version_text}"
        )
