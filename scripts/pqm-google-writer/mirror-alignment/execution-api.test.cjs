const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),crypto=require('node:crypto');
for(const env of ['prod','sandbox']){
  const dir=path.join(__dirname,env),prefix=env==='prod'?'pqmProd':'pqmSandbox';
  function fixture(){
    const context=vm.createContext({Date,Map,Set,console:{log(){}}});
    for(const file of fs.readdirSync(dir).filter(f=>f.endsWith('.gs')))
      vm.runInContext(fs.readFileSync(path.join(dir,file),'utf8'),context,{filename:file});
    const cfg=context.PQM_MIRROR_ENV,secret='LOCAL_TEST_SECRET_NOT_A_CREDENTIAL_0123456789';
    const properties=new Map([['PQM_EXECUTION_SHARED_SECRET',secret],
      [env==='prod'?'PQM_PROD_GOOGLE_REGISTRY_SPREADSHEET_ID':'PQM_SANDBOX_GOOGLE_REGISTRY_SPREADSHEET_ID',cfg.spreadsheetId]]);
    let opens=0,active=0,locks=0,releases=0,runs=0,available=true;
    const lock={tryLock(){locks++;return available;},releaseLock(){releases++;}};
    context.ScriptApp={getScriptId:()=>cfg.scriptId};
    context.PropertiesService={getScriptProperties:()=>({getProperty:k=>properties.get(k)||null,
      setProperty:(k,v)=>properties.set(k,v),getProperties:()=>Object.fromEntries(properties)})};
    context.Utilities={computeHmacSha256Signature:(raw,key)=>crypto.createHmac('sha256',key).update(raw).digest(),
      base64EncodeWebSafe:raw=>Buffer.from(raw).toString('base64url')};
    context.SpreadsheetApp={openById:id=>{opens++;assert.equal(id,cfg.spreadsheetId);return{getId:()=>id};},
      getActiveSpreadsheet:()=>{active++;throw new Error('Not available through Execution API');},
      getUi:()=>{throw new Error('No UI in headless execution');}};
    context.LockService={getScriptLock:()=>lock};
    context[prefix+'FullLoad_']=()=>({plan_digest:'a'.repeat(64),state:{payload_digest:'b'.repeat(64)},
      plan:{counts:{appended:1,updated:2,conflicts:0,errors:0,unchanged:3}}});
    context[prefix+'DailySync']=execution=>{runs++;assert.equal(execution.lock,lock);
      assert.equal(execution.expectedDigest,'a'.repeat(64));
      return {status:'COMPLETE',append:1,update:2,conflict:0,error:0,remaining_safe:0,batches:1};};
    function envelope(action='preview',changes={}){
      const now=Math.floor(Date.now()/1000);
      const message={environment:cfg.environment,scriptId:cfg.scriptId,spreadsheetId:cfg.spreadsheetId,
        contract:'pqm-mirror-datetime-v1',action,requestId:'c'.repeat(32),actor:'test-uo',trigger:'manual',
        issuedAt:now,expiresAt:now+300,expectedDigest:action==='apply'?'a'.repeat(64):null,...changes};
      const payload=JSON.stringify(message);return{payload,signature:crypto.createHmac('sha256',secret).update(payload).digest('base64url')};
    }
    return{context,cfg,properties,envelope,call:e=>context[prefix+'Execution'](e),
      get opens(){return opens},get active(){return active},get releases(){return releases},get runs(){return runs},
      lockUnavailable(){available=false;}};
  }
  test(env+': explicit headless spreadsheet, Preview zero receipts/writer calls',()=>{
    const f=fixture(),before=JSON.stringify([...f.properties]);const result=f.call(f.envelope());
    assert.equal(result.status,'PREVIEW');assert.equal(result.digest,'a'.repeat(64));
    assert.equal(f.opens,1);assert.equal(f.active,0);assert.equal(f.runs,0);
    assert.equal(JSON.stringify([...f.properties]),before);assert.equal(f.context.PQM_EXECUTION_CONTEXT_,null);
  });
  test(env+': wrong script, destination, environment, signature or expired request reject before open',()=>{
    for(const changes of [{scriptId:'other'},{spreadsheetId:'other'},{environment:'OTHER'},{expiresAt:1}]){
      const f=fixture();assert.throws(()=>f.call(f.envelope('preview',changes)),/rejected/);assert.equal(f.opens,0);assert.equal(f.runs,0);
    }
    const f=fixture(),e=f.envelope();e.signature+='bad';assert.throws(()=>f.call(e),/authorization rejected/);assert.equal(f.opens,0);
  });
  test(env+': stale Preview and occupied ScriptLock mean no Apply',()=>{
    const f=fixture();assert.throws(()=>f.call(f.envelope('apply',{expectedDigest:'d'.repeat(64)})),/stale/);assert.equal(f.runs,0);
    const busy=fixture();busy.lockUnavailable();assert.throws(()=>busy.call(busy.envelope('apply')),/another writer/);assert.equal(busy.opens,0);
  });
  test(env+': Apply uses same DailySync engine once; repeat returns receipt without Apply',()=>{
    const f=fixture(),e=f.envelope('apply'),first=f.call(e),second=f.call(e);
    assert.equal(first.status,'COMPLETE');assert.equal(JSON.stringify(first),JSON.stringify(second));assert.equal(f.runs,1);
    assert.equal(f.active,0);assert.equal(f.releases,2);
    assert.throws(()=>f.call(f.envelope('apply',{actor:'another-uo'})),/identity rejected/);assert.equal(f.runs,1);
  });
  test(env+': partial exception holds future requests; never silently retries',()=>{
    const f=fixture();let writes=0;
    f.context[prefix+'DailySync']=()=>{writes++;throw new Error('Simulated partial write');};
    assert.throws(()=>f.call(f.envelope('apply')),/may be partial/);assert.equal(writes,1);
    assert.throws(()=>f.call(f.envelope('apply')),/no retry/);assert.equal(writes,1);
    assert.throws(()=>f.call(f.envelope('apply',{requestId:'d'.repeat(32)})),/unresolved/);assert.equal(writes,1);
    assert.equal(f.context.PQM_EXECUTION_CONTEXT_,null);
  });
  test(env+': legacy bound handlers still require bound identity outside execution',()=>{
    const f=fixture();f.context.SpreadsheetApp.getActiveSpreadsheet=()=>({getId:()=>f.cfg.spreadsheetId});
    assert.equal(f.context.pqmMirrorContext_().environment,f.cfg.environment);
    f.context.SpreadsheetApp.getActiveSpreadsheet=()=>null;
    assert.throws(()=>f.context.pqmMirrorContext_(),/identity mismatch/);
  });
}
