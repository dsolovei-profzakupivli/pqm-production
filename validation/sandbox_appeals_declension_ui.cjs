const fs=require('fs');
const vm=require('vm');
const assert=require('assert');
const src=fs.readFileSync('app.js','utf8');
const actions=src.slice(src.indexOf('function unresolvedViolationDeclensionsBySide('),src.indexOf('async function loadReferencesView(){'));
assert(src.includes('return html+violationDeclensionActions(declensions)+controls}'));
const openSource=src.slice(src.indexOf('async function openDocumentDeclension('),src.indexOf('async function openDeclensionFromValidation('));
assert(openSource.indexOf("if(context.originType==='violation_report_side')")<openSource.indexOf("$('#requestDetailsDialog').close()"), 'side editor must keep the appeal card open');
const entry=(side,status='unresolved',original=side)=>({subject_label:side==='customer'?'Замовник':'Постачальник',status,original,entity_type:'legal_entity',grammatical_case:'genitive'});
const customer=entry('customer'),supplier=entry('supplier');
const context={currentMe:{permissions:{'appeals.review':true,'declension.manage':true}},openDocumentDeclension:async(item,selection)=>{context.selection={item,selection}}};
vm.createContext(context);vm.runInContext(actions,context);
const render=entries=>vm.runInContext(`violationDeclensionActions(${JSON.stringify(entries)})`,context);
const sides=html=>({customer:html.includes('↗ Для замовника'),supplier:html.includes('↗ Для постачальника')});
assert.deepStrictEqual(sides(render([customer])),{customer:true,supplier:false});
assert.deepStrictEqual(sides(render([supplier])),{customer:false,supplier:true});
assert.deepStrictEqual(sides(render([customer,supplier])),{customer:true,supplier:true});
assert.strictEqual(render([]),'');
assert.strictEqual(render([entry('customer','resolved'),entry('supplier','resolved')]),'');
assert.deepStrictEqual(sides(render([entry('customer','resolved'),customer])),{customer:true,supplier:false});
const twoCustomer=[entry('customer','resolved'),customer,entry('customer','unresolved','second'),supplier];
(async()=>{
  await vm.runInContext(`openViolationDeclensionSide('customer',{id:'R1',report_id:'R1',protocol_readiness:{declensions:${JSON.stringify(twoCustomer)}}})`,context);
  assert.strictEqual(context.selection.item.original,'customer');
  assert.deepStrictEqual(Array.from(context.selection.selection.entries,entry=>entry.original),['customer','second']);
  assert.strictEqual(context.selection.selection.originType,'violation_report_side');
  assert.strictEqual(context.selection.selection.side,'customer');
  context.currentMe={role:'viewer',permissions:{'appeals.review':false,'declension.manage':false}};
  assert.strictEqual(render([customer,supplier]),'');
  context.currentMe={permissions:{'appeals.review':true,'declension.manage':false}};
  assert.strictEqual(render([customer]),'');
  context.currentMe={permissions:{'appeals.review':true,'declension.manage':true}};
  const formValues={'#declensionType':'legal_entity','#declensionOriginal':'customer','#declensionGenitive':'filled','#declensionDative':'','#declensionAccusative':'','#declensionComment':''};
  const saved=[];let returned=0,next=null,lastRendered='';
  Object.assign(context,{
    $:selector=>selector==='#declensionDialog'?{close:()=>{}}:selector==='#declensionSearch'?{value:''}:{value:formValues[selector]||''},
    API:'/api',editingDeclensionId:null,declensionReturnContext:context.selection.selection,declensionItems:[],
    request:async(_url,options)=>{saved.push(JSON.parse(options.body))},
    loadDeclensionOverrides:async()=>{context.declensionItems=saved.map(row=>({...row}))},
    openDeclensionEditor:(item,grammaticalCase,requestContext)=>{next={item,grammaticalCase,requestContext}},
    returnToDeclensionReport:async()=>{returned++},toast:()=>{},
    reloadOpenViolationReportDetail:async()=>{const remaining=twoCustomer.filter(row=>row.subject_label==='Замовник'&&row.status!=='resolved'&&!saved.some(savedRow=>savedRow.original===row.original&&savedRow.genitive));lastRendered=render(remaining);return{protocol_readiness:{declensions:remaining}}},
  });
  const lookup=src.slice(src.indexOf('function declensionLookup('),src.indexOf('async function returnToDeclensionReport(){'));
  const save=src.slice(src.indexOf('async function saveDeclensionEditor(){'),src.indexOf('async function deleteDeclension(id){'));
  vm.runInContext(lookup+save,context);
  await vm.runInContext('saveDeclensionEditor()',context);
  assert.strictEqual(next.requestContext.original,'second');assert.strictEqual(returned,0);
  assert.deepStrictEqual(sides(lastRendered),{customer:true,supplier:false});
  formValues['#declensionOriginal']='second';next=null;
  await vm.runInContext('saveDeclensionEditor()',context);
  assert.strictEqual(next,null);assert.strictEqual(returned,0);
  assert.strictEqual(lastRendered,'');
  assert.strictEqual(context.declensionReturnContext,null);
  const list=src.slice(src.indexOf('async function loadViolationReports(){'),src.indexOf('function violationDetailHtml(item){'));
  const reloadStart=src.indexOf('async function reloadOpenViolationReportDetail(){');
  const reload=src.slice(reloadStart,src.indexOf('\n}\n',reloadStart)+3);
  assert(list.includes('if(syncWasActive&&!sync.running)await reloadOpenViolationReportDetail()'));
  const nodes=new Map();const node=selector=>{if(!nodes.has(selector))nodes.set(selector,{value:'',innerHTML:'',textContent:'',disabled:false,open:selector==='#requestDetailsDialog',querySelectorAll:()=>[]});return nodes.get(selector)};
  const refreshContext={
    $:node,$$:()=>[],API:'/api',URLSearchParams,requestsPage:1,requestsPages:1,requestsPolling:null,selectedRequestAuthority:'',violationReports:[],
    requestStatusLabels:{},requestReasonLabels:{},populateRequestSelect:()=>{},renderRequestAuthorityCards:()=>{},displayDate:value=>value,requestLabel:value=>value,esc:value=>value,
    requestsRefreshState:{running:false,starting:false},updateRequestsRefreshAvailability:change=>Object.assign(refreshContext.requestsRefreshState,change),
    activeDeclensionRequest:{id:'R1'},syncRunning:false,detail:{id:'R1',report_id:'R1',protocol_readiness:{declensions:[customer]}},
    request:async url=>url.includes('/violation-reports/R1')?refreshContext.detail:{pages:1,items:[],pending:0,satisfied:0,declined:0,statuses:[],reasons:[],authorities:[],sync:{running:refreshContext.syncRunning}},
    violationDeclensionActions:entries=>render(entries),violationDetailHtml:item=>render(item.protocol_readiness.declensions),
    bindViolationReview:item=>{refreshContext.activeDeclensionRequest=item},setInterval:()=>1,clearInterval:()=>{},toast:()=>{},
  };
  vm.createContext(refreshContext);vm.runInContext(list+reload,refreshContext);
  const load=()=>vm.runInContext('loadViolationReports()',refreshContext);
  refreshContext.syncRunning=true;await load();
  refreshContext.detail={id:'R1',report_id:'R1',protocol_readiness:{declensions:[supplier]}};
  refreshContext.syncRunning=false;await load();
  assert.deepStrictEqual(sides(node('#requestDetailsBody').innerHTML),{customer:false,supplier:true});
  refreshContext.syncRunning=true;await load();
  refreshContext.detail={id:'R1',report_id:'R1',protocol_readiness:{declensions:[]}};
  refreshContext.syncRunning=false;await load();
  assert.strictEqual(node('#requestDetailsBody').innerHTML,'');
  console.log('PASS: appeal side matrix, unresolved-only sequence, save progression, open-card refresh');
})().catch(error=>{console.error(error);process.exit(1)});
