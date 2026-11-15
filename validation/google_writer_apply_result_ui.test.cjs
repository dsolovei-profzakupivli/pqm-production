'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const source=fs.readFileSync('google_writer_apply_result.js','utf8');
const index=fs.readFileSync('index.html','utf8');
const styles=fs.readFileSync('modules.css','utf8');
const requestId='c1dc13464f0247c5a727204ebf28f8cc';
const ticket='PRIVATE_TICKET_SENTINEL';
const ids=['googleWriterApplyCompact','googleWriterApplyCompactStatus','googleWriterApplyCompactHttp',
  'googleWriterApplyDetailsOpen','googleWriterApplyDetailsDialog','googleWriterApplyDetailsBody',
  'googleWriterApplyCopy','googleWriterApplyCopyStatus','googleWriterApplyDiagnosticRefresh'];
function harness(applyResult,storage=new Map()){
  const calls=[],nodes={},clipboard={text:''};
  const element=()=>({hidden:true,open:false,textContent:'',value:'',children:[],dataset:{},style:{},listeners:{},
    appendChild(node){this.children.push(node);this.textContent=this.children.map(x=>x.textContent).join('\n')},
    append(...items){this.children.push(...items)},replaceChildren(){this.children=[];this.textContent=''},
    addEventListener(type,handler){this.listeners[type]=handler},setAttribute(){},select(){},remove(){},
    showModal(){this.open=true},click(){return this.listeners.click?.()}});
  ids.forEach(id=>nodes[id]=element());
  const app={document:{getElementById:id=>nodes[id]||null,createElement:()=>element(),body:element(),execCommand:()=>true},
    navigator:{clipboard:{writeText:async text=>{clipboard.text=text}}},
    sessionStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value)},
    request:async(url,options={})=>{
      calls.push({url,method:options.method||'GET',body:options.body||''});
      if(url.endsWith('/append-continuation-preview'))return{status:'PREVIEW_READY',request_id:requestId,ticket};
      if(url.endsWith('/google-writer/apply')){
        if(applyResult instanceof Error)throw applyResult;
        return applyResult;
      }
      if(url===`/api/google-writer/continuation-status/${requestId}`)return{status:'outcome_unknown',confirmed_append:25,
        attempted_chunk:1,checkpoint:{present:true,next_chunk:1},receipts:{verified_count:1},read_only:true,
        digest:'D'.repeat(43),ticket:'SHOULD_NOT_ESCAPE'};
      throw Error('Unexpected mocked API call');
    }};
  vm.createContext(app);vm.runInContext(source,app,{filename:'google_writer_apply_result.js'});
  return {app,calls,nodes,storage,clipboard};
}
async function invokeApply(h,applyPayload={ticket,confirmed:true}){
  await h.app.request('/api/admin/google-writer/append-continuation-preview',{method:'POST'});
  try{await h.app.request('/api/google-writer/apply',{method:'POST',body:JSON.stringify(applyPayload)});}catch{}
  await new Promise(resolve=>setTimeout(resolve,0));
}
function detailText(h){return h.nodes.googleWriterApplyDetailsBody.children.map(item=>
  item.children.map(child=>child.textContent).join(': ')).join('\n');}

test('HTTP 409 with started:false is BLOCKED, preserves the exact code, and never retries Apply',async()=>{
  const error=Object.assign(new Error('raw private error'),{httpStatus:409,code:'CONTINUATION_PREVIEW_STALE',
    status:'CONTINUATION_PREVIEW_STALE',started:false,ticket,digest:'D'.repeat(43)});
  const h=harness(error);await invokeApply(h);
  assert.equal(h.nodes.googleWriterApplyCompact.hidden,false);
  assert.equal(h.nodes.googleWriterApplyCompactStatus.textContent,'BLOCKED');
  assert.equal(h.nodes.googleWriterApplyCompactHttp.textContent,'HTTP 409');
  await h.nodes.googleWriterApplyDetailsOpen.click();
  assert.equal(h.nodes.googleWriterApplyDetailsDialog.open,true);
  const text=detailText(h);
  assert.match(text,/HTTP-статус: 409/);assert.match(text,/Код відповіді: CONTINUATION_PREVIEW_STALE/);
  assert.match(text,/Новий запуск розпочато: ні/);
  await h.nodes.googleWriterApplyCopy.click();
  assert.match(h.clipboard.text,/HTTP-статус: 409/);
  assert.match(h.clipboard.text,/Код відповіді: CONTINUATION_PREVIEW_STALE/);
  assert.match(h.clipboard.text,/Новий запуск розпочато: ні/);
  assert.doesNotMatch(h.clipboard.text,/PRIVATE_TICKET_SENTINEL|D{43}|raw private error/);
  assert.equal(h.calls.filter(call=>call.url.endsWith('/google-writer/apply')).length,1);
  assert.equal(h.calls.filter(call=>call.url.startsWith('/api/google-writer/continuation-status/')).length,1);
  assert.doesNotMatch(text,/PRIVATE_TICKET_SENTINEL|D{43}|raw private error|SHOULD_NOT_ESCAPE/);
});

test('unknown HTTP 409 is STOP and exposes only verified journal fields',async()=>{
  const error=Object.assign(new Error('private backend text'),{httpStatus:409,code:'APPLY_OUTCOME_UNCONFIRMED',ticket});
  const h=harness(error);await invokeApply(h);await h.nodes.googleWriterApplyDetailsOpen.click();
  const text=detailText(h);
  assert.equal(h.nodes.googleWriterApplyCompactStatus.textContent,'STOP');
  assert.match(text,/Стан continuation run: outcome_unknown/);
  assert.match(text,/Підтверджені APPEND: 25/);assert.match(text,/attempted_chunk: 1/);
  assert.match(text,/Checkpoint: є; наступний chunk 1/);assert.match(text,/Receipts: 1/);
  assert.match(text,/Новий запуск розпочато: невідомо/);
  assert.equal(h.calls.filter(call=>call.url.endsWith('/google-writer/apply')).length,1);
  assert.doesNotMatch(text,/PRIVATE_TICKET_SENTINEL|private backend text|SHOULD_NOT_ESCAPE|D{43}/);
});

test('confirmed start shows SUCCESS and copy button copies only safe fields',async()=>{
  const h=harness({started:true,request_id:requestId});await invokeApply(h);await h.nodes.googleWriterApplyDetailsOpen.click();
  assert.equal(h.nodes.googleWriterApplyCompactStatus.textContent,'SUCCESS');
  assert.equal(h.nodes.googleWriterApplyCompactHttp.textContent,'HTTP 202');
  await h.nodes.googleWriterApplyCopy.click();
  assert.match(h.clipboard.text,/HTTP-статус: 202/);
  assert.match(h.clipboard.text,/Новий запуск розпочато: так/);
  assert.match(h.clipboard.text,/Підтверджені APPEND: 25/);
  assert.match(h.clipboard.text,/Receipts: 1/);
  assert.doesNotMatch(h.clipboard.text,/PRIVATE_TICKET_SENTINEL|SHOULD_NOT_ESCAPE|D{43}|requestId/);
  assert.match(h.nodes.googleWriterApplyCopyStatus.textContent,/скопійовано/);
});

test('safe result survives a tab reload and does not persist a ticket or digest',async()=>{
  const h=harness({started:true,request_id:requestId});await invokeApply(h);
  const saved=[...h.storage.values()].join('');
  assert.doesNotMatch(saved,/PRIVATE_TICKET_SENTINEL|SHOULD_NOT_ESCAPE|D{43}/);
  const restored=harness({started:false},h.storage);await new Promise(resolve=>setTimeout(resolve,0));
  assert.equal(restored.nodes.googleWriterApplyCompact.hidden,false);
  assert.equal(restored.nodes.googleWriterApplyCompactStatus.textContent,'SUCCESS');
  assert.equal(restored.calls.filter(call=>call.url.endsWith('/google-writer/apply')).length,0);
  assert.equal(restored.calls.filter(call=>call.url.startsWith('/api/google-writer/continuation-status/')).length,1);
});

test('status sits in desktop column four and details dialog wraps responsively',()=>{
  assert.match(index,/id="googleWriterApplyCompact" class="google-writer-apply-compact/);
  assert.doesNotMatch(index,/googleWriterApplyResult"[^>]*position:\s*fixed/);
  assert.match(index,/id="googleWriterApplyDetailsDialog" class="google-writer-apply-dialog/);
  assert.match(styles,/grid-template-columns:minmax\(220px,1\.1fr\) minmax\(0,1fr\) minmax\(0,1fr\) minmax\(170px,\.9fr\)/);
  assert.match(styles,/grid-column:4/);
  assert.match(styles,/overflow-wrap:anywhere;word-break:break-word/);
  assert.match(styles,/@media\(max-width:700px\)[\s\S]*?\.google-writer-apply-details\{grid-template-columns:minmax\(0,1fr\)/);
  assert.match(index,/Копіювати діагностику/);
});
