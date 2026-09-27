const fs=require('fs');
const vm=require('vm');
const assert=require('assert');
const src=fs.readFileSync('app.js','utf8');
const action=src.slice(src.indexOf('function documentDeclensionAction('),src.indexOf('async function loadReferencesView(){'));
const availability=src.slice(src.indexOf('const requestsRefreshState='),src.indexOf('function applyRoleCapabilities(me){'));
const list=src.slice(src.indexOf('async function loadViolationReports(){'),src.indexOf('function violationDetailHtml(item){'));
assert(action.includes('function requestDeclensionAction(entries)'));
assert(list.includes('updateRequestsRefreshAvailability({running:Boolean(sync.running),starting:false})'));
assert(!list.includes('requestDetailsBody'), 'list refresh must not replace an open appeal card');
assert(src.includes("${requestDeclensionAction(declensions)}"), 'card rerender must use the permission-aware action');
assert(src.includes("$('#requestDetailsBody [data-check-declension]')?.addEventListener('click'"), 'fresh card action must be rebound');
const nodes=new Map();
const $=selector=>{if(!nodes.has(selector))nodes.set(selector,{value:'',innerHTML:'',textContent:'',disabled:false,querySelectorAll:()=>[]});return nodes.get(selector)};
const context={$, $$:()=>[],currentMe:{permissions:{'appeals.update':true,'appeals.review':true,'declension.manage':true}},
  API:'/api',URLSearchParams,requestsPage:1,requestsPages:1,requestsPolling:null,selectedRequestAuthority:'',violationReports:[],
  requestStatusLabels:{},requestReasonLabels:{},populateRequestSelect:()=>{},renderRequestAuthorityCards:()=>{},displayDate:value=>value,
  syncRunning:false,request:async()=>({pages:1,items:[],pending:0,satisfied:0,declined:0,statuses:[],reasons:[],authorities:[],sync:{running:context.syncRunning}}),
  setInterval:()=>1,clearInterval:()=>{}};
vm.createContext(context);
vm.runInContext(availability+action+list,context);
const rendered=()=>vm.runInContext("requestDeclensionAction([{original:'synthetic'}])",context);
const load=()=>vm.runInContext('loadViolationReports()',context);
(async()=>{
  vm.runInContext('updateRequestsRefreshAvailability({runtimeLoaded:true,sandboxMode:true,sandboxOperational:true,sandboxProzorroRead:true})',context);
  const expected=rendered();
  assert(expected.includes('data-check-declension="0"'));
  $('#requestDetailsBody').innerHTML=expected;
  await load();assert.strictEqual(rendered(),expected);assert.strictEqual($('#requestDetailsBody').innerHTML,expected);
  context.syncRunning=true;await load();assert.strictEqual(rendered(),expected);assert.strictEqual($('#requestDetailsBody').innerHTML,expected);
  context.syncRunning=false;await load();await load();assert.strictEqual(rendered(),expected);assert.strictEqual($('#requestDetailsBody').innerHTML,expected);
  assert.strictEqual(vm.runInContext('requestDeclensionAction([])',context),'', 'no business evidence means no action');
  context.currentMe={permissions:{'appeals.update':true,'appeals.review':true,'declension.manage':false}};
  assert.strictEqual(rendered(),'', 'no declension.manage');
  context.currentMe={role:'viewer',permissions:{'appeals.update':false,'appeals.review':false,'declension.manage':false}};
  assert.strictEqual(rendered(),'', 'viewer');
  console.log('PASS: appeal declension action survives refresh/rerender, respects evidence and RBAC');
})().catch(error=>{console.error(error);process.exit(1)});
