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
