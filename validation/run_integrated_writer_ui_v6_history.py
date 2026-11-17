"""Run integrated Writer/UI integrity v6 on its exact immutable Git snapshot."""
import hashlib
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


SNAPSHOT_COMMIT = '8e0dc787d0d1db8211fefcf531f722508d3d2d74'
TEST_MODULE = 'test_google_writer_integrated_candidate_integrity_v6'
MANIFEST_RELATIVE = Path('validation/local_release_20261116/pqm_sync_ui_integrated_v6.json')
MANIFEST_SHA256 = 'db2bcf83ad9b6bc2b7734176807b00a3359776951ac0779264d0eca2955d6aa9'
ARCHIVE_RELATIVE = Path('validation/fixtures/pqm_sync_ui_integrated_v6_8e0dc78.zip')
ARCHIVE_SHA256 = 'c1cb75c99aa17ecdb9640b2da8a18b9023952982cd50a9ea03fac2f3b1be8001'


def canonical(data):
    return data.replace(b'\r\n', b'\n')


def source_snapshot_archive(repo):
    manifest_bytes = canonical((repo / MANIFEST_RELATIVE).read_bytes())
    if hashlib.sha256(manifest_bytes).hexdigest() != MANIFEST_SHA256:
        raise RuntimeError('Integrated v6 manifest SHA mismatch')
    manifest = json.loads(manifest_bytes.decode('utf-8'))
    paths = sorted(set(manifest['scope']) | set(manifest['files']) | {str(MANIFEST_RELATIVE)})
    archive = subprocess.run(
        ['git', 'archive', '--format=zip', SNAPSHOT_COMMIT, '--', *paths],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout
    if hashlib.sha256(archive).hexdigest() != ARCHIVE_SHA256:
        raise RuntimeError('Integrated v6 Git snapshot archive SHA mismatch')
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
        if hashlib.sha256(archive).hexdigest() != ARCHIVE_SHA256:
            raise RuntimeError('Integrated v6 staged archive SHA mismatch')
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
