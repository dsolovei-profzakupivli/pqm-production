"""Provide immutable historical Production trees to exact-tree integrity tests."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import zipfile


OVERLAY_SHA256 = "09d1f1cec428bd2bcfdbc236158a5f0466ab09038b3d8d0584f51b964dda8f7f"
OVERLAY_RELATIVE = Path("validation/fixtures/production_nazk_recovery_overlay_cbe1ec4.zip")
MANIFEST_RELATIVE = Path("validation/production_nazk_recovery_autoclose_v1.json")
MANIFEST_SHA256 = "bc01a5a66d7384ffddefb7347f2c4a6eb4e802a3b75aff707a920cca1536bf4d"
NAZK_TEST_ARCHIVE = Path("validation/fixtures/production_memory_nazk_test_parent_a53234f.zip")
NAZK_TEST_ARCHIVE_SHA256 = "21619cb4e55592f508035f88a466c53e5f9afe024e29ae100bf85203acee54c6"
NAZK_TEST_MEMBER = "validation/local_release_20260911/test_nazk_full_contract.py"
NAZK_TEST_SHA256 = "829db6538fa96ac4cd4a3fc67c61c12d484d259a739e6b820ccf8760885c01fe"
_CACHE: dict[Path, Path] = {}
_TEMP_DIRS: list[tempfile.TemporaryDirectory[str]] = []


def _sha(data: bytes) -> str:
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def _safe_member(root: Path, name: str) -> Path:
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts:
        raise AssertionError(f"Unsafe historical overlay member: {name}")
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()):
        raise AssertionError(f"Historical overlay path escaped root: {name}")
    return target


def _historical_nazk_test(source_root: Path) -> bytes:
    """Read the original test only from its existing immutable Stage 1 archive."""
    archive_path = source_root / NAZK_TEST_ARCHIVE
    if hashlib.sha256(archive_path.read_bytes()).hexdigest() != NAZK_TEST_ARCHIVE_SHA256:
        raise AssertionError("Historical connection fixture archive changed")
    with zipfile.ZipFile(archive_path) as archive:
        if archive.namelist() != [NAZK_TEST_MEMBER]:
            raise AssertionError("Unexpected historical connection fixture members")
        content = archive.read(NAZK_TEST_MEMBER)
    if _sha(content) != NAZK_TEST_SHA256:
        raise AssertionError("Historical NAZK test content changed")
    return content


def _verify_historical_nazk_test(root: Path) -> None:
    if _sha((root / NAZK_TEST_MEMBER).read_bytes()) != NAZK_TEST_SHA256:
        raise AssertionError("Historical NAZK test no longer matches its contract")


def historical_integrity_root(source_root: Path) -> Path:
    """Overlay cbe1ec4's pinned integrity inputs onto an isolated tree copy.

    The caller's live source tree is never modified. All old exact-tree
    assertions and their byte-mutation checks run against the historical
    candidate; the separate additive contract checks the current integration.
    """
    source_root = Path(source_root).resolve()
    if not (source_root / "validation/fixtures/production_nazk_messages_integrated_f9eb8ed_v1.json").is_file():
        return source_root
    if (source_root / ".pqm_historical_integrity_overlay").is_file():
        _verify_historical_nazk_test(source_root)
        return source_root
    cached = _CACHE.get(source_root)
    if cached:
        _verify_historical_nazk_test(cached)
        return cached

    # Both the standalone Container smoke and the local runner enter here.
    # Restore the original test only in the disposable historical tree.
    historical_nazk_test = _historical_nazk_test(source_root)

    manifest_path = source_root / MANIFEST_RELATIVE
    manifest_raw = manifest_path.read_bytes()
    if _sha(manifest_raw) != MANIFEST_SHA256:
        raise AssertionError("Historical NAZK v1 manifest no longer matches its pinned hash")
    manifest = json.loads(manifest_raw)
    expected = {}
    for section in ("files", "protected_file_hashes", "historical_integrity_sha256"):
        expected.update(manifest.get(section, {}))
    expected[MANIFEST_RELATIVE.as_posix()] = MANIFEST_SHA256
    expected_names = set(expected)

    overlay_path = source_root / OVERLAY_RELATIVE
    overlay_bytes = overlay_path.read_bytes()
    if hashlib.sha256(overlay_bytes).hexdigest() != OVERLAY_SHA256:
        raise AssertionError("Historical NAZK recovery overlay hash mismatch")
    with zipfile.ZipFile(overlay_path) as archive:
        names = [item.filename for item in archive.infolist() if not item.is_dir()]
        if len(names) != len(set(names)) or set(names) != expected_names:
            raise AssertionError("Historical NAZK recovery overlay has an unexpected file set")

        temp = tempfile.TemporaryDirectory(prefix="pqm-production-integrity-overlay-")
        _TEMP_DIRS.append(temp)
        destination = Path(temp.name) / "tree"
        shutil.copytree(
            source_root,
            destination,
            ignore=shutil.ignore_patterns(
                ".git", ".local_tmp", ".gate_tmp", "__pycache__", "node_modules",
                ".venv", "venv", "data", "logs", "output", "backups",
            ),
        )
        for name in names:
            target = _safe_member(destination, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            content = archive.read(name)
            if _sha(content) != expected[name]:
                raise AssertionError(f"Historical overlay file hash mismatch: {name}")
            target.write_bytes(content)
        target = _safe_member(destination, NAZK_TEST_MEMBER)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(historical_nazk_test)
        _verify_historical_nazk_test(destination)
        (destination / ".pqm_historical_integrity_overlay").write_text("cbe1ec4b65bfc4b01285c20477d91974ccb411fe\n", encoding="ascii")

    _CACHE[source_root] = destination
    return destination
