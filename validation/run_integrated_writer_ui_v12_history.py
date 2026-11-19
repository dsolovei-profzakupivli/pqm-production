"""Run integrated Writer/UI integrity v12 against its immutable Git snapshot."""
from io import BytesIO
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile

import integrated_snapshot_archive
from integrated_git_snapshot import snapshot_archive_for_runner


SNAPSHOT_COMMIT = "f8def8951eb9f95f1a5139bd7138681c4c1a9d7b"
MANIFEST_RELATIVE = "validation/local_release_20261116/pqm_sync_ui_integrated_v12.json"
MANIFEST_SHA256 = "f59ad8b9e1404935efa3020b164b47e2324e9635afb441dacb1b4933f6e598d8"
TEST_MODULE = "test_google_writer_integrated_candidate_integrity_v12"
SELF_NORMALIZE = {
    "test_google_writer_integrated_candidate_integrity_v10.py",
    "test_google_writer_integrated_candidate_integrity_v11.py",
    TEST_MODULE + ".py",
}
_self_manifest_rule = (
    re.compile(rb'(?m)^MANIFEST_SHA256 = "(?:<manifest-sha256>|[0-9a-f]{64})"$'),
    b'MANIFEST_SHA256 = "<manifest-sha256>"',
)
for _path in SELF_NORMALIZE:
    integrated_snapshot_archive.SELF_MANIFEST_RULES[_path] = _self_manifest_rule


def source_snapshot_archive(repository: Path) -> bytes:
    archive, _git_version = snapshot_archive_for_runner(
        repository,
        version=12,
        commit=SNAPSHOT_COMMIT,
        manifest_relative=MANIFEST_RELATIVE,
        expected_manifest_sha256=MANIFEST_SHA256,
        self_normalize_paths=SELF_NORMALIZE,
    )
    return archive


def main():
    repository = Path(__file__).resolve().parents[1]
    archive = source_snapshot_archive(repository)
    with tempfile.TemporaryDirectory(prefix="pqm-integrated-v12-history-") as temporary:
        snapshot = Path(temporary)
        with zipfile.ZipFile(BytesIO(archive)) as bundle:
            for member in bundle.infolist():
                target = (snapshot / member.filename).resolve()
                if snapshot.resolve() not in target.parents:
                    raise RuntimeError(f"Unsafe v12 snapshot archive path: {member.filename!r}")
            bundle.extractall(snapshot)
        return subprocess.run(
            [sys.executable, "-B", "-m", "unittest", "-v", TEST_MODULE],
            cwd=snapshot,
            check=False,
        ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
