"""Run integrated Writer/UI integrity v10 against its immutable Git snapshot."""
from io import BytesIO
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile

import integrated_snapshot_archive
from integrated_git_snapshot import snapshot_archive_for_runner


SNAPSHOT_COMMIT = "27f28b501d37ce125e2334af769f2d23f33355b5"
MANIFEST_RELATIVE = "validation/local_release_20261116/pqm_sync_ui_integrated_v10.json"
MANIFEST_SHA256 = "f06808711ce9e961dce3b0c31c2bca084d170493d1ae83d4c421ce8c312c4727"
TEST_MODULE = "test_google_writer_integrated_candidate_integrity_v10"
SELF_NORMALIZE = {TEST_MODULE + ".py"}
integrated_snapshot_archive.SELF_MANIFEST_RULES[TEST_MODULE + ".py"] = (
    re.compile(rb'(?m)^MANIFEST_SHA256 = "(?:<manifest-sha256>|[0-9a-f]{64})"$'),
    b'MANIFEST_SHA256 = "<manifest-sha256>"',
)


def source_snapshot_archive(repository: Path) -> bytes:
    archive, _git_version = snapshot_archive_for_runner(
        repository,
        version=10,
        commit=SNAPSHOT_COMMIT,
        manifest_relative=MANIFEST_RELATIVE,
        expected_manifest_sha256=MANIFEST_SHA256,
        self_normalize_paths=SELF_NORMALIZE,
    )
    return archive


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
