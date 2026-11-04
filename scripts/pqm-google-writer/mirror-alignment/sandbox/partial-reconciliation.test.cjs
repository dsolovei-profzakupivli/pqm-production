const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const crypto=require('node:crypto');

const dir=__dirname;
const requestId='d'.repeat(32);
const reconciliationId='e'.repeat(32);
const actor='sandbox-admin';
const digest=crypto.createHash('sha256').update('synthetic old plan').digest('base64url');

function fixture(options={}) {
  const context=vm.createContext({Date,Map,Set,JSON,Math,Object,Array,String,Number,RegExp,Error,
    console:{log(){}},Logger:{log(){}}});
  for(const file of fs.readdirSync(dir).filter(name=>name.endsWith('.gs')))
    vm.runInContext(fs.readFileSync(path.join(dir,file),'utf8'),context,{filename:file});
  const cfg=context.PQM_MIRROR_ENV;
  const secret='TEST_ONLY_RECONCILIATION_SECRET_0123456789';
  const eventKey='PQM_EXECUTION_RECONCILIATION_'+reconciliationId;
  let marker=requestId,deleteFailures=options.deleteFailures||0,dailySyncCalls=0,spreadsheetWrites=0;
  const initialRun={actor:'original-operator',trigger:'manual',digest,result:null};
  const properties=new Map([
    ['PQM_EXECUTION_SHARED_SECRET',secret],
    ['PQM_SANDBOX_GOOGLE_REGISTRY_SPREADSHEET_ID',cfg.spreadsheetId],
    ['PQM_EXECUTION_UNCERTAIN',requestId],
    ['PQM_EXECUTION_RUN_'+requestId,JSON.stringify(initialRun)]
  ]);
  const lock={tryLock:()=>true,releaseLock(){}};
  context.ScriptApp={getScriptId:()=>cfg.scriptId};
  context.PropertiesService={getScriptProperties:()=>({
    getProperty:key=>properties.has(key)?properties.get(key):null,
    setProperty:(key,value)=>properties.set(key,value),
    deleteProperty:key=>{
      if(key==='PQM_EXECUTION_UNCERTAIN'&&deleteFailures>0){deleteFailures--;throw new Error('synthetic delete failure');}
      properties.delete(key);
    },
    getProperties:()=>Object.fromEntries(properties)
  })};
  context.Utilities={
    DigestAlgorithm:{SHA_256:'sha256'},Charset:{UTF_8:'utf8'},
    computeDigest:(algorithm,value,charset)=>Array.from(crypto.createHash(algorithm).update(value,charset||'utf8').digest()),
    base64DecodeWebSafe:value=>Array.from(Buffer.from(value,'base64url')),
    computeHmacSha256Signature:(value,key)=>crypto.createHmac('sha256',key).update(value).digest(),
    base64EncodeWebSafe:bytes=>Buffer.from(bytes).toString('base64url')
  };
  context.SpreadsheetApp={openById:id=>({getId:()=>id,getRange(){spreadsheetWrites++;throw new Error('No Sheet writes permitted in reconciliation');}}),
    getActiveSpreadsheet(){throw new Error('Active spreadsheet must not be used');}};
  context.LockService={getScriptLock:()=>lock};
  context.PQM_SANDBOX_PARTIAL_RECONCILIATION_FINGERPRINT_=
    crypto.createHash('sha256').update(requestId,'utf8').digest('hex').slice(0,24);
  context.pqmSandboxDailySync=()=>{dailySyncCalls++;throw new Error('Apply must never run');};
  const evidence=context.pqmSandboxPartialReconciliationEvidence_();
  const evidenceDigest=context.pqmSandboxReconciliationDigest_(evidence);
  const message={environment:'SANDBOX',scriptId:cfg.scriptId,spreadsheetId:cfg.spreadsheetId,
    contract:'pqm-mirror-datetime-v1',action:'reconcile_partial',requestId,actor,trigger:'manual',
    issuedAt:Math.floor(Date.now()/1000),expiresAt:Math.floor(Date.now()/1000)+300,expectedDigest:null,
    reconciliationId,requestFingerprint:context.PQM_SANDBOX_PARTIAL_RECONCILIATION_FINGERPRINT_,
    evidence,evidenceDigest};
  function envelope(overrides={}){
    const payload=JSON.stringify({...message,...overrides});
    return{payload,signature:crypto.createHmac('sha256',secret).update(payload).digest('base64url')};
  }
  return {context,cfg,properties,message,envelope,eventKey,initialRun,
    call:e=>context.pqmSandboxExecution(e),
    get marker(){return properties.get('PQM_EXECUTION_UNCERTAIN')||null;},
    get spreadsheetWrites(){return spreadsheetWrites;},get dailySyncCalls(){return dailySyncCalls;}};
}

test('valid Sandbox reconciliation preserves original run and clears only its matching marker',()=>{
  const f=fixture();
  const result=f.call(f.envelope());
  assert.equal(result.status,'RECONCILED_PARTIAL');
  assert.equal(result.requestFingerprint,f.message.requestFingerprint);
  assert.equal(result.evidenceDigest,f.message.evidenceDigest);
  assert.equal(f.marker,null);
  const run=JSON.parse(f.properties.get('PQM_EXECUTION_RUN_'+requestId));
  assert.equal(run.reconciliation.status,'RECONCILED_PARTIAL');
  assert.equal(run.reconciliation.originalStatus,'outcome_unknown');
  assert.equal(run.result.status,'RECONCILED_PARTIAL');
  const event=JSON.parse(f.properties.get(f.eventKey));
  assert.equal(event.state,'RECONCILED_PARTIAL');
  assert.deepEqual(JSON.parse(event.originalRunRecordRaw),f.initialRun);
  assert.equal(f.spreadsheetWrites,0);
  assert.equal(f.dailySyncCalls,0);
});

test('same reconciliation request is idempotent and never replays Apply',()=>{
  const f=fixture();
  const first=f.call(f.envelope());
  const second=f.call(f.envelope());
  assert.equal(JSON.stringify(second),JSON.stringify(first));
  assert.equal(f.dailySyncCalls,0);
  assert.equal(f.spreadsheetWrites,0);
});

test('fingerprint, evidence, environment, and run-state mismatches fail closed',()=>{
  for(const overrides of [
    {requestFingerprint:'0'.repeat(24)},
    {evidence:{verified_append_rows:49}},
    {environment:'PROD'},
    {requestId:'f'.repeat(32)}
  ]){
    const f=fixture();
    assert.throws(()=>f.call(f.envelope(overrides)));
    assert.equal(f.marker,requestId);
    assert.equal(JSON.parse(f.properties.get('PQM_EXECUTION_RUN_'+requestId)).result,null);
    assert.equal(f.dailySyncCalls,0);
  }
  const withResult=fixture();
  const prior={...withResult.initialRun,result:{status:'COMPLETE'}};
  withResult.properties.set('PQM_EXECUTION_RUN_'+requestId,JSON.stringify(prior));
  assert.throws(()=>withResult.call(withResult.envelope()),/run state changed/);
  assert.equal(withResult.marker,requestId);
});

test('failure clearing the marker retains the hold and same-ID retry completes safely',()=>{
  const f=fixture({deleteFailures:1});
  assert.throws(()=>f.call(f.envelope()),/synthetic delete failure/);
  assert.equal(f.marker,requestId);
  assert.equal(JSON.parse(f.properties.get('PQM_EXECUTION_RUN_'+requestId)).result.status,'RECONCILED_PARTIAL');
  const result=f.call(f.envelope());
  assert.equal(result.status,'RECONCILED_PARTIAL');
  assert.equal(f.marker,null);
  assert.equal(f.dailySyncCalls,0);
});
