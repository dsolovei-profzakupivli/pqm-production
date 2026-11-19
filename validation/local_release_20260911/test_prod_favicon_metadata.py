"""PROD install-icon metadata stays on the approved existing assets."""
import struct
import hashlib
import os
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

import sandbox_runtime


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
    def test_environment_heads_resolve_to_distinct_approved_icon_contents(self):
        source = (ROOT / 'index.html').read_text(encoding='utf-8')
        parser = HeadLinks()
        parser.feed(source)
        self.assertEqual([(link['rel'], link['href'], link.get('type'), link.get('sizes'))
                          for link in parser.links], [
            ('icon', '/assets/pqm-q-favicon-prod-192.png?v=6', 'image/png', '192x192'),
            ('icon', '/assets/pqm-q-favicon-prod.svg?v=6', 'image/svg+xml', 'any'),
            ('icon', '/assets/pqm-q-favicon-prod-16.png?v=6', 'image/png', '16x16'),
            ('icon', '/assets/pqm-q-favicon-prod-32.png?v=6', 'image/png', '32x32'),
            ('apple-touch-icon', '/assets/pqm-q-favicon-prod-180.png?v=6', None, None),
        ])
        with patch.dict(os.environ, {'PQM_SANDBOX': '1'}):
            sandbox_html = sandbox_runtime.decorate_html(source.encode('utf-8')).decode('utf-8')
        sandbox = HeadLinks()
        sandbox.feed(sandbox_html)
        self.assertEqual([link['href'] for link in sandbox.links], [
            '/assets/pqm-q-favicon-192.png?v=4', '/assets/pqm-q-favicon.svg?v=4',
            '/assets/pqm-q-favicon-16.png?v=4', '/assets/pqm-q-favicon-32.png?v=4',
            '/assets/pqm-q-favicon-180.png?v=4'])
        expected = {
            'prod': {'16': '389643b43dc5270d4870526cb5d48578b255e2f9f46f48ec550511579e378e90',
                     '32': '2678496dde5e00289342b252e62d96e5736b5b9690fb1cf8d5c91dbc7b371ce8',
                     '180': '7f1af338db29bc924402d7cc6dc61a6785d82df3e0ea924171e2fe782322f38e',
                     '192': 'f4464ddb9e2a7566b76df68ebc8fbc405a654554f9f1c31257b5bc58a731e25b'},
            'sandbox': {'16': 'cc35568a2fc1775b0bd7c016452e1d4a164b8c41e4d5448d800e4eab1f55f50c',
                        '32': 'd5e3cebf91715f79fbe48a2d3fdd1bf3289663b8a57f7b54c28079ea6282609e',
                        '180': 'a244d5a86e60f2218e0a646dd38a9816866b1d724f701bfe3dcc2798215891e7',
                        '192': 'e8afdc6a8f382805bc4a875058fd6779c0e3a8e7340611fc78d53f07f0c1bbbe'},
        }
        for env, links in [('prod', parser.links), ('sandbox', sandbox.links)]:
            for link in links:
                asset = ROOT / link['href'].split('?', 1)[0].lstrip('/')
                data = asset.read_bytes()
                if asset.suffix == '.svg':
                    background = '#f5f7f8' if env == 'prod' else '#132840'
                    self.assertIn(f'fill="{background}"', data.decode('utf-8'))
                    self.assertIn('fill="#63b2ff"', data.decode('utf-8'))
                    continue
                size = link['href'].split('.png', 1)[0].rsplit('-', 1)[-1]
                self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
                self.assertEqual(struct.unpack('>II', data[16:24]), (int(size), int(size)))
                self.assertEqual(hashlib.sha256(data).hexdigest(), expected[env][size])


if __name__ == '__main__':
    unittest.main()
