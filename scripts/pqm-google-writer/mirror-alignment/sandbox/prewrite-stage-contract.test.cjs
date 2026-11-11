const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const sandboxDir=__dirname;
const sources=[
  ['PqmSandboxAppendApply.gs',sandboxDir],['PqmSandboxFullApply.gs',sandboxDir],
  ['PqmExecutionCheckpoint.gs',path.join(__dirname,'../shared')],
  ['PqmSandboxControlledApply.gs',sandboxDir],['PqmSandboxExecution.gs',sandboxDir],
  ['PqmSandboxAllScopeExecution20261109.gs',sandboxDir],
  ['PqmSandboxPreviewDependencies.gs',sandboxDir],['PqmVerificationDatetime.gs',sandboxDir],
  ['PqmSandboxPreview.gs',sandboxDir]
].map(([name,dir])=>fs.readFileSync(path.join(dir,name),'utf8')).join('\n');

function digest(value) {
  return crypto.createHash('sha256').update(value,'utf8').digest('base64url');
}

function legacyRequest() {
  const requestId='b11433e8efb84b4492bf2df7c7c25908';
  const rows=Array.from({length:25},(_,i)=>({tab:i<21?'ФОП':'ЮО',row:i+2,
    code:String(i+1).padStart(10,'0'),formulaA:'='+('x'.repeat(220))}));
  const identities=rows.map(({tab,code})=>({tab,code}));
  const projection=rows.map(({code,formulaA,row,tab})=>({code,formulaA,row,tab}));
  return {environment:'SANDBOX',scriptId:'s'.repeat(57),spreadsheetId:'h'.repeat(44),
    contract:'pqm-mirror-datetime-v1',action:'prewrite_close_preflight',requestId,
    actor:'sandbox-admin',trigger:'manual',issuedAt:Math.floor(Date.now()/1000),
    expiresAt:Math.floor(Date.now()/1000)+300,expectedDigest:digest('preview'),planScope:'APPEND_ONLY',
    chunkIndex:0,chunkId:'c'.repeat(32),chunkDigest:digest('chunk'),planId:requestId,
    prewriteStage:'LEGACY_V1_WRITEAHEAD_LIMIT_PROOF_V1',
    targetIdentityDigest:digest(JSON.stringify(rows.map(item=>[item.tab,item.code]))),
    targetIdentities:identities,legacyManifestRows:rows,
    legacyManifestProjectionDigest:digest(JSON.stringify(projection))};
}

function dispatcherFixture() {
  const request=legacyRequest(),secret='S'.repeat(40),uncertain=request.requestId;
  const runRecord={state:'ready',planScope:'APPEND_ONLY',chunkJournalVersion:1,
    digest:request.expectedDigest,nextChunk:0,inflight:null,inflightManifest:null,uncertainChunk:null,
    steps:[],aggregate:{append:0,update:0,batches:0},result:null};
  const props=new Map([['PQM_EXECUTION_SHARED_SECRET',secret],['PQM_EXECUTION_UNCERTAIN',uncertain],
    ['PQM_EXECUTION_RUN_'+uncertain,JSON.stringify(runRecord)]]);
  const sheetIds=[];let propertyWrites=0,sheetWrites=0;
  const scriptId=request.scriptId,spreadsheetId=request.spreadsheetId;
  const context={Date,Map,Set,JSON,Math,Object,Array,String,Number,RegExp,Error,
    PQM_MIRROR_ENV:{environment:'SANDBOX',scriptId,spreadsheetId},PQM_GOOGLE_TABS:['ФОП','ЮО'],
    PQM_EXECUTION_CONTEXT_:null,ScriptApp:{getScriptId:()=>scriptId},
    Utilities:{Charset:{UTF_8:'UTF_8'},DigestAlgorithm:{SHA_256:'SHA_256'},
      computeDigest:(_algorithm,value)=>crypto.createHash('sha256').update(value,'utf8').digest(),
      computeHmacSha256Signature:(value,key)=>crypto.createHmac('sha256',key).update(value,'utf8').digest(),
      base64EncodeWebSafe:value=>Buffer.from(value).toString('base64url'),
      base64DecodeWebSafe:value=>[...Buffer.from(value,'base64url')],
      newBlob:value=>({getBytes:()=>[...Buffer.from(value,'utf8')]})},
    PropertiesService:{getScriptProperties:()=>({getProperty:key=>props.get(key)??null,
      getProperties:()=>Object.fromEntries(props),setProperty:(key,value)=>{propertyWrites++;props.set(key,value);},
      deleteProperty:key=>{propertyWrites++;props.delete(key);}})},
    SpreadsheetApp:{},LockService:{getScriptLock:()=>({tryLock:()=>true,releaseLock:()=>{}})},
    Sheets:{Spreadsheets:{get:(id)=>{sheetIds.push(id);return {sheets:['ФОП','ЮО'].map((title,index)=>({
        properties:{title,sheetId:index+1,gridProperties:{rowCount:2,columnCount:19}}}))};},
      Values:{batchGet:(id,{ranges})=>{sheetIds.push(id);return {valueRanges:ranges.map(()=>({values:[]}))};},
        batchUpdate:()=>{sheetWrites++;throw new Error('preflight must never write Sheets');}}}}
  };
  vm.createContext(context);vm.runInContext(sources,context);
  const payload=JSON.stringify(request);
  const signature=crypto.createHmac('sha256',secret).update(payload,'utf8').digest('base64url');
  return {context,request,props,propertyWrites:()=>propertyWrites,sheetWrites:()=>sheetWrites,sheetIds,
    envelope:{payload,signature}};
}

test('Apps Script v21 dispatcher returns the concrete legacy proof stage read-only',()=>{
  const f=dispatcherFixture();
  const before=JSON.stringify(Object.fromEntries(f.props));
  const result=f.context.pqmSandboxAllScopeExecution20261109(f.envelope);
  assert.equal(result.status,'READY');
  assert.equal(result.prewriteStage,'append_inflight_save');
  assert.equal(result.proofType,'LEGACY_V1_WRITEAHEAD_OVERSIZE');
  assert.ok(result.writeAheadBytes>8000);
  assert.equal(result.checkpointMaxBytes,8000);
  assert.equal(result.legacyManifestProjectionDigest,f.request.legacyManifestProjectionDigest);
  assert.equal(result.targetIdentityDigest,f.request.targetIdentityDigest);
  assert.equal(result.spreadsheetId,f.request.spreadsheetId);
  assert.ok(f.sheetIds.length>0);assert.ok(f.sheetIds.every(id=>id===f.request.spreadsheetId));
  assert.equal(f.propertyWrites(),0);assert.equal(f.sheetWrites(),0);
  assert.equal(JSON.stringify(Object.fromEntries(f.props)),before);
});

test('Apps Script v21 dispatcher rejects a bad signature and malformed binding before reads',()=>{
  const f=dispatcherFixture();
  assert.throws(()=>f.context.pqmSandboxAllScopeExecution20261109({...f.envelope,signature:'bad'}),
    /execution authorization rejected/);
  const invalid={...f.request,targetIdentityDigest:digest('wrong')};
  const payload=JSON.stringify(invalid);
  const signature=crypto.createHmac('sha256','S'.repeat(40)).update(payload,'utf8').digest('base64url');
  assert.throws(()=>f.context.pqmSandboxAllScopeExecution20261109({payload,signature}),
    /prewrite target identity digest mismatch/);
  assert.equal(f.sheetIds.length,0);assert.equal(f.propertyWrites(),0);assert.equal(f.sheetWrites(),0);
});

test('25-row UTF-16 envelope is scoped above 8192 and other actions retain the old cap',()=>{
  const f=dispatcherFixture();
  assert.equal(f.envelope.payload.length,8649);
  assert.ok(f.envelope.payload.length>8192 && f.envelope.payload.length<=32768);
  const other={...f.request,action:'apply'};
  const payload=JSON.stringify(other);
  const signature=crypto.createHmac('sha256','S'.repeat(40)).update(payload,'utf8').digest('base64url');
  assert.ok(payload.length>8192);
  assert.throws(()=>f.context.pqmSandboxAllScopeExecution20261109({payload,signature}),
    /oversized execution payload is restricted to read-only preflight/);
  assert.throws(()=>f.context.pqmSandboxAllScopeExecution20261109({payload:'x'.repeat(32769),signature:'invalid'}),
    /invalid execution envelope/);
  assert.equal(f.sheetIds.length,0);assert.equal(f.propertyWrites(),0);assert.equal(f.sheetWrites(),0);
});
