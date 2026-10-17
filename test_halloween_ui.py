"""Frontend-only seasonal decoration contracts; no runtime or external API."""
from pathlib import Path
import hashlib
import subprocess
import unittest


class HalloweenUiTests(unittest.TestCase):
    def test_workqueue_background_is_scoped_and_behind_content(self):
        css=Path('halloween.css').read_text(encoding='utf-8')
        layer=css[css.index('/* Work Queue background only.'):]
        self.assertIn('html[data-halloween="on"] #workQueueView:not([hidden])',layer)
        self.assertIn('position:absolute;inset:0;z-index:-1;pointer-events:none',layer)
        self.assertNotIn('animation',layer)
        for forbidden in ['.card{','button{','input{','height:','min-height:','overflow:']:
            self.assertNotIn(forbidden,layer)

    def test_workqueue_decorative_assets_are_local_svg(self):
        import xml.etree.ElementTree as ET
        for name in ['web','web-right','bat']:
            source=Path(f'assets/halloween-queue-{name}.svg').read_text(encoding='utf-8')
            self.assertEqual(ET.fromstring(source).tag,'{http://www.w3.org/2000/svg}svg')
            self.assertNotIn('<script',source)
            self.assertNotIn('href=',source)

    def test_pumpkins_paint_existing_badges_without_changing_layout_or_values(self):
        css=Path('halloween.css').read_text(encoding='utf-8')
        self.assertIn('html[data-halloween="on"] .topbar #mainNav .action-count-badge',css)
        self.assertIn('width:30px;height:30px',css)
        self.assertIn('background:transparent!important;color:#fff!important',css)
        self.assertIn('.action-count-badge[hidden]::before{content:none}',css)
        source=Path('halloween.js').read_text(encoding='utf-8')
        self.assertIn('number.textContent=badge.textContent;badge.replaceChildren(number)',source)

    def test_digit_scale_is_paint_only_and_outline_is_scoped(self):
        css=Path('halloween.css').read_text(encoding='utf-8')
        self.assertIn('transform:scale(1.18);transform-origin:center',css)
        self.assertIn('-webkit-text-stroke:.3px #592600',css)
        self.assertIn('html[data-halloween="on"] .topbar #mainNav .halloween-count-number',css)

    def test_hat_is_avatar_bound_and_uses_shared_switch(self):
        source=Path('halloween.js').read_text(encoding='utf-8')
        css=Path('halloween.css').read_text(encoding='utf-8')
        self.assertIn("document.querySelector('#currentUserAvatar')",source)
        self.assertIn('avatar.getBoundingClientRect()',source)
        self.assertIn('avatar.hidden||!avatar.complete||!avatar.naturalWidth',source)
        self.assertIn('refreshSpider();refreshHat()',source)
        self.assertIn('width:40px;height:28px;pointer-events:none',css)
        self.assertIn('html[data-halloween="off"] .halloween-avatar-hat{display:none}',css)

    def test_spider_grows_without_changing_thread_anchor(self):
        css=Path('halloween.css').read_text(encoding='utf-8')
        self.assertIn('transform:scale(1.2);transform-origin:50% 25%',css)
        self.assertIn('left:5.5px;top:0;bottom:9px;width:.7px',css)

    def test_web_uses_actual_button_geometry_and_content_clearance(self):
        source=Path('halloween.js').read_text(encoding='utf-8')
        self.assertIn('const width=button.clientWidth',source)
        self.assertIn("button.style.setProperty('--halloween-web-width'",source)
        self.assertIn('content.selectNodeContents(button)',source)
        self.assertIn("button.style.setProperty('--halloween-web-height'",source)
        self.assertIn("preserveAspectRatio='none'",Path('halloween.css').read_text(encoding='utf-8'))

    def test_navigation_decoration_is_active_only_and_uses_shared_toggle(self):
        css=Path('halloween.css').read_text(encoding='utf-8')
        self.assertIn('html[data-halloween="on"] #mainNav button.nav-active::before',css)
        self.assertIn('.halloween-spider{position:fixed',css)
        self.assertIn('pointer-events:none',css)
        self.assertIn('pqm-spider-sway',css)
        self.assertIn('.halloween-spider{animation:none}',css)
        self.assertNotIn('overflow:visible!important',css)

    def test_cat_svg_is_identical_to_approved_parent(self):
        current=Path('halloween.js').read_text(encoding='utf-8')
        svg=lambda s:s[s.index('<svg class="halloween-cat"'):s.index('</svg>')+6]
        # SHA256 of the approved SVG in parent a619e1d; works in ZIP fixtures too.
        self.assertEqual(hashlib.sha256(svg(current).encode()).hexdigest(),'637d43a94e1e24e42d1d23d933d3e18ccfe0d4abf89324af94549a9c561a9e57')

    def test_decorative_svg_and_no_backend_calls(self):
        source=Path('halloween.js').read_text(encoding='utf-8')
        self.assertIn('aria-hidden="true" focusable="false"',source)
        self.assertIn("document.querySelector('.prod-brand-copy strong')",source)
        for forbidden in ['fetch(', 'XMLHttpRequest', '/api/', 'setInterval(', 'setTimeout(']:
            self.assertNotIn(forbidden,source)
        self.assertIn('halloween.js',Path('index.html').read_text(encoding='utf-8'))

    def test_overlay_and_accessibility_contract(self):
        css=Path('halloween.css').read_text(encoding='utf-8')
        self.assertIn('position:absolute;pointer-events:none',css)
        self.assertIn('prefers-reduced-motion:reduce',css)
        self.assertIn('animation:none',css)
        self.assertIn('html[data-halloween="off"] .halloween-cat{display:none}',css)
        self.assertNotIn('.topbar{',css)

    def test_preference_restored_and_storage_failure_is_safe(self):
        script=r"""
        const vm=require('vm'),fs=require('fs'),assert=require('assert/strict');
        const source=fs.readFileSync('halloween.js','utf8');
        for(const stored of [null,'0','1','denied']){
          let svg='',added=false;
          const document={documentElement:{dataset:{}},querySelector:s=>s.includes('strong')?{
            classList:{add:()=>added=true},insertAdjacentHTML:(_,html)=>svg=html
          }:null};
          vm.runInNewContext(source,{document,localStorage:{getItem:()=>{if(stored==='denied')throw Error('blocked');return stored}}});
          assert.equal(document.documentElement.dataset.halloween,stored==='0'?'off':'on');
          assert(added&&svg.includes('cat-eyes'));
        }
        """
        result=subprocess.run(['node','-e',script],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
