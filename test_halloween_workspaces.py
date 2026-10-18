from pathlib import Path
import hashlib
import subprocess
import unittest


class HalloweenWorkspaceTests(unittest.TestCase):
    def test_viewport_scene_independent_of_table_length_and_document_scroll(self):
        r=subprocess.run(['node','validation/halloween_workspace_unit.cjs'],capture_output=True,text=True,timeout=20)
        self.assertEqual(r.returncode,0,r.stderr)

    def test_spider_exact_approved_motion_and_reduced_motion(self):
        css=Path('halloween.css').read_text(encoding='utf-8')
        self.assertIn('transform-origin:50% 0;animation:pqm-spider-sway 4.5s ease-in-out infinite',css)
        self.assertIn('@keyframes pqm-spider-sway{0%,100%{transform:rotate(-5deg)}50%{transform:rotate(5deg)}}',css)
        self.assertIn('@media(prefers-reduced-motion:reduce){.halloween-spider{animation:none}}',css)
        self.assertIn('left:5.5px;top:0;bottom:9px;width:.7px',css)
        self.assertIn('transform:scale(1.2);transform-origin:50% 25%',css)

    def test_cat_and_scenery_bytes_unchanged(self):
        for file,digest in {'halloween-witch-cat.webp':'62991ef629660918e07247008cbae56a1ebe7ef4a6beb87199d745f86acdb528','halloween-workqueue-light.webp':'f11bb9e7b4f042fde5f24f2e55ea9b0895275823d0196e1780cef734f3747302','halloween-workqueue-dark.webp':'54201419649b53a1d41f3dc33abe38b25fe3a7d26707c7446831df233d364377'}.items():
            self.assertEqual(hashlib.sha256(Path('assets',file).read_bytes()).hexdigest(),digest)

    def test_background_layer_does_not_style_working_components(self):
        layer=Path('halloween.css').read_text(encoding='utf-8').split('/* Explicitly selected workspaces only.')[1].split('*/',1)[1]
        for forbidden in ['.card','table','button','input','opacity:','min-height:','overflow:','100% 100%']:
            self.assertNotIn(forbidden,layer)
        self.assertIn('background-size:cover;background-position:right bottom',layer)
        self.assertIn('z-index:-1;pointer-events:none',layer)

    def test_experimental_entry_points_removed(self):
        html=Path('index.html').read_text(encoding='utf-8')
        self.assertNotIn('halloween_background_experiment',html)
        self.assertNotIn('Local three-workspace',html)
