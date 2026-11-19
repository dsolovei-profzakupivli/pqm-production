"""Run integrated Writer/UI integrity v1 on its exact immutable Git snapshot."""
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


SNAPSHOT_COMMIT = '3eda8169d8dae0d76bf14b276c16e6773dd746d6'
TEST_MODULE = 'test_google_writer_integrated_candidate_integrity_v1'
MANIFEST_RELATIVE = Path('validation/local_release_20261116/pqm_sync_ui_integrated_v1.json')
MANIFEST_SHA256 = 'cec0c8c637a51e021c21532a76e2b8d1ebbd4990489e0e920229e33bb417b3a9'
ARCHIVE_RELATIVE = Path('validation/fixtures/pqm_sync_ui_integrated_v1_3eda816.zip')


def canonical(data):
    return data.replace(b'\r\n', b'\n')


def source_snapshot_archive(repo):
    manifest_bytes = canonical((repo / MANIFEST_RELATIVE).read_bytes())
    if hashlib.sha256(manifest_bytes).hexdigest() != MANIFEST_SHA256:
        raise RuntimeError('Integrated v1 manifest SHA mismatch')
    manifest = json.loads(manifest_bytes.decode('utf-8'))
    paths = sorted(set(manifest['scope']) | set(manifest['files']) | {str(MANIFEST_RELATIVE)})
    return subprocess.run(
        ['git', 'archive', '--format=zip', SNAPSHOT_COMMIT, '--', *paths],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def main():
    repo = Path(__file__).resolve().parents[1]
    archive_output = os.environ.get('PQM_INTEGRATED_V1_ARCHIVE_OUT')
    try:
        archive = source_snapshot_archive(repo)
    except (FileNotFoundError, subprocess.CalledProcessError):
        fixture = repo / ARCHIVE_RELATIVE
        if not fixture.is_file():
            raise RuntimeError('Exact integrated v1 Git snapshot or staged archive is unavailable')
        archive = fixture.read_bytes()
    if archive_output:
        archive_path = Path(archive_output)
        if not archive_path.is_absolute():
            archive_path = repo / archive_path
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        archive_path.write_bytes(archive)
    with tempfile.TemporaryDirectory(prefix='pqm-integrated-v1-') as temp:
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
