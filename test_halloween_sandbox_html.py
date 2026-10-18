"""Actual Sandbox response decoration contract, no server/DB initialization."""
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from sandbox_runtime import decorate_html


class HalloweenSandboxHtmlTests(unittest.TestCase):
    def run_ui(self, html, title_expected):
        result = subprocess.run(
            ['node', 'validation/halloween_sandbox_html.cjs', str(int(title_expected))],
            input=html, text=True, encoding='utf-8', capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_actual_sandbox_decorated_html_initializes_switch_and_cat(self):
        with patch.dict(os.environ, {'PQM_SANDBOX': '1'}):
            html = decorate_html(Path('index.html').read_bytes()).decode('utf-8')
        self.assertIn('sandbox-brand-copy', html)
        self.assertNotIn('class="prod-brand-copy"', html)
        self.run_ui(html, True)

    def test_production_brand_remains_compatible(self):
        self.run_ui(Path('index.html').read_text(encoding='utf-8'), True)

    def test_missing_brand_does_not_disable_other_components_or_switch(self):
        html = Path('index.html').read_text(encoding='utf-8').replace(
            'class="prod-brand-copy"', 'class="unrecognized-brand-copy"')
        self.run_ui(html, False)

    def test_cat_positioning_supports_both_headers(self):
        css = Path('halloween.css').read_text(encoding='utf-8')
        self.assertIn('.prod-brand-copy .halloween-title,.sandbox-brand-copy .halloween-title{position:relative;isolation:isolate}', css)
