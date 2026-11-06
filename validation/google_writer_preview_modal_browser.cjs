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
window.API='/api';window.calls=[];window.notices=[];window.failApply=false;window.applyGate=null;window.resumeMode=false;window.crypto.randomUUID=()=> 'fixture-request-id';
window.esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));window.displayDate=value=>String(value??'');window.toast=(message,type)=>notices.push({message,type});
window.request=async(url,options={})=>{
  calls.push({url,method:options.method||'GET',body:options.body||''});
  if(url.endsWith('/google-writer/status'))return{can_execute:true,channel_ready:true,blocked:resumeMode,automation_blocked:true,configured_enabled:false,schedule:'07:00',last_status:resumeMode?'partial':'never',hour:7,minute:0,runs:resumeMode?[{request_id:'r'.repeat(32),actor:'test-user',trigger:'manual',status:'partial',resume_available:true,result:{counts:{append:25,update:0}}}]:[]};
  if(url.endsWith('/google-writer/preview'))return{ticket:'opaque-preview-ticket',plan_digest:'P'.repeat(43),details_digest:'D'.repeat(43),expires_at:9999999999,counts:{append:1234,update:7,conflict:2}};
  if(url.includes('/google-writer/preview-details/'))return{details_digest:'D'.repeat(43),details:{version:1,environment:'SANDBOX',plan_digest:'P'.repeat(43),
    counts:{append:1234,update:7,conflict:2,error:0},
    appends:Array.from({length:1234},(_,i)=>({operation:'APPEND',tab:'ФОП',name:'Supplier '+i,code:String(i).padStart(6,'0'),cells:[{column:'A',new_value:'=TODAY()',formula:true},{column:'B',new_value:'000001'}]})),
    updates:Array.from({length:7},(_,i)=>({operation:'UPDATE',tab:'ЮО',name:i?'Supplier':'<img src=x onerror=alert(1)>',code:'000002',cells:[{column:'E',old_value:'Old',new_value:'New'}]})),
    conflicts:Array.from({length:2},()=>({tab:'ФОП',name:'Conflict',code:'000003',reason:'routing_mismatch',explanation:'Тип не відповідає вкладці'})),errors:[]}};
  if(url.endsWith('/google-writer/preview-scope'))return{scope:'APPEND_ONLY',counts:{append:1234,update:0,conflict:2,error:0},ticket:'opaque-append-ticket'};
  if(url.endsWith('/google-writer/resume-preview'))return{status:'RESUME_READY',scope:'APPEND_ONLY',request_id:'r'.repeat(32),plan_digest:'P'.repeat(43),details_digest:'D'.repeat(43),checkpoint_digest:'C'.repeat(43),next_chunk:4,counts:{append:5,update:0,conflict:0,error:0},ticket:'opaque-resume-ticket',details:{version:1,environment:'SANDBOX',plan_digest:'P'.repeat(43),remaining_plan_digest:'R'.repeat(43),counts:{append:5,update:0,conflict:0,error:0},appends:Array.from({length:5},()=>({operation:'APPEND',tab:'ФОП',name:'Remaining',code:'000004',cells:[{column:'A',new_value:'=TODAY()',formula:true}]})),updates:[],conflicts:[],errors:[]}};
  if(url.endsWith('/google-writer/resume-append-only'))return{started:true,status:'APPEND_ONLY_RESUME_ACCEPTED'};
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
  if(document.querySelectorAll('#googleWriterPreviewDetails tbody tr').length!==1243)throw Error('Detailed APPEND/UPDATE/conflict rows missing');
  if(document.querySelector('#googleWriterPreviewDetails img'))throw Error('Preview data was not escaped');
  if(!document.querySelector('#googleWriterPreviewDetails').textContent.includes('Old → New'))throw Error('Old/new UPDATE values are missing');
  const darkColor=getComputedStyle(modal).backgroundColor;
  if(lightColor===darkColor)throw Error('Modal surface does not respond to theme');
  document.getElementById('googleWriterPreviewCancel').click();await wait(()=>!modal.open&&!googleWriterBusy);
  await openPreview();
  document.getElementById('googleWriterPreviewAppendOnly').click();
  await wait(()=>!googleWriterBusy&&applyCalls()===1);
  const scopeCall=calls.find(item=>item.url.endsWith('/google-writer/preview-scope'));
  const scopedBody=JSON.parse(scopeCall.body),applyBody=JSON.parse(calls.filter(item=>item.url.endsWith('/google-writer/apply')).at(-1).body);
  if(scopedBody.scope!=='APPEND_ONLY'||scopedBody.confirmed!==true||applyBody.ticket!=='opaque-append-ticket')throw Error('APPEND_ONLY did not use a separately scoped ticket');
  const applyButton=document.getElementById('googleWriterPreviewApply');
  let releaseApply;applyGate=new Promise(resolve=>releaseApply=resolve);
  await openPreview();
  applyButton.click();applyButton.click();
  await wait(()=>applyCalls()===2);
  if(!applyButton.disabled)throw Error('Apply confirmation button was not disabled after activation');
  run.click();if(previews()!==7)throw Error('A second Preview started while Apply was in flight');
  if(modal.open)throw Error('Preview reopened while Apply was in flight');
  releaseApply();await wait(()=>!googleWriterBusy);
  if(!notices.some(item=>item.message.includes('Запуск прийнято')))throw Error('Success toast was not preserved');
  failApply=true;await openPreview();document.getElementById('googleWriterPreviewApply').click();
  await wait(()=>!googleWriterBusy);
  if(!notices.some(item=>item.type==='error'&&item.message==='fixture apply error'))throw Error('Apply error toast was not preserved');
  resumeMode=true;await loadGoogleWriterJob();await wait(()=>document.querySelector('.google-writer-resume'));
  const beforeResumeApply=applyCalls(),beforeResumePreview=previews();
  document.querySelector('.google-writer-resume').click();
  await wait(()=>modal.open&&googleWriterBusy,'resume confirmation');
  if(document.getElementById('googleWriterPreviewAppendOnly').hidden!==true)throw Error('Resume must not offer APPEND/UPDATE scope selection');
  if(document.getElementById('googleWriterPreviewApply').textContent!=='Продовжити порції')throw Error('Resume action label missing');
  document.getElementById('googleWriterPreviewApply').click();
  await wait(()=>calls.some(item=>item.url.endsWith('/google-writer/resume-append-only')));
  await wait(()=>!googleWriterBusy);
  const resumeCall=calls.find(item=>item.url.endsWith('/google-writer/resume-append-only'));
  if(JSON.parse(resumeCall.body).ticket!=='opaque-resume-ticket'||JSON.parse(resumeCall.body).confirmed!==true)throw Error('Continuation did not use fresh ticket and explicit confirmation');
  if(applyCalls()!==beforeResumeApply||previews()!==beforeResumePreview)throw Error('Continuation called ordinary Preview or Apply');
  if(!notices.some(item=>item.message.includes('Продовження прийнято')))throw Error('Continuation success notice missing');
  document.querySelector('#result').dataset.tests='PASS';document.querySelector('#result').textContent='PASS: detailed rows; escaped values; separate metrics; APPEND_ONLY scoped ticket; cancel, X, Escape, backdrop; no Apply on cancel; single Apply; busy lock; light/dark; success/error notices; resume confirmation uses fresh ticket without ordinary Preview/Apply';
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
