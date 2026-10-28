"""Additive integrity contract for the Production NAZK + Messages integration."""
import hashlib
import json
import unittest
from pathlib import Path

ROOT=Path.cwd()
MANIFEST_RELATIVE=Path('validation/fixtures/production_nazk_messages_integrated_f9eb8ed_v1.json')
MANIFEST_SHA256='a3f6344a2ec4e3ebe33237165da522049a0d030a1caff4a28bb88179e03198e6'
TEXT_SUFFIXES={'.py','.js','.cjs','.css','.html','.json','.md','.txt','.yaml','.yml'}
EXPECTED_REGRESSION_FILES={
    'production_integrity_overlay.py',
    'test_production_ui_release_integrity.py',
    'test_production_scenario_projection_integrity.py',
    'test_production_nazk_recovery_integrity.py',
    'test_production_nazk_recovery_followup_integrity.py',
    'validation/local_release_20260911/test_chat_annotations.py',
    'validation/local_release_20260911/test_chat_annotations_http.py',
    'validation/local_release_20260911/test_nazk_authority_request.py',
    'validation/local_release_20260911/test_task_documents.py',
    'validation/chat_messages_browser.cjs',
    'validation/sandbox_smoke.py',
    'validation/web_smoke.py',
    'validation/fixtures/production_nazk_recovery_overlay_cbe1ec4.zip',
}

def normalized(content,relative):
    if Path(relative).suffix.lower() in TEXT_SUFFIXES:
        return content.replace(b'\r\n',b'\n')
    return content

def sha256(content,relative):
    return hashlib.sha256(normalized(content,relative)).hexdigest()

def read_manifest():
    raw=(ROOT/MANIFEST_RELATIVE).read_bytes()
    if sha256(raw,MANIFEST_RELATIVE)!=MANIFEST_SHA256:
        raise AssertionError('Production integration manifest hash mismatch')
    manifest=json.loads(raw)
    if manifest.get('contract_id')!='pqm_production_nazk_messages_integrated_f9eb8ed_v1':
        raise AssertionError('Unexpected Production integration integrity identity')
    if manifest.get('baseline_sha')!='f9eb8ed0feb29e57bbd95932a462b372f4cf634f':
        raise AssertionError('Unexpected Production baseline')
    if manifest.get('source_candidate_sha')!='40da14517de6988f98dd5d49b1d9e1c21f928290':
        raise AssertionError('Unexpected approved source candidate')
    if manifest.get('historical_overlay')!={
        'commit':'cbe1ec4b65bfc4b01285c20477d91974ccb411fe',
        'archive':'validation/fixtures/production_nazk_recovery_overlay_cbe1ec4.zip',
        'sha256':'09d1f1cec428bd2bcfdbc236158a5f0466ab09038b3d8d0584f51b964dda8f7f',
    }:
        raise AssertionError('Unexpected historical recovery integrity overlay')
    return manifest

def tree_matches(manifest,root=ROOT):
    for section in ('product_sha256','protected_sha256','regression_sha256'):
        for relative,expected in manifest.get(section,{}).items():
            try:content=(Path(root)/relative).read_bytes()
            except OSError:return False
            if sha256(content,relative)!=expected:return False
    return True

class ProductionNazkMessagesIntegrityTests(unittest.TestCase):
    def test_integrated_tree_matches_exact_additive_manifest(self):
        manifest=read_manifest()
        self.assertEqual(len(manifest['product_sha256']),12)
        self.assertEqual(len(manifest['protected_sha256']),8)
        self.assertEqual(set(manifest['regression_sha256']),EXPECTED_REGRESSION_FILES)
        self.assertTrue(tree_matches(manifest))

    def test_production_workflow_and_existing_supplier_template_are_guarded(self):
        manifest=read_manifest()
        protected=set(manifest['protected_sha256'])
        self.assertTrue({'nazk_workflow.py','scheduler_runtime.py','supplier_activity.py',
                         'edr_sync_v2.py','operational_tasks.py','table_widths_ui.js',
                         'templates/nazk_supplier_request.docx'}<=protected)
        products=set(manifest['product_sha256'])
        self.assertIn('templates/nazk_authority_request.docx',products)
        self.assertEqual(manifest['product_sha256']['templates/nazk_authority_request.docx'],
                         'c5649e036601364eb9a3fbe37cd49cfea0a4b9d3c8f9696ca0684f490b6801f5')

    def test_single_byte_append_and_delete_mutations_are_rejected(self):
        manifest=read_manifest()
        for relative,expected in {**manifest['product_sha256'],**manifest['protected_sha256'],
                                  **manifest['regression_sha256']}.items():
            content=(ROOT/relative).read_bytes()
            self.assertEqual(sha256(content,relative),expected,relative)
            if content:
                mutation=bytearray(content);mutation[len(mutation)//2]^=1
                self.assertNotEqual(sha256(bytes(mutation),relative),expected,relative+' byte')
                self.assertNotEqual(sha256(content+b'X',relative),expected,relative+' append')
                self.assertNotEqual(sha256(content[:-1],relative),expected,relative+' delete')

if __name__=='__main__':unittest.main()
