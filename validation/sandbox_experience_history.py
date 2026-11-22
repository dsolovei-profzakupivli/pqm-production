"""Exact f0cd900 inputs for prior contracts; current experience acceptance is separate."""
import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile
import zipfile
from validation.sandbox_integrity_routes import digest
ARCHIVE='validation/fixtures/sandbox_experience_f0cd900_v1.zip'
ARCHIVE_SHA256='f7390bef730d22ebfb3960c4403906b152fd87c68e71d4d0f6c8b19caf1a6190'
INDEX_SHA256='e706a7bfde1acb40ca6bf168945cc714362562511cce5f6ec05979e291139636'
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
        temp=tempfile.TemporaryDirectory(prefix='pqm-experience-f0cd900-');_TEMPS.append(temp);root=Path(temp.name)
        for name,expected in index['files'].items():
            target=root/name;target.resolve().relative_to(root.resolve());target.parent.mkdir(parents=True,exist_ok=True)
            raw=bundle.read('files/'+name) if name in index['overrides'] else (source/name).read_bytes()
            if digest(raw,name)!=expected:raise AssertionError('Previous candidate input drifted: '+name)
            target.write_bytes(raw)
    _CACHE[source]=(root,index);return root,index
