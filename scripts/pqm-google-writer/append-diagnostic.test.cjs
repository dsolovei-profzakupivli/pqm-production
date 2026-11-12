const assert=require('node:assert/strict');
const crypto=require('node:crypto');
const fs=require('node:fs');
const path=require('node:path');
const test=require('node:test');
const vm=require('node:vm');

const source=fs.readFileSync(path.join(__dirname,'mirror-alignment/sandbox/PqmSandboxAppendDiagnostic20261112.gs'),'utf8');
const id='7'.repeat(32),secret='sandbox-diagnostic-secret-'.padEnd(40,'S');
const b64digest=value=>crypto.createHash('sha256').update(value).digest('base64url');

function fixture({rowsWritten=25,duplicate=false,wrongTab=false,valueMismatch=false,failMetadata=false,manifestMismatch=false,
  manifestChunkIndex='absent',manifestOverrides={},recordOverrides={},fullDigestMismatch=false,
  appendDigestMismatch=false,plannedAppendCount=276,appendOperationCount=276,unsafePlan=false,
  sourceMismatch=false,fieldMismatchCodes=[],formulaMismatchCodes=[]}={}) {
  const fullDigest=b64digest('full-preview'),appendDigest=b64digest('append-preview');
  const sourceDigest=b64digest('source'),detailsDigest=b64digest('details'),chunkDigest=b64digest('chunk');
  const targets=[],next={'ФОП':2,'ЮО':2};
  for(let i=0;i<276;i++){
    const tab=i%2?'ЮО':'ФОП',legal=['32835814','32871061','33134397','33642588','33872747','33897714'];
    const code=tab==='ЮО'&&i<12?legal[Math.floor(i/2)]:String(10000000+i).padStart(8,'0');
    targets.push({tab,code,row:next[tab]++});
  }
  const laterCode=targets[25].code;
  const byTab={'ФОП':[],'ЮО':[]},service=new Map();
  targets.forEach((item,index)=>{
    const row={values:Array(15).fill(''),formulas:Array(15).fill(''),codeDisplay:''};
    if(index<rowsWritten){
      row.values[1]=item.code;row.formulas[0]=`=IF(B${item.row}="","",1)`;row.codeDisplay=item.code;
      if(valueMismatch&&index===0)row.values[1]='99999999';
      if(fieldMismatchCodes.includes(item.code))row.values[2]='SENSITIVE_CELL_VALUE';
      if(formulaMismatchCodes.includes(item.code))row.formulas[0]='=1';
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
  const manifest={chunkId:'8'.repeat(32),chunkDigest,planId:id,runId:id,rows:manifestRows};
  if(manifestChunkIndex!=='absent')manifest.chunkIndex=manifestChunkIndex;
  Object.assign(manifest,manifestOverrides);
  const record={state:'uncertain',chunkJournalVersion:1,planScope:'APPEND_ONLY',runId:id,planId:id,
    digest:appendDigest,inflight:0,uncertainChunk:0,nextChunk:0,steps:[],inflightManifest:{ref:'manifest'}};
  Object.assign(record,recordOverrides);
  if(manifestMismatch)manifest.chunkDigest=b64digest('different chunk');
  const properties=new Map([['PQM_EXECUTION_SHARED_SECRET',secret],['PQM_EXECUTION_UNCERTAIN',id],
    [`PQM_EXECUTION_RUN_${id}`,JSON.stringify(record)]]);
  let writes=0,sheetsWrites=0,locked=false;
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
    pqmSandboxFullLoad_:()=>({state:{payload_digest:sourceMismatch?b64digest('other source'):sourceDigest},body:{items:[]},tabs:JSON.parse(JSON.stringify({
      'ФОП':{rows:byTab['ФОП']},'ЮО':{rows:byTab['ЮО']}}))}),
    pqmGooglePlan_:()=>({changes:appendOperationCount===276?changes:changes.slice(0,appendOperationCount),
      counts:{appended:plannedAppendCount,conflicts:0,errors:0}}),
    pqmSandboxFullBlocked_:()=>unsafePlan,
    pqmSandboxFullState_:(_body,tabs)=>({payload_digest:sourceDigest,laterChunkStillPresent:
      Object.values(tabs).some(tab=>tab.rows.some(row=>row.codeDisplay===laterCode))}),
    pqmSandboxFullDigest_:value=>value.laterChunkStillPresent?b64digest('changed-plan'):
      value.state&&value.state.scope==='APPEND_ONLY'?(appendDigestMismatch?b64digest('different-append'):appendDigest):
        fullDigestMismatch?b64digest('different-full'):fullDigest,
    pqmSandboxControlledDigest_:value=>value&&value.kind
      ?b64digest(JSON.stringify(canonical(value))):Array.isArray(value)||value&&value.values&&value.formulas&&value.service
        ?b64digest(JSON.stringify(canonical(value))):'cells-digest',
    pqmGoogleSnapshot_:()=>JSON.parse(JSON.stringify({
      'ФОП':{rows:byTab['ФОП']},'ЮО':{rows:byTab['ЮО']}})),
    pqmGoogleBlank_:value=>value===null||value===undefined||value==='',
    pqmSandboxExecutionComparableValue_:value=>value===null||value===undefined?'':String(value),
    pqmSandboxAppendRowMetadata_:()=>({cells:[],height:20}),
    pqmSandboxAppendVerifyMetadata_:()=>{if(failMetadata)throw new Error('synthetic read-back failure');},
    Sheets:{Spreadsheets:{batchUpdate:()=>{sheetsWrites++;throw new Error('write forbidden in diagnostic mock');},Values:{batchGet:(_id,request)=>{
      const ranges=request.ranges||[];
      if(failMetadata)throw new Error('synthetic Sheets read failure');
      return {valueRanges:ranges.map(range=>{
        const serviceMatch=range.match(/^'(.+)'!Q(\d+):S(\d+)$/);
        const formulaMatch=range.match(/^'(.+)'!A(\d+):O(\d+)$/);assert.ok(serviceMatch||formulaMatch);
        const [,tab,first,last]=(serviceMatch||formulaMatch),rows=[];
        for(let row=Number(first);row<=Number(last);row++){
          if(serviceMatch)rows.push(service.get(`${tab}:${row}`)||[]);
          else {
            const record=byTab[tab][row-2]||{values:[],formulas:[]};
            rows.push(Array.from({length:15},(_,column)=>record.formulas[column]||record.values[column]||''));
          }
        }
        return {values:rows};
      })};
    }}}}};
  vm.createContext(ctx);vm.runInContext(source,ctx);
  const request={environment:'SANDBOX',scriptId:'script-sandbox',spreadsheetId:'sheet-sandbox',
    contract:'pqm-mirror-datetime-v1',action:'diagnose_append_plan',requestId:id,actor:'admin',trigger:'manual',
    diagnosticMode:'recovery',
    issuedAt:Math.floor(Date.now()/1000),expiresAt:Math.floor(Date.now()/1000)+300,
    expectedDigest:appendDigest,planScope:'APPEND_ONLY',chunkIndex:0,chunkId:manifest.chunkId,
    chunkDigest:chunkDigest,planId:id,detailsDigest,fullPlanDigest:fullDigest,sourceDigest,
    totalAppendCount:targets.length,targetIdentities:targets};
  const recoveryEnvelope=sign(request);
  const auditTargets=targets.map(item=>{
    const values=Array(15).fill(''),formulas=Array(15).fill('');
    values[1]=item.code;formulas[0]=`=IF(B${item.row}="","",1)`;
    const projection={tab:item.tab,row:item.row,code:item.code,values,formulas,
      service:{addedAtValid:true,planId:id,runId:id}};
    return [item.tab,item.code,item.row,b64digest(JSON.stringify(canonical(projection)))];
  });
  const auditRequest={environment:'SANDBOX',scriptId:'script-sandbox',spreadsheetId:'sheet-sandbox',
    contract:'pqm-mirror-datetime-v1',action:'diagnose_append_plan',requestId:id,actor:'admin',trigger:'manual',
    issuedAt:Math.floor(Date.now()/1000),expiresAt:Math.floor(Date.now()/1000)+300,
    diagnosticMode:'audit',expectedDigest:appendDigest,planScope:'APPEND_ONLY',chunkIndex:0,planId:id,
    detailsDigest,fullPlanDigest:fullDigest,sourceDigest,totalAppendCount:targets.length,auditTargets,
    auditTargetsDigest:b64digest(JSON.stringify(canonical(auditTargets)))};
  return {ctx,properties,request,envelope:recoveryEnvelope,auditRequest,auditEnvelope:sign(auditRequest),targets,manifest,record,sign,
    get writes(){return writes;},get sheetsWrites(){return sheetsWrites;}};

  function sign(value) {
    const payload=JSON.stringify(value),signature=crypto.createHmac('sha256',secret).update(payload).digest('base64url');
    return {payload,signature};
  }
}

function canonical(value){
  if(Array.isArray(value))return value.map(canonical);
  if(value&&typeof value==='object')return Object.fromEntries(Object.keys(value).sort().map(key=>[key,canonical(value[key])]));
  return value;
}

test('audits a 276-row plan with the first 25 exactly present and never writes state',()=>{
  const f=fixture(),before=JSON.stringify([...f.properties]);
  assert.equal(Object.prototype.hasOwnProperty.call(f.manifest,'chunkIndex'),false,
    'the fixture preserves the actual APPEND_ONLY v1 manifest shape');
  const result=f.ctx.pqmSandboxAppendDiagnostic20261112(f.envelope);
  assert.equal(result.status,'DIAGNOSED');
  assert.deepEqual(JSON.parse(JSON.stringify(result.counts)),
    {planned:276,confirmed:25,missing:251,conflict:0,unverified:0,remaining:251});
  assert.equal(result.firstChunkRecoveryEvidence,true,JSON.stringify(result));
  assert.deepEqual(JSON.parse(JSON.stringify(result.reconstructionChecks)),{
    fullPreviewDigest:'MATCH',appendOnlyDigest:'MATCH',plannedAppendCount:'MATCH',appendOperationCount:'MATCH'});
  assert.deepEqual(JSON.parse(JSON.stringify(result.downstreamChecks)),{
    sourceBinding:'MATCH',planSafety:'MATCH',targetRows:'MATCH',rowValuesAndFormulas:'MATCH',
    serviceMetadata:'MATCH',manifestRows:'MATCH',appendRowMetadata:'MATCH'});
  assert.equal(result.readOnly,true);
  assert.equal(f.writes,0);
  assert.equal(JSON.stringify([...f.properties]),before);
  assert.equal(JSON.stringify(result).includes(f.targets[0].code),false,'supplier codes are never returned');
});

test('reports each preview reconstruction comparison separately without exposing digests',()=>{
  const cases=[
    [{fullDigestMismatch:true},{fullPreviewDigest:'MISMATCH',appendOnlyDigest:'MATCH',
      plannedAppendCount:'MATCH',appendOperationCount:'MATCH'}],
    [{appendDigestMismatch:true},{fullPreviewDigest:'MATCH',appendOnlyDigest:'MISMATCH',
      plannedAppendCount:'MATCH',appendOperationCount:'MATCH'}],
    [{plannedAppendCount:275},{fullPreviewDigest:'MATCH',appendOnlyDigest:'MATCH',
      plannedAppendCount:'MISMATCH',appendOperationCount:'MATCH'}],
    [{appendOperationCount:275},{fullPreviewDigest:'MATCH',appendOnlyDigest:'MATCH',
      plannedAppendCount:'MATCH',appendOperationCount:'MISMATCH'}]
  ];
  for(const [options,expected] of cases){
    const f=fixture(options),before=JSON.stringify([...f.properties]);
    const result=f.ctx.pqmSandboxAppendDiagnostic20261112(f.envelope);
    assert.equal(result.status,'BLOCKED');
    assert.ok(result.reasonCodes.includes('PREVIEW_RECONSTRUCTION_MISMATCH'));
    assert.deepEqual(JSON.parse(JSON.stringify(result.reconstructionChecks)),expected);
    assert.equal(result.firstChunkRecoveryEvidence,false);
    assert.equal(JSON.stringify(result).includes('different-'),false,'digest values are never returned');
    assert.equal(f.writes,0);
    assert.equal(JSON.stringify([...f.properties]),before);
  }
});

test('marks downstream checks NOT_CHECKED when a prerequisite blocks reconstruction',()=>{
  const source=fixture({sourceMismatch:true});
  const sourceResult=source.ctx.pqmSandboxAppendDiagnostic20261112(source.envelope);
  assert.equal(sourceResult.status,'BLOCKED');
  assert.deepEqual(JSON.parse(JSON.stringify(sourceResult.reconstructionChecks)),{
    fullPreviewDigest:'NOT_CHECKED',appendOnlyDigest:'NOT_CHECKED',
    plannedAppendCount:'NOT_CHECKED',appendOperationCount:'NOT_CHECKED'});
  assert.equal(sourceResult.downstreamChecks.sourceBinding,'MISMATCH');
  assert.equal(sourceResult.downstreamChecks.targetRows,'NOT_CHECKED');
  const unsafe=fixture({unsafePlan:true});
  const unsafeResult=unsafe.ctx.pqmSandboxAppendDiagnostic20261112(unsafe.envelope);
  assert.equal(unsafeResult.status,'BLOCKED');
  assert.equal(unsafeResult.downstreamChecks.planSafety,'MISMATCH');
  assert.equal(unsafeResult.reconstructionChecks.fullPreviewDigest,'NOT_CHECKED');
  assert.equal(source.writes,0);assert.equal(unsafe.writes,0);
});

test('accepts a strictly matching explicit v1 chunkIndex zero',()=>{
  const f=fixture({manifestChunkIndex:0}),before=JSON.stringify([...f.properties]);
  const result=f.ctx.pqmSandboxAppendDiagnostic20261112(f.envelope);
  assert.equal(result.status,'DIAGNOSED');
  assert.equal(result.firstChunkRecoveryEvidence,true);
  assert.equal(result.counts.confirmed,25);
  assert.equal(f.writes,0);
  assert.equal(JSON.stringify([...f.properties]),before);
});

test('rejects present malformed or nonzero manifest chunkIndex values',()=>{
  for(const value of [1,'0',null]){
    const f=fixture({manifestChunkIndex:value}),before=JSON.stringify([...f.properties]);
    const result=f.ctx.pqmSandboxAppendDiagnostic20261112(f.envelope);
    assert.equal(result.status,'BLOCKED',`manifest.chunkIndex=${JSON.stringify(value)}`);
    assert.deepEqual(JSON.parse(JSON.stringify(result.manifestMismatchFields)),['manifest.chunkIndex']);
    assert.equal(result.firstChunkRecoveryEvidence,false);
    assert.equal(f.writes,0);
    assert.equal(JSON.stringify([...f.properties]),before);
  }
});

test('missing chunkIndex is accepted only for the bound v1 APPEND_ONLY first chunk',()=>{
  for(const recordOverrides of [
    {chunkJournalVersion:2},
    {planScope:'ALL'},
    {inflight:1},
    {uncertainChunk:1},
    {nextChunk:1}
  ]){
    const f=fixture({recordOverrides}),before=JSON.stringify([...f.properties]);
    const result=f.ctx.pqmSandboxAppendDiagnostic20261112(f.envelope);
    assert.equal(result.status,'BLOCKED',JSON.stringify(recordOverrides));
    assert.ok(result.reasonCodes.includes('RUN_RECORD_BINDING_MISMATCH'));
    assert.equal(result.firstChunkRecoveryEvidence,false);
    assert.equal(f.writes,0);
    assert.equal(JSON.stringify([...f.properties]),before);
  }
  for(const [field,value] of [['chunkIndex',1],['planScope','ALL']]){
    const f=fixture(),before=JSON.stringify([...f.properties]);
    f.request[field]=value;f.envelope=f.sign(f.request);
    assert.throws(()=>f.ctx.pqmSandboxAppendDiagnostic20261112(f.envelope),/APPEND diagnostic binding rejected/);
    assert.equal(f.writes,0);
    assert.equal(JSON.stringify([...f.properties]),before);
  }
});

test('legacy missing chunkIndex does not relax other manifest header or row bindings',()=>{
  for(const manifestOverrides of [
    {chunkId:'9'.repeat(32)},
    {chunkDigest:b64digest('wrong chunk digest')},
    {planId:'8'.repeat(32)},
    {runId:'8'.repeat(32)},
    {rows:[]}
  ]){
    const f=fixture();Object.assign(f.manifest,manifestOverrides);
    const before=JSON.stringify([...f.properties]);
    const result=f.ctx.pqmSandboxAppendDiagnostic20261112(f.envelope);
    assert.equal(result.status,'BLOCKED',JSON.stringify(Object.keys(manifestOverrides)));
    assert.equal(result.firstChunkRecoveryEvidence,false);
    assert.ok(result.reasonCodes.includes('MANIFEST_BINDING_MISMATCH'));
    assert.equal(f.writes,0);
    assert.equal(JSON.stringify([...f.properties]),before);
  }
  const f=fixture();f.manifest.rows[0].cellsDigest=b64digest('different cell proof');
  const before=JSON.stringify([...f.properties]);
  const result=f.ctx.pqmSandboxAppendDiagnostic20261112(f.envelope);
  assert.equal(result.firstChunkRecoveryEvidence,false);
  assert.ok(result.reasonCodes.includes('MANIFEST_BINDING_MISMATCH'));
  assert.ok(result.manifestMismatchFields.includes('manifest.rows[0].cellsDigest'));
  assert.equal(f.writes,0);
  assert.equal(JSON.stringify([...f.properties]),before);
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
  assert.deepEqual(JSON.parse(JSON.stringify(result.manifestMismatchFields)),['manifest.chunkDigest']);
  assert.equal(f.writes,0);
  const bad=fixture();bad.envelope.signature='invalid';
  assert.throws(()=>bad.ctx.pqmSandboxAppendDiagnostic20261112(bad.envelope),/authorization rejected/);
  assert.equal(JSON.stringify([...bad.properties]),JSON.stringify([...fixture().properties]));
  assert.equal(bad.writes,0);
});

test('read-only row audit succeeds without checkpoint, run property or uncertainty marker',()=>{
  const f=fixture(),before=JSON.stringify([...f.properties]);
  f.properties.delete('PQM_EXECUTION_UNCERTAIN');
  f.properties.delete(`PQM_EXECUTION_RUN_${id}`);
  const result=f.ctx.pqmSandboxAppendDiagnostic20261112(f.auditEnvelope);
  assert.equal(result.status,'AUDITED',JSON.stringify(result));
  assert.deepEqual(JSON.parse(JSON.stringify(result.counts)),
    {planned:276,confirmed:25,missing:251,conflict:0,unverified:0,remaining:251});
  assert.equal(result.firstChunkRecoveryEvidence,undefined);
  assert.equal(f.writes,0);
  assert.equal([...f.properties].some(([key])=>key.includes(id)),false);
  assert.equal(JSON.stringify(result).includes(f.targets[0].code),false);
  assert.notEqual(JSON.stringify([...f.properties]),before,'the fixture removes properties to prove the audit does not require them');
});

test('read-only audit classifies row conflicts and fails incomplete sheet reads closed',()=>{
  const mismatch=fixture({valueMismatch:true});
  const mismatchResult=mismatch.ctx.pqmSandboxAppendDiagnostic20261112(mismatch.auditEnvelope);
  assert.equal(mismatchResult.counts.conflict,1);
  assert.equal(mismatchResult.counts.confirmed,24);
  const incomplete=fixture({failMetadata:true});
  const incompleteResult=incomplete.ctx.pqmSandboxAppendDiagnostic20261112(incomplete.auditEnvelope);
  assert.equal(incompleteResult.status,'READ_INCOMPLETE');
  assert.equal(incompleteResult.counts.unverified,25);
  assert.equal(incompleteResult.counts.missing,251);
  assert.equal(incomplete.writes,0);
});

test('six legal-entity conflicts expose only mismatching field names',()=>{
  const codes=['32835814','32871061','33134397','33642588','33872747','33897714'];
  const f=fixture({fieldMismatchCodes:codes,formulaMismatchCodes:[codes[0]]}),stateBefore=JSON.stringify([...f.properties]);
  const audit=f.ctx.pqmSandboxAppendDiagnostic20261112(f.auditEnvelope);
  assert.equal(audit.counts.conflict,6);
  assert.deepEqual(JSON.parse(JSON.stringify(audit.conflicts.map(item=>item.code))),codes);
  assert.ok(audit.conflicts.every(item=>item.fields.length===0&&item.observed_digest));
  const targetsByCode=new Map(f.targets.map(item=>[item.code,item]));
  const fieldTargets=audit.conflicts.map(item=>{
    const target=targetsByCode.get(item.code),values=Array(15).fill(''),formulas=Array(15).fill('');
    values[1]=item.code;formulas[0]=`=IF(B${target.row}="","",1)`;
    const expected=Array.from({length:15},(_,column)=>{
      const cell=column===0?{kind:'formula',value:formulas[column]}:
        column===1?{kind:'value',value:values[column]}:{kind:'blank',value:''};
      return [cell.kind,f.ctx.pqmSandboxControlledDigest_(cell)];
    });
    return [target.tab,target.code,target.row,item.observed_digest,expected];
  });
  const payload={...f.auditRequest,diagnosticMode:'audit_fields',auditFieldTargets:fieldTargets,
    auditFieldTargetsDigest:b64digest(JSON.stringify(canonical(fieldTargets)))};
  delete payload.auditTargets;delete payload.auditTargetsDigest;
  const details=f.ctx.pqmSandboxAppendDiagnostic20261112(f.sign(payload));
  assert.equal(details.status,'AUDIT_DETAILS');
  assert.deepEqual(JSON.parse(JSON.stringify(details.conflicts.map(item=>item.code))),codes);
  assert.ok(details.conflicts.every((item,index)=>item.status==='ROW_CHANGED'&&
    JSON.stringify(item.fields)===(index===0?'["formula:A","value:C"]':'["value:C"]')));
  assert.equal(JSON.stringify(details).includes('SENSITIVE_CELL_VALUE'),false);
  assert.equal(JSON.stringify(details).includes('observed_digest'),false);
  assert.equal(f.writes,0);
  assert.equal(f.sheetsWrites,0);
  assert.equal(JSON.stringify([...f.properties]),stateBefore);
});

test('Writer UI keeps a copyable APPEND report panel with field paths only',()=>{
  const ui=fs.readFileSync(path.join(__dirname,'../../google_writer_ui.js'),'utf8').split('const googleWriterRunButton=')[0];
  const context={esc:value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))};
  vm.createContext(context);vm.runInContext(ui,context);
  vm.runInContext(`googleWriterAppendDiagnosticReport={request_id:'r',status:'DIAGNOSED',
    counts:{planned:276,confirmed:19,missing:251,conflict:6,unverified:0,remaining:257},reason_codes:['TARGET_CONFLICT'],
    conflicts:[{code:'32835814',fields:['value:C'],detail_status:'VERIFIED'}],recovery_status:'BLOCKED',
    recovery_reason_codes:['PREVIEW_RECONSTRUCTION_MISMATCH'],recovery_field_mismatches:['manifest.chunkDigest'],
    reconstruction_checks:{full_preview_digest:'MISMATCH',append_only_digest:'MATCH',
      planned_append_count:'MATCH',append_operation_count:'MATCH'},
    downstream_checks:{source_binding:'MATCH',plan_safety:'MATCH',target_rows:'NOT_CHECKED',
      row_values_and_formulas:'NOT_CHECKED',service_metadata:'NOT_CHECKED',manifest_rows:'NOT_CHECKED',
      append_row_metadata:'NOT_CHECKED'}};`,context);
  const html=vm.runInContext(`googleWriterAppendDiagnosticHtml('r')`,context);
  const text=vm.runInContext(`googleWriterAppendReportText(googleWriterAppendDiagnosticReport)`,context);
  assert.match(html,/google-writer-append-diagnostic-result/);assert.match(html,/Скопіювати короткий звіт/);
  assert.match(html,/32835814/);assert.match(html,/value:C/);
  assert.match(html,/Повний digest Preview: MISMATCH/);assert.match(html,/APPEND_ONLY digest: MATCH/);
  assert.match(html,/Значення й формули: NOT_CHECKED/);
  assert.match(text,/PREVIEW_RECONSTRUCTION_MISMATCH/);assert.match(text,/manifest.chunkDigest/);
  assert.match(text,/Повний digest Preview — MISMATCH/);assert.match(text,/Цільові рядки — NOT_CHECKED/);
  assert.equal(/SENSITIVE_CELL_VALUE|observed_digest|[A-Za-z0-9_-]{43}/.test(html+text),false);
});
