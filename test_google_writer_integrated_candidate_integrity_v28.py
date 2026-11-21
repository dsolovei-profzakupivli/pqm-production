"""V28 pins the accepted UI tree; V1-V27 remain immutable historical contracts."""
from hashlib import sha256
import ast
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import re
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from validation.integrated_snapshot_archive import canonical_eol
import validation.integrated_snapshot_archive as archive_support
import validation.integrated_git_snapshot as git_support

from validation.memory_v28_history import snapshot_root
ROOT = snapshot_root('v28')
MANIFEST = Path('validation/local_release_20261116/pqm_sync_ui_integrated_v28.json')
MANIFEST_SHA256 = "da17790c32b9a4dccd6c9a06324d6ab0fdc3d1c84123c7fe7737ac8cd4c45728"
PREVIOUS_MANIFEST = Path('validation/local_release_20261116/pqm_sync_ui_integrated_v27.json')
PREVIOUS_MANIFEST_SHA256 = '24cd07a8aef893fff6d8dba38e7abb4ea6dc557e951977ce115c78d82f65aca5'
PREVIOUS_CANDIDATE = '644dbe87809637215cf05c72cead99183033877d'
HISTORY_RUNNER = Path('validation/run_integrated_writer_ui_v27_history.py')
V28_CHANGES = {
    'validation/halloween_resource_gate_browser.cjs',
    'test_calendar_resource_gate.py',
    'pqm_cat.css',
    'pqm_cat.js',
    'halloween_motion.js',
    'test_halloween_ui.py',
    'validation/halloween_sandbox_html.cjs',
    'validation/halloween_season_unit.cjs',
    'validation/local_release_20260911/test_registry_ux_cleanup.py',
    '.github/workflows/release-checks.yml',
    'app.js',
    'docs/EDR_MONITORING_PERFORMANCE_FOLLOWUP.txt',
    'halloween.js',
    'index.html',
    'queue_statistics_ui.js',
    'sandbox_runtime.py',
    'server.py',
    'test_release_gate_infrastructure.py',
    'test_v27_live_filter_regressions.py',
    'theme_ui.js',
    'ui_improvements.js',
    'validation/docker_release_gate.py',
    'validation/edr_monitoring_drawer.test.cjs',
    'validation/local_release_20260911/test_release_test_package.py',
    'validation/queue_statistics_ui.test.cjs',
    'validation/release_test_package_v1.json',
    'validation/run_local_release.py',
    'validation/ui_improvements_unit.cjs',
    'validation/uo_work_page_layout_browser.cjs',
    'validation/v27_live_regressions_browser.cjs',
}
SELF_NORMALIZE = {
    f'test_google_writer_integrated_candidate_integrity_v{v}.py' for v in range(10, 29)
}


def pinned_bytes(relative, data):
    data = canonical_eol(data)
    if relative in SELF_NORMALIZE:
        data = re.sub(rb'''(?m)^MANIFEST_SHA256 = ["'][^"']+["']$''',
                      b'MANIFEST_SHA256 = "<manifest-sha256>"', data)
    return data


def verify_files(root, pins):
    for relative, expected in pins.items():
        actual = sha256(pinned_bytes(relative, (root / relative).read_bytes())).hexdigest()
        if actual != expected:
            raise AssertionError(f'V28 file integrity mismatch: {relative}: {actual} != {expected}')


def history_module():
    spec = importlib.util.spec_from_file_location('v27_history_under_test', ROOT / HISTORY_RUNNER)
    module = importlib.util.module_from_spec(spec)
    with patch.dict('sys.modules', {'integrated_snapshot_archive': archive_support,
                                    'integrated_git_snapshot': git_support}):
        spec.loader.exec_module(module)
    return module


class GoogleWriterIntegratedCandidateIntegrityV28(unittest.TestCase):
    def test_current_tree_and_exact_scope(self):
        raw = canonical_eol((ROOT / MANIFEST).read_bytes())
        self.assertEqual(sha256(raw).hexdigest(), MANIFEST_SHA256)
        current = json.loads(raw)
        previous_raw = canonical_eol((ROOT / PREVIOUS_MANIFEST).read_bytes())
        self.assertEqual(sha256(previous_raw).hexdigest(), PREVIOUS_MANIFEST_SHA256)
        previous = json.loads(previous_raw)
        self.assertEqual(current['contract'], 'pqm-google-writer-sync-ui-integrated')
        self.assertEqual(current['version'], 28)
        self.assertEqual(current['previous_candidate_commit'], PREVIOUS_CANDIDATE)
        self.assertEqual(current['previous_manifest'], PREVIOUS_MANIFEST.as_posix())
        self.assertEqual(current['previous_manifest_sha256'], PREVIOUS_MANIFEST_SHA256)
        expected = set(previous['scope']) | V28_CHANGES | {
            PREVIOUS_MANIFEST.as_posix(), HISTORY_RUNNER.as_posix(), Path(__file__).name,
        }
        self.assertEqual(set(current['scope']), expected)
        self.assertEqual(len(current['scope']), len(expected))
        self.assertEqual(set(current['files']), expected)
        verify_files(ROOT, current['files'])
        for relative, digest in previous['files'].items():
            if relative not in V28_CHANGES:
                self.assertEqual(sha256(pinned_bytes(relative, (ROOT / relative).read_bytes())).hexdigest(), digest, relative)
        for relative, digest in current['immutable_history_files'].items():
            self.assertEqual(sha256(canonical_eol((ROOT / relative).read_bytes())).hexdigest(), digest, relative)

    def test_routes_history_and_current_without_omitting_groups(self):
        workflow = (ROOT / '.github/workflows/release-checks.yml').read_text(encoding='utf8')
        runner = (ROOT / 'validation/run_local_release.py').read_text(encoding='utf8')
        package = json.loads((ROOT / 'validation/release_test_package_v1.json').read_text(encoding='utf8'))
        self.assertEqual(package['integrated_history_versions'], list(range(1, 28)))
        self.assertEqual(package['integrity_test_versions'], list(range(1, 29)))
        self.assertIn('integrated_v27_history.returncode==0', runner)
        self.assertIn('integrated_v28_current.returncode==0', runner)
        self.assertIn(HISTORY_RUNNER.as_posix(), workflow)
        self.assertIn('PQM_INTEGRATED_V27_SNAPSHOT_ARCHIVE_SHA256', workflow)
        self.assertIn('dst=/tmp/pqm-integrated-v27-snapshot.zip,readonly', workflow)
        command = workflow.split('test_google_writer_integrated_candidate_integrity_v28 ' + chr(92), 1)[1].split('- name: Install Playwright', 1)[0]
        self.assertNotIn('test_google_writer_integrated_candidate_integrity_v27', command)
        for test in ('uo_work_page_layout_browser', 'application_filter_drawer_browser',
                     'filter_panels_context_browser', 'filter_panels_unified_browser',
                     'v27_live_regressions_browser', 'halloween_resource_gate_browser'):
            self.assertIn(f'node validation/{test}.cjs', workflow)

    def test_historical_route_uses_exact_sha_and_original_contract(self):
        module = history_module()
        self.assertEqual(module.SNAPSHOT_COMMIT, PREVIOUS_CANDIDATE)
        self.assertEqual(module.MANIFEST_SHA256, PREVIOUS_MANIFEST_SHA256)
        self.assertEqual(module.TEST_MODULE, 'test_google_writer_integrated_candidate_integrity_v27')
        with patch.object(module, 'snapshot_archive_for_runner', return_value=(b'verified', 'git')) as factory:
            self.assertEqual(module.source_snapshot_archive(ROOT), b'verified')
            self.assertEqual(factory.call_args.kwargs['version'], 27)
            self.assertEqual(factory.call_args.kwargs['commit'], PREVIOUS_CANDIDATE)
            self.assertEqual(factory.call_args.kwargs['expected_manifest_sha256'], PREVIOUS_MANIFEST_SHA256)
        with patch.object(module, 'snapshot_archive_for_runner', side_effect=RuntimeError('bad snapshot SHA')):
            with self.assertRaisesRegex(RuntimeError, 'bad snapshot SHA'):
                module.source_snapshot_archive(ROOT)

    def test_historical_failure_stays_nonzero(self):
        module = history_module()
        stream = BytesIO()
        with zipfile.ZipFile(stream, 'w') as bundle:
            bundle.writestr('fixture.txt', 'synthetic')
        with patch.object(module, 'source_snapshot_archive', return_value=stream.getvalue()), \
             patch.object(module.subprocess, 'run', return_value=SimpleNamespace(returncode=7)) as run:
            self.assertEqual(module.main(), 7)
            self.assertEqual(run.call_args.args[0][-1], module.TEST_MODULE)
            self.assertNotEqual(Path(run.call_args.kwargs['cwd']), ROOT)

    def test_runtime_guards_outside_approved_functions_are_unchanged(self):
        protected = {'server.py': {'allowed': ['_filter_edr_monitoring_rows'], 'sha256': '0db9cefd5c8818e38caf6df3abc67285eac5c5d958a76af1a60ef5cddeb33903'}, 'sandbox_runtime.py': {'allowed': ['decorate_html'], 'sha256': 'cb48d6d5effe708e0befdb3d1b4a083f31d8a41c26dd18eb3d14d9e1ad855b9d'}}
        for name, contract in protected.items():
            tree = ast.parse((ROOT / name).read_text(encoding='utf8'))
            for index, node in enumerate(tree.body):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in contract['allowed']:
                    tree.body[index] = ast.Pass()
            actual = sha256(ast.dump(tree, include_attributes=False).encode()).hexdigest()
            self.assertEqual(actual, contract['sha256'], name)

    def test_current_file_corruption_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix='pqm-v28-corruption-') as tmp:
            root = Path(tmp)
            (root / 'fixture.css').write_bytes(b'approved')
            pins = {'fixture.css': sha256(b'approved').hexdigest()}
            verify_files(root, pins)
            (root / 'fixture.css').write_bytes(b'changed')
            with self.assertRaisesRegex(AssertionError, 'fixture.css'):
                verify_files(root, pins)


if __name__ == '__main__':
    unittest.main()
