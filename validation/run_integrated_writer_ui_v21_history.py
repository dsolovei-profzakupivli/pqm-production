"""Run integrated Writer/UI integrity v21 against its immutable Git snapshot."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile
from io import BytesIO

import integrated_snapshot_archive
from integrated_git_snapshot import snapshot_archive_for_runner


SNAPSHOT_COMMIT = "2ca88abe5cfcd83afec90f3f6b4a8c0015c3c807"
MANIFEST_RELATIVE = "validation/local_release_20261116/pqm_sync_ui_integrated_v21.json"
MANIFEST_SHA256 = "d0136fe5103543c9594c8581f600c2ff7a0657c521e965fdb5cb350b04df49b6"
TEST_MODULE = "test_google_writer_integrated_candidate_integrity_v21"
SELF_NORMALIZE = {
    f"test_google_writer_integrated_candidate_integrity_v{version}.py"
    for version in range(10, 22)
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
        version=21,
        commit=SNAPSHOT_COMMIT,
        manifest_relative=MANIFEST_RELATIVE,
        expected_manifest_sha256=MANIFEST_SHA256,
        self_normalize_paths=SELF_NORMALIZE,
    )
    return archive


def main():
    repository = Path(__file__).resolve().parents[1]
    archive = source_snapshot_archive(repository)
    with tempfile.TemporaryDirectory(prefix="pqm-integrated-v21-history-") as temporary:
        snapshot = Path(temporary)
        with zipfile.ZipFile(BytesIO(archive)) as bundle:
            for member in bundle.infolist():
                target = (snapshot / member.filename).resolve()
                if snapshot.resolve() not in target.parents:
                    raise RuntimeError(f"Unsafe v21 snapshot archive path: {member.filename!r}")
            bundle.extractall(snapshot)
        return subprocess.run(
            [sys.executable, "-B", "-m", "unittest", "-v", TEST_MODULE],
            cwd=snapshot,
            check=False,
        ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
