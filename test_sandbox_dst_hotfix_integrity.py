import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from validation.local_release_20260911 import sandbox_protocol_integrity_variant as guard

ROOT=guard.ROOT

class SandboxDstHotfixIntegrityTests(unittest.TestCase):
    def test_exact_new_tree_and_unchanged_historical_contracts(self):
        contracts=guard.load_contracts()
        self.assertEqual(len(contracts),32)
        current=next(c for c in contracts if c['variant_id']==guard.DST_VARIANT_ID)
        self.assertEqual(current['variant_id'],guard.DST_VARIANT_ID)
        self.assertEqual(current['baseline_sha'],'94c5e37693ef2855aaf9bc848ca2af1b3965cb25')
        self.assertFalse(guard.manifest_tree_matches(current))
        previous=next(c for c in contracts if c['variant_id']==guard.STABILIZATION_V5_VARIANT_ID)
        self.assertFalse(guard.manifest_tree_matches(previous))
        self.assertTrue(guard.manifest_tree_matches(previous,guard.dst_parent_root()))
        self.assertTrue(guard.manifest_tree_matches(contracts[-1]))
        self.assertTrue(guard.manifest_tree_matches(
            next(c for c in contracts if c['variant_id']==guard.DST_RECOVERY_VARIANT_ID),
            guard.dst_recovery_v2_root()))
        with zipfile.ZipFile(ROOT/'validation/fixtures/dst_parent_94c5e37.zip') as z:
            hashes=json.loads(z.read('historical_manifest_sha256.json'))
        for name,expected in hashes.items():
            self.assertEqual(guard.sha256((ROOT/name).read_bytes().replace(b'\r\n',b'\n')),expected,name)
        self.assertEqual(guard.sha256((ROOT/'validation/fixtures/dst_parent_94c5e37.zip').read_bytes()),current['parent_fixture_sha256'])
        recovery = next(c for c in contracts if c['variant_id'] == guard.DST_RECOVERY_VARIANT_ID)
        self.assertEqual(recovery['variant_id'], guard.DST_RECOVERY_VARIANT_ID)

    def test_one_byte_change_in_every_pinned_file_is_rejected(self):
        current=guard.load_contracts()[-1]
        names=set().union(*(set(current[k]) for k in ('product_files','guarded_files','protected_files')))
        with tempfile.TemporaryDirectory(dir=ROOT / "validation") as tmp:
            tree=Path(tmp)
            for name in names:
                p=tree/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((ROOT/name).read_bytes())
            self.assertTrue(guard.manifest_tree_matches(current,tree))
            for name in names:
                p=tree/name;data=p.read_bytes();p.write_bytes(bytes([data[0]^1])+data[1:])
                with self.subTest(name=name):self.assertFalse(guard.manifest_tree_matches(current,tree))
                p.write_bytes(data)
            self.assertTrue(guard.manifest_tree_matches(current,tree))

    def test_partial_and_arbitrary_sha_never_become_allowed_variants(self):
        current=guard.load_contracts()[-1]
        forged=copy.deepcopy(current);forged['product_files']['server.py']['sha256']='0'*64
        self.assertFalse(guard.manifest_tree_matches(forged))
        partial=copy.deepcopy(current);partial['guarded_files'].pop('scheduler_runtime.py')
        self.assertFalse(guard.manifest_tree_matches(partial))

if __name__=='__main__':unittest.main()
