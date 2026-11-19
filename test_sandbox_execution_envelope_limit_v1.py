"""Additive integrity overlay for the scoped Apps Script envelope allowance."""
import hashlib
import json
from pathlib import Path
import re
import unittest


ROOT=Path(__file__).resolve().parent
MANIFEST=Path('validation/local_release_20261111/google_writer_execution_envelope_v1.json')
MANIFEST_SHA256="92620f4066b23414170590b27ba7c26a79eef76851b3e10ff469004d28e2c401"
TEST_FILE='test_sandbox_execution_envelope_limit_v1.py'


def canonical(raw):
    return raw.replace(b'\r\n',b'\n')


def canonical_self(raw):
    return re.sub(rb'(?m)^MANIFEST_SHA256="(?:<manifest-sha256>|[0-9a-f]{64})"$',
        b'MANIFEST_SHA256="<manifest-sha256>"',canonical(raw))


class GoogleWriterExecutionEnvelopeV1(unittest.TestCase):
    def test_additive_overlay_pins_modified_sources_and_preserves_history(self):
        raw=canonical((ROOT/MANIFEST).read_bytes())
        self.assertEqual(hashlib.sha256(raw).hexdigest(),MANIFEST_SHA256)
        manifest=json.loads(raw.decode('utf-8'))
        self.assertEqual(manifest['contract'],'pqm-sandbox-google-writer-execution-envelope')
        self.assertEqual(manifest['version'],1)
        self.assertEqual(manifest['baseline'],'b4f35fc3c55ad2919dd1c08925fa2cfd13acd657')
        self.assertEqual(set(manifest['scope']),set(manifest['files']))
        for relative,expected in manifest['files'].items():
            data=(ROOT/relative).read_bytes()
            normalized=canonical_self(data) if relative==TEST_FILE else canonical(data)
            with self.subTest(path=relative):
                self.assertEqual(hashlib.sha256(normalized).hexdigest(),expected)
        for relative,expected in manifest['preserved_manifests'].items():
            with self.subTest(preserved=relative):
                self.assertEqual(hashlib.sha256(canonical((ROOT/relative).read_bytes())).hexdigest(),expected)

    def test_large_payload_allowance_is_signed_and_action_scoped(self):
        source=canonical((ROOT/'scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxAllScopeExecution20261109.gs').read_bytes()).decode()
        self.assertIn('var maxExecutionPayloadChars=8192;',source)
        self.assertIn('var maxReadOnlyPreflightPayloadChars=32768;',source)
        hmac_end=source.index("if (different) throw new Error('PQM: execution authorization rejected');")
        parse_at=source.index('var request = JSON.parse(envelope.payload)',hmac_end)
        scoped_at=source.index("request.action!=='prewrite_close_preflight'",parse_at)
        self.assertLess(hmac_end,parse_at)
        self.assertLess(parse_at,scoped_at)
        self.assertIn('envelope.payload.length>maxExecutionPayloadChars',source)
        self.assertIn('if (prewriteEvidenceAction) return pqmSandboxClosePrewriteFailure20261109_(request.spreadsheetId,properties,request);',source)
        self.assertIn("request.action==='prewrite_close_preflight'",source)
        for guard in ('request.environment!==\'SANDBOX\'','request.requestId===\'592128d9837d4b71bbeb330ef8aabf4b\'',
                      'targetIdentityDigest','legacyManifestProjectionDigest','chunkDigest','request.chunkIndex!==0'):
            with self.subTest(guard=guard):
                self.assertIn(guard,source)

    def test_regressions_measure_utf16_and_cover_rejections(self):
        node=canonical((ROOT/'scripts/pqm-google-writer/sandbox-full-apply.test.cjs').read_bytes()).decode()
        self.assertIn('signed 25-row legacy preflight may exceed 8192 only within the scoped envelope cap',node)
        self.assertIn('payload.length; // Apps Script String.length is UTF-16 code units.',node)
        self.assertIn('assert.equal(payloadChars,8649',node)
        self.assertIn('oversized execution payload is restricted to read-only preflight',node)
        self.assertIn('execution authorization rejected',node)
        self.assertIn("payload:'x'.repeat(32769)",node)
        py=canonical((ROOT/'test_sandbox_execution_transport.py').read_bytes()).decode()
        self.assertIn('test_legacy_25_row_preflight_payload_length_uses_utf16_units_and_exceeds_old_cap',py)
        self.assertIn('self.assertEqual(payload_utf16_units, 8649)',py)


if __name__=='__main__':
    unittest.main()
