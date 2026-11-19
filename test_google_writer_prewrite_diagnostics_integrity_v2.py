"""Additive integrity pins for safe prewrite diagnostics v2."""
import hashlib
import json
from pathlib import Path
import re
import unittest


MANIFEST=Path('validation/local_release_20261111/google_writer_prewrite_diagnostics_v2.json')
MANIFEST_SHA256="61e31d839778b8c930f3d79d2402e1f710827ed25441920e5bf5cc85f2f51507"
TEST_FILE='test_google_writer_prewrite_diagnostics_integrity_v2.py'
ROOT=Path(__file__).resolve().parent


def canonical(raw):
    return raw.replace(b'\r\n',b'\n')


def canonical_self(raw):
    return re.sub(rb'(?m)^MANIFEST_SHA256="(?:<manifest-sha256>|[0-9a-f]{64})"$',
        b'MANIFEST_SHA256="<manifest-sha256>"',canonical(raw))


class GoogleWriterPrewriteDiagnosticsIntegrityV2(unittest.TestCase):
    def test_additive_overlay_pins_diagnostics_and_preserves_v1(self):
        raw=canonical((ROOT/MANIFEST).read_bytes())
        self.assertEqual(hashlib.sha256(raw).hexdigest(),MANIFEST_SHA256)
        manifest=json.loads(raw.decode('utf-8'))
        self.assertEqual(manifest['contract'],'pqm-sandbox-google-writer-prewrite-diagnostics')
        self.assertEqual(manifest['version'],2)
        self.assertEqual(manifest['baseline'],'40a6598c13221372969f556c48e8165769d59343')
        self.assertEqual(set(manifest['scope']),set(manifest['files']))
        for relative,expected in manifest['files'].items():
            data=(ROOT/relative).read_bytes()
            normalized=canonical_self(data) if relative==TEST_FILE else canonical(data)
            with self.subTest(path=relative):
                self.assertEqual(hashlib.sha256(normalized).hexdigest(),expected)
        for relative,expected in manifest['preserved_manifests'].items():
            with self.subTest(preserved=relative):
                self.assertEqual(hashlib.sha256(canonical((ROOT/relative).read_bytes())).hexdigest(),expected)

    def test_render_preflight_emits_allowlisted_diagnostics_without_raw_errors(self):
        source=canonical((ROOT/'google_writer_execution.py').read_bytes()).decode()
        invoke=source[source.index('    def invoke('):source.index('\ndef _preview_details_raw(',source.index('    def invoke('))]
        for code in ('OAUTH_TOKEN_SOURCE_FAILED','OAUTH_TOKEN_PREFLIGHT_REJECTED',
                     'EXECUTION_API_HTTP_','EXECUTION_API_TRANSPORT_TIMEOUT',
                     'APPS_SCRIPT_FUNCTION_ERROR','EXECUTION_RESPONSE_IDENTITY_MISMATCH',
                     'APPS_SCRIPT_PREFLIGHT_'):
            self.assertIn(code,invoke)
        self.assertNotIn('errorMessage',invoke[ invoke.index("if data.get('done')"):invoke.index("if action=='prewrite_close_preflight'")])
        helper=source[source.index('def prewrite_close_preflight('):source.index('\ndef prepare_admin_close_prewrite(',source.index('def prewrite_close_preflight('))]
        self.assertIn("result['diagnostic_code']=diagnostic_code",helper)
        self.assertIn("'sqlite_writes':0,'sheets_writes':0,'properties_writes':0",helper)

    def test_ui_only_renders_safe_codes_and_does_not_turn_preflight_into_close(self):
        source=canonical((ROOT/'google_writer_ui.js').read_bytes()).decode()
        start=source.index('async function preflightGoogleWriterPrewriteClose(')
        end=source.index('\nasync function closeGoogleWriterUnknownRun(',start)
        preflight=source[start:end]
        self.assertIn("/^[A-Z0-9_]{1,64}$/.test(result.diagnostic_code)",preflight)
        self.assertIn('HOLD збережено',preflight)
        self.assertNotIn('/close-prewrite',preflight)
        self.assertNotIn('close_confirmed_prewrite_failure',preflight)

    def test_v20_apps_script_dispatcher_and_read_only_handler_remain_compatible(self):
        source=canonical((ROOT/'scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxAllScopeExecution20261109.gs').read_bytes()).decode()
        self.assertIn('function pqmSandboxAllScopeExecution20261109(envelope)',source)
        self.assertIn("var prewriteCheckAction=request.action==='prewrite_close_preflight'",source)
        self.assertIn("if (prewriteEvidenceAction) return pqmSandboxClosePrewriteFailure20261109_",source)
        start=source.index('function pqmSandboxClosePrewriteFailure20261109_(')
        end=source.index('\nfunction pqmSandboxApplyStateReadOnly(',start)
        handler=source[start:end]
        self.assertIn("var readOnlyCheck=request.action==='prewrite_close_preflight'",handler)
        self.assertIn('readOnly:true',handler)
        readonly_return=handler.index("if (readOnlyCheck) {\n    if (markerScanIncomplete)")
        property_write=handler.index('properties.setProperty(closeKey,JSON.stringify(event))')
        self.assertLess(readonly_return,property_write)
        self.assertIn("return preflightResult(ready?'READY':'BLOCKED',reasons",handler[readonly_return:property_write])


if __name__=='__main__':
    unittest.main()
