"""Run integrated Writer/UI integrity v28 on its immutable candidate snapshot."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile
from io import BytesIO

import integrated_snapshot_archive
from integrated_git_snapshot import snapshot_archive_for_runner

SNAPSHOT_COMMIT = "1e75aa05c1b2c2018a28b13d158283414843473d"
MANIFEST_RELATIVE = "validation/local_release_20261116/pqm_sync_ui_integrated_v28.json"
MANIFEST_SHA256 = "21686ca702f1e57d8ec4b6b38c00e75ba7e21c133f600a8a5b31f64d8a988eb8"
TEST_MODULE = "test_google_writer_integrated_candidate_integrity_v28"
SELF_NORMALIZE = {
    f"test_google_writer_integrated_candidate_integrity_v{version}.py"
    for version in range(10, 29)
}
SELF_NORMALIZE.add(TEST_MODULE + ".py")
_manifest_rule = (
    re.compile(rb'(?m)^MANIFEST_SHA256 = "(?:<manifest-sha256>|[0-9a-f]{64})"$'),
    b'MANIFEST_SHA256 = "<manifest-sha256>"',
)
for _path in SELF_NORMALIZE:
    integrated_snapshot_archive.SELF_MANIFEST_RULES[_path] = _manifest_rule


def main():
    repository = Path(__file__).resolve().parents[1]
    archive, _version = snapshot_archive_for_runner(
        repository, version=28, commit=SNAPSHOT_COMMIT,
        manifest_relative=MANIFEST_RELATIVE,
        expected_manifest_sha256=MANIFEST_SHA256,
        self_normalize_paths=SELF_NORMALIZE,
    )
    with tempfile.TemporaryDirectory(prefix="pqm-integrated-v28-history-") as temporary:
        snapshot = Path(temporary)
        with zipfile.ZipFile(BytesIO(archive)) as bundle:
            for member in bundle.infolist():
                target = (snapshot / member.filename).resolve()
                if snapshot.resolve() not in target.parents:
                    raise RuntimeError(f"Unsafe v28 snapshot archive path: {member.filename!r}")
            bundle.extractall(snapshot)
        return subprocess.run(
            [sys.executable, "-B", "-m", "unittest", "-v", TEST_MODULE],
            cwd=snapshot, check=False,
        ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
