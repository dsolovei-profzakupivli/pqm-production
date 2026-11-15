"""Current-source integrity contract for the always-visible read-only diagnostic panel."""
import hashlib
import json
from pathlib import Path
import re
import unittest


MANIFEST = Path('validation/local_release_20261115/google_writer_apply_result_v6.json')
MANIFEST_SHA256 = "65b509634de88ede330bd4202107de023d9e0c62cfb4487a34bc919aa7f4d802"
TEST_FILE = 'test_google_writer_apply_result_integrity_v6.py'
ROOT = Path(__file__).resolve().parent


def canonical(data):
    return data.replace(b'\r\n', b'\n')


def canonical_self(data):
    return re.sub(rb'(?m)^MANIFEST_SHA256 = "(?:<manifest-sha256>|[0-9a-f]{64})"$',
                  b'MANIFEST_SHA256 = "<manifest-sha256>"', canonical(data))


class GoogleWriterApplyResultIntegrityV6(unittest.TestCase):
    def test_current_readonly_diagnostic_and_edr_layout_are_pinned(self):
        raw = canonical((ROOT / MANIFEST).read_bytes())
        self.assertEqual(hashlib.sha256(raw).hexdigest(), MANIFEST_SHA256)
        manifest = json.loads(raw.decode('utf-8'))
        self.assertEqual(manifest['contract'], 'pqm-sandbox-google-writer-apply-result-panel')
        self.assertEqual(manifest['version'], 6)
        self.assertEqual(manifest['baseline'], '2a4e4bff0bbbe84670d3bb10a5ba4b90347a7d78')
        self.assertEqual(set(manifest['scope']), set(manifest['files']))
        self.assertEqual(set(manifest['files']), {
            'google_writer_apply_result.js', 'index.html', 'modules.css',
            'validation/google_writer_apply_result_ui.test.cjs',
            'validation/run_local_release.py', '.github/workflows/release-checks.yml',
            'test_release_gate_infrastructure.py', TEST_FILE,
        })
        for relative, expected in manifest['files'].items():
            data = (ROOT / relative).read_bytes()
            normalized = canonical_self(data) if relative == TEST_FILE else canonical(data)
            with self.subTest(path=relative):
                self.assertEqual(hashlib.sha256(normalized).hexdigest(), expected)

    def test_apply_result_v1_to_v5_contracts_remain_unchanged(self):
        manifest = json.loads(canonical((ROOT / MANIFEST).read_bytes()).decode('utf-8'))
        expected_paths = {
            'validation/local_release_20261115/google_writer_apply_result_v5.json',
            'validation/local_release_20261113/google_writer_append_continuation_v1.json',
            'validation/local_release_20261113/google_writer_append_continuation_v2.json',
            'validation/local_release_20261113/google_writer_append_continuation_v3.json',
            'validation/local_release_20261113/google_writer_append_continuation_v4.json',
        }
        self.assertEqual(set(manifest['preserved_manifests']), expected_paths)
        for relative, expected in manifest['preserved_manifests'].items():
            with self.subTest(manifest=relative):
                self.assertEqual(hashlib.sha256(canonical((ROOT / relative).read_bytes())).hexdigest(), expected)

    def test_gate_runs_v5_on_its_exact_tree_and_v6_on_current_sources(self):
        workflow = (ROOT / '.github/workflows/release-checks.yml').read_text(encoding='utf-8')
        self.assertIn('git archive 2a4e4bff0bbbe84670d3bb10a5ba4b90347a7d78', workflow)
        self.assertIn('test_google_writer_apply_result_integrity_v5', workflow)
        self.assertIn('test_google_writer_apply_result_integrity_v6', workflow)
        runner = (ROOT / 'validation/run_local_release.py').read_text(encoding='utf-8')
        exact = runner.split('EXACT_TREE_OVERLAY_MODULES', 1)[1].split('}', 1)[0]
        self.assertIn("'test_google_writer_apply_result_integrity_v5'", exact)
        self.assertNotIn("'test_google_writer_apply_result_integrity_v6'", exact)


if __name__ == '__main__':
    unittest.main()
