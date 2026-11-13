"""Additive integrity contract for the guarded APPEND continuation release."""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import unittest


MANIFEST = Path('validation/local_release_20261113/google_writer_append_continuation_v1.json')
MANIFEST_SHA256 = "e2569da64bcc83e18b5223d9cbfeccab46ea7524cfa2f41ed1a452f929922aa2"
TEST_FILE = 'test_google_writer_append_continuation_integrity_v1.py'


def canonical(raw):
    return raw.replace(b'\r\n', b'\n')


def canonical_self(raw):
    return re.sub(rb'(?m)^MANIFEST_SHA256 = "(?:<manifest-sha256>|[0-9a-f]{64})"$',
                  b'MANIFEST_SHA256 = "<manifest-sha256>"', canonical(raw))


def source_root():
    configured = os.environ.get('PQM_RELEASE_SOURCE_ROOT')
    if configured:
        return Path(configured).resolve()
    return Path(__file__).resolve().parent


class GoogleWriterAppendContinuationIntegrityV1(unittest.TestCase):
    def test_additive_overlay_pins_continuation_and_preserves_history(self):
        root = source_root()
        manifest_path = root / MANIFEST
        raw = canonical(manifest_path.read_bytes())
        self.assertEqual(hashlib.sha256(raw).hexdigest(), MANIFEST_SHA256)
        manifest = json.loads(raw.decode('utf-8'))
        self.assertEqual(manifest['contract'], 'pqm-sandbox-google-writer-append-continuation')
        self.assertEqual(manifest['version'], 1)
        self.assertEqual(manifest['baseline'], '44db9734345e9435adb112d4c1ec19b065d29cd6')
        self.assertEqual(set(manifest['scope']), set(manifest['files']))
        required = {
            'scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxFullApply.gs',
            'scripts/pqm-google-writer/sandbox-full-apply.test.cjs',
            'test_google_writer_execution.py',
        }
        self.assertTrue(required.issubset(manifest['files']))
        for relative, expected in manifest['files'].items():
            data = (root / relative).read_bytes()
            normalized = canonical_self(data) if relative == TEST_FILE else canonical(data)
            with self.subTest(path=relative):
                self.assertEqual(hashlib.sha256(normalized).hexdigest(), expected)
        for relative, expected in manifest['preserved_manifests'].items():
            with self.subTest(preserved=relative):
                self.assertEqual(hashlib.sha256(canonical((root / relative).read_bytes())).hexdigest(), expected)

    def test_release_runner_stages_every_candidate_manifest_without_touching_historical_mode(self):
        from validation.run_local_release import copy_candidate_manifests

        with tempfile.TemporaryDirectory(prefix='pqm-manifest-staging-') as temporary:
            base = Path(temporary)
            source_root = base / 'source'
            source_validation = source_root / 'validation'
            expected = (
                Path('sandbox_preview_append_only_v1.json'),
                Path('sandbox_preview_workflow_v1.json'),
                Path('local_release_20261109/google_writer_manifest_compatibility_v2.json'),
                Path('local_release_20261111/google_writer_execution_envelope_v1.json'),
                Path('local_release_20261111/google_writer_prewrite_diagnostics_v2.json'),
                Path('local_release_20261111/google_writer_prewrite_egress_v1.json'),
                Path('local_release_20261113/google_writer_append_continuation_v1.json'),
            )
            for index, relative in enumerate(expected):
                source = source_validation / relative
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(f'manifest-{index}'.encode('ascii'))
            unrelated = source_validation / 'halloween_shared_acceptance.json'
            unrelated.write_text('{"not":"a release manifest"}', encoding='utf-8')

            staged = base / 'staged-validation'
            copy_candidate_manifests(source_root, staged, 'candidate')
            for relative in expected:
                with self.subTest(manifest=str(relative)):
                    self.assertEqual((staged / relative).read_bytes(),
                                     (source_validation / relative).read_bytes())
            self.assertFalse((staged / unrelated.name).exists())

            historical = base / 'historical-validation'
            copy_candidate_manifests(source_root, historical, 'historical_integrity')
            self.assertFalse(historical.exists())


if __name__ == '__main__':
    unittest.main()
