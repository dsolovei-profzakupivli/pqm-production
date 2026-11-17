"""Run integrated Writer/UI integrity v6 on its exact immutable Git snapshot."""
import hashlib
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

from integrated_snapshot_archive import (
    SnapshotArchiveError,
    canonical_eol,
    git_version,
    validate_snapshot_archive,
    verify_fixture_sha256,
)


SNAPSHOT_COMMIT = '8e0dc787d0d1db8211fefcf531f722508d3d2d74'
TEST_MODULE = 'test_google_writer_integrated_candidate_integrity_v6'
MANIFEST_RELATIVE = Path('validation/local_release_20261116/pqm_sync_ui_integrated_v6.json')
MANIFEST_SHA256 = 'db2bcf83ad9b6bc2b7734176807b00a3359776951ac0779264d0eca2955d6aa9'
ARCHIVE_RELATIVE = Path('validation/fixtures/pqm_sync_ui_integrated_v6_8e0dc78.zip')
ARCHIVE_SHA256 = 'c1cb75c99aa17ecdb9640b2da8a18b9023952982cd50a9ea03fac2f3b1be8001'


def source_snapshot_archive(repo):
    git = git_version(repo)
    manifest_bytes = canonical_eol((repo / MANIFEST_RELATIVE).read_bytes())
    actual_manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    if actual_manifest_sha != MANIFEST_SHA256:
        raise RuntimeError(
            f'Integrated v6 manifest SHA mismatch: expected={MANIFEST_SHA256}, '
            f'actual={actual_manifest_sha}; git={git}'
        )
    try:
        manifest = json.loads(manifest_bytes.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f'Integrated v6 manifest is invalid; git={git}: {exc}') from exc
    paths = sorted(set(manifest['scope']) | set(manifest['files']) | {str(MANIFEST_RELATIVE)})
    archive = subprocess.run(
        ['git', 'archive', '--format=zip', SNAPSHOT_COMMIT, '--', *paths],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout
    try:
        validate_snapshot_archive(
            archive,
            manifest_relative=MANIFEST_RELATIVE.as_posix(),
            expected_manifest_sha256=MANIFEST_SHA256,
            git_version_text=git,
            self_normalize_paths={TEST_MODULE + '.py'},
        )
    except SnapshotArchiveError as exc:
        raise RuntimeError(f'Integrated v6 Git snapshot integrity mismatch: {exc}') from exc
    return archive


def main():
    repo = Path(__file__).resolve().parents[1]
    try:
        archive = source_snapshot_archive(repo)
    except (FileNotFoundError, subprocess.CalledProcessError):
        fixture = repo / ARCHIVE_RELATIVE
        if not fixture.is_file():
            raise RuntimeError('Exact integrated v6 Git snapshot or staged archive is unavailable')
        archive = fixture.read_bytes()
        git = git_version(repo)
        try:
            verify_fixture_sha256(archive, ARCHIVE_SHA256, git)
            validate_snapshot_archive(
                archive,
                manifest_relative=MANIFEST_RELATIVE.as_posix(),
                expected_manifest_sha256=MANIFEST_SHA256,
                git_version_text=git,
                self_normalize_paths={TEST_MODULE + '.py'},
            )
        except SnapshotArchiveError as exc:
            raise RuntimeError(f'Integrated v6 staged archive integrity mismatch: {exc}') from exc
    with tempfile.TemporaryDirectory(prefix='pqm-integrated-v6-') as temp:
        snapshot = Path(temp)
        with zipfile.ZipFile(BytesIO(archive)) as bundle:
            for member in bundle.infolist():
                target = (snapshot / member.filename).resolve()
                if snapshot.resolve() not in target.parents and target != snapshot.resolve():
                    raise RuntimeError('Snapshot archive contains an unsafe path')
            bundle.extractall(snapshot)
        return subprocess.run(
            [sys.executable, '-B', '-m', 'unittest', '-v', TEST_MODULE],
            cwd=snapshot,
            check=False,
        ).returncode


if __name__ == '__main__':
    raise SystemExit(main())
