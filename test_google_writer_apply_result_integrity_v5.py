"""Current-source integrity contract for the read-only Apply Result Panel."""
import hashlib
import json
from pathlib import Path
import re
import unittest


MANIFEST = Path('validation/local_release_20261115/google_writer_apply_result_v5.json')
MANIFEST_SHA256 = "d029a33dec13613634f2704ecaa0bf76038a01435ecf6d67f3d17585ee16f45d"
TEST_FILE = 'test_google_writer_apply_result_integrity_v5.py'
ROOT = Path(__file__).resolve().parent


def canonical(data):
    return data.replace(b'\r\n', b'\n')


def canonical_self(data):
    return re.sub(rb'(?m)^MANIFEST_SHA256 = "(?:<manifest-sha256>|[0-9a-f]{64})"$',
                  b'MANIFEST_SHA256 = "<manifest-sha256>"', canonical(data))


class GoogleWriterApplyResultIntegrityV5(unittest.TestCase):
    def test_current_apply_result_contract_is_fully_pinned(self):
        raw = canonical((ROOT / MANIFEST).read_bytes())
        self.assertEqual(hashlib.sha256(raw).hexdigest(), MANIFEST_SHA256)
        manifest = json.loads(raw.decode('utf-8'))
        self.assertEqual(manifest['contract'], 'pqm-sandbox-google-writer-apply-result-panel')
        self.assertEqual(manifest['version'], 5)
        self.assertEqual(manifest['baseline'], 'ce722e3ed654a0e30be3b048a292e1e7e6ba0828')
        self.assertEqual(set(manifest['scope']), set(manifest['files']))
        self.assertEqual(set(manifest['files']), {
            'google_writer_execution.py', 'server.py', 'google_writer_ui.js',
            'google_writer_apply_result.js', 'index.html', 'modules.css',
            'test_google_writer_apply_result_diagnostic.py',
            'validation/google_writer_apply_result_ui.test.cjs',
            'validation/google_writer_preview_modal_browser.cjs',
            'validation/run_local_release.py', '.github/workflows/release-checks.yml',
            'test_release_gate_infrastructure.py', TEST_FILE,
        })
        for relative, expected in manifest['files'].items():
            data = (ROOT / relative).read_bytes()
            normalized = canonical_self(data) if relative == TEST_FILE else canonical(data)
            with self.subTest(path=relative):
                self.assertEqual(hashlib.sha256(normalized).hexdigest(), expected)

    def test_historical_v1_through_v4_manifests_are_unchanged(self):
        manifest = json.loads(canonical((ROOT / MANIFEST).read_bytes()).decode('utf-8'))
        self.assertEqual(set(manifest['preserved_manifests']), {
            'validation/local_release_20261113/google_writer_append_continuation_v1.json',
            'validation/local_release_20261113/google_writer_append_continuation_v2.json',
            'validation/local_release_20261113/google_writer_append_continuation_v3.json',
            'validation/local_release_20261113/google_writer_append_continuation_v4.json',
        })
        for relative, expected in manifest['preserved_manifests'].items():
            with self.subTest(manifest=relative):
                self.assertEqual(hashlib.sha256(canonical((ROOT / relative).read_bytes())).hexdigest(), expected)

    def test_release_gate_runs_v4_on_its_historical_tree_and_v5_on_current_tree(self):
        workflow = (ROOT / '.github/workflows/release-checks.yml').read_text(encoding='utf-8')
        self.assertIn('git archive ce722e3ed654a0e30be3b048a292e1e7e6ba0828', workflow)
        self.assertIn('test_google_writer_append_continuation_integrity_v4', workflow)
        self.assertIn('test_google_writer_apply_result_integrity_v5', workflow)


if __name__ == '__main__':
    unittest.main()
