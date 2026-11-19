"""Run the unchanged Messages header v3 contract on its exact 40da145 tree."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BASELINE = 'validation/fixtures/messages_header_polish_v3_baseline_40da.zip'
BASELINE_SHA256 = '3a34bfb1933a55ab0df408872f61137fc53426bcbdbeaa9f95caa6fe5f6f7429'
EXPECTED_FILES = {
    'chat_annotations.css',
    'validation/chat_messages_browser.cjs',
    'validation/run_local_release.py',
    'validation/run_messages_search_header_v2_integrity.py',
    'validation/fixtures/messages_search_header_v2_overrides.zip',
    'test_sandbox_messages_header_polish_integrity_v3.py',
    'test_sandbox_messages_header_polish_integrity_v3.json',
    'test_sandbox_messages_search_header_integrity_v2.json',
}


def main():
    archive_path = ROOT / BASELINE
    archive_bytes = archive_path.read_bytes()
    if hashlib.sha256(archive_bytes).hexdigest() != BASELINE_SHA256:
        raise SystemExit('Messages v3 historical baseline fixture SHA-256 mismatch')
    with tempfile.TemporaryDirectory(prefix='pqm-messages-polish-v3-') as temporary:
        tree = Path(temporary).resolve()
        with zipfile.ZipFile(archive_path) as archive:
            members = {item.filename for item in archive.infolist() if not item.is_dir()}
            if members != EXPECTED_FILES:
                raise SystemExit('Unexpected Messages v3 historical baseline fixture members')
            for relative in sorted(members):
                target = (tree / relative).resolve()
                if not target.is_relative_to(tree):
                    raise SystemExit('Unsafe path in Messages v3 historical baseline fixture')
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(relative))
        env = os.environ.copy()
        env.pop('PQM_RELEASE_SOURCE_ROOT', None)
        env['PYTHONPATH'] = str(tree)
        return subprocess.run(
            [sys.executable, '-m', 'unittest',
             'test_sandbox_messages_header_polish_integrity_v3'],
            cwd=tree, env=env, check=False).returncode


if __name__ == '__main__':
    raise SystemExit(main())
