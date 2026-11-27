"""Routing acceptance: native filesystem/subprocess, no live config or data."""
import ast
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import bridge
from routing import CONTRACT, ENTRYPOINTS, MODULES, SUPERSEDED

SOURCE=Path(os.environ['PQM_V311_SOURCE_ROOT']).resolve()

class BridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        protected=Path(os.environ.get('PQM_V311_TEMP_ROOT') or tempfile.gettempdir()).resolve()
        cls.temp=tempfile.TemporaryDirectory(prefix='pqm-v311-route-tests-',dir=protected)
        cls.addClassCleanup(cls.temp.cleanup)
        cls.base=Path(cls.temp.name)
        child_temp=cls.base/'bridge-temp';child_temp.mkdir()
        # Nested bridge invocations need a distinct sibling temp root: the
        # bridge intentionally rejects a temp root that contains its source.
        os.environ['PQM_V311_TEMP_ROOT']=str(child_temp)
        cls.current=cls.base/'current';cls.current.mkdir()
        bridge.stage(SOURCE,cls.current)
        cls.historical=cls.base/'historical';cls.historical.mkdir()
        bridge.stage(SOURCE,cls.historical,baseline=True)

    @contextmanager
    def mutation(self,name):
        file=self.current/name;raw=file.read_bytes()
        try:
            file.write_bytes(raw+b'\n# negative mutation\n')
            yield file
        finally:file.write_bytes(raw)

    def cli(self,entry='local',cwd=None,extra=()):
        env=bridge.child_environment(self.current,self.base,self.base/'evidence')
        env['PATH']=str(self.base/'no-programs')
        return subprocess.run([sys.executable,'-B',str(self.current/'validation/v31_1/bridge.py'),
            '--entrypoint',entry,'--phase','check','--root',str(self.current),*extra],
            cwd=cwd or self.base,env=env,capture_output=True,text=True)

    def test_all_entrypoint_contracts_without_git(self):
        self.assertFalse((self.current/'.git').exists())
        for entry in ENTRYPOINTS:
            with self.subTest(entry=entry):
                result=self.cli(entry);self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_actual_stock_entrypoint_preflights(self):
        for script in ('validation/run_local_release.py','validation/docker_release_gate_csv_ui_v3.py','validation/docker_release_gate.py'):
            result=subprocess.run([sys.executable,'-B',str(self.current/script),'--v31-1-preflight'],
                cwd=self.base,env=bridge.child_environment(self.current,self.base,self.base/'evidence'),capture_output=True,text=True)
            self.assertEqual(result.returncode,0,script+'\n'+result.stdout+result.stderr)

    def test_file_database_cannot_receive_minimal_fixture_adapter(self):
        import sqlite3
        path=self.base/'unsupported.sqlite3'
        con=sqlite3.connect(path);con.execute('CREATE TABLE probe(value TEXT)');con.commit();con.close()
        before=bridge.sha(path.read_bytes())
        tree=ast.parse((self.current/'validation/v31_1/history_run.py').read_text(encoding='utf-8'))
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='adapted')
        original=unittest.mock.Mock(side_effect=AssertionError('Runtime fallback forbidden'))
        namespace={'original':original};exec(compile(ast.Module(body=[function],type_ignores=[]),'actual-fixture-adapter','exec'),namespace)
        con=sqlite3.connect(path)
        try:
            with self.assertRaisesRegex(RuntimeError,'restricted to explicit in-memory'):namespace['adapted'](con)
            self.assertFalse(con.execute('SELECT name FROM temp.sqlite_master').fetchall())
        finally:con.close()
        original.assert_not_called();self.assertEqual(bridge.sha(path.read_bytes()),before)

    def test_current_suite_executes_from_package_without_git_or_git_executable(self):
        env=bridge.child_environment(self.current,self.base,self.base/'nogit-evidence')
        env['PATH']=str(self.base/'no-programs')
        result=subprocess.run([sys.executable,'-B',str(self.current/'validation/v31_1/bridge.py'),
            '--entrypoint','local','--phase','unit','--root',str(self.current),'--evidence',str(self.base/'nogit-evidence')],
            cwd=self.base,env=env,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('Ran 45 tests',result.stdout+result.stderr)

    def test_uninitialized_and_initialized_cwd_without_git_executable(self):
        for initialized in (False,True):
            folder=self.base/('initialized' if initialized else 'empty');folder.mkdir()
            if initialized:
                git=folder/'.git';(git/'objects').mkdir(parents=True);(git/'refs/heads').mkdir(parents=True)
                (git/'HEAD').write_text('ref: refs/heads/synthetic\n')
                (git/'config').write_text('[core]\nrepositoryformatversion = 0\nbare = false\n')
            result=self.cli(cwd=folder);self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_unknown_contract_and_entrypoint_and_phase_fail(self):
        self.assertNotEqual(self.cli(extra=('--contract','unknown')).returncode,0)
        with self.assertRaisesRegex(RuntimeError,'Unknown Gate'):bridge.preflight(self.current,'unknown')
        with self.assertRaisesRegex(RuntimeError,'Unknown V31.1 phase'):bridge.phase(self.current,'unknown')

    def test_every_runtime_mutation_is_rejected(self):
        manifest=json.loads((self.current/'validation/v31_1/contract.json').read_text())
        for name in manifest['runtime_lf_sha256']:
            with self.subTest(file=name),self.mutation(name):
                with self.assertRaisesRegex(RuntimeError,'runtime SHA mismatch'):bridge.preflight(self.current)

    def test_each_new_runtime_module_is_required(self):
        for name in ('edr_monitoring_projection.py','edr_sync_comparison.py','edr_sync_identity.py'):
            file=self.current/name;hidden=file.with_suffix('.absent');file.rename(hidden)
            try:
                with self.assertRaisesRegex(RuntimeError,'Missing or unsafe'):bridge.preflight(self.current)
            finally:hidden.rename(file)

    def test_unknown_stock_local_selection_is_not_a_successful_empty_suite(self):
        result=subprocess.run([sys.executable,'-B',str(self.current/'validation/run_local_release.py'),'--unknown'],
            cwd=self.base,env=bridge.child_environment(self.current,self.base,self.base/'evidence'),capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Unknown Release Gate test selection',result.stderr)

    def test_missing_bridge_cannot_select_legacy_local_gate(self):
        file=self.current/'validation/v31_1/bridge.py';hidden=file.with_suffix('.absent');file.rename(hidden)
        try:
            result=subprocess.run([sys.executable,'-B',str(self.current/'validation/run_local_release.py'),'--v31-1-preflight'],
                cwd=self.base,env=bridge.child_environment(self.current,self.base,self.base/'evidence'),capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
        finally:hidden.rename(file)

    def test_missing_snapshot_blocks(self):
        file=self.current/bridge.ARCHIVE;hidden=file.with_suffix('.absent');file.rename(hidden)
        try:
            with self.assertRaisesRegex(RuntimeError,'Missing or unsafe'):bridge.preflight(self.current)
        finally:hidden.rename(file)

    def test_corrupted_snapshot_blocks(self):
        with self.mutation(bridge.ARCHIVE):
            with self.assertRaisesRegex(RuntimeError,'snapshot archive SHA mismatch'):bridge.preflight(self.current)

    def test_external_historical_archive_mutation_and_absence_block(self):
        with zipfile.ZipFile(self.current/bridge.ARCHIVE) as z:index=json.loads(z.read('V31_SNAPSHOT_INDEX.json'))
        name=min(index['external'],key=lambda n:(self.current/n).stat().st_size)
        with self.mutation(name):
            with self.assertRaisesRegex(RuntimeError,'snapshot member SHA mismatch'):bridge.preflight(self.current)
        file=self.current/name;hidden=file.with_suffix('.absent');file.rename(hidden)
        try:
            with self.assertRaisesRegex(RuntimeError,'Missing or unsafe'):bridge.preflight(self.current)
        finally:hidden.rename(file)

    def test_wrong_snapshot_identity_blocks_even_with_test_trust_anchor(self):
        path=self.current/'wrong.zip'
        with zipfile.ZipFile(path,'w') as z:
            z.comment=b'wrong';z.writestr('V31_SNAPSHOT_INDEX.json',json.dumps({'commit':'wrong','tree':'wrong','files':{}}))
        with patch.object(bridge,'ARCHIVE','wrong.zip'),patch.object(bridge.pins,'ARCHIVE_SHA256',bridge.sha(path.read_bytes())):
            with self.assertRaisesRegex(RuntimeError,'Wrong V31 snapshot identity'):bridge.validate_snapshot(self.current)
        path.unlink()

    def test_archive_traversal_and_duplicate_members_block(self):
        for names in (('../outside',),('same','same')):
            path=self.current/'wrong.zip'
            with zipfile.ZipFile(path,'w') as z:
                for name in names:z.writestr(name,b'x')
            with patch.object(bridge,'ARCHIVE','wrong.zip'),patch.object(bridge.pins,'ARCHIVE_SHA256',bridge.sha(path.read_bytes())):
                with self.assertRaises(RuntimeError):bridge.validate_snapshot(self.current)
            path.unlink()

    def test_current_mutation_fails_while_historical_integrity_passes(self):
        with self.mutation('edr_sync_v2.py'):
            result=subprocess.run([sys.executable,'-B','-m','unittest',
                'test_google_writer_integrated_candidate_integrity_v31'],cwd=self.historical,
                env=bridge.child_environment(self.current,self.base,self.base/'evidence'),capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertNotEqual(self.cli().returncode,0)

    def test_inventory_and_test_mutations_fail(self):
        for name in (bridge.INVENTORY,'validation/v31_1/test_current.py','validation/v31_1/history_run.py'):
            with self.subTest(file=name),self.mutation(name):
                with self.assertRaisesRegex(RuntimeError,'SHA mismatch'):bridge.preflight(self.current)

    def test_background_thread_error_is_a_gate_failure(self):
        file=self.base/'thread_failure.py'
        file.write_text("import threading\ndef crash():raise RuntimeError('synthetic thread failure')\nt=threading.Thread(target=crash);t.start();t.join()\n",encoding='utf-8')
        result=subprocess.run(bridge.monitored_command(file),cwd=self.current,
            env=bridge.child_environment(self.current,self.base,self.base/'evidence'),capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('uncaught exception in background thread',result.stdout+result.stderr)

    def test_test_error_propagates(self):
        with patch.object(bridge.subprocess,'run',return_value=subprocess.CompletedProcess([],1)):
            with self.assertRaisesRegex(RuntimeError,'test phase failed'):bridge.run_script(self.current,'validation/v31_1/test_current.py')

    def test_recursive_targets_and_temporary_base_inside_source_rejected(self):
        for destination in (self.current,self.current/'tmp',self.current.parent):
            with self.assertRaises(ValueError):bridge.validate_paths(self.current,destination)
        nested=self.current/'tmp';nested.mkdir(exist_ok=True)
        with patch.dict(os.environ,{'PQM_V311_TEMP_ROOT':str(nested)}):
            with self.assertRaisesRegex(RuntimeError,'outside and disjoint'):bridge.preflight(self.current)

    def test_stage_never_copies_evidence_or_old_temp_trees(self):
        for name in ('evidence','tmp-old','pqm-old-temp'):
            folder=self.current/name;folder.mkdir(exist_ok=True);(folder/'must-not-copy').write_text('sentinel')
        target=self.base/'filtered';target.mkdir()
        bridge.stage(self.current,target)
        for name in ('evidence','tmp-old','pqm-old-temp','.git'):
            self.assertFalse((target/name).exists(),name)

    def test_stock_package_staging_uses_explicit_files(self):
        import importlib.util
        sys.path.insert(0,str(self.current))
        try:
            spec=importlib.util.spec_from_file_location('v311_test_package',self.current/'validation/release_test_package.py')
            package=importlib.util.module_from_spec(spec);spec.loader.exec_module(package)
            manifest=package.load_package_manifest(self.current)
            target=self.base/'stock-staging';target.mkdir()
            package.stage_dynamic_package_files(self.current,target,self.current,manifest)
            self.assertTrue((target/'edr_sync_identity.py').is_file())
            self.assertTrue((target/'validation/v31_1/baseline_v31.zip').is_file())
            for name in ('evidence','tmp-old','pqm-old-temp','.git'):self.assertFalse((target/name).exists())
            with self.assertRaises(ValueError):package.stage_dynamic_package_files(self.current,self.current/'nested',self.current,manifest)
        finally:sys.path.pop(0)

    def test_routing_keeps_unrelated_tests_and_executes_checked_bridge_once(self):
        events=[]
        class A(unittest.TestCase):
            def runTest(self):raise AssertionError('Must run through current fixture bridge')
        A.__module__=MODULES[0]
        class B(unittest.TestCase):
            def runTest(self):events.append('unrelated')
        B.__module__='unrelated_current_suite'
        with patch.object(bridge,'phase') as call:
            suite=bridge.route_suite(unittest.TestSuite([A(),A(),B()]),self.current)
            self.assertEqual(suite.countTestCases(),2)
            result=unittest.TestResult();suite.run(result)
            self.assertTrue(result.wasSuccessful());self.assertEqual(events,['unrelated'])
            call.assert_called_once_with(self.current,'python','local')
        with self.assertRaisesRegex(RuntimeError,'Missing version-routed'):
            bridge.route_suite(unittest.TestSuite([B()]),self.current,required=True)
        with patch.object(bridge,'phase',side_effect=RuntimeError('negative routed failure')):
            result=unittest.TestResult();bridge.route_suite(unittest.TestSuite([A()]),self.current).run(result)
            self.assertFalse(result.wasSuccessful());self.assertEqual(len(result.errors),1)

    def test_external_temporary_tree_is_removed(self):
        with bridge.temporary(self.current) as folder:
            path=folder;self.assertNotIn(self.current,folder.parents);(folder/'own').write_text('synthetic')
        self.assertFalse(path.exists())

    def test_configured_protected_temporary_root_is_used_and_scoped(self):
        safe=self.base/'protected-temp';safe.mkdir(exist_ok=True)
        with patch.dict(os.environ,{'PQM_V311_TEMP_ROOT':str(safe)}):
            with bridge.temporary(self.current) as folder:
                self.assertEqual(folder.parent,safe.resolve())
                self.assertNotIn(self.current,folder.parents)

    def test_insufficient_disk_blocks(self):
        with patch.object(bridge.shutil,'disk_usage',return_value=type('Usage',(),{'free':1})()):
            with self.assertRaisesRegex(RuntimeError,'Insufficient'):bridge.preflight(self.current)

    def test_current_workflow_and_delegates_enforce_shared_bridge(self):
        workflow=(self.current/'.github/workflows/release-checks.yml').read_text(encoding='utf-8')
        commands=[line.strip() for line in workflow.splitlines() if 'validation/v31_1/bridge.py' in line and not line.lstrip().startswith('#')]
        self.assertEqual(len(commands),2)
        self.assertTrue(any('--entrypoint github --phase python' in c for c in commands))
        self.assertTrue(any('--entrypoint github --phase browser' in c for c in commands))
        self.assertLess(workflow.index('--phase python'),workflow.index('Install Playwright and Chromium'))
        self.assertGreater(workflow.index('--phase browser'),workflow.index('Install Playwright and Chromium'))
        for name,entry in (('validation/docker_release_gate.py','predeploy'),('validation/docker_release_gate_csv_ui_v3.py','container')):
            tree=ast.parse((self.current/name).read_text(encoding='utf-8'))
            fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
            commands=next(n.value for n in fn.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='commands' for t in n.targets))
            text=ast.unparse(commands.elts[0])
            self.assertIn('validation/v31_1/bridge.py',text);self.assertIn(entry,text);self.assertIn('python',text)
        source=(self.current/'validation/run_local_release.py').read_text(encoding='utf-8')
        self.assertIn('v311.route_suite(suite,ROOT',source)
        self.assertIn('refusing source-tree generation in V31.1',source)

    def test_legacy_delegate_isolated_and_unknown_token_fails(self):
        result=subprocess.run([sys.executable,'-B',str(self.current/'validation/document_release_history_v2.py'),
            '-v','validation.local_release_20260911.test_release_test_package'],cwd=self.base,
            env=bridge.child_environment(self.current,self.base,self.base/'legacy-evidence'),capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('Ran 7 tests',result.stdout+result.stderr)
        with patch.dict(os.environ,{'PQM_V311_INNER_LEGACY':'wrong'}):
            with self.assertRaisesRegex(RuntimeError,'Invalid legacy staging ownership'):
                bridge.legacy_entry(self.current,'validation/document_release_history_v2.py',['-v','test_missing'])
        with self.assertRaisesRegex(RuntimeError,'No legacy test selection'):
            bridge.legacy_entry(self.current,'validation/csv_ui_gate_history.py',[])

    def test_only_three_exact_tests_are_version_owned(self):
        self.assertEqual(len(SUPERSEDED),3)
        self.assertEqual(len(MODULES),7)
        tree=ast.parse((self.current/'validation/v31_1/test_current.py').read_text(encoding='utf-8'))
        names={'CurrentTests.'+n.name for n in ast.walk(tree) if isinstance(n,ast.FunctionDef)}
        for old,policy in SUPERSEDED.items():
            self.assertTrue(old.startswith('test_permanent_edr_sync_safety.PermanentSyncSafetyTests.'))
            self.assertTrue(policy['old'] and policy['new'])
            self.assertTrue(set(policy['regressions']).issubset(names))

    def test_supported_schema_check_remains_outside_fixture_adapter(self):
        source=(self.current/'validation/v31_1/test_current.py').read_text(encoding='utf-8')
        self.assertIn('test_supported_native_schema_requires_registry_summary_without_repair',source)
        self.assertIn('require_current_schema(path',source)
        adapter=(self.current/'validation/v31_1/history_run.py').read_text(encoding='utf-8')
        self.assertIn('restricted to explicit in-memory legacy fixtures',adapter)

if __name__=='__main__':unittest.main(verbosity=2)
