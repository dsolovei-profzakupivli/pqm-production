"""Run integrated Writer/UI integrity v10 against its immutable Git snapshot."""
from io import BytesIO
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile

import integrated_snapshot_archive
from integrated_snapshot_archive import SnapshotArchiveError, validate_snapshot_archive


SNAPSHOT_COMMIT = "27f28b501d37ce125e2334af769f2d23f33355b5"
MANIFEST_RELATIVE = "validation/local_release_20261116/pqm_sync_ui_integrated_v10.json"
MANIFEST_SHA256 = "f06808711ce9e961dce3b0c31c2bca084d170493d1ae83d4c421ce8c312c4727"
TEST_MODULE = "test_google_writer_integrated_candidate_integrity_v10"
SELF_NORMALIZE = {TEST_MODULE + ".py"}
integrated_snapshot_archive.SELF_MANIFEST_RULES[TEST_MODULE + ".py"] = (
    re.compile(rb'(?m)^MANIFEST_SHA256 = "(?:<manifest-sha256>|[0-9a-f]{64})"$'),
    b'MANIFEST_SHA256 = "<manifest-sha256>"',
)


def _git_blob(repository: Path, path: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{SNAPSHOT_COMMIT}:{path}"], cwd=repository,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if result.returncode:
        raise RuntimeError(f"Could not read v10 snapshot file {path}: {result.stderr.decode(errors='replace')}")
    return result.stdout


def source_snapshot_archive(repository: Path) -> bytes:
    try:
        manifest_bytes = _git_blob(repository, MANIFEST_RELATIVE)
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        paths = sorted(set(manifest["scope"]) | {MANIFEST_RELATIVE})
        archive_buffer = BytesIO()
        with zipfile.ZipFile(archive_buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
            for path in paths:
                bundle.writestr(path, _git_blob(repository, path))
        archive = archive_buffer.getvalue()
        validate_snapshot_archive(
            archive,
            manifest_relative=MANIFEST_RELATIVE,
            expected_manifest_sha256=MANIFEST_SHA256,
            git_version_text=subprocess.run(
                ["git", "--version"], cwd=repository, check=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            ).stdout.strip(),
            self_normalize_paths=SELF_NORMALIZE,
        )
        return archive
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError, SnapshotArchiveError) as exc:
        raise RuntimeError(f"Integrated v10 immutable snapshot validation failed: {exc}") from exc


def main():
    repository = Path(__file__).resolve().parents[1]
    archive = source_snapshot_archive(repository)
    with tempfile.TemporaryDirectory(prefix="pqm-integrated-v10-history-") as temporary:
        snapshot = Path(temporary)
        with zipfile.ZipFile(BytesIO(archive)) as bundle:
            bundle.extractall(snapshot)
        return subprocess.run(
            [sys.executable, "-B", "-m", "unittest", "-v", TEST_MODULE],
            cwd=snapshot,
            check=False,
        ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
