"""Current full-tree mutation checks plus immutable c246edef historical coverage."""
import ast
import copy
import hashlib
import json
import shutil
from pathlib import Path
import tempfile
import unittest
import zipfile
import messages_integrity as messages
import messages_crlf_test_integrity as crlf_contract
import test_sandbox_nazk_messages_integrated_integrity as integrated
from validation.local_release_20260911 import sandbox_protocol_integrity_variant as guard

ROOT=guard.ROOT
BASELINE_FIXTURE='validation/fixtures/edr_google_nazk_baseline_40da.zip'
BASELINE_FIXTURE_SHA256='3e4675426df956b2b7641352ea4d6b900108f5ba418deed7f389cc8deb75e790'
BASELINE_MEMBERS={'edr_sync_v2.py','server.py','test_sandbox_messages_integrity.py'}
MESSAGES_V1_FIXTURE='validation/fixtures/messages_integrated_v1_overrides.zip'
MESSAGES_V1_FIXTURE_SHA256='78287b12633f82c3a366e2377d35eec4a0b96ecba28f2bfd5ea3e79982ea7928'
MESSAGES_V1_MEMBERS={
    'chat_annotations.css','chat_annotations.py','index.html',
    'test_sandbox_nazk_messages_integrated_integrity.py',
    'validation/chat_messages_browser.cjs',
    'validation/local_release_20260911/test_chat_annotations.py',
    'validation/local_release_20260911/test_chat_annotations_http.py',
    'validation/run_local_release.py',
}


def integrated_messages_baseline():
    """Build the exact 40da messages tree without EDR candidate overlays."""
    temporary=tempfile.TemporaryDirectory(prefix='pqm-messages-40da-overlay-',dir=ROOT/'validation')
    tree=Path(temporary.name)
    for relative in integrated.EXPECTED_FILES:
        target=tree/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/relative,target)
    fixture=ROOT/BASELINE_FIXTURE
    raw=fixture.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=BASELINE_FIXTURE_SHA256:
        temporary.cleanup()
        raise AssertionError('EDR baseline overlay fixture SHA mismatch')
    with zipfile.ZipFile(fixture) as archive:
        members={item.filename for item in archive.infolist() if not item.is_dir()}
        if members!=BASELINE_MEMBERS:
            temporary.cleanup()
            raise AssertionError('Unexpected EDR baseline overlay members')
        for relative in sorted(members):
            target=tree/relative
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(archive.read(relative))
    messages_fixture=ROOT/MESSAGES_V1_FIXTURE
    messages_bytes=messages_fixture.read_bytes()
    if hashlib.sha256(messages_bytes).hexdigest()!=MESSAGES_V1_FIXTURE_SHA256:
        temporary.cleanup()
        raise AssertionError('Historical Messages v1 overlay fixture SHA mismatch')
    with zipfile.ZipFile(messages_fixture) as archive:
        members={item.filename for item in archive.infolist() if not item.is_dir()}
        if members!=MESSAGES_V1_MEMBERS:
            temporary.cleanup()
            raise AssertionError('Unexpected Messages v1 overlay members')
        for relative in sorted(members):
            target=tree/relative
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(archive.read(relative))
    return temporary,tree


class MessagesIntegrityTests(unittest.TestCase):
    def test_exact_additive_variant_and_immutable_history(self):
        contracts=guard.load_contracts()
        self.assertEqual(35,len(contracts))
        current=contracts[-2]
        self.assertEqual(messages.VARIANT,current['variant_id'])
        self.assertEqual(messages.BASELINE,current['baseline_sha'])
        self.assertFalse(guard.manifest_tree_matches(current))
        temporary,tree=integrated_messages_baseline()
        try:
            self.assertTrue(integrated.manifest_tree_matches(tree))
        finally:
            temporary.cleanup()
        historical=messages.historical_guard(ROOT)
        self.assertEqual(contracts[:-2],historical.load_contracts())
        self.assertTrue(historical.manifest_tree_matches(historical.load_contracts()[-1]))
        for path in ROOT.glob('*.json'):
            if path.name in current['parent_files']:
                with zipfile.ZipFile(ROOT/current['parent_fixture']) as archive:
                    self.assertEqual(archive.read(path.name).replace(b'\r\n',b'\n'),path.read_bytes().replace(b'\r\n',b'\n'),path.name)

    def test_every_pinned_file_one_byte_mutation_is_rejected(self):
        current=integrated.read_manifest()
        names=set(current['files'])
        baseline_temp,baseline_tree=integrated_messages_baseline()
        try:
          with tempfile.TemporaryDirectory(dir=ROOT/'validation') as tmp:
            tree=Path(tmp)
            for name in names:
                target=tree/name;target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes((baseline_tree/name).read_bytes())
            self.assertTrue(integrated.manifest_tree_matches(tree))
            for name in sorted(names):
                target=tree/name
                # Mutate in place, keeping large immutable fixture copies bounded.
                with target.open('r+b') as stream:
                    original=stream.read()
                    offset=next((index for index,value in enumerate(original) if value not in (10,13)),0)
                    stream.seek(offset);stream.write(bytes([original[offset]^1]))
                with self.subTest(name=name):self.assertFalse(integrated.manifest_tree_matches(tree))
                with target.open('r+b') as stream:stream.write(original)
            self.assertTrue(integrated.manifest_tree_matches(tree))
        finally:
            baseline_temp.cleanup()

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
        temporary,tree=integrated_messages_baseline()
        try:
          with zipfile.ZipFile(ROOT/current['parent_fixture']) as archive:
            old=ast.parse(archive.read('server.py').decode('utf-8-sig'))
            new=ast.parse((tree/'server.py').read_text(encoding='utf-8-sig'))
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
            for name in ['auth_access.py','auth_ui.js','scheduler_runtime.py','nazk_workflow.py',
                         'google_writer_execution.py','table_widths_ui.js',
                         'violation_protocol_docx.py','theme.css','styles.css']:
                self.assertEqual(archive.read(name).replace(b'\r\n',b'\n'),(ROOT/name).read_bytes().replace(b'\r\n',b'\n'),name)
        finally:
            temporary.cleanup()


if __name__=='__main__':unittest.main()
