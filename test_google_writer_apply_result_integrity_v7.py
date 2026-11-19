"""Current-source integrity overlay for read-only saved continuation audit."""
import hashlib
import json
from pathlib import Path
import re
import unittest


MANIFEST = Path('validation/local_release_20261115/google_writer_apply_result_v7.json')
MANIFEST_SHA256 = "d933c14848be3e0bdde412c1b45c4dc6b5736bdb39325d29b1afd1a1d024fabb"
TEST_FILE = 'test_google_writer_apply_result_integrity_v7.py'
ROOT = Path(__file__).resolve().parent


def canonical(data):
    return data.replace(b'\r\n', b'\n')


def canonical_self(data):
    return re.sub(rb'(?m)^MANIFEST_SHA256 = "(?:<manifest-sha256>|[0-9a-f]{64})"$',
                  b'MANIFEST_SHA256 = "<manifest-sha256>"', canonical(data))


class SavedContinuationAuditIntegrityV7(unittest.TestCase):
    def test_current_audit_sources_and_tests_are_pinned(self):
        raw = canonical((ROOT / MANIFEST).read_bytes())
        self.assertEqual(hashlib.sha256(raw).hexdigest(), MANIFEST_SHA256)
        manifest = json.loads(raw.decode('utf-8'))
        self.assertEqual(manifest['contract'], 'pqm-sandbox-saved-continuation-audit')
        self.assertEqual(manifest['version'], 7)
        self.assertEqual(manifest['baseline'], '86b6ad82105fdcd7fa530a872943525af812ec47')
        self.assertEqual(set(manifest['scope']), set(manifest['files']))
        expected = {
            'google_writer_apply_result.js', 'google_writer_execution.py', 'index.html', 'modules.css',
            'server.py', 'validation/google_writer_apply_result_ui.test.cjs',
            'test_google_writer_saved_continuation_audit.py', 'test_release_gate_infrastructure.py',
            'validation/run_local_release.py', '.github/workflows/release-checks.yml', TEST_FILE,
        }
        self.assertEqual(set(manifest['files']), expected)
        for relative, digest in manifest['files'].items():
            data = (ROOT / relative).read_bytes()
            normalized = canonical_self(data) if relative == TEST_FILE else canonical(data)
            with self.subTest(path=relative):
                self.assertEqual(hashlib.sha256(normalized).hexdigest(), digest)

    def test_historical_overlays_v1_to_v6_remain_byte_pinned(self):
        manifest = json.loads(canonical((ROOT / MANIFEST).read_bytes()).decode('utf-8'))
        expected = {
            'validation/local_release_20261115/google_writer_apply_result_v6.json',
            'validation/local_release_20261115/google_writer_apply_result_v5.json',
            'validation/local_release_20261113/google_writer_append_continuation_v1.json',
            'validation/local_release_20261113/google_writer_append_continuation_v2.json',
            'validation/local_release_20261113/google_writer_append_continuation_v3.json',
            'validation/local_release_20261113/google_writer_append_continuation_v4.json',
        }
        self.assertEqual(set(manifest['preserved_manifests']), expected)
        for relative, digest in manifest['preserved_manifests'].items():
            with self.subTest(manifest=relative):
                self.assertEqual(hashlib.sha256(canonical((ROOT / relative).read_bytes())).hexdigest(), digest)

    def test_release_gate_runs_v6_on_its_baseline_and_v7_on_current_sources(self):
        workflow = (ROOT / '.github/workflows/release-checks.yml').read_text(encoding='utf-8')
        self.assertIn('git archive 86b6ad82105fdcd7fa530a872943525af812ec47', workflow)
        self.assertIn('test_google_writer_apply_result_integrity_v6)', workflow)
        self.assertIn('test_google_writer_apply_result_integrity_v7', workflow)
        self.assertLess(workflow.index('test_google_writer_apply_result_integrity_v6)'),
                        workflow.index('test_google_writer_apply_result_integrity_v7'))
        runner = (ROOT / 'validation/run_local_release.py').read_text(encoding='utf-8')
        exact = runner.split('EXACT_TREE_OVERLAY_MODULES', 1)[1].split('}', 1)[0]
        self.assertIn("'test_google_writer_apply_result_integrity_v6'", exact)
        self.assertNotIn("'test_google_writer_apply_result_integrity_v7'", exact)

    def test_audit_contract_is_read_only_and_uses_existing_signed_diagnostic(self):
        source = (ROOT / 'google_writer_execution.py').read_text(encoding='utf-8')
        audit = source.split('def audit_saved_append_continuation(', 1)[1].split('\ndef claim_interrupted_append_chunk_recovery', 1)[0]
        self.assertIn('mode=ro', audit)
        self.assertIn('diagnose_append_only_plan(', audit)
        self.assertIn('audit_only=True', audit)
        self.assertIn('include_target_statuses=True', audit)
        self.assertIn('allow_closed_unknown=True', audit)
        self.assertIn("'VERIFIED'", audit)
        self.assertIn("'BLOCKED'", audit)
        self.assertIn("'UNAVAILABLE'", audit)
        self.assertNotIn('prepare_append_continuation_preview(', audit)
        self.assertNotIn('apply_append_continuation(', audit)
        self.assertNotIn('resume_append_continuation(', audit)
