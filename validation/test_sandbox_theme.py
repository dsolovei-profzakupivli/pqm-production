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
        import xml.etree.ElementTree as ET
        import struct
        raw = (sandbox.ROOT / 'index.html').read_bytes()
        for flag in ('0', '1'):
            with patch.dict(os.environ, PQM_SANDBOX=flag):
                html = sandbox.decorate_html(raw).decode()
                self.assertEqual('pqm-q-favicon.svg' in html, flag == '1')
                self.assertEqual('pqm-q-favicon-180.png' in html, flag == '1')
                if flag == '0': self.assertIn('pqm-tab-icon.png', html)
        root = ET.parse(sandbox.ROOT / 'assets/pqm-q-favicon.svg').getroot()
        self.assertEqual(root.find('{http://www.w3.org/2000/svg}rect').get('fill'), '#132840')
        self.assertEqual(root.find('{http://www.w3.org/2000/svg}circle').get('stroke'), '#86bdff')
        for size in (32, 180, 192):
            png = (sandbox.ROOT / 'assets' / f'pqm-q-favicon-{size}.png').read_bytes()
            self.assertEqual(png[:8], b'\x89PNG\r\n\x1a\n')
            self.assertEqual(struct.unpack('>II', png[16:24]), (size, size))
    def test_compact_filters_are_sandbox_scoped_and_keep_actions(self):
        css = (sandbox.ROOT / 'sandbox_theme.css').read_text(encoding='utf-8')
        html = (sandbox.ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn('html[data-pqm-environment="sandbox"] :is(.applications-toolbar,.edr-monitoring-toolbar,.frameworks-toolbar,.history-filters)', css)
        self.assertIn('flex-wrap:wrap', css)
        self.assertIn('max-width:calc(100vw - 24px)', css)
        for control in ('edrMonitoringReset', 'edrMonitoringChips', 'clearFiltersBtn', 'historyReset'):
            self.assertIn(f'id="{control}"', html)
    def test_sandbox_only(self):
        raw = (sandbox.ROOT / 'index.html').read_bytes()
        for flag in ('0', '1'):
            with patch.dict(os.environ, PQM_SANDBOX=flag):
                html = sandbox.decorate_html(raw).decode()
                self.assertEqual('id="pqmSandboxTheme"' in html, flag == '1')
                self.assertEqual('data-pqm-environment="sandbox"' in html, flag == '1')
                self.assertEqual('/sandbox_contrast.js?v=1' in html, flag == '1')
                self.assertIn('id="sandboxWarning"', html)
        self.assertNotIn(b'sandbox_theme.css', raw)
        self.assertNotIn(b'id="pqmSandboxTheme"', raw)
        self.assertNotIn(b'id="sandboxWarning"', raw)
        self.assertIn('if SANDBOX_MODE and path == "index.html":',
                      (sandbox.ROOT / 'server.py').read_text(encoding='utf-8'))
    def test_navbar_brand_is_sandbox_only(self):
        raw = (sandbox.ROOT / 'index.html').read_bytes()
        with patch.dict(os.environ, PQM_SANDBOX='1'):
            html = sandbox.decorate_html(raw).decode()
        with patch.dict(os.environ, PQM_SANDBOX='0'):
            prod_html = sandbox.decorate_html(raw).decode()
        self.assertIn('class="brand sandbox-brand"', html)
        self.assertIn('<span>P</span><span class="sandbox-brand-q">Q</span><span>M</span>', html)
        self.assertIn('class="sandbox-brand-divider"', html)
        self.assertIn('<strong>Професійні закупівлі</strong>', html)
        self.assertIn('<small>Procurement Qualification Manager</small>', html)
        self.assertIn('id="environmentBanner" class="sandbox-brand-accessible"', html)
        self.assertNotIn('<img class="brand-logo"', html)
        self.assertIn('id="sandboxWarning"', html)
        self.assertIn('<nav id="mainNav" aria-label="Основна навігація"></nav>', html)
        self.assertNotIn('sandbox-brand', prod_html)
        self.assertIn('<img class="brand-logo"', prod_html)
        self.assertIn('id="environmentBanner" title="Profzakupivli Qualification Manager">PQM</em>', prod_html)
        self.assertIn('<nav id="mainNav" aria-label="Основна навігація"></nav>', prod_html)
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
