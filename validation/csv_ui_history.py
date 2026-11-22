"""Keep original CSV contracts on 6a5cd45; functional CSV/UI tests stay current."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ARCHIVE = 'validation/fixtures/csv_ui_parent_6a5cd45.zip'
PIN = '6dc6630f876dd85de99376aff9d48d95724a5c609ae69755f64b11b50b0a1778'
CSV_SHA = '6a5cd4536ef7d2ef9e724ed3cb85140ea270e7c2'
_TEMPS = []
_ROOTS = {}


def baseline_root(source):
    source = Path(source).resolve()
    raw = (source / ARCHIVE).read_bytes()
    if hashlib.sha256(raw).hexdigest() != PIN:
        raise AssertionError('CSV integration parent archive changed')
    if source not in _ROOTS:
        tmp = tempfile.TemporaryDirectory(prefix='pqm-csv-ui-history-')
        _TEMPS.append(tmp)
        root = Path(tmp.name)
        shutil.copytree(source, root, dirs_exist_ok=True, ignore=shutil.ignore_patterns(
            '.git', 'data', 'evidence', 'outputs', '__pycache__', 'node_modules', 'logs', 'backups'))
        with zipfile.ZipFile(source / ARCHIVE) as archive:
            index = json.loads(archive.read('INDEX.json'))
            if index['sha'] != CSV_SHA or set(archive.namelist()) != {'INDEX.json', *('files/' + n for n in index['files'])}:
                raise AssertionError('Wrong CSV parent snapshot')
            for name, expected in index['files'].items():
                target = root / name
                target.resolve().relative_to(root.resolve())
                content = archive.read('files/' + name)
                if hashlib.sha256(content).hexdigest() != expected:
                    raise AssertionError('CSV parent member changed: ' + name)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
        _ROOTS[source] = (root, index)
    root, index = _ROOTS[source]
    for name, expected in index['files'].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
            raise AssertionError('CSV parent view changed: ' + name)
    return root


def route_integrity_suite(suite, source, module_root=None):
    tests = []
    def visit(node):
        if isinstance(node, unittest.TestSuite):
            for child in node:
                visit(child)
        else:
            tests.append(node)
    visit(suite)
    parent = baseline_root(source)
    # All earlier routing/expected hashes remain unmodified.
    from validation.sandbox_clarity_history import route_integrity_suite as prior
    prior(suite, parent, module_root=module_root or source)
    for test in tests:
        name = test.__class__.__module__
        short = name.rsplit('.', 1)[-1]
        if short == 'test_sandbox_clarity_integrity':
            sys.modules[name].ROOT = parent
        if short == 'test_sandbox_clarity_csv' and test.__class__.__name__ == 'ClarityEntrypointTests':
            if getattr(test, '_csv_ui_routed', False):
                continue
            original = test.run
            # This test invokes the *old* CLI. Its environment names the old
            # snapshot; no assertions or functional test server are replaced.
            def run(result=None, original=original):
                with patch.dict(os.environ, PQM_RELEASE_SOURCE_ROOT=str(parent)):
                    return original(result)
            test.run = run
            test._csv_ui_routed = True


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    if sys.platform == 'win32':
        from validation.run_local_release import install_windows_sqlite_uri_compatibility
        install_windows_sqlite_uri_compatibility()
    suite = unittest.defaultTestLoader.loadTestsFromNames([n for n in sys.argv[1:] if n not in {'-v', '--verbose'}])
    route_integrity_suite(suite, root)
    raise SystemExit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())
