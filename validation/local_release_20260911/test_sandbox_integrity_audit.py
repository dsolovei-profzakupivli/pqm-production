"""Current Sandbox source guard, historical inputs and runner-order regressions."""
import ast
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from validation import sandbox_integrity_routes as routes

ROOT=Path(os.environ.get('PQM_RELEASE_SOURCE_ROOT') or Path(__file__).resolve().parents[2]).resolve()
MANIFEST_SHA256='c504c142dbd5ebeda060dc1afe5e414630d2f1b80fbce431aca1870357a85fc9'

class SandboxIntegrityAuditTests(unittest.TestCase):
    def test_current_tree_pins_and_negative_mutations(self):
        raw=(ROOT/'validation/sandbox_integrity_audit_v1.json').read_bytes()
        self.assertEqual(routes.digest(raw,'manifest.json'),MANIFEST_SHA256)
        manifest=json.loads(raw)
        for name,expected in manifest['current_files'].items():
            with self.subTest(file=name):
                data=(ROOT/name).read_bytes()
                self.assertEqual(routes.digest(data,name),expected)
                self.assertNotEqual(routes.digest(data+b'X',name),expected)
                self.assertNotEqual(routes.digest(data[:-1],name),expected)
                changed=bytearray(data);changed[len(changed)//2]^=1
                self.assertNotEqual(routes.digest(changed,name),expected)
        for name,expected in manifest['unchanged_files'].items():
            self.assertEqual(routes.digest((ROOT/name).read_bytes(),name),expected,name)

    def test_writer_business_logic_ast_is_identical_to_v28(self):
        manifest=json.loads((ROOT/'validation/sandbox_integrity_audit_v1.json').read_text())
        tree=ast.parse((ROOT/'supplier_registry_integration.py').read_text(encoding='utf-8-sig'))
        tree.body=[node for node in tree.body if not (isinstance(node,ast.FunctionDef) and node.name=='database_revision')]
        self.assertEqual(hashlib.sha256(ast.dump(tree,include_attributes=False).encode()).hexdigest(),manifest['writer_ast_except_revision'])
        import supplier_registry_integration as current
        self.assertEqual(routes.digest(Path(current.__file__).read_bytes(),'supplier_registry_integration.py'),
                         manifest['unchanged_files']['supplier_registry_integration.py'])

    def test_original_case_ids_and_methods_are_not_changed(self):
        module=importlib.import_module('test_google_writer_update_append_v2_integrity')
        suite=unittest.defaultTestLoader.loadTestsFromModule(module)
        def ids(node):
            if isinstance(node,unittest.TestSuite):return [identifier for child in node for identifier in ids(child)]
            return [node.id()]
        before=ids(suite)
        methods={name:value for name,value in vars(module.GoogleWriterUpdateAppendV2Integrity).items() if name.startswith('test_')}
        # The source may be the checked-out tree or a preflight-verified staging copy.
        module_root=Path(module.__file__).resolve().parent
        result=routes.route_integrity_suite(suite,ROOT,module_root=module_root)
        self.assertEqual(result,[(module.__name__,'writer_v2_v28')])
        self.assertEqual(ids(suite),before)
        self.assertEqual(len(before),7)
        self.assertEqual({name:value for name,value in vars(module.GoogleWriterUpdateAppendV2Integrity).items() if name.startswith('test_')},methods)
        self.assertEqual(module.MANIFEST,module.ROOT/'validation/local_release_20260911/google_writer_update_append_v2.json')

    def test_workflow_keeps_every_original_direct_group(self):
        manifest=json.loads((ROOT/'validation/sandbox_integrity_audit_v1.json').read_text())
        workflow=(ROOT/'.github/workflows/release-checks.yml').read_text()
        command=workflow.split(' -B validation/sandbox_integrity_routes.py -v '+chr(92)+'\n',1)[1].split('\n      - name:',1)[0]
        modules=[token for token in command.replace(chr(92),'').split()]
        self.assertEqual(modules,manifest['original_direct_modules']+['validation.local_release_20260911.test_sandbox_integrity_audit'])

    def test_actual_stage1_preflight_still_fails_closed_after_v2_setup(self):
        import validation.run_local_release as release
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);archive=root/'validation/fixtures/pqm_sync_ui_integrated_v2_0d7e059.zip'
            archive.parent.mkdir(parents=True);archive.write_bytes(b'fixture already staged')
            with patch.object(release,'ROOT',root),patch.object(release,'load_package_manifest',return_value={'pinned_release_files':{}}),\
                 patch.dict(os.environ,{'PQM_RELEASE_MODE':''}),patch.object(sys,'argv',['run_local_release.py','test_synthetic.py']):
                with self.assertRaisesRegex(FileNotFoundError,'runtime_memory.py'):
                    release.main()

    def test_changed_transport_archive_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/routes.ARCHIVE;path.parent.mkdir(parents=True)
            data=bytearray((ROOT/routes.ARCHIVE).read_bytes());data[-1]^=1;path.write_bytes(data)
            with self.assertRaisesRegex(AssertionError,'archive changed'):routes.read_archive(Path(folder))

    def test_unknown_module_is_not_routed(self):
        module=SimpleNamespace(__name__='unregistered_contract',ROOT=ROOT)
        self.assertIsNone(routes.bind_historical_module(module,ROOT))
        self.assertEqual(module.ROOT,ROOT)

    def test_changed_historical_view_is_rejected_without_repair(self):
        index,_=routes.read_archive(ROOT)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name in index['contexts']['writer_v2_v28']:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,path)
            path=root/routes.ARCHIVE;path.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/routes.ARCHIVE,path)
            view=routes.historical_view(root,'writer_v2_v28')
            target=view/'supplier_registry_integration.py';original=target.read_bytes();changed=bytes([original[0]^1])+original[1:];target.write_bytes(changed)
            with self.assertRaisesRegex(AssertionError,'Historical view changed'):routes.historical_view(root,'writer_v2_v28')
            self.assertEqual(target.read_bytes(),changed)

if __name__=='__main__':unittest.main()
