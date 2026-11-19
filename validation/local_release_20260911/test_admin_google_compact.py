import subprocess
import unittest
from pathlib import Path


class AdminGoogleCompactTests(unittest.TestCase):
    def test_scoped_layout_and_all_status_fields(self):
        css = Path('styles.css').read_text(encoding='utf-8')
        html = Path('index.html').read_text(encoding='utf-8')
        for field in ('googleClientState', 'googleTokenState', 'googleLastEdrSync',
                      'googleConfigurationSource', 'googleRuntimeState', 'googleRuntimeMessage',
                      'googleRuntimeToggle', 'googleDisconnect'):
            self.assertEqual(html.count('id="' + field + '"'), 1)
        self.assertIn('#adminSyncPanel .google-runtime-panel dl', css)
        self.assertIn('repeat(4,minmax(0,1fr))', css)
        self.assertIn('@media(max-width:480px)', css)
        self.assertIn('overflow-wrap:anywhere', css)

    def test_existing_render_handlers_permissions_and_confirmation(self):
        app = Path('app.js').read_text(encoding='utf-8')
        code = app[app.index('let googleRuntimeFeatureState='):app.index('function renderManualBidsUpdateState(')]
        harness = r'''
const assert=require('node:assert/strict');let currentRole='admin',answer=false,calls=[];
const ids=['googleRuntimeState','googleRuntimeToggle','googleDisconnect','googleClientState','googleTokenState','googleLastEdrSync','googleConfigurationSource','googleRuntimeMessage'];
const elements=Object.fromEntries(ids.map(id=>[id,{dataset:{}}]));
const $=selector=>elements[selector.slice(1)],role=()=>currentRole,displayDate=x=>x,confirm=()=>answer,toast=()=>{},API='/api';
const request=async(url,options)=>{calls.push(url);return {feature:{enabled:false,oauth_connected:false}}};
const loadRuntimeFeatures=async()=>{},loadSupplierEdrStatus=async()=>{},loadSupplierNazkReviewStatus=async()=>{};
__CODE__
(async()=>{
 renderGoogleRuntimeState({enabled:true,oauth_connected:true,client_configured:true,last_edr_sync_at:'2026-10-11',configuration_source:'runtime',message:'Ready'});
 assert.equal(elements.googleClientState.textContent,'Налаштовано');
 assert.equal(elements.googleTokenState.textContent,'Підключено');
 assert.equal(elements.googleLastEdrSync.textContent,'2026-10-11');
 assert.equal(elements.googleConfigurationSource.textContent,'Адміністратор');
 assert.match(elements.googleRuntimeState.textContent,/Увімкнено/);
 assert.equal(elements.googleDisconnect.hidden,false);
 currentRole='viewer';renderGoogleRuntimeState();assert.equal(elements.googleDisconnect.hidden,true);assert.equal(elements.googleRuntimeToggle.disabled,true);
 currentRole='admin';renderGoogleRuntimeState();await disconnectGoogle();assert.equal(calls.length,0);
 answer=true;await disconnectGoogle();assert.deepEqual(calls,['/api/admin/google/disconnect']);
 renderGoogleRuntimeState({enabled:false,oauth_connected:false,message:'Error'});assert.equal(elements.googleDisconnect.hidden,true);assert.equal(elements.googleRuntimeMessage.textContent,'Error');
 console.log('Google UI-only interactions PASS');
})().catch(e=>{console.error(e);process.exit(1)});
'''.replace('__CODE__', code)
        result = subprocess.run(['node', '-e', harness], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
