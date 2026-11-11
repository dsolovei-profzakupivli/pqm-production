"""Additive integrity overlay for the legacy prewrite stage response contract."""
import hashlib
import json
from pathlib import Path
import re
import unittest


ROOT=Path(__file__).resolve().parent
MANIFEST=Path('google_writer_prewrite_stage_v1.json')
MANIFEST_SHA256="95cb9cf8635e81f431f7c6ef470db53b9770097d60454c704a4c8df0fafb88d0"
TEST_FILE='test_google_writer_prewrite_stage_integrity_v1.py'
PRESERVED_PINNED={
    'validation/local_release_20261111/google_writer_execution_envelope_v1.json':'92620f4066b23414170590b27ba7c26a79eef76851b3e10ff469004d28e2c401',
    'validation/local_release_20261111/google_writer_prewrite_egress_v1.json':'92d475bc10a69e1053204600bbb64edad2d40e36f336339ea6456ae08fb33e5e',
    'validation/local_release_20261111/google_writer_prewrite_readonly_v1.json':'e62544033cf683620368dfccfced91499180655ad47e728530315f7cf2528e0c',
    'validation/local_release_20261111/google_writer_prewrite_diagnostics_v2.json':'61e31d839778b8c930f3d79d2402e1f710827ed25441920e5bf5cc85f2f51507',
    'validation/local_release_20261109/google_writer_legacy_source_snapshots_v1.json':'5974fdff6faa703603ef7ce41d78f40e162df2d9501906c5d9fc9a136071debd',
    'validation/local_release_20261109/google_writer_all_scope_receipt_recovery_v1.json':'72c63161435081aec44f98a4605338bd9263afc9064614bce931caa3e43a0fa6',
}


def canonical(raw):
    return raw.replace(b'\r\n',b'\n')


def canonical_self(raw):
    return re.sub(rb'(?m)^MANIFEST_SHA256="(?:<manifest-sha256>|[0-9a-f]{64})"$',
        b'MANIFEST_SHA256="<manifest-sha256>"',canonical(raw))


class GoogleWriterPrewriteStageIntegrityV1(unittest.TestCase):
    def test_additive_overlay_pins_new_contract_and_preserves_previous_manifests(self):
        raw=canonical((ROOT/MANIFEST).read_bytes())
        self.assertEqual(hashlib.sha256(raw).hexdigest(),MANIFEST_SHA256)
        manifest=json.loads(raw.decode('utf-8'))
        self.assertEqual(manifest['contract'],'pqm-sandbox-google-writer-prewrite-stage')
        self.assertEqual(manifest['version'],1)
        self.assertEqual(manifest['baseline'],'c9bc1fef7ccf2adae0185f87ba18cfd2ef42f897')
        self.assertEqual(set(manifest['scope']),set(manifest['files']))
        for relative,expected in manifest['files'].items():
            data=(ROOT/relative).read_bytes()
            normalized=canonical_self(data) if relative==TEST_FILE else canonical(data)
            with self.subTest(path=relative):
                self.assertEqual(hashlib.sha256(normalized).hexdigest(),expected)
        for relative,expected in manifest['preserved_manifests'].items():
            with self.subTest(preserved=relative):
                self.assertEqual(expected,PRESERVED_PINNED[relative])
                path=ROOT/relative
                if path.is_file():
                    self.assertEqual(hashlib.sha256(canonical(path.read_bytes())).hexdigest(),expected)

    def test_render_accepts_only_bound_legacy_proof_and_keeps_other_stages_exact(self):
        source=canonical((ROOT/'google_writer_execution.py').read_bytes()).decode('utf-8')
        self.assertIn("result.get('prewriteStage')=='append_inflight_save'",source)
        self.assertIn("result.get('prewriteStage')!=expected_prewrite_stage",source)
        self.assertIn("result.get('proofType')!='LEGACY_V1_WRITEAHEAD_OVERSIZE'",source)
        self.assertIn("not is_canonical_sha256_b64url(result.get('runRecordDigest'))",source)
        self.assertIn("result['writeAheadBytes']<=_LEGACY_PREWRITE_LIMIT_BYTES",source)
        self.assertIn("result['checkpointMaxBytes']!=_LEGACY_PREWRITE_LIMIT_BYTES",source)
        self.assertIn("result.get('legacyManifestProjectionDigest')!=legacy_manifest_projection_digest",source)
        self.assertIn("'reasonCodes' not in result",source)
        tests=canonical((ROOT/'test_google_writer_prewrite_stage_contract.py').read_bytes()).decode('utf-8')
        for name in ('test_render_egress_accepts_exact_legacy_dispatcher_response_read_only',
                     'test_legacy_stage_or_proof_mismatch_never_becomes_ready',
                     'test_missing_proof_fields_and_nonlegacy_stage_remain_fail_closed',
                     'test_subject_matter_blocked_remains_blocked'):
            with self.subTest(test=name):
                self.assertIn(name,tests)

    def test_mock_invokes_real_apps_script_dispatcher_without_writes(self):
        test=canonical((ROOT/'scripts/pqm-google-writer/mirror-alignment/sandbox/prewrite-stage-contract.test.cjs').read_bytes()).decode('utf-8')
        self.assertIn('pqmSandboxAllScopeExecution20261109(f.envelope)',test)
        self.assertIn("assert.equal(result.prewriteStage,'append_inflight_save')",test)
        self.assertIn("assert.equal(f.propertyWrites(),0)",test)
        self.assertIn("assert.equal(f.sheetWrites(),0)",test)
        self.assertIn('execution authorization rejected',test)
        self.assertIn('assert.equal(f.envelope.payload.length,8649)',test)
        self.assertIn('oversized execution payload is restricted to read-only preflight',test)


if __name__=='__main__':
    unittest.main()
