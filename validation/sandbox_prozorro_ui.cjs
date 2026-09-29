const fs=require('fs'),vm=require('vm'),assert=require('assert');
const src=fs.readFileSync('app.js','utf8');
const availability=src.slice(src.indexOf('const requestsRefreshState='),src.indexOf('function applyRoleCapabilities(me){'));
const fn=availability+src.slice(src.indexOf('function environmentBannerText(features){'),src.indexOf("document.addEventListener('click',event=>{",src.indexOf('async function loadRuntimeFeatures(){')));
(async()=>{
 for(const automatic of [false,true])for(const readable of [false,true])for(const allowed of [false,true]){
  const nodes=new Map();const $=id=>{if(!nodes.has(id))nodes.set(id,{dataset:{roleDisabled:allowed?'0':'1'},disabled:!allowed});return nodes.get(id)};
  const context={$,currentMe:{permissions:{'appeals.update':allowed}},role:()=>allowed?'admin':'officer',API:'/api',request:async()=>({sandbox_mode:true,sandbox_prozorro_read:readable,sandbox_prozorro_scheduler:automatic,sandbox_operational:true,scheduler_jobs:[],bids_mode:'disabled'}),
   renderGoogleRuntimeState:()=>{},renderManualBidsUpdateState:()=>{},esc:s=>s,toast:()=>{},schedulerJobLabels:{}};
  vm.createContext(context);await vm.runInContext(fn+'; loadRuntimeFeatures()',context);
  // Manual Prozorro is role-gated; a scheduler flag or legacy read opt-in
  // must not install the former per-button SANDBOX denial marker.
  assert.equal($('#resetBtn').disabled,!allowed);
  assert.equal($('#resetBtn').dataset.sandboxBlocked,undefined);
  assert.equal($('#resetBtn').dataset.runtimeDisabled,undefined);
  for(const id of ['#refNazkRefresh','#refAmcuRefresh','#frameworksRefresh']){
   assert.equal($(id).disabled,!allowed,id);assert.equal($(id).dataset.sandboxBlocked,undefined,id);
  }
  assert.equal($('#requestsRefresh').disabled,!(readable&&allowed));
  assert.equal($('#requestsRefresh').dataset.sandboxBlocked,undefined);
  for(const id of ['#supplierEdrSync','#supplierNazkReviewSync']){
   assert.equal($(id).disabled,true,id);
   assert.equal($(id).dataset.runtimeDisabled,'1',id);
  }
 }
 {
  const nodes=new Map();const $=id=>{if(!nodes.has(id))nodes.set(id,{dataset:{roleDisabled:'0'},disabled:false});return nodes.get(id)};
  const context={$,currentMe:{permissions:{'appeals.update':true}},role:()=> 'admin',API:'/api',request:async()=>({sandbox_mode:true,google:true,
    sandbox_prozorro_read:true,sandbox_operational:true,sandbox_nazk_read:true,sandbox_amcu_read:true,
    scheduler_jobs:[],bids_mode:'disabled'}),renderGoogleRuntimeState:()=>{},
    renderManualBidsUpdateState:()=>{},esc:s=>s,toast:()=>{},schedulerJobLabels:{}};
  vm.createContext(context);await vm.runInContext(fn+'; loadRuntimeFeatures()',context);
  for(const id of ['#resetBtn','#supplierRegistryRefresh','#frameworksRefresh','#requestsRefresh',
                   '#refNazkRefresh','#refAmcuRefresh','#refAmcuUploadBtn','#edrMonitoringSync']){
    assert.equal($(id).disabled,false,id);assert.equal($(id).dataset.sandboxBlocked,undefined,id);
  }
  assert.equal($('#googleRuntimeToggle').dataset.sandboxBlocked,undefined);
 }
 console.log('PASS: 8 sandbox manual-Prozorro role/read UI cases; no per-action SANDBOX marker');
})().catch(e=>{console.error(e);process.exit(1)});
