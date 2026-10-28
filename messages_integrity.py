"""Exact additive Messages variant; immutable parent contracts stay unchanged."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import tempfile
import zipfile

MANIFEST_SHA = "1bb3bdbe99b3f041b6bc6dbdfaf4768a5b21f75c84d7f4a6a61351726a731143"
NAME = 'test_sandbox_messages_integrity_v1.json'
VARIANT = 'sandbox-messages-all-chats-c246edef-v1'
BASELINE = 'c246edefaa676d137d3f38d40f18d039f7b5bac2'
_parent_temp = None
_historical_module = None


def canonical(name, data):
    if not name.endswith(('.zip','.docx','.png','.webp','.jpg','.gif','.jpeg')):
        data=data.replace(b'\r\n',b'\n')
    if name=='messages_integrity.py':
        data=re.sub(rb'MANIFEST_SHA = "[0-9a-f]{64}"',b'MANIFEST_SHA = "<pinned-manifest-sha256>"',data)
    return data


def digest(data):
    return hashlib.sha256(data).hexdigest()


def contract(root, previous):
    raw=(root/NAME).read_bytes().replace(b'\r\n',b'\n')
    if digest(raw)!=MANIFEST_SHA:
        raise AssertionError('Messages manifest SHA mismatch')
    data=json.loads(raw)
    if data['baseline_sha']!=BASELINE or data['variant_id']!=VARIANT or data['parent_variant']!=previous['variant_id']:
        raise AssertionError('Messages baseline/parent mismatch')
    return data


def historical_guard(root):
    """Execute historical v5 regression assertions on exact c246edef bytes."""
    global _parent_temp, _historical_module
    if _historical_module is not None:
        return _historical_module
    if _parent_temp is None:
        raw=(root/NAME).read_bytes().replace(b'\r\n',b'\n')
        if digest(raw)!=MANIFEST_SHA:
            raise AssertionError('Messages manifest SHA mismatch')
        data=json.loads(raw)
        archive_path=root/data['parent_fixture']
        if digest(archive_path.read_bytes())!=data['parent_fixture_sha256']:
            raise AssertionError('Messages parent fixture SHA mismatch')
        _parent_temp=tempfile.TemporaryDirectory(prefix='pqm-messages-parent-',dir=root/'validation')
        tree=Path(_parent_temp.name)
        with zipfile.ZipFile(archive_path) as archive:
            expected=data['parent_files']
            members=[entry.filename for entry in archive.infolist() if not entry.is_dir()]
            if len(members)!=len(expected) or set(members)!=set(expected):
                raise AssertionError('Unexpected Messages parent fixture member')
            for name,sha in expected.items():
                target=tree/name
                if not target.resolve().is_relative_to(tree.resolve()):
                    raise AssertionError('Unsafe fixture path')
                content=archive.read(name)
                if digest(content)!=sha:
                    raise AssertionError('Changed parent fixture content')
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(content)
    path=Path(_parent_temp.name)/'validation/local_release_20260911/sandbox_protocol_integrity_variant.py'
    spec=importlib.util.spec_from_file_location('messages_historical_v5_guard',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _historical_module=module
    return module
