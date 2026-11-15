"""Current-source integrity overlay v8 for detailed, read-only continuation audit checks."""
import hashlib
import json
from pathlib import Path
import re
import unittest


MANIFEST = Path('validation/local_release_20261115/google_writer_apply_result_v8.json')
MANIFEST_SHA256 = "f52397e93ef6ecfd1f772d26b0b6562c48169a272ab17917f9c4fc7456c0fbe5"
TEST_FILE = 'test_google_writer_apply_result_integrity_v8.py'
ROOT = Path(__file__).resolve().parent


def canonical(data):
    return data.replace(b'\r\n', b'\n')


def canonical_self(data):
    return re.sub(rb'(?m)^MANIFEST_SHA256 = "(?:<manifest-sha256>|[0-9a-f]{64})"$',
                  b'MANIFEST_SHA256 = "<manifest-sha256>"', canonical(data))


class SavedContinuationAuditIntegrityV8(unittest.TestCase):
    def test_current_audit_sources_and_tests_are_pinned(self):
        raw = canonical((ROOT / MANIFEST).read_bytes())
        self.assertEqual(hashlib.sha256(raw).hexdigest(), MANIFEST_SHA256)
        manifest = json.loads(raw.decode('utf-8'))
        self.assertEqual(manifest['contract'], 'pqm-sandbox-saved-continuation-audit')
        self.assertEqual(manifest['version'], 8)
        self.assertEqual(manifest['baseline'], '8bf5fb0188bebf6f2b35583ec018848c914b714c')
        self.assertEqual(set(manifest['scope']), set(manifest['files']))
        expected = {
            'google_writer_apply_result.js', 'google_writer_execution.py',
            'test_google_writer_saved_continuation_audit.py',
            'validation/google_writer_apply_result_ui.test.cjs',
            'test_release_gate_infrastructure.py', 'validation/run_local_release.py',
            '.github/workflows/release-checks.yml', TEST_FILE,
        }
        self.assertEqual(set(manifest['files']), expected)
        for relative, digest in manifest['files'].items():
            data = (ROOT / relative).read_bytes()
            normalized = canonical_self(data) if relative == TEST_FILE else canonical(data)
            with self.subTest(path=relative):
                self.assertEqual(hashlib.sha256(normalized).hexdigest(), digest)

    def test_saved_continuation_audit_v1_to_v7_manifests_remain_pinned(self):
        manifest = json.loads(canonical((ROOT / MANIFEST).read_bytes()).decode('utf-8'))
        expected = {
            'validation/local_release_20261115/google_writer_apply_result_v7.json':
                'd933c14848be3e0bdde412c1b45c4dc6b5736bdb39325d29b1afd1a1d024fabb',
            'validation/local_release_20261115/google_writer_apply_result_v6.json':
                '65b509634de88ede330bd4202107de023d9e0c62cfb4487a34bc919aa7f4d802',
            'validation/local_release_20261115/google_writer_apply_result_v5.json':
                'd029a33dec13613634f2704ecaa0bf76038a01435ecf6d67f3d17585ee16f45d',
            'validation/local_release_20261113/google_writer_append_continuation_v1.json':
                'e2569da64bcc83e18b5223d9cbfeccab46ea7524cfa2f41ed1a452f929922aa2',
            'validation/local_release_20261113/google_writer_append_continuation_v2.json':
                '2fb4d7124cdd7039ff07c87b275551e678afafb4aa807b7b0f0c5536e9bf2089',
            'validation/local_release_20261113/google_writer_append_continuation_v3.json':
                'ad378d8717b936a01671eb9837b842946f5636d74663f2382e23c24f4dbb7e63',
            'validation/local_release_20261113/google_writer_append_continuation_v4.json':
                '644737f2c2772e21b7c81f571678bec494641a336703375aa40b3988e1944b92',
        }
        self.assertEqual(manifest['preserved_manifests'], expected)
        for relative, digest in expected.items():
            with self.subTest(manifest=relative):
                self.assertEqual(hashlib.sha256(canonical((ROOT / relative).read_bytes())).hexdigest(), digest)

    def test_release_gate_runs_v7_on_its_snapshot_and_v8_on_candidate(self):
        workflow = (ROOT / '.github/workflows/release-checks.yml').read_text(encoding='utf-8')
        self.assertIn('git archive 8bf5fb0188bebf6f2b35583ec018848c914b714c', workflow)
        self.assertIn('test_google_writer_apply_result_integrity_v7)', workflow)
        self.assertIn('test_google_writer_apply_result_integrity_v8', workflow)
        self.assertLess(workflow.index('test_google_writer_apply_result_integrity_v7)'),
                        workflow.index('test_google_writer_apply_result_integrity_v8'))
        runner = (ROOT / 'validation/run_local_release.py').read_text(encoding='utf-8')
        exact = runner.split('EXACT_TREE_OVERLAY_MODULES', 1)[1].split('}', 1)[0]
        self.assertIn("'test_google_writer_apply_result_integrity_v7'", exact)
        self.assertIn("'test_google_writer_apply_result_integrity_v8'", exact)

    def test_diagnostics_are_read_only_and_surface_each_blocking_predicate(self):
        source = (ROOT / 'google_writer_execution.py').read_text(encoding='utf-8')
        audit = source.split('def audit_saved_append_continuation(', 1)[1].split(
            '\ndef claim_interrupted_append_chunk_recovery', 1)[0]
        for name in ('plan_matches', 'preserved_match', 'source_chunks_unresolved',
                     'continuation_chunks_unresolved', 'additional_saved_previews',
                     'continuation_preview', 'linked_runs_unresolved', 'competing_attempts'):
            self.assertIn("'" + name + "'", source)
        self.assertIn('checks=checks', audit)
        self.assertIn('_saved_continuation_audit_checks_block(checks)', audit)
        self.assertIn('mode=ro', audit)
        self.assertIn('diagnose_append_only_plan(', audit)
        self.assertIn('allow_closed_unknown=True', audit)
        self.assertNotIn('prepare_append_continuation_preview(', audit)
        self.assertNotIn('apply_append_continuation(', audit)
        self.assertNotIn('resume_append_continuation(', audit)
        ui = (ROOT / 'google_writer_apply_result.js').read_text(encoding='utf-8')
        self.assertIn('Конкретні умови BLOCKED', ui)
        self.assertIn('checks:safeAuditChecks(value.checks)', ui)
        self.assertIn('savedAuditText()', ui)


if __name__ == '__main__':
    unittest.main()
