"""Exact DST child tree and immutable Declension/historical integrity lineage."""
import ast
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import unittest
import zipfile
import test_production_ui_release_integrity as guard

ROOT = guard.preview_parent_root()
MANIFEST_SHA = '39b1da68114916865b5307a1aa4e8db56f50ba7cea0fea88562a6583d1e5437b'
V1_SHA = '9902b0cf1e281cba3c1852a5be83df2d8d925f303a26c234c53744bcfeb93c5a'
HOTFIX_CONTRACT_SHA = 'e48197b55f08d5d96b53befd6316b6b598ed5b4396cdb61dd7674e791a28fc0a'


def sha(data):
    return hashlib.sha256(data.replace(b'\r\n', b'\n')).hexdigest()


class ProductionDstHotfixIntegrityTests(unittest.TestCase):
    def test_complete_manifest_and_immutable_history(self):
        c = guard.DST_VARIANT
        self.assertEqual(sha((ROOT/'validation/production_dst_hotfix_integrity_v2.json').read_bytes()), MANIFEST_SHA)
        self.assertEqual(c['baseline'], '4a3aca491cb836e73f1bb36dac364a336d46341a')
        self.assertEqual(sha((ROOT/'validation/production_ui_baseline_contract.json').read_bytes()), HOTFIX_CONTRACT_SHA)
        self.assertEqual(sha((ROOT/'validation/production_dst_hotfix_integrity_v1.json').read_bytes()), V1_SHA)
        self.assertEqual(c['historical_contract_sha256'], HOTFIX_CONTRACT_SHA)
        self.assertEqual(c['dst_v1_manifest_sha256'], V1_SHA)
        self.assertTrue(guard.variant_matches(ROOT, c['files'], variant=c))
        self.assertEqual(guard.matching_variant(ROOT), c)
        self.assertNotIn(guard.DST_V1_VARIANT, guard.VARIANTS)
        with zipfile.ZipFile(ROOT/'validation/fixtures/production_dst_lineage_4a3aca4.zip') as archive:
            metadata = json.loads(archive.read('metadata.json'))
            for prefix, hashes in metadata.items():
                for name, expected in hashes.items():
                    self.assertEqual(sha(archive.read(prefix+'/'+name)), expected)
            hotfix = {name: archive.read('hotfix/'+name) for name in guard.DECLENSION_HOTFIX_VARIANT['files']}
            previous = {name: archive.read('dst_v1/'+name) for name in guard.DST_V1_VARIANT['files']}
            self.assertTrue(guard.variant_matches(ROOT, hotfix, overrides=hotfix, variant=guard.DECLENSION_HOTFIX_VARIANT))
            self.assertTrue(guard.variant_matches(ROOT, previous, overrides=previous, variant=guard.DST_V1_VARIANT))
            for name in ('app.js', 'validation/declension_loader_result.cjs', 'validation/docker_release_gate.py',
                         'validation/local_release_20260911/test_violation_scenario_context_cache.py',
                         'validation/production_ui_baseline_contract.json'):
                self.assertEqual(sha((ROOT/name).read_bytes()), metadata['hotfix'][name])
            # No original test method/assertion may disappear from the child guard.
            original = ast.parse(archive.read('hotfix/test_production_ui_release_integrity.py').decode('utf-8-sig'))
            current = ast.parse((ROOT/'test_production_ui_release_integrity.py').read_text(encoding='utf-8-sig'))
            def methods(tree):
                return {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name.startswith('test_')}
            old_methods, new_methods = methods(original), methods(current)
            self.assertEqual(set(old_methods), set(new_methods))
            for name, method in old_methods.items():
                self.assertGreaterEqual(sum(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                                            and n.func.attr.startswith('assert') for n in ast.walk(new_methods[name])),
                                        sum(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                                            and n.func.attr.startswith('assert') for n in ast.walk(method)), name)
        with zipfile.ZipFile(ROOT/'validation/fixtures/production_dst_parent_292b072.zip') as archive:
            historical = {name: archive.read(name) if name in archive.namelist() else (ROOT/name).read_bytes()
                          for name in guard.APPEALS_VARIANT['files']}
        self.assertTrue(guard.variant_matches(ROOT, historical, overrides=historical, variant=guard.APPEALS_VARIANT))

    def test_single_byte_mutations_partial_and_forged_manifests_fail(self):
        c = guard.DST_VARIANT
        for name in c['files']:
            data = (ROOT/name).read_bytes()
            with self.subTest(name=name):
                self.assertFalse(guard.variant_matches(ROOT, c['files'], variant=c,
                    overrides={name: bytes([data[0]^1])+data[1:]}))
        for names in (set(c['files'])-{'server.py'}, set(c['files'])|{'unexpected.py'}):
            self.assertFalse(guard.variant_matches(ROOT, names, variant=c))
        for field, value in [('baseline', '292b0726b4adc13644c7f98721e569c8809ea785'), ('name', 'arbitrary')]:
            forged = copy.deepcopy(c)
            forged[field] = value
            self.assertFalse(guard.variant_matches(ROOT, forged['files'], variant=forged))
        forged = copy.deepcopy(c)
        forged['files']['server.py'] = '0'*64
        self.assertFalse(guard.variant_matches(ROOT, forged['files'], variant=forged))
        # Mutation test coverage of the original hotfix remains independently effective.
        with zipfile.ZipFile(ROOT/'validation/fixtures/production_dst_lineage_4a3aca4.zip') as archive:
            historical = {name: archive.read('hotfix/'+name) for name in guard.DECLENSION_HOTFIX_VARIANT['files']}
        for name, data in historical.items():
            with self.subTest(hotfix=name):
                self.assertFalse(guard.variant_matches(ROOT, historical, variant=guard.DECLENSION_HOTFIX_VARIANT,
                    overrides={**historical, name: bytes([data[0]^1])+data[1:]}))

    def test_verified_declension_loader_regression(self):
        result = subprocess.run(['node', 'validation/declension_loader_result.cjs'], cwd=ROOT,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('DECLENSION_LOADER_RESULT=PASS', result.stdout)


if __name__ == '__main__':
    unittest.main()
