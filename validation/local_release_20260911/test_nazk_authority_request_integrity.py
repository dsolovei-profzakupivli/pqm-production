"""Additive, exact integrity contract for the approved NAZK authority request."""
import ast
import hashlib
import inspect
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import auth_access
import server
from validation.local_release_20260911 import sandbox_protocol_integrity_variant as history

ROOT = history.ROOT
MANIFEST_RELATIVE = 'validation/fixtures/nazk_authority_request_v1.json'
MANIFEST_SHA256 = '81d7ccba8c000eb7bd585280e64db342b6c90d825fcf217ba0e7c0db37474eaf'
BASELINE_ARCHIVE = 'validation/fixtures/nazk_authority_parent_c246.zip'
TEXT_SUFFIXES = {'.css', '.html', '.js', '.json', '.md', '.py', '.txt', '.yaml', '.yml'}


def sha256(content):
    return hashlib.sha256(content).hexdigest()


def sha256_matches(content, expected, *, text=False):
    hashes = {sha256(content)}
    if text:
        lf = content.replace(b'\r\n', b'\n')
        crlf = lf.replace(b'\n', b'\r\n')
        hashes.update((sha256(lf), sha256(crlf)))
    return expected in hashes


def read_manifest(root=ROOT):
    raw = (Path(root) / MANIFEST_RELATIVE).read_bytes()
    if not sha256_matches(raw, MANIFEST_SHA256, text=True):
        raise AssertionError('NAZK authority-request additive manifest hash mismatch')
    manifest = json.loads(raw)
    if (manifest.get('variant_id') != 'pqm_sandbox_nazk_authority_request_v1'
            or manifest.get('baseline_sha') != 'c246edefaa676d137d3f38d40f18d039f7b5bac2'):
        raise AssertionError('Unexpected NAZK authority-request integrity identity')
    return manifest


def manifest_tree_matches(manifest, root):
    for section in ('product_files', 'approved_documents', 'guarded_files'):
        for relative, expected in manifest.get(section, {}).items():
            try:
                content = (Path(root) / relative).read_bytes()
            except OSError:
                return False
            if not sha256_matches(content, expected,
                                  text=Path(relative).suffix.lower() in TEXT_SUFFIXES):
                return False
    return True


def function_ast(source, names):
    tree = ast.parse(source.decode('utf-8-sig'))
    functions = {node.name: node for node in tree.body
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    return {name: ast.dump(functions[name], include_attributes=False) for name in names}


class NazkAuthorityRequestIntegrityTests(unittest.TestCase):
    def test_crlf_and_lf_have_the_same_pinned_text_identity(self):
        manifest = read_manifest()
        for section in ('product_files', 'approved_documents', 'guarded_files'):
            for relative, expected in manifest[section].items():
                if Path(relative).suffix.lower() not in TEXT_SUFFIXES:
                    continue
                content = (ROOT / relative).read_bytes()
                lf = content.replace(b'\r\n', b'\n')
                crlf = lf.replace(b'\n', b'\r\n')
                with self.subTest(file=relative):
                    self.assertTrue(sha256_matches(lf, expected, text=True))
                    self.assertTrue(sha256_matches(crlf, expected, text=True))

    def test_content_addition_deletion_and_json_value_mutation_are_rejected(self):
        raw = (ROOT / MANIFEST_RELATIVE).read_bytes()
        self.assertFalse(sha256_matches(raw + b'X', MANIFEST_SHA256, text=True))
        self.assertFalse(sha256_matches(raw[1:], MANIFEST_SHA256, text=True))
        changed_value = raw.replace(b'c246edefaa676d137d3f38d40f18d039f7b5bac2',
                                    b'd246edefaa676d137d3f38d40f18d039f7b5bac2', 1)
        self.assertNotEqual(raw, changed_value)
        self.assertFalse(sha256_matches(changed_value, MANIFEST_SHA256, text=True))

    def test_exact_additive_manifest_and_approved_docx_gold_masters(self):
        manifest = read_manifest()
        self.assertEqual(set(manifest), {'variant_id', 'baseline_sha', 'product_files',
                                         'approved_documents', 'guarded_files'})
        self.assertEqual(set(manifest['product_files']), {
            'app.js', 'metadata/runtime_templates.v1.json', 'metadata/template_fields.v1.json',
            'operational_tasks.py', 'protocol_template.py', 'server.py', 'task_documents.py'})
        self.assertEqual(set(manifest['approved_documents']), {
            'templates/nazk_authority_request.docx', 'templates/nazk_supplier_request.docx',
            'artifacts/nazk_authority_request_samples/Запит_до_НАЗК_ФОП_Салій_зразок.docx',
            'artifacts/nazk_authority_request_samples/Запит_до_НАЗК_юридична_особа_синтетичний_зразок.docx',
            'artifacts/rendered/Запит_до_НАЗК_ФОП_Салій_зразок.pdf',
            'artifacts/rendered/Запит_до_НАЗК_юридична_особа_синтетичний_зразок.pdf',
            'artifacts/rendered/nazk_authority_request.pdf'})
        self.assertTrue(manifest_tree_matches(manifest, ROOT))

    def test_single_byte_mutations_of_every_pinned_file_are_rejected(self):
        manifest = read_manifest()
        files = set().union(*(set(manifest[key]) for key in
                              ('product_files', 'approved_documents', 'guarded_files')))
        with tempfile.TemporaryDirectory(dir=ROOT / 'validation') as temporary:
            tree = Path(temporary)
            for relative in files:
                target = tree / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / relative).read_bytes())
            self.assertTrue(manifest_tree_matches(manifest, tree))
            for relative in sorted(files):
                with self.subTest(path=relative):
                    target = tree / relative
                    original = target.read_bytes()
                    mutated = bytearray(original)
                    mutated[0] ^= 1
                    target.write_bytes(mutated)
                    self.assertFalse(manifest_tree_matches(manifest, tree))
                    target.write_bytes(original)
                    self.assertTrue(manifest_tree_matches(manifest, tree))

    def test_changed_manifest_bytes_are_rejected(self):
        read_manifest()
        with tempfile.TemporaryDirectory(dir=ROOT / 'validation') as temporary:
            tree = Path(temporary)
            target = tree / MANIFEST_RELATIVE
            target.parent.mkdir(parents=True)
            target.write_bytes((ROOT / MANIFEST_RELATIVE).read_bytes() + b' ')
            with self.assertRaisesRegex(AssertionError, 'manifest hash mismatch'):
                read_manifest(tree)

    def test_nazk_workflow_qualification_and_scheduler_logic_match_parent(self):
        manifest = read_manifest()
        with zipfile.ZipFile(ROOT / BASELINE_ARCHIVE) as archive:
            baseline = {name: archive.read(name) for name in
                        ('nazk_workflow.py', 'supplier_activity.py', 'scheduler_runtime.py',
                         'operational_tasks.py', 'server.py')}
        for relative in ('nazk_workflow.py', 'supplier_activity.py', 'scheduler_runtime.py'):
            with self.subTest(file=relative):
                self.assertEqual((ROOT / relative).read_bytes(), baseline[relative])
                self.assertIn(relative, manifest['guarded_files'])
        operational_functions = {
            'reconcile_stale_nazk_tasks', 'reconcile_stale_nazk_tasks_after_prozorro_sync',
            'reconcile_irrelevant_nazk_managers', 'materialize_nazk_tasks',
            'reconcile_duplicate_nazk_tasks', 'reconcile_amcu_after_qualification_sync',
            'reconcile_termination_after_qualification_sync', 'build', 'record_channel_sent',
        }
        self.assertEqual(function_ast((ROOT / 'operational_tasks.py').read_bytes(), operational_functions),
                         function_ast(baseline['operational_tasks.py'], operational_functions))
        self.assertEqual(function_ast((ROOT / 'server.py').read_bytes(),
                                      {'nazk_registry_scheduler', 'prozorro_scheduler',
                                       'violation_reports_scheduler', '_trigger_scheduler_job'}),
                         function_ast(baseline['server.py'],
                                      {'nazk_registry_scheduler', 'prozorro_scheduler',
                                       'violation_reports_scheduler', '_trigger_scheduler_job'}))

    def test_generation_route_uses_tasks_manage_and_direction_is_separate(self):
        path = '/api/operational-tasks/' + ('a' * 32) + '/documents/nazk-authority-request'
        self.assertEqual(auth_access.permission_key('POST', path), 'tasks.manage')
        self.assertTrue(server.mutation_allowed('admin', 'POST', path))
        self.assertFalse(server.mutation_allowed('viewer', 'POST', path))
        tasks_manage = next(permission for permission in auth_access.PERMISSIONS
                            if permission[0] == 'tasks.manage')
        self.assertTrue(tasks_manage[3])  # Officer default grant remains explicit and permission-gated.
        self.assertIn("self.auth_role == 'officer' and permission", inspect.getsource(server.Handler._dispatch))
        source = (ROOT / 'server.py').read_text(encoding='utf-8')
        self.assertIn('documents/nazk-authority-request', source)
        self.assertIn('task_documents.generate_authority', source)
        self.assertIn('/documents/nazk-authority-request', (ROOT / 'app.js').read_text(encoding='utf-8'))
        sent = (ROOT / 'operational_tasks.py').read_text(encoding='utf-8')
        self.assertIn('def record_channel_sent(', sent)
        self.assertIn('nazk_evidence.record_channel(con,check_id,channel,payload,actor', sent)


if __name__ == '__main__':
    unittest.main()
