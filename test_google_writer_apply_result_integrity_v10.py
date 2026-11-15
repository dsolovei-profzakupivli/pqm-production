"""Current-source integrity overlay v10 for continuation Apply and request UX."""
import hashlib
import json
from pathlib import Path
import re
import unittest


MANIFEST = Path('validation/local_release_20261115/google_writer_apply_result_v10.json')
MANIFEST_SHA256 = '3e9e7d340436d46782e55a4d7b4273849b00ca771e667503d009f0dfb2fb5063'
TEST_FILE = 'test_google_writer_apply_result_integrity_v10.py'
ROOT = Path(__file__).resolve().parent
PRESERVED = {
    'validation/local_release_20261115/google_writer_apply_result_v5.json': 'd029a33dec13613634f2704ecaa0bf76038a01435ecf6d67f3d17585ee16f45d',
    'validation/local_release_20261115/google_writer_apply_result_v6.json': '65b509634de88ede330bd4202107de023d9e0c62cfb4487a34bc919aa7f4d802',
    'validation/local_release_20261115/google_writer_apply_result_v7.json': 'd933c14848be3e0bdde412c1b45c4dc6b5736bdb39325d29b1afd1a1d024fabb',
    'validation/local_release_20261115/google_writer_apply_result_v8.json': 'f52397e93ef6ecfd1f772d26b0b6562c48169a272ab17917f9c4fc7456c0fbe5',
    'validation/local_release_20261115/google_writer_apply_result_v9.json': '07dc3ad3dc72f88a0f6334dd1e876140f9b0a4d991376f736a5b9dee0ad09373',
    'validation/local_release_20261113/google_writer_append_continuation_v1.json': 'e2569da64bcc83e18b5223d9cbfeccab46ea7524cfa2f41ed1a452f929922aa2',
    'validation/local_release_20261113/google_writer_append_continuation_v2.json': '2fb4d7124cdd7039ff07c87b275551e678afafb4aa807b7b0f0c5536e9bf2089',
    'validation/local_release_20261113/google_writer_append_continuation_v3.json': 'ad378d8717b936a01671eb9837b842946f5636d74663f2382e23c24f4dbb7e63',
    'validation/local_release_20261113/google_writer_append_continuation_v4.json': '644737f2c2772e21b7c81f571678bec494641a336703375aa40b3988e1944b92',
}


def canonical(data):
    return data.replace(b'\r\n', b'\n')


def canonical_self(data):
    return re.sub(rb"(?m)^MANIFEST_SHA256\s*=\s*'(?:<manifest-sha256>|[0-9a-f]{64})'$",
                  b"MANIFEST_SHA256 = '<manifest-sha256>'", canonical(data))


class GoogleWriterApplyResultIntegrityV10(unittest.TestCase):
    def test_v10_manifest_pins_current_sources_tests_and_gate_routing(self):
        raw = canonical((ROOT / MANIFEST).read_bytes())
        self.assertEqual(hashlib.sha256(raw).hexdigest(), MANIFEST_SHA256)
        manifest = json.loads(raw.decode('utf-8'))
        self.assertEqual(manifest['contract'], 'pqm-sandbox-saved-continuation-audit')
        self.assertEqual(manifest['version'], 10)
        self.assertEqual(manifest['baseline'], 'b988f140af37c45bd5461735cf40d18cd00d741a')
        self.assertEqual(set(manifest['scope']), set(manifest['files']))
        self.assertEqual(set(manifest['files']), {
            'google_writer_apply_result.js',
            'google_writer_execution.py',
            'google_writer_ui.js',
            'server.py',
            'modules.css',
            'test_google_writer_append_continuation.py',
            'test_google_writer_append_continuation_integrity_v5.py',
            'test_release_gate_infrastructure.py',
            'validation/run_local_release.py',
            '.github/workflows/release-checks.yml',
            'validation/google_writer_apply_result_ui.test.cjs',
            'validation/google_writer_continuation_preview_ui.test.cjs',
            'test_google_writer_apply_result_integrity_v10.py',
        })
        for relative, expected in manifest['files'].items():
            data = (ROOT / relative).read_bytes()
            normalized = canonical_self(data) if relative == TEST_FILE else canonical(data)
            with self.subTest(path=relative):
                self.assertEqual(hashlib.sha256(normalized).hexdigest(), expected)

    def test_v1_through_v9_manifests_are_preserved(self):
        for relative, expected in PRESERVED.items():
            with self.subTest(manifest=relative):
                self.assertEqual(hashlib.sha256(canonical((ROOT / relative).read_bytes())).hexdigest(), expected)

    def test_v9_is_historical_and_v10_is_current_in_release_gate(self):
        workflow = (ROOT / '.github/workflows/release-checks.yml').read_text(encoding='utf-8')
        self.assertIn('git archive b988f140af37c45bd5461735cf40d18cd00d741a', workflow)
        self.assertIn('test_google_writer_apply_result_integrity_v9', workflow)
        self.assertIn('test_google_writer_apply_result_integrity_v10', workflow)
        self.assertLess(workflow.index('test_google_writer_apply_result_integrity_v9'),
                        workflow.index('test_google_writer_apply_result_integrity_v10'))
        runner = (ROOT / 'validation/run_local_release.py').read_text(encoding='utf-8')
        exact = runner.split('EXACT_TREE_OVERLAY_MODULES', 1)[1].split('}', 1)[0]
        self.assertIn("'test_google_writer_apply_result_integrity_v9'", exact)
        self.assertNotIn("'test_google_writer_apply_result_integrity_v10'", exact)


if __name__ == '__main__':
    unittest.main()
