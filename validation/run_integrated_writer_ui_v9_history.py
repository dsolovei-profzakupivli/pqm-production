"""Run integrated Writer/UI integrity v9 from its exact pinned snapshot."""
from io import BytesIO
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

from integrated_snapshot_archive import (
    SnapshotArchiveError,
    validate_snapshot_archive,
    verify_fixture_sha256,
)


TEST_MODULE = "test_google_writer_integrated_candidate_integrity_v9"
SNAPSHOT_COMMIT = "8e74484d3961b70355a4868c72336e22fad9d8de"
MANIFEST_RELATIVE = "validation/local_release_20261116/pqm_sync_ui_integrated_v9.json"
MANIFEST_SHA256 = "612c268e3555beecf79d9a32d2041d621e7b599cc7a42b8d89e3feecc52f1254"
ARCHIVE_RELATIVE = Path("validation/fixtures/pqm_sync_ui_integrated_v9_8e74484.zip")
ARCHIVE_SHA256 = "c6f04f1b5d149f487445e34089a2eaf06ab9e27346d856bf59ec46e5bc944550"


def main():
    repository = Path(__file__).resolve().parents[1]
    fixture = repository / ARCHIVE_RELATIVE
    if not fixture.is_file():
        raise RuntimeError(f"Exact integrated v9 snapshot fixture is unavailable: {ARCHIVE_RELATIVE}")
    archive = fixture.read_bytes()
    try:
        verify_fixture_sha256(archive, ARCHIVE_SHA256, "git version pinned fixture")
        validate_snapshot_archive(
            archive,
            manifest_relative=MANIFEST_RELATIVE,
            expected_manifest_sha256=MANIFEST_SHA256,
            git_version_text="git version pinned fixture",
            self_normalize_paths={TEST_MODULE + ".py"},
        )
    except SnapshotArchiveError as exc:
        raise RuntimeError(f"Integrated v9 immutable snapshot integrity mismatch: {exc}") from exc

    with tempfile.TemporaryDirectory(prefix="pqm-integrated-v9-history-") as temporary:
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
