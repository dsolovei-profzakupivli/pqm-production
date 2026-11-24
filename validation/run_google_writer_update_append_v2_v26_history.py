"""Run the immutable Update Append v2 integrity suite on exact V26 bytes."""
from hashlib import sha256
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import zipfile
from io import BytesIO

import integrated_snapshot_archive

SNAPSHOT_COMMIT = "e436c952b17fc79ccb8fc1f8c366cbbf18ca31fc"
MANIFEST_RELATIVE = "validation/local_release_20261116/pqm_sync_ui_integrated_v26.json"
MANIFEST_SHA256 = "d858aa19de810f8a40a935a528006f6d38537961ba4b1e97d31f6272323a62dc"
TEST_MODULE = "test_google_writer_update_append_v2_integrity"
FULL_ARCHIVE_ENV = "PQM_UPDATE_APPEND_V2_V26_FULL_ARCHIVE"
FULL_ARCHIVE_SHA_ENV = FULL_ARCHIVE_ENV + "_SHA256"


def snapshot_bytes(repository: Path) -> bytes:
    archive_path = os.environ.get(FULL_ARCHIVE_ENV, "").strip()
    expected_archive_sha = os.environ.get(FULL_ARCHIVE_SHA_ENV, "").strip().lower()
    if archive_path:
        archive = Path(archive_path).read_bytes()
        if not expected_archive_sha or sha256(archive).hexdigest() != expected_archive_sha:
            raise RuntimeError("Full V26 Git archive is missing its matching SHA-256")
        return archive
    result = subprocess.run(
        ["git", "archive", "--format=zip", SNAPSHOT_COMMIT],
        cwd=repository, check=True, capture_output=True,
    )
    return result.stdout


def main():
    repository = Path(__file__).resolve().parents[1]
    archive = snapshot_bytes(repository)
    with zipfile.ZipFile(BytesIO(archive)) as bundle:
        manifest_bytes = integrated_snapshot_archive.canonical_eol(bundle.read(MANIFEST_RELATIVE))
        if sha256(manifest_bytes).hexdigest() != MANIFEST_SHA256:
            raise RuntimeError("Full Git archive does not contain the pinned V26 manifest")
    with tempfile.TemporaryDirectory(prefix="pqm-update-append-v2-v26-") as temporary:
        snapshot = Path(temporary)
        with zipfile.ZipFile(BytesIO(archive)) as bundle:
            for member in bundle.infolist():
                target = (snapshot / member.filename).resolve()
                if snapshot.resolve() not in target.parents:
                    raise RuntimeError(f"Unsafe V26 snapshot archive path: {member.filename!r}")
            bundle.extractall(snapshot)
        return subprocess.run(
            [sys.executable, "-B", "-m", "unittest", "-v", TEST_MODULE],
            cwd=snapshot, check=False,
        ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
