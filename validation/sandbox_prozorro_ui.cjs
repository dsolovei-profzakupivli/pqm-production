const fs=require('fs'),vm=require('vm'),assert=require('assert');
const src=fs.readFileSync('app.js','utf8');
const fn=src.slice(src.indexOf('async function loadRuntimeFeatures(){'),src.indexOf("document.addEventListener('click',event=>{",src.indexOf('async function loadRuntimeFeatures(){')));
(async()=>{
 for(const enabled of [false,true])for(const allowed of [false,true]){
  const nodes=new Map();const $=id=>{if(!nodes.has(id))nodes.set(id,{dataset:{roleDisabled:allowed?'0':'1'},disabled:true});return nodes.get(id)};
  const context={$,role:()=>allowed?'admin':'officer',API:'/api',request:async()=>({sandbox_mode:true,sandbox_prozorro_read:enabled,scheduler_jobs:[],bids_mode:'disabled'}),
   renderGoogleRuntimeState:()=>{},renderManualBidsUpdateState:()=>{},esc:s=>s,toast:()=>{},schedulerJobLabels:{}};
  vm.createContext(context);await vm.runInContext(fn+'; loadRuntimeFeatures()',context);
  assert.equal($('#resetBtn').disabled,!(enabled&&allowed));
  assert.equal($('#resetBtn').dataset.sandboxBlocked,enabled?undefined:'1');
  for(const id of ['#refNazkRefresh','#refAmcuRefresh','#requestsRefresh','#frameworksRefresh','#googleRuntimeToggle']){
   assert.equal($(id).disabled,true,id);assert.equal($(id).dataset.sandboxBlocked,'1',id);
  }
 }
 console.log('PASS: 4 sandbox manual-Prozorro/permission UI cases; other integrations remain blocked');
})().catch(e=>{console.error(e);process.exit(1)});
