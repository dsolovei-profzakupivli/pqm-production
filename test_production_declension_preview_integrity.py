"""Exact Preview/filename child contract; historical contracts remain immutable."""
import ast
import copy
import hashlib
import json
from pathlib import Path
import unittest
import test_production_ui_release_integrity as guard

ROOT = Path(__file__).resolve().parent
MANIFEST_SHA = 'a7c06d66a69fefc74231b265d1ec833a5ca3331b4fadbf553050611dd1a2e362'
HISTORICAL = {
    'validation/production_ui_baseline_contract.json': 'e48197b55f08d5d96b53befd6316b6b598ed5b4396cdb61dd7674e791a28fc0a',
    'validation/production_dst_hotfix_integrity_v1.json': '9902b0cf1e281cba3c1852a5be83df2d8d925f303a26c234c53744bcfeb93c5a',
    'validation/production_dst_hotfix_integrity_v2.json': '39b1da68114916865b5307a1aa4e8db56f50ba7cea0fea88562a6583d1e5437b',
}


def normalized(path):
    return path.read_bytes().replace(b'\r\n', b'\n')


class DeclensionPreviewIntegrityTests(unittest.TestCase):
    def test_exact_child_and_all_historical_contracts(self):
        c = guard.PREVIEW_VARIANT
        self.assertEqual(hashlib.sha256(normalized(ROOT/'validation/production_declension_preview_integrity_v1.json')).hexdigest(), MANIFEST_SHA)
        self.assertEqual(c['baseline'], 'f2565a4e52d482b50f4ddfc2ff8468c38f9a49a7')
        self.assertEqual(c['name'], 'production-declension-preview-f2565a4-v1')
        self.assertEqual(guard.matching_variant(ROOT), c)
        self.assertTrue(guard.variant_matches(ROOT, c['files'], variant=c))
        self.assertFalse(guard.variant_matches(ROOT, guard.DST_VARIANT['files'], variant=guard.DST_VARIANT))
        parent = guard.preview_parent_root()
        self.assertTrue(guard.variant_matches(parent, guard.DST_VARIANT['files'], variant=guard.DST_VARIANT))
        self.assertEqual(guard.matching_variant(parent), guard.DST_VARIANT)
        self.assertNotIn(guard.DST_V1_VARIANT, guard.VARIANTS)
        for name, expected in HISTORICAL.items():
            self.assertEqual(hashlib.sha256(normalized(ROOT/name)).hexdigest(), expected, name)
            self.assertEqual(normalized(ROOT/name), normalized(parent/name), name)
        # The original assertions/mutation methods are retained verbatim.
        for name in ('test_production_ui_release_integrity.py', 'test_production_dst_hotfix_integrity.py'):
            def classes(path):
                return {node.name: ast.dump(node, include_attributes=False) for node in ast.parse(path.read_text(encoding='utf-8-sig')).body if isinstance(node, ast.ClassDef)}
            self.assertEqual(classes(ROOT/name), classes(parent/name), name)

    def test_single_byte_partial_extra_and_arbitrary_hashes_rejected(self):
        c = guard.PREVIEW_VARIANT
        for name in c['files']:
            data = (ROOT/name).read_bytes()
            with self.subTest(file=name):
                self.assertFalse(guard.variant_matches(ROOT, c['files'], variant=c,
                    overrides={name: bytes([data[0]^1])+data[1:]}))
        for paths in (set(c['files'])-{'app.js'}, set(c['files'])|{'unexpected.py'}):
            self.assertFalse(guard.variant_matches(ROOT, paths, variant=c))
        for field, value in (('baseline', guard.DST_VARIANT['baseline']), ('name', 'arbitrary-variant')):
            forged = copy.deepcopy(c)
            forged[field] = value
            self.assertFalse(guard.variant_matches(ROOT, forged['files'], variant=forged))
        forged = copy.deepcopy(c)
        forged['files']['server.py'] = '0'*64
        self.assertFalse(guard.variant_matches(ROOT, forged['files'], variant=forged))
        forged = copy.deepcopy(c)
        del forged['files']['validation/declension_preview_http.py']
        self.assertFalse(guard.variant_matches(ROOT, forged['files'], variant=forged))

    def test_business_algorithms_docs_scheduler_and_rights_unchanged(self):
        parent = guard.preview_parent_root()
        for name in ('declension.py', 'declension_overrides.py', 'violation_protocol_docx.py',
                     'protocol_docx.py', 'scheduler_runtime.py', 'auth_access.py', 'nazk_workflow.py',
                     'operational_tasks.py', 'supplier_registry_integration.py', 'edr_sync_v2.py',
                     'sandbox_runtime.py', 'theme.css', 'modules.css', 'index.html'):
            self.assertEqual(normalized(ROOT/name), normalized(parent/name), name)
        previous = guard.nodes((parent/'server.py').read_text(encoding='utf-8-sig'))
        current = guard.nodes((ROOT/'server.py').read_text(encoding='utf-8-sig'))
        changed = {key for key in set(previous)|set(current) if previous.get(key) != current.get(key)}
        self.assertEqual(changed, {'Handler._do_GET', '_violation_protocol_filename', '_resolve_violation_protocol_metadata'})
        self.assertEqual(set(guard.PREVIEW_VARIANT['server_variant_excluded_functions']),
                         set(guard.DST_VARIANT['server_variant_excluded_functions'])|{'_violation_protocol_filename', '_resolve_violation_protocol_metadata'})


if __name__ == '__main__':
    unittest.main()
