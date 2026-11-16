"""Current integrated Writer/UI contract v6; v5 stays an immutable snapshot."""
import hashlib
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parent
MANIFEST = Path('validation/local_release_20261116/pqm_sync_ui_integrated_v6.json')
MANIFEST_SHA256 = '1c1c1a201f7a87a3fc44c53ecd02575dce5165f3f670e6a812d8101750376583'
TEST_FILE = 'test_google_writer_integrated_candidate_integrity_v6.py'
PREVIOUS_MANIFEST = Path('validation/local_release_20261116/pqm_sync_ui_integrated_v5.json')
PREVIOUS_TEST = 'test_google_writer_integrated_candidate_integrity_v5.py'
PREVIOUS_SNAPSHOT = 'cd01e1376114781e43d408b5b83ee15e22050a53'
PREVIOUS_MANIFEST_SHA256 = '71a25437255990abed106836cdf91519c0a7323e223d601d258f6e19a98f358c'


def canonical(data):
    return data.replace(b'\r\n', b'\n')


def canonical_self(data):
    return re.sub(
        rb"(?m)^MANIFEST_SHA256 = '(?:<manifest-sha256>|[0-9a-f]{64})'$",
        b"MANIFEST_SHA256 = '<manifest-sha256>'",
        canonical(data),
    )


class GoogleWriterIntegratedCandidateIntegrityV6(unittest.TestCase):
    def test_v6_manifest_pins_current_candidate_and_preserves_v1_v5_contracts(self):
        raw = canonical((ROOT / MANIFEST).read_bytes())
        self.assertEqual(hashlib.sha256(raw).hexdigest(), MANIFEST_SHA256)
        manifest = json.loads(raw.decode('utf-8'))
        previous_raw = canonical((ROOT / PREVIOUS_MANIFEST).read_bytes())
        self.assertEqual(hashlib.sha256(previous_raw).hexdigest(), PREVIOUS_MANIFEST_SHA256)
        previous = json.loads(previous_raw.decode('utf-8'))
        self.assertEqual(manifest['contract'], 'pqm-google-writer-sync-ui-integrated')
        self.assertEqual(manifest['version'], 6)
        self.assertEqual(manifest['previous_candidate_commit'], PREVIOUS_SNAPSHOT)
        expected_scope = set(previous['scope']) | {
            PREVIOUS_MANIFEST.as_posix(),
            'validation/fixtures/pqm_sync_ui_integrated_v5_cd01e13.zip',
            'validation/run_integrated_writer_ui_v5_history.py',
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

    def test_historical_zip_fixtures_are_not_used_as_archive_outputs(self):
        workflow = (ROOT / '.github/workflows/release-checks.yml').read_text(encoding='utf-8')
        for version, filename in (
            ('V1', 'pqm_sync_ui_integrated_v1_3eda816.zip'),
            ('V2', 'pqm_sync_ui_integrated_v2_0d7e059.zip'),
            ('V3', 'pqm_sync_ui_integrated_v3_8c6ba07.zip'),
            ('V4', 'pqm_sync_ui_integrated_v4_654bd0de.zip'),
        ):
            self.assertIn(f'validation/run_integrated_writer_ui_{version.lower()}_history.py', workflow)
            self.assertNotIn(f'PQM_INTEGRATED_{version}_ARCHIVE_OUT=validation/fixtures/{filename}', workflow)
        self.assertIn('validation/run_integrated_writer_ui_v5_history.py', workflow)
        self.assertIn('test_google_writer_integrated_candidate_integrity_v6', workflow)
        self.assertNotIn('test_google_writer_integrated_candidate_integrity_v5 \\', workflow)

    def test_v5_historical_runner_and_archive_are_staged_for_gitless_container(self):
        runner = (ROOT / 'validation/run_local_release.py').read_text(encoding='utf-8')
        infra = (ROOT / 'test_release_gate_infrastructure.py').read_text(encoding='utf-8')
        self.assertIn('run_integrated_writer_ui_v5_history.py', runner)
        self.assertIn('pqm_sync_ui_integrated_v5_cd01e13.zip', runner)
        self.assertIn('PQM_RELEASE_SOURCE_ROOT=str(ROOT)', runner)
        self.assertIn('test_google_writer_integrated_candidate_integrity_v6', runner)
        self.assertIn('test_v5_historical_runner_uses_pinned_fixture_without_git', infra)


if __name__ == '__main__':
    unittest.main()
