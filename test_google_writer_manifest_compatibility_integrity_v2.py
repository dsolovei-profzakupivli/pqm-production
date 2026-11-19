"""Additive pins for v1/v2 chunk-manifest compatibility and hold safety."""
import hashlib
import json
import os
from pathlib import Path
import re
import unittest


MANIFEST=Path('validation/local_release_20261109/google_writer_manifest_compatibility_v2.json')
MANIFEST_SHA256 = "3b2af6306f75f93503332d214a636c87dcfc75ce0ca0497821d84441d701d494"
TEST_FILE='test_google_writer_manifest_compatibility_integrity_v2.py'


def canonical(raw):
    return raw.replace(b'\r\n',b'\n')


def canonical_self(raw):
    return re.sub(rb'(?m)^MANIFEST_SHA256 = "(?:<manifest-sha256>|[0-9a-f]{64})"$',
        b'MANIFEST_SHA256 = "<manifest-sha256>"',canonical(raw))


def root_path():
    configured=os.environ.get('PQM_RELEASE_SOURCE_ROOT')
    if configured:return Path(configured).resolve()
    here=Path(__file__).resolve()
    for root in (here.parent,*here.parents):
        if (root/MANIFEST).is_file() and (root/'google_writer_execution.py').is_file():return root
    raise RuntimeError('Cannot locate chunk manifest compatibility overlay root')


class GoogleWriterManifestCompatibilityIntegrityTests(unittest.TestCase):
    def test_additive_overlay_pins_v2_fix_and_preserves_v1_history(self):
        root=root_path();raw=canonical((root/MANIFEST).read_bytes())
        self.assertEqual(hashlib.sha256(raw).hexdigest(),MANIFEST_SHA256)
        manifest=json.loads(raw.decode('utf-8'))
        self.assertEqual(manifest['contract'],'pqm-sandbox-google-writer-manifest-compatibility')
        self.assertEqual(manifest['version'],2)
        self.assertEqual(manifest['baseline'],'7df413e2d3d7242e1cc321e6578026f5cad271d1')
        self.assertEqual(set(manifest['files']),set(manifest['scope']))
        for relative,expected in manifest['files'].items():
            data=(root/relative).read_bytes()
            normalized=canonical_self(data) if relative==TEST_FILE else canonical(data)
            with self.subTest(path=relative):self.assertEqual(hashlib.sha256(normalized).hexdigest(),expected)
        for relative,expected in manifest['preserved_manifests'].items():
            with self.subTest(preserved=relative):
                self.assertEqual(hashlib.sha256(canonical((root/relative).read_bytes())).hexdigest(),expected)

    def test_appends_keep_legacy_v1_shape_and_all_uses_v2_evidence(self):
        root=root_path()
        checkpoint=canonical((root/'scripts/pqm-google-writer/mirror-alignment/shared/PqmExecutionCheckpoint.gs').read_bytes()).decode()
        legacy=canonical((root/'scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxExecution.gs').read_bytes()).decode()
        all_scope=canonical((root/'scripts/pqm-google-writer/mirror-alignment/sandbox/PqmSandboxAllScopeExecution20261109.gs').read_bytes()).decode()
        for field in ('code: String(change.cells[1]).trim()','cellsDigest: adapter.controlledDigest(change.cells)',
                      'formulaA: change.cells[0]','serviceMetadata: change.serviceMetadata'):
            self.assertIn(field,checkpoint)
            self.assertIn(field.split(':')[0],legacy)
        self.assertIn("record.chunkJournalVersion = 1",checkpoint)
        self.assertIn("record.chunkJournalVersion = 2",checkpoint)
        for field in ('detailsDigest','beforeDigest','afterDigest','codeDigest'):
            self.assertIn(field,checkpoint+all_scope)
        self.assertIn("record.chunkJournalVersion!==2",all_scope)

    def test_holds_are_not_discovered_by_background_recovery_worker(self):
        root=root_path();source=canonical((root/'google_writer_execution.py').read_bytes()).decode()
        start=source.index('    def recoverable(self):',source.index('class AppendOnlyContinuationWorker'))
        end=source.index('    def run_once(self):',start)
        recoverable=source[start:end]
        self.assertIn("r.status='running'",recoverable)
        self.assertNotIn("r.status IN ('running','outcome_unknown')",recoverable)
        tests=canonical((root/'test_google_writer_all_scope_recovery.py').read_bytes()).decode()
        append_tests=canonical((root/'test_google_writer_durable_append_recovery.py').read_bytes()).decode()
        self.assertIn('test_continuation_worker_does_not_auto_recover_all_scope_unknown_hold',tests)
        self.assertIn('test_continuation_worker_keeps_unknown_hold_after_restart_without_recovery_call',append_tests)


if __name__=='__main__':
    unittest.main()
