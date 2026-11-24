"""Additive accepted-document baseline routing with V30 pinned overrides."""
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
ADDITIVE_ARCHIVE = 'validation/fixtures/document_release_parent_0678d46_addendum_v1.zip'
ADDITIVE_PIN = 'bb9524ba26b6778b9fd70a57487e6c5610fda41325dfab638961e89c81e4fbef'
V1_SOURCE_ARCHIVE = 'validation/fixtures/document_release_v1_source_6e0a9ef.zip'
V1_SOURCE_PIN = '309313cc321244321c9921515c8bea8ea54ec78f4b069419130afb5fecc0c2f9'
V1_SOURCE_COMMIT = '6e0a9ef928e5ed09876c2218560bd27c3385ca09'
V1_SOURCE_TREE = 'ad66a3c5830293fdc41dfe0c5b3400a8c7ffc6c9'
_CACHE = {}
_TEMPS = []
_ACCEPTED_ROOTS = set()

def blob_oid(raw):
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()

def _text_bytes(name, raw):
    if Path(name).suffix in {'.py', '.js', '.css', '.cjs', '.json', '.yml', '.html', '.md', '.mjs', '.yaml', '.txt'}:
        return raw.replace(b'\r\n', b'\n')
    return raw

def verify_v1_source(source):
    """Verify V1's exact file pins against its source commit plus additive overrides."""
    source = Path(source).resolve()
    contract_raw = _text_bytes('document_release_v1.json', (source / 'validation/document_release_v1.json').read_bytes())
    contract = json.loads(contract_raw)
    archive_raw = (source / V1_SOURCE_ARCHIVE).read_bytes()
    if hashlib.sha256(archive_raw).hexdigest() != V1_SOURCE_PIN:
        raise AssertionError('V1 source archive changed')
    with zipfile.ZipFile(source / V1_SOURCE_ARCHIVE) as archive:
        index = json.loads(archive.read('INDEX.json'))
        overrides = index.get('files')
        if (archive.comment.decode() != V1_SOURCE_COMMIT
                or index.get('commit') != V1_SOURCE_COMMIT
                or index.get('tree') != V1_SOURCE_TREE
                or index.get('contract_sha256') != hashlib.sha256(contract_raw).hexdigest()
                or not isinstance(overrides, dict)
                or not set(overrides).issubset(contract['files'])
                or set(archive.namelist()) != {'INDEX.json', *('files/' + n for n in overrides)}):
            raise AssertionError('Wrong V1 source snapshot metadata')
        for name, expected in contract['files'].items():
            raw = archive.read('files/' + name) if name in overrides else (source / name).read_bytes()
            actual = hashlib.sha256(_text_bytes(name, raw)).hexdigest()
            if actual != expected:
                raise AssertionError('V1 source pin mismatch: ' + name)
            if name in overrides and overrides[name] != expected:
                raise AssertionError('V1 source override pin mismatch: ' + name)
    return contract

def baseline_root(source):
    source = Path(source).resolve()
    if source in _ACCEPTED_ROOTS:
        return source
    raw = (source / ARCHIVE).read_bytes()
    if hashlib.sha256(raw).hexdigest() != PIN:
        raise AssertionError('Accepted document baseline archive changed')
    additive_raw = (source / ADDITIVE_ARCHIVE).read_bytes()
    if hashlib.sha256(additive_raw).hexdigest() != ADDITIVE_PIN:
        raise AssertionError('Accepted document baseline addendum changed')
    with zipfile.ZipFile(source / ARCHIVE) as archive:
        index = json.loads(archive.read('INDEX.json'))
        if index['sha'] != BASE_SHA or index['tree'] != BASE_TREE or archive.comment.decode() != BASE_SHA:
            raise AssertionError('Wrong accepted baseline SHA/tree')
        if set(archive.namelist()) != {'INDEX.json', *('files/' + n for n in index['overrides'])}:
            raise AssertionError('Unexpected accepted baseline members')
    with zipfile.ZipFile(source / ADDITIVE_ARCHIVE) as additive:
        additive_index = json.loads(additive.read('INDEX.json'))
        additive_overrides = additive_index.get('overrides')
        if (additive_index.get('sha') != BASE_SHA or additive_index.get('tree') != BASE_TREE
                or additive.comment.decode() != BASE_SHA
                or not isinstance(additive_overrides, list)
                or len(additive_overrides) != len(set(additive_overrides))
                or set(additive_index.get('files', {})) != set(additive_overrides)
                or set(additive.namelist()) != {'INDEX.json', *('files/' + n for n in additive_overrides)}
                or not set(additive_overrides).issubset(index['files'])
                or set(additive_overrides).intersection(index['overrides'])):
            raise AssertionError('Wrong accepted document baseline addendum')
        for name in additive_overrides:
            if additive_index['files'][name] != index['files'][name]:
                raise AssertionError('Accepted document baseline addendum pin mismatch: ' + name)
    if source not in _CACHE:
        with zipfile.ZipFile(source / ARCHIVE) as archive:
            tmp = tempfile.TemporaryDirectory(prefix='pqm-documents-accepted-')
            _TEMPS.append(tmp)
            root = Path(tmp.name)
            for name, expected in index['files'].items():
                target = root / name
                target.resolve().relative_to(root.resolve())
                if name in index['overrides']:
                    content = archive.read('files/' + name)
                elif name in additive_overrides:
                    with zipfile.ZipFile(source / ADDITIVE_ARCHIVE) as additive:
                        content = additive.read('files/' + name)
                else:
                    content = (source / name).read_bytes()
                if blob_oid(content) != expected['oid']:
                    content = content.replace(b'\r\n', b'\n')
                if blob_oid(content) != expected['oid']:
                    raise AssertionError('Accepted baseline Git blob mismatch: ' + name)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            for relative in (ARCHIVE, ADDITIVE_ARCHIVE):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((source / relative).read_bytes())
        _CACHE[source] = root
        _ACCEPTED_ROOTS.add(root.resolve())
    return _CACHE[source]

def route_integrity_suite(suite, source, module_root=None):
    from validation.csv_ui_gate_history import route_integrity_suite as prior
    candidate_source = Path(source).resolve()
    accepted = baseline_root(source)
    # Historical data and the origin of the loaded tests are separate roots.
    prior(suite, accepted, module_root=Path(module_root or source).resolve())
    modules = set()
    def collect(node):
        if isinstance(node, unittest.TestSuite):
            for child in node:
                collect(child)
        else:
            modules.add(node.__class__.__module__)
    collect(suite)
    # The compact functionality snapshot stores files that changed from its
    # parent. A few unchanged binary inputs remain pinned by the original
    # contract but are not snapshot overrides; hydrate only those missing files
    # from the candidate when their bytes still match the historical pin.
    from validation.sandbox_integrity_routes import digest
    for module_name in modules:
        if module_name.rsplit('.', 1)[-1] != 'test_sandbox_functionality_integrity':
            continue
        module = sys.modules[module_name]
        historical_root = Path(module.ROOT).resolve()
        manifest_path = historical_root / 'validation/sandbox_functionality_repair_v1.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        for relative, expected in manifest.get('unchanged_files', {}).items():
            target = (historical_root / relative).resolve()
            target.relative_to(historical_root)
            if target.is_file():
                continue
            source_file = (candidate_source / relative).resolve()
            source_file.relative_to(candidate_source)
            raw = source_file.read_bytes()
            if digest(raw, relative) != expected:
                raise AssertionError('Missing historical input does not match its pin: ' + relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
    def visit(node):
        if isinstance(node, unittest.TestSuite):
            for child in node:
                visit(child)
        elif node.__class__.__module__.rsplit('.', 1)[-1] == 'test_csv_ui_gate_integrity':
            sys.modules[node.__class__.__module__].ROOT = accepted
        elif node.__class__.__module__.rsplit('.', 1)[-1] == 'test_document_release_integrity_v1':
            module = sys.modules[node.__class__.__module__]
            original = node.run
            def run(result=None, original=original, module=module):
                with patch.object(module, 'history', sys.modules[__name__]):
                    return original(result)
            node.run = run
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
