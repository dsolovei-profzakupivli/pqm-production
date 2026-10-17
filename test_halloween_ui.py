"""Frontend-only seasonal decoration contracts; no runtime or external API."""
from pathlib import Path
import subprocess
import unittest


class HalloweenUiTests(unittest.TestCase):
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
