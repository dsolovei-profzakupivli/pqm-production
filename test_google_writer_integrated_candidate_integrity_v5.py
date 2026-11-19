"""Current integrated Writer/UI contract v5; v4 remains an immutable snapshot."""
import hashlib
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parent
MANIFEST = Path('validation/local_release_20261116/pqm_sync_ui_integrated_v5.json')
MANIFEST_SHA256 = '71a25437255990abed106836cdf91519c0a7323e223d601d258f6e19a98f358c'
TEST_FILE = 'test_google_writer_integrated_candidate_integrity_v5.py'
PREVIOUS_MANIFEST = Path('validation/local_release_20261116/pqm_sync_ui_integrated_v4.json')
PREVIOUS_TEST = 'test_google_writer_integrated_candidate_integrity_v4.py'
PREVIOUS_SNAPSHOT = '654bd0de0e5b3de6be61c5293a9fc00cf17217c3'
PREVIOUS_MANIFEST_SHA256 = '9282240bb39b4f97b551b6b0c60756d21b9b0d389bdcc50061369357a175d5e9'


def canonical(data):
    return data.replace(b'\r\n', b'\n')


def canonical_self(data):
    return re.sub(
        rb"(?m)^MANIFEST_SHA256 = '(?:<manifest-sha256>|[0-9a-f]{64})'$",
        b"MANIFEST_SHA256 = '<manifest-sha256>'",
        canonical(data),
    )


class GoogleWriterIntegratedCandidateIntegrityV5(unittest.TestCase):
    def test_v5_manifest_pins_current_candidate_and_preserves_v1_v4_contracts(self):
        raw = canonical((ROOT / MANIFEST).read_bytes())
        self.assertEqual(hashlib.sha256(raw).hexdigest(), MANIFEST_SHA256)
        manifest = json.loads(raw.decode('utf-8'))
        previous_raw = canonical((ROOT / PREVIOUS_MANIFEST).read_bytes())
        self.assertEqual(hashlib.sha256(previous_raw).hexdigest(), PREVIOUS_MANIFEST_SHA256)
        previous = json.loads(previous_raw.decode('utf-8'))
        self.assertEqual(manifest['contract'], 'pqm-google-writer-sync-ui-integrated')
        self.assertEqual(manifest['version'], 5)
        self.assertEqual(manifest['previous_candidate_commit'], PREVIOUS_SNAPSHOT)
        expected_scope = set(previous['scope']) | {
            PREVIOUS_MANIFEST.as_posix(),
            'validation/docker_release_gate.py',
            'validation/fixtures/pqm_sync_ui_integrated_v1_3eda816.zip',
            'validation/fixtures/pqm_sync_ui_integrated_v2_0d7e059.zip',
            'validation/fixtures/pqm_sync_ui_integrated_v3_8c6ba07.zip',
            'validation/fixtures/pqm_sync_ui_integrated_v4_654bd0de.zip',
            'validation/run_integrated_writer_ui_v4_history.py',
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

    def test_container_predeploy_missing_archive_regression_is_routed(self):
        runner = (ROOT / 'validation/run_local_release.py').read_text(encoding='utf-8')
        main = runner.split('def main():', 1)[1]
        self.assertLess(main.index('old_cwd=Path.cwd()'), main.index('v2_archive='))
        infrastructure = (ROOT / 'test_release_gate_infrastructure.py').read_text(encoding='utf-8')
        self.assertIn(
            'test_container_release_gate_stages_missing_v2_archive_with_initialized_cwd',
            infrastructure,
        )
        docker_gate = (ROOT / 'validation/docker_release_gate.py').read_text(encoding='utf-8')
        self.assertIn('validation/run_local_release.py', docker_gate)
        self.assertIn('test_release_gate_infrastructure.py', docker_gate)
        self.assertNotIn('*.zip', (ROOT / '.dockerignore').read_text(encoding='utf-8'))
        workflow = (ROOT / '.github/workflows/release-checks.yml').read_text(encoding='utf-8')
        self.assertIn(
            'test_release_gate_infrastructure.ReleaseGateInfrastructureTests.'
            'test_container_release_gate_stages_missing_v2_archive_with_initialized_cwd',
            workflow,
        )
        self.assertIn('validation/run_integrated_writer_ui_v4_history.py', workflow)
        self.assertIn('test_google_writer_integrated_candidate_integrity_v5', workflow)


if __name__ == '__main__':
    unittest.main()
