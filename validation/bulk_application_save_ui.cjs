'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const bulk=require('../bulk_application_save.js');
const fs=require('node:fs'),vm=require('node:vm');
const error=(status,code)=>Object.assign(new Error('synthetic'),{httpStatus:status,code});
function fixture(count=3){
  const values=new Map(Array.from({length:count},(_,i)=>[String(i),{protocol_number:''}]));
  const items=bulk.create([...values.keys()].map(id=>({id,expected:{protocol_number:''}})),{protocol_number:'123'});
  let writes=0,reads=0,active=0,peak=0;
  const transport={read:async id=>{reads++;return {...values.get(id)}},write:async(id,desired,expected)=>{
    writes++;active++;peak=Math.max(peak,active);await new Promise(resolve=>setTimeout(resolve,1));active--;
    if(values.get(id).protocol_number!==expected.protocol_number&&values.get(id).protocol_number!==desired.protocol_number)throw error(409,'bulk_value_conflict');
    values.set(id,{...desired});return {saved:true};
  }};
  return {items,values,transport,stats:()=>({writes,reads,peak})};
}
test('all successes are sequential, frozen and confirmed',async()=>{
  const f=fixture(30);assert.equal((await bulk.run(f.items,f.transport)).confirmed,30);
  assert.equal(f.stats().peak,1);assert.ok(Object.isFrozen(f.items[0].desired));assert.ok(Object.isFrozen(f.items[0].expected));
});
test('partial 502 before commit: retry only missing rows after readback',async()=>{
  const f=fixture();const write=f.transport.write;let fail=true;
  f.transport.write=async(...args)=>{if(args[0]==='1'&&fail)throw error(502);return write(...args)};
  assert.deepEqual(await bulk.run(f.items,f.transport),{total:3,confirmed:2,unconfirmed:1,conflict:0,error:0});
  fail=false;const before=f.stats().writes;
  assert.equal((await bulk.run(f.items,f.transport,{retry:true})).confirmed,3);
  assert.equal(f.stats().writes-before,1);
});
test('response lost after commit does not repeat PATCH',async()=>{
  const f=fixture(1),write=f.transport.write;
  f.transport.write=async(...args)=>{await write(...args);throw error(502)};
  assert.equal((await bulk.run(f.items,f.transport)).confirmed,1);
  await bulk.run(f.items,f.transport,{retry:true});assert.equal(f.stats().writes,1);
});
test('timeout plus unavailable readback is unconfirmed and never blindly retried',async()=>{
  const f=fixture(1);let calls=0;
  f.transport.write=async()=>{calls++;throw new Error('AbortError')};f.transport.read=async()=>{throw error(503)};
  assert.equal((await bulk.run(f.items,f.transport)).unconfirmed,1);
  await bulk.run(f.items,f.transport,{retry:true});assert.equal(calls,1);
});
test('SQLite lock/503 reconciles and permits only one explicit retry',async()=>{
  const f=fixture(1);let calls=0;
  f.transport.write=async()=>{calls++;throw error(503)};
  await bulk.run(f.items,f.transport);await bulk.run(f.items,f.transport,{retry:true});await bulk.run(f.items,f.transport,{retry:true});
  assert.equal(calls,2);assert.equal(f.items[0].status,'unconfirmed');
});
test('concurrent officer edit is never overwritten',async()=>{
  const f=fixture(1);f.values.set('0',{protocol_number:'OTHER'});
  assert.equal((await bulk.run(f.items,f.transport)).conflict,1);assert.equal(f.values.get('0').protocol_number,'OTHER');
});
test('concurrent edit between initial failure and explicit retry is detected by readback',async()=>{
  const f=fixture(1);let calls=0;f.transport.write=async()=>{calls++;throw error(502)};
  await bulk.run(f.items,f.transport);f.values.set('0',{protocol_number:'OTHER'});
  assert.equal((await bulk.run(f.items,f.transport,{retry:true})).conflict,1);assert.equal(calls,1);
});
test('deterministic forbidden and formed-protocol errors remain errors, not retries',async()=>{
  for(const status of [400,401,403,404,409]){
    const f=fixture(1);let calls=0;f.transport.write=async()=>{calls++;throw error(status)};
    assert.equal((await bulk.run(f.items,f.transport)).error,1);
    await bulk.run(f.items,f.transport,{retry:true});assert.equal(calls,1);assert.equal(f.stats().reads,0);
  }
});
test('unseen row with existing number is not silently adopted',async()=>{
  const f=fixture(1);f.items[0].expected=null;f.values.set('0',{protocol_number:'OTHER'});
  assert.equal((await bulk.run(f.items,f.transport)).conflict,1);assert.equal(f.stats().writes,0);
});
test('malformed and missing readback fields never permit retry',async()=>{
  for(const current of [{},{protocol_number:null}]){
    const f=fixture(1);let calls=0;f.transport.write=async()=>{calls++;throw error(502)};f.transport.read=async()=>current;
    await bulk.run(f.items,f.transport);await bulk.run(f.items,f.transport,{retry:true});assert.equal(calls,1);
  }
});
test('repeated click is blocked in real UI controller; selection/values snapshot is fixed',async()=>{
  const app=fs.readFileSync(require('node:path').join(__dirname,'../app.js'),'utf8');
  const controller=app.slice(app.indexOf('async function runBulkOperation(retry){'),app.indexOf('\nlet auditPage=',app.indexOf('async function runBulkOperation(retry){')));
  const elements={};const node=()=>({textContent:'',innerHTML:'',disabled:false,hidden:false});
  const dialog={querySelectorAll:()=>[],oncancel:null};let calls=0,release;
  const f=fixture(1);const context={bulkInFlight:false,bulkOperation:f.items,selected:new Set(['0']),
    $:s=>s==='#bulkDialog'?dialog:(elements[s]??=node()),PqmBulkSave:bulk,API:'/api',esc:s=>s,toast:()=>{},loadRows:async()=>{},
    bulkRequest:async()=>{calls++;await new Promise(resolve=>release=resolve);return {saved:true}}};
  context.applicationSelection={remove:id=>context.selected.delete(id)};
  vm.createContext(context);vm.runInContext(controller,context);
  const first=context.runBulkOperation(false);await context.runBulkOperation(false);
  assert.equal(calls,1);assert.equal(context.bulkInFlight,true);release();await first;
  assert.equal(context.bulkInFlight,false);assert.match(elements['#bulkSummary'].textContent,/Збереження підтверджено: 1/);
  assert.equal(context.selected.size,0);
});
test('snapshot is independent of later input/selection changes',()=>{
  const ids=[{id:'0',expected:{protocol_number:''}}],changes={protocol_number:'123'};
  const operation=bulk.create(ids,changes);
  ids[0].expected.protocol_number='OTHER';ids.push({id:'1'});changes.protocol_number='456';
  assert.equal(operation.length,1);assert.equal(operation[0].expected.protocol_number,'');assert.equal(operation[0].desired.protocol_number,'123');
});
test('real bulk request wrapper aborts timeout and disables cache',async()=>{
  const app=fs.readFileSync(require('node:path').join(__dirname,'../app.js'),'utf8');
  const wrapper=app.slice(app.indexOf('async function bulkRequest('),app.indexOf('async function runBulkOperation('));
  let cache,cleared=false;
  const context={AbortController,setTimeout:fn=>{queueMicrotask(fn);return 1},clearTimeout:()=>{cleared=true},
    request:async(url,options)=>{cache=options.cache;await new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(new Error('timeout')),{once:true}))}};
  vm.createContext(context);vm.runInContext(wrapper,context);
  await assert.rejects(context.bulkRequest('/synthetic'),/timeout/);assert.equal(cache,'no-store');assert.equal(cleared,true);
});
