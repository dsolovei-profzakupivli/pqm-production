"""Additive follow-up integrity for Linux Gate 44947804174."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from validation.sandbox_integrity_routes import digest
ROOT=Path(os.environ.get('PQM_RELEASE_SOURCE_ROOT') or Path(__file__).resolve().parents[2]).resolve()
MANIFEST_SHA256='8595660b4631d9d8551c89481ee00bdfec0ca05cdfedf363dc0b9f2073952be4'

class Gate449IntegrityTests(unittest.TestCase):
    def manifest(self):
        raw=(ROOT/'validation/sandbox_functionality_repair_v2.json').read_bytes()
        self.assertEqual(digest(raw,'manifest.json'),MANIFEST_SHA256)
        return json.loads(raw)

    def test_current_exact_files_reject_every_single_byte_change(self):
        for name,expected in self.manifest()['current_files'].items():
            with self.subTest(file=name):
                raw=(ROOT/name).read_bytes();self.assertEqual(digest(raw,name),expected)
                for changed in (raw+b'X',raw[:-1],bytes([raw[0]^1])+raw[1:]):self.assertNotEqual(digest(changed,name),expected)

    def test_historical_contracts_and_unrelated_product_files_unchanged(self):
        manifest=self.manifest()
        for name,expected in manifest['unchanged_files'].items():self.assertEqual(digest((ROOT/name).read_bytes(),name),expected,name)
        for name in ['app.js','runtime_memory.py','supplier_registry_integration.py','scheduler_runtime.py','validation/sandbox_functionality_repair_v1.json','validation/local_release_20260911/test_scheduler_runtime.py','validation/local_release_20260911/test_supplier_evidence_shadow_hooks_v3.py','validation/local_release_20260911/test_sandbox_functionality_integrity.py']:
            self.assertIn(name,manifest['unchanged_files'])

    def test_previous_snapshot_is_exact_without_git_and_fails_on_corruption(self):
        from validation import sandbox_gate449_history as history
        previous,index=history.previous_root(ROOT)
        self.assertEqual(index['parent'],'525cfd4153cdf38c7ff3b3172b6b5cea62700870')
        self.assertFalse((previous/'.git').exists())
        for name,expected in index['files'].items():self.assertEqual(digest((previous/name).read_bytes(),name),expected,name)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/history.ARCHIVE;path.parent.mkdir(parents=True)
            raw=bytearray((ROOT/history.ARCHIVE).read_bytes());raw[-1]^=1;path.write_bytes(raw)
            with self.assertRaisesRegex(AssertionError,'archive changed'):history.previous_root(tmp)

if __name__=='__main__':unittest.main()
