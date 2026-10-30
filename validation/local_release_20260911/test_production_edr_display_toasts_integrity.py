"""Additive integrity contract for the EDR timestamp and Apply notification fix."""
import hashlib
import json
import unittest
from pathlib import Path

MANIFEST = Path('validation/fixtures/production_edr_display_toasts_1b3ff_v1.json')
MANIFEST_SHA256 = '0a6df86f4e8e386e9718564e8cb21a143c85d1738bdd84c9d45d08b886bda7a9'
TEXT_SUFFIXES = {'.py', '.js', '.cjs', '.css', '.html', '.json', '.md', '.txt', '.yaml', '.yml'}


def digest(content, relative):
    if Path(relative).suffix.lower() in TEXT_SUFFIXES:
        content = content.replace(b'\r\n', b'\n')
    return hashlib.sha256(content).hexdigest()


def load_manifest():
    raw = MANIFEST.read_bytes()
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
        raise AssertionError('EDR display and Apply toast manifest hash mismatch')
    manifest = json.loads(raw)
    if manifest.get('contract_id') != 'pqm_production_edr_display_and_apply_toasts_1b3ff_v1':
        raise AssertionError('Unexpected EDR display and Apply toast contract')
    if manifest.get('parent_sha') != '1b3ff305d65d8c8548e7f645700ca20975456daa':
        raise AssertionError('Unexpected parent candidate')
    return manifest


class ProductionEdrDisplayToastsIntegrityTests(unittest.TestCase):
    def test_additive_contract_scopes_runtime_change_and_regressions(self):
        manifest = load_manifest()
        self.assertEqual(set(manifest['product_sha256']), {'server.py', 'app.js'})
        self.assertEqual(set(manifest['protected_sha256']), {
            'edr_sync_v2.py', 'google_verification_contract.py', 'nazk_workflow.py',
            'scheduler_runtime.py', 'operational_tasks.py',
            'validation/fixtures/production_edr_google_nazk_ea3079_v1.json'})
        self.assertEqual(set(manifest['regression_sha256']), {
            'validation/local_release_20260911/test_prod_edr_display_toasts.py',
            'validation/local_release_20260911/test_production_edr_google_nazk_integrity.py',
            'validation/production_edr_display_toasts_browser.cjs',
            'validation/fixtures/production_edr_google_nazk_ea3079_tree_v1.zip'})

    def test_pinned_bytes_and_negative_mutations(self):
        manifest = load_manifest()
        pinned = {**manifest['product_sha256'], **manifest['protected_sha256'],
                  **manifest['regression_sha256']}
        for relative, expected in pinned.items():
            with self.subTest(path=relative):
                content = Path(relative).read_bytes()
                self.assertEqual(digest(content, relative), expected)
                self.assertNotEqual(digest(content + b'X', relative), expected)
                self.assertNotEqual(digest(content[:-1], relative), expected)
                if content:
                    changed = bytearray(content)
                    changed[len(changed) // 2] ^= 1
                    self.assertNotEqual(digest(bytes(changed), relative), expected)


if __name__ == '__main__':
    unittest.main()
