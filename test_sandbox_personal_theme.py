"""Palette integration and unchanged Sandbox safety/business code contracts."""
import ast
import hashlib
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import sandbox_runtime
from validation.local_release_20260911.sandbox_protocol_integrity_variant import (
 protected_content_matches,
)


def normalized_server(source):
    tree = ast.parse(source)
    targets = [
        (index, node) for index, node in enumerate(tree.body)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "list_violation_reports"
    ]
    if len(targets) != 1:
        raise AssertionError("Expected exactly one top-level list_violation_reports function")
    index, function = targets[0]
    if (not isinstance(function, ast.FunctionDef)
            or [arg.arg for arg in function.args.args] != ["params"]
            or function.args.posonlyargs or function.args.kwonlyargs
            or function.args.vararg or function.args.kwarg
            or function.args.defaults or function.args.kw_defaults
            or ast.dump(function.args.args[0].annotation, include_attributes=False)
               != ast.dump(ast.Name(id="dict", ctx=ast.Load()), include_attributes=False)
            or ast.dump(function.returns, include_attributes=False)
               != ast.dump(ast.Name(id="dict", ctx=ast.Load()), include_attributes=False)
            or function.decorator_list):
        raise AssertionError("list_violation_reports signature changed outside its approved body")
    previous = tree.body[index - 1] if index else None
    following = tree.body[index + 1] if index + 1 < len(tree.body) else None
    if (not isinstance(previous, ast.FunctionDef) or previous.name != "start_nazk_registry_refresh"
            or not isinstance(following, ast.Assign)
            or not any(isinstance(target, ast.Name) and target.id == "VIOLATION_REVIEW_FIELDS"
                       for target in following.targets)):
        raise AssertionError("list_violation_reports moved from its protected top-level location")

    class ApprovedRegionsOnly(ast.NodeTransformer):
        account_branch_count = 0

        def visit_If(self,node):
            if ast.unparse(node.test) == "parsed.path == '/api/account'":
                self.account_branch_count += 1
                node.body=[ast.Pass()]
                return node
            return self.generic_visit(node)

        def visit_FunctionDef(self, node):
            if node is function:
                node.body = [ast.Pass()]
                return node
            return self.generic_visit(node)

    normalizer = ApprovedRegionsOnly()
    normalized = normalizer.visit(tree)
    if normalizer.account_branch_count != 2:
        raise AssertionError("Expected exactly the GET and PATCH /api/account handler branches")
    return ast.dump(normalized,include_attributes=False)


def normalized_app(source):
    a=source.index('function applyAccountAppearance(')
    b=source.index('async function loadAccountSettings(',a)
    source=source[:a]+'ACCOUNT_APPEARANCE\n'+source[b:]
    a=source.index('globalThis.PqmThemeUI?.install();') if 'globalThis.PqmThemeUI?.install();' in source else source.index("$('#accountSettingsBtn').onclick=")
    b=source.index('void initializeLoginGate();',a)
    return source[:a]+'ACCOUNT_HANDLERS\n'+source[b:]


class SandboxPersonalThemeTests(unittest.TestCase):
    def test_whole_server_unchanged_outside_account_and_approved_appeals_kpi_function(self):
        contract=json.loads(Path('test_sandbox_personal_theme_contract.json').read_text())
        self.assertEqual(contract['server_baseline'], '0374436f2006c9e8eae1836d959b34ae7dfda7d8')
        digest=hashlib.sha256(normalized_server(Path('server.py').read_text(encoding='utf-8')).encode()).hexdigest()
        raw=Path('server.py').read_bytes()
        self.assertTrue(protected_content_matches(
            'server.py',raw,digest,contract['server_outside_account_and_appeals_kpi'],
            'personal_theme_normalized_sha256'))

    def test_app_business_functions_unchanged(self):
        contract=json.loads(Path('test_sandbox_personal_theme_contract.json').read_text())
        digest=hashlib.sha256(normalized_app(Path('app.js').read_text(encoding='utf-8')).encode()).hexdigest()
        raw=Path('app.js').read_bytes()
        self.assertTrue(protected_content_matches(
            'app.js',raw,digest,contract['app_without_account'],
            'personal_theme_normalized_sha256'))

    def test_protected_modules_and_halloween_bytes_unchanged(self):
        contract=json.loads(Path('test_sandbox_personal_theme_contract.json').read_text())
        for file,digest in contract['files'].items():
            with self.subTest(file=file):
                data=Path(file).read_bytes()
                if not file.endswith('.webp'):data=data.replace(b'\r\n',b'\n')
                self.assertEqual(hashlib.sha256(data).hexdigest(),digest)

    def test_actual_decorated_html_keeps_identity_and_both_switch_resources(self):
        with patch.dict(os.environ,PQM_SANDBOX='1'):
            html=sandbox_runtime.decorate_html(Path('index.html').read_bytes()).decode()
        for token in ['data-pqm-environment="sandbox"','id="sandboxWarning"','sandbox-brand-copy','id="personalThemeStyles"','theme_ui.js','halloween.js','halloween_season.js']:
            self.assertIn(token,html)
        self.assertIn('Personal colours live in theme.css',html)
        self.assertNotIn('background-color:#102238!important',html)

    def test_environment_identity_cannot_force_dark_halloween(self):
        css=Path('halloween.css').read_text(encoding='utf-8')
        self.assertNotIn('data-pqm-environment',css)
        self.assertIn('[data-theme="dark"]',css)
        self.assertIn('halloween-workqueue-light.webp',css)
        self.assertIn('halloween-workqueue-dark.webp',css)

    def test_legacy_contrast_is_not_a_personal_palette_repair(self):
        self.assertIn('if (globalThis.PqmThemeUI) return;',Path('sandbox_contrast.js').read_text())

    def test_existing_schema_has_color_scheme_no_new_migration(self):
        self.assertIn('color_scheme TEXT',Path('auth_access.py').read_text())

