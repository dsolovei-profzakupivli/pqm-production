"""Run unchanged integrated Messages v1 integrity tests on their exact tree."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = 'test_sandbox_nazk_messages_integrated_v1.json'
OVERRIDES = 'validation/fixtures/messages_integrated_v1_overrides.zip'
OVERRIDES_SHA256 = '78287b12633f82c3a366e2377d35eec4a0b96ecba28f2bfd5ea3e79982ea7928'
EXPECTED_OVERRIDES = {
    'chat_annotations.css',
    'chat_annotations.py',
    'index.html',
    'test_sandbox_nazk_messages_integrated_integrity.py',
    'validation/chat_messages_browser.cjs',
    'validation/local_release_20260911/test_chat_annotations.py',
    'validation/local_release_20260911/test_chat_annotations_http.py',
    'validation/run_local_release.py',
}


def main():
    manifest = json.loads((ROOT / MANIFEST).read_text(encoding='utf-8'))
    archive_path = ROOT / OVERRIDES
    archive_bytes = archive_path.read_bytes()
    if hashlib.sha256(archive_bytes).hexdigest() != OVERRIDES_SHA256:
        raise SystemExit('Integrated v1 override fixture SHA-256 mismatch')
    with tempfile.TemporaryDirectory(prefix='pqm-integrated-messages-v1-') as temporary:
        tree = Path(temporary).resolve()
        shutil.copytree(ROOT, tree, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('.git', 'data', 'output', 'logs',
                                                      'evidence', '__pycache__', '.pytest_cache'))
        for source in (ROOT / 'validation/local_release_20260911').glob('test_*.py'):
            shutil.copy2(source, tree / source.name)
        with zipfile.ZipFile(archive_path) as archive:
            members = {item.filename for item in archive.infolist() if not item.is_dir()}
            if members != EXPECTED_OVERRIDES:
                raise SystemExit('Unexpected integrated v1 override fixture members')
            for relative in sorted(members):
                target = (tree / relative).resolve()
                if not target.is_relative_to(tree):
                    raise SystemExit('Unsafe path in integrated v1 override fixture')
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(relative))
        env = os.environ.copy()
        env.pop('PQM_RELEASE_SOURCE_ROOT', None)
        env['PYTHONPATH'] = str(tree)
        return subprocess.run(
            [sys.executable, '-m', 'unittest',
             'test_sandbox_messages_integrity',
             'test_sandbox_nazk_messages_integrated_integrity',
             'test_nazk_authority_request_integrity',
             'test_messages_historical_line_endings'],
            cwd=tree, env=env, check=False).returncode


if __name__ == '__main__':
    raise SystemExit(main())
