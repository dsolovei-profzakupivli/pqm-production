"""Run the unchanged Messages search/header v2 contract on its exact tree."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OVERRIDES = 'validation/fixtures/messages_search_header_v2_overrides.zip'
OVERRIDES_SHA256 = '58a8f3cab5308e9a2b90d6cf1603ed8eb84f1e9ea7a73854fa2c642276a8a221'
V1_RUNNER_BASELINE = 'validation/fixtures/messages_search_header_v2_runner_40da.zip'
V1_RUNNER_BASELINE_SHA256 = '699512fcb46edef1eef183580dfefaF3dfb7f8ed82e5ffcfa5579c29699d3105'.lower()
EXPECTED_OVERRIDES = {
    'chat_annotations.css',
    'validation/chat_messages_browser.cjs',
    'validation/run_local_release.py',
}
EXPECTED_V1_RUNNER = {'validation/run_integrated_messages_v1_integrity.py'}


def main():
    archive_path = ROOT / OVERRIDES
    archive_bytes = archive_path.read_bytes()
    if hashlib.sha256(archive_bytes).hexdigest() != OVERRIDES_SHA256:
        raise SystemExit('Messages v2 override fixture SHA-256 mismatch')
    runner_archive_path = ROOT / V1_RUNNER_BASELINE
    runner_archive_bytes = runner_archive_path.read_bytes()
    if hashlib.sha256(runner_archive_bytes).hexdigest() != V1_RUNNER_BASELINE_SHA256:
        raise SystemExit('Messages v2 historical v1-runner fixture SHA-256 mismatch')
    with tempfile.TemporaryDirectory(prefix='pqm-messages-header-v2-') as temporary:
        tree = Path(temporary).resolve()
        shutil.copytree(ROOT, tree, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('.git', 'data', 'output', 'logs',
                                                      'evidence', '__pycache__', '.pytest_cache'))
        with zipfile.ZipFile(archive_path) as archive:
            members = {item.filename for item in archive.infolist() if not item.is_dir()}
            if members != EXPECTED_OVERRIDES:
                raise SystemExit('Unexpected Messages v2 override fixture members')
            for relative in sorted(members):
                target = (tree / relative).resolve()
                if not target.is_relative_to(tree):
                    raise SystemExit('Unsafe path in Messages v2 override fixture')
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(relative))
        with zipfile.ZipFile(runner_archive_path) as archive:
            members = {item.filename for item in archive.infolist() if not item.is_dir()}
            if members != EXPECTED_V1_RUNNER:
                raise SystemExit('Unexpected Messages v2 historical v1-runner fixture members')
            relative = next(iter(members))
            target = (tree / relative).resolve()
            if not target.is_relative_to(tree):
                raise SystemExit('Unsafe path in Messages v2 historical v1-runner fixture')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(relative))
        env = os.environ.copy()
        env.pop('PQM_RELEASE_SOURCE_ROOT', None)
        env['PYTHONPATH'] = str(tree)
        return subprocess.run(
            [sys.executable, '-m', 'unittest',
             'test_sandbox_messages_search_header_integrity_v2'],
            cwd=tree, env=env, check=False).returncode


if __name__ == '__main__':
    raise SystemExit(main())
