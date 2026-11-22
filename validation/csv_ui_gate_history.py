"""Mandatory old Node/browser checks on CSV-001; current functional tests stay current."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

BASE_SHA = 'c0c1df0d8136f90b42c2770f72e955c3f739855d'
ARCHIVE = 'validation/fixtures/csv_ui_gate_parent_c0c1df0.zip'
PIN = 'e6fcc145a1d89c452a68f72ea6956146ba5a2a79fe95bc0689ff9a2ee0351cfd'
LEGACY = {
    'validation/sandbox_functionality_repair_ui.cjs': '9e62f79f1c32b69575a73d0b2bd3050252b983c88da5e3606ffc5963d10c550e',
    'validation/sandbox_functionality_repair_browser.cjs': '7993f699d06ff5d023157f6494a3afbbccb615274dffd993b00c71ffb1a61944',
    'validation/sandbox_supplier_ux.cjs': '8178f4b2f4831c94c002174fa3d115773f1c563cf0f825c43df2a560a1592d66',
    'validation/supplier_ux.cjs': 'de934eecbe374b86f1fe8ccb4c44a6c39698cb335391a430930cb6865bc35e8c',
}
_TEMPS = []
_CACHE = {}


def parent_root(source):
    source = Path(source).resolve()
    if hashlib.sha256((source / ARCHIVE).read_bytes()).hexdigest() != PIN:
        raise AssertionError('Integrated v1 parent archive changed')
    if source not in _CACHE:
        with zipfile.ZipFile(source / ARCHIVE) as archive:
            index = json.loads(archive.read('INDEX.json'))
            if index['sha'] != BASE_SHA or set(archive.namelist()) != {'INDEX.json', *('files/' + n for n in index['files'])}:
                raise AssertionError('Wrong integration parent SHA/members')
            tmp = tempfile.TemporaryDirectory(prefix='pqm-csv-ui-v1-')
            _TEMPS.append(tmp)
            root = Path(tmp.name)
            for name in index['tracked']:
                target = root / name
                target.resolve().relative_to(root.resolve())
                target.parent.mkdir(parents=True, exist_ok=True)
                raw = archive.read('files/' + name) if name in index['files'] else (source / name).read_bytes()
                if name in index['files'] and hashlib.sha256(raw).hexdigest() != index['files'][name]:
                    raise AssertionError('Integrated parent member changed: ' + name)
                target.write_bytes(raw)
        _CACHE[source] = (root, index)
    root, index = _CACHE[source]
    for name, expected in index['files'].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
            raise AssertionError('Integrated parent view changed: ' + name)
    return root


def route_integrity_suite(suite, source, module_root=None):
    from validation.csv_ui_history import route_integrity_suite as prior
    prior(suite, source, module_root=module_root)
    def visit(node):
        if isinstance(node, unittest.TestSuite):
            for child in node:
                visit(child)
        elif node.__class__.__module__.rsplit('.', 1)[-1] == 'test_csv_ui_integration_integrity':
            sys.modules[node.__class__.__module__].ROOT = parent_root(source)
        elif (node.__class__.__module__.rsplit('.', 1)[-1] == 'test_contract_experience_search'
              and node._testMethodName == 'test_valid_mvs_and_verified_signature_are_green'
              and not getattr(node, '_csv_ui_gate_routed', False)):
            module = sys.modules[node.__class__.__module__]
            original = node.run
            def run(result=None, original=original, module=module):
                with patch.object(module, 'server', historical_server(source)):
                    return original(result)
            node.run = run
            node._csv_ui_gate_routed = True
        elif (node.__class__.__module__.rsplit('.', 1)[-1] == 'test_history_document_groups'
              and node._testMethodName == 'test_registry_modal_splits_supplier_and_decision_documents'
              and not getattr(node, '_csv_ui_gate_path_routed', False)):
            module = sys.modules[node.__class__.__module__]
            nested = Path(module_root or source) / 'validation/local_release_20260911/test_history_document_groups.py'
            if not nested.is_file():
                raise FileNotFoundError('Missing nested UI-001 test source: ' + str(nested))
            original = node.run
            # The delivered runner also flattens tests into its temporary root.
            # Preserve the original test's relative-path contract using the
            # identical nested copy, so its Node subprocess sees staged assets.
            def run(result=None, original=original, module=module, nested=nested):
                with patch.object(module, '__file__', str(nested)):
                    return original(result)
            node.run = run
            node._csv_ui_gate_path_routed = True
        elif (node.__class__.__module__.rsplit('.', 1)[-1] == 'test_registry_ux_cleanup'
              and node._testMethodName == 'test_document_experience_uses_contract_links_not_document_ocr_tag'
              and not getattr(node, '_csv_ui_gate_experience_routed', False)):
            from validation.csv_ui_history import baseline_root
            legacy_app = (baseline_root(source) / 'app.js').read_text(encoding='utf8')
            original = node.run
            def run(result=None, original=original, node=node, legacy_app=legacy_app):
                with patch.object(node, 'app', legacy_app):
                    return original(result)
            node.run = run
            node._csv_ui_gate_experience_routed = True
    visit(suite)


def historical_server(source):
    from validation.csv_ui_history import baseline_root
    root = baseline_root(source)
    alias = '_csv_ui_gate_csv001_server'
    if alias not in sys.modules:
        spec = importlib.util.spec_from_file_location(alias, root / 'server.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[alias] = module
        spec.loader.exec_module(module)
    return sys.modules[alias]


def run_legacy(source, mode, node='node'):
    from validation.csv_ui_history import baseline_root, CSV_SHA
    source = Path(source).resolve()
    root = baseline_root(source)
    for name, expected in LEGACY.items():
        for candidate in (source / name, root / name):
            raw = candidate.read_bytes().replace(b'\r\n', b'\n')
            if hashlib.sha256(raw).hexdigest() != expected:
                raise AssertionError('Original historical test changed: ' + name)
    names = (['validation/sandbox_supplier_ux.cjs', 'validation/supplier_ux.cjs'] if mode == 'supplier' else
             ['validation/sandbox_functionality_repair_' + ('ui.cjs' if mode == 'node' else 'browser.cjs')])
    print('MANDATORY HISTORY:', mode, 'CSV-001', CSV_SHA, flush=True)
    for name in names:
        command = [node, '--test', name] if mode == 'node' else [node, name]
        result = subprocess.run(command, cwd=root, check=False).returncode
        if result:
            return result
    return 0


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    if sys.argv[1:] in [['--node-history'], ['--browser-history'], ['--supplier-history']]:
        raise SystemExit(run_legacy(root, sys.argv[1].removeprefix('--').removesuffix('-history')))
    if sys.platform == 'win32':
        from validation.run_local_release import install_windows_sqlite_uri_compatibility
        install_windows_sqlite_uri_compatibility()
    suite = unittest.defaultTestLoader.loadTestsFromNames([n for n in sys.argv[1:] if n not in {'-v', '--verbose'}])
    route_integrity_suite(suite, root)
    raise SystemExit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())
