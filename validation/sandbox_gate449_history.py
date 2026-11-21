"""Exact candidate 525cfd4 inputs for its unchanged v1 integrity assertions."""
import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile
import zipfile
from validation.sandbox_integrity_routes import digest
ARCHIVE='validation/fixtures/sandbox_functionality_525cfd4_v1.zip'
ARCHIVE_SHA256='77d2284d28794355ad3633b0995e93e6fd7b5491d2de679da6e78146a173c3dd'
INDEX_SHA256='fec9d4bb3ba7da0b5c01834e9b87f5e9a0c9491301a683d58c802e797b39c598'
_CACHE={}
_TEMPS=[]

def previous_root(source):
    source=Path(source).resolve()
    if source in _CACHE:
        root,index=_CACHE[source]
        for name,expected in index['files'].items():
            if digest((root/name).read_bytes(),name)!=expected:raise AssertionError('Previous candidate view changed: '+name)
        return root,index
    raw=(source/ARCHIVE).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=ARCHIVE_SHA256:raise AssertionError('Previous candidate archive changed')
    with zipfile.ZipFile(BytesIO(raw)) as bundle:
        encoded=bundle.read('INDEX.json')
        if hashlib.sha256(encoded).hexdigest()!=INDEX_SHA256:raise AssertionError('Previous candidate index changed')
        index=json.loads(encoded)
        if set(bundle.namelist())!={'INDEX.json',*('files/'+n for n in index['overrides'])}:raise AssertionError('Unexpected previous candidate member')
        temp=tempfile.TemporaryDirectory(prefix='pqm-functionality-525cfd4-');_TEMPS.append(temp);root=Path(temp.name)
        for name,expected in index['files'].items():
            target=root/name;target.resolve().relative_to(root.resolve());target.parent.mkdir(parents=True,exist_ok=True)
            raw=bundle.read('files/'+name) if name in index['overrides'] else (source/name).read_bytes()
            if digest(raw,name)!=expected:raise AssertionError('Previous candidate input drifted: '+name)
            target.write_bytes(raw)
    _CACHE[source]=(root,index);return root,index

def bind_previous_guard(module,source):
    root,index=previous_root(source)
    name='validation/local_release_20260911/test_sandbox_functionality_integrity.py'
    if digest(Path(module.__file__).read_bytes(),name)!=index['files'][name]:raise AssertionError('Original v1 test changed')
    module.ROOT=root
    print('FUNCTIONALITY HISTORY: original v1 guard => exact 525cfd4',flush=True)
