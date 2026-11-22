"""Pinned Stage 1 inputs; current Production acceptance always runs separately."""
import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import sys
import tempfile
import zipfile

ARCHIVE = 'validation/fixtures/production_memory_16339b1_history.zip'
ARCHIVE_SHA256 = '17def109ec43cd332f11c3f87b4ea49e9cf98b94719737b71463ef6b71b083ab'
_TEMPS = []
_ROOTS = {}

def previous_root(source):
    source = Path(source).resolve()
    raw = (source / ARCHIVE).read_bytes()
    if hashlib.sha256(raw).hexdigest() != ARCHIVE_SHA256:
        raise AssertionError('Production memory history archive changed')
    if source not in _ROOTS:
        temp = tempfile.TemporaryDirectory(prefix='pqm-production-memory-history-')
        _TEMPS.append(temp)
        root = Path(temp.name)
        for item in source.iterdir():
            if item.name.startswith('.') or item.name in {'data','evidence','backups','logs','__pycache__'}:
                continue
            if item.is_dir():
                shutil.copytree(item, root/item.name, ignore=shutil.ignore_patterns('__pycache__'))
            else:
                shutil.copy2(item, root/item.name)
        _ROOTS[source] = root
    root = _ROOTS[source]
    with zipfile.ZipFile(source / ARCHIVE) as archive:
        for name in archive.namelist():
            path = root / name
            path.resolve().relative_to(root)
            path.parent.mkdir(parents=True, exist_ok=True)
            expected = archive.read(name)
            if source not in getattr(previous_root, '_initialized', set()):
                path.write_bytes(expected)
            elif path.read_bytes().replace(b'\r\n',b'\n') != expected.replace(b'\r\n',b'\n'):
                raise AssertionError('Production historical input changed: '+name)
    previous_root._initialized = getattr(previous_root, '_initialized', set()) | {source}
    return root

def route_suite(suite, source):
    import unittest
    modules = set()
    def visit(node):
        if isinstance(node, unittest.TestSuite):
            for child in node: visit(child)
        else: modules.add(node.__class__.__module__)
    visit(suite)
    selected = {'test_memory_stage1', 'test_memory_stage1_followup',
                'test_production_integrity_routes'}
    if not any(name.rsplit('.',1)[-1] in selected for name in modules):
        return
    root = previous_root(source)
    for name in sorted(modules):
        short = name.rsplit('.',1)[-1]
        if short not in selected: continue
        module = sys.modules[name]
        relative = 'validation/local_release_20260911/'+short+'.py'
        if Path(module.__file__).read_bytes().replace(b'\r\n',b'\n') != (root/relative).read_bytes().replace(b'\r\n',b'\n'):
            raise AssertionError('Historical assertion changed: '+short)
        if short == 'test_production_integrity_routes':
            module.ROOT = root
            # This old contract checks nested historical routing relative to ROOT.
            nested = __import__('importlib').import_module('validation.local_release_20260911.test_production_nazk_messages_integrity')
            nested.__file__ = str(root/'validation/local_release_20260911/test_production_nazk_messages_integrity.py')
        else:
            alias = '_production_memory_accepted_server'
            if alias not in sys.modules:
                import builtins
                runtime_spec = importlib.util.spec_from_file_location(alias+'_runtime', root/'runtime_memory.py')
                old_runtime = importlib.util.module_from_spec(runtime_spec)
                runtime_spec.loader.exec_module(old_runtime)
                spec = importlib.util.spec_from_file_location(alias, root/'server.py')
                saved = importlib.util.module_from_spec(spec)
                native_import = builtins.__import__
                def historical_import(name, *args, **kwargs):
                    return old_runtime if name == 'runtime_memory' else native_import(name,*args,**kwargs)
                saved.__dict__['__builtins__'] = {**vars(builtins),'__import__':historical_import}
                sys.modules[alias] = saved
                spec.loader.exec_module(saved)
            module.server = sys.modules[alias]
            if short == 'test_memory_stage1':
                module.runtime_memory = module.server.runtime_memory
        print('PRODUCTION MEMORY HISTORY:',short,'=> 16339b1',flush=True)
