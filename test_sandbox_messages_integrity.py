"""Current full-tree mutation checks plus immutable c246edef historical coverage."""
import ast
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
import messages_integrity as messages
from validation.local_release_20260911 import sandbox_protocol_integrity_variant as guard

ROOT=guard.ROOT


class MessagesIntegrityTests(unittest.TestCase):
    def test_exact_additive_variant_and_immutable_history(self):
        contracts=guard.load_contracts()
        self.assertEqual(34,len(contracts))
        current=contracts[-1]
        self.assertEqual(messages.VARIANT,current['variant_id'])
        self.assertEqual(messages.BASELINE,current['baseline_sha'])
        self.assertTrue(guard.manifest_tree_matches(current))
        historical=messages.historical_guard(ROOT)
        self.assertEqual(contracts[:-1],historical.load_contracts())
        self.assertTrue(historical.manifest_tree_matches(historical.load_contracts()[-1]))
        for path in ROOT.glob('*.json'):
            if path.name in current['parent_files']:
                with zipfile.ZipFile(ROOT/current['parent_fixture']) as archive:
                    self.assertEqual(archive.read(path.name).replace(b'\r\n',b'\n'),path.read_bytes().replace(b'\r\n',b'\n'),path.name)

    def test_every_pinned_file_one_byte_mutation_is_rejected(self):
        current=guard.load_contracts()[-1]
        names=set().union(*(set(current[section]) for section in ('product_files','guarded_files','protected_files')))
        with tempfile.TemporaryDirectory(dir=ROOT/'validation') as tmp:
            tree=Path(tmp)
            for name in names:
                target=tree/name;target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes((ROOT/name).read_bytes())
            self.assertTrue(guard.manifest_tree_matches(current,tree))
            for name in sorted(names):
                target=tree/name
                # Mutate in place, keeping large immutable fixture copies bounded.
                with target.open('r+b') as stream:
                    original=stream.read(1);stream.seek(0);stream.write(bytes([original[0]^1]))
                with self.subTest(name=name):self.assertFalse(guard.manifest_tree_matches(current,tree))
                with target.open('r+b') as stream:stream.write(original)
            self.assertTrue(guard.manifest_tree_matches(current,tree))

    def test_partial_forged_baseline_and_arbitrary_hash_are_rejected(self):
        current=guard.load_contracts()[-1]
        for mutation in ('partial','sha','baseline','variant'):
            fake=copy.deepcopy(current)
            if mutation=='partial':fake['guarded_files'].pop(next(iter(fake['guarded_files'])))
            if mutation=='sha':fake['product_files']['chat_ui.js']['sha256']='0'*64
            if mutation=='baseline':fake['baseline_sha']='0'*40
            if mutation=='variant':fake['variant_id']='anything'
            with self.subTest(mutation=mutation):self.assertFalse(guard.manifest_tree_matches(fake))

    def test_no_unrelated_server_functions_or_components_changed(self):
        current=guard.load_contracts()[-1]
        with zipfile.ZipFile(ROOT/current['parent_fixture']) as archive:
            old=ast.parse(archive.read('server.py').decode('utf-8-sig'))
            new=ast.parse((ROOT/'server.py').read_text(encoding='utf-8-sig'))
            def functions(tree):
                result={node.name:ast.dump(node,include_attributes=False) for node in tree.body
                        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef))}
                for node in tree.body:
                    if isinstance(node,ast.ClassDef):
                        for method in node.body:
                            if isinstance(method,ast.FunctionDef):result[node.name+'.'+method.name]=ast.dump(method,include_attributes=False)
                return result
            a,b=functions(old),functions(new)
            changed={key for key in set(a)|set(b) if a.get(key)!=b.get(key)}
            self.assertEqual({'init_db','mutation_allowed','Handler._do_GET','Handler._do_POST','Handler._authorize'},changed)
            for name in ['app.js','auth_access.py','auth_ui.js','scheduler_runtime.py','nazk_workflow.py',
                         'operational_tasks.py','google_writer_execution.py','table_widths_ui.js',
                         'violation_protocol_docx.py','theme.css','styles.css','protocol_template.py']:
                self.assertEqual(archive.read(name).replace(b'\r\n',b'\n'),(ROOT/name).read_bytes().replace(b'\r\n',b'\n'),name)


if __name__=='__main__':unittest.main()
