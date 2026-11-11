"""Additive pins for the read-only prewrite egress action."""
import hashlib
import json
from pathlib import Path
import re
import unittest


MANIFEST=Path('validation/local_release_20261111/google_writer_prewrite_egress_v1.json')
MANIFEST_SHA256="92d475bc10a69e1053204600bbb64edad2d40e36f336339ea6456ae08fb33e5e"
TEST_FILE='test_sandbox_execution_prewrite_egress_integrity_v1.py'
ROOT=Path(__file__).resolve().parent


def canonical(raw):
    return raw.replace(b'\r\n',b'\n')


def canonical_self(raw):
    return re.sub(rb'(?m)^MANIFEST_SHA256="(?:<manifest-sha256>|[0-9a-f]{64})"$',
        b'MANIFEST_SHA256="<manifest-sha256>"',canonical(raw))


class GoogleWriterPrewriteEgressIntegrityV1(unittest.TestCase):
    def test_additive_overlay_pins_transport_and_preserves_prior_contracts(self):
        raw=canonical((ROOT/MANIFEST).read_bytes())
        self.assertEqual(hashlib.sha256(raw).hexdigest(),MANIFEST_SHA256)
        manifest=json.loads(raw.decode('utf-8'))
        self.assertEqual(manifest['contract'],'pqm-sandbox-google-writer-prewrite-egress')
        self.assertEqual(manifest['version'],1)
        self.assertEqual(manifest['baseline'],'6696a2d0b7425a2bd69c47641539a05072d47dbb')
        self.assertEqual(set(manifest['scope']),set(manifest['files']))
        for relative,expected in manifest['files'].items():
            data=(ROOT/relative).read_bytes()
            normalized=canonical_self(data) if relative==TEST_FILE else canonical(data)
            with self.subTest(path=relative):
                self.assertEqual(hashlib.sha256(normalized).hexdigest(),expected)
        for relative,expected in manifest['preserved_manifests'].items():
            with self.subTest(preserved=relative):
                self.assertEqual(hashlib.sha256(canonical((ROOT/relative).read_bytes())).hexdigest(),expected)

    def test_transport_admits_only_read_only_prewrite_preflight_shape(self):
        source=canonical((ROOT/'sandbox_runtime.py').read_bytes()).decode('utf-8')
        start=source.index('def validate_execution_request(')
        end=source.index('\n\n@contextmanager\ndef execution_open',start)
        guard=source[start:end]
        self.assertIn("action == 'prewrite_close_preflight'",guard)
        self.assertIn('prewrite_preflight_shape',guard)
        self.assertIn("'prewrite_close_preflight')",guard)
        self.assertIn("action not in ('preview', 'apply', 'reconcile_partial', 'recover_apply_chunk', 'close_unknown_run',",guard)
        self.assertIn('prewrite_keys == expected_prewrite_keys',guard)
        self.assertIn("payload.get('planScope') == 'APPEND_ONLY'",guard)
        self.assertIn('payload.get(\'targetIdentityDigest\') == prewrite_identity_digest',guard)
        self.assertIn("payload.get('requestId') != 'b11433e8efb84b4492bf2df7c7c25908'",guard)

    def test_apps_script_v20_contract_and_transport_regressions_are_present(self):
        source=canonical((ROOT/'scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxAllScopeExecution20261109.gs').read_bytes()).decode('utf-8')
        self.assertIn('function pqmSandboxAllScopeExecution20261109(envelope)',source)
        self.assertIn("request.action==='prewrite_close_preflight'",source)
        self.assertIn('var readOnlyCheck=request.action===',source)
        tests=canonical((ROOT/'test_sandbox_execution_transport.py').read_bytes()).decode('utf-8')
        self.assertIn('test_read_only_prewrite_preflight_is_allowed_with_exact_v20_contract',tests)
        self.assertIn('test_read_only_prewrite_preflight_rejects_invalid_bindings_and_shape',tests)
        self.assertIn('test_prewrite_preflight_allowance_does_not_allow_close_apply_or_resume',tests)


if __name__=='__main__':
    unittest.main()
