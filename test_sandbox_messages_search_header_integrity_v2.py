"""Additive integrity contract for chat-linked search and compact header."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

MANIFEST_NAME = 'test_sandbox_messages_search_header_integrity_v2.json'
MANIFEST_SHA256 = 'e59205a1018267cd38e4b42ef79163b1041a4300c5441d96d39a56075a5d9d9b'
VARIANT_ID = 'pqm-sandbox-messages-search-header-v2'
BASELINE_SHA = 'eafa12a59ad5a382d1accd972bf50d0f26c8b8bc'
INTEGRITY_TEST = 'test_sandbox_messages_search_header_integrity_v2.py'
V1_MESSAGES_MANIFEST_SHA256 = '1bb3bdbe99b3f041b6bc6dbdfaf4768a5b21f75c84d7f4a6a61351726a731143'
V1_INTEGRATED_MANIFEST_SHA256 = '09974dd9d59b41439b873a334325d9aa33e755d81d8c5e357992696b5556d41e'
OVERRIDE_FIXTURE = 'validation/fixtures/messages_integrated_v1_overrides.zip'
OVERRIDE_FIXTURE_SHA256 = '78287b12633f82c3a366e2377d35eec4a0b96ecba28f2bfd5ea3e79982ea7928'
EXPECTED_FILES = {
    'chat_annotations.py',
    'chat_annotations.css',
    'index.html',
    'validation/chat_messages_browser.cjs',
    'validation/local_release_20260911/test_chat_annotations.py',
    'validation/local_release_20260911/test_chat_annotations_http.py',
    'validation/run_local_release.py',
    'validation/run_integrated_messages_v1_integrity.py',
    OVERRIDE_FIXTURE,
    INTEGRITY_TEST,
}
ROOT = Path(__file__).resolve().parent


def digest(content):
    return hashlib.sha256(content).hexdigest()


def canonical_text(content):
    return content.replace(b'\r\n', b'\n')


def canonical_self(content):
    lines = canonical_text(content).splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.startswith(b"MANIFEST_SHA256 = "):
            ending = b"\n" if line.endswith(b"\n") else b""
            lines[index] = b"MANIFEST_SHA256 = '<pinned-manifest-sha256>'" + ending
            break
    return b''.join(lines)


def canonical_file(name, content):
    if Path(name).suffix.lower() in {'.cjs', '.css', '.html', '.js', '.json', '.md', '.py', '.txt', '.yaml', '.yml'}:
        content = canonical_text(content)
    if name == INTEGRITY_TEST:
        content = canonical_self(content)
    return content


def read_manifest(root=ROOT):
    root = Path(root)
    raw = (root / MANIFEST_NAME).read_bytes()
    if digest(canonical_text(raw)) != MANIFEST_SHA256:
        raise AssertionError('Messages search/header manifest SHA-256 mismatch')
    manifest = json.loads(raw.decode('utf-8'))
    if set(manifest) != {'variant_id', 'baseline_sha', 'files', 'integrity_test_file', 'integrity_test_sha256'}:
        raise AssertionError('Unexpected Messages search/header manifest schema')
    if manifest['variant_id'] != VARIANT_ID or manifest['baseline_sha'] != BASELINE_SHA:
        raise AssertionError('Unexpected Messages search/header baseline or variant')
    if set(manifest['files']) != EXPECTED_FILES or manifest['integrity_test_file'] != INTEGRITY_TEST:
        raise AssertionError('Messages search/header file scope mismatch')
    if digest(canonical_self((root / INTEGRITY_TEST).read_bytes())) != manifest['integrity_test_sha256']:
        raise AssertionError('Messages search/header integrity test source changed')
    return manifest


def tree_matches(root=ROOT, manifest=None):
    root = Path(root)
    manifest = manifest or read_manifest(root)
    for name, expected in manifest['files'].items():
        try:
            actual = canonical_file(name, (root / name).read_bytes())
        except OSError:
            return False
        if digest(actual) != expected:
            return False
    return True


class MessagesSearchHeaderIntegrityTests(unittest.TestCase):
    def test_exact_additive_contract_and_unchanged_historical_manifests(self):
        manifest = read_manifest()
        self.assertEqual(EXPECTED_FILES, set(manifest['files']))
        self.assertTrue(tree_matches(ROOT, manifest))
        for name, expected in {
            'test_sandbox_messages_integrity_v1.json': V1_MESSAGES_MANIFEST_SHA256,
            'test_sandbox_nazk_messages_integrated_v1.json': V1_INTEGRATED_MANIFEST_SHA256,
        }.items():
            self.assertEqual(expected, digest(canonical_text((ROOT / name).read_bytes())))
        self.assertEqual(OVERRIDE_FIXTURE_SHA256, digest((ROOT / OVERRIDE_FIXTURE).read_bytes()))

    def test_v1_overlay_contains_only_approved_historical_overrides(self):
        with zipfile.ZipFile(ROOT / OVERRIDE_FIXTURE) as archive:
            names = {item.filename for item in archive.infolist() if not item.is_dir()}
        self.assertEqual({
            'chat_annotations.css', 'chat_annotations.py', 'index.html',
            'test_sandbox_nazk_messages_integrated_integrity.py',
            'validation/chat_messages_browser.cjs',
            'validation/local_release_20260911/test_chat_annotations.py',
            'validation/local_release_20260911/test_chat_annotations_http.py',
            'validation/run_local_release.py',
        }, names)

    def test_every_pinned_file_rejects_single_byte_mutation(self):
        manifest = read_manifest()
        with tempfile.TemporaryDirectory(dir=ROOT / 'validation') as temporary:
            tree = Path(temporary)
            for name in manifest['files']:
                target = tree / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / name).read_bytes())
            self.assertTrue(tree_matches(tree, manifest))
            for name in sorted(manifest['files']):
                target = tree / name
                original = target.read_bytes()
                offset = next((index for index, value in enumerate(original) if value not in (10, 13)), 0)
                changed = bytearray(original)
                changed[offset] ^= 1
                target.write_bytes(changed)
                with self.subTest(name=name):
                    self.assertFalse(tree_matches(tree, manifest))
                target.write_bytes(original)
            self.assertTrue(tree_matches(tree, manifest))


if __name__ == '__main__':
    unittest.main()
