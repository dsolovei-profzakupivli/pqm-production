"""Exact additive integrity contract for the joint NAZK and Messages tree."""
import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST_NAME = 'test_sandbox_nazk_messages_integrated_v1.json'
MANIFEST_SHA256 = '09974dd9d59b41439b873a334325d9aa33e755d81d8c5e357992696b5556d41e'
VARIANT_ID = 'pqm-sandbox-nazk-messages-integrated-v1'
BASELINE_SHA = 'c246edefaa676d137d3f38d40f18d039f7b5bac2'
NAZK_CANDIDATE_SHA = 'd0bb9eaa323210183081c6605bd292d6443d5f70'
MESSAGES_CANDIDATE_SHA = 'aa350c5cf65adf3d436c9d64d43efae82b8cd846'
INTEGRITY_TEST = 'test_sandbox_nazk_messages_integrated_integrity.py'
EXPECTED_FILES = {
    '.github/workflows/release-checks.yml',
    'app.js',
    'artifacts/nazk_authority_request_samples/Запит_до_НАЗК_ФОП_Салій_зразок.docx',
    'artifacts/nazk_authority_request_samples/Запит_до_НАЗК_юридична_особа_синтетичний_зразок.docx',
    'artifacts/rendered/nazk_authority_request.pdf',
    'artifacts/rendered/Запит_до_НАЗК_ФОП_Салій_зразок.pdf',
    'artifacts/rendered/Запит_до_НАЗК_юридична_особа_синтетичний_зразок.pdf',
    'chat_annotations.css',
    'chat_annotations.py',
    'chat_ui.js',
    'index.html',
    'messages_crlf_test_integrity.py',
    'messages_integrity.py',
    'metadata/runtime_templates.v1.json',
    'metadata/template_fields.v1.json',
    'navigation.js',
    'operational_tasks.py',
    'protocol_template.py',
    'sandbox_runtime.py',
    'server.py',
    'task_documents.py',
    'templates/nazk_authority_request.docx',
    'test_halloween_motion_integration.py',
    'test_messages_historical_line_endings.py',
    'test_sandbox_appeals_scenario_api_integrity.py',
    'test_sandbox_dst_hotfix_integrity.py',
    'test_sandbox_messages_crlf_integrity_v2.json',
    'test_sandbox_messages_integrity.py',
    'test_sandbox_messages_integrity_v1.json',
    'test_sandbox_nazk_appeals_stabilization_integrity.py',
    'test_sandbox_nazk_appeals_stabilization_v3_integrity.py',
    'test_sandbox_nazk_messages_integrated_integrity.py',
    'test_sandbox_nazk_preview_integrity.py',
    'test_sandbox_nazk_recovery_integrity.py',
    'test_sandbox_nazk_recovery_qualification_integrity.py',
    'test_sandbox_smoke_nazk_authority_integrity.py',
    'test_sandbox_smoke_nazk_authority_v1.json',
    'test_sandbox_web_smoke_nazk_authority_integrity.py',
    'test_sandbox_web_smoke_nazk_authority_v1.json',
    'validation/chat_messages_browser.cjs',
    'validation/fixtures/messages_parent_c246edef.zip',
    'validation/fixtures/messages_v1_test_parent.zip',
    'validation/fixtures/nazk_authority_parent_c246.zip',
    'validation/fixtures/nazk_authority_request_v1.json',
    'validation/local_release_20260911/sandbox_protocol_integrity_variant.py',
    'validation/local_release_20260911/test_chat_annotations.py',
    'validation/local_release_20260911/test_chat_annotations_http.py',
    'validation/local_release_20260911/test_nazk_authority_request.py',
    'validation/local_release_20260911/test_nazk_authority_request_integrity.py',
    'validation/local_release_20260911/test_task_documents.py',
    'validation/run_local_release.py',
    'validation/sandbox_smoke.py',
    'validation/web_smoke.py',
}
TEXT_SUFFIXES = {'.cjs', '.css', '.html', '.js', '.json', '.md', '.py', '.txt', '.yaml', '.yml'}


def digest(content):
    return hashlib.sha256(content).hexdigest()


def canonical_text(content):
    return content.replace(b'\r\n', b'\n')


def canonical_self(content):
    content = canonical_text(content)
    return re.sub(rb"MANIFEST_SHA256 = '[0-9a-f]{64}'",
                  b"MANIFEST_SHA256 = '<pinned-manifest-sha256>'", content)


def file_matches(relative, content, expected):
    if relative == INTEGRITY_TEST:
        return digest(canonical_self(content)) == expected
    if Path(relative).suffix.lower() in TEXT_SUFFIXES:
        content = canonical_text(content)
    return digest(content) == expected


def read_manifest(root=ROOT):
    root = Path(root)
    raw = (root / MANIFEST_NAME).read_bytes()
    if digest(canonical_text(raw)) != MANIFEST_SHA256:
        raise AssertionError('Integrated NAZK + Messages manifest SHA mismatch')
    manifest = json.loads(raw.decode('utf-8'))
    if set(manifest) != {'variant_id', 'baseline_sha', 'nazk_candidate_sha',
                         'messages_candidate_sha', 'approved_scope', 'files',
                         'integrity_test_file', 'integrity_test_sha256'}:
        raise AssertionError('Unexpected integrated manifest schema')
    if (manifest['variant_id'] != VARIANT_ID or manifest['baseline_sha'] != BASELINE_SHA
            or manifest['nazk_candidate_sha'] != NAZK_CANDIDATE_SHA
            or manifest['messages_candidate_sha'] != MESSAGES_CANDIDATE_SHA):
        raise AssertionError('Unexpected integrated baseline or candidate identity')
    if set(manifest['files']) != EXPECTED_FILES or manifest['integrity_test_file'] != INTEGRITY_TEST:
        raise AssertionError('Integrated manifest file scope mismatch')
    test_source = (root / INTEGRITY_TEST).read_bytes()
    if digest(canonical_self(test_source)) != manifest['integrity_test_sha256']:
        raise AssertionError('Integrated integrity test source changed')
    return manifest


def manifest_tree_matches(root=ROOT, manifest=None):
    root = Path(root)
    manifest = manifest or read_manifest()
    for relative, expected in manifest['files'].items():
        try:
            content = (root / relative).read_bytes()
        except OSError:
            return False
        if not file_matches(relative, content, expected):
            return False
    return True


class IntegratedNazkMessagesIntegrityTests(unittest.TestCase):
    def test_exact_integrated_tree_and_candidate_scope(self):
        manifest = read_manifest()
        self.assertEqual(EXPECTED_FILES, set(manifest['files']))
        self.assertTrue(manifest_tree_matches(ROOT, manifest))

    def test_every_integrated_file_rejects_single_content_byte_mutation(self):
        manifest = read_manifest()
        with tempfile.TemporaryDirectory(dir=ROOT / 'validation') as temporary:
            tree = Path(temporary)
            for relative in manifest['files']:
                target = tree / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / relative).read_bytes())
            self.assertTrue(manifest_tree_matches(tree, manifest))
            for relative in sorted(manifest['files']):
                target = tree / relative
                original = target.read_bytes()
                offset = next((index for index, value in enumerate(original)
                               if value not in (10, 13)), 0)
                changed = bytearray(original)
                changed[offset] ^= 1
                target.write_bytes(changed)
                with self.subTest(path=relative):
                    self.assertFalse(manifest_tree_matches(tree, manifest))
                target.write_bytes(original)
            self.assertTrue(manifest_tree_matches(tree, manifest))

    def test_manifest_single_byte_and_json_value_mutations_are_rejected(self):
        read_manifest()
        original = (ROOT / MANIFEST_NAME).read_bytes()
        for changed in (original + b' ', original[1:],
                        original.replace(BASELINE_SHA.encode(), b'x' + BASELINE_SHA[1:].encode(), 1)):
            with tempfile.TemporaryDirectory(dir=ROOT / 'validation') as temporary:
                tree = Path(temporary)
                (tree / MANIFEST_NAME).write_bytes(changed)
                (tree / INTEGRITY_TEST).write_bytes((ROOT / INTEGRITY_TEST).read_bytes())
                with self.assertRaisesRegex(AssertionError, 'manifest SHA mismatch'):
                    read_manifest(tree)


if __name__ == '__main__':
    unittest.main()
