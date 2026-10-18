from pathlib import Path
import hashlib
import unittest


class HalloweenBackgroundExperimentTests(unittest.TestCase):
    def test_only_three_workspaces_and_only_background_layer(self):
        css=Path('halloween_background_experiment.css').read_text(encoding='utf-8')
        self.assertIn(':is(#applicationsView,#operationalTasksView,#suppliersView)',css)
        for forbidden in ['.card', 'table', 'button', 'opacity:', 'min-height:', 'overflow:']:
            self.assertNotIn(forbidden,css)
        self.assertIn('z-index:-1;pointer-events:none',css)
        self.assertIn('background-size:cover;background-position:right bottom',css)

    def test_existing_switch_and_theme_gate(self):
        css=Path('halloween_background_experiment.css').read_text(encoding='utf-8')
        self.assertEqual(css.count('html['),5)
        self.assertIn('data-halloween="on"',css)
        self.assertIn('[data-theme="dark"]',css)
        self.assertIn('[data-pqm-environment="sandbox"]',css)

    def test_original_approved_landscapes_unchanged(self):
        for theme,digest in {'light':'f11bb9e7b4f042fde5f24f2e55ea9b0895275823d0196e1780cef734f3747302','dark':'54201419649b53a1d41f3dc33abe38b25fe3a7d26707c7446831df233d364377'}.items():
            self.assertEqual(hashlib.sha256(Path(f'assets/halloween-workqueue-{theme}.webp').read_bytes()).hexdigest(),digest)

    def test_experiment_has_no_data_access_or_preferences(self):
        js=Path('halloween_background_experiment.js').read_text(encoding='utf-8')
        for forbidden in ['fetch(', '/api/', 'localStorage', 'setInterval(', 'innerHTML', '.hidden=']:
            self.assertNotIn(forbidden,js)
        self.assertIn('Math.max(box.height,innerHeight-box.top)',js)
        self.assertIn("attributeFilter:['hidden']",js)
