"""Additive integrity contract for the Messages page header layout polish."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

MANIFEST_NAME = 'test_sandbox_messages_header_polish_integrity_v3.json'
MANIFEST_SHA256 = '307c53ecabfa22c7abc77ca8d9d88423000ff0e42e162e8b7a766021d13fc0ed'
VARIANT_ID = 'pqm-sandbox-messages-header-polish-v3'
BASELINE_SHA = 'abb1964a8bf5b07c6882d1c119068bdbe7f8b9bf'
INTEGRITY_TEST = 'test_sandbox_messages_header_polish_integrity_v3.py'
INTEGRITY_TEST_SHA256 = '23dfd295575f9af3b89d14c7fd55227823293115340ba62f64d79d227110fbea'
HISTORICAL_V2_MANIFEST_SHA256 = 'e59205a1018267cd38e4b42ef79163b1041a4300c5441d96d39a56075a5d9d9b'
V2_OVERRIDE_FIXTURE = 'validation/fixtures/messages_search_header_v2_overrides.zip'
V2_OVERRIDE_FIXTURE_SHA256 = '58a8f3cab5308e9a2b90d6cf1603ed8eb84f1e9ea7a73854fa2c642276a8a221'
EXPECTED_FILES = {
    'chat_annotations.css',
    'validation/chat_messages_browser.cjs',
    'validation/run_local_release.py',
    'validation/run_messages_search_header_v2_integrity.py',
    V2_OVERRIDE_FIXTURE,
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
        elif line.startswith(b"INTEGRITY_TEST_SHA256 = "):
            ending = b"\n" if line.endswith(b"\n") else b""
            lines[index] = b"INTEGRITY_TEST_SHA256 = '<pinned-integrity-test-sha256>'" + ending
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
        raise AssertionError('Messages header polish manifest SHA-256 mismatch')
    manifest = json.loads(raw.decode('utf-8'))
    if set(manifest) != {'variant_id', 'baseline_sha', 'files', 'integrity_test_file', 'integrity_test_sha256'}:
        raise AssertionError('Unexpected Messages header polish manifest schema')
    if manifest['variant_id'] != VARIANT_ID or manifest['baseline_sha'] != BASELINE_SHA:
        raise AssertionError('Unexpected Messages header polish baseline or variant')
    if set(manifest['files']) != EXPECTED_FILES or manifest['integrity_test_file'] != INTEGRITY_TEST:
        raise AssertionError('Messages header polish file scope mismatch')
    if manifest['integrity_test_sha256'] != INTEGRITY_TEST_SHA256:
        raise AssertionError('Messages header polish test hash mismatch in manifest')
    if digest(canonical_self((root / INTEGRITY_TEST).read_bytes())) != INTEGRITY_TEST_SHA256:
        raise AssertionError('Messages header polish integrity test source changed')
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


class MessagesHeaderPolishIntegrityTests(unittest.TestCase):
    def test_exact_additive_contract_preserves_v2_history(self):
        manifest = read_manifest()
        self.assertEqual(EXPECTED_FILES, set(manifest['files']))
        self.assertTrue(tree_matches(ROOT, manifest))
        self.assertEqual(HISTORICAL_V2_MANIFEST_SHA256,
                         digest(canonical_text((ROOT / 'test_sandbox_messages_search_header_integrity_v2.json').read_bytes())))
        self.assertEqual(V2_OVERRIDE_FIXTURE_SHA256, digest((ROOT / V2_OVERRIDE_FIXTURE).read_bytes()))

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
