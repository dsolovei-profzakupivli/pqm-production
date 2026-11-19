"""Current integrated Writer/UI contract v4; earlier contracts use snapshots."""
import hashlib
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parent
MANIFEST = Path('validation/local_release_20261116/pqm_sync_ui_integrated_v4.json')
MANIFEST_SHA256 = '9282240bb39b4f97b551b6b0c60756d21b9b0d389bdcc50061369357a175d5e9'
TEST_FILE = 'test_google_writer_integrated_candidate_integrity_v4.py'
PREVIOUS_MANIFEST = Path('validation/local_release_20261116/pqm_sync_ui_integrated_v3.json')
PREVIOUS_TEST = 'test_google_writer_integrated_candidate_integrity_v3.py'
PREVIOUS_SNAPSHOT = '8c6ba07372196b1919a88beb7da3078e6c53d4d0'
PREVIOUS_MANIFEST_SHA256 = '7324a8ac548e57c9cd2fe5f20e82a9381dbe581cb758e3a28904d7f3d511b9d7'


def canonical(data):
    return data.replace(b'\r\n', b'\n')


def canonical_self(data):
    return re.sub(
        rb"(?m)^MANIFEST_SHA256 = '(?:<manifest-sha256>|[0-9a-f]{64})'$",
        b"MANIFEST_SHA256 = '<manifest-sha256>'",
        canonical(data),
    )


class GoogleWriterIntegratedCandidateIntegrityV4(unittest.TestCase):
    def test_v4_manifest_pins_current_candidate_and_preserves_v1_v3_contracts(self):
        raw = canonical((ROOT / MANIFEST).read_bytes())
        self.assertEqual(hashlib.sha256(raw).hexdigest(), MANIFEST_SHA256)
        manifest = json.loads(raw.decode('utf-8'))
        previous_raw = canonical((ROOT / PREVIOUS_MANIFEST).read_bytes())
        self.assertEqual(hashlib.sha256(previous_raw).hexdigest(), PREVIOUS_MANIFEST_SHA256)
        previous = json.loads(previous_raw.decode('utf-8'))
        self.assertEqual(manifest['contract'], 'pqm-google-writer-sync-ui-integrated')
        self.assertEqual(manifest['version'], 4)
        self.assertEqual(manifest['previous_candidate_commit'], PREVIOUS_SNAPSHOT)
        expected_scope = set(previous['scope']) | {
            PREVIOUS_MANIFEST.as_posix(),
            'validation/run_integrated_writer_ui_v3_history.py',
            TEST_FILE,
        }
        self.assertEqual(set(manifest['scope']), expected_scope)
        self.assertEqual(set(manifest['files']), expected_scope)
        self.assertEqual(
            hashlib.sha256(canonical_self((ROOT / PREVIOUS_TEST).read_bytes())).hexdigest(),
            previous['files'][PREVIOUS_TEST],
        )
        for relative, expected in manifest['files'].items():
            data = (ROOT / relative).read_bytes()
            normalized = canonical_self(data) if relative == TEST_FILE else canonical(data)
            with self.subTest(path=relative):
                self.assertEqual(hashlib.sha256(normalized).hexdigest(), expected)

    def test_dialog_marketplace_action_and_copy_close_order_are_preserved(self):
        app = (ROOT / 'app.js').read_text(encoding='utf-8')
        renderer_start = app.index('violationDetailHtml=function(item)', app.index('function violationObjectLinks('))
        renderer_end = app.index('\nconst violationDetailHtmlBase', renderer_start)
        self.assertNotIn('zakupivliComplaintLink(item)', app[renderer_start:renderer_end])
        helper_start = app.index('function zakupivliComplaintLink(item)')
        helper_end = app.index('\nfunction requestBlockingBadge(', helper_start)
        helper = app[helper_start:helper_end]
        label = 'Звернення щодо постачальника на Zakupivli.Pro'
        self.assertIn(f"label='{label}'", helper)
        self.assertIn('aria-label="${label}" title="${label}"', helper)
        self.assertIn('/cabinet/ecatalog/gov/complaints/list', helper)
        self.assertIn('?defendant_srn=${encodeURIComponent(supplierCode)}', helper)

        index = (ROOT / 'index.html').read_text(encoding='utf-8')
        dialog = re.search(r'<dialog id="requestDetailsDialog"[\s\S]*?</dialog>', index)
        self.assertIsNotNone(dialog)
        header = dialog.group(0)
        self.assertRegex(
            header,
            r'id="requestHeaderDecision"[\s\S]*?id="requestCopyJustification"[\s\S]*?id="requestHeaderMarketplace"[\s\S]*?class="dialog-close"',
        )
        styles = (ROOT / 'styles.css').read_text(encoding='utf-8')
        self.assertIn('#requestHeaderMarketplace{display:inline-flex;flex:0 0 auto;margin-left:31px}', styles)

    def test_all_integrated_history_runners_are_in_the_delivered_package(self):
        for relative in (
            'validation/run_integrated_writer_ui_v1_history.py',
            'validation/run_integrated_writer_ui_v2_history.py',
            'validation/run_integrated_writer_ui_v3_history.py',
        ):
            with self.subTest(path=relative):
                self.assertTrue((ROOT / relative).is_file())

    def test_ci_routes_v1_v2_v3_to_history_and_v4_to_current_checkout(self):
        workflow = (ROOT / '.github/workflows/release-checks.yml').read_text(encoding='utf-8')
        self.assertIn('PQM_INTEGRATED_V1_ARCHIVE_OUT=validation/fixtures/pqm_sync_ui_integrated_v1_3eda816.zip', workflow)
        self.assertIn('PQM_INTEGRATED_V2_ARCHIVE_OUT=validation/fixtures/pqm_sync_ui_integrated_v2_0d7e059.zip', workflow)
        self.assertIn('PQM_INTEGRATED_V3_ARCHIVE_OUT=validation/fixtures/pqm_sync_ui_integrated_v3_8c6ba07.zip', workflow)
        self.assertIn('test_google_writer_integrated_candidate_integrity_v4', workflow)
        self.assertNotIn('test_google_writer_integrated_candidate_integrity_v3', workflow)
        runner = (ROOT / 'validation/run_integrated_writer_ui_v3_history.py').read_text(encoding='utf-8')
        self.assertIn(PREVIOUS_SNAPSHOT, runner)
        self.assertIn('test_google_writer_integrated_candidate_integrity_v3', runner)
        local_runner = (ROOT / 'validation/run_local_release.py').read_text(encoding='utf-8')
        self.assertIn('run_integrated_writer_ui_v3_history.py', local_runner)
        self.assertIn('test_google_writer_integrated_candidate_integrity_v4', local_runner)
        infrastructure = (ROOT / 'test_release_gate_infrastructure.py').read_text(encoding='utf-8')
        self.assertIn('test_integrated_history_runners_are_present_in_the_delivered_test_package', infrastructure)


if __name__ == '__main__':
    unittest.main()
