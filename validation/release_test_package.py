"""Single source of truth for the delivered Release Gate test package."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import Iterable


PACKAGE_MANIFEST = Path("validation/release_test_package_v1.json")
PACKAGE_HELPER = Path("validation/release_test_package.py")


def load_package_manifest(source_root: Path) -> dict:
    path = Path(source_root) / PACKAGE_MANIFEST
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise RuntimeError(f"Unsupported release test package manifest: {path}")
    return payload


def _manifest_paths(manifest: dict, mode: str = "", source_root: Path | None = None) -> list[str]:
    versions = manifest["integrated_history_versions"]
    test_versions = manifest["integrity_test_versions"]
    release_dir = manifest["integrity_manifest_dir"]
    if mode == "historical_integrity":
        source_root = Path(source_root)
        test_versions = [version for version in test_versions
                         if (source_root / f"test_google_writer_integrated_candidate_integrity_v{version}.py").is_file()
                         and (source_root / release_dir / f"pqm_sync_ui_integrated_v{version}.json").is_file()]
    paths = [
        f"validation/run_integrated_writer_ui_v{version}_history.py"
        for version in versions
    ]
    paths.extend(
        f"test_google_writer_integrated_candidate_integrity_v{version}.py"
        for version in test_versions
    )
    paths.extend(
        f"{release_dir}/pqm_sync_ui_integrated_v{version}.json"
        for version in test_versions
    )
    paths.extend(
        f"validation/local_release_20260911/{name}"
        for name in manifest["required_local_release_tests"]
        if mode != "historical_integrity"
        or (Path(source_root) / "validation/local_release_20260911" / name).is_file()
    )
    paths.extend(
        f"validation/{name}"
        for name in manifest["snapshot_support_files"]
        + manifest["supplemental_validation_files"]
    )
    paths.extend(manifest["pinned_release_files"])
    paths.extend(manifest["infrastructure_auxiliary_files"])
    if mode != "historical_integrity":
        paths.extend(f"validation/fixtures/{name}"
                     for name in manifest["release_fixture_basenames"])
    paths.extend(manifest["root_level_release_files"])
    paths.extend((
        PACKAGE_MANIFEST.as_posix(),
        PACKAGE_HELPER.as_posix(),
        manifest["infrastructure_release_runner"],
        manifest["candidate_docker_gate"],
        manifest["candidate_workflow"],
    ))
    return list(dict.fromkeys(paths))


def _source_candidates(relative: str, source_root: Path, infrastructure_root: Path,
                       mode: str, manifest: dict) -> tuple[Path, ...]:
    relative_path = Path(relative)
    if relative in manifest["pinned_release_files"]:
        return (Path(source_root) / relative_path,)
    if relative == manifest["infrastructure_release_runner"]:
        return (Path(infrastructure_root) / relative_path,)
    if relative in manifest["infrastructure_auxiliary_files"]:
        return (Path(infrastructure_root) / relative_path,)
    if mode == "historical_integrity" and relative in {
        PACKAGE_MANIFEST.as_posix(), PACKAGE_HELPER.as_posix(),
        manifest["candidate_docker_gate"], manifest["candidate_workflow"],
        *manifest["root_level_release_files"],
    }:
        return (Path(source_root) / relative_path,
                Path(infrastructure_root) / relative_path)
    if relative in manifest["root_level_release_files"]:
        return (Path(source_root) / relative_path,)
    validation_name = relative_path.name
    history_names = {f"run_integrated_writer_ui_v{version}_history.py"
                     for version in manifest["integrated_history_versions"]}
    snapshot_names = set(manifest["snapshot_support_files"])
    if relative.startswith("validation/") and validation_name in history_names | snapshot_names:
        candidate = Path(source_root) / relative_path
        if mode == "historical_integrity":
            return candidate, Path(infrastructure_root) / relative_path
        return (candidate,)
    fallback_names = set(manifest["supplemental_validation_files"])
    if relative.startswith("validation/") and validation_name in fallback_names:
        return (Path(source_root) / relative_path,
                Path(infrastructure_root) / relative_path)
    if relative.startswith("validation/fixtures/"):
        candidate = Path(source_root) / relative_path
        if candidate.name == "google_writer_historical_integrity_snapshots_v1_compact.zip":
            return (Path(infrastructure_root) / relative_path,)
        if mode == "historical_integrity":
            return candidate, Path(infrastructure_root) / relative_path
        return (candidate,)
    return (Path(source_root) / relative_path,)


def _dynamic_copy_pairs(source_root: Path, infrastructure_root: Path,
                        manifest: dict) -> list[tuple[Path, Path]]:
    """Return files covered by the existing whole-tree and glob copy rules."""
    source_root = Path(source_root)
    infrastructure_root = Path(infrastructure_root)
    pairs: list[tuple[Path, Path]] = []
    excluded = {"data", "validation", "__pycache__", "backups", "output", "logs", "evidence"}
    for source in source_root.iterdir():
        if source.name.startswith(".") or source.name in excluded:
            continue
        if source.is_file():
            pairs.append((source, Path(source.name)))
        elif source.is_dir():
            pairs.extend((item, item.relative_to(source_root))
                         for item in source.rglob("*") if item.is_file())

    local_release = source_root / "validation/local_release_20260911"
    if local_release.is_dir():
        pairs.extend((item, Path(item.name))
                     for item in local_release.glob("test_*.py") if item.is_file())
        pairs.extend((item, item.relative_to(source_root))
                     for item in local_release.rglob("*")
                     if item.is_file() and "__pycache__" not in item.parts)

    snapshots = source_root / "validation/legacy_snapshots"
    if snapshots.is_dir():
        pairs.extend((item, item.relative_to(source_root))
                     for item in snapshots.rglob("*")
                     if item.is_file() and "__pycache__" not in item.parts)

    for pattern in ("sandbox_preview_*.json",):
        pairs.extend((item, item.relative_to(source_root))
                     for item in (source_root / "validation").glob(pattern) if item.is_file())
    for release_dir in (source_root / "validation").glob("local_release_*"):
        if release_dir.is_dir():
            pairs.extend((item, item.relative_to(source_root))
                         for item in release_dir.rglob("*.json") if item.is_file())
    pairs.extend((item, item.relative_to(source_root))
                 for item in (source_root / "validation").glob("*.cjs") if item.is_file())
    gitattributes = source_root / ".gitattributes"
    if gitattributes.is_file():
        pairs.append((gitattributes, Path(".gitattributes")))
    for name in manifest["root_level_release_files"]:
        source = source_root / name
        if source.is_file():
            pairs.append((source, Path(name)))
    return pairs


def stage_dynamic_package_files(source_root: Path, staging_root: Path,
                                infrastructure_root: Path,
                                manifest: dict | None = None) -> None:
    """Stage the same tree/glob payload that preflight later verifies."""
    manifest = manifest or load_package_manifest(source_root)
    staging_root = Path(staging_root)
    for source, relative_target in _dynamic_copy_pairs(
        Path(source_root), Path(infrastructure_root), manifest
    ):
        target = staging_root / relative_target
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def package_dependency_map(source_root: Path, infrastructure_root: Path,
                           mode: str = "", manifest: dict | None = None
                           ) -> list[tuple[str, tuple[Path, ...]]]:
    source_root = Path(source_root)
    manifest = manifest or load_package_manifest(source_root)
    return [
        (relative, _source_candidates(relative, source_root,
                                       Path(infrastructure_root), mode, manifest))
        for relative in _manifest_paths(manifest, mode, source_root)
    ]


def stage_dependency_map(dependencies: Iterable[tuple[str, tuple[Path, ...]]],
                         staging_root: Path) -> None:
    staging_root = Path(staging_root)
    for relative, candidates in dependencies:
        source = next((candidate for candidate in candidates if candidate.is_file()), None)
        if source is None:
            continue
        target = staging_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def preflight_dependency_map(dependencies: Iterable[tuple[str, tuple[Path, ...]]],
                             staging_root: Path) -> tuple[list[str], list[str]]:
    staging_root = Path(staging_root)
    source_missing: list[str] = []
    staging_missing: list[str] = []
    for relative, candidates in dependencies:
        if not any(candidate.is_file() for candidate in candidates):
            source_missing.append(relative)
        elif not (staging_root / relative).is_file():
            staging_missing.append(relative)
    return sorted(set(source_missing)), sorted(set(staging_missing))


def format_preflight_error(source_missing: Iterable[str],
                           staging_missing: Iterable[str]) -> str:
    lines = ["Release test package preflight failed:"]
    source_missing = sorted(set(source_missing))
    staging_missing = sorted(set(staging_missing))
    if source_missing:
        lines.append("SOURCE missing:")
        lines.extend(f"  - {path}" for path in source_missing)
    if staging_missing:
        lines.append("STAGING missing:")
        lines.extend(f"  - {path}" for path in staging_missing)
    return "\n".join(lines)


def stage_declared_files(source_root: Path, staging_root: Path,
                         infrastructure_root: Path, mode: str = "",
                         manifest: dict | None = None) -> None:
    """Stage required explicit files. Missing entries are reported by preflight."""
    source_root = Path(source_root)
    staging_root = Path(staging_root)
    infrastructure_root = Path(infrastructure_root)
    manifest = manifest or load_package_manifest(source_root)
    pinned = set(manifest["pinned_release_files"])
    dependencies = [item for item in package_dependency_map(
        source_root, infrastructure_root, mode, manifest) if item[0] not in pinned]
    stage_dependency_map(dependencies, staging_root)


def preflight_package(source_root: Path, staging_root: Path,
                      infrastructure_root: Path, mode: str = "",
                      manifest: dict | None = None) -> None:
    """Fail once, with complete SOURCE/STAGING lists, before test discovery."""
    source_root = Path(source_root)
    staging_root = Path(staging_root)
    infrastructure_root = Path(infrastructure_root)
    manifest = manifest or load_package_manifest(source_root)
    source_missing: set[str] = set()
    staging_missing: set[str] = set()

    dependencies = package_dependency_map(source_root, infrastructure_root, mode, manifest)
    explicit_source_missing, explicit_staging_missing = preflight_dependency_map(
        dependencies, staging_root)
    source_missing: set[str] = set(explicit_source_missing)
    staging_missing: set[str] = set(explicit_staging_missing)
    pairs: list[tuple[Path, Path, str]] = []

    for source, relative_target in _dynamic_copy_pairs(source_root, infrastructure_root, manifest):
        try:
            label = source.relative_to(source_root).as_posix()
        except ValueError:
            label = relative_target.as_posix()
        pairs.append((source, relative_target, label))

    for source, relative_target, label in pairs:
        if not source.is_file():
            source_missing.add(label)
        if not (staging_root / relative_target).is_file():
            staging_missing.add(relative_target.as_posix())

    # A disposable release package must never inherit repository metadata.
    if (staging_root / ".git").exists():
        staging_missing.add(".git (unexpected in isolated test package)")

    if source_missing or staging_missing:
        raise RuntimeError(format_preflight_error(source_missing, staging_missing))
