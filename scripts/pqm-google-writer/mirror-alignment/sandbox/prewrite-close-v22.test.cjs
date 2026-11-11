const assert=require('node:assert/strict');
const crypto=require('node:crypto');
const fs=require('node:fs');
const path=require('node:path');
const test=require('node:test');
const vm=require('node:vm');

const dir=__dirname;
const sources=[
  ['PqmSandboxAppendApply.gs',dir],['PqmSandboxFullApply.gs',dir],
  ['PqmExecutionCheckpoint.gs',path.join(dir,'../shared')],
  ['PqmSandboxControlledApply.gs',dir],['PqmSandboxExecution.gs',dir],
  ['PqmSandboxAllScopeExecution20261109.gs',dir],
  ['PqmSandboxPreviewDependencies.gs',dir],['PqmVerificationDatetime.gs',dir],
  ['PqmSandboxPreview.gs',dir]
].map(([name,root])=>fs.readFileSync(path.join(root,name),'utf8')).join('\n');

const REQUEST_ID='b11433e8efb84b4492bf2df7c7c25908';
const SECRET='mock-v22-shared-secret-'.padEnd(48,'x');
const SCRIPT_ID='s'.repeat(57);
const SHEET_ID='h'.repeat(44);
const digest=value=>crypto.createHash('sha256').update(value,'utf8').digest('base64url');

function fixture({formulaLength=220,requestOverride=null,secret=SECRET,initialProperties=null}={}) {
  const now=Math.floor(Date.now()/1000);
  const rows=Array.from({length:25},(_,i)=>({tab:i<21?'ФОП':'ЮО',row:i+2,
    code:String(i+1).padStart(10,'0'),formulaA:'='+('x'.repeat(formulaLength))}));
  const projection=rows.map(({code,formulaA,row,tab})=>({code,formulaA,row,tab}));
  const identities=rows.map(({tab,code})=>({tab,code}));
  const request=requestOverride||{environment:'SANDBOX',scriptId:SCRIPT_ID,spreadsheetId:SHEET_ID,
    contract:'pqm-mirror-datetime-v1',action:'close_prewrite_failure',requestId:REQUEST_ID,
    actor:'sandbox-admin',trigger:'manual',issuedAt:now,expiresAt:now+300,
    expectedDigest:digest('reviewed APPEND_ONLY preview'),planScope:'APPEND_ONLY',
    closeId:'c'.repeat(32),closeEvidenceDigest:digest('close evidence'),
    reasonDigest:digest('admin reason'),chunkIndex:0,prewriteStage:'LEGACY_V1_WRITEAHEAD_LIMIT_PROOF_V1',
    targetIdentityDigest:digest(JSON.stringify(rows.map(({tab,code})=>[tab,code]))),
    targetIdentities:identities,chunkId:'d'.repeat(32),chunkDigest:digest('chunk'),
    planId:REQUEST_ID,legacyManifestRows:rows,
    legacyManifestProjectionDigest:digest(JSON.stringify(projection))};
  const scriptId=request.scriptId||SCRIPT_ID;
  const sheetId=request.spreadsheetId||SHEET_ID;
  const props=initialProperties?new Map(Object.entries(initialProperties)):
    new Map([['PQM_EXECUTION_SHARED_SECRET',secret],['PQM_EXECUTION_UNCERTAIN',REQUEST_ID],
    ['PQM_EXECUTION_RUN_'+REQUEST_ID,JSON.stringify({state:'ready',planScope:'APPEND_ONLY',
      chunkJournalVersion:1,digest:request.expectedDigest,nextChunk:0,inflight:null,
      inflightManifest:null,uncertainChunk:null,steps:[],aggregate:{append:0,update:0,batches:0},result:null})]]);
  const calls={sheetReads:0,propertyWrites:0,sheetWrites:0};
  const context={Date,Map,Set,JSON,Math,Object,Array,String,Number,RegExp,Error,
    PQM_MIRROR_ENV:{environment:'SANDBOX',scriptId,spreadsheetId:sheetId},
    PQM_GOOGLE_TABS:['ФОП','ЮО'],PQM_EXECUTION_CONTEXT_:null,
    ScriptApp:{getScriptId:()=>scriptId},SpreadsheetApp:{},
    LockService:{getScriptLock:()=>({tryLock:()=>true,releaseLock:()=>{}})},
    Utilities:{Charset:{UTF_8:'UTF_8'},DigestAlgorithm:{SHA_256:'SHA_256'},
      computeDigest:(_a,value)=>crypto.createHash('sha256').update(value,'utf8').digest(),
      computeHmacSha256Signature:(value,key)=>crypto.createHmac('sha256',key).update(value,'utf8').digest(),
      base64EncodeWebSafe:value=>Buffer.from(value).toString('base64url'),
      base64DecodeWebSafe:value=>[...Buffer.from(value,'base64url')],
      newBlob:value=>({getBytes:()=>[...Buffer.from(value,'utf8')]})},
    PropertiesService:{getScriptProperties:()=>({getProperty:key=>props.get(key)??null,
      getProperties:()=>Object.fromEntries(props),setProperty:(key,value)=>{calls.propertyWrites++;props.set(key,value);},
      deleteProperty:key=>{calls.propertyWrites++;props.delete(key);}})},
    Sheets:{Spreadsheets:{get:id=>{calls.sheetReads++;assert.equal(id,sheetId);return {sheets:['ФОП','ЮО'].map((title,i)=>({
      properties:{title,sheetId:i+1,gridProperties:{rowCount:2,columnCount:19}}}))};},
      Values:{batchGet:(id,{ranges})=>{calls.sheetReads++;assert.equal(id,sheetId);
        return {valueRanges:ranges.map(()=>({values:[]}))};},
        batchUpdate:()=>{calls.sheetWrites++;throw new Error('closure must not write Sheets');}}}}
  };
  vm.createContext(context);vm.runInContext(sources,context);
  const raw=JSON.stringify(request);
  const envelope={payload:raw,signature:crypto.createHmac('sha256',secret).update(raw,'utf8').digest('base64url')};
  return {context,request,props,calls,envelope};
}

function signed(request) {
  const payload=JSON.stringify(request);
  return {payload,signature:crypto.createHmac('sha256',SECRET).update(payload,'utf8').digest('base64url')};
}

if (process.argv.includes('--bridge')) {
  let input='';
  process.stdin.setEncoding('utf8');
  process.stdin.on('data',chunk=>input+=chunk);
  process.stdin.on('end',()=>{
    try {
      const value=JSON.parse(input);
      const f=fixture({requestOverride:JSON.parse(value.envelope.payload),secret:value.secret,
        initialProperties:value.properties||null});
      const receipt=f.context.pqmSandboxAllScopeExecution20261109(value.envelope);
      process.stdout.write(JSON.stringify({receipt,properties:Object.fromEntries(f.props),
        sheetReads:f.calls.sheetReads,sheetWrites:f.calls.sheetWrites,propertyWrites:f.calls.propertyWrites}));
    } catch(error) {
      process.stderr.write(String(error && error.message || error));
      process.exitCode=2;
    }
  });
} else {

test('v22 accepts the 25-row signed closure payload and returns a no-append receipt',()=>{
  const f=fixture();
  const units=f.envelope.payload.length;
  assert.equal(units,8821);
  assert.ok(units>8192 && units<=32768);
  const beforeSheetWrites=f.calls.sheetWrites;
  const receipt=f.context.pqmSandboxAllScopeExecution20261109(f.envelope);
  assert.equal(receipt.status,'ADMIN_CLOSED_PREWRITE_NO_WRITE');
  assert.equal(receipt.requestId,REQUEST_ID);
  assert.equal(receipt.closeId,f.request.closeId);
  assert.equal(receipt.prewriteStage,'append_inflight_save');
  assert.equal(receipt.proofType,'LEGACY_V1_WRITEAHEAD_OVERSIZE');
  assert.ok(receipt.writeAheadBytes>8000);
  assert.equal(receipt.checkpointMaxBytes,8000);
  assert.equal(receipt.legacyManifestProjectionDigest,f.request.legacyManifestProjectionDigest);
  assert.equal(f.props.has('PQM_EXECUTION_PREWRITE_CLOSED_'+REQUEST_ID),true);
  assert.equal(f.props.has('PQM_EXECUTION_UNCERTAIN'),false);
  assert.ok(f.calls.sheetReads>0);
  assert.equal(f.calls.sheetWrites,beforeSheetWrites);
});

test('same close ID replay returns the stored tombstone without another write',()=>{
  const f=fixture();
  const first=f.context.pqmSandboxAllScopeExecution20261109(f.envelope);
  const propertyWrites=f.calls.propertyWrites;
  const second=f.context.pqmSandboxAllScopeExecution20261109(f.envelope);
  assert.equal(first.digest,second.digest);
  assert.equal(second.idempotent,true);
  assert.equal(f.calls.propertyWrites,propertyWrites);
  assert.equal(f.calls.sheetWrites,0);
});

test('bad HMAC, incomplete legacy proof, other large action, and payload above 32768 fail closed',()=>{
  const f=fixture();
  assert.throws(()=>f.context.pqmSandboxAllScopeExecution20261109({...f.envelope,signature:'x'.repeat(43)}),
    /execution authorization rejected/);
  const incomplete=signed({...f.request,legacyManifestRows:undefined});
  assert.throws(()=>f.context.pqmSandboxAllScopeExecution20261109(incomplete),
    /historical v1 manifest proof is not allowed/);
  const other=signed({...f.request,action:'apply'});
  assert.throws(()=>f.context.pqmSandboxAllScopeExecution20261109(other),
    /oversized execution payload is restricted/);
  const huge=fixture({formulaLength:2000});
  assert.ok(huge.envelope.payload.length>32768);
  assert.throws(()=>huge.context.pqmSandboxAllScopeExecution20261109(huge.envelope),
    /invalid execution envelope/);
  assert.equal(f.calls.propertyWrites,0);
  assert.equal(f.calls.sheetReads,0);
  assert.equal(f.calls.sheetWrites,0);
});
}
