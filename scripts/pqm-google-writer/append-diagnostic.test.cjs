const assert=require('node:assert/strict');
const crypto=require('node:crypto');
const fs=require('node:fs');
const path=require('node:path');
const test=require('node:test');
const vm=require('node:vm');

const source=fs.readFileSync(path.join(__dirname,'mirror-alignment/sandbox/PqmSandboxAppendDiagnostic20261112.gs'),'utf8');
const id='7'.repeat(32),secret='sandbox-diagnostic-secret-'.padEnd(40,'S');
const b64digest=value=>crypto.createHash('sha256').update(value).digest('base64url');

function fixture({rowsWritten=25,duplicate=false,wrongTab=false,valueMismatch=false,failMetadata=false,manifestMismatch=false}={}) {
  const fullDigest=b64digest('full-preview'),appendDigest=b64digest('append-preview');
  const sourceDigest=b64digest('source'),detailsDigest=b64digest('details'),chunkDigest=b64digest('chunk');
  const targets=[],next={'ФОП':2,'ЮО':2};
  for(let i=0;i<276;i++){
    const tab=i%2?'ЮО':'ФОП',code=String(10000000+i).padStart(8,'0');
    targets.push({tab,code,row:next[tab]++});
  }
  const laterCode=targets[25].code;
  const byTab={'ФОП':[],'ЮО':[]},service=new Map();
  targets.forEach((item,index)=>{
    const row={values:Array(15).fill(''),formulas:Array(15).fill(''),codeDisplay:''};
    if(index<rowsWritten){
      row.values[1]=item.code;row.formulas[0]=`=IF(B${item.row}="","",1)`;row.codeDisplay=item.code;
      if(valueMismatch&&index===0)row.values[1]='99999999';
      service.set(`${item.tab}:${item.row}`,['2026-11-11T20:00:00+02:00',id,id]);
    }
    byTab[item.tab][item.row-2]=row;
  });
  if(duplicate){
    const first=targets[0],other=first.tab==='ФОП'?'ЮО':'ФОП';
    byTab[other].push({values:Array(15).fill(''),formulas:Array(15).fill(''),codeDisplay:first.code});
    const row=byTab[other].length+1;
    service.set(`${other}:${row}`,['2026-11-11T20:00:00+02:00',id,id]);
  }
  if(wrongTab){
    const first=targets[0],other=first.tab==='ФОП'?'ЮО':'ФОП';
    byTab[first.tab][first.row-2]={values:Array(15).fill(''),formulas:Array(15).fill(''),codeDisplay:''};
    const row=byTab[other].length+2;const moved={values:Array(15).fill(''),formulas:Array(15).fill(''),codeDisplay:first.code};
    moved.values[1]=first.code;moved.formulas[0]=`=IF(B${first.row}="","",1)`;
    byTab[other].push(moved);service.set(`${other}:${row}`,['2026-11-11T20:00:00+02:00',id,id]);
  }
  const changes=targets.map(item=>({tab:item.tab,row:item.row,append:true,cells:{
    0:`=IF(B${item.row}="","",1)`,1:item.code}}));
  const manifestRows=targets.slice(0,25).map((item,index)=>({tab:item.tab,row:item.row,code:item.code,
    cellsDigest:'cells-digest',formulaA:`=IF(B${item.row}="","",1)`,
    planId:id,runId:id,serviceMetadata:{addedAt:'2026-11-11T20:00:00+02:00',planId:id,runId:id}}));
  const manifest={chunkIndex:0,chunkId:'8'.repeat(32),chunkDigest,planId:id,runId:id,rows:manifestRows};
  const record={state:'uncertain',chunkJournalVersion:1,planScope:'APPEND_ONLY',runId:id,planId:id,
    digest:appendDigest,inflight:0,uncertainChunk:0,nextChunk:0,steps:[],inflightManifest:{ref:'manifest'}};
  if(manifestMismatch)manifest.chunkDigest=b64digest('different chunk');
  const properties=new Map([['PQM_EXECUTION_SHARED_SECRET',secret],['PQM_EXECUTION_UNCERTAIN',id],
    [`PQM_EXECUTION_RUN_${id}`,JSON.stringify(record)]]);
  let writes=0,locked=false;
  const ctx={Date,Map,Set,JSON,Math,Object,Array,String,Number,RegExp,Error,
    PQM_MIRROR_ENV:{environment:'SANDBOX',scriptId:'script-sandbox',spreadsheetId:'sheet-sandbox'},
    PQM_EXECUTION_CONTEXT_:null,PQM_GOOGLE_TABS:['ФОП','ЮО'],
    Utilities:{Charset:{UTF_8:'UTF_8'},computeHmacSha256Signature:(value,key)=>crypto.createHmac('sha256',key).update(value,'utf8').digest(),
      base64EncodeWebSafe:value=>Buffer.from(value).toString('base64url')},
    PropertiesService:{getScriptProperties:()=>({getProperty:key=>properties.get(key)||null,
      setProperty:()=>{writes++;},deleteProperty:()=>{writes++;}})},
    ScriptApp:{getScriptId:()=> 'script-sandbox'},
    SpreadsheetApp:{openById:sheet=>({getId:()=>sheet})},
    LockService:{getScriptLock:()=>({tryLock:()=>{if(locked)return false;locked=true;return true;},releaseLock:()=>{locked=false;}})},
    pqmSandboxIsCanonicalDigest_:value=>typeof value==='string'&&/^[A-Za-z0-9_-]{43}$/.test(value),
    pqmExecutionCheckpointResolveManifest_:()=>manifest,
    pqmSandboxFullLoad_:()=>({state:{payload_digest:sourceDigest},body:{items:[]},tabs:JSON.parse(JSON.stringify({
      'ФОП':{rows:byTab['ФОП']},'ЮО':{rows:byTab['ЮО']}}))}),
    pqmGooglePlan_:()=>({changes,counts:{appended:276,conflicts:0,errors:0}}),
    pqmSandboxFullBlocked_:()=>false,
    pqmSandboxFullState_:(_body,tabs)=>({payload_digest:sourceDigest,laterChunkStillPresent:
      Object.values(tabs).some(tab=>tab.rows.some(row=>row.codeDisplay===laterCode))}),
    pqmSandboxFullDigest_:value=>value.state&&value.state.scope==='APPEND_ONLY'?appendDigest:
      value.laterChunkStillPresent?b64digest('changed-plan'):fullDigest,
    pqmSandboxControlledDigest_:()=> 'cells-digest',
    pqmGoogleBlank_:value=>value===null||value===undefined||value==='',
    pqmSandboxExecutionComparableValue_:value=>value===null||value===undefined?'':String(value),
    pqmSandboxAppendRowMetadata_:()=>({cells:[],height:20}),
    pqmSandboxAppendVerifyMetadata_:()=>{if(failMetadata)throw new Error('synthetic read-back failure');},
    Sheets:{Spreadsheets:{Values:{batchGet:(_id,request)=>{
      const ranges=request.ranges||[];
      if(failMetadata)throw new Error('synthetic Sheets read failure');
      return {valueRanges:ranges.map(range=>{
        const match=range.match(/^'(.+)'!Q(\d+):S(\d+)$/);assert.ok(match);
        const [,tab,first,last]=match,rows=[];
        for(let row=Number(first);row<=Number(last);row++)rows.push(service.get(`${tab}:${row}`)||[]);
        return {values:rows};
      })};
    }}}}};
  vm.createContext(ctx);vm.runInContext(source,ctx);
  const request={environment:'SANDBOX',scriptId:'script-sandbox',spreadsheetId:'sheet-sandbox',
    contract:'pqm-mirror-datetime-v1',action:'diagnose_append_plan',requestId:id,actor:'admin',trigger:'manual',
    issuedAt:Math.floor(Date.now()/1000),expiresAt:Math.floor(Date.now()/1000)+300,
    expectedDigest:appendDigest,planScope:'APPEND_ONLY',chunkIndex:0,chunkId:manifest.chunkId,
    chunkDigest:chunkDigest,planId:id,detailsDigest,fullPlanDigest:fullDigest,sourceDigest,
    totalAppendCount:targets.length,targetIdentities:targets};
  const payload=JSON.stringify(request),signature=crypto.createHmac('sha256',secret).update(payload).digest('base64url');
  return {ctx,properties,request,envelope:{payload,signature},targets,get writes(){return writes;}};
}

test('audits a 276-row plan with the first 25 exactly present and never writes state',()=>{
  const f=fixture(),before=JSON.stringify([...f.properties]);
  const result=f.ctx.pqmSandboxAppendDiagnostic20261112(f.envelope);
  assert.equal(result.status,'DIAGNOSED');
  assert.deepEqual(JSON.parse(JSON.stringify(result.counts)),
    {planned:276,confirmed:25,missing:251,conflict:0,unverified:0,remaining:251});
  assert.equal(result.firstChunkRecoveryEvidence,true,JSON.stringify(result));
  assert.equal(result.readOnly,true);
  assert.equal(f.writes,0);
  assert.equal(JSON.stringify([...f.properties]),before);
  assert.equal(JSON.stringify(result).includes(f.targets[0].code),false,'supplier codes are never returned');
});

test('classifies duplicate, wrong-tab and mismatching rows as conflicts',()=>{
  for(const options of [{duplicate:true},{wrongTab:true},{valueMismatch:true}]){
    const f=fixture(options),result=f.ctx.pqmSandboxAppendDiagnostic20261112(f.envelope);
    assert.equal(result.counts.conflict,1);
    assert.equal(result.counts.confirmed,24);
    assert.equal(result.firstChunkRecoveryEvidence,false);
    assert.equal(f.writes,0);
  }
});

test('incomplete metadata read returns blocked/unverified and preserves run properties',()=>{
  const f=fixture({failMetadata:true}),before=JSON.stringify([...f.properties]);
  const result=f.ctx.pqmSandboxAppendDiagnostic20261112(f.envelope);
  assert.equal(result.status,'BLOCKED');
  assert.equal(result.counts.unverified,276);
  assert.equal(result.firstChunkRecoveryEvidence,false);
  assert.equal(JSON.stringify([...f.properties]),before);
  assert.equal(f.writes,0);
});

test('a later-chunk row is not erased during first-chunk plan reconstruction',()=>{
  const f=fixture({rowsWritten:26}),result=f.ctx.pqmSandboxAppendDiagnostic20261112(f.envelope);
  assert.equal(result.status,'BLOCKED');
  assert.equal(result.firstChunkRecoveryEvidence,false);
  assert.equal(result.counts.confirmed,0);
  assert.equal(result.counts.unverified,276);
  assert.ok(result.reasonCodes.includes('PREVIEW_RECONSTRUCTION_MISMATCH'));
  assert.equal(f.writes,0);
});

test('manifest mismatch and bad signature fail closed without property writes',()=>{
  const f=fixture({manifestMismatch:true}),before=JSON.stringify([...f.properties]);
  const result=f.ctx.pqmSandboxAppendDiagnostic20261112(f.envelope);
  assert.equal(result.status,'BLOCKED');
  assert.equal(result.firstChunkRecoveryEvidence,false);
  assert.equal(f.writes,0);
  const bad=fixture();bad.envelope.signature='invalid';
  assert.throws(()=>bad.ctx.pqmSandboxAppendDiagnostic20261112(bad.envelope),/authorization rejected/);
  assert.equal(JSON.stringify([...bad.properties]),JSON.stringify([...fixture().properties]));
  assert.equal(bad.writes,0);
});
