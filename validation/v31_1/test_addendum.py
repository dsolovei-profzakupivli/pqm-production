"""Fail-closed tests for the additive V31.1 fixture and history contract."""
import ast
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
import base64
import hashlib
import io
import json
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'validation'))
sys.path.insert(0, str(ROOT))

import run_messages_integrated_v1_history_addendum as messages_addendum
from validation.v31_1 import bridge, routing


class V311AddendumTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path(os.environ.get('PQM_V311_SOURCE_ROOT') or ROOT).resolve()

    def test_exact_additive_contract_and_protected_files(self):
        manifest = bridge.validate_addendum(self.source)
        self.assertEqual(messages_addendum.HISTORY_COMMIT, manifest['history_commit'])
        self.assertEqual(messages_addendum.HISTORY_TREE, manifest['history_tree'])
        self.assertEqual(messages_addendum.CURRENT_CANDIDATE_TEST, manifest['candidate_test'])
        self.assertEqual(sorted(set(manifest['allowed_paths'])), manifest['allowed_paths'])

    def test_wrong_history_commit_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, 'Unapproved Messages/NAZK historical commit'):
            messages_addendum.verify_history_identity(self.source, 'c246edefaa676d137d3f38d40f18d039f7b5bac2')

    def test_archive_blob_corruption_fails_closed(self):
        manifest = bridge.validate_addendum(self.source)
        name = 'validation/chat_messages_browser.cjs'
        record = manifest['history_snapshot']['files'][name]
        archive = base64.b64decode(manifest['history_snapshot']['delta_zip_base64'], validate=True)
        with zipfile.ZipFile(io.BytesIO(archive)) as source:
            exported = source.read(name)
        raw = exported.replace(b'\r\n', b'\n') if record['archive_eol'] == 'crlf' else exported
        oid = record['git_blob'].encode('ascii')
        messages_addendum.verify_exported_blob('validation/chat_messages_browser.cjs', oid, raw, exported)
        offset = next(i for i, value in enumerate(exported) if value not in (10, 13))
        corrupted = exported[:offset] + bytes([exported[offset] ^ 1]) + exported[offset + 1:]
        with self.assertRaisesRegex(RuntimeError, 'Unexpected Git archive content transformation'):
            messages_addendum.verify_exported_blob('validation/chat_messages_browser.cjs', oid, raw, corrupted)

    def test_delegate_nonzero_exit_is_not_swallowed(self):
        with patch.object(messages_addendum.subprocess, 'run',
                          return_value=subprocess.CompletedProcess(['delegate'], 23, '', 'synthetic failure')):
            with self.assertRaisesRegex(RuntimeError, 'exit code 23'):
                messages_addendum._run(['delegate'], cwd=self.source, env={}, label='synthetic delegate')

    def test_git_integrity_checks_drop_inherited_config_overrides(self):
        environment = os.environ.copy()
        environment['GIT_CONFIG_COUNT'] = '1'
        environment['GIT_CONFIG_KEY_0'] = 'core.bare'
        environment.pop('GIT_CONFIG_VALUE_0', None)
        with patch.dict(os.environ, environment, clear=True):
            manifest = bridge.validate_addendum(self.source)
        self.assertEqual(manifest['base_commit'], bridge.ACCEPTED_CANDIDATE)

    def test_historical_modules_route_through_current_bridge_once(self):
        class Historical(unittest.TestCase):
            def runTest(self):
                raise AssertionError('Historical test must be routed to exact snapshot')
        class Unrelated(unittest.TestCase):
            def runTest(self):
                self.ran = True
        leaves = []
        for module in routing.HISTORICAL_MESSAGES_MODULES:
            case = Historical()
            case.__class__.__module__ = module
            leaves.append(case)
        unrelated = Unrelated()
        unrelated.__class__.__module__ = 'unrelated_candidate_test'
        leaves.append(unrelated)
        with patch.object(bridge, 'phase') as phase:
            suite = bridge.route_suite(unittest.TestSuite(leaves), self.source)
            self.assertEqual(suite.countTestCases(), 2)
            result = unittest.TestResult()
            suite.run(result)
            self.assertTrue(result.wasSuccessful())
            phase.assert_called_once_with(self.source, 'python', 'local')

    def test_historical_source_uses_preflighted_checkout_for_reduced_release_stage(self):
        temp_root = Path(os.environ.get('PQM_V311_TEMP_ROOT') or self.source.parent).resolve()
        trusted = Path(os.environ.get('PQM_RELEASE_SOURCE_ROOT') or self.source).resolve()
        index = bridge.validate_snapshot(trusted)
        with tempfile.TemporaryDirectory(prefix='pqm-v311-reduced-stage-', dir=temp_root) as folder:
            stage = Path(folder)
            bridge_path = stage / 'validation/v31_1/bridge.py'
            bridge_path.parent.mkdir(parents=True)
            bridge_path.write_bytes((trusted / 'validation/v31_1/bridge.py').read_bytes())
            with patch.dict(os.environ, {'PQM_RELEASE_SOURCE_ROOT': str(trusted)}):
                with bridge.historical_source(stage) as pinned:
                    server = (pinned / 'server.py').read_bytes()
                    self.assertEqual(bridge.sha(server), index['files']['server.py'])
                    self.assertFalse((pinned / 'V31_SNAPSHOT_INDEX.json').exists())

    def test_current_functional_route_is_mandatory_and_not_a_historical_skip(self):
        self.assertEqual(messages_addendum.CURRENT_CANDIDATE_TEST,
                         bridge.validate_addendum(self.source)['candidate_test'])
        self.assertIn('test_nazk_authority_request_integrity', routing.HISTORICAL_MESSAGES_MODULES)

    def test_edr_fixture_adapter_is_case_scoped_and_preserves_assertions(self):
        source = (self.source / 'validation/v31_1/history_run.py').read_text(encoding='utf-8')
        self.assertNotIn('make_edr_apply_nazk_reconciler', source)
        parsed = ast.parse(source)
        function = next(node for node in parsed.body if isinstance(node, ast.FunctionDef)
                        and node.name == 'adapt_edr_fixture_tree')
        namespace = {'ast': ast, 'RuntimeError': RuntimeError}
        exec(compile(ast.Module(body=[function], type_ignores=[]), 'history-fixture-adapter', 'exec'), namespace)
        adapt = namespace['adapt_edr_fixture_tree']

        cases = {
            'test_permanent_edr_sync_safety': '''from test_edr_sync_v2 import database, row, snapshot
class T:
 def test_google_full_mirror_clears_newer_blanks_and_preserves_history(self):
  profile(self.con, status="Припинено")
  self.assertEqual(1, 1)
 def test_same_day_same_officer_equivalent(self):
  profile(self.con)
  self.assertEqual(1, 1)
 def test_same_instant_preserves_officer_then_newer_second_wins(self):
  profile(self.con)
  self.assertEqual(1, 1)
 def test_fop_equal_timestamp_fills_only_blank_names_and_is_idempotent(self):
  code="2934702572"
  existing_name_code="2934702573"
  preview=sync.build_preview(self.con, source)
  self.assertEqual(1, 1)
 def test_unrelated_noneligible_case_stays_unseeded(self):
  self.assertEqual(1, 1)
''',
            'test_supplier_edr_dates': '''from validation.local_release_20260911.test_edr_sync_v2 import database
class T:
 def test_import_and_repeat_keep_verification_date_separate(self):
  con=database()
  con.commit()
  self.assertEqual(1, 1)
''',
            'test_supplier_edr_apply_v31': '''from validation.local_release_20260911.test_edr_sync_v2 import database
class T:
 def test_worker_rolls_back_business_changes_and_records_failed_result(self):
  con=database()
  con.execute("ALTER TABLE submissions ADD COLUMN framework_id TEXT DEFAULT ''")
  con.commit()
  self.assertEqual(1, 1)
''',
        }
        for module_name, text in cases.items():
            tree = ast.parse(text)
            before = [ast.dump(node) for node in ast.walk(tree)
                      if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                      and node.func.attr.startswith('assert')]
            adapted = adapt(tree, module_name)
            after = [ast.dump(node) for node in ast.walk(adapted)
                     if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                     and node.func.attr.startswith('assert')]
            self.assertEqual(before, after, module_name)
            self.assertIn('eligible_supplier', ast.unparse(adapted))
        permanent = ast.unparse(adapt(ast.parse(cases['test_permanent_edr_sync_safety']),
                                      'test_permanent_edr_sync_safety'))
        unrelated = permanent.split('def test_unrelated_noneligible_case_stays_unseeded', 1)[1]
        self.assertNotIn('eligible_supplier', unrelated)
        unchanged = adapt(ast.parse('class T:\n def test_new_google_code_without_decided_application_stays_ineligible(self):\n  pass\n'),
                          'test_edr_sync_v2')
        self.assertNotIn('eligible_supplier', ast.unparse(unchanged))

    def test_current_protected_file_hash_rejects_mutation(self):
        manifest = bridge.validate_addendum(self.source)
        name = 'edr_sync_v2.py'
        expected = manifest['protected_lf_sha256'][name]
        temp_root = Path(os.environ.get('PQM_V311_TEMP_ROOT') or self.source.parent).resolve()
        if not temp_root.is_dir() or temp_root == self.source or self.source in temp_root.parents or temp_root in self.source.parents:
            self.fail('addendum test temporary root is not isolated')
        with tempfile.TemporaryDirectory(prefix='pqm-v311-addendum-mutation-', dir=temp_root) as folder:
            target = Path(folder) / name
            target.write_bytes((self.source / name).read_bytes() + b'\n# mutation\n')
            with self.assertRaisesRegex(RuntimeError, 'addendum file SHA mismatch'):
                bridge.validate_lf_file(folder, name, expected)

    def _candidate_route_suite(self, root, module_file):
        module_name = messages_addendum.CURRENT_CANDIDATE_TEST.rsplit('.', 2)[0]
        module = types.ModuleType(module_name)
        module.__file__ = str(module_file)
        test_name = messages_addendum.CURRENT_CANDIDATE_TEST.rsplit('.', 2)[2]
        test_class = type('NazkAuthorityRequestIntegrityTests', (unittest.TestCase,), {
            '__module__': module_name,
            test_name: lambda self: None,
        })
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(test_class)
        return module_name, module, suite

    def test_required_current_test_is_verified_from_actual_staging(self):
        temp_root = Path(os.environ.get('PQM_V311_TEMP_ROOT') or self.source.parent).resolve()
        with tempfile.TemporaryDirectory(prefix='pqm-v311-staged-nazk-', dir=temp_root) as folder:
            stage = Path(folder) / 'stage'
            stage.mkdir()
            bridge.stage(self.source, stage)
            manifest = bridge.validate_addendum(stage)
            relative = Path('validation/local_release_20260911/test_nazk_authority_request_integrity.py')
            target = stage / relative
            original = target.read_bytes()
            module_name, module, suite = self._candidate_route_suite(stage, target)
            # The authoritative checkout remains valid while the exact file
            # that unittest discovered in staging is corrupted.
            self.assertEqual(bridge.sha((self.source / relative).read_bytes().replace(b'\r\n', b'\n')),
                             bridge.sha(original.replace(b'\r\n', b'\n')))
            try:
                mutations = {
                    'body replaced by pass': b'import unittest\nclass NazkAuthorityRequestIntegrityTests:\n'
                        b'    def test_generation_route_uses_tasks_manage_and_direction_is_separate(self):\n        pass\n',
                    'same name and count, changed body': original.replace(
                        b"self.assertEqual(auth_access.permission_key('POST', path), 'tasks.manage')",
                        b"self.assertEqual('pass', 'pass')", 1),
                    'test removed': original.replace(
                        b'    def test_generation_route_uses_tasks_manage_and_direction_is_separate(self):',
                        b'    def test_generation_route_removed(self):', 1),
                }
                for label, changed in mutations.items():
                    with self.subTest(mutation=label):
                        target.write_bytes(changed)
                        with patch.dict(sys.modules, {module_name: module}):
                            with self.assertRaisesRegex(RuntimeError, 'addendum file SHA mismatch'):
                                bridge.route_suite(suite, stage, required=True)
                target.unlink()
                with patch.dict(sys.modules, {module_name: module}):
                    with self.assertRaisesRegex(RuntimeError, 'Missing or unsafe package dependency'):
                        bridge.route_suite(suite, stage, required=True)
                target.write_bytes(original)
                with patch.dict(sys.modules, {module_name: module}):
                    bridge.route_suite(suite, stage, required=True)
                class OtherVersionOwnedTest(unittest.TestCase):
                    def runTest(self):
                        self.ran = True
                OtherVersionOwnedTest.__module__ = 'test_edr_sync_v2'
                with patch.object(bridge, 'phase') as phase:
                    routed = bridge.route_suite(unittest.TestSuite([OtherVersionOwnedTest()]), stage, required=True)
                    result = unittest.TestResult()
                    routed.run(result)
                    self.assertTrue(result.wasSuccessful())
                    phase.assert_called_once_with(stage, 'python', 'local')
                with patch.dict(sys.modules, {module_name: module}):
                    with self.assertRaisesRegex(RuntimeError, 'Missing version-routed'):
                        bridge.route_suite(unittest.TestSuite(), stage, required=True)
                external = Path(folder) / 'outside.py'
                external.write_bytes(original)
                module.__file__ = str(external)
                with patch.dict(sys.modules, {module_name: module}):
                    with self.assertRaisesRegex(RuntimeError, 'loaded outside delivered staging'):
                        bridge.route_suite(suite, stage, required=True)
                history_name = next(name for name, item in manifest['history_snapshot']['files'].items()
                                    if item['delivery'] == 'candidate')
                history_file = stage / history_name
                history_original = history_file.read_bytes()
                history_file.unlink()
                with self.assertRaisesRegex(RuntimeError, 'Missing or unsafe package dependency'):
                    bridge.validate_addendum(stage)
                history_file.write_bytes(history_original)
            finally:
                target.write_bytes(original)

    def test_stock_messages_delegate_rejects_tampered_staged_current_test(self):
        relative = Path('validation/local_release_20260911/test_nazk_authority_request_integrity.py')
        original_stage = bridge.stage
        mutations = {
            'body replaced by pass': lambda raw: b'import unittest\nclass NazkAuthorityRequestIntegrityTests:\n'
                b'    def test_generation_route_uses_tasks_manage_and_direction_is_separate(self):\n        pass\n',
            'required assertion changed': lambda raw: raw.replace(
                b"self.assertEqual(auth_access.permission_key('POST', path), 'tasks.manage')",
                b"self.assertEqual('pass', 'pass')", 1),
            'current test removed': lambda raw: raw.replace(
                b'    def test_generation_route_uses_tasks_manage_and_direction_is_separate(self):',
                b'    def test_generation_route_removed(self):', 1),
        }
        temp_root = Path(os.environ.get('PQM_V311_TEMP_ROOT') or self.source.parent).resolve()
        for label, mutate in mutations.items():
            with self.subTest(mutation=label):
                with tempfile.TemporaryDirectory(prefix='pqm-v311-child-mutation-', dir=temp_root) as folder:
                    evidence = Path(folder) / 'evidence'

                    def stage_then_mutate(source, target, *, baseline=False):
                        result = original_stage(source, target, baseline=baseline)
                        delivered = target / relative
                        if label == 'current test removed':
                            delivered.unlink()
                        else:
                            delivered.write_bytes(mutate(delivered.read_bytes()))
                        return result

                    with patch.object(bridge, 'stage', side_effect=stage_then_mutate):
                        with self.assertRaisesRegex(RuntimeError, 'test phase failed: validation/run_messages_integrated_v1_history_addendum.py'):
                            bridge.run_script(self.source, 'validation/run_messages_integrated_v1_history_addendum.py',
                                evidence=evidence, arguments=('--history-only',))

    def test_pinned_messages_history_bundle_materializes_exact_git_tree(self):
        temp_root = Path(os.environ.get('PQM_V311_TEMP_ROOT') or self.source.parent).resolve()
        with tempfile.TemporaryDirectory(prefix='pqm-v311-history-bundle-', dir=temp_root) as folder:
            snapshot = Path(folder) / 'snapshot'
            count = messages_addendum.extract_history_snapshot(self.source, snapshot)
            self.assertEqual(721, count)
            self.assertFalse((snapshot / '.git').exists())
            names = {item.relative_to(snapshot).as_posix() for item in snapshot.rglob('*') if item.is_file()}
            self.assertEqual(set(bridge.validate_addendum(self.source)['history_snapshot']['files']), names)
            self.assertFalse((snapshot / '.git').exists())

    def test_pinned_messages_history_bundle_rejects_missing_corrupt_and_substituted_data(self):
        manifest = bridge.validate_addendum(self.source)
        with self.assertRaisesRegex(RuntimeError, 'snapshot schema'):
            bridge.validate_history_snapshot({'history_snapshot': {}})
        missing = json.loads(json.dumps(manifest))
        missing['history_snapshot']['files'].pop(next(iter(missing['history_snapshot']['files'])))
        with self.assertRaisesRegex(RuntimeError, 'snapshot index'):
            bridge.validate_history_snapshot(missing)
        corrupt = json.loads(json.dumps(manifest))
        corrupt['history_snapshot']['delta_zip_base64'] = corrupt['history_snapshot']['delta_zip_base64'][8:]
        with self.assertRaisesRegex(RuntimeError, 'delta SHA mismatch'):
            bridge.validate_history_snapshot(corrupt)
        substituted = json.loads(json.dumps(manifest))
        snapshot = substituted['history_snapshot']
        archive = base64.b64decode(snapshot['delta_zip_base64'])
        with zipfile.ZipFile(io.BytesIO(archive)) as source:
            members = {item.filename: source.read(item) for item in source.infolist()}
        name = next(iter(members))
        data = bytearray(members[name]); data[0] ^= 1; members[name] = bytes(data)
        rebuilt = io.BytesIO()
        with zipfile.ZipFile(rebuilt, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as target:
            for item, content in sorted(members.items()): target.writestr(item, content)
        changed = rebuilt.getvalue()
        snapshot['delta_zip_base64'] = base64.b64encode(changed).decode('ascii')
        snapshot['delta_zip_sha256'] = hashlib.sha256(changed).hexdigest()
        with self.assertRaisesRegex(RuntimeError, 'delta blob mismatch'):
            bridge.validate_history_snapshot(substituted)

if __name__ == '__main__':
    unittest.main(verbosity=2)
