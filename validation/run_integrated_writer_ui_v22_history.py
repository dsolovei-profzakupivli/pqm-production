"""Run integrated Writer/UI integrity v22 against its immutable Git snapshot."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile
from io import BytesIO

import integrated_snapshot_archive
from integrated_git_snapshot import snapshot_archive_for_runner


SNAPSHOT_COMMIT = "aecd6c10ecdad2a8d51b7153cc9717c5b3a4e66c"
MANIFEST_RELATIVE = "validation/local_release_20261116/pqm_sync_ui_integrated_v22.json"
MANIFEST_SHA256 = "fbe60d95b335aa9da53dbe161c8fb67cdf3679722472156655c27cdf77877b59"
TEST_MODULE = "test_google_writer_integrated_candidate_integrity_v22"
SELF_NORMALIZE = {
    f"test_google_writer_integrated_candidate_integrity_v{version}.py"
    for version in range(10, 23)
}
SELF_NORMALIZE.add(TEST_MODULE + ".py")
_self_manifest_rule = (
    re.compile(rb'(?m)^MANIFEST_SHA256 = "(?:<manifest-sha256>|[0-9a-f]{64})"$'),
    b'MANIFEST_SHA256 = "<manifest-sha256>"',
)
for _path in SELF_NORMALIZE:
    integrated_snapshot_archive.SELF_MANIFEST_RULES[_path] = _self_manifest_rule


def source_snapshot_archive(repository: Path) -> bytes:
    archive, _version = snapshot_archive_for_runner(
        repository,
        version=22,
        commit=SNAPSHOT_COMMIT,
        manifest_relative=MANIFEST_RELATIVE,
        expected_manifest_sha256=MANIFEST_SHA256,
        self_normalize_paths=SELF_NORMALIZE,
    )
    return archive


def main():
    repository = Path(__file__).resolve().parents[1]
    archive = source_snapshot_archive(repository)
    with tempfile.TemporaryDirectory(prefix="pqm-integrated-v22-history-") as temporary:
        snapshot = Path(temporary)
        with zipfile.ZipFile(BytesIO(archive)) as bundle:
            for member in bundle.infolist():
                target = (snapshot / member.filename).resolve()
                if snapshot.resolve() not in target.parents:
                    raise RuntimeError(f"Unsafe v22 snapshot archive path: {member.filename!r}")
            bundle.extractall(snapshot)
        return subprocess.run(
            [sys.executable, "-B", "-m", "unittest", "-v", TEST_MODULE],
            cwd=snapshot,
            check=False,
        ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
