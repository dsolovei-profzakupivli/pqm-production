"""Additive current-tree pins; original parent contracts are immutable."""
import hashlib
import json
import os
from pathlib import Path
import unittest
from validation.sandbox_integrity_routes import digest

ROOT=Path(os.environ.get('PQM_RELEASE_SOURCE_ROOT') or Path(__file__).resolve().parents[2]).resolve()
MANIFEST_SHA256='2e4019fa7e5d0fd175766b4344070cb7a10dd19030e3dbf0989badb24f39636e'

class SandboxFunctionalityIntegrity(unittest.TestCase):
    def test_exact_current_files_and_single_byte_mutations(self):
        raw=(ROOT/'validation/sandbox_functionality_repair_v1.json').read_bytes()
        self.assertEqual(digest(raw,'manifest.json'),MANIFEST_SHA256)
        manifest=json.loads(raw)
        for name,expected in manifest['current_files'].items():
            with self.subTest(file=name):
                data=(ROOT/name).read_bytes();self.assertEqual(digest(data,name),expected)
                for mutation in (data+b'X',data[:-1],bytes([data[0]^1])+data[1:]):
                    self.assertNotEqual(digest(mutation,name),expected)

    def test_original_contracts_and_optimized_core_are_unchanged(self):
        manifest=json.loads((ROOT/'validation/sandbox_functionality_repair_v1.json').read_text())
        for name,expected in manifest['unchanged_files'].items():
            self.assertEqual(digest((ROOT/name).read_bytes(),name),expected,name)
        self.assertIn('runtime_memory.py',manifest['current_files'])
        self.assertIn('supplier_registry_integration.py',manifest['unchanged_files'])

    def test_parent_fixture_and_original_assertions_fail_closed(self):
        import tempfile
        from validation import sandbox_functionality_history as history
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/history.ARCHIVE;path.parent.mkdir(parents=True)
            data=bytearray((ROOT/history.ARCHIVE).read_bytes());data[-1]^=1;path.write_bytes(data)
            with self.assertRaisesRegex(AssertionError,'archive changed'):history.parent_root(Path(folder))

if __name__=='__main__':unittest.main()
