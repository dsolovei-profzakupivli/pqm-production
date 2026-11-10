"""Run the immutable source-snapshot v1 overlay against its pinned byte tree."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_REL = Path("validation/local_release_20261109/google_writer_legacy_source_snapshots_v1.json")
MANIFEST_SHA256 = "5974fdff6faa703603ef7ce41d78f40e162df2d9501906c5d9fc9a136071debd"
LEGACY_ARCHIVE_REL = Path("validation/fixtures/google_writer_all_scope_receipt_recovery_v1_9037e57.zip")
LEGACY_ARCHIVE_SHA256_RAW = "9d2fc834edbfe5668ec2bf8388d6d67cd21c692904261aa5bfd6f0eec780eafa"
RUNNER_FIXTURE_REL = Path("validation/fixtures/google_writer_legacy_source_snapshots_v1_run_local_release.py")
ARCHIVE_BACKED_PATHS = {
    "google_writer_execution.py",
    "scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxAllScopeExecution20261109.gs",
}
SELF_PINNED_TEST = "test_google_writer_legacy_source_snapshots_integrity_v1.py"
HISTORICAL_TEST_MODULE = "test_google_writer_legacy_source_snapshots_integrity_v1"


class SnapshotIntegrityError(RuntimeError):
    """A required historical byte or pin is absent or does not match."""


def canonical(path, raw):
    # Match the exact normalization performed by the untouched v1 assertion.
    return raw.replace(b"\r\n", b"\n")


def canonical_self(raw):
    import re
    normalized = raw.replace(b"\r\n", b"\n")
    return re.sub(
        rb'(?m)^MANIFEST_SHA256 = "(?:<manifest-sha256>|[0-9a-f]{64})"$',
        b'MANIFEST_SHA256 = "<manifest-sha256>"', normalized,
    )


def safe_target(root, relative):
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise SnapshotIntegrityError("Unsafe path in immutable snapshot manifest")
    target = (root / path).resolve()
    if not target.is_relative_to(root.resolve()):
        raise SnapshotIntegrityError("Snapshot path escapes the isolated tree")
    return target


def verify_bytes(relative, raw, expected, *, self_pinned=False):
    normalized = canonical_self(raw) if self_pinned else canonical(relative, raw)
    actual = hashlib.sha256(normalized).hexdigest()
    if actual != expected:
        raise SnapshotIntegrityError(f"Historical snapshot checksum mismatch: {relative}")
    return raw


def load_manifest(source_root, expected_sha256=MANIFEST_SHA256):
    path = source_root / MANIFEST_REL
    if not path.is_file():
        raise SnapshotIntegrityError("Immutable v1 snapshot manifest is missing")
    raw = canonical(MANIFEST_REL, path.read_bytes())
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise SnapshotIntegrityError("Immutable v1 snapshot manifest checksum mismatch")
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SnapshotIntegrityError("Immutable v1 snapshot manifest is invalid") from exc
    scope = manifest.get("scope")
    files = manifest.get("files")
    if (not isinstance(scope, list) or len(scope) != len(set(scope)) or
            not isinstance(files, dict) or set(scope) != set(files)):
        raise SnapshotIntegrityError("Immutable v1 snapshot scope and pins differ")
    return raw, manifest


def materialize_snapshot(source_root, destination, *, archive_path=None, runner_fixture_path=None,
                         expected_manifest_sha256=MANIFEST_SHA256):
    source_root = Path(source_root).resolve()
    destination = Path(destination).resolve()
    manifest_raw, manifest = load_manifest(source_root, expected_manifest_sha256)

    archive_path = Path(archive_path or (source_root / LEGACY_ARCHIVE_REL))
    if not archive_path.is_file():
        raise SnapshotIntegrityError("Pinned historical source archive is missing")
    archive_raw = archive_path.read_bytes()
    if hashlib.sha256(archive_raw).hexdigest() != LEGACY_ARCHIVE_SHA256_RAW:
        raise SnapshotIntegrityError("Pinned historical source archive checksum mismatch")
    try:
        archive = zipfile.ZipFile(archive_path)
    except zipfile.BadZipFile as exc:
        raise SnapshotIntegrityError("Pinned historical source archive is corrupt") from exc

    runner_fixture_path = Path(runner_fixture_path or (source_root / RUNNER_FIXTURE_REL))
    if not runner_fixture_path.is_file():
        archive.close()
        raise SnapshotIntegrityError("Pinned historical release-runner snapshot is missing")
    runner_expected = manifest["files"].get("validation/run_local_release.py")
    try:
        manifest_target = safe_target(destination, str(MANIFEST_REL))
        manifest_target.parent.mkdir(parents=True, exist_ok=True)
        manifest_target.write_bytes(manifest_raw)
        runner_raw = verify_bytes("validation/run_local_release.py", runner_fixture_path.read_bytes(),
                                  runner_expected)
        for relative in manifest["scope"]:
            expected = manifest["files"].get(relative)
            if not isinstance(relative, str) or not isinstance(expected, str):
                raise SnapshotIntegrityError("Invalid file entry in immutable v1 snapshot")
            target = safe_target(destination, relative)
            if relative == "validation/run_local_release.py":
                raw = runner_raw
            elif relative in ARCHIVE_BACKED_PATHS:
                try:
                    raw = archive.read(relative)
                except KeyError as exc:
                    raise SnapshotIntegrityError(f"Historical archive member is missing: {relative}") from exc
            else:
                source = safe_target(source_root, relative)
                if not source.is_file():
                    raise SnapshotIntegrityError(f"Pinned historical file is missing: {relative}")
                raw = source.read_bytes()
            verify_bytes(relative, raw, expected, self_pinned=(relative == SELF_PINNED_TEST))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)

        for relative, expected in manifest.get("preserved_manifests", {}).items():
            source = safe_target(source_root, relative)
            if not source.is_file():
                raise SnapshotIntegrityError(f"Preserved historical manifest is missing: {relative}")
            raw = verify_bytes(relative, source.read_bytes(), expected)
            target = safe_target(destination, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
    finally:
        archive.close()
    return destination


def run_history_test(source_root=ROOT):
    with tempfile.TemporaryDirectory(prefix="pqm-google-writer-snapshot-v1-", dir=source_root) as tmp:
        destination = Path(tmp).resolve() / "historical-tree"
        destination.mkdir()
        materialize_snapshot(source_root, destination)
        environment = os.environ.copy()
        environment["PQM_RELEASE_SOURCE_ROOT"] = str(destination)
        environment.pop("PQM_RELEASE_MODE", None)
        return subprocess.run(
            [sys.executable, "-B", "-m", "unittest", "-v", HISTORICAL_TEST_MODULE],
            cwd=destination, env=environment, check=False,
        ).returncode


def main():
    try:
        result = run_history_test()
    except SnapshotIntegrityError as exc:
        print(f"HISTORICAL SNAPSHOT STOP: {exc}", file=sys.stderr, flush=True)
        return 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())
