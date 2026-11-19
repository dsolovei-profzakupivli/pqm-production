"""Run integrated Writer/UI integrity v15 against its immutable Git snapshot."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile
from io import BytesIO

import integrated_snapshot_archive
from integrated_git_snapshot import snapshot_archive_for_runner


SNAPSHOT_COMMIT = "86fe0d85bc36f431af6708918c07add73144f9db"
MANIFEST_RELATIVE = "validation/local_release_20261116/pqm_sync_ui_integrated_v15.json"
MANIFEST_SHA256 = "5097d801488b83b4bcae85650d7074ea1a13e755e390880258eb382ce0378977"
TEST_MODULE = "test_google_writer_integrated_candidate_integrity_v15"
SELF_NORMALIZE = {
    "test_google_writer_integrated_candidate_integrity_v10.py",
    "test_google_writer_integrated_candidate_integrity_v11.py",
    "test_google_writer_integrated_candidate_integrity_v12.py",
    "test_google_writer_integrated_candidate_integrity_v13.py",
    "test_google_writer_integrated_candidate_integrity_v14.py",
    TEST_MODULE + ".py",
}
_self_manifest_rule = (
    re.compile(rb'(?m)^MANIFEST_SHA256 = "(?:<manifest-sha256>|[0-9a-f]{64})"$'),
    b'MANIFEST_SHA256 = "<manifest-sha256>"',
)
for _path in SELF_NORMALIZE:
    integrated_snapshot_archive.SELF_MANIFEST_RULES[_path] = _self_manifest_rule


def source_snapshot_archive(repository: Path) -> bytes:
    archive, _version = snapshot_archive_for_runner(
        repository,
        version=15,
        commit=SNAPSHOT_COMMIT,
        manifest_relative=MANIFEST_RELATIVE,
        expected_manifest_sha256=MANIFEST_SHA256,
        self_normalize_paths=SELF_NORMALIZE,
    )
    return archive


def main():
    repository = Path(__file__).resolve().parents[1]
    archive = source_snapshot_archive(repository)
    with tempfile.TemporaryDirectory(prefix="pqm-integrated-v15-history-") as temporary:
        snapshot = Path(temporary)
        with zipfile.ZipFile(BytesIO(archive)) as bundle:
            for member in bundle.infolist():
                target = (snapshot / member.filename).resolve()
                if snapshot.resolve() not in target.parents:
                    raise RuntimeError(f"Unsafe v15 snapshot archive path: {member.filename!r}")
            bundle.extractall(snapshot)
        return subprocess.run(
            [sys.executable, "-B", "-m", "unittest", "-v", TEST_MODULE],
            cwd=snapshot,
            check=False,
        ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
