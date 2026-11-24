"""Run Sandbox integrated Writer/UI v28 against its immutable pre-integration snapshot."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile
from io import BytesIO

import integrated_snapshot_archive
from integrated_git_snapshot import snapshot_archive_for_runner

SNAPSHOT_COMMIT = "175d474a75cd236e6fbe3b5042c79c318460e118"
MANIFEST_RELATIVE = "validation/local_release_20261116/pqm_sync_ui_integrated_v28.json"
MANIFEST_SHA256 = "da17790c32b9a4dccd6c9a06324d6ab0fdc3d1c84123c7fe7737ac8cd4c45728"
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
    with tempfile.TemporaryDirectory(prefix="pqm-sandbox-integrated-v28-history-") as temporary:
        snapshot = Path(temporary)
        with zipfile.ZipFile(BytesIO(archive)) as bundle:
            for member in bundle.infolist():
                target = (snapshot / member.filename).resolve()
                if snapshot.resolve() not in target.parents:
                    raise RuntimeError(f"Unsafe Sandbox v28 snapshot archive path: {member.filename!r}")
            bundle.extractall(snapshot)
        return subprocess.run(
            [sys.executable, "-B", "-m", "unittest", "-v", TEST_MODULE],
            cwd=snapshot, check=False,
        ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
