"""Explicit immutable inputs for old contracts; never omit or edit assertions."""
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

ARCHIVE = 'validation/fixtures/sandbox_integrity_ancestry_de17865.zip'
ARCHIVE_SHA256 = '8286507afe09ed97b7b122f0f181faefe7c0412265a8297ef0515285bb7e3cf0'
INDEX_SHA256 = '6527d5598b6cb251b3a9ef9c72048ef516f1cd4cbcda6285f0af99f355d348c3'
ROUTED_MODULES = {'test_google_writer_update_append_v2_integrity',
                  'test_google_writer_integrated_candidate_integrity_v28',
                  'test_memory_v28_integration_integrity'}
TEXT = {'.py','.js','.cjs','.css','.html','.json','.md','.txt','.yaml','.yml',
        '.gs','.sql','.svg','.xml','.toml','.ini','.csv','.mjs','.sh','.example'}
_TEMPS = []
_CACHE = {}

def normalized(data, name):
    if Path(name).suffix.lower() in TEXT or Path(name).name in {'.gitignore','.gitattributes','.dockerignore','Dockerfile'}:
        data = data.replace(b'\r\n', b'\n')
    return data

def digest(data, name):
    return hashlib.sha256(normalized(data, name)).hexdigest()

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
            for context, files in index['overrides'].items() for name in files}
        if len(archive.namelist()) != len(names) or set(archive.namelist()) != names:
            raise AssertionError('Unexpected integrity ancestry members')
        payload = {}
        for context, files in index['overrides'].items():
            for name in files:
                relative = Path(name)
                if relative.is_absolute() or '..' in relative.parts:
                    raise AssertionError('Unsafe integrity ancestry path')
                data = archive.read(context + '/' + name)
                if (digest(data, name) != index['contexts'][context][name] or
                    hashlib.sha256(data).hexdigest() != index['raw_overrides'][context][name]):
                    raise AssertionError('Integrity ancestry content changed: ' + name)
                payload[(context, name)] = data
    return index, payload

def validate_view(root, files, raw_files):
    for name, expected in files.items():
        if digest((root / name).read_bytes(), name) != expected:
            raise AssertionError('Historical view changed: ' + name)
    for name, expected in raw_files.items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
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
            data = payload[(context, name)] if (context, name) in payload else (source_root / name).read_bytes()
            if digest(data, name) != index['contexts'][context][name]:
                raise AssertionError('Unchanged historical input drifted: ' + name)
            target.write_bytes(data if (context, name) in payload else normalized(data, name))
        _CACHE[key] = root
    root = _CACHE[key]
    validate_view(root, index['contexts'][context], index['raw_overrides'][context])
    return root

def bind_historical_module(module, source_root, module_root=None):
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
    source.relative_to(Path(module_root or source_root).resolve())
    if digest(source.read_bytes(), source.name) != specification['test_sha256']:
        raise AssertionError('Historical contract source changed: ' + short)
    previous_root = Path(module.ROOT).resolve()
    for field, relative in specification.get('path_globals', {}).items():
        if Path(getattr(module, field)).resolve() != previous_root / relative:
            raise AssertionError('Unexpected historical path binding: ' + field)
    module.ROOT = historical_view(source_root, specification['context'])
    for field, relative in specification.get('path_globals', {}).items():
        setattr(module, field, module.ROOT / relative)
    return specification['context']

def route_integrity_suite(suite, source_root, module_root=None):
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
        context = bind_historical_module(module, source_root, module_root)
        if context:
            routed.append((name, context))
            print('INTEGRITY ROUTE:', name, '=>', context, flush=True)
    return routed

if __name__ == '__main__':
    source = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(source))
    if sys.platform == 'win32':
        from validation.run_local_release import install_windows_sqlite_uri_compatibility
        install_windows_sqlite_uri_compatibility()
    suite = unittest.defaultTestLoader.loadTestsFromNames([name for name in sys.argv[1:] if name not in {'-v', '--verbose'}])
    route_integrity_suite(suite, source)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
