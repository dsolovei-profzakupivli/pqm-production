"""Current-source integrity contract for APPEND continuation v2."""
import hashlib
import json
from pathlib import Path
import re
import unittest


MANIFEST = Path('validation/local_release_20261113/google_writer_append_continuation_v4.json')
MANIFEST_SHA256 = "49b4468485d206b98f378d079faa7bb5763e5708e10144ece8eb1c4e1546a085"
TEST_FILE = 'test_google_writer_append_continuation_integrity_v4.py'
ROOT = Path(__file__).resolve().parent
PRESERVED = {
    'validation/local_release_20261113/google_writer_append_continuation_v1.json': 'e2569da64bcc83e18b5223d9cbfeccab46ea7524cfa2f41ed1a452f929922aa2',
    'validation/local_release_20261113/google_writer_append_continuation_v2.json': '2fb4d7124cdd7039ff07c87b275551e678afafb4aa807b7b0f0c5536e9bf2089',
    'validation/local_release_20261113/google_writer_append_continuation_v3.json': 'ad378d8717b936a01671eb9837b842946f5636d74663f2382e23c24f4dbb7e63',
}


def canonical(data):
    return data.replace(b'\r\n', b'\n')


def canonical_self(data):
    return re.sub(rb'(?m)^MANIFEST_SHA256 = "(?:<manifest-sha256>|[0-9a-f]{64})"$',
                  b'MANIFEST_SHA256 = "<manifest-sha256>"', canonical(data))


class GoogleWriterAppendContinuationIntegrityV4(unittest.TestCase):
    def test_current_v2_overlay_pins_all_changed_sources_and_tests(self):
        raw = canonical((ROOT / MANIFEST).read_bytes())
        self.assertEqual(hashlib.sha256(raw).hexdigest(), MANIFEST_SHA256)
        manifest = json.loads(raw.decode('utf-8'))
        self.assertEqual(manifest['contract'], 'pqm-sandbox-google-writer-append-continuation')
        self.assertEqual(manifest['version'], 4)
        self.assertEqual(manifest['baseline'], '94d5b409c8f36feb01004cb293655e118e9bfedf')
        self.assertEqual(set(manifest['scope']), set(manifest['files']))
        self.assertEqual(set(manifest['files']), {
            'google_writer_execution.py',
            'sandbox_runtime.py',
            'scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxExecution.gs',
            'scripts/pqm-google-writer/mirror-alignment/shared/PqmExecutionCheckpoint.gs',
            'test_google_writer_append_continuation.py',
            'test_google_writer_append_diagnostic.py',
            'test_google_writer_execution.py',
            'scripts/pqm-google-writer/mirror-alignment/sandbox/continuation-v2-contract.test.cjs',
            'validation/run_local_release.py',
            '.github/workflows/release-checks.yml',
            'test_release_gate_infrastructure.py',
            '.gitattributes',
            TEST_FILE,
        })
        for relative, expected in manifest['files'].items():
            data = (ROOT / relative).read_bytes()
            normalized = canonical_self(data) if relative == TEST_FILE else canonical(data)
            with self.subTest(path=relative):
                self.assertEqual(hashlib.sha256(normalized).hexdigest(), expected)

    def test_previous_v1_v2_v3_manifests_are_unchanged(self):
        for relative, expected in PRESERVED.items():
            with self.subTest(manifest=relative):
                self.assertEqual(hashlib.sha256(canonical((ROOT / relative).read_bytes())).hexdigest(), expected)

    def test_c246_text_files_are_checked_out_with_lf_without_changing_blob_pins(self):
        rules = (ROOT / '.gitattributes').read_text(encoding='utf-8').splitlines()
        self.assertEqual(set(rules), {
            '/validation/run_c246_historical_integrity_snapshots_v1.py text eol=lf',
            '/validation/c246_historical_integrity_snapshots_v1.json text eol=lf',
        })

    def test_prior_integrity_contracts_are_routed_to_exact_trees(self):
        runner = (ROOT / 'validation/run_local_release.py').read_text(encoding='utf-8')
        exact_modules = runner.split('EXACT_TREE_OVERLAY_MODULES', 1)[1].split('}', 1)[0]
        self.assertIn("'test_google_writer_append_continuation_integrity_v2'", exact_modules)
        self.assertIn("'test_google_writer_append_continuation_integrity_v3'", exact_modules)
        workflow = (ROOT / '.github/workflows/release-checks.yml').read_text(encoding='utf-8')
        self.assertIn('git archive 7417591bbd8cb945a85e759d28036b72f97f8e9e', workflow)
        self.assertIn('test_google_writer_append_continuation_integrity_v4', workflow)


if __name__ == '__main__':
    unittest.main()
