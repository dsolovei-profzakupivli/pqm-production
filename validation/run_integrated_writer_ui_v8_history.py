"""Run integrated Writer/UI integrity v8 from its exact immutable snapshot fixture."""
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


TEST_MODULE = "test_google_writer_integrated_candidate_integrity_v8"
SNAPSHOT_COMMIT = "b7d8279ab8616553140ce7012685242631f6b1c3"
MANIFEST_RELATIVE = "validation/local_release_20261116/pqm_sync_ui_integrated_v8.json"
MANIFEST_SHA256 = "027783c537408f24656f7498d6d6bb6422a7db6b49e441e0d56fb2369e5b29d2"
ARCHIVE_RELATIVE = Path("validation/fixtures/pqm_sync_ui_integrated_v8_b7d8279.zip")
ARCHIVE_SHA256 = "6e190bdbbaa60e1bed371481a01162111c5060b2acdd94ba231ccbf6b09621d1"


def main():
    repo = Path(__file__).resolve().parents[1]
    git = git_version(repo)
    fixture = repo / ARCHIVE_RELATIVE
    if not fixture.is_file():
        raise RuntimeError(f"Exact integrated v8 snapshot fixture is unavailable; git={git}")
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
        raise RuntimeError(f"Integrated v8 immutable snapshot integrity mismatch: {exc}") from exc

    with tempfile.TemporaryDirectory(prefix="pqm-integrated-v8-") as temporary:
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
