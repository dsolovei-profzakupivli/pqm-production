"""Keep the Package 1 exact contract on its immutable Production inputs."""
import hashlib
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import zipfile

ARCHIVE='validation/fixtures/production_memory_package1_49afd73.zip'
PIN='ee3c1a4ecbc9416868f8ec18ee6619de3eee8d18e8e02b4a532547d9130f1ce8'
_TEMPS=[]

def route_suite(suite,source):
    modules=set()
    def visit(node):
        if isinstance(node,unittest.TestSuite):
            for child in node:visit(child)
        else:modules.add(node.__class__.__module__)
    visit(suite)
    selected=[name for name in modules if name.rsplit('.',1)[-1]=='test_production_memory_integrity']
    if not selected:return
    source=Path(source).resolve()
    raw=(source/ARCHIVE).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=PIN:raise AssertionError('Package 1 history changed')
    temp=tempfile.TemporaryDirectory(prefix='pqm-production-package1-');_TEMPS.append(temp)
    root=Path(temp.name)
    for item in source.iterdir():
        if item.name.startswith('.') or item.name in {'data','evidence','logs','backups','__pycache__'}:continue
        if item.is_dir():shutil.copytree(item,root/item.name,ignore=shutil.ignore_patterns('__pycache__'))
        else:shutil.copy2(item,root/item.name)
    with zipfile.ZipFile(source/ARCHIVE) as archive:
        if set(archive.namelist())!={'server.py','validation/run_local_release.py','validation/production_integrity_routes.py'}:
            raise AssertionError('Unexpected Package 1 overrides')
        for name in archive.namelist():(root/name).write_bytes(archive.read(name))
    for name in selected:
        sys.modules[name].ROOT=root
        print('PRODUCTION PACKAGE 1 HISTORY:',name,'=> 49afd73',flush=True)
