"""Current route infrastructure and immutable-contract ancestry regressions."""
import hashlib
import importlib
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest

from validation import production_integrity_routes as routes

ROOT=Path.cwd()
MANIFEST_SHA256='3b26cf9433c40539cf55eae8d98147e388925141047906d070350f942e2e3449'

class IntegrityRouteTests(unittest.TestCase):
    def test_current_additive_contract_and_negative_mutations(self):
        raw=(ROOT/'validation/production_integrity_routes_v1.json').read_bytes()
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

    def test_original_and_current_resolver_are_explicitly_distinct(self):
        root=routes.historical_view(ROOT,'messages_f9eb8ed')
        name='production_integrity_overlay.py'
        self.assertEqual(routes.digest((root/name).read_bytes(),name),'812529b1029e6518402a90bc7b95c09d4b14c72a2030c17f0b094508c1dc9d6e')
        self.assertEqual(routes.digest((ROOT/name).read_bytes(),name),'0cc7afcb3dd061762f575e443031d7ebb9c37445923ee0c7b64b2ab6ba37e5d0')
        self.assertNotEqual(root,ROOT)

    def test_routing_preserves_all_original_case_ids_and_methods(self):
        module=importlib.import_module('validation.local_release_20260911.test_production_nazk_messages_integrity')
        suite=unittest.defaultTestLoader.loadTestsFromModule(module)
        def ids(node):
            if isinstance(node,unittest.TestSuite):
                return [identifier for child in node for identifier in ids(child)]
            return [node.id()]
        before=ids(suite)
        methods={name:value for name,value in vars(module.ProductionNazkMessagesIntegrityTests).items() if name.startswith('test_')}
        source=(Path(module.__file__)).read_bytes()
        result=routes.route_integrity_suite(suite,ROOT)
        self.assertEqual(result,[(module.__name__,'messages_f9eb8ed')])
        self.assertEqual(ids(suite),before)
        self.assertEqual(len(before),3)
        self.assertEqual({name:value for name,value in vars(module.ProductionNazkMessagesIntegrityTests).items() if name.startswith('test_')},methods)
        self.assertEqual(Path(module.__file__).read_bytes(),source)

    def test_unknown_module_is_not_routed(self):
        module=SimpleNamespace(__name__='unregistered_integrity_contract',ROOT=ROOT)
        self.assertIsNone(routes.bind_historical_module(module,ROOT))
        self.assertEqual(module.ROOT,ROOT)

    def test_changed_transport_archive_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/routes.ARCHIVE
            path.parent.mkdir(parents=True)
            data=bytearray((ROOT/routes.ARCHIVE).read_bytes());data[-1]^=1
            path.write_bytes(data)
            with self.assertRaisesRegex(AssertionError,'archive changed'):
                routes.read_archive(Path(folder))

    def test_changed_assertion_source_cannot_be_routed(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            path=root/routes.ARCHIVE;path.parent.mkdir(parents=True)
            shutil.copyfile(ROOT/routes.ARCHIVE,path)
            test=root/'test_production_nazk_messages_integrity.py'
            test.write_text('changed assertions')
            module=SimpleNamespace(__name__=test.stem,__file__=str(test),ROOT=root)
            with self.assertRaisesRegex(AssertionError,'contract source changed'):
                routes.bind_historical_module(module,root)
            self.assertEqual(module.ROOT,root)

    def test_corrupted_cached_view_is_rejected_not_repaired(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            path=root/routes.ARCHIVE;path.parent.mkdir(parents=True)
            shutil.copyfile(ROOT/routes.ARCHIVE,path)
            view=routes.historical_view(root,'messages_f9eb8ed')
            target=view/'production_integrity_overlay.py'
            original=target.read_bytes();changed=bytes([original[0]^1])+original[1:]
            target.write_bytes(changed)
            with self.assertRaisesRegex(AssertionError,'Historical view changed'):
                routes.historical_view(root,'messages_f9eb8ed')
            self.assertEqual(target.read_bytes(),changed)

if __name__=='__main__':unittest.main()
