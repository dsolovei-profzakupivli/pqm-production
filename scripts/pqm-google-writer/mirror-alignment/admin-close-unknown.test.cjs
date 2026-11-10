const assert=require('node:assert/strict');
const crypto=require('node:crypto');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

const sourcePath=path.join(__dirname,'sandbox','PqmSandboxAllScopeExecution20261109.gs');
const source=fs.readFileSync(sourcePath,'utf8');
const scriptId='1Ht0jL2xQc3hsd6uWKui4uA6o1z2Oe_BAUbZq8HTXcw6C1Kpyi7JxNtmQ';
const spreadsheetId='1lZtneKmCTvFcEL0erlJbegVzTTLNA-IKnjempn1G8Ww';
const secret='LOCAL_MOCK_SECRET_ONLY_012345678901234567890123';
const requestId='a'.repeat(32),closeId='b'.repeat(32);
const planDigest=crypto.createHash('sha256').update('synthetic plan').digest('base64url');
const evidenceDigest=crypto.createHash('sha256').update('close evidence').digest('base64url');
const reasonDigest=crypto.createHash('sha256').update('admin reason').digest('base64url');

function fixture(options={}){
  const runRaw=JSON.stringify({actor:'writer-user',trigger:'manual',digest:planDigest,
    planScope:options.scope||'ALL',state:options.runState||'uncertain',inflight:0,uncertainChunk:0,
    nextChunk:0,steps:[],result:null});
  const values=new Map([['PQM_EXECUTION_SHARED_SECRET',secret],
    ['PQM_EXECUTION_UNCERTAIN',options.marker===undefined?requestId:options.marker],
    ['PQM_EXECUTION_RUN_'+requestId,runRaw]]);
  let failDeleteOnce=!!options.failDeleteOnce,openCalls=0,lockAvailable=true,releaseCalls=0;
  const properties={getProperty:key=>values.has(key)?values.get(key):null,
    setProperty:(key,value)=>values.set(key,String(value)),
    deleteProperty:key=>{if(key==='PQM_EXECUTION_UNCERTAIN'&&failDeleteOnce){failDeleteOnce=false;throw new Error('simulated property delete failure');}values.delete(key);}};
  const lock={tryLock:()=>lockAvailable,releaseLock:()=>releaseCalls++};
  const context=vm.createContext({Date,Map,Set,console:{log(){}}});
  context.PQM_MIRROR_ENV={environment:'SANDBOX',scriptId,spreadsheetId};
  context.PQM_EXECUTION_CONTEXT_=null;
  context.ScriptApp={getScriptId:()=>scriptId};
  context.PropertiesService={getScriptProperties:()=>properties};
  context.LockService={getScriptLock:()=>lock};
  context.SpreadsheetApp={openById:()=>{openCalls++;throw new Error('close action must not open Sheets');}};
  context.Utilities={Charset:{UTF_8:'UTF_8'},DigestAlgorithm:{SHA_256:'SHA_256'},
    computeHmacSha256Signature:(raw,key)=>crypto.createHmac('sha256',key).update(raw,'utf8').digest(),
    computeDigest:(_algorithm,value)=>crypto.createHash('sha256').update(value,'utf8').digest(),
    base64EncodeWebSafe:value=>Buffer.from(value).toString('base64url')};
  context.pqmSandboxIsCanonicalDigest_=value=>typeof value==='string'&&/^[A-Za-z0-9_-]{43}$/.test(value);
  vm.runInContext(source,context,{filename:path.basename(sourcePath)});
  function envelope(action='close_unknown_run',changes={}){
    const now=Math.floor(Date.now()/1000);
    const payloadObject={environment:'SANDBOX',scriptId,spreadsheetId,contract:'pqm-mirror-datetime-v1',
      action,requestId,actor:'admin-fixture',trigger:'manual',issuedAt:now,expiresAt:now+300,
      expectedDigest:planDigest,planScope:options.scope||'ALL',closeId,
      closeEvidenceDigest:evidenceDigest,reasonDigest,...changes};
    if(action==='apply')Object.assign(payloadObject,{chunkIndex:0,chunkId:'d'.repeat(32),
      chunkDigest:planDigest,planId:requestId,chunkDetailsDigest:evidenceDigest,
      chunkPhase:'append',chunkAddedAt:'2026-11-10T10:00:00+02:00'});
    const payload=JSON.stringify(payloadObject);
    return{payload,signature:crypto.createHmac('sha256',secret).update(payload,'utf8').digest('base64url')};
  }
  return{context,values,runRaw,envelope,call:e=>context.pqmSandboxAllScopeExecution20261109(e),
    get openCalls(){return openCalls;},get releaseCalls(){return releaseCalls;},
    set lockAvailable(value){lockAvailable=value;}};
}

function test(name,fn){try{fn();console.log('PASS '+name);}catch(error){console.error('FAIL '+name+' '+error.stack);process.exitCode=1;}}

test('close persists tombstone first, preserves uncertain record, releases marker, and never opens Sheets',()=>{
  const f=fixture();
  const first=f.call(f.envelope());
  assert.equal(first.status,'ADMIN_CLOSED_UNKNOWN');
  assert.equal(first.disposition,'OUTCOME_UNKNOWN_NOT_CONFIRMED');
  assert.equal(first.idempotent,false);
  assert.equal(f.values.get('PQM_EXECUTION_RUN_'+requestId),f.runRaw);
  assert.equal(f.values.has('PQM_EXECUTION_UNCERTAIN'),false);
  assert.ok(f.values.has('PQM_EXECUTION_CLOSED_'+requestId));
  assert.equal(f.openCalls,0);
  const tombstone=f.values.get('PQM_EXECUTION_CLOSED_'+requestId);
  const second=f.call(f.envelope());
  assert.equal(second.status,'ADMIN_CLOSED_UNKNOWN');
  assert.equal(second.idempotent,true);
  assert.equal(f.values.get('PQM_EXECUTION_CLOSED_'+requestId),tombstone);
  assert.equal(f.openCalls,0);
});

test('same closed request cannot pass through ALL Apply',()=>{
  const f=fixture();f.call(f.envelope());
  assert.throws(()=>f.call(f.envelope('apply')),/permanently non-replayable/);
  assert.equal(f.openCalls,0);
});

test('different close ID cannot reuse tombstone',()=>{
  const f=fixture();f.call(f.envelope());
  assert.throws(()=>f.call(f.envelope('close_unknown_run',{closeId:'c'.repeat(32)})),/retry binding rejected/);
  assert.equal(f.openCalls,0);
});

test('marker mismatch or changed run state leaves properties untouched',()=>{
  const wrongMarker=fixture({marker:'d'.repeat(32)}),before=[...wrongMarker.values];
  assert.throws(()=>wrongMarker.call(wrongMarker.envelope()),/marker no longer matches/);
  assert.deepEqual([...wrongMarker.values],before);
  const wrongState=fixture({runState:'ready'}),stateBefore=[...wrongState.values];
  assert.throws(()=>wrongState.call(wrongState.envelope()),/run binding changed/);
  assert.deepEqual([...wrongState.values],stateBefore);
});

test('failed marker deletion is retried idempotently with the same close ID',()=>{
  const f=fixture({failDeleteOnce:true});
  assert.throws(()=>f.call(f.envelope()),/simulated property delete failure/);
  assert.ok(f.values.has('PQM_EXECUTION_CLOSED_'+requestId));
  assert.equal(f.values.get('PQM_EXECUTION_UNCERTAIN'),requestId);
  const result=f.call(f.envelope());
  assert.equal(result.idempotent,true);
  assert.equal(f.values.has('PQM_EXECUTION_UNCERTAIN'),false);
  assert.equal(f.openCalls,0);
});

test('ScriptLock contention makes no property changes',()=>{
  const f=fixture(),before=[...f.values];f.lockAvailable=false;
  assert.throws(()=>f.call(f.envelope()),/another writer/);
  assert.deepEqual([...f.values],before);
  assert.equal(f.openCalls,0);
});

test('protected historical HOLD identity is rejected before any property or Sheets access',()=>{
  const f=fixture(),before=[...f.values];
  assert.throws(()=>f.call(f.envelope('close_unknown_run',
    {requestId:'592128d9837d4b71bbeb330ef8aabf4b'})),/rejects this action or scope/);
  assert.deepEqual([...f.values],before);
  assert.equal(f.openCalls,0);
});
