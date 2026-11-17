"""Run integrated Writer/UI integrity v7 from its exact immutable snapshot fixture."""
from io import BytesIO
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

from integrated_snapshot_archive import (
    SnapshotArchiveError,
    git_version,
    validate_snapshot_archive,
    verify_fixture_sha256,
)


TEST_MODULE = "test_google_writer_integrated_candidate_integrity_v7"
MANIFEST_RELATIVE = "validation/local_release_20261116/pqm_sync_ui_integrated_v7.json"
MANIFEST_SHA256 = "a52cd0a107f22d88f58d2f4db91534ae46fb4f58c932bdad7387fbd1c9b7e252"
ARCHIVE_RELATIVE = Path("validation/fixtures/pqm_sync_ui_integrated_v7_9b3dd33.zip")
ARCHIVE_SHA256 = "305adb9d89a1f5f46de8baa1bbd6f5100cf26d24d09b9aa10e70c00dba0539d8"


def main():
    repo = Path(__file__).resolve().parents[1]
    git = git_version(repo)
    fixture = repo / ARCHIVE_RELATIVE
    if not fixture.is_file():
        raise RuntimeError(f"Exact integrated v7 snapshot fixture is unavailable; git={git}")
    archive = fixture.read_bytes()
    try:
        verify_fixture_sha256(archive, ARCHIVE_SHA256, git)
        validate_snapshot_archive(
            archive,
            manifest_relative=MANIFEST_RELATIVE,
            expected_manifest_sha256=MANIFEST_SHA256,
            git_version_text=git,
            self_normalize_paths={TEST_MODULE + ".py"},
        )
    except SnapshotArchiveError as exc:
        raise RuntimeError(f"Integrated v7 immutable snapshot integrity mismatch: {exc}") from exc

    with tempfile.TemporaryDirectory(prefix="pqm-integrated-v7-") as temporary:
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
