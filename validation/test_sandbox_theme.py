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
    def test_detail_surface_contract(self):
        css = (sandbox.ROOT / 'sandbox_theme.css').read_text()
        for selector in ('dialog>form', 'dialog form>header', 'dialog form>footer',
                         '.request-details-body section', '.supplier-profile-section',
                         '.supplier-profile-stats>div', '.module-kpis>article',
                         '.operational-summary', '.operational-workspace>details',
                         '.operational-workspace>section', '.operational-facts>div',
                         '.operational-registry-list:has(table)', '.status-chip',
                         '.supplier-status-count:not(.inactive)', '.supplier-registry-state.registered'):
            self.assertIn(selector, css)
        for fg, bg in (('#edf3fc', '#132840'), ('#b2c3db', '#132840'),
                       ('#8be0b6', '#173e38'), ('#ffdc8a', '#443b26'),
                       ('#ffb1b8', '#492936'), ('#edf3fc', '#203e62')):
            self.assertGreaterEqual((luminance(fg)+.05)/(luminance(bg)+.05), 4.5)
    def test_sandbox_favicon_isolated(self):
        import base64
        import xml.etree.ElementTree as ET
        raw = (sandbox.ROOT / 'index.html').read_bytes()
        for flag in ('0', '1'):
            with patch.dict(os.environ, PQM_SANDBOX=flag):
                html = sandbox.decorate_html(raw).decode()
                self.assertEqual('pqm-sandbox-tab-inverted.svg' in html, flag == '1')
                self.assertEqual('sizes="32x32"' in html, flag == '0')
        root = ET.parse(sandbox.ROOT / 'assets/pqm-sandbox-tab-inverted.svg').getroot()
        ns = {'s': 'http://www.w3.org/2000/svg'}
        for channel in ('R', 'G', 'B'):
            self.assertEqual(root.find('.//s:feFunc'+channel, ns).get('tableValues'), '1 0')
        self.assertEqual(root.find('.//s:feFuncA', ns).get('type'), 'identity')
        embedded = root.find('s:image', ns).get('href').split(',', 1)[1]
        self.assertEqual(base64.b64decode(embedded), (sandbox.ROOT / 'assets/pqm-tab-icon.png').read_bytes())
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
    def test_light_surfaces_contrast(self):
        css = (sandbox.ROOT / 'sandbox_theme.css').read_text()
        for selector in ('.multi-filter', '.advanced-filters', '.toolbar-settings', '.table-card>footer', '.paperclip>span'):
            self.assertIn(selector, css)
        for background in ('#f2f5fa', '#e8eff7'):
            self.assertGreaterEqual((luminance(background)+.05)/(luminance('#172b43')+.05), 4.5)


if __name__ == '__main__':
    unittest.main()
