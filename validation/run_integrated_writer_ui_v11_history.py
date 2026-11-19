"""Run integrated Writer/UI integrity v11 from its immutable Git snapshot."""
from io import BytesIO
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile

import integrated_snapshot_archive
from integrated_git_snapshot import snapshot_archive_for_runner


SNAPSHOT_COMMIT = "b2804d6e20e6b81b128508f285eb71e807f01ddf"
MANIFEST_RELATIVE = "validation/local_release_20261116/pqm_sync_ui_integrated_v11.json"
MANIFEST_SHA256 = "e96321367b2e724f7dc452e35b9f418741ced4a2e8525191a505f7db6c190c3b"
TEST_MODULE = "test_google_writer_integrated_candidate_integrity_v11"
PREVIOUS_TEST_MODULE = "test_google_writer_integrated_candidate_integrity_v10"
SELF_NORMALIZE = {TEST_MODULE + ".py", PREVIOUS_TEST_MODULE + ".py"}
_self_manifest_rule = (
    re.compile(rb'(?m)^MANIFEST_SHA256 = "(?:<manifest-sha256>|[0-9a-f]{64})"$'),
    b'MANIFEST_SHA256 = "<manifest-sha256>"',
)
integrated_snapshot_archive.SELF_MANIFEST_RULES[TEST_MODULE + ".py"] = _self_manifest_rule
integrated_snapshot_archive.SELF_MANIFEST_RULES[PREVIOUS_TEST_MODULE + ".py"] = _self_manifest_rule


def source_snapshot_archive(repository: Path) -> bytes:
    archive, _git_version = snapshot_archive_for_runner(
        repository,
        version=11,
        commit=SNAPSHOT_COMMIT,
        manifest_relative=MANIFEST_RELATIVE,
        expected_manifest_sha256=MANIFEST_SHA256,
        self_normalize_paths=SELF_NORMALIZE,
    )
    return archive


def main():
    repository = Path(__file__).resolve().parents[1]
    archive = source_snapshot_archive(repository)
    with tempfile.TemporaryDirectory(prefix="pqm-integrated-v11-history-") as temporary:
        snapshot = Path(temporary)
        with zipfile.ZipFile(BytesIO(archive)) as bundle:
            for member in bundle.infolist():
                target = (snapshot / member.filename).resolve()
                if snapshot.resolve() not in target.parents:
                    raise RuntimeError(f"Unsafe v11 snapshot archive path: {member.filename!r}")
            bundle.extractall(snapshot)
        return subprocess.run(
            [sys.executable, "-B", "-m", "unittest", "-v", TEST_MODULE],
            cwd=snapshot,
            check=False,
        ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
