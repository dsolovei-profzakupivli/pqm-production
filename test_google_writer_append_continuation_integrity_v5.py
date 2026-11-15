"""Current-source integrity contract for continuation v2 and its preview UX."""
import hashlib
import json
from pathlib import Path
import re
import unittest


MANIFEST = Path('validation/local_release_20261115/google_writer_append_continuation_v5.json')
MANIFEST_SHA256 = "34154a0d0b5060301bfb038a95d8b2c8616a96c8f8bed8720bd9cfa1987a3c8e"
TEST_FILE = 'test_google_writer_append_continuation_integrity_v5.py'
ROOT = Path(__file__).resolve().parent
PRESERVED = {
    'validation/local_release_20261113/google_writer_append_continuation_v1.json': 'e2569da64bcc83e18b5223d9cbfeccab46ea7524cfa2f41ed1a452f929922aa2',
    'validation/local_release_20261113/google_writer_append_continuation_v2.json': '2fb4d7124cdd7039ff07c87b275551e678afafb4aa807b7b0f0c5536e9bf2089',
    'validation/local_release_20261113/google_writer_append_continuation_v3.json': 'ad378d8717b936a01671eb9837b842946f5636d74663f2382e23c24f4dbb7e63',
    'validation/local_release_20261113/google_writer_append_continuation_v4.json': '644737f2c2772e21b7c81f571678bec494641a336703375aa40b3988e1944b92',
}


def canonical(data):
    return data.replace(b'\r\n', b'\n')


def canonical_self(data):
    return re.sub(rb'(?m)^MANIFEST_SHA256 = "(?:<manifest-sha256>|[0-9a-f]{64})"$',
                  b'MANIFEST_SHA256 = "<manifest-sha256>"', canonical(data))


class GoogleWriterAppendContinuationIntegrityV5(unittest.TestCase):
    def test_v5_manifest_pins_current_continuation_sources_and_tests(self):
        raw = canonical((ROOT / MANIFEST).read_bytes())
        self.assertEqual(hashlib.sha256(raw).hexdigest(), MANIFEST_SHA256)
        manifest = json.loads(raw.decode('utf-8'))
        self.assertEqual(manifest['contract'], 'pqm-sandbox-google-writer-append-continuation')
        self.assertEqual(manifest['version'], 5)
        self.assertEqual(manifest['baseline'], 'b988f140af37c45bd5461735cf40d18cd00d741a')
        self.assertEqual(set(manifest['scope']), set(manifest['files']))
        self.assertEqual(set(manifest['files']), {
            'google_writer_execution.py',
            'server.py',
            'test_google_writer_append_continuation.py',
            'google_writer_ui.js',
            'validation/google_writer_continuation_preview_ui.test.cjs',
            TEST_FILE,
        })
        for relative, expected in manifest['files'].items():
            data = (ROOT / relative).read_bytes()
            normalized = canonical_self(data) if relative == TEST_FILE else canonical(data)
            with self.subTest(path=relative):
                self.assertEqual(hashlib.sha256(normalized).hexdigest(), expected)

    def test_v1_through_v4_manifests_are_preserved(self):
        for relative, expected in PRESERVED.items():
            with self.subTest(manifest=relative):
                self.assertEqual(hashlib.sha256(canonical((ROOT / relative).read_bytes())).hexdigest(), expected)

    def test_v5_is_current_gate_while_v4_remains_historical(self):
        workflow = (ROOT / '.github/workflows/release-checks.yml').read_text(encoding='utf-8')
        self.assertIn('git archive ce722e3ed654a0e30be3b048a292e1e7e6ba0828', workflow)
        self.assertIn('test_google_writer_append_continuation_integrity_v4', workflow)
        self.assertIn('test_google_writer_append_continuation_integrity_v5', workflow)
        runner = (ROOT / 'validation/run_local_release.py').read_text(encoding='utf-8')
        exact = runner.split('EXACT_TREE_OVERLAY_MODULES', 1)[1].split('}', 1)[0]
        self.assertIn("'test_google_writer_append_continuation_integrity_v4'", exact)
        self.assertNotIn("'test_google_writer_append_continuation_integrity_v5'", exact)


if __name__ == '__main__':
    unittest.main()
