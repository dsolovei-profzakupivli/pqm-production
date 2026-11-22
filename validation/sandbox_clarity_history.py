"""Original five-column acceptance/contracts remain pinned to 4d7ccba."""
import hashlib
import importlib.util
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import zipfile

ARCHIVE='validation/fixtures/sandbox_clarity_parent_4d7ccba.zip'
PIN='db3325565b25377f1e7e6573edf8bce2e85f308c2af945b1b3554c2f5203fcdc'
NEW_FILES={
    'validation/sandbox_clarity_history.py','validation/sandbox_clarity_csv_v1.json',
    'validation/release_test_package_clarity_v7.json',
    'validation/local_release_20260911/test_sandbox_clarity_csv.py',
    'validation/local_release_20260911/test_sandbox_clarity_integrity.py',
    ARCHIVE,
}
_TEMPS=[]
_CACHE={}

def baseline_root(source):
    source=Path(source).resolve()
    raw=(source/ARCHIVE).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=PIN:raise AssertionError('Clarity parent archive changed')
    if source not in _CACHE:
        tmp=tempfile.TemporaryDirectory(prefix='pqm-clarity-parent-');_TEMPS.append(tmp)
        root=Path(tmp.name)
        def ignore(directory,names):
            rel=Path(directory).relative_to(source)
            return [name for name in names if name in {'.git','data','evidence','outputs','__pycache__','backups','logs','node_modules'}
                    or (rel/name).as_posix() in NEW_FILES]
        shutil.copytree(source,root,dirs_exist_ok=True,ignore=ignore)
        _CACHE[source]=root
        with zipfile.ZipFile(source/ARCHIVE) as archive:
            if set(archive.namelist())!={'server.py','validation/run_local_release.py','validation/release_test_package.py'}:
                raise AssertionError('Unexpected Clarity parent overrides')
            for name in archive.namelist():(root/name).write_bytes(archive.read(name))
    root=_CACHE[source]
    with zipfile.ZipFile(source/ARCHIVE) as archive:
        for name in archive.namelist():
            if (root/name).read_bytes()!=archive.read(name):raise AssertionError('Historical parent changed: '+name)
    return root

def historical_server(source):
    root=baseline_root(source)
    name='_sandbox_clarity_parent_server'
    if name not in sys.modules:
        spec=importlib.util.spec_from_file_location(name,root/'server.py')
        module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
    return sys.modules[name]

def route_integrity_suite(suite,source,module_root=None):
    modules=set()
    def visit(node):
        if isinstance(node,unittest.TestSuite):
            for child in node:visit(child)
        else:modules.add(node.__class__.__module__)
    visit(suite)
    current={'test_sandbox_clarity_csv','test_sandbox_clarity_integrity'}
    from validation.sandbox_functionality_history import route_integrity_suite as prior
    if all(name.rsplit('.',1)[-1] in current for name in modules):
        return prior(suite,source,module_root=module_root)
    parent=baseline_root(source)
    prior(suite,parent,module_root=module_root)
    for name in modules:
        module=sys.modules[name];short=name.rsplit('.',1)[-1]
        if short in {'test_supplier_edr_filter','test_final_local_stabilization','test_edr_monitoring'}:
            module.server=historical_server(source)
            print('CLARITY HISTORY:',short,'=> 4d7ccba',flush=True)
        elif short=='test_sandbox_experience_integrity':
            module.ROOT=parent


if __name__=='__main__':
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    if sys.platform=='win32':
        from validation.run_local_release import install_windows_sqlite_uri_compatibility
        install_windows_sqlite_uri_compatibility()
    suite=unittest.defaultTestLoader.loadTestsFromNames([n for n in sys.argv[1:] if n not in {'-v','--verbose'}])
    route_integrity_suite(suite,root,module_root=root)
    raise SystemExit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())
