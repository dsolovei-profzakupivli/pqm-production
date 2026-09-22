import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sandbox_runtime as sandbox


class Theme(unittest.TestCase):
    def test_sandbox_theme_is_injected_only_for_sandbox_runtime(self):
        raw = (sandbox.ROOT / 'index.html').read_bytes()
        for flag in ('0', '1'):
            with patch.dict(os.environ, PQM_SANDBOX=flag):
                html = sandbox.decorate_html(raw).decode()
                self.assertEqual('id="pqmSandboxTheme"' in html, flag == '1')
                self.assertEqual('data-pqm-environment="sandbox"' in html, flag == '1')
        self.assertNotIn(b'sandbox_theme.css', raw)
        self.assertNotIn(b'id="pqmSandboxTheme"', raw)
    def test_sandbox_theme_preserves_light_application_surfaces(self):
        css = (sandbox.ROOT / 'sandbox_theme.css').read_text(encoding='utf-8')
        self.assertIn('#sandboxWarning', css)
        for dark_override in ('color-scheme: dark', '#0b172a', '#132840', '#193451'):
            self.assertNotIn(dark_override, css)


if __name__ == '__main__':
    unittest.main()
