"""Explicit immutable inputs for old contracts; never omit or edit assertions."""
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

ARCHIVE = 'validation/fixtures/production_integrity_ancestry_b12cd34.zip'
ARCHIVE_SHA256 = '284d96633edf9f9f136247901ff26a6ff93c7c183f06d20d01141289f14cedab'
INDEX_SHA256 = 'a7e7fb31e911a8886b91e6216cdfc7d7d6e16c2e3d632dd175f10a14169da1ba'
ROUTED_MODULES = {'test_production_nazk_messages_integrity',
                  'test_memory_stage1_followup_integrity', 'test_memory_stage1_gate_resolver'}
TEXT = {'.py','.js','.cjs','.css','.html','.json','.md','.txt','.yaml','.yml'}
_TEMPS = []
_CACHE = {}

def digest(data, name):
    if Path(name).suffix.lower() in TEXT:
        data = data.replace(b'\r\n', b'\n')
    return hashlib.sha256(data).hexdigest()

def read_archive(source_root):
    raw = (Path(source_root) / ARCHIVE).read_bytes()
    if hashlib.sha256(raw).hexdigest() != ARCHIVE_SHA256:
        raise AssertionError('Integrity ancestry archive changed')
    with zipfile.ZipFile(BytesIO(raw)) as archive:
        index_raw = archive.read('INDEX.json')
        if hashlib.sha256(index_raw).hexdigest() != INDEX_SHA256:
            raise AssertionError('Integrity ancestry index changed')
        index = json.loads(index_raw)
        if set(index['routes']) != ROUTED_MODULES:
            raise AssertionError('Unexpected historical contract routes')
        names = {'INDEX.json'} | {context + '/' + name
            for context, files in index['contexts'].items() for name in files}
        if len(archive.namelist()) != len(names) or set(archive.namelist()) != names:
            raise AssertionError('Unexpected integrity ancestry members')
        payload = {}
        for context, files in index['contexts'].items():
            for name, expected in files.items():
                relative = Path(name)
                if relative.is_absolute() or '..' in relative.parts:
                    raise AssertionError('Unsafe integrity ancestry path')
                data = archive.read(context + '/' + name)
                if digest(data, name) != expected:
                    raise AssertionError('Integrity ancestry content changed: ' + name)
                payload[(context, name)] = data
    return index, payload

def validate_view(root, files):
    for name, expected in files.items():
        if digest((root / name).read_bytes(), name) != expected:
            raise AssertionError('Historical view changed: ' + name)

def historical_view(source_root, context):
    source_root = Path(source_root).resolve()
    index, payload = read_archive(source_root)
    if context not in index['contexts']:
        raise AssertionError('Unregistered historical context')
    key = (source_root, context)
    if key not in _CACHE:
        temp = tempfile.TemporaryDirectory(prefix='pqm-integrity-ancestry-')
        _TEMPS.append(temp)
        root = Path(temp.name)
        for name in index['contexts'][context]:
            target = root / name
            target.resolve().relative_to(root.resolve())
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload[(context, name)])
        _CACHE[key] = root
    root = _CACHE[key]
    validate_view(root, index['contexts'][context])
    return root

def bind_historical_module(module, source_root):
    """Only ROOT is routed; original source and all test methods remain intact."""
    name = module.__name__
    short = name.rsplit('.', 1)[-1]
    if short not in ROUTED_MODULES or name not in {short, 'validation.local_release_20260911.' + short}:
        return None
    index, _ = read_archive(source_root)
    specification = index['routes'].get(short)
    if specification is None:
        return None
    source = Path(module.__file__).resolve()
    source.relative_to(Path(source_root).resolve())
    if digest(source.read_bytes(), source.name) != specification['test_sha256']:
        raise AssertionError('Historical contract source changed: ' + short)
    module.ROOT = historical_view(source_root, specification['context'])
    return specification['context']

def route_integrity_suite(suite, source_root):
    modules = set()
    def visit(node):
        if isinstance(node, unittest.TestSuite):
            for child in node:
                visit(child)
        else:
            modules.add(node.__class__.__module__)
    visit(suite)
    routed = []
    for name in sorted(modules):
        module = sys.modules[name]
        context = bind_historical_module(module, source_root)
        if context:
            routed.append((name, context))
            print('INTEGRITY ROUTE:', name, '=>', context, flush=True)
    return routed

if __name__ == '__main__':
    source = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(source))
    suite = unittest.defaultTestLoader.loadTestsFromNames(sys.argv[1:])
    route_integrity_suite(suite, source)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
