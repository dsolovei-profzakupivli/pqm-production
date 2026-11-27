"""Current package integrity and fail-closed accepted-history routing."""
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from validation import document_release_history_v2 as history
ROOT = Path(os.environ.get('PQM_RELEASE_SOURCE_ROOT') or Path(__file__).resolve().parents[2])
CONTRACT_SHA = '39cfb74e7a3c58b15d63f885fd6d53553aab4421cb21a44b00e77ed721cefb08'
def digest(raw, name):
    # Git checks out text as CRLF on Windows and LF in Linux images. Binary
    # evidence remains byte-exact; UTF-8 text (including extensionless files)
    # uses the same canonical LF content on both hosts.
    text = Path(name).suffix in {'.py','.js','.css','.cjs','.json','.yml','.html','.md','.mjs','.yaml','.txt'}
    if not text and b'\0' not in raw:
        try:
            raw.decode('utf8')
            text = True
        except UnicodeDecodeError:
            pass
    if text:
        raw = raw.replace(b'\r\n', b'\n')
    return hashlib.sha256(raw).hexdigest()
class DocumentReleaseIntegrity(unittest.TestCase):
    def _assert_pinned_runtime(self, root, contract):
        root = Path(root).resolve()
        self.assertFalse((root / '.git').exists())
        for name, expected in contract['accepted_baseline_runtime'].items():
            self.assertEqual(digest((root / name).read_bytes(), name), expected, name)

    def test_current_package_and_unchanged_history(self):
        raw = (ROOT / 'validation/document_release_v1.json').read_bytes()
        self.assertEqual(digest(raw, 'contract.json'), CONTRACT_SHA)
        contract = json.loads(raw)
        self.assertEqual(contract['baseline_sha'], history.BASE_SHA)
        self.assertEqual(contract['container_entrypoint'], 'validation/docker_release_gate_csv_ui_v2.py')
        self.assertEqual(history.verify_v1_source(ROOT), contract)
    def test_history_sha_tree_and_original_runtime(self):
        root = history.baseline_root(ROOT)
        contract = json.loads((ROOT / 'validation/document_release_v1.json').read_text(encoding='utf8'))
        self._assert_pinned_runtime(root, contract)
        from validation.local_release_20260911 import test_csv_ui_gate_integrity as old
        suite = unittest.TestSuite([old.GateRepairIntegrity('test_current_files_and_original_contracts')])
        history.route_integrity_suite(suite, ROOT)
        routed = Path(old.ROOT).resolve()
        self._assert_pinned_runtime(routed, contract)
        for name, expected in contract['accepted_baseline_runtime'].items():
            self.assertEqual((root / name).read_bytes().replace(b'\r\n', b'\n'),
                             (routed / name).read_bytes().replace(b'\r\n', b'\n'), name)
            self.assertEqual(digest((routed / name).read_bytes(), name), expected, name)
        result = unittest.TestResult();suite.run(result)
        self.assertTrue(result.wasSuccessful(), str(result.failures) + str(result.errors))
    def _load_v28(self, path):
        name = 'test_google_writer_integrated_candidate_integrity_v28'
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return name, module
    def test_direct_github_and_render_cli_keep_current_module_origin(self):
        import sys
        name, module = self._load_v28(ROOT / 'test_google_writer_integrated_candidate_integrity_v28.py')
        with patch.dict(sys.modules, {name: module}):
            suite = unittest.defaultTestLoader.loadTestsFromModule(module)
            history.route_integrity_suite(suite, ROOT)
            self.assertEqual(Path(module.__file__).resolve().parent, ROOT.resolve())
            self.assertNotEqual(Path(module.ROOT).resolve(), ROOT.resolve())
            result = unittest.TestResult()
            suite.run(result)
            self.assertTrue(result.wasSuccessful(), str(result.failures) + str(result.errors))
    def test_render_delivered_suite_retains_explicit_staging_origin(self):
        import sys
        with tempfile.TemporaryDirectory(prefix='pqm-document-module-origin-') as folder:
            target = Path(folder) / 'test_google_writer_integrated_candidate_integrity_v28.py'
            target.write_bytes((ROOT / target.name).read_bytes())
            name, module = self._load_v28(target)
            with patch.dict(sys.modules, {name: module}):
                suite = unittest.defaultTestLoader.loadTestsFromModule(module)
                history.route_integrity_suite(suite, ROOT, module_root=Path(folder))
                self.assertEqual(Path(module.__file__).resolve(), target.resolve())
                self.assertNotEqual(Path(module.ROOT).resolve(), Path(folder).resolve())
                result = unittest.TestResult()
                suite.run(result)
                self.assertTrue(result.wasSuccessful(), str(result.failures) + str(result.errors))
    def test_wrong_explicit_module_origin_still_fails_closed(self):
        import sys
        name, module = self._load_v28(ROOT / 'test_google_writer_integrated_candidate_integrity_v28.py')
        with tempfile.TemporaryDirectory() as folder, patch.dict(sys.modules, {name: module}):
            suite = unittest.defaultTestLoader.loadTestsFromModule(module)
            with self.assertRaises(ValueError):
                history.route_integrity_suite(suite, ROOT, module_root=Path(folder))
    def test_text_newlines_are_portable_and_binary_is_byte_exact(self):
        for name in ['Dockerfile', '.gitattributes', 'assets/example.svg', 'config/example.csv', 'scripts/example.gs', 'app.js']:
            self.assertEqual(digest(b'a\r\nb\r\n', name), digest(b'a\nb\n', name))
        self.assertNotEqual(digest(b'PK\0a\r\nb', 'archive.zip'), digest(b'PK\0a\nb', 'archive.zip'))
        accepted = history.baseline_root(ROOT)
        contract = json.loads((ROOT / 'validation/document_release_v1.json').read_text(encoding='utf8'))
        for name, expected in contract['files'].items():
            if (accepted / name).is_file() and (accepted / name).read_bytes().replace(b'\r\n', b'\n') == (ROOT / name).read_bytes().replace(b'\r\n', b'\n'):
                self.assertEqual(digest((accepted / name).read_bytes(), name), expected, name)
    def test_corrupt_archive_and_wrong_sha_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / history.ARCHIVE;target.parent.mkdir(parents=True)
            target.write_bytes((ROOT / history.ARCHIVE).read_bytes() + b'X')
            additive = Path(folder) / history.ADDITIVE_ARCHIVE
            additive.parent.mkdir(parents=True, exist_ok=True)
            additive.write_bytes((ROOT / history.ADDITIVE_ARCHIVE).read_bytes())
            with self.assertRaisesRegex(AssertionError, 'archive changed'):
                history.baseline_root(folder)
            target.write_bytes((ROOT / history.ARCHIVE).read_bytes())
            with patch.object(history, 'BASE_SHA', 'wrong-sha'):
                with self.assertRaisesRegex(AssertionError, 'SHA/tree'):
                    history.baseline_root(folder)
    def test_historical_and_container_failures_propagate(self):
        accepted = history.baseline_root(ROOT)
        contract = json.loads((ROOT / 'validation/document_release_v1.json').read_text(encoding='utf8'))
        self._assert_pinned_runtime(accepted, contract)
        with patch.object(history, 'baseline_root', return_value=accepted), \
             patch.object(history.subprocess, 'run', return_value=SimpleNamespace(returncode=7)) as run:
            self.assertEqual(history.run_accepted(ROOT, 'node'), 7)
            self.assertEqual(Path(run.call_args.kwargs['cwd']).resolve(), accepted.resolve())
            self._assert_pinned_runtime(run.call_args.kwargs['cwd'], contract)
        spec = importlib.util.spec_from_file_location('_document_candidate_gate', ROOT / 'validation/docker_release_gate_csv_ui_v3.py')
        gate = importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)
        with patch.object(gate.sys, 'argv', [str(ROOT / 'validation/docker_release_gate_csv_ui_v3.py')]), \
             patch.object(gate.subprocess, 'run', side_effect=subprocess.CalledProcessError(9, ['synthetic'])):
            with self.assertRaises(subprocess.CalledProcessError):gate.main()
    def test_historical_browser_fixture_has_sandbox_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            env = {'PQM_UI001_EVIDENCE': folder + '/ui001', 'PQM_UI002_EVIDENCE': folder + '/ui002', 'PQM_CURRENT_FUNCTIONALITY_BROWSER_EVIDENCE': folder + '/current'}
            with patch.dict(os.environ, env), patch.object(history.subprocess, 'run', return_value=SimpleNamespace(returncode=7)):
                self.assertEqual(history.run_accepted(ROOT, 'browser'), 7)
            html = (Path(folder) / 'ui002/accepted-0678d46/sandbox-index.html').read_text(encoding='utf8')
            self.assertIn('data-pqm-environment="sandbox"', html)
    def test_github_and_render_require_current_and_historical_checks(self):
        workflow = (ROOT / '.github/workflows/release-checks.yml').read_text(encoding='utf8')
        for name in ['docker_release_gate_csv_ui_v3.py','document_release_history_v2.py','--accepted-node','--accepted-browser','document_partial_selection_browser.cjs','document_check_partial_browser.cjs','mvs_parameter_statuses_browser.cjs']:
            self.assertIn(name, workflow)
        self.assertNotIn('continue-on-error', workflow)
        gate = (ROOT / 'validation/docker_release_gate_csv_ui_v3.py').read_text(encoding='utf8')
        for name in ['--supplier-history','--accepted-node','document_partial_selection.test.cjs','sandbox_functionality_partial_ui.cjs','test_document_release_integrity_v1.py','validation.test_document_partial_http','validation.test_mvs_parameter_analysis']:
            self.assertIn(name, gate)
        self.assertIn('check=True', gate)
