"""Additive actual-Production contract; historic manifests are immutable."""
import ast,hashlib,json
from pathlib import Path
import unittest

ROOT=Path.cwd()
PIN='bf7b9e5ee5b4d5244e665c83c2c5b7f86b3e6b041c0834cf0225f386b28c02e9'
def sha(raw):return hashlib.sha256(raw.replace(b'\r\n',b'\n')).hexdigest()

class ProductionMemoryIntegrity(unittest.TestCase):
    def manifest(self):
        raw=(ROOT/'validation/production_memory_selective_v1.json').read_bytes()
        self.assertEqual(sha(raw),PIN)
        return json.loads(raw)

    def test_actual_candidate_and_single_byte_mutations(self):
        for name,expected in self.manifest()['files'].items():
            with self.subTest(file=name):
                raw=(ROOT/name).read_bytes()
                self.assertEqual(sha(raw),expected)
                self.assertNotEqual(sha(raw+b'X'),expected)
                self.assertNotEqual(sha(raw[:-1]),expected)
                changed=bytearray(raw);changed[len(changed)//2]^=1
                self.assertNotEqual(sha(changed),expected)

    def test_all_historical_manifests_unchanged(self):
        for name,expected in self.manifest()['historical_manifests'].items():
            self.assertEqual(sha((ROOT/name).read_bytes()),expected,name)

    def test_production_processes_and_non_ui_files_unchanged(self):
        manifest=self.manifest()
        source=(ROOT/'server.py').read_text(encoding='utf-8-sig')
        functions={n.name:hashlib.sha256(ast.dump(n,include_attributes=False).encode()).hexdigest()
                   for n in ast.parse(source).body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
        for name,expected in manifest['unchanged_server_functions'].items():
            self.assertEqual(functions.get(name),expected,name)
        for name,expected in manifest['unchanged_baseline_files'].items():
            self.assertEqual(sha((ROOT/name).read_bytes()),expected,name)
