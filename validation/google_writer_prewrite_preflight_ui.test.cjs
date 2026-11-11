'use strict';

const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const source=fs.readFileSync('google_writer_ui.js','utf8');

async function runPreflight(result,run={request_id:'b'.repeat(32),status:'failed_safe',prewrite_close_eligible:true}){
  const calls=[],messages=[];
  const context={API:'/api',
    document:{getElementById:()=>null},
    request:async(url,options)=>{
      if(url==='/api/google-writer/status')return {runs:[],can_manage:false};
      calls.push({url,options});return result;
    },
    toast:(message,kind)=>messages.push({message,kind}),
    loadGoogleWriterJob:async()=>null,
    Intl,JSON,Number,String,Error,Promise};
  vm.createContext(context);
  vm.runInContext(source,context,{filename:'google_writer_ui.js'});
  await Promise.resolve();
  vm.runInContext(`googleWriterJobState={can_preflight_close_prewrite:true,runs:[${JSON.stringify(run)}]};`,context);
  vm.runInContext('loadGoogleWriterJob=async()=>null;',context);
  await vm.runInContext(`preflightGoogleWriterPrewriteClose(${JSON.stringify(run.request_id)})`,context);
  return {calls,messages};
}

test('READY preflight UI calls only its read-only endpoint and labels the result informational',async()=>{
  const {calls,messages}=await runPreflight({status:'READY',read_only:true,sqlite_writes:0,sheets_writes:0,
    properties_writes:0,request_id_matches:true,plan_binding:'PASS',chunk_binding:'PASS',manifest_binding:'PASS',
    target_code_matches:0,run_marker_matches:0,write_ahead_bytes:9001,checkpoint_max_bytes:8000});
  assert.equal(calls.length,1);
  assert.equal(calls[0].url,'/api/admin/google-writer/prewrite-close-preflight');
  assert.equal(calls[0].options.method,'POST');
  assert.deepEqual(JSON.parse(calls[0].options.body),{request_id:'b'.repeat(32)});
  assert.match(messages[0].message,/READY/);
  assert.match(messages[0].message,/під час закриття все буде перевірено повторно/);
});

test('BLOCKED preflight UI preserves the HOLD and reports a safe reason',async()=>{
  const {calls,messages}=await runPreflight({status:'BLOCKED',read_only:true,sqlite_writes:0,sheets_writes:0,
    properties_writes:0,reason_codes:['SHEET_READ_INCOMPLETE']});
  assert.equal(calls.length,1);
  assert.match(messages[0].message,/BLOCKED/);
  assert.match(messages[0].message,/читання аркушів неповне/);
  assert.match(messages[0].message,/HOLD збережено/);
});

test('BLOCKED preflight UI surfaces only the allowlisted diagnostic code',async()=>{
  const {messages}=await runPreflight({status:'BLOCKED',read_only:true,sqlite_writes:0,sheets_writes:0,
    properties_writes:0,reason_codes:['APPS_SCRIPT_CHECK_UNAVAILABLE'],diagnostic_code:'EXECUTION_API_HTTP_403'});
  assert.match(messages[0].message,/EXECUTION_API_HTTP_403/);
  const unsafe=await runPreflight({status:'BLOCKED',read_only:true,sqlite_writes:0,sheets_writes:0,
    properties_writes:0,reason_codes:['APPS_SCRIPT_CHECK_UNAVAILABLE'],diagnostic_code:'secret-token-value'});
  assert.doesNotMatch(unsafe.messages[0].message,/secret-token-value/);
});

test('incomplete or unsafe preflight response is rejected without a close call',async()=>{
  const {calls,messages}=await runPreflight({status:'READY',read_only:true,sqlite_writes:0,sheets_writes:1,
    properties_writes:0,request_id_matches:true,plan_binding:'PASS',chunk_binding:'PASS',manifest_binding:'PASS',
    target_code_matches:0,run_marker_matches:0});
  assert.equal(calls.length,1);
  assert.equal(calls[0].url,'/api/admin/google-writer/prewrite-close-preflight');
  assert.match(messages[0].message,/BLOCKED/);
  assert.match(messages[0].message,/read-only результат не підтверджений/i);
});
