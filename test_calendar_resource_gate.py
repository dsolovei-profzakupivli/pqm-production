"""Calendar loading contract complements the real-browser network boundary matrix."""
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import sandbox_runtime


class CalendarResourceGateTests(unittest.TestCase):
    def test_default_sandbox_html_is_ordinary_without_seasonal_resources(self):
        with patch.dict(os.environ, {'PQM_SANDBOX': '1'}):
            html = sandbox_runtime.decorate_html(Path('index.html').read_bytes()).decode('utf8')
        self.assertIn('data-halloween="off"', html)
        self.assertIn('src="assets/pqm-cat-no-hat.png"', html)
        self.assertEqual(html.count('src="pqm_cat.js"'), 1)
        self.assertEqual(html.count('href="pqm_cat.css"'), 1)
        for name in ['halloween.js', 'halloween.css', 'halloween_motion.js',
                     'halloween_motion.css', 'halloween_cat_season.js?v=1',
                     'halloween_cat_season.css?v=1', 'assets/halloween-witch-cat.webp']:
            self.assertNotIn('src="' + name + '"', html)
            self.assertNotIn('href="' + name + '"', html)

    def test_ordinary_cat_css_contains_no_seasonal_art_or_animation(self):
        css = Path('pqm_cat.css').read_text()
        self.assertNotIn('url(', css)
        self.assertNotIn('animation:', css)
        self.assertIn('width:180px', css)
        self.assertIn('max-width:900px', css)
        self.assertIn('max-width:600px', css)

    def test_calendar_policy_is_explicit_and_fails_closed(self):
        policy = Path('halloween_season.js').read_text()
        self.assertIn("timeZone='Europe/Kyiv'", policy)
        self.assertIn('available=p.month===10', policy)
        self.assertIn('catch{return {available:false', policy)
        loader = Path('pqm_cat.js').read_text()
        self.assertIn("value?.timeZone!=='Europe/Kyiv'", loader)
        self.assertIn('Number.isFinite(value.nextTransitionAt)', loader)
        self.assertIn("const normal='assets/pqm-cat-no-hat.png'", loader)
        self.assertIn('image.onerror=fail', loader)

    def test_every_seasonal_request_rechecks_calendar(self):
        loader = Path('pqm_cat.js').read_text()
        self.assertIn("if(!allowed())return reject(Error('Season is closed'))", loader)
        self.assertIn("node.onload=()=>allowed()?resolve():reject", loader)
        self.assertIn('if(allowed())image.src=hat', loader)
        motion = Path('halloween_motion.js').read_text()
        self.assertIn('const allowed=()=>inSeason()', motion)
        self.assertIn('const catAllowed=()=>inSeason()', motion)
        self.assertIn('if(!allowed())return;\n      const lane=host;', motion)

    def test_calendar_changes_do_not_touch_filter_css(self):
        self.assertNotIn('pqm_cat', Path('filter_panels.css').read_text())
        self.assertNotIn('halloween', Path('filter_panels.css').read_text())


if __name__ == '__main__':
    unittest.main()
