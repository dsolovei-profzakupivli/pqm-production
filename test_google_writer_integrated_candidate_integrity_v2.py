"""Additive integrity contract for the corrected integrated Writer/UI candidate."""
import hashlib
import json
from pathlib import Path
import re
import unittest


MANIFEST = Path('validation/local_release_20261116/pqm_sync_ui_integrated_v2.json')
MANIFEST_SHA256 = '3c3f3a38ac7678d93ea08ed72ae1bc0be7e7147a51a3832ab79d91033ff26287'
TEST_FILE = 'test_google_writer_integrated_candidate_integrity_v2.py'
V1_TEST_FILE = 'test_google_writer_integrated_candidate_integrity_v1.py'
ROOT = Path(__file__).resolve().parent
BASELINE = 'b5a2fd076505e55ac2f8fbcc1eefacc80e845da7'
PREVIOUS_CANDIDATE = '3eda8169d8dae0d76bf14b276c16e6773dd746d6'
V1_MANIFEST = Path('validation/local_release_20261116/pqm_sync_ui_integrated_v1.json')
V1_SCOPE = set(json.loads((ROOT / V1_MANIFEST).read_text(encoding='utf-8'))['scope'])
EXPECTED_SCOPE = V1_SCOPE | {
    '.dockerignore',
    'Dockerfile',
    V1_MANIFEST.as_posix(),
    'validation/appeals_justification_browser.cjs',
    'validation/run_integrated_writer_ui_v1_history.py',
    TEST_FILE,
}


def canonical(data):
    return data.replace(b'\r\n', b'\n')


def canonical_self(data):
    return re.sub(
        rb"(?m)^MANIFEST_SHA256 = '(?:<manifest-sha256>|[0-9a-f]{64})'$",
        b"MANIFEST_SHA256 = '<manifest-sha256>'",
        canonical(data),
    )


class GoogleWriterIntegratedCandidateIntegrityV2(unittest.TestCase):
    def test_manifest_pins_all_integrated_sources_and_unchanged_v1_files(self):
        raw = canonical((ROOT / MANIFEST).read_bytes())
        self.assertEqual(hashlib.sha256(raw).hexdigest(), MANIFEST_SHA256)
        manifest = json.loads(raw.decode('utf-8'))
        self.assertEqual(manifest['contract'], 'pqm-google-writer-sync-ui-integrated')
        self.assertEqual(manifest['version'], 2)
        self.assertEqual(manifest['baseline'], BASELINE)
        self.assertEqual(manifest['previous_candidate_commit'], PREVIOUS_CANDIDATE)
        self.assertEqual(set(manifest['scope']), EXPECTED_SCOPE)
        self.assertEqual(set(manifest['files']), EXPECTED_SCOPE)
        for relative, expected in manifest['files'].items():
            data = (ROOT / relative).read_bytes()
            normalized = canonical_self(data) if relative in {V1_TEST_FILE, TEST_FILE} else canonical(data)
            with self.subTest(path=relative):
                self.assertEqual(hashlib.sha256(normalized).hexdigest(), expected)

    def test_active_renderer_places_supplier_filtered_marketplace_link_in_heading(self):
        app = (ROOT / 'app.js').read_text(encoding='utf-8')
        helper_boundary = app.index('function violationObjectLinks(')
        renderer_start = app.index('violationDetailHtml=function(item)', helper_boundary)
        renderer_end = app.index('\nconst violationDetailHtmlBase', renderer_start)
        renderer = app[renderer_start:renderer_end]
        heading_start = renderer.index('<h3 class="violation-platform-heading"')
        helper_call = renderer.index('${zakupivliComplaintLink(item)}', heading_start)
        heading_end = renderer.index('</h3>', heading_start)
        self.assertLess(heading_start, helper_call)
        self.assertLess(helper_call, heading_end)
        heading = renderer[heading_start:heading_end]
        self.assertNotIn('requestViolationUrl(item)', heading)

        helpers = list(re.finditer(r'function zakupivliComplaintLink\(item\)\{', app))
        self.assertTrue(helpers, 'marketplace link helper must exist')
        active_helper_start = helpers[-1].start()
        active_helper_end = app.index('\nfunction requestBlockingBadge(', active_helper_start)
        active_helper = app[active_helper_start:active_helper_end]
        self.assertIn('item?.defendant_code', active_helper)
        self.assertNotIn('item?.author_code', active_helper)
        self.assertNotIn('item?.id', active_helper)
        self.assertIn('/complaints/list', active_helper)
        self.assertIn('?defendant_srn=', active_helper)

    def test_dialog_copy_and_close_controls_remain_available(self):
        index = (ROOT / 'index.html').read_text(encoding='utf-8')
        dialog = re.search(
            r'<dialog id="requestDetailsDialog"[\s\S]*?</dialog>', index
        )
        self.assertIsNotNone(dialog)
        self.assertIn('requestCopyJustification', dialog.group(0))
        self.assertIn('class="dialog-close"', dialog.group(0))

    def test_v1_snapshot_and_v2_current_checkout_are_routed_separately(self):
        workflow = (ROOT / '.github/workflows/release-checks.yml').read_text(encoding='utf-8')
        runner_path = 'validation/run_integrated_writer_ui_v1_history.py'
        v1_module = 'test_google_writer_integrated_candidate_integrity_v1'
        v2_module = 'test_google_writer_integrated_candidate_integrity_v2'
        self.assertIn(runner_path, workflow)
        self.assertIn(v2_module, workflow)
        self.assertNotIn(v1_module, workflow)
        self.assertLess(workflow.index(runner_path), workflow.index(v2_module))
        self.assertLess(workflow.index(v2_module), workflow.index('Install Playwright and Chromium'))

        history_runner = (ROOT / runner_path).read_text(encoding='utf-8')
        self.assertIn(PREVIOUS_CANDIDATE, history_runner)
        self.assertIn("'git', 'archive', '--format=zip'", history_runner)
        self.assertIn(v1_module, history_runner)

        local_runner = (ROOT / 'validation/run_local_release.py').read_text(encoding='utf-8')
        self.assertIn(v1_module, local_runner.split('EXACT_TREE_OVERLAY_MODULES={', 1)[1]
                      .split('}', 1)[0])
        self.assertIn(v2_module, local_runner)
        self.assertIn(runner_path, local_runner)

        for current_edr_test in (
            'validation.local_release_20260911.test_edr_sync_v2',
            'validation.local_release_20260911.test_permanent_edr_sync_safety',
            'validation.local_release_20260911.test_sandbox_edr_review',
        ):
            self.assertIn(current_edr_test, workflow)

        dockerfile = (ROOT / 'Dockerfile').read_text(encoding='utf-8')
        dockerignore = (ROOT / '.dockerignore').read_text(encoding='utf-8')
        self.assertIn('COPY . .', dockerfile)
        self.assertNotIn('validation/fixtures/', dockerignore)
        self.assertIn("'pqm_sync_ui_integrated_v1_3eda816.zip'", local_runner)


if __name__ == '__main__':
    unittest.main()
