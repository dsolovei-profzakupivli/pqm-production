"""Run integrated Writer/UI integrity v5 on its exact immutable Git snapshot."""
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


SNAPSHOT_COMMIT = 'cd01e1376114781e43d408b5b83ee15e22050a53'
TEST_MODULE = 'test_google_writer_integrated_candidate_integrity_v5'
MANIFEST_RELATIVE = Path('validation/local_release_20261116/pqm_sync_ui_integrated_v5.json')
MANIFEST_SHA256 = '71a25437255990abed106836cdf91519c0a7323e223d601d258f6e19a98f358c'
ARCHIVE_RELATIVE = Path('validation/fixtures/pqm_sync_ui_integrated_v5_cd01e13.zip')


def canonical(data):
    return data.replace(b'\r\n', b'\n')


def source_snapshot_archive(repo):
    manifest_bytes = canonical((repo / MANIFEST_RELATIVE).read_bytes())
    if hashlib.sha256(manifest_bytes).hexdigest() != MANIFEST_SHA256:
        raise RuntimeError('Integrated v5 manifest SHA mismatch')
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
    try:
        archive = source_snapshot_archive(repo)
    except (FileNotFoundError, subprocess.CalledProcessError):
        fixture = repo / ARCHIVE_RELATIVE
        if not fixture.is_file():
            raise RuntimeError('Exact integrated v5 Git snapshot or staged archive is unavailable')
        archive = fixture.read_bytes()
    with tempfile.TemporaryDirectory(prefix='pqm-integrated-v5-') as temp:
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
