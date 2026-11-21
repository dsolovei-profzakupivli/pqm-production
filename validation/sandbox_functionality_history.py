"""Exact parent inputs for old Stage 1 assertions; current acceptance stays separate."""
import hashlib
import importlib.util
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import zipfile

ARCHIVE = 'validation/fixtures/sandbox_functionality_parent_43b14a9.zip'
ARCHIVE_SHA256 = '3a549262f8f60d60921ea376ea75afc842f17d8eb763a8ea1e3ce838b7fd0b1f'
INDEX_SHA256 = '283652f1714e5bbf80b3aa7a39a5446ffaa99b5f7182db8f6435aec85460e2f3'
ROUTED = {'test_google_writer_update_append_v2_integrity',
          'test_google_writer_integrated_candidate_integrity_v28',
          'test_memory_v28_integration_integrity', 'test_sandbox_integrity_audit',
          'test_memory_stage1_followup', 'test_memory_stage1', 'test_sandbox_functionality_integrity'}
_TEMP = []
_ROOTS = {}

def digest(data, name):
    from validation.sandbox_integrity_routes import digest as normalized
    return normalized(data, name)

def parent_root(source):
    source = Path(source).resolve()
    if source in _ROOTS:
        root, index = _ROOTS[source]
        for name, expected in index['files'].items():
            if digest((root/name).read_bytes(),name) != expected:
                raise AssertionError('Historical parent view changed: '+name)
        return root,index
    raw=(source/ARCHIVE).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=ARCHIVE_SHA256:
        raise AssertionError('Historical functionality parent archive changed')
    with zipfile.ZipFile(BytesIO(raw)) as bundle:
        encoded=bundle.read('INDEX.json')
        if hashlib.sha256(encoded).hexdigest()!=INDEX_SHA256:
            raise AssertionError('Historical functionality parent index changed')
        index=json.loads(encoded)
        if set(bundle.namelist())!={'INDEX.json',*('files/'+name for name in index['overrides'])}:
            raise AssertionError('Unexpected parent archive members')
        temp=tempfile.TemporaryDirectory(prefix='pqm-functionality-parent-');_TEMP.append(temp)
        root=Path(temp.name)
        for name, expected in index['files'].items():
            path=root/name;path.resolve().relative_to(root.resolve());path.parent.mkdir(parents=True,exist_ok=True)
            data=bundle.read('files/'+name) if name in index['overrides'] else (source/name).read_bytes()
            if digest(data,name)!=expected:
                raise AssertionError('Parent input drifted: '+name)
            path.write_bytes(data)
    _ROOTS[source]=(root,index)
    return root,index


def route_integrity_suite(suite, source, module_root=None):
    from validation.sandbox_integrity_routes import bind_historical_module
    modules=set()
    def visit(node):
        if isinstance(node,unittest.TestSuite):
            for child in node:visit(child)
        else:modules.add(node.__class__.__module__)
    visit(suite)
    for name in sorted(modules):
        short=name.rsplit('.',1)[-1]
        if short not in ROUTED:continue
        module=sys.modules[name]
        if short=='test_sandbox_functionality_integrity':
            from validation.sandbox_gate449_history import bind_previous_guard
            bind_previous_guard(module,source)
            continue
        path=Path(module.__file__).resolve();path.relative_to(Path(module_root or source).resolve())
        root,index=parent_root(source)
        relative=('validation/local_release_20260911/' if path.parent.name=='local_release_20260911' or short in {'test_sandbox_integrity_audit','test_memory_stage1_followup','test_memory_stage1','test_memory_v28_integration_integrity'} else '')+path.name
        if digest(path.read_bytes(),relative)!=index['files'][relative]:
            raise AssertionError('Original historical test changed: '+relative)
        if short in {'test_memory_stage1_followup','test_memory_stage1'}:
            alias='_pqm_functionality_parent_server'
            if alias not in sys.modules:
                spec=importlib.util.spec_from_file_location(alias,root/'server.py')
                saved=importlib.util.module_from_spec(spec)
                runtime_spec=importlib.util.spec_from_file_location(alias+'_runtime',root/'runtime_memory.py')
                old_runtime=importlib.util.module_from_spec(runtime_spec);runtime_spec.loader.exec_module(old_runtime)
                import builtins
                native_import=builtins.__import__
                def historic_import(name,*args,**kwargs):
                    return old_runtime if name=='runtime_memory' else native_import(name,*args,**kwargs)
                saved.__dict__['__builtins__']={**vars(builtins),'__import__':historic_import}
                sys.modules[alias]=saved;spec.loader.exec_module(saved)
            module.server=sys.modules[alias]
            if short=='test_memory_stage1':module.runtime_memory=module.server.runtime_memory
        elif short=='test_sandbox_integrity_audit':
            module.ROOT=root
        else:
            bind_historical_module(module,root,module_root=module_root or source)
        print('FUNCTIONALITY HISTORY:',short,'=> 43b14a9',flush=True)

if __name__=='__main__':
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    if sys.platform=='win32':
        from validation.run_local_release import install_windows_sqlite_uri_compatibility
        install_windows_sqlite_uri_compatibility()
    suite=unittest.defaultTestLoader.loadTestsFromNames([n for n in sys.argv[1:] if n not in {'-v','--verbose'}])
    route_integrity_suite(suite,root)
    raise SystemExit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())
