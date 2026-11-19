"""Current additive integrity contract for the synchronized Writer + UI candidate."""
import hashlib
import json
from pathlib import Path
import re
import unittest


MANIFEST = Path('validation/local_release_20261116/pqm_sync_ui_integrated_v1.json')
MANIFEST_SHA256 = 'cec0c8c637a51e021c21532a76e2b8d1ebbd4990489e0e920229e33bb417b3a9'
TEST_FILE = 'test_google_writer_integrated_candidate_integrity_v1.py'
ROOT = Path(__file__).resolve().parent
BASELINE = 'b5a2fd076505e55ac2f8fbcc1eefacc80e845da7'
PROTECTION_SNAPSHOT = '9b38a258c0d279f33541dac6e95d12d3057a9b70'
EXPECTED_SCOPE = {
    '.github/workflows/release-checks.yml',
    'app.js',
    'edr_sync_v2.py',
    'google_writer_apply_result.js',
    'google_writer_execution.py',
    'google_writer_ui.js',
    'history_ui.js',
    'index.html',
    'modules.css',
    'queue_statistics_ui.js',
    'sandbox_edr_review.py',
    'server.py',
    'styles.css',
    'scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxPreviewDependencies.gs',
    'scripts/pqm-google-writer/sandbox-full-apply.test.cjs',
    'scripts/pqm-google-writer/update-append-business-matrix.test.cjs',
    'test_google_writer_append_continuation.py',
    TEST_FILE,
    'test_google_writer_update_append_v2_integrity.py',
    'test_google_writer_update_append_v3_integrity.py',
    'test_release_gate_infrastructure.py',
    'validation/google_writer_apply_result_ui.test.cjs',
    'validation/google_writer_continuation_preview_ui.test.cjs',
    'validation/local_release_20260911/google_writer_update_append_v2.json',
    'validation/local_release_20260911/google_writer_update_append_v3.json',
    'validation/local_release_20260911/test_edr_sync_v2.py',
    'validation/local_release_20260911/test_permanent_edr_sync_safety.py',
    'validation/local_release_20260911/test_sandbox_edr_review.py',
    'validation/queue_statistics_ui.test.cjs',
    'validation/run_local_release.py',
}


def canonical(data):
    return data.replace(b'\r\n', b'\n')


def canonical_self(data):
    return re.sub(rb"(?m)^MANIFEST_SHA256 = '(?:<manifest-sha256>|[0-9a-f]{64})'$",
                  b"MANIFEST_SHA256 = '<manifest-sha256>'", canonical(data))


class GoogleWriterIntegratedCandidateIntegrityV1(unittest.TestCase):
    def test_manifest_pins_exact_integrated_sources_and_tests(self):
        raw = canonical((ROOT / MANIFEST).read_bytes())
        self.assertEqual(hashlib.sha256(raw).hexdigest(), MANIFEST_SHA256)
        manifest = json.loads(raw.decode('utf-8'))
        self.assertEqual(manifest['contract'], 'pqm-google-writer-sync-ui-integrated')
        self.assertEqual(manifest['version'], 1)
        self.assertEqual(manifest['baseline'], BASELINE)
        self.assertEqual(manifest['writer_protection_snapshot'], PROTECTION_SNAPSHOT)
        self.assertEqual(set(manifest['scope']), EXPECTED_SCOPE)
        self.assertEqual(set(manifest['files']), EXPECTED_SCOPE)
        for relative, expected in manifest['files'].items():
            data = (ROOT / relative).read_bytes()
            normalized = canonical_self(data) if relative == TEST_FILE else canonical(data)
            with self.subTest(path=relative):
                self.assertEqual(hashlib.sha256(normalized).hexdigest(), expected)

    def test_continuation_v2_parent_exclusions_and_projection_are_checked_before_claim(self):
        execution = (ROOT / 'google_writer_execution.py').read_text(encoding='utf-8')
        start = execution.index('def validate_append_continuation_v2_live_preview(')
        end = execution.index('\ndef validate_append_continuation_closed(', start)
        validator = execution[start:end]
        for required in (
            "live.get('digest')!=snapshot.get('plan_digest')",
            "live_details.get('source_digest')!=saved_details.get('source_digest')",
            "expected_full_counts={'append':251,'update':2,'conflict':2,'error':0}",
            '_append_continuation_v2_source_exclusions_from_db',
            '_append_continuation_v2_assert_disjoint',
            '_preview_details_digest(live_core)!=_preview_details_digest(saved_core)',
        ):
            self.assertIn(required, validator)
        server = (ROOT / 'server.py').read_text(encoding='utf-8')
        route = server[server.index("if parsed.path in {'/api/google-writer/preview','/api/google-writer/apply'}:"):]
        self.assertLess(route.index('validate_append_continuation_v2_live_preview('),
                        route.index('google_writer_execution.claim_run('))

    def test_apply_lock_stays_closed_after_unknown_result_until_verified_read_only_no_run(self):
        apply_result = (ROOT / 'google_writer_apply_result.js').read_text(encoding='utf-8')
        self.assertIn('applyLockMode=null,applyRequestInFlight=false', apply_result)
        self.assertIn("if(isApply&&(applyLockMode==='unknown'||applyLockMode==='started'&&continuation))", apply_result)
        self.assertIn("explicitUserCheck&&applyLockMode==='unknown'", apply_result)
        self.assertIn('const noRunConfirmed=diagnostic.status===\'preview_saved\'', apply_result)
        self.assertIn('canApplyContinuation:requestId=>applyLockMode===null&&!applyRequestInFlight', apply_result)
        ui = (ROOT / 'google_writer_ui.js').read_text(encoding='utf-8')
        guard = ui.index('PqmGoogleWriterApplyResult?.canApplyContinuation?.(preview.request_id)===false')
        post = ui.index("request(`${API}/google-writer/apply`", guard)
        self.assertLess(guard, post)

    def test_historical_v5_v10_route_to_exact_9b38_snapshot_and_current_overlays_run_current(self):
        workflow = (ROOT / '.github/workflows/release-checks.yml').read_text(encoding='utf-8')
        self.assertIn(f'git archive {PROTECTION_SNAPSHOT}', workflow)
        route = workflow.split('writer_v5_v10_snapshot=', 1)[1].split(
            'test_google_writer_integrated_candidate_integrity_v1', 1)[0]
        self.assertIn('(cd "$writer_v5_v10_snapshot"', route)
        self.assertIn('test_google_writer_append_continuation_integrity_v5', route)
        self.assertIn('test_google_writer_apply_result_integrity_v10', route)
        self.assertIn('test_google_writer_integrated_candidate_integrity_v1', workflow)
        self.assertIn('test_google_writer_update_append_v2_integrity', workflow)
        self.assertIn('test_google_writer_update_append_v3_integrity', workflow)
        runner = (ROOT / 'validation/run_local_release.py').read_text(encoding='utf-8')
        exact = runner.split('EXACT_TREE_OVERLAY_MODULES', 1)[1].split('}', 1)[0]
        self.assertIn("'test_google_writer_append_continuation_integrity_v5'", exact)
        self.assertIn("'test_google_writer_apply_result_integrity_v10'", exact)
        self.assertNotIn("'test_google_writer_integrated_candidate_integrity_v1'", exact)


if __name__ == '__main__':
    unittest.main()
