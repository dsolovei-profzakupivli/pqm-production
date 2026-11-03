/* Sandbox Google writer confirmation dialog acceptance; mocked API only. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {chromium} = globalThis.PQM_PLAYWRIGHT_TEST_MODULE || require('playwright');
const testBrowser = globalThis.PQM_TEST_BROWSER_PATH || process.env.PQM_TEST_BROWSER;

const root = path.resolve(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8').replace(/\r\n/g, '\n');

const index = read('index.html');
const dialog = index.match(/<dialog id="googleWriterPreviewDialog"[\s\S]*?<\/dialog>/)?.[0];
assert(dialog, 'shared PQM dialog markup must exist in index.html');
const script = read('google_writer_ui.js');
const styles = `${read('styles.css')}\n${read('theme.css')}`;
const harness = `<!doctype html><html data-theme="light"><head><meta charset="utf-8"><style>${styles}</style></head><body>
<button id="pqmGoogleWriterRun" type="button">PQM → Google Sheets</button><span id="pqmGoogleWriterMessage"></span><div id="schedulerJobs"></div>${dialog}
<pre id="result" data-tests="RUNNING">RUNNING</pre>
<script>
window.API='/api';window.calls=[];window.notices=[];window.failApply=false;window.applyGate=null;window.crypto.randomUUID=()=> 'fixture-request-id';
window.esc=value=>String(value??'');window.displayDate=value=>String(value??'');window.toast=(message,type)=>notices.push({message,type});
window.request=async(url,options={})=>{
  calls.push({url,method:options.method||'GET',body:options.body||''});
  if(url.endsWith('/google-writer/status'))return{can_execute:true,channel_ready:true,blocked:false,automation_blocked:true,configured_enabled:false,schedule:'07:00',last_status:'never',hour:7,minute:0,runs:[]};
  if(url.endsWith('/google-writer/preview'))return{ticket:'opaque-preview-ticket',counts:{append:1234,update:7,conflict:2}};
  if(url.endsWith('/google-writer/apply')){if(failApply)throw Error('fixture apply error');if(applyGate)await applyGate;return{accepted:true};}
  throw Error('Unexpected mocked request: '+url);
};
</script><script>${script.replace(/<\/script/gi,'<\\/script')}</script>
<script>
const wait=async(test,label='UI state')=>{for(let i=0;i<200;i++){if(test())return;await new Promise(r=>setTimeout(r,10))}throw Error('Timed out waiting for '+label)};
const modal=document.getElementById('googleWriterPreviewDialog'),run=document.getElementById('pqmGoogleWriterRun');
const applyCalls=()=>calls.filter(x=>x.url.endsWith('/google-writer/apply')).length;
const previews=()=>calls.filter(x=>x.url.endsWith('/google-writer/preview')).length;
async function openPreview(){await wait(()=>!run.disabled,'run button');if(typeof run.onclick!=='function')throw Error('Run handler missing');run.click();await wait(()=>modal.open,'Preview modal; handler='+String(run.onclick)+' busy='+googleWriterBusy+' state='+JSON.stringify(googleWriterJobState)+' calls='+JSON.stringify(calls));}
async function closedWithoutApply(label,close){
  const before=applyCalls();await openPreview();
  if(label==='metrics'){
    if(document.querySelector('#googleWriterPreviewAppend').textContent!=='1 234')throw Error('Append metric is not separately formatted');
    if(document.querySelector('#googleWriterPreviewUpdate').textContent!=='7')throw Error('Update metric is missing');
    if(document.querySelector('#googleWriterPreviewConflict').textContent!=='2')throw Error('Conflict metric is missing');
  }
  await close();await wait(()=>!modal.open&&!googleWriterBusy);
  if(applyCalls()!==before)throw Error(label+' unexpectedly called Apply');
}
(async()=>{
 try{
  await wait(()=>!run.disabled);
  const lightColor=getComputedStyle(modal).backgroundColor;
  await closedWithoutApply('metrics',async()=>document.getElementById('googleWriterPreviewCancel').click());
  await closedWithoutApply('close button',async()=>document.getElementById('googleWriterPreviewClose').click());
  await closedWithoutApply('Escape cancel event',async()=>modal.requestClose('cancel'));
  await closedWithoutApply('backdrop',async()=>modal.dispatchEvent(new MouseEvent('click',{bubbles:true})));
  if(previews()!==4)throw Error('Each reopen should request a fresh Preview');
  document.documentElement.dataset.theme='dark';
  await openPreview();
  const darkColor=getComputedStyle(modal).backgroundColor;
  if(lightColor===darkColor)throw Error('Modal surface does not respond to theme');
  const applyButton=document.getElementById('googleWriterPreviewApply');
  let releaseApply;applyGate=new Promise(resolve=>releaseApply=resolve);
  applyButton.click();applyButton.click();
  await wait(()=>applyCalls()===1);
  if(!applyButton.disabled)throw Error('Apply confirmation button was not disabled after activation');
  run.click();if(previews()!==5)throw Error('A second Preview started while Apply was in flight');
  if(modal.open)throw Error('Preview reopened while Apply was in flight');
  releaseApply();await wait(()=>!googleWriterBusy);
  if(!notices.some(item=>item.message.includes('Запуск прийнято')))throw Error('Success toast was not preserved');
  failApply=true;await openPreview();document.getElementById('googleWriterPreviewApply').click();
  await wait(()=>!googleWriterBusy);
  if(!notices.some(item=>item.type==='error'&&item.message==='fixture apply error'))throw Error('Apply error toast was not preserved');
  document.querySelector('#result').dataset.tests='PASS';document.querySelector('#result').textContent='PASS: separate metrics; cancel, X, Escape, backdrop; no Apply on cancel; single Apply; busy lock; light/dark; success/error notices';
 }catch(error){document.querySelector('#result').dataset.tests='FAIL';document.querySelector('#result').textContent='FAIL: '+String(error&&error.stack||error);}
})();
</script></body></html>`;

(async()=>{
let browser;
try {
  browser=await chromium.launch({headless:true,...(testBrowser?{executablePath:testBrowser}:{})});
  const page=await browser.newPage();
  await page.setContent(harness);
  await page.waitForFunction(()=>document.querySelector('#result')?.dataset.tests!=='RUNNING',{timeout:15000});
  const status=await page.locator('#result').evaluate(node=>({state:node.dataset.tests,text:node.textContent}));
  assert.equal(status.state,'PASS',status.text);
  console.log(status.text);
} finally {
  if(browser)await browser.close();
}
})().catch(error=>{console.error(error);process.exitCode=1});
