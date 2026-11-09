"""Additive source pins for the Sandbox ALL-scope durable recovery candidate."""
import hashlib
import json
import os
from pathlib import Path
import re
import unittest


MANIFEST=Path('validation/local_release_20261109/google_writer_all_scope_receipt_recovery_v1.json')
MANIFEST_SHA256 = "a70817e78a7bf602e27ca05f728d8ee6ab02adf52befc393857f827431d5ff01"
TEST_FILE='test_google_writer_all_scope_receipt_recovery_integrity_v1.py'


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
    raise RuntimeError('Cannot locate ALL-scope recovery integrity root')


class GoogleWriterAllScopeReceiptRecoveryIntegrityTests(unittest.TestCase):
    def test_additive_overlay_pins_candidate_and_preserves_historical_manifests(self):
        root=root_path();raw=canonical((root/MANIFEST).read_bytes())
        self.assertEqual(hashlib.sha256(raw).hexdigest(),MANIFEST_SHA256)
        manifest=json.loads(raw.decode('utf-8'))
        self.assertEqual(manifest['contract'],'pqm-sandbox-google-writer-all-scope-receipt-recovery')
        self.assertEqual(manifest['version'],1)
        self.assertEqual(manifest['baseline'],'9037e57728c09fe8aaea02d44b994da860944283')
        self.assertEqual(set(manifest['files']),set(manifest['scope']))
        for relative,expected in manifest['files'].items():
            data=(root/relative).read_bytes()
            normalized=canonical_self(data) if relative==TEST_FILE else canonical(data)
            with self.subTest(path=relative):self.assertEqual(hashlib.sha256(normalized).hexdigest(),expected)
        for relative,expected in manifest['preserved_manifests'].items():
            with self.subTest(preserved=relative):
                self.assertEqual(hashlib.sha256(canonical((root/relative).read_bytes())).hexdigest(),expected)

    def test_candidate_pins_write_ahead_journal_readback_and_restart_continuation(self):
        source=canonical((root_path()/'google_writer_execution.py').read_bytes()).decode('utf-8')
        tests=canonical((root_path()/'test_google_writer_all_scope_recovery.py').read_bytes()).decode('utf-8')
        for required in ('google_writer_apply_chunk_journal','claim_interrupted_apply_chunk_recovery',
                         'recover_interrupted_apply_chunk','claim_apply_continuation',
                         'APPLY_CHUNKS_PER_WORKER = 4','recover_apply_chunk'):
            with self.subTest(required=required):self.assertIn(required,source)
        for required in ('test_worker_recovers_exact_uncertain_chunk_then_continues_with_remaining_append_and_update',
                         'test_all_scope_worker_bounds_each_http_apply_to_four_confirmed_chunks',
                         'test_read_only_no_write_proof_keeps_all_scope_run_held'):
            with self.subTest(test=required):self.assertIn(required,tests)


if __name__=='__main__':
    unittest.main()
