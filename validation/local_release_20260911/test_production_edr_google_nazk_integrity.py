"""Additive integrity and mutation contract for the Production EDR/NAZK patch."""
import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path.cwd()
MANIFEST = Path('validation/fixtures/production_edr_google_nazk_ea3079_v1.json')
MANIFEST_SHA256 = 'ffbd92ff26994d2e1e278ea64b16126aeb1159164178377632467bd609ded3e3'
TEXT_SUFFIXES = {'.py', '.js', '.cjs', '.css', '.html', '.json', '.md', '.txt', '.yaml', '.yml'}


def normalized(content, relative):
    return content.replace(b'\r\n', b'\n') if Path(relative).suffix.lower() in TEXT_SUFFIXES else content


def digest(content, relative):
    return hashlib.sha256(normalized(content, relative)).hexdigest()


def load_manifest():
    raw = MANIFEST.read_bytes()
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
        raise AssertionError('Production EDR/NAZK additive manifest hash mismatch')
    payload = json.loads(raw)
    if payload.get('contract_id') != 'pqm_production_edr_google_nazk_ea3079_v1':
        raise AssertionError('Unexpected Production EDR/NAZK integrity contract')
    if payload.get('baseline_sha') != 'ea3079a85de5acff1157f067fa62bd9ecd346d04':
        raise AssertionError('Unexpected Production baseline in additive contract')
    return payload


class ProductionEdrGoogleNazkIntegrityTests(unittest.TestCase):
    def test_additive_manifest_pins_exact_product_and_regression_scope(self):
        manifest = load_manifest()
        self.assertEqual(set(manifest['product_sha256']), {
            'google_verification_contract.py', 'edr_sync_v2.py', 'server.py',
            'edr_sync_review.py', 'app.js'})
        self.assertEqual(set(manifest['protected_sha256']), {
            'nazk_workflow.py', 'scheduler_runtime.py', 'operational_tasks.py',
            'supplier_activity.py', 'templates/nazk_supplier_request.docx',
            'templates/nazk_authority_request.docx'})
        self.assertEqual(set(manifest['regression_sha256']), {
            'validation/local_release_20260911/test_edr_sync_v2.py',
            'validation/local_release_20260911/test_permanent_edr_sync_safety.py',
            'validation/local_release_20260911/test_production_nazk_messages_integrity.py',
            'validation/local_release_20260911/test_single_supplier_edr_workflow.py',
            'validation/local_release_20260911/test_prod_edr_review_promotion.py',
            'validation/local_release_20260911/test_sandbox_edr_review.py',
            'validation/local_release_20260911/test_supplier_edr_dates.py',
            'validation/local_release_20260911/test_supplier_edr_filter.py',
            'validation/local_release_20260911/test_edr_preview_skip_contract.py',
            'validation/local_release_20260911/test_google_verification_contract.py',
            'validation/local_release_20260911/test_production_edr_google_nazk_reconcile.py',
            'validation/fixtures/production_nazk_messages_integrated_f9eb8ed_tree_v1.zip'})

    def test_all_pinned_files_match_and_mutations_are_rejected(self):
        manifest = load_manifest()
        pinned = {**manifest['product_sha256'], **manifest['protected_sha256'],
                  **manifest['regression_sha256']}
        for relative, expected in pinned.items():
            with self.subTest(path=relative):
                content = (ROOT / relative).read_bytes()
                self.assertEqual(digest(content, relative), expected)
                if content:
                    changed = bytearray(content)
                    changed[len(changed) // 2] ^= 1
                    self.assertNotEqual(digest(bytes(changed), relative), expected)
                    self.assertNotEqual(digest(content + b'X', relative), expected)
                    self.assertNotEqual(digest(content[:-1], relative), expected)


if __name__ == '__main__':
    unittest.main()
