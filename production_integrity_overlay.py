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
        return source_root
    cached = _CACHE.get(source_root)
    if cached:
        return cached

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
        (destination / ".pqm_historical_integrity_overlay").write_text("cbe1ec4b65bfc4b01285c20477d91974ccb411fe\n", encoding="ascii")

    _CACHE[source_root] = destination
    return destination
