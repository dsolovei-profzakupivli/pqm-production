const fs=require('fs'),vm=require('vm'),assert=require('assert');
const src=fs.readFileSync('app.js','utf8');
const availability=src.slice(src.indexOf('const requestsRefreshState='),src.indexOf('function applyRoleCapabilities(me){'));
const fn=availability+src.slice(src.indexOf('function environmentBannerText(features){'),src.indexOf("document.addEventListener('click',event=>{",src.indexOf('async function loadRuntimeFeatures(){')));
(async()=>{
 for(const automatic of [false,true])for(const enabled of [false,true])for(const allowed of [false,true]){
  const nodes=new Map();const $=id=>{if(!nodes.has(id))nodes.set(id,{dataset:{roleDisabled:allowed?'0':'1'},disabled:true});return nodes.get(id)};
  const context={$,currentMe:{permissions:{'appeals.update':allowed}},role:()=>allowed?'admin':'officer',API:'/api',request:async()=>({sandbox_mode:true,sandbox_prozorro_read:enabled,sandbox_prozorro_scheduler:automatic,scheduler_jobs:[],bids_mode:'disabled'}),
   renderGoogleRuntimeState:()=>{},renderManualBidsUpdateState:()=>{},esc:s=>s,toast:()=>{},schedulerJobLabels:{}};
  vm.createContext(context);await vm.runInContext(fn+'; loadRuntimeFeatures()',context);
  assert.equal($('#resetBtn').disabled,!(enabled&&allowed));
  assert.equal($('#resetBtn').dataset.sandboxBlocked,enabled?undefined:'1');
  if(enabled)assert.equal($('#resetBtn').title.includes('Автоматично щогодини'),automatic);
  for(const id of ['#refNazkRefresh','#refAmcuRefresh','#frameworksRefresh','#googleRuntimeToggle']){
   assert.equal($(id).disabled,true,id);assert.equal($(id).dataset.sandboxBlocked,'1',id);
  }
  assert.equal($('#requestsRefresh').disabled,true);
  assert.equal($('#requestsRefresh').dataset.sandboxBlocked,undefined);
 }
 {
  const nodes=new Map();const $=id=>{if(!nodes.has(id))nodes.set(id,{dataset:{roleDisabled:'0'},disabled:true});return nodes.get(id)};
  const context={$,currentMe:{permissions:{'appeals.update':true}},role:()=> 'admin',API:'/api',request:async()=>({sandbox_mode:true,google:true,
    sandbox_prozorro_read:true,sandbox_operational:true,sandbox_nazk_read:true,sandbox_amcu_read:true,
    scheduler_jobs:[],bids_mode:'disabled'}),renderGoogleRuntimeState:()=>{},
    renderManualBidsUpdateState:()=>{},esc:s=>s,toast:()=>{},schedulerJobLabels:{}};
  vm.createContext(context);await vm.runInContext(fn+'; loadRuntimeFeatures()',context);
  for(const id of ['#resetBtn','#supplierRegistryRefresh','#frameworksRefresh','#requestsRefresh',
                   '#refNazkRefresh','#refAmcuRefresh','#refAmcuUploadBtn','#edrMonitoringSync']){
    assert.equal($(id).disabled,false,id);assert.equal($(id).dataset.sandboxBlocked,undefined,id);
  }
  for(const id of ['#googleRuntimeToggle','#googleDisconnect']){
    assert.equal($(id).disabled,true,id);assert.equal($(id).dataset.sandboxBlocked,'1',id);
  }
 }
 console.log('PASS: 8 sandbox automatic/manual-Prozorro permission UI cases; other integrations remain blocked');
})().catch(e=>{console.error(e);process.exit(1)});
