"""Additive immutable pins and contract checks for read-only prewrite readiness."""
import hashlib
import json
import os
from pathlib import Path
import re
import unittest


MANIFEST=Path('validation/local_release_20261111/google_writer_prewrite_readonly_v1.json')
MANIFEST_SHA256="e62544033cf683620368dfccfced91499180655ad47e728530315f7cf2528e0c"
TEST_FILE='test_google_writer_prewrite_readonly_integrity_v1.py'


def canonical(raw):
    return raw.replace(b'\r\n',b'\n')


def canonical_self(raw):
    return re.sub(rb'(?m)^MANIFEST_SHA256="(?:<manifest-sha256>|[0-9a-f]{64})"$',
        b'MANIFEST_SHA256="<manifest-sha256>"',canonical(raw))


def root_path():
    configured=os.environ.get('PQM_RELEASE_SOURCE_ROOT')
    if configured:return Path(configured).resolve()
    here=Path(__file__).resolve()
    for root in (here.parent,*here.parents):
        if (root/MANIFEST).is_file() and (root/'google_writer_execution.py').is_file():return root
    raise RuntimeError('Cannot locate prewrite read-only overlay root')


class GoogleWriterPrewriteReadOnlyIntegrityTests(unittest.TestCase):
    def test_additive_overlay_pins_feature_and_preserves_previous_manifests(self):
        root=root_path();raw=canonical((root/MANIFEST).read_bytes())
        self.assertEqual(hashlib.sha256(raw).hexdigest(),MANIFEST_SHA256)
        manifest=json.loads(raw.decode('utf-8'))
        self.assertEqual(manifest['contract'],'pqm-sandbox-google-writer-prewrite-readonly-preflight')
        self.assertEqual(manifest['version'],1)
        self.assertEqual(manifest['baseline'],'9a0c50a493514488a00c54a4c6b371e99238ebed')
        self.assertEqual(set(manifest['scope']),set(manifest['files']))
        for relative,expected in manifest['files'].items():
            data=(root/relative).read_bytes()
            normalized=canonical_self(data) if relative==TEST_FILE else canonical(data)
            with self.subTest(path=relative):self.assertEqual(hashlib.sha256(normalized).hexdigest(),expected)
        for relative,expected in manifest['preserved_manifests'].items():
            with self.subTest(preserved=relative):
                self.assertEqual(hashlib.sha256(canonical((root/relative).read_bytes())).hexdigest(),expected)

    def test_preflight_is_read_only_and_closure_repeats_evidence_checks(self):
        root=root_path()
        python_source=canonical((root/'google_writer_execution.py').read_bytes()).decode()
        start=python_source.index('def prewrite_close_preflight(')
        end=python_source.index('\ndef prepare_admin_close_prewrite(',start)
        preflight=python_source[start:end]
        self.assertIn("'?mode=ro'",preflight)
        self.assertIn("PRAGMA query_only=ON",preflight)
        self.assertIn("client.invoke('prewrite_close_preflight'",preflight)
        self.assertNotIn('prepare_admin_close_prewrite(',preflight)
        self.assertNotIn('close_confirmed_prewrite_failure(',preflight)

        apps=canonical((root/'scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxAllScopeExecution20261109.gs').read_bytes()).decode()
        self.assertIn("var readOnlyCheck=request.action==='prewrite_close_preflight'",apps)
        self.assertIn("if (prewriteEvidenceAction) return pqmSandboxClosePrewriteFailure20261109_",apps)
        self.assertIn("writeAheadBytes<=checkpointMaxBytes",apps)
        self.assertIn("pqmSandboxAppendCodeCounts_(id,tabs,selected)",apps)
        self.assertIn("esc+'!S'+first+':S'+last",apps)
        self.assertIn("if (readOnlyCheck) {",apps)
        self.assertNotIn('setProperty(',apps[apps.index("function pqmSandboxClosePrewriteFailure20261109_"):apps.index("event={version:1",apps.index("function pqmSandboxClosePrewriteFailure20261109_"))])

    def test_endpoint_requires_both_permissions_and_ui_never_turns_ready_into_close(self):
        root=root_path();server=canonical((root/'server.py').read_bytes()).decode()
        start=server.index("if parsed.path == '/api/admin/google-writer/prewrite-close-preflight':")
        end=server.index("if parsed.path == '/api/admin/google-writer/close-prewrite':",start)
        route=server[start:end]
        self.assertIn("not permissions.get('admin.manage') or not permissions.get('google.writer.execute')",route)
        self.assertIn('prewrite_close_preflight(',route)
        self.assertNotIn('close_confirmed_prewrite_failure(',route)
        ui=canonical((root/'google_writer_ui.js').read_bytes()).decode()
        self.assertIn('Перевірити можливість закриття',ui)
        self.assertIn("${API}/admin/google-writer/prewrite-close-preflight",ui)
        self.assertIn('під час закриття все буде перевірено повторно',ui)
        self.assertIn('finally{googleWriterBusy=false;}',ui)


if __name__=='__main__':
    unittest.main()
