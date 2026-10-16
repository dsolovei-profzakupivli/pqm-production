'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const selection=require('../application_selection.js'),bulk=require('../bulk_application_save.js');
const app=fs.readFileSync(require('node:path').join(__dirname,'../app.js'),'utf8');
const records=n=>Array.from({length:n},(_,i)=>({id:String(i),protocolNumber:'',protocolDecision:'',complianceStatus:'',historicalReadOnly:false}));
function ui(n=72){
  const selected=new Set(),state=selection.create(selected),nodes=new Map(),messages=[];
  const filters={search:'',framework_id:'f'},all=records(n);let page=1;
  const ctx={applicationSelection:state,PqmApplicationSelection:selection,selected,rows:[],rowsFilterSignature:null,
    loading:false,selectAllResultsPending:false,bulkInFlight:false,loadRowsGeneration:0,page:1,pages:1,total:n,
    sortKey:'receivedDate',sortDirection:'desc',multiSort:[],
    API:'/api',fieldMap:{protocolNumber:'protocol_number',protocolDecision:'protocol_decision',complianceStatus:'compliance_status'},URLSearchParams,
    currentFilterParams:()=>({...filters}),toast:message=>messages.push(message),mapRow:x=>x,
    invalidateRegistryStats(){},updateApplicationFilterStyles(){},saveFilterState(){},render(){},loadStats(){},
    $:key=>{if(!nodes.has(key))nodes.set(key,{});return nodes.get(key)},
    request:async()=>({items:all.slice((page-1)*50,page*50),page,pages:Math.ceil(n/50),total:n}),
    bulkRequest:async()=>({items:all.map(row=>({id:row.id,values:{protocol_number:'',protocol_decision:'',compliance_status:''}})),total:n})};
  vm.createContext(ctx);vm.runInContext(app.slice(app.indexOf('function syncApplicationSelection(){'),app.indexOf('function bindStaticMulti(')),ctx);
  return {ctx,state,filters,all,messages,nodes,setPage:value=>{page=value;ctx.page=value}};
}
for(const n of [20,72,205])test(`select-all freezes all ${n} results, not just the current 50`,async()=>{
  const f=ui(n);await f.ctx.loadRows();assert.equal(f.ctx.rows.length,Math.min(50,n));
  await f.ctx.selectAllApplicationResults();assert.equal(f.ctx.selected.size,n);assert.equal(f.state.entries().length,n);
  f.all.push({id:'new',protocolNumber:''});f.setPage(2);await f.ctx.loadRows();assert.equal(f.ctx.selected.size,n);
});
test('page-only selection and manual selections survive pagination and sorting',async()=>{
  const f=ui();await f.ctx.loadRows();f.ctx.selectApplicationPage();assert.equal(f.ctx.selected.size,50);
  f.setPage(2);await f.ctx.loadRows();f.state.toggle(f.ctx.rows[0],true);assert.equal(f.ctx.selected.size,51);
  f.ctx.selectApplicationPage(false);assert.equal(f.ctx.selected.size,50);
  f.setPage(1);await f.ctx.loadRows();assert.equal(f.ctx.selected.size,50);
  assert.equal(selection.signature({...f.filters,sort:'participant',page:2}),selection.signature(f.filters));
});
test('filter changes explicitly clear selection and never include old hidden rows',async()=>{
  const f=ui();await f.ctx.loadRows();f.ctx.selectApplicationPage();f.filters.search='different';await f.ctx.loadRows();
  assert.equal(f.ctx.selected.size,0);assert.match(f.messages.at(-1),/вибір 50 заявок очищено/);
});
test('individual rows on different pages remain selected without selecting the whole page',async()=>{
  const f=ui();await f.ctx.loadRows();f.state.toggle(f.ctx.rows[2],true);
  f.setPage(2);await f.ctx.loadRows();f.state.toggle(f.ctx.rows[3],true);
  assert.deepEqual([...f.ctx.selected],['2','53']);f.setPage(1);await f.ctx.loadRows();
  assert.equal(f.state.entries().length,2);assert.deepEqual([...f.ctx.selected],['2','53']);
});
test('historical protection metadata remains attached to an off-page selected row',async()=>{
  const f=ui();f.all[0].historicalReadOnly=true;await f.ctx.loadRows();f.state.toggle(f.ctx.rows[0],true);
  f.setPage(2);await f.ctx.loadRows();assert.equal(f.state.entries()[0].historicalReadOnly,true);
  assert.equal(f.ctx.rows.some(row=>row.id==='0'),false);assert.equal(f.ctx.selected.size,1);
});
test('stale all-results response cannot cross changed filters',async()=>{
  const f=ui();await f.ctx.loadRows();let resolve;
  f.ctx.bulkRequest=()=>new Promise(r=>resolve=r);const pending=f.ctx.selectAllApplicationResults();
  f.filters.search='new';await f.ctx.loadRows();resolve({items:[{id:'old',values:{}}],total:1});await pending;
  assert.equal(f.ctx.selected.size,0);
});
test('double select-all click starts only one request',async()=>{
  const f=ui();await f.ctx.loadRows();let resolve,calls=0;
  f.ctx.bulkRequest=()=>{calls++;return new Promise(r=>resolve=r)};
  const first=f.ctx.selectAllApplicationResults();await f.ctx.selectAllApplicationResults();assert.equal(calls,1);
  resolve({items:[],total:0});await first;
});
test('duplicate or incomplete all-results snapshot never replaces a valid selection',async()=>{
  const f=ui();await f.ctx.loadRows();f.state.toggle(f.ctx.rows[0],true);
  for(const data of [{items:[{id:'1',values:{}}],total:72},{items:[{id:'1',values:{}},{id:'1',values:{}}],total:2}]){
    f.ctx.bulkRequest=async()=>data;await f.ctx.selectAllApplicationResults();assert.deepEqual([...f.ctx.selected],['0']);
  }
});
test('failed filtered load disables actions on stale visible rows',async()=>{
  const f=ui();await f.ctx.loadRows();f.filters.search='missing';f.ctx.request=async()=>{throw new Error('offline')};
  await f.ctx.loadRows();assert.equal(f.ctx.applicationRowsCurrent(),false);
  f.ctx.selectApplicationPage();assert.equal(f.ctx.selected.size,0);
});
test('confirmation shows exact 72 IDs count and values; cancellation does not start PATCH',async()=>{
  const chosen=records(72),selected=new Set(chosen.map(r=>r.id));let starts=0,answer=false,message='';
  const ctx={bulkInFlight:false,bulkOperation:null,selectAllResultsPending:false,selected,rows:chosen.slice(0,50),
    applicationSelection:{entries:()=>chosen},syncApplicationSelection(){},applicationRowsCurrent:()=>true,
    fieldMap:{protocolNumber:'protocol_number'},PqmBulkSave:bulk,PqmApplicationSelection:selection,currentFilterParams:()=>({framework_id:'f'}),
    $:key=>key.includes('data-clear')?null:{value:'900'},$$:()=>[{dataset:{enable:'protocolNumber'}}],toast(){},
    window:{confirm:text=>{message=text;return answer}},runBulkOperation:async()=>{starts++}};
  vm.createContext(ctx);vm.runInContext(app.slice(app.indexOf('async function applyBulk(e){'),app.indexOf('async function bulkRequest(')),ctx);
  await ctx.applyBulk({preventDefault(){}});assert.equal(starts,0);assert.match(message,/72 заявок/);assert.match(message,/900/);
  answer=true;await ctx.applyBulk({preventDefault(){}});assert.equal(starts,1);assert.equal(ctx.bulkOperation.length,72);
  assert.equal(new Set(ctx.bulkOperation.map(x=>x.id)).size,72);assert.ok(Object.isFrozen(ctx.bulkOperation[0].desired));
});
test('retry controller refuses an operation whose filter scope has changed',async()=>{
  const messages=[];const ctx={bulkInFlight:false,bulkOperation:[{id:'old'}],bulkOperationScope:selection.signature({search:'old'}),
    PqmApplicationSelection:selection,currentFilterParams:()=>({search:'new'}),toast:message=>messages.push(message)};
  vm.createContext(ctx);vm.runInContext(app.slice(app.indexOf('async function runBulkOperation(retry){'),app.indexOf('\nlet auditPage=',app.indexOf('async function runBulkOperation(retry){'))),ctx);
  await ctx.runBulkOperation(true);assert.match(messages[0],/повтор старої вибірки заблоковано/);assert.equal(ctx.bulkInFlight,false);
});
test('205 sequential saves report completed progress; retry skips confirmed and conflicting rows',async()=>{
  const values=new Map(records(205).map(row=>[row.id,''])),calls=[],progress=[];
  const operation=bulk.create(records(205).map(row=>({id:row.id,expected:{protocol_number:''}})),{protocol_number:'900'});
  let failing=true,active=0,peak=0;
  const transport={read:async id=>({protocol_number:values.get(id)}),write:async(id,desired,expected)=>{
    calls.push(id);active++;peak=Math.max(peak,active);await Promise.resolve();active--;
    if(values.get(id)!==expected.protocol_number&&values.get(id)!==desired.protocol_number)throw Object.assign(new Error('conflict'),{code:'bulk_value_conflict',httpStatus:409});
    if(id==='71'&&failing)throw Object.assign(new Error('502'),{httpStatus:502});
    values.set(id,desired.protocol_number);
    if(id==='101'&&failing)throw new Error('lost after commit');return {saved:true};
  }};
  values.set('204','OTHER');const first=await bulk.run(operation,transport,{onProgress:(done,total,counts)=>progress.push([done,total,counts.confirmed])});
  assert.equal(first.confirmed,203);assert.equal(first.unconfirmed,1);assert.equal(first.conflict,1);
  assert.equal(peak,1);assert.deepEqual(progress.at(-1),[205,205,203]);assert.equal(progress.length,205);
  failing=false;const before=calls.length;const second=await bulk.run(operation,transport,{retry:true});
  assert.equal(second.confirmed,204);assert.deepEqual(calls.slice(before),['71']);assert.equal(values.get('204'),'OTHER');
});
