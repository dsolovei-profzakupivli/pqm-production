"""Run integrated Writer/UI integrity v23 against its immutable Git snapshot."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile
from io import BytesIO

import integrated_snapshot_archive
from integrated_git_snapshot import snapshot_archive_for_runner


SNAPSHOT_COMMIT = "c6bac6226af3ed75e175b36aaa3a2dc55700b5af"
MANIFEST_RELATIVE = "validation/local_release_20261116/pqm_sync_ui_integrated_v23.json"
MANIFEST_SHA256 = "88cf0b074780d5ce5a1946ba849979254556be5d8020d477b9013ce931d24482"
TEST_MODULE = "test_google_writer_integrated_candidate_integrity_v23"
SELF_NORMALIZE = {
    f"test_google_writer_integrated_candidate_integrity_v{version}.py"
    for version in range(10, 24)
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
        version=23,
        commit=SNAPSHOT_COMMIT,
        manifest_relative=MANIFEST_RELATIVE,
        expected_manifest_sha256=MANIFEST_SHA256,
        self_normalize_paths=SELF_NORMALIZE,
    )
    return archive


def main():
    repository = Path(__file__).resolve().parents[1]
    archive = source_snapshot_archive(repository)
    with tempfile.TemporaryDirectory(prefix="pqm-integrated-v23-history-") as temporary:
        snapshot = Path(temporary)
        with zipfile.ZipFile(BytesIO(archive)) as bundle:
            for member in bundle.infolist():
                target = (snapshot / member.filename).resolve()
                if snapshot.resolve() not in target.parents:
                    raise RuntimeError(f"Unsafe v23 snapshot archive path: {member.filename!r}")
            bundle.extractall(snapshot)
        return subprocess.run(
            [sys.executable, "-B", "-m", "unittest", "-v", TEST_MODULE],
            cwd=snapshot,
            check=False,
        ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
