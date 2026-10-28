"""Additive integrity checks for the NAZK template in the sandbox smoke test."""
import ast
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

from validation.local_release_20260911 import sandbox_protocol_integrity_variant as history

ROOT = history.ROOT
MANIFEST_NAME = 'test_sandbox_smoke_nazk_authority_v1.json'
MANIFEST_SHA256 = '2f7e9d77e79dba530f629a26dda0190ca4b99b13f4fe6dd3f2e3ec2cc7a069a7'
EXPECTED_KEYS = {
    'warning', 'decline_p49_1_2', 'decline_p49_3', 'application_protocol',
    'nazk_supplier_request', 'nazk_authority_request', 'amcu_exclusion_protocol',
    'termination_exclusion_protocol', 'decline_individual_review',
}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def smoke_path():
    candidates = []
    for entry in sys.path:
        base = Path(entry or Path.cwd()).resolve()
        candidates.extend((base / 'sandbox_smoke.py', base / 'validation' / 'sandbox_smoke.py'))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise AssertionError('validation/sandbox_smoke.py is unavailable to the release suite')


def method_node(source):
    tree = ast.parse(source.decode('utf-8-sig'))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == 'SandboxHTTP':
            for member in node.body:
                if isinstance(member, ast.FunctionDef) and member.name == 'test_11_offline_features_and_modules':
                    return member
    raise AssertionError('protected sandbox smoke test method is missing')


def expected_keys(source):
    method = method_node(source)
    for node in method.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == 'expected_template_keys'
                for target in node.targets):
            if not isinstance(node.value, ast.Set):
                raise AssertionError('runtime template expectation must remain an exact set')
            return {element.value for element in node.value.elts
                    if isinstance(element, ast.Constant) and isinstance(element.value, str)}
    raise AssertionError('exact runtime template key set is missing')


def contract_matches(source, manifest):
    try:
        return (
            sha256(source) == manifest['smoke_sha256']
            and expected_keys(source) == set(manifest['expected_template_keys'])
            and sha256(ast.dump(method_node(source), include_attributes=False).encode())
                == manifest['protected_method_ast_sha256']
        )
    except (AssertionError, KeyError, SyntaxError, UnicodeDecodeError):
        return False


def read_manifest(root=ROOT):
    raw = (Path(root) / MANIFEST_NAME).read_bytes()
    if sha256(raw) != MANIFEST_SHA256:
        raise AssertionError('Sandbox smoke additive manifest hash mismatch')
    manifest = json.loads(raw)
    if set(manifest) != {'variant_id', 'parent_sha', 'smoke_path', 'smoke_sha256',
                         'expected_template_keys', 'protected_method_ast_sha256'}:
        raise AssertionError('Unexpected Sandbox smoke manifest fields')
    if manifest['variant_id'] != 'sandbox-smoke-nazk-authority-v1' or manifest['parent_sha'] != 'fb3e95d8008b5e62630d71fc57be43f7f5aeca91':
        raise AssertionError('Unexpected Sandbox smoke manifest identity')
    return manifest


class SandboxSmokeNazkAuthorityIntegrityTests(unittest.TestCase):
    def test_exact_additive_manifest_and_smoke_source(self):
        manifest = read_manifest()
        self.assertEqual(manifest['smoke_path'], 'validation/sandbox_smoke.py')
        self.assertEqual(set(manifest['expected_template_keys']), EXPECTED_KEYS)
        self.assertTrue(contract_matches(smoke_path().read_bytes(), manifest))

    def test_removing_approved_authority_template_is_rejected(self):
        manifest = read_manifest()
        source = smoke_path().read_bytes()
        mutant = source.replace(b"'nazk_authority_request', ", b'', 1)
        self.assertNotEqual(source, mutant)
        self.assertFalse(contract_matches(mutant, manifest))

    def test_adding_unapproved_template_is_rejected(self):
        manifest = read_manifest()
        source = smoke_path().read_bytes()
        mutant = source.replace(b"'nazk_authority_request', ", b"'nazk_authority_request', 'unapproved_template', ", 1)
        self.assertNotEqual(source, mutant)
        self.assertFalse(contract_matches(mutant, manifest))

    def test_mutating_another_protected_smoke_assertion_is_rejected(self):
        manifest = read_manifest()
        source = smoke_path().read_bytes()
        mutant = source.replace(b"self.assertTrue(flags['sandbox_documents'])",
                                b"self.assertTrue(True)", 1)
        self.assertNotEqual(source, mutant)
        self.assertFalse(contract_matches(mutant, manifest))

    def test_changed_manifest_bytes_are_rejected(self):
        read_manifest()
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            folder = Path(temporary)
            (folder / MANIFEST_NAME).write_bytes((ROOT / MANIFEST_NAME).read_bytes() + b' ')
            with self.assertRaisesRegex(AssertionError, 'manifest hash mismatch'):
                read_manifest(folder)


if __name__ == '__main__':
    unittest.main()
