"""Pinned historical contracts; current integration is protected separately."""
import hashlib
import os
import json
import shutil
from pathlib import Path
import tempfile
import zipfile

PINS = {'nazk': ['memory_nazk_production_contract.zip', 'be2b464d300c317c46dc8c4243a64d1edd2a5e657cebb94db3dacbf9ef037358'], 'stage1': ['memory_stage1_verified_3405f8b.zip', 'cb0e17edaca44b346938935600c05cc0d107a16ddc49d22119ed7a7eb47c9c02'], 'v28': ['memory_v28_verified_dea2161.zip', '93a9514744af15c84548a6a129d3224d713c879b94e18a5f26ba3b6ce3c416f7'], 'edr': ['memory_production_edr_history.zip', '716a89aafad93c2802a9302fb45ab6bc9c551d74e8fe470b20d15e17b86e8bfc']}
_ROOTS = {}
_TEMPS = []
def snapshot_root(kind, source=None):
    if kind in _ROOTS: return _ROOTS[kind]
    source = Path(source or os.environ.get('PQM_RELEASE_SOURCE_ROOT') or Path(__file__).resolve().parents[1])
    filename, expected = PINS[kind]
    path = source / 'validation/fixtures' / filename
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise AssertionError('Historical archive changed: ' + kind)
    temp = tempfile.TemporaryDirectory(prefix='pqm-memory-history-')
    _TEMPS.append(temp)
    root = Path(temp.name)
    with zipfile.ZipFile(path) as archive:
        if len(archive.namelist()) != len(set(archive.namelist())):
            raise AssertionError('Duplicate snapshot paths')
        for name in archive.namelist():
            target = root / name
            target.resolve().relative_to(root.resolve())
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(name))
    if kind == 'v28':
        manifest = json.loads((root / 'validation/local_release_20261116/pqm_sync_ui_integrated_v28.json').read_text())
        dependencies = set(manifest['files']) | set(manifest['immutable_history_files']) | {
            'validation/release_test_package_v1.json', 'validation/integrated_snapshot_archive.py',
            'validation/integrated_git_snapshot.py'}
        for name in dependencies:
            target = root / name
            target.resolve().relative_to(root.resolve())
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source / name, target)
    _ROOTS[kind] = root
    return root
