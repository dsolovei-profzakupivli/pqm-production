"""PROD install-icon metadata stays on the approved existing assets."""
import struct
import unittest
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parent
if not (ROOT / 'index.html').exists():
    ROOT = Path(__file__).resolve().parents[2]


class HeadLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_head = False
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == 'head':
            self.in_head = True
        if self.in_head and tag == 'link':
            data = dict(attrs)
            if data.get('rel') in {'icon', 'apple-touch-icon'}:
                self.links.append(data)

    def handle_endtag(self, tag):
        if tag == 'head':
            self.in_head = False


class ProdFaviconMetadataTests(unittest.TestCase):
    def test_installed_head_uses_approved_order_and_existing_assets(self):
        parser = HeadLinks()
        parser.feed((ROOT / 'index.html').read_text(encoding='utf-8'))
        self.assertEqual([(link['rel'], link['href'], link.get('type'), link.get('sizes'))
                          for link in parser.links], [
            ('icon', '/assets/pqm-q-favicon-192.png?v=5', 'image/png', '192x192'),
            ('icon', '/assets/pqm-q-favicon.svg?v=5', 'image/svg+xml', 'any'),
            ('icon', '/assets/pqm-q-favicon-16.png?v=5', 'image/png', '16x16'),
            ('icon', '/assets/pqm-q-favicon-32.png?v=5', 'image/png', '32x32'),
            ('apple-touch-icon', '/assets/pqm-q-favicon-180.png?v=5', None, None),
        ])
        for name, dimension in [('192', 192), ('16', 16), ('32', 32), ('180', 180)]:
            data = (ROOT / 'assets' / f'pqm-q-favicon-{name}.png').read_bytes()
            self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
            self.assertEqual(struct.unpack('>II', data[16:24]), (dimension, dimension))
        self.assertTrue((ROOT / 'assets' / 'pqm-q-favicon.svg').is_file())


if __name__ == '__main__':
    unittest.main()
