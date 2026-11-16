'use strict';

const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const source=fs.readFileSync('google_writer_ui.js','utf8');
const sourceRequestId='71487a74779f4445a186a8dbe6252fbc';
const continuationId='c1dc13464f0247c5a727204ebf28f8cc';
const planDigest='P'.repeat(43),detailsDigest='D'.repeat(43);

function validPrepared(overrides={}){
  return {status:'PREVIEW_READY',source_request_id:sourceRequestId,request_id:continuationId,
    counts:{append:251,update:0,conflict:0,error:0},
    excluded_counts:{update:2,conflict:2,error:0},
    continuation:{confirmed:25,excluded:25,missing:251},
    plan_digest:planDigest,details_digest:detailsDigest,ticket:'PRIVATE_TICKET_SENTINEL',
    preview_created:true,writer_started:false,google_writes:0,script_properties_writes:0,
    ...overrides};
}
function validSaved(overrides={}){
  return {details_digest:detailsDigest,details:{plan_digest:planDigest,
    counts:{append:251,update:0,conflict:0,error:0},
    appends:Array.from({length:251},()=>({operation:'APPEND'})),updates:[],conflicts:[],errors:[],
    append_continuation:{version:2,source_request_id:sourceRequestId,
      source_excluded_counts:{update:2,conflict:2,error:0},
      excluded_updates:[{},{}],excluded_conflicts:[{},{}]}},...overrides};
}
async function runPreview(prepared,saved=validSaved()){
  const calls=[],messages=[];
  const app={API:'/api',document:{getElementById:()=>null},Intl,JSON,Number,String,Error,Promise,
    request:async(url,options={})=>{
      calls.push({url,method:options.method||'GET'});
      return url.endsWith('/append-continuation-preview')?prepared:saved;
    },
    toast:(message,type)=>messages.push({message,type}),
    loadGoogleWriterJob:async()=>null};
  vm.createContext(app);
  vm.runInContext(source,app,{filename:'google_writer_ui.js'});
  vm.runInContext(`googleWriterJobState={can_diagnose_append:true,runs:[{
    request_id:${JSON.stringify(sourceRequestId)},status:'closed_unknown',
    result:{plan_scope:'APPEND_ONLY',attempted_chunk:0}}]};`,app);
  vm.runInContext('confirmGoogleWriterPreview=async()=>false;',app);
  await vm.runInContext(`prepareGoogleWriterAppendContinuation(${JSON.stringify(sourceRequestId)})`,app);
  return {calls,messages};
}

test('accepts exact numeric counts regardless of object key order',async()=>{
  const prepared=validPrepared({counts:{error:0,conflict:0,update:0,append:251}});
  const saved=validSaved({details:{...validSaved().details,
    counts:{conflict:0,error:0,append:251,update:0}}});
  const {calls,messages}=await runPreview(prepared,saved);
  assert.equal(calls.filter(x=>x.url==='/api/admin/google-writer/append-continuation-preview').length,1);
  assert.equal(calls.filter(x=>x.url===`/api/google-writer/preview-details/${continuationId}?plan_digest=${planDigest}`).length,1);
  assert.deepEqual(messages,[]);
});
test('rejects wrong numeric counts with a field-specific safe code',async()=>{
  const prepared=validPrepared({counts:{append:250,update:0,conflict:0,error:0}});
  const {calls,messages}=await runPreview(prepared);
  assert.equal(calls.filter(x=>x.url==='/api/admin/google-writer/append-continuation-preview').length,1);
  assert.equal(calls.some(x=>x.url.includes('/google-writer/preview-details/')),false);
  assert.match(messages[0].message,/COUNT_APPEND_MISMATCH/);
  assert.doesNotMatch(messages[0].message,/PRIVATE_TICKET_SENTINEL|P{43}|D{43}/);
});

test('rejects string counts instead of coercing them to numbers',async()=>{
  const prepared=validPrepared({counts:{append:251,update:'0',conflict:0,error:0}});
  const {messages}=await runPreview(prepared);
  assert.match(messages[0].message,/COUNT_UPDATE_MISMATCH/);
});

test('rejects missing count fields with a field-specific code',async()=>{
  const counts={append:251,update:0,error:0};
  const prepared=validPrepared({counts});
  const {calls,messages}=await runPreview(prepared);
  assert.equal(calls.filter(x=>x.url==='/api/admin/google-writer/append-continuation-preview').length,1);
  assert.equal(calls.some(x=>x.url.includes('/google-writer/preview-details/')),false);
  assert.match(messages[0].message,/COUNT_CONFLICT_MISMATCH/);
});

test('rejects malformed request IDs without exposing ticket or digests',async()=>{
  const prepared=validPrepared({request_id:'not-a-request-id'});
  const {calls,messages}=await runPreview(prepared);
  assert.equal(calls.filter(x=>x.url==='/api/admin/google-writer/append-continuation-preview').length,1);
  assert.equal(calls.some(x=>x.url.includes('/google-writer/preview-details/')),false);
  assert.match(messages[0].message,/REQUEST_ID_INVALID/);
  assert.doesNotMatch(messages[0].message,/PRIVATE_TICKET_SENTINEL|P{43}|D{43}/);
});

test('retains status, source binding, no-write and exclusion checks',async t=>{
  const cases=[
    ['status','PREVIEW_STATUS_NOT_READY',{status:'BLOCKED'}],
    ['source request','SOURCE_REQUEST_ID_MISMATCH',{source_request_id:'f'.repeat(32)}],
    ['writer start','WRITER_STARTED',{writer_started:true}],
    ['Google write count','GOOGLE_WRITES_NOT_ZERO',{google_writes:1}],
    ['Script Properties write count','SCRIPT_PROPERTIES_WRITES_NOT_ZERO',{script_properties_writes:1}],
    ['excluded operation counts','EXCLUDED_COUNTS_MISMATCH',{excluded_counts:{update:1,conflict:2,error:0}}],
  ];
  for(const [label,reason,overrides] of cases){
    await t.test(label,async()=>{
      const {calls,messages}=await runPreview(validPrepared(overrides));
      assert.match(messages[0].message,new RegExp(reason));
      assert.equal(calls.some(x=>x.url.includes('/google-writer/preview-details/')),false);
      assert.doesNotMatch(messages[0].message,/PRIVATE_TICKET_SENTINEL|P{43}|D{43}/);
    });
  }
});

test('shows a pending label during continuation Preview request and restores it afterward',async()=>{
  let releasePreview;
  const calls=[],button={disabled:false,textContent:'Перевірити Preview 251 відсутнього APPEND',dataset:{requestId:sourceRequestId},
    setAttribute(){},removeAttribute(){}};
  const app={API:'/api',document:{getElementById:()=>null,querySelectorAll:()=>[button]},Intl,JSON,Number,String,Error,Promise,
    request:(url,options={})=>{
      calls.push({url,method:options.method||'GET'});
      if(url.endsWith('/append-continuation-preview'))return new Promise(resolve=>{releasePreview=()=>resolve(validPrepared());});
      if(url.includes('/google-writer/preview-details/'))return Promise.resolve(validSaved());
      throw Error('Unexpected request');
    },toast:()=>{},loadGoogleWriterJob:async()=>null};
  vm.createContext(app);vm.runInContext(source,app,{filename:'google_writer_ui.js'});
  vm.runInContext(`googleWriterJobState={can_diagnose_append:true,runs:[{request_id:${JSON.stringify(sourceRequestId)},
    status:'closed_unknown',result:{plan_scope:'APPEND_ONLY',attempted_chunk:0}}]};
    confirmGoogleWriterPreview=async()=>false;`,app);
  const pending=app.prepareGoogleWriterAppendContinuation(sourceRequestId,button);
  assert.equal(button.disabled,true);
  assert.equal(button.textContent,'Виконується запит…');
  assert.equal(button.getAttribute?.('aria-busy'),undefined);
  releasePreview();await pending;
  assert.equal(button.disabled,false);
  assert.equal(button.textContent,'Перевірити Preview 251 відсутнього APPEND');
  assert.equal(calls.filter(call=>call.method==='POST').length,1);
});

test('read-only status refresh shows progress, success time, and a safe error message',async()=>{
  const tick=()=>new Promise(resolve=>setImmediate(resolve));
  const refreshButton={disabled:false,textContent:'Оновити стан',onclick:null};
  const stateNode={textContent:''};
  const card={id:'googleWriterJobCard',className:'scheduler-job',innerHTML:'',
    querySelector(selector){return selector==='.google-writer-status-refresh'?refreshButton:
      selector==='.google-writer-status-refresh-state'?stateNode:null;},
    querySelectorAll(selector){return selector==='.google-writer-status-refresh'?[refreshButton]:[];}};
  const root={append(){}};let calls=0,releaseRefresh;
  const response={runs:[],can_execute:false,channel_ready:true,blocked:false,resume_available:false,
    automation_blocked:true,configured_enabled:false,can_manage:false,schedule:'',last_status:'none',
    last_finished_at:null,next_run:null,hour:0,minute:0};
  const app={API:'/api',document:{getElementById:id=>id==='schedulerJobs'?root:id==='googleWriterJobCard'?card:null,
    createElement:()=>card},Intl,JSON,Number,String,Error,Promise,
    displayDate:value=>`date:${value}`,esc:value=>String(value),
    request:async()=>{
      calls++;
      if(calls<=2)return response;
      if(calls===3)return new Promise((resolve,reject)=>{releaseRefresh={resolve:()=>resolve(response),reject};});
      throw Object.assign(new Error('private backend response'),{httpStatus:503});
    }};
  vm.createContext(app);vm.runInContext(source,app,{filename:'google_writer_ui.js'});
  await tick();await app.loadGoogleWriterJob();
  assert.match(card.innerHTML,/Остання успішна перевірка:/);
  refreshButton.onclick=()=>app.refreshGoogleWriterStatus(refreshButton);
  const refreshing=refreshButton.onclick();
  const duplicateStatusRead=app.loadGoogleWriterJob();
  assert.equal(refreshButton.disabled,true);
  assert.equal(refreshButton.textContent,'Виконується запит…');
  assert.equal(calls,3,'manual refresh joins an in-flight status request instead of starting a parallel GET');
  releaseRefresh.resolve();await refreshing;
  await duplicateStatusRead;
  assert.equal(refreshButton.disabled,false);
  assert.match(stateNode.textContent,/Остання успішна перевірка:/);
  releaseRefresh=null;
  app.request=async()=>{const error=new Error('private backend response');error.httpStatus=503;throw error;};
  await app.loadGoogleWriterJob();
  assert.match(card.innerHTML,/Не вдалося оновити стан Google Writer \(HTTP 503\)/);
  assert.doesNotMatch(card.innerHTML,/private backend response/);
  assert.equal(calls>=3,true);
});

test('APPEND confirmation stays visible, busy, and disabled while the Apply request is pending',async()=>{
  const nodes={},makeButton=()=>({disabled:false,hidden:false,textContent:'',listeners:{},attrs:{},
    addEventListener(type,handler){this.listeners[type]=handler},removeEventListener(type){delete this.listeners[type]},
    setAttribute(key,value){this.attrs[key]=value},removeAttribute(key){delete this.attrs[key]},click(){return this.listeners.click?.()}});
  const dialog={open:false,returnValue:'',listeners:{},showModal(){this.open=true},close(value){this.returnValue=value;this.open=false;
    this.listeners.close?.forEach?.(fn=>fn());},addEventListener(type,handler){(this.listeners[type]??=[]).push(handler)},
    removeEventListener(type,handler){this.listeners[type]=(this.listeners[type]||[]).filter(item=>item!==handler)}};
  for(const id of ['googleWriterPreviewAppend','googleWriterPreviewUpdate','googleWriterPreviewConflict','googleWriterPreviewNotice'])
    nodes[id]={textContent:'',hidden:false};
  nodes.googleWriterPreviewDialog=dialog;nodes.googleWriterPreviewApply=makeButton();
  nodes.googleWriterPreviewAppendOnly=makeButton();nodes.googleWriterPreviewDetails={innerHTML:''};
  const app={document:{getElementById:id=>nodes[id]||null},Intl,JSON,Number,String,Error,Promise,esc:value=>String(value)};
  vm.createContext(app);vm.runInContext(source,app,{filename:'google_writer_ui.js'});
  const pending=app.confirmGoogleWriterPreview({plan_digest:'x',counts:{append:251,update:0,conflict:0}},
    {appends:[],updates:[],conflicts:[],errors:[]},{continuation:true,keepOpenDuringApply:true});
  nodes.googleWriterPreviewAppendOnly.textContent='Підтвердити APPEND 251';
  nodes.googleWriterPreviewAppendOnly.click();
  const choice=await pending;
  assert.equal(choice.scope,'APPEND_ONLY');assert.equal(choice.keepOpen,true);
  assert.equal(dialog.open,true);
  assert.equal(nodes.googleWriterPreviewAppendOnly.disabled,true);
  assert.equal(nodes.googleWriterPreviewAppendOnly.textContent,'Виконується запит…');
  assert.equal(nodes.googleWriterPreviewAppendOnly.attrs['aria-busy'],'true');
});
