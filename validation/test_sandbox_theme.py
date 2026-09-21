import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sandbox_runtime as sandbox


def luminance(value):
    rgb = [int(value[i:i+2], 16)/255 for i in (1, 3, 5)]
    rgb = [v/12.92 if v <= .04045 else ((v+.055)/1.055)**2.4 for v in rgb]
    return sum(v*w for v, w in zip(rgb, (.2126, .7152, .0722)))


class Theme(unittest.TestCase):
    def test_sandbox_only(self):
        raw = (sandbox.ROOT / 'index.html').read_bytes()
        for flag in ('0', '1'):
            with patch.dict(os.environ, PQM_SANDBOX=flag):
                html = sandbox.decorate_html(raw).decode()
                self.assertEqual('id="pqmSandboxTheme"' in html, flag == '1')
                self.assertEqual('data-pqm-environment="sandbox"' in html, flag == '1')
        self.assertNotIn(b'sandbox_theme.css', raw)
        self.assertNotIn(b'id="pqmSandboxTheme"', raw)
    def test_text_contrast(self):
        for foreground in ('#edf3fc', '#b2c3db', '#86bdff'):
            for background in ('#0b172a', '#132840', '#193451'):
                ratio = (luminance(foreground)+.05)/(luminance(background)+.05)
                self.assertGreaterEqual(ratio, 4.5, (foreground, background, ratio))


if __name__ == '__main__':
    unittest.main()
