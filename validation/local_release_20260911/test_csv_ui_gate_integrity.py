"""Gate-451 repair: mandatory old/current checks, immutable runtime and fail-closed routing."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from validation import csv_ui_gate_history as history

ROOT = Path(os.environ.get('PQM_RELEASE_SOURCE_ROOT') or Path(__file__).resolve().parents[2])
PIN = 'a7cc38474b61c1461cc951f6328c5c48bc08a8741a2e94579eb1858bd6799837'


def digest(raw, name):
    if Path(name).suffix in {'.py', '.js', '.css', '.cjs', '.json', '.yml', '.html', '.md'}:
        raw = raw.replace(b'\r\n', b'\n')
    return hashlib.sha256(raw).hexdigest()


class GateRepairIntegrity(unittest.TestCase):
    def test_current_files_and_original_contracts(self):
        raw = (ROOT / 'validation/csv_ui_integration_v2.json').read_bytes()
        self.assertEqual(digest(raw, 'manifest.json'), PIN)
        contract = json.loads(raw)
        for name, expected in {**contract['files'], **contract['unchanged']}.items():
            with self.subTest(file=name):
                data = (ROOT / name).read_bytes()
                self.assertEqual(digest(data, name), expected)
                self.assertNotEqual(digest(data + b'X', name), expected)

    def test_original_node_and_browser_failures_propagate(self):
        from validation.csv_ui_history import baseline_root
        parent = baseline_root(ROOT)
        for mode, name in [('node', 'ui.cjs'), ('browser', 'browser.cjs')]:
            with patch.object(history.subprocess, 'run', return_value=SimpleNamespace(returncode=7)) as run:
                self.assertEqual(history.run_legacy(ROOT, mode), 7)
            self.assertEqual(run.call_args.kwargs['cwd'], parent)
            self.assertTrue(run.call_args.args[0][-1].endswith(name))
            self.assertFalse(run.call_args.kwargs['check'])

    def test_parent_sha_and_corrupt_archive_fail_closed(self):
        parent = history.parent_root(ROOT)
        self.assertFalse((parent / '.git').exists())
        self.assertEqual(history.BASE_SHA, 'c0c1df0d8136f90b42c2770f72e955c3f739855d')
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / history.ARCHIVE
            target.parent.mkdir(parents=True)
            target.write_bytes((ROOT / history.ARCHIVE).read_bytes() + b'X')
            with self.assertRaisesRegex(AssertionError, 'archive changed'):
                history.parent_root(folder)

    def test_old_v1_guard_is_historical_and_functional_tests_remain_current(self):
        from validation.local_release_20260911 import test_csv_ui_integration_integrity as old
        from validation import test_document_check_policy as ui
        import server
        suite = unittest.TestSuite([old.IntegratedIntegrity('test_actual_candidate_files_and_historical_contracts')])
        history.route_integrity_suite(suite, ROOT)
        self.assertEqual(old.ROOT, history.parent_root(ROOT))
        self.assertIs(ui.server, server)

    def test_workflow_requires_both_histories_and_current_checks(self):
        source = (ROOT / '.github/workflows/release-checks.yml').read_text(encoding='utf8')
        for name in ['--node-history', '--browser-history', 'sandbox_functionality_current_ui.cjs',
                     'sandbox_functionality_current_browser.cjs', 'application_documents_browser.cjs',
                     'document_check_browser.cjs', 'validation/run_local_release.py', 'validation/docker_release_gate_csv_ui_v2.py']:
            self.assertIn(name, source)
        self.assertNotIn('continue-on-error', source)
        self.assertIn('set -euo pipefail', source)
        from validation.release_test_package import load_package_manifest
        package = load_package_manifest(ROOT)
        self.assertIn('test_csv_ui_gate_integrity.py', package['required_local_release_tests'])
        self.assertIn('csv_ui_gate_history.py', package['supplemental_validation_files'])
