"""Actual eight-column contract, all previous manifests and selection rules intact."""
import ast
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from validation import sandbox_clarity_history as history

ROOT=Path(__file__).resolve().parents[2] if Path(__file__).parent.name=='local_release_20260911' else Path.cwd()
PIN='e9445dfa9e53eef3591d5995f00e805b3b342e9980e81316cd96845e9a13de4e'
def sha(raw,name):
    if Path(name).suffix in {'.py','.js','.json','.md','.yml','.cjs'}:raw=raw.replace(b'\r\n',b'\n')
    return hashlib.sha256(raw).hexdigest()

class ClarityIntegrity(unittest.TestCase):
    def manifest(self):
        raw=(ROOT/'validation/sandbox_clarity_csv_v1.json').read_bytes()
        self.assertEqual(sha(raw,'manifest.json'),PIN)
        return json.loads(raw)

    def test_actual_files_and_exact_byte_mutations(self):
        for name,expected in self.manifest()['files'].items():
            with self.subTest(file=name):
                raw=(ROOT/name).read_bytes();self.assertEqual(sha(raw,name),expected)
                for changed in [raw+b'X',raw[:-1],bytes([raw[0]^1])+raw[1:]]:
                    self.assertNotEqual(sha(changed,name),expected)

    def test_all_historical_manifests_and_unrelated_components_unchanged(self):
        for name,expected in self.manifest()['unchanged'].items():
            self.assertEqual(sha((ROOT/name).read_bytes(),name),expected,name)

    def test_selection_api_and_all_other_functions_unchanged(self):
        source=(ROOT/'server.py').read_text(encoding='utf-8-sig')
        tree=ast.parse(source)
        nodes={n.name:ast.dump(n,include_attributes=False) for n in tree.body if isinstance(n,ast.FunctionDef)}
        for name,expected in self.manifest()['unchanged_server_functions'].items():
            self.assertEqual(hashlib.sha256(nodes[name].encode()).hexdigest(),expected,name)
        handler=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Handler')
        for name,expected in self.manifest()['unchanged_http_methods'].items():
            node=next(n for n in handler.body if isinstance(n,ast.FunctionDef) and n.name==name)
            self.assertEqual(hashlib.sha256(ast.dump(node,include_attributes=False).encode()).hexdigest(),expected,name)

    def test_changed_parent_archive_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/history.ARCHIVE;path.parent.mkdir(parents=True)
            raw=bytearray((ROOT/history.ARCHIVE).read_bytes());raw[-1]^=1;path.write_bytes(raw)
            with self.assertRaisesRegex(AssertionError,'archive changed'):history.baseline_root(folder)
