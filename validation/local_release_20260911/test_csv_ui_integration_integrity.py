"""Current combined files, immutable CSV history and functional routing."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from validation import csv_ui_history as history

ROOT = Path(os.environ.get('PQM_RELEASE_SOURCE_ROOT') or Path(__file__).resolve().parents[2])
PIN = 'a43222ee5fccf84cbc2f00f3a8b6e00e9703b05dfe50b6045a6f93269ce3931c'


def digest(raw, name):
    if Path(name).suffix in {'.py', '.js', '.css', '.cjs', '.json', '.yml', '.html', '.md'}:
        raw = raw.replace(b'\r\n', b'\n')
    return hashlib.sha256(raw).hexdigest()


class IntegratedIntegrity(unittest.TestCase):
    def test_actual_candidate_files_and_historical_contracts(self):
        raw = (ROOT / 'validation/csv_ui_integration_v1.json').read_bytes()
        self.assertEqual(digest(raw, 'manifest.json'), PIN)
        manifest = json.loads(raw)
        for name, expected in {**manifest['files'], **manifest['unchanged']}.items():
            with self.subTest(file=name):
                content = (ROOT / name).read_bytes()
                self.assertEqual(digest(content, name), expected)
                self.assertNotEqual(digest(content + b'X', name), expected)

    def test_original_csv_snapshot_without_git(self):
        root = history.baseline_root(ROOT)
        self.assertFalse((root / '.git').exists())
        from validation.local_release_20260911.test_sandbox_clarity_integrity import sha as legacy_sha
        contract = json.loads((root / 'validation/sandbox_clarity_csv_v1.json').read_bytes())
        for name, expected in {**contract['files'], **contract['unchanged']}.items():
            self.assertEqual(legacy_sha((root / name).read_bytes(), name), expected, name)

    def test_wrong_archive_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / history.ARCHIVE
            target.parent.mkdir(parents=True)
            target.write_bytes((ROOT / history.ARCHIVE).read_bytes() + b'X')
            with self.assertRaisesRegex(AssertionError, 'archive changed'):
                history.baseline_root(folder)

    def test_routing_keeps_functional_csv_and_ui_on_current_server(self):
        from validation.local_release_20260911 import test_sandbox_clarity_csv as csv
        from validation import test_document_check_policy as ui
        import server
        tests = unittest.TestSuite([csv.ClarityFormatTests('test_headers_append_only'),
                                   ui.PolicyCountsTests('test_experience_never_affects_new_totals_for_any_severity')])
        history.route_integrity_suite(tests, ROOT)
        self.assertIs(csv.server, server)
        self.assertIs(ui.server, server)
        self.assertEqual(len(server.EDR_EXPORT_HEADERS), 8)

    def test_declared_package_contains_ui_tests_and_assets(self):
        from validation.release_test_package import load_package_manifest, package_dependency_map
        manifest = load_package_manifest(ROOT)
        declared = {name for name, _ in package_dependency_map(ROOT, ROOT, 'baseline_full', manifest)}
        for name in ['application_documents_ui.js', 'document_check_ui.css',
                     'validation/test_document_check_policy.py', 'validation/test_application_documents_source_indexes.py',
                     'validation/csv_ui_history.py', 'validation/fixtures/csv_ui_parent_6a5cd45.zip']:
            self.assertIn(name, declared)
