"""Preserve the accepted CSV/UI contracts on an attested, Gitless baseline view."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

BASE_SHA = '0678d46e0c1931031af24d2fd2fe50c952d92766'
BASE_TREE = 'f226f52dcb07b44c0fdd0187044585319ce11e05'
ARCHIVE = 'validation/fixtures/document_release_parent_0678d46.zip'
PIN = '6579cd45b89cb59d9ed7ea820e578bff21b0817ac698da98f3639a553ff952ac'
_CACHE = {}
_TEMPS = []

def blob_oid(raw):
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()

def baseline_root(source):
    source = Path(source).resolve()
    raw = (source / ARCHIVE).read_bytes()
    if hashlib.sha256(raw).hexdigest() != PIN:
        raise AssertionError('Accepted document baseline archive changed')
    if source not in _CACHE:
        with zipfile.ZipFile(source / ARCHIVE) as archive:
            index = json.loads(archive.read('INDEX.json'))
            if index['sha'] != BASE_SHA or index['tree'] != BASE_TREE or archive.comment.decode() != BASE_SHA:
                raise AssertionError('Wrong accepted baseline SHA/tree')
            if set(archive.namelist()) != {'INDEX.json', *('files/' + n for n in index['overrides'])}:
                raise AssertionError('Unexpected accepted baseline members')
            tmp = tempfile.TemporaryDirectory(prefix='pqm-documents-accepted-')
            _TEMPS.append(tmp)
            root = Path(tmp.name)
            for name, expected in index['files'].items():
                target = root / name
                target.resolve().relative_to(root.resolve())
                content = archive.read('files/' + name) if name in index['overrides'] else (source / name).read_bytes()
                if blob_oid(content) != expected['oid']:
                    content = content.replace(b'\r\n', b'\n')
                if blob_oid(content) != expected['oid']:
                    raise AssertionError('Accepted baseline Git blob mismatch: ' + name)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
        _CACHE[source] = root
    return _CACHE[source]

def route_integrity_suite(suite, source, module_root=None):
    from validation.csv_ui_gate_history import route_integrity_suite as prior
    accepted = baseline_root(source)
    prior(suite, accepted, module_root=module_root)
    def visit(node):
        if isinstance(node, unittest.TestSuite):
            for child in node:
                visit(child)
        elif node.__class__.__module__.rsplit('.', 1)[-1] == 'test_csv_ui_gate_integrity':
            sys.modules[node.__class__.__module__].ROOT = accepted
    visit(suite)

def run_accepted(source, mode):
    root = baseline_root(source)
    names = (['sandbox_functionality_current_ui.cjs', 'application_documents_ui.test.cjs', 'document_check_ui.test.cjs']
             if mode == 'node' else ['sandbox_functionality_current_browser.cjs', 'application_documents_browser.cjs', 'document_check_browser.cjs'])
    env = os.environ.copy()
    if mode == 'browser':
        env['PQM_SANDBOX'] = '1'
        sys.path.insert(0, str(root))
        with patch.dict(os.environ, {'PQM_SANDBOX': '1'}):
            import sandbox_runtime
            html = sandbox_runtime.decorate_html((root / 'index.html').read_bytes())
        for key in ['PQM_UI001_EVIDENCE', 'PQM_UI002_EVIDENCE', 'PQM_CURRENT_FUNCTIONALITY_BROWSER_EVIDENCE']:
            base = env.get(key)
            if not base:
                raise RuntimeError('Missing browser evidence directory: ' + key)
            folder = Path(base) / 'accepted-0678d46'
            folder.mkdir(parents=True, exist_ok=True)
            (folder / 'sandbox-index.html').write_bytes(html)
            env[key] = str(folder)
    print('MANDATORY ACCEPTED HISTORY:', BASE_SHA, mode, flush=True)
    for name in names:
        result = subprocess.run(['node', 'validation/' + name], cwd=root, env=env, check=False, timeout=240)
        if result.returncode:
            return result.returncode
    return 0

if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    if sys.argv[1:] in [['--accepted-node'], ['--accepted-browser']]:
        raise SystemExit(run_accepted(root, sys.argv[1].removeprefix('--accepted-')))
    if sys.argv[1:] in [['--node-history'], ['--browser-history'], ['--supplier-history']]:
        from validation.csv_ui_gate_history import run_legacy
        raise SystemExit(run_legacy(baseline_root(root), sys.argv[1].removeprefix('--').removesuffix('-history')))
    if sys.platform == 'win32':
        from validation.run_local_release import install_windows_sqlite_uri_compatibility
        install_windows_sqlite_uri_compatibility()
    suite = unittest.defaultTestLoader.loadTestsFromNames([n for n in sys.argv[1:] if n not in {'-v', '--verbose'}])
    route_integrity_suite(suite, root)
    raise SystemExit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())
