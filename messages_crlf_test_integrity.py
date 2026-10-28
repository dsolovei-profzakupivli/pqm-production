"""Test-only additive contract. Historical manifests and product hashes are immutable."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
import zipfile

MANIFEST_SHA = "15d9706e4282c8ef799c468e93b855e27b657310fe1cb17a874fd27b13a05996"
NAME = 'test_sandbox_messages_crlf_integrity_v2.json'
VARIANT = 'sandbox-messages-test-crlf-lf-v2'
BASELINE = '67d1ba660eadcbfe68393f8657b66c990622773b'
TEST_CHANGES = {
    'test_sandbox_nazk_appeals_stabilization_v3_integrity.py',
    'test_sandbox_messages_integrity.py',
    'test_sandbox_dst_hotfix_integrity.py',
    'test_sandbox_nazk_preview_integrity.py',
    'test_sandbox_nazk_recovery_integrity.py',
    'test_sandbox_appeals_scenario_api_integrity.py',
    'test_sandbox_nazk_appeals_stabilization_integrity.py',
    'validation/local_release_20260911/sandbox_protocol_integrity_variant.py',
    'validation/run_local_release.py',
}
ADDITIONS = {
    'messages_crlf_test_integrity.py',
    'test_messages_historical_line_endings.py',
    'validation/fixtures/messages_v1_test_parent.zip',
    'test_sandbox_messages_integrity_v1.json',
}
_parent_temp = None


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(data):
    data=data.replace(b'\r\n',b'\n')
    return re.sub(rb'MANIFEST_SHA = "[0-9a-f]{64}"',
                  b'MANIFEST_SHA = "<pinned-manifest-sha256>"',data)


def load_contract(root, previous):
    raw=(root/NAME).read_bytes().replace(b'\r\n',b'\n')
    if digest(raw)!=MANIFEST_SHA:
        raise AssertionError('Changed Messages CRLF test manifest')
    data=json.loads(raw)
    if (data['variant_id']!=VARIANT or data['baseline_sha']!=BASELINE or
            data['parent_variant']!=previous['variant_id'] or
            digest((root/'test_sandbox_messages_integrity_v1.json').read_bytes().replace(b'\r\n',b'\n'))
            !=data['parent_manifest_sha256']):
        raise AssertionError('Unexpected CRLF test baseline or parent')
    # Protected product entries are inherited byte-for-byte; only test paths can differ.
    if data['protected_files']!=previous['protected_files']:
        raise AssertionError('CRLF test variant cannot alter protected product hashes')
    old_names=set().union(*(set(previous[key]) for key in ('product_files','guarded_files','protected_files')))
    new_names=set().union(*(set(data[key]) for key in ('product_files','guarded_files','protected_files')))
    if new_names!=old_names|ADDITIONS:
        raise AssertionError('Unexpected CRLF test file set')
    for section in ('product_files','guarded_files','protected_files'):
        for name,expected in previous[section].items():
            if name not in TEST_CHANGES and data[section].get(name)!=expected:
                raise AssertionError('CRLF contract changed an unrelated file: '+name)
    return data


def parent_tree(root):
    """Rebuild the exact v1 protected tree using original Git blobs for changed tests."""
    global _parent_temp
    if _parent_temp is not None:
        return Path(_parent_temp.name)
    from validation.local_release_20260911 import sandbox_protocol_integrity_variant as guard
    previous=next(c for c in guard.load_contracts() if c['variant_id']=='sandbox-messages-all-chats-c246edef-v1')
    current=guard.load_contracts()[-1]
    fixture=root/current['test_parent_fixture']
    if digest(fixture.read_bytes())!=current['test_parent_fixture_sha256']:
        raise AssertionError('Changed v1 test parent archive')
    _parent_temp=tempfile.TemporaryDirectory(prefix='pqm-messages-v1-tests-',dir=root/'validation')
    tree=Path(_parent_temp.name)
    names=set().union(*(set(previous[key]) for key in ('product_files','guarded_files','protected_files')))
    names.add('test_sandbox_messages_integrity_v1.json')
    # The historical loader reads its complete immutable JSON contract chain.
    names.update(path.name for path in root.glob('*.json')
                 if path.name not in {NAME, 'test_sandbox_nazk_authority_v1.json',
                                      'test_sandbox_web_smoke_nazk_authority_v1.json',
                                      'test_sandbox_nazk_messages_integrated_v1.json'})
    for name in names:
        target=tree/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(root/name,target)
    with zipfile.ZipFile(fixture) as archive:
        if len(archive.namelist())!=len(TEST_CHANGES) or set(archive.namelist())!=TEST_CHANGES:
            raise AssertionError('Unexpected v1 parent override set')
        for name in TEST_CHANGES:
            content=archive.read(name)
            if digest(content)!=current['test_parent_file_sha256'][name]:
                raise AssertionError('Changed v1 parent test bytes')
            (tree/name).write_bytes(content)
    if not guard.manifest_tree_matches(previous,tree):
        raise AssertionError('Restored v1 tree does not match its immutable manifest')
    return tree
