"""Palette integration and unchanged Sandbox safety/business code contracts."""
import ast
import hashlib
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import sandbox_runtime


def normalized_server(source):
    class AccountsOnly(ast.NodeTransformer):
        def visit_If(self,node):
            if ast.unparse(node.test) == "parsed.path == '/api/account'":
                node.body=[ast.Pass()]
                return node
            return self.generic_visit(node)
    return ast.dump(AccountsOnly().visit(ast.parse(source)),include_attributes=False)


def normalized_app(source):
    a=source.index('function applyAccountAppearance(')
    b=source.index('async function loadAccountSettings(',a)
    source=source[:a]+'ACCOUNT_APPEARANCE\n'+source[b:]
    a=source.index('globalThis.PqmThemeUI?.install();') if 'globalThis.PqmThemeUI?.install();' in source else source.index("$('#accountSettingsBtn').onclick=")
    b=source.index('void initializeLoginGate();',a)
    return source[:a]+'ACCOUNT_HANDLERS\n'+source[b:]


class SandboxPersonalThemeTests(unittest.TestCase):
    def test_whole_server_unchanged_outside_two_account_branches(self):
        contract=json.loads(Path('test_sandbox_personal_theme_contract.json').read_text())
        self.assertEqual(hashlib.sha256(normalized_server(Path('server.py').read_text(encoding='utf-8')).encode()).hexdigest(),contract['server_without_account'])

    def test_app_business_functions_unchanged(self):
        contract=json.loads(Path('test_sandbox_personal_theme_contract.json').read_text())
        self.assertEqual(hashlib.sha256(normalized_app(Path('app.js').read_text(encoding='utf-8')).encode()).hexdigest(),contract['app_without_account'])

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

