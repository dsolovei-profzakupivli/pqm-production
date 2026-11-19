"""Current integrated Writer/UI contract v3; v1 and v2 run on snapshots."""
import hashlib
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parent
MANIFEST = Path('validation/local_release_20261116/pqm_sync_ui_integrated_v3.json')
MANIFEST_SHA256 = '7324a8ac548e57c9cd2fe5f20e82a9381dbe581cb758e3a28904d7f3d511b9d7'
TEST_FILE = 'test_google_writer_integrated_candidate_integrity_v3.py'
PREVIOUS_MANIFEST = Path('validation/local_release_20261116/pqm_sync_ui_integrated_v2.json')
PREVIOUS_TEST = 'test_google_writer_integrated_candidate_integrity_v2.py'
PREVIOUS_SNAPSHOT = '0d7e05984fb9b1fc7276b4cc1d8176dec383ef08'
PREVIOUS_MANIFEST_SHA256 = '3c3f3a38ac7678d93ea08ed72ae1bc0be7e7147a51a3832ab79d91033ff26287'
V1_SNAPSHOT = '3eda8169d8dae0d76bf14b276c16e6773dd746d6'


def canonical(data):
    return data.replace(b'\r\n', b'\n')


def canonical_self(data):
    return re.sub(
        rb"(?m)^MANIFEST_SHA256 = '(?:<manifest-sha256>|[0-9a-f]{64})'$",
        b"MANIFEST_SHA256 = '<manifest-sha256>'",
        canonical(data),
    )


class GoogleWriterIntegratedCandidateIntegrityV3(unittest.TestCase):
    def test_v3_manifest_pins_current_candidate_and_preserves_v1_v2_contracts(self):
        raw = canonical((ROOT / MANIFEST).read_bytes())
        self.assertEqual(hashlib.sha256(raw).hexdigest(), MANIFEST_SHA256)
        manifest = json.loads(raw.decode('utf-8'))
        previous = json.loads((ROOT / PREVIOUS_MANIFEST).read_text(encoding='utf-8'))
        self.assertEqual(manifest['contract'], 'pqm-google-writer-sync-ui-integrated')
        self.assertEqual(manifest['version'], 3)
        self.assertEqual(manifest['previous_candidate_commit'], PREVIOUS_SNAPSHOT)
        expected_scope = set(previous['scope']) | {
            PREVIOUS_MANIFEST.as_posix(),
            '.github/workflows/release-checks.yml',
            'test_release_gate_infrastructure.py',
            'validation/run_local_release.py',
            'validation/run_integrated_writer_ui_v2_history.py',
            TEST_FILE,
        }
        self.assertEqual(set(manifest['scope']), expected_scope)
        self.assertEqual(set(manifest['files']), expected_scope)
        self.assertEqual(manifest['files'][PREVIOUS_TEST],
                         hashlib.sha256(canonical((ROOT / PREVIOUS_TEST).read_bytes())).hexdigest())
        self.assertEqual(hashlib.sha256(canonical((ROOT / PREVIOUS_MANIFEST).read_bytes())).hexdigest(),
                         PREVIOUS_MANIFEST_SHA256)
        for relative, expected in manifest['files'].items():
            data = (ROOT / relative).read_bytes()
            normalized = canonical_self(data) if relative == TEST_FILE else canonical(data)
            with self.subTest(path=relative):
                self.assertEqual(hashlib.sha256(normalized).hexdigest(), expected)

    def test_marketplace_action_is_in_dialog_header_after_copy_before_close(self):
        app = (ROOT / 'app.js').read_text(encoding='utf-8')
        renderer_start = app.index('violationDetailHtml=function(item)', app.index('function violationObjectLinks('))
        renderer_end = app.index('\nconst violationDetailHtmlBase', renderer_start)
        renderer = app[renderer_start:renderer_end]
        self.assertNotIn('zakupivliComplaintLink(item)', renderer)
        helper_start = app.index('function zakupivliComplaintLink(item)')
        helper_end = app.index('\nfunction requestBlockingBadge(', helper_start)
        helper = app[helper_start:helper_end]
        label = 'Звернення щодо постачальника на Zakupivli.Pro'
        self.assertIn(f"label='{label}'", helper)
        self.assertIn('aria-label="${label}" title="${label}"', helper)
        self.assertIn("/cabinet/ecatalog/gov/complaints/list", helper)
        self.assertIn("?defendant_srn=${encodeURIComponent(supplierCode)}", helper)

        index = (ROOT / 'index.html').read_text(encoding='utf-8')
        dialog = re.search(r'<dialog id="requestDetailsDialog"[\s\S]*?</dialog>', index)
        self.assertIsNotNone(dialog)
        header = dialog.group(0)
        self.assertRegex(header, r'<div><h2 id="requestDetailsTitle">[\s\S]*?</h2><p id="requestDetailsSubtitle">[\s\S]*?</p></div><div class="appeal-header-tools">')
        self.assertRegex(header, r'id="requestCopyJustification"[\s\S]*?id="requestHeaderMarketplace"[\s\S]*?class="dialog-close"')
        styles = (ROOT / 'styles.css').read_text(encoding='utf-8')
        self.assertIn('.appeal-header-decision,.appeal-header-actions{display:flex;align-items:center;gap:8px}', styles)
        self.assertIn('#requestHeaderMarketplace{display:inline-flex;flex:0 0 auto;margin-left:31px}', styles)

    def test_history_runners_and_current_overlay_are_mandatory(self):
        workflow = (ROOT / '.github/workflows/release-checks.yml').read_text(encoding='utf-8')
        self.assertIn('PQM_INTEGRATED_V1_ARCHIVE_OUT=validation/fixtures/pqm_sync_ui_integrated_v1_3eda816.zip', workflow)
        self.assertIn('PQM_INTEGRATED_V2_ARCHIVE_OUT=validation/fixtures/pqm_sync_ui_integrated_v2_0d7e059.zip', workflow)
        self.assertIn('test_google_writer_integrated_candidate_integrity_v3', workflow)
        self.assertNotIn('test_google_writer_integrated_candidate_integrity_v2', workflow)
        v2_runner = (ROOT / 'validation/run_integrated_writer_ui_v2_history.py').read_text(encoding='utf-8')
        self.assertIn(PREVIOUS_SNAPSHOT, v2_runner)
        self.assertIn(PREVIOUS_TEST[:-3], v2_runner)
        infra = (ROOT / 'test_release_gate_infrastructure.py').read_text(encoding='utf-8')
        self.assertIn('test_workflow_routes_historical_and_current_integrity_checks', infra)
        local_runner = (ROOT / 'validation/run_local_release.py').read_text(encoding='utf-8')
        self.assertIn('run_integrated_writer_ui_v1_history.py', local_runner)
        self.assertIn('run_integrated_writer_ui_v2_history.py', local_runner)
        self.assertIn('test_google_writer_integrated_candidate_integrity_v3', local_runner)


if __name__ == '__main__':
    unittest.main()
