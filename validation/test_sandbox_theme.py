import os
from html.parser import HTMLParser
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sandbox_runtime as sandbox


class BrandMarkup(HTMLParser):
    """Parse descendants so attributes and decorative children cannot hide lost text."""
    def __init__(self, html):
        super().__init__()
        self.root = {'tag': None, 'attrs': {}, 'children': [], 'text': ''}
        self.stack = [self.root]
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = {'tag': tag, 'attrs': dict(attrs), 'children': [], 'text': ''}
        self.stack[-1]['children'].append(node)
        if tag not in {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
                       'link', 'meta', 'param', 'source', 'track', 'wbr'}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index]['tag'] == tag:
                del self.stack[index:]
                return

    def handle_data(self, data):
        for node in self.stack:
            node['text'] += data

    def find(self, parent=None, *, tag=None, css_class=None):
        found = []
        for node in (parent or self.root)['children']:
            if (tag is None or node['tag'] == tag) and (
                    css_class is None or css_class in node['attrs'].get('class', '').split()):
                found.append(node)
            found.extend(self.find(node, tag=tag, css_class=css_class))
        return found


def luminance(value):
    rgb = [int(value[i:i+2], 16)/255 for i in (1, 3, 5)]
    rgb = [v/12.92 if v <= .04045 else ((v+.055)/1.055)**2.4 for v in rgb]
    return sum(v*w for v, w in zip(rgb, (.2126, .7152, .0722)))


class Theme(unittest.TestCase):
    def test_detail_surface_contract(self):
        css = (sandbox.ROOT / 'theme.css').read_text()
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
                self.assertEqual('pqm-q-favicon.svg?v=4' in html, flag == '1')
                self.assertEqual('pqm-q-favicon-16.png?v=4' in html, flag == '1')
                self.assertEqual('pqm-q-favicon-180.png?v=4' in html, flag == '1')
                self.assertIn('pqm-brand-mark-prod.svg', html)
                if flag == '0': self.assertIn('pqm-q-favicon-prod-192.png?v=6', html)
        root = ET.parse(sandbox.ROOT / 'assets/pqm-q-favicon.svg').getroot()
        self.assertEqual(root.find('{http://www.w3.org/2000/svg}rect').get('fill'), '#132840')
        self.assertEqual(root.find('{http://www.w3.org/2000/svg}title').text, 'Q — PQM')
        logo = ET.parse(sandbox.ROOT / 'assets/pqm-brand-mark.svg').getroot()
        ns='{http://www.w3.org/2000/svg}'
        self.assertEqual([p.get('fill') for p in logo.findall(ns+'path')], ['#fff', '#fff'])
        q=logo.find(ns+'g')
        self.assertEqual(q.get('fill'), '#63b2ff')
        self.assertEqual(q.find(ns+'path').get('d'),root.find(ns+'path').get('d'))
        self.assertEqual([circle.get('r') for circle in root.findall(ns+'circle')], ['19', '10'])
        self.assertNotIn('filter', ET.tostring(logo,encoding='unicode'))
        for size in (16, 32, 180, 192):
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
        self.assertIn('<img class="sandbox-brand-initials" src="/assets/pqm-brand-mark-prod.svg"', html)
        self.assertIn('class="sandbox-brand-divider"', html)
        markup = BrandMarkup(html)
        brands = markup.find(tag='div', css_class='sandbox-brand')
        self.assertEqual(len(brands), 1)
        copies = markup.find(brands[0], tag='span', css_class='sandbox-brand-copy')
        self.assertEqual(len(copies), 1)
        titles = markup.find(copies[0], tag='strong')
        self.assertEqual(len(titles), 1)
        self.assertEqual(titles[0]['text'], 'Професійні закупівлі')
        self.assertIn('halloween-title', titles[0]['attrs'].get('class', '').split())
        cats = markup.find(titles[0], tag='img', css_class='halloween-cat')
        self.assertEqual(len(cats), 1)
        self.assertEqual(cats[0]['attrs']['src'], 'assets/pqm-cat-no-hat.png')
        self.assertEqual((cats[0]['attrs']['width'], cats[0]['attrs']['height']), ('180', '97'))
        self.assertEqual(cats[0]['attrs']['alt'], '')
        self.assertEqual(cats[0]['attrs']['aria-hidden'], 'true')
        self.assertEqual(markup.find(copies[0], tag='small')[0]['text'],
                         'Procurement Qualification Manager')
        self.assertIn('<small>Procurement Qualification Manager</small>', html)
        self.assertIn('id="environmentBanner" class="sandbox-brand-accessible"', html)
        self.assertNotIn('<img class="brand-logo"', html)
        self.assertIn('id="sandboxWarning"', html)
        self.assertIn('<nav id="mainNav" aria-label="Основна навігація"></nav>', html)
        self.assertNotIn('sandbox-brand', prod_html)
        prod_markup = BrandMarkup(prod_html)
        prod_copies = prod_markup.find(tag='span', css_class='prod-brand-copy')
        self.assertEqual(len(prod_copies), 1)
        self.assertEqual([node['text'] for node in prod_markup.find(prod_copies[0], tag='strong')],
                         ['Професійні закупівлі'])
        self.assertEqual(prod_markup.find(css_class='halloween-cat'), [])
        self.assertEqual(prod_markup.find(css_class='halloween-title'), [])
        self.assertIn('<img class="prod-brand-initials" src="/assets/pqm-brand-mark-prod.svg"', prod_html)
        self.assertIn('id="environmentBanner" class="prod-brand-accessible">PQM</em>', prod_html)
        self.assertIn('<nav id="mainNav" aria-label="Основна навігація"></nav>', prod_html)
    def test_navbar_brand_contract_rejects_structural_and_isolation_regressions(self):
        raw = (sandbox.ROOT / 'index.html').read_bytes()
        with patch.dict(os.environ, PQM_SANDBOX='1'):
            html = sandbox.decorate_html(raw).decode()
        with patch.dict(os.environ, PQM_SANDBOX='0'):
            production = sandbox.decorate_html(raw).decode()
        mutations = {
            'title text lost': (html.replace('Професійні закупівлі', 'Wrong title'), production),
            'copy moved outside brand': (html.replace('sandbox-brand-copy', 'unrelated-copy'), production),
            'ordinary cat missing': (html.replace('class="halloween-cat"', 'class="missing-cat"'), production),
            'seasonal cat used initially': (html.replace('assets/pqm-cat-no-hat.png', 'assets/halloween-witch-cat.webp'), production),
            'cat accessible to screen readers': (html.replace('aria-hidden="true" draggable="false"', 'aria-hidden="false" draggable="false"'), production),
            'Sandbox leaked into Production': (html, html),
            'cat leaked into Production': (html, production.replace('</strong>', '<img class="halloween-cat"></strong>', 1)),
        }
        for name, (candidate, prod_candidate) in mutations.items():
            with self.subTest(name=name), patch.object(
                    sandbox, 'decorate_html', side_effect=[candidate.encode(), prod_candidate.encode()]):
                with self.assertRaises(AssertionError):
                    self.test_navbar_brand_is_sandbox_only()
    def test_prod_brand_reuses_sandbox_geometry(self):
        import xml.etree.ElementTree as ET
        ns = '{http://www.w3.org/2000/svg}'
        sandbox_logo = ET.parse(sandbox.ROOT / 'assets/pqm-brand-mark.svg').getroot()
        prod_logo = ET.parse(sandbox.ROOT / 'assets/pqm-brand-mark-prod.svg').getroot()
        sandbox_favicon = ET.parse(sandbox.ROOT / 'assets/pqm-q-favicon.svg').getroot()
        prod_favicon = ET.parse(sandbox.ROOT / 'assets/pqm-q-favicon-prod.svg').getroot()
        def geometry(root):
            return [(node.tag, tuple(sorted((key, value) for key, value in node.attrib.items() if key != 'fill')))
                    for node in root.iter()]
        self.assertEqual(geometry(sandbox_logo), geometry(prod_logo))
        self.assertEqual(geometry(sandbox_favicon), geometry(prod_favicon))
        self.assertEqual(prod_logo.find(ns + 'g').get('fill'), sandbox_logo.find(ns + 'g').get('fill'))
        self.assertEqual(prod_favicon.find(ns + 'path').get('d'), sandbox_favicon.find(ns + 'path').get('d'))
        self.assertEqual(prod_favicon.find(ns + 'path').get('fill'), '#63b2ff')
        self.assertEqual(prod_favicon.find(ns + 'rect').get('fill'), '#f5f7f8')
    def test_text_contrast(self):
        for foreground in ('#edf3fc', '#b2c3db', '#86bdff'):
            for background in ('#0b172a', '#132840', '#193451'):
                ratio = (luminance(foreground)+.05)/(luminance(background)+.05)
                self.assertGreaterEqual(ratio, 4.5, (foreground, background, ratio))
    def test_light_surfaces_contrast(self):
        css = (sandbox.ROOT / 'theme.css').read_text()
        for selector in ('.multi-filter', '.advanced-filters', '.toolbar-settings', '.table-card>footer', '.paperclip>span'):
            self.assertIn(selector, css)
        for background in ('#f2f5fa', '#e8eff7'):
            self.assertGreaterEqual((luminance(background)+.05)/(luminance('#172b43')+.05), 4.5)


if __name__ == '__main__':
    unittest.main()
