"""Additive v2 integrity contract for the APPEND formula-indicator correction."""
import hashlib
import json
import os
from pathlib import Path
import re
import unittest


MANIFEST = Path('validation/local_release_20261113/google_writer_append_continuation_v2.json')
MANIFEST_SHA256 = "2fb4d7124cdd7039ff07c87b275551e678afafb4aa807b7b0f0c5536e9bf2089"
TEST_FILE = 'test_google_writer_append_continuation_integrity_v2.py'


def canonical(raw):
    return raw.replace(b'\r\n', b'\n')


def canonical_self(raw):
    return re.sub(rb'(?m)^MANIFEST_SHA256 = "(?:<manifest-sha256>|[0-9a-f]{64})"$',
                  b'MANIFEST_SHA256 = ' + b'"<manifest-sha256>"', canonical(raw))


def source_root():
    configured = os.environ.get('PQM_RELEASE_SOURCE_ROOT')
    return Path(configured).resolve() if configured else Path(__file__).resolve().parent


class GoogleWriterAppendContinuationIntegrityV2(unittest.TestCase):
    def test_v2_pins_formula_semantics_and_preserves_v1_contract(self):
        root = source_root()
        raw = canonical((root / MANIFEST).read_bytes())
        self.assertEqual(hashlib.sha256(raw).hexdigest(), MANIFEST_SHA256)
        manifest = json.loads(raw.decode('utf-8'))
        self.assertEqual(manifest['contract'], 'pqm-sandbox-google-writer-append-continuation')
        self.assertEqual(manifest['version'], 2)
        self.assertEqual(manifest['baseline'], '85dc98bf5d0870266b2d895ad1a5e8be957dfcaa')
        self.assertEqual(set(manifest['scope']), set(manifest['files']))
        required = {
            'scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxFullApply.gs',
            'scripts/pqm-google-writer/sandbox-full-apply.test.cjs',
            'scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxAppendDiagnostic20261112.gs',
            'scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxExecution.gs',
            'scripts/pqm-google-writer/mirror-alignment/shared/PqmExecutionCheckpoint.gs',
            TEST_FILE,
        }
        self.assertEqual(set(manifest['files']), required)
        for relative, expected in manifest['files'].items():
            data = (root / relative).read_bytes()
            normalized = canonical_self(data) if relative == TEST_FILE else canonical(data)
            with self.subTest(path=relative):
                self.assertEqual(hashlib.sha256(normalized).hexdigest(), expected)

        preserved = manifest['preserved_manifests']
        v1 = 'validation/local_release_20261113/google_writer_append_continuation_v1.json'
        self.assertEqual(set(preserved), {v1})
        self.assertEqual(hashlib.sha256(canonical((root / v1).read_bytes())).hexdigest(), preserved[v1])

        full_apply = (root / 'scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxFullApply.gs').read_text(encoding='utf-8')
        self.assertIn("formula: column === 0 && typeof rawNew === 'string' && rawNew.charAt(0) === '='", full_apply)
        self.assertIn('continuationPrewriteGuard:pqmSandboxContinuationPrewriteGuard_', full_apply)
        execution = (root / 'scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxExecution.gs').read_text(encoding='utf-8')
        checkpoint = (root / 'scripts/pqm-google-writer/mirror-alignment/shared/PqmExecutionCheckpoint.gs').read_text(encoding='utf-8')
        diagnostic = (root / 'scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxAppendDiagnostic20261112.gs').read_text(encoding='utf-8')
        self.assertIn('pqmSandboxContinuationPrewriteGuard_', execution)
        self.assertIn('adapter.continuationPrewriteGuard', checkpoint)
        self.assertIn('continuationGuardRows', diagnostic)


if __name__ == '__main__':
    unittest.main()
