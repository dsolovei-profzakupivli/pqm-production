"""Additive current-source integrity contract for APPEND continuation v1."""
import hashlib
import json
from pathlib import Path
import re
import unittest


MANIFEST = Path('validation/local_release_20261113/google_writer_append_continuation_v3.json')
MANIFEST_SHA256 = "ad378d8717b936a01671eb9837b842946f5636d74663f2382e23c24f4dbb7e63"
TEST_FILE = 'test_google_writer_append_continuation_integrity_v3.py'
ROOT = Path(__file__).resolve().parent
PRESERVED = {
    'validation/local_release_20261113/google_writer_append_continuation_v1.json': 'e2569da64bcc83e18b5223d9cbfeccab46ea7524cfa2f41ed1a452f929922aa2',
    'validation/local_release_20261113/google_writer_append_continuation_v2.json': '2fb4d7124cdd7039ff07c87b275551e678afafb4aa807b7b0f0c5536e9bf2089',
}


def canonical(data):
    return data.replace(b'\r\n', b'\n')


def canonical_self(data):
    return re.sub(rb'(?m)^MANIFEST_SHA256 = "(?:<manifest-sha256>|[0-9a-f]{64})"$',
                  b'MANIFEST_SHA256 = "<manifest-sha256>"', canonical(data))


class GoogleWriterAppendContinuationIntegrityV3(unittest.TestCase):
    def test_current_continuation_overlay_pins_complete_contract(self):
        raw = canonical((ROOT / MANIFEST).read_bytes())
        self.assertEqual(hashlib.sha256(raw).hexdigest(), MANIFEST_SHA256)
        manifest = json.loads(raw.decode('utf-8'))
        self.assertEqual(manifest['contract'], 'pqm-sandbox-google-writer-append-continuation')
        self.assertEqual(manifest['version'], 3)
        self.assertEqual(manifest['baseline'], '7417591bbd8cb945a85e759d28036b72f97f8e9e')
        self.assertEqual(set(manifest['scope']), set(manifest['files']))
        self.assertIn('scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxFullApply.gs', manifest['scope'])
        self.assertIn('test_google_writer_append_continuation.py', manifest['scope'])
        for relative, expected in manifest['files'].items():
            data = (ROOT / relative).read_bytes()
            normalized = canonical_self(data) if relative == TEST_FILE else canonical(data)
            with self.subTest(path=relative):
                self.assertEqual(hashlib.sha256(normalized).hexdigest(), expected)

    def test_historical_v1_and_v2_manifests_are_unchanged(self):
        for relative, expected in PRESERVED.items():
            with self.subTest(manifest=relative):
                self.assertEqual(hashlib.sha256(canonical((ROOT / relative).read_bytes())).hexdigest(), expected)

    def test_v29_formula_compatibility_remains_limited_to_column_a(self):
        source = canonical((ROOT / 'scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxFullApply.gs').read_bytes()).decode('utf-8')
        self.assertIn('column === 0', source)
        self.assertIn('formula', source)


if __name__ == '__main__':
    unittest.main()
