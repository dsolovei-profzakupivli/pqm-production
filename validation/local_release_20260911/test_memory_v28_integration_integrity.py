"""Current V28 + Stage 1 tree, independent of immutable historical contracts."""
import ast
import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2] if Path(__file__).parent.name == 'local_release_20260911' else Path.cwd()
MANIFEST_SHA256 = '7ce360cc65c2407f1f4b30b86986fbcf40e9c7946b988597675575bec32a10b8'
def digest(data, name):
    if Path(name).suffix in {'.py','.js','.json','.cjs','.css','.html','.yml','.md'}:
        data = data.replace(b'\r\n', b'\n')
    return hashlib.sha256(data).hexdigest()

class MemoryV28Integrity(unittest.TestCase):
    def manifest(self):
        raw = (ROOT/'validation/memory_v28_integration_v1.json').read_bytes()
        self.assertEqual(digest(raw,'manifest.json'), MANIFEST_SHA256)
        return json.loads(raw)

    def test_current_files_and_negative_byte_mutations(self):
        for name, expected in self.manifest()['files'].items():
            with self.subTest(file=name):
                raw=(ROOT/name).read_bytes()
                self.assertEqual(digest(raw,name), expected)
                self.assertNotEqual(digest(raw+b'X',name), expected)
                self.assertNotEqual(digest(raw[:-1],name), expected)
                changed=bytearray(raw); changed[len(changed)//2]^=1
                self.assertNotEqual(digest(changed,name), expected)

    def test_v28_untouched_functions_and_historical_manifests(self):
        manifest=self.manifest()
        for name, expected in manifest['historical_manifests'].items():
            self.assertEqual(digest((ROOT/name).read_bytes(),name),expected,name)
        for name, expected in manifest['unchanged_v28_runtime_files'].items():
            self.assertEqual(digest((ROOT/name).read_bytes(),name),expected,name)
        for name, functions in manifest['unchanged_functions'].items():
            source=(ROOT/name).read_text(encoding='utf-8-sig')
            actual={node.name:hashlib.sha256(ast.dump(node,include_attributes=False).encode()).hexdigest()
                    for node in ast.parse(source).body if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef))}
            for key,expected in functions.items():
                self.assertEqual(actual[key],expected,(name,key))

    def test_additive_runner_keeps_v28_groups_and_package(self):
        manifest=self.manifest()
        runner=(ROOT/'validation/run_local_release.py').read_text()
        for token in manifest['runner_required_tokens']:
            self.assertIn(token,runner)
        from validation.release_test_package import load_package_manifest, package_dependency_map
        package=load_package_manifest(ROOT)
        paths={name for name,_ in package_dependency_map(ROOT,ROOT,manifest=package)}
        for name in ('validation/memory_v28_history.py','validation/memory_v28_integration_v1.json',
                     'validation/fixtures/memory_v28_verified_dea2161.zip'):
            self.assertIn(name,paths)
        self.assertEqual(package['integrated_history_versions'],list(range(1,28)))
        self.assertEqual(package['integrity_test_versions'],list(range(1,29)))

if __name__=='__main__': unittest.main()
