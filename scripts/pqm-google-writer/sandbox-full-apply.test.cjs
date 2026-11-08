const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');
const path = require('node:path');
const {spawnSync} = require('node:child_process');

const sandboxSourceDir = path.join(__dirname, 'mirror-alignment/sandbox');
const source = ['PqmSandboxPreviewDependencies.gs', 'PqmGoogleBusinessMatrix.gs', 'PqmVerificationDatetime.gs', 'PqmSandboxPreview.gs',
  'PqmSandboxControlledApply.gs', 'PqmSandboxFullApply.gs']
  .map(name => fs.readFileSync(path.join(__dirname, name), 'utf8')).join('\n');
const v6Source = ['PqmEnvironmentGuard.gs', 'PqmSandboxPreviewDependencies.gs', 'PqmVerificationDatetime.gs',
  'PqmSandboxPreview.gs', 'PqmSandboxControlledApply.gs', 'PqmSandboxAppendApply.gs',
  'PqmSandboxFullApply.gs', 'PqmSandboxExecution.gs']
  .map(name => fs.readFileSync(path.join(sandboxSourceDir, name), 'utf8')).join('\n');
const executionSource = [
  fs.readFileSync(path.join(sandboxSourceDir, 'PqmSandboxAppendApply.gs'), 'utf8'),
  fs.readFileSync(path.join(sandboxSourceDir, 'PqmSandboxFullApply.gs'), 'utf8'),
  fs.readFileSync(path.join(__dirname, 'mirror-alignment/shared/PqmExecutionCheckpoint.gs'), 'utf8'),
  fs.readFileSync(path.join(sandboxSourceDir, 'PqmSandboxControlledApply.gs'), 'utf8'),
  fs.readFileSync(path.join(sandboxSourceDir, 'PqmSandboxExecution.gs'), 'utf8'),
  fs.readFileSync(path.join(sandboxSourceDir, 'PqmSandboxPreviewDependencies.gs'), 'utf8'),
  fs.readFileSync(path.join(sandboxSourceDir, 'PqmVerificationDatetime.gs'), 'utf8'),
  fs.readFileSync(path.join(sandboxSourceDir, 'PqmSandboxPreview.gs'), 'utf8')
].join('\n');
const clone = value => JSON.parse(JSON.stringify(value));
function response(text) { return {getSelectedButton: () => 'OK', getResponseText: () => text}; }

function executionFixture(planDigest) {
  const properties = new Map([['PQM_EXECUTION_SHARED_SECRET', 'S'.repeat(40)] ]);
  let applyCalls = 0, locked = false, failAfterWrite=false, sourceDigest='payload-digest', sheetDigest='sheet-state-0';
  const context = {
    Date,
    PQM_MIRROR_ENV: {environment: 'SANDBOX', scriptId: 'script-sandbox', spreadsheetId: 'sheet-sandbox'},
    Utilities: {
      Charset: {UTF_8:'UTF_8'},
      DigestAlgorithm:{SHA_256:'SHA_256'},
      computeDigest:(_algorithm,value)=>crypto.createHash('sha256').update(value,'utf8').digest(),
      computeHmacSha256Signature: (value, secret, charset) => {
        assert.equal(charset,'UTF_8');return crypto.createHmac('sha256', secret).update(value,'utf8').digest();},
      base64EncodeWebSafe: value => Buffer.from(value).toString('base64url'),
      base64DecodeWebSafe: value => [...Buffer.from(value, 'base64url')],
      newBlob: value => ({getBytes: () => [...Buffer.from(value, 'utf8')]})
    },
    PropertiesService: {getScriptProperties: () => ({
      getProperty: key => properties.get(key) || null,
      setProperty: (key, value) => {properties.set(key, value);},
      getProperties: () => Object.fromEntries(properties)
    })},
    ScriptApp: {getScriptId: () => 'script-sandbox'},
    SpreadsheetApp: {openById: id => ({getId: () => id})},
    LockService: {getScriptLock: () => ({
      tryLock: () => {if (locked) return false; locked = true; return true;},
      releaseLock: () => {locked = false;}
    })},
    PQM_EXECUTION_CONTEXT_: null,
    pqmSandboxControlledSpreadsheetId_: () => 'sheet-sandbox',
    pqmSandboxFullLoad_: () => ({plan_digest: planDigest, plan: {counts: {
      appended: 0, updated: 0, conflicts: 0, errors: 0, unchanged: 0
    }}, state: {payload_digest: sourceDigest, google_digest: crypto.createHash('sha256').update(sheetDigest).digest('base64url')}}),
    pqmSandboxDailySync: () => {throw new Error('Legacy DailySync must not be used by checkpoint Apply');}
  };
  vm.createContext(context);
  vm.runInContext(executionSource, context);
  vm.runInContext(`pqmSandboxFullPreviewDetails_=function(){return {version:1,environment:'SANDBOX',plan_digest:${JSON.stringify(planDigest)},
    append_only_digest:'${crypto.createHash('sha256').update('append-only fixture').digest('base64url')}',
    counts:{append:0,update:0,conflict:0,error:0},appends:[],updates:[],conflicts:[],errors:[]};}`,context);
  context.PQM_GOOGLE_TABS=['ФОП','ЮО'];
  context.pqmSandboxFullLoad_ = () => ({plan_digest: planDigest, append_only_digest:planDigest, plan: {counts: {
    appended: 0, updated: 0, conflicts: 0, errors: 0, unchanged: 0
  }}, state: {payload_digest: sourceDigest, google_digest: crypto.createHash('sha256').update(sheetDigest).digest('base64url')}});
  context.pqmSandboxControlledSpreadsheetId_ = () => 'sheet-sandbox';
  context.pqmSandboxApplyCheckpointStep_ = (id, loaded, request, props, key, record, makeReceipt) => {
    assert.equal(id,'sheet-sandbox');
    assert.equal(loaded.state.payload_digest,sourceDigest);
    assert.equal(loaded.state.google_digest,crypto.createHash('sha256').update(sheetDigest).digest('base64url'));
    applyCalls++;
    const index=request.chunkIndex;
    if(failAfterWrite){
      failAfterWrite=false;record.inflight=index;record.state='writing';
      context.pqmExecutionCheckpointSave_(props,key,record,8000);
      sheetDigest='sheet-state-unknown';
      throw new Error('synthetic lost response after write');
    }
    const more=index===0;
    const status=more?'APPLY_CHUNK_VERIFIED':'COMPLETE';
    const counts={append:more?25:0,update:more?0:1,conflict:0,error:0,remaining_safe:more?1:0,batches:1};
    const step={status,chunkIndex:index,nextChunk:index+1,more,phase:more?'append':'update',counts,
      verified:true,digest:request.expectedDigest,planScope:request.planScope||'ALL',
      payloadDigest:record.payloadDigest,googleDigest:crypto.createHash('sha256').update(sheetDigest).digest('base64url')};
    record.inflight=null;record.state=more?'ready':'complete';record.nextChunk=index+1;
    record.steps=record.steps||[];record.steps.push(step);
    record.aggregate=record.aggregate||{append:0,update:0,batches:0};
    record.aggregate.append+=counts.append;record.aggregate.update+=counts.update;record.aggregate.batches++;
    sheetDigest='sheet-state-'+(index+1);record.googleDigest=crypto.createHash('sha256').update(sheetDigest).digest('base64url');
    step.googleDigest=record.googleDigest;
    step.checkpointDigest=context.pqmExecutionCheckpointStateDigest_(record);
    if(!more) record.result={...makeReceipt(status,{append:25,update:1,conflict:0,error:0,remaining_safe:0,batches:2},planDigest),
      chunkIndex:index,nextChunk:index+1,more:false,phase:'update',checkpointDigest:step.checkpointDigest,planScope:request.planScope||'ALL'};
    context.pqmExecutionCheckpointSave_(props,key,record,8000);
    return context.pqmExecutionCheckpointReceipt_(request,makeReceipt,step);
  };
  function request(action, requestId, expectedDigest, chunkIndex=0,planScope='ALL',expectedCheckpointDigest=null) {
    const issuedAt = Math.floor(Date.now() / 1000);
    const payload = JSON.stringify({environment: 'SANDBOX', scriptId: 'script-sandbox',
      spreadsheetId: 'sheet-sandbox', contract: 'pqm-mirror-datetime-v1', action,
      requestId, actor: 'synthetic-admin', trigger: 'manual', issuedAt,
      expiresAt: issuedAt + 300, expectedDigest,...(['apply','resume_check'].includes(action)?{chunkIndex,planScope}:{}),
      ...(expectedCheckpointDigest?{expectedCheckpointDigest}:{})});
    const signature = crypto.createHmac('sha256', 'S'.repeat(40)).update(payload).digest('base64url');
    return {payload, signature};
  }
  return {context, properties, request, get applyCalls() {return applyCalls;},
    setSourceDigest(value){sourceDigest=value;},setSheetDigest(value){sheetDigest=value;},
    failAfterNextWrite(){failAfterWrite=true;}};
}

function realCheckpointExecutionFixture(planDigest,totalAppends=30) {
  const properties=new Map([['PQM_EXECUTION_SHARED_SECRET','S'.repeat(40)]]);
  let locked=false,version=0,writes=0,loseNextResponse=false,sheetDigest='sheet-state-0',payloadDigest='source-stable';
  const nextRow={'ФОП':2,'ЮО':2};
  const queue=Array.from({length:totalAppends},(_,i)=>{
    const tab=i%2?'ЮО':'ФОП',row=nextRow[tab]++;
    return {tab,row,cells:{1:'code-'+i}};
  });
  const writtenRows={'ФОП':0,'ЮО':0};
  const tabsNow=()=>({ФОП:{rows:Array.from({length:writtenRows['ФОП']},()=>({}))},
    ЮО:{rows:Array.from({length:writtenRows['ЮО']},()=>({}))}});
  const context={Date,Map,Set,JSON,Math,Object,Array,String,Number,RegExp,Error,
    PQM_MIRROR_ENV:{environment:'SANDBOX',scriptId:'script-sandbox',spreadsheetId:'sheet-sandbox'},
    Utilities:{Charset:{UTF_8:'UTF_8'},DigestAlgorithm:{SHA_256:'SHA_256'},
      computeDigest:(_algorithm,value)=>crypto.createHash('sha256').update(value,'utf8').digest(),
      computeHmacSha256Signature:(value,secret,charset)=>{
      assert.equal(charset,'UTF_8');return crypto.createHmac('sha256',secret).update(value,'utf8').digest();},
      base64EncodeWebSafe:value=>Buffer.from(value).toString('base64url'),
      base64DecodeWebSafe:value=>[...Buffer.from(value,'base64url')],
      newBlob:value=>({getBytes:()=>[...Buffer.from(value,'utf8')]})},
    PropertiesService:{getScriptProperties:()=>({getProperty:key=>properties.get(key)||null,
      setProperty:(key,value)=>properties.set(key,value),getProperties:()=>Object.fromEntries(properties)})},
    ScriptApp:{getScriptId:()=> 'script-sandbox'},SpreadsheetApp:{openById:id=>({getId:()=>id})},
    LockService:{getScriptLock:()=>({tryLock:()=>{if(locked)return false;locked=true;return true;},releaseLock:()=>{locked=false;}})},
    PQM_EXECUTION_CONTEXT_:null,pqmSandboxControlledSpreadsheetId_:()=> 'sheet-sandbox'};
  vm.createContext(context);vm.runInContext(executionSource,context);
  context.pqmSandboxFullPreviewDetails_=loaded=>({version:1,environment:'SANDBOX',plan_digest:loaded.plan_digest,
    append_only_digest:loaded.append_only_digest,
    remaining_plan_digest:loaded.append_only_digest,
    counts:{append:queue.length,update:0,conflict:0,error:0},
    appends:Array.from({length:queue.length},()=>({operation:'APPEND',cells:[{column:'A',formula:true}]})),
    updates:[],conflicts:[],errors:[]});
  context.PQM_GOOGLE_TABS=['ФОП','ЮО'];
  context.pqmSandboxControlledSpreadsheetId_=()=> 'sheet-sandbox';
  const controlledDigest=value=>crypto.createHash('sha256').update(JSON.stringify(value),'utf8').digest('base64url');
  const stateDigest=()=>controlledDigest({version,sheetDigest});
  context.pqmSandboxFullLoad_=()=>({plan_digest:planDigest,
    append_only_digest:planDigest,
    plan:{counts:{appended:queue.length,updated:0,conflicts:0,errors:0,unchanged:0}},
    state:{payload_digest:payloadDigest,google_digest:stateDigest()},body:{count:0,items:[]},tabs:tabsNow(),entries:[]});
  context.pqmSandboxCheckpointAdapter_=()=>({
    appendLoad:(_id,_allowlist,loaded,limit)=>({selected:queue.slice(0,limit),tabs:{
      ФОП:{rows:Array.from({length:writtenRows['ФОП']},()=>({}))},
      ЮО:{rows:Array.from({length:writtenRows['ЮО']},()=>({}))}},
      payload_digest:loaded.state.payload_digest,plan:loaded.plan}),
    appendPrewriteGuard:()=>{},appendRowMetadata:()=>({cells:[],height:28}),
    appendRequests:selected=>[{selected:selected}],
    batchUpdate:request=>{writes++;request.requests[0].selected.forEach(change=>{writtenRows[change.tab]++;});
      queue.splice(0,request.requests[0].selected.length);version++;
      if(loseNextResponse){loseNextResponse=false;throw new Error('synthetic response lost after successful write');}},
    appendVerify:(_id,selected)=>({rows:selected.map(change=>{
      const values=Array.from({length:15},()=> ''); values[1]=change.cells[1]||'';
      return {tab:change.tab,row:change.row,values,formulas:Array.from({length:15},()=>''),codeDisplay:values[1]};
    })}),appendVerifyMetadata:()=>{},fullChunks:()=>[],fetchRegistry:()=>({count:0,items:[]}),
    appendPayloadDigest:()=> payloadDigest,protectionCheck:()=>{},readRows:()=>[],fullBeforeCheck:()=>{},
    fullRequests:()=>[],controlledVerify:()=>({verification_passed:true}),snapshot:()=>({version,sheetDigest}),
    fullSheetState:tabs=>tabs,plan:()=>({counts:{appended:queue.length,updated:0,conflicts:0,errors:0}}),
    controlledDigest,rowState:value=>value});
  const checkpointStep=context.pqmSandboxApplyCheckpointStep_;
  context.pqmSandboxApplyCheckpointStep_=(...args)=>{
    try{return checkpointStep(...args);}catch(error){context.lastCheckpointError=String(error);throw error;}
  };
  function request(action,requestId,expectedDigest,chunkIndex=0,planScope='ALL',expectedCheckpointDigest=null){
    const issuedAt=Math.floor(Date.now()/1000),payload=JSON.stringify({environment:'SANDBOX',
      scriptId:'script-sandbox',spreadsheetId:'sheet-sandbox',contract:'pqm-mirror-datetime-v1',
      action,requestId,actor:'synthetic-admin',trigger:'manual',issuedAt,expiresAt:issuedAt+300,
      expectedDigest,...(['apply','resume_check'].includes(action)?{chunkIndex,planScope}:{}),
      ...(expectedCheckpointDigest?{expectedCheckpointDigest}:{})});
    return {payload,signature:crypto.createHmac('sha256','S'.repeat(40)).update(payload).digest('base64url')};
  }
  return {context,properties,request,get writes(){return writes;},get remaining(){return queue.length;},
    setSheetDigest(value){sheetDigest=value;},setSourceDigest(value){payloadDigest=value;},
    loseNextResponse(){loseNextResponse=true;}};
}

function checkpointStepFixture(totalAppends=30, updateRows=1) {
  const context={Date,Map,Set,JSON,Math,Object,Array,String,Number,RegExp,Error,
    console:{log(){}},PQM_MIRROR_ENV:{environment:'SANDBOX',scriptId:'script-sandbox',spreadsheetId:'sheet-sandbox'}};
  vm.createContext(context);vm.runInContext(executionSource,context);
  context.PQM_GOOGLE_TABS=['ФОП','ЮО'];
  const nextRow={'ФОП':2,'ЮО':2};
  let appendQueue=Array.from({length:totalAppends},(_,i)=>{
    const tab=i%2?'ЮО':'ФОП',row=nextRow[tab]++;
    return {tab,row,cells:{1:'code-'+i}};
  });
  const writtenRows={'ФОП':0,'ЮО':0};
  const tabsNow=()=>({ФОП:{rows:Array.from({length:writtenRows['ФОП']},()=>({}))},
    ЮО:{rows:Array.from({length:writtenRows['ЮО']},()=>({}))}});
  let remainingUpdates=updateRows, version=0, writeKinds=[], verifiedAppend=0, metadataVerifyCalls=0;
  const payloadDigest='pqm-source-stable';
  context.Utilities={newBlob:value=>({getBytes:()=>Array.from(Buffer.from(value,'utf8'))})};
  context.PQM_SANDBOX_EXECUTION_APPEND_PAGE_ROWS=25;
  context.PQM_SANDBOX_EXECUTION_UPDATE_PAGE_ROWS=50;
  context.PQM_SANDBOX_EXECUTION_UPDATE_PAGE_CELLS=100;
  context.pqmSandboxAppendLoad_=(id,allowlist,full,limit)=>({
    selected:appendQueue.slice(0,limit),tabs:{
      ФОП:{rows:Array.from({length:writtenRows['ФОП']},()=>({}))},
      ЮО:{rows:Array.from({length:writtenRows['ЮО']},()=>({}))}},payload_digest:payloadDigest,
    plan:{counts:{conflicts:2,errors:0}}
  });
  context.pqmSandboxAppendPrewriteGuard_=()=>{};
  context.pqmSandboxAppendRowMetadata_=()=>({cells:Array.from({length:15},()=>({})),height:28});
  context.pqmSandboxAppendRequests_=(selected)=>[{kind:'append',selected:selected}];
  context.pqmSandboxAppendVerify_=(id,selected)=>{verifiedAppend+=selected.length;return {rows:selected.map(change=>{
    const values=Array.from({length:15},()=> ''); values[1]=change.cells[1]||'';
    return {tab:change.tab,row:change.row,values,formulas:Array.from({length:15},()=>''),codeDisplay:values[1]};
  })};};
  context.pqmSandboxAppendVerifyMetadata_=()=>{metadataVerifyCalls++;};
  context.pqmSandboxFullChunks_=()=>remainingUpdates?[[...Array.from({length:remainingUpdates},(_,i)=>({row:i+2,columns:[4]}))]]:[];
  context.pqmSandboxFetchRegistry_=()=>({count:0,items:[]});
  context.pqmSandboxAppendPayloadDigest_=()=>payloadDigest;
  context.pqmSandboxControlledProtectionCheck_=()=>{};
  context.pqmSandboxControlledReadRows_=(id,chunk)=>chunk.map(()=>({}));
  context.pqmSandboxControlledRowState_=row=>row;
  context.pqmSandboxFullBeforeCheck_=()=>{};
  context.pqmSandboxFullRequests_=chunk=>[{kind:'update',rows:chunk.length}];
  context.pqmSandboxControlledVerify_=()=>({verification_passed:true});
  context.pqmSandboxFullSheetState_=tabs=>tabs;
  context.pqmSandboxControlledDigest_=value=>crypto.createHash('sha256')
    .update(JSON.stringify(value),'utf8').digest('base64url');
  context.pqmSandboxFullSheetState_=()=>({version});
  context.pqmGoogleSnapshot_=()=>({version:++version});
  context.pqmGooglePlan_=()=>({counts:{appended:appendQueue.length,updated:remainingUpdates,
    conflicts:2,errors:0}});
  context.pqmMirrorSheetsBatchUpdate_=request=>{
    const kind=request.requests[0].kind;writeKinds.push(kind);version++;
    if(kind==='append'){
      request.requests[0].selected.forEach(change=>{writtenRows[change.tab]++;});
      appendQueue.splice(0,request.requests[0].selected.length);
    }
    else remainingUpdates=Math.max(0,remainingUpdates-(request.requests[0].rows||0));
  };
  context.pqmSandboxControlledDigest_ = value => crypto.createHash('sha256')
    .update(JSON.stringify(value),'utf8').digest('base64url');
  function loaded(){return {state:{payload_digest:payloadDigest,
    google_digest:context.pqmSandboxControlledDigest_({version})},
    plan:{counts:{conflicts:2,errors:0}},body:{count:0,items:[]},tabs:tabsNow(),entries:[]};}
  return {context,loaded,appendLeft:()=>appendQueue.length,writeKinds:()=>writeKinds.slice(),
    get version(){return version;},
    get verifiedAppend(){return verifiedAppend;},get metadataVerifyCalls(){return metadataVerifyCalls;},
    updateLeft:()=>remainingUpdates};
}

function v6PlannerFixture(items, rowsByTab={}) {
  const context={Date,Map,Set,JSON,Math,Object,Array,String,Number,RegExp,Error,Intl,
    console:{log(){}}};
  vm.createContext(context);vm.runInContext(v6Source,context);
  context.ScriptApp={getScriptId:()=>context.PQM_MIRROR_ENV.scriptId};
  context.SpreadsheetApp={getActiveSpreadsheet:()=>({getId:()=>context.PQM_MIRROR_ENV.spreadsheetId})};
  context.PropertiesService={getScriptProperties:()=>({getProperty:()=>null})};
  context.PQM_GOOGLE_TABS=['ФОП','ЮО'];
  context.Utilities={DigestAlgorithm:{SHA_256:'SHA_256'},Charset:{UTF_8:'UTF_8'},
    formatDate:(date,zone,pattern)=>{
      assert.equal(zone,'Europe/Kyiv');
      const parts=Object.fromEntries(new Intl.DateTimeFormat('en-GB',{timeZone:zone,
        year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',
        hourCycle:'h23'}).formatToParts(date).map(part=>[part.type,part.value]));
      return pattern.includes('T')?`${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}.000`:
        `${parts.year}-${parts.month}-${parts.day}`;
    },computeDigest:(_,value)=>crypto.createHash('sha256').update(value).digest(),
    base64EncodeWebSafe:value=>Buffer.from(value).toString('base64url')};
  const tabs=Object.fromEntries(['ФОП','ЮО'].map((name,index)=>[name,{
    id:index+1,maxRows:100,headers:Array.from(context.PQM_GOOGLE_HEADERS),merges:[],protectedRanges:[],
    conditionalFormats:[],templateRowHeight:28,formulaLocale:'uk_UA',rows:rowsByTab[name]||[]} ]));
  const body={count:items.length,items};
  return {context,tabs,body};
}

function v6Item(overrides={}) {
  return {supplier_code:'0000000123',entity_type:'individual_entrepreneur',monitoring_eligible:true,
    google_sync_eligible:true,supplier_name:'ФОП Тестовий',latest_submission_name:null,
    current_manager_name:'Тестовий Керівник',edr_status_current:'Немає інформації',
    prozorro_status_google:'Активний',freshness_marker:'fresh',last_application_date:null,
    google_sync_last_decided_application_date:null,verification_date:null,verification_officer:null,
    verification_datetime_precision:'unknown',...overrides};
}

function v6Row(values, formulas=Array(15).fill(''), codeDisplay=values[1]) {
  return {values,formulas,codeDisplay,dateFormat:'dd.MM.yyyy',verificationDateFormat:'dd.MM.yyyy HH:mm:ss'};
}

function fixture() {
  const logs = [], context = {console: {log: text => logs.push(text)}, Date, Map, Set};
  vm.createContext(context);
  vm.runInContext(source, context);
  const tabs = Object.fromEntries(['ФОП', 'ЮО'].map((name, index) => [name, {
    id: index + 1, maxRows: 40, headers: Array.from(context.PQM_GOOGLE_HEADERS),
    merges: [], protectedRanges: [], conditionalFormats: [], templateRowHeight: 28, rows: []
  }]));
  const body = {count: 8, items: []}, raw = new Map();
  const serial = context.pqmGoogleDate_('2026-09-22');
  for (let i = 0; i < 8; i++) {
    const name = i < 4 ? 'ФОП' : 'ЮО', tab = tabs[name];
    const code = name === 'ФОП' ? String(1000000000 + i) : String(10000000 + i);
    const row = tab.rows.length + 2;
    const values = Array(15).fill('');
    values[0] = 'old'; values[1] = code; values[2] = 'old-name';
    values[4] = 'Зареєстровано'; values[5] = 'Неактивний'; values[7] = serial - 1;
    const formulas = Array(15).fill(''); formulas[0] = `=IF(B${row}="", "", 1)`;
    tab.rows.push({values, formulas, codeDisplay: code, dateFormat: 'dd.MM.yyyy'});
    body.items.push({supplier_code: code, entity_type: name === 'ФОП' ? 'individual_entrepreneur' : 'legal_entity',
      classification_version: 'subject-nature-20261031-v3', classification_status: 'resolved',
      classification_reason: 'established_subject_nature', classification_reason_label: 'Тип підтверджено у fixture',
      target_sheet: name, append_allowed: true,
      monitoring_eligible: true, google_sync_eligible: true,
      google_writer_eligible: true, google_sync_has_active_qualification: true,
      google_sync_has_admission_history: true, google_sync_last_decided_application_decision: 'admit',
      google_sync_last_decided_protocol_at: '', google_sync_last_decided_protocol_officer: '',
      google_sync_last_decided_submission_id: 's' + i, google_sync_latest_rejection_officer: '',
      freshness_marker: 'fresh', supplier_name: 'verified-name',
      edr_status_current: null, verification_date: null, verification_officer: null, verification_event_type: null,
      prozorro_status_google: 'Active', last_application_date: '2026-09-22',
      google_sync_last_decided_application_date: '2026-09-22'});
    raw.set(tab.id + ':' + row, values.map((value, column) => {
      const v = typeof value === 'number' ? {numberValue: value} : {stringValue: value};
      const cell = {userEnteredValue: clone(v), effectiveValue: clone(v), formattedValue: String(value)};
      if (column === 0) {
        cell.userEnteredValue = {formulaValue: formulas[0]};
        cell.effectiveValue = {numberValue: 1}; cell.formattedValue = '1';
      }
      if (column === 7) cell.userEnteredFormat = {numberFormat: {type: 'DATE', pattern: 'dd.MM.yyyy'}};
      return cell;
    }));
  }
  let writes = 0, requests = [], reads = 0, fetches = 0, snapshots = 0, beforeRead = null, afterWrite = null;
  let prompts = [], confirmation = 'NO', released = 0, locked = false;
  context.PQM_SANDBOX_FULL_CHUNK_MAX_CELLS = 4;
  context.PQM_SANDBOX_FULL_CHUNK_MAX_ROWS = 2;
  context.pqmSandboxFetchRegistry_ = () => { fetches++; return clone(body); };
  context.pqmSandboxRegistryUrl_ = () => 'https://pqm-sandbox.onrender.com/api/integrations/suppliers/full-registry';
  context.pqmGoogleSnapshot_ = () => {
    snapshots++;
    const result = clone(tabs);
    Object.values(result).forEach(tab => tab.rows.forEach((row, index) => {
      const cells = raw.get(tab.id + ':' + (index + 2));
      row.values = cells.map(cell => {
        const v = cell.effectiveValue || {};
        return v.stringValue !== undefined ? v.stringValue : v.numberValue !== undefined ? v.numberValue : '';
      });
      row.formulas = cells.map(cell => (cell.userEnteredValue || {}).formulaValue || '');
      row.codeDisplay = cells[1].formattedValue;
      row.dateFormat = ((cells[7].userEnteredFormat || {}).numberFormat || {}).pattern || '';
      row.verificationDateFormat = ((cells[8].userEnteredFormat || {}).numberFormat || {}).pattern || '';
    }));
    return result;
  };
  context.Utilities = {DigestAlgorithm: {SHA_256: 'SHA_256'}, Charset: {UTF_8: 'UTF_8'},
    formatDate: (date, zone) => {
      const parts = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {timeZone: zone,
        year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
        second: '2-digit', hourCycle: 'h23'}).formatToParts(date).map(part => [part.type, part.value]));
      return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}.000`;
    },
    computeDigest: (_, value) => crypto.createHash('sha256').update(value).digest(),
    base64EncodeWebSafe: buffer => Buffer.from(buffer).toString('base64url')};
  context.SpreadsheetApp = {
    getActiveSpreadsheet: () => ({getId: () => context.PQM_SANDBOX_CONTROLLED_SPREADSHEET_ID}),
    getUi: () => ({ButtonSet: {OK_CANCEL: 'OK_CANCEL', YES_NO: 'YES_NO'}, Button: {OK: 'OK', YES: 'YES'},
      prompt: () => prompts.shift() || {getSelectedButton: () => 'CANCEL'}, alert: () => confirmation})
  };
  context.LockService = {getScriptLock: () => ({
    tryLock: () => {if (locked) return false; locked = true; return true;},
    releaseLock: () => {locked = false; released++;}
  })};
  context.Sheets = {Spreadsheets: {
    get: (_, options) => {
      reads++;
      if (beforeRead) beforeRead(reads);
      const grouped = new Map();
      options.ranges.forEach(range => {
        const match = /^'(ФОП|ЮО)'!A(\d+):O\2$/.exec(range);
        assert.ok(match, 'targeted A:O row read only');
        const tab = tabs[match[1]], row = Number(match[2]);
        if (!grouped.has(tab.id)) grouped.set(tab.id, []);
        grouped.get(tab.id).push({startRow: row - 1,
          rowData: [{values: clone(raw.get(tab.id + ':' + row))}]});
      });
      return {sheets: [...grouped].map(([id, data]) => ({properties: {sheetId: id}, data}))};
    },
    batchUpdate: ({requests: next}) => {
      writes++; requests.push(clone(next));
      next.forEach(request => {
        assert.deepEqual(Object.keys(request), ['updateCells']);
        const update = request.updateCells, range = update.range;
        assert.ok([2, 3, 4, 5, 7, 8, 11].includes(range.startColumnIndex));
        const cell = raw.get(range.sheetId + ':' + (range.startRowIndex + 1))[range.startColumnIndex];
        cell.userEnteredValue = clone(update.rows[0].values[0].userEnteredValue);
        cell.effectiveValue = clone(cell.userEnteredValue);
        cell.formattedValue = String(cell.userEnteredValue.stringValue ?? cell.userEnteredValue.numberValue);
        if (range.startColumnIndex === 7 || range.startColumnIndex === 8) {
          cell.userEnteredFormat = clone(update.rows[0].values[0].userEnteredFormat);
        }
      });
      if (afterWrite) afterWrite(writes);
    }
  }};
  return {context, body, tabs, raw, logs, requests,
    get writes() {return writes;}, get reads() {return reads;}, get fetches() {return fetches;},
    get snapshots() {return snapshots;},
    get released() {return released;}, setPrompts: list => {prompts = list;},
    confirm: value => {confirmation = value;}, beforeRead: hook => {beforeRead = hook;},
    afterWrite: hook => {afterWrite = hook;}};
}

function arm(f, preview) {
  f.setPrompts([response(preview.plan_digest)]);
  f.confirm('YES');
}

function setGoogleCell(f, column, value) {
  const cell = f.raw.get('1:2')[column];
  const entered = typeof value === 'number' ? {numberValue: value} : {stringValue: value};
  cell.userEnteredValue = clone(entered);
  cell.effectiveValue = clone(entered);
  cell.formattedValue = String(value);
  if (column === 8) {
    const dateTime = typeof value === 'number' && Math.abs(value - Math.floor(value)) > 1e-9;
    cell.userEnteredFormat = {numberFormat: {type: dateTime ? 'DATE_TIME' : 'DATE',
      pattern: dateTime ? 'dd.MM.yyyy HH:mm:ss' : 'dd.MM.yyyy'}};
  }
}

for (const environment of ['prod', 'sandbox']) test(environment + ': eight complete merged daily cycles converge across real morning and evening code', () => {
  const python = process.env.PQM_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
  const repo = process.env.PQM_PERMANENT_REPO || path.resolve(__dirname, '../..');
  const bridge = path.join(repo, 'validation/local_release_20260911/daily_cycle_evening_fixture.py');
  const scenarios = [
    {pqm: '2026-09-20', po: 'Officer A', google: '2026-09-20', go: 'Officer A', final: ['2026-09-20', 'Officer A']},
    {pqm: '2026-09-20', po: 'Officer A', google: '2026-09-25', go: 'Officer B', final: ['2026-09-25', 'Officer B']},
    // Equal instants preserve the PQM officer; they are not a new verification.
    {pqm: '2026-09-20', po: 'Officer A', google: '2026-09-20', go: 'Officer B', final: ['2026-09-20', 'Officer A']},
    {pqm: '2026-09-25', po: 'Officer B', google: '2026-06-05', go: 'Officer A', final: ['2026-09-25', 'Officer B']},
    {pqm: '2026-09-25', po: 'Officer B', google: '2026-09-25', go: 'Officer B',
      daytime: {i: '2026-06-05', l: 'Officer A'}, final: ['2026-09-25', 'Officer B']},
    {pqm: '2026-09-20', po: 'Officer A', google: '2026-09-20', go: 'Officer A',
      startingGjkm: ['Old G', '2026-09-20', 'Old K', 'Old M'],
      // Newer verified Google observations fully mirror G/J/K/M, including clears.
      daytime: {i: '2026-09-21', g: 'Changed G', j: '', k: 'Changed K', m: ''},
      final: ['2026-09-21', 'Officer A']},
    {pqm: '2026-09-20', po: 'Officer A', google: '2026-09-20', go: 'Officer A',
      e: 'Немає інформації', final: ['2026-09-20', 'Officer A']},
    {pqm: '2026-09-20', po: 'Officer A', google: '2026-09-20', go: 'Officer B',
      e: 'Зареєстровано', factual: 'Припинено', final: ['2026-09-20', 'Officer A']}
  ];
  for (const [index, s] of scenarios.entries()) {
    // Round trips use the current merged writer, never the legacy date-only writer.
    const f = require('./mirror-alignment/engine-fixture.cjs')(environment), item = f.body.items[0];
    const protectedGoogleColumns = [6, 9, 10, 12]; // G/J/K/M are Google-owned inputs.
    const protectedGoogleValues = () => protectedGoogleColumns.map(column =>
      clone(f.raw.get('1:2')[column]));
    // Test-call aliases only. PROD functions still execute their own pinned guards and helpers.
    if (environment === 'prod') for (const name of ['FullApplyPreview','FullApply'])
      f.context['pqmSandbox'+name] = f.context['pqmProd'+name];
    f.context.PQM_SANDBOX_FULL_CHUNK_MAX_CELLS = 400;
    f.context.PQM_PROD_FULL_CHUNK_MAX_CELLS = 6;
    item.verification_date = s.pqm + 'T17:03:19+03:00'; item.verification_officer = s.po;
    item.edr_status_current = s.factual || 'Зареєстровано';
    setGoogleCell(f, 8, f.context.pqmVerificationSerial_(Date.parse(s.google + 'T17:03:19+03:00')));
    setGoogleCell(f, 11, s.go);
    if (s.startingGjkm) for (const [position, column] of [6, 9, 10, 12].entries()) {
      setGoogleCell(f, column, s.startingGjkm[position]);
    }
    if (s.e) setGoogleCell(f, 4, s.e);
    const protectedBeforeMorning = protectedGoogleValues();
    const morning = f.context.pqmSandboxFullApplyPreview();
    arm(f, morning);
    assert.equal(f.context.pqmSandboxFullApply().status, 'COMPLETE', index + 1);
    assert.deepEqual(protectedGoogleValues(), protectedBeforeMorning,
      `scenario ${index + 1}: PQM → Google must preserve Google-owned G/J/K/M`);
    if (index === 6) assert.equal(f.raw.get('1:2')[4].effectiveValue.stringValue, s.e);
    if (s.daytime) for (const [key, value] of Object.entries(s.daytime)) {
      const column = {i: 8, l: 11, g: 6, j: 9, k: 10, m: 12}[key];
      setGoogleCell(f, column, key === 'i' ? f.context.pqmVerificationSerial_(Date.parse(value + 'T17:03:19+03:00')) : value);
    }
    const cell = column => f.raw.get('1:2')[column].effectiveValue;
    const value = column => cell(column).stringValue ?? cell(column).numberValue ?? '';
    const google = {i: new Date(f.context.pqmVerificationDatetime_(value(8)).value).toISOString(), l: value(11),
      e: value(4), g: value(6), j: value(9), k: value(10), m: value(12)};
    const run = spawnSync(python, [bridge], {cwd: repo, encoding: 'utf8',
      env: {...process.env, PYTHONIOENCODING: 'utf-8',
        PQM_GOOGLE_REGISTRY_SPREADSHEET_ID: 'SYNTHETIC_AUTHORIZED'},
      input: JSON.stringify({pqm_date: item.verification_date, pqm_officer: s.po, pqm_status: s.factual || 'Зареєстровано',
        factual: s.factual, pqm_gjkm: s.startingGjkm, google, expect_conflict: index === 7})});
    assert.equal(run.status, 0, `scenario ${index + 1}: ${run.stderr}`);
    const evening = JSON.parse(run.stdout);
    if (index === 7) {
      assert.equal(evening.apply_skipped, true, 'same-timestamp conflicting EDR status blocks Apply');
      assert.equal(evening.conflicts.length, 1, 'the actual same-timestamp discrepancy is reported');
      assert.equal(evening.profile_unchanged, true, 'conflict does not mutate PQM profile');
      assert.equal(evening.events_unchanged, true, 'conflict does not append a verification event');
      assert.equal(evening.date, item.verification_date.replace(/([+-]\d\d:\d\d)$/, '.000$1'));
      assert.equal(evening.officer, s.po);
      continue;
    }
    assert.deepEqual([evening.date, evening.officer],
      [s.final[0] + 'T17:03:19.000+03:00', s.final[1]], `scenario ${index + 1}`);
    assert.equal(evening.second.verification_event_changes, 0, `scenario ${index + 1}: repeat evening`);
    if (index === 5) {
      assert.deepEqual(evening.gjkm, ['Changed G', '', 'Changed K', '']);
      assert.equal(google.j, '', 'the verified Google J cell is intentionally empty');
      assert.equal(google.m, '', 'the verified Google M cell is intentionally empty');
      assert.equal(evening.gjkm[1], '', 'newer Google J blank clears PQM');
      assert.equal(evening.gjkm[3], '', 'newer Google M blank clears PQM');
    }
    if (index === 7) assert.equal(evening.status, 'Припинено');
    item.verification_date = evening.date; item.verification_officer = evening.officer;
    item.edr_status_current = evening.status;
    const plan = f.context.pqmGooglePlan_(f.body, f.context.pqmGoogleSnapshot_('sandbox-id'));
    if (evening.status === 'Немає інформації' && plan.issues.some(issue => issue.supplier_code === item.supplier_code && issue.reason === 'unknown_edr_status')) {
      // Active qualifications do not prove EDR registration. The writer must
      // fail closed instead of publishing "Немає інформації" as an EDR status.
      assert.equal(plan.counts.conflicts, 1,
        `scenario ${index + 1}: ${JSON.stringify(plan.issues)} evening=${JSON.stringify(evening)} google=${JSON.stringify(google)}`);
      assert.equal(plan.counts.errors + plan.counts.duplicate_keys, 0);
      const statusIssues = plan.issues.filter(issue => issue.supplier_code === item.supplier_code);
      assert.equal(statusIssues.length, 1);
      assert.equal(statusIssues[0].reason, 'unknown_edr_status');
      assert.ok(!plan.changes.some(change => Object.values(change.cells).includes('Немає інформації')));
      const targetEntry = Object.entries(f.tabs).find(([, tab]) => tab.rows.some(row =>
        String(row.codeDisplay || row.values[1] || '') === String(item.supplier_code)));
      assert.ok(targetEntry, 'synthetic supplier must map to its existing Google row');
      const [targetTab, targetData] = targetEntry;
      const targetRowIndex = targetData.rows.findIndex(row =>
        String(row.codeDisplay || row.values[1] || '') === String(item.supplier_code));
      const targetRow = targetRowIndex + 2;
      const statusBeforePlan = JSON.stringify(f.raw.get(targetData.id + ':' + targetRow)[4]);
      const writesBeforePlan = f.writes.length;
      assert.ok(!plan.changes.some(change => change.tab === targetTab && change.row === targetRow),
        'unconfirmed EDR status must not produce a Google row write');
      assert.equal(f.writes.length, writesBeforePlan, 'Preview planning must not write to Google');
      assert.equal(JSON.stringify(f.raw.get(targetData.id + ':' + targetRow)[4]), statusBeforePlan,
        'Google EDR status remains unchanged when PQM has no confirmed EDR information');
      continue;
    }
    assert.equal(plan.counts.conflicts + plan.counts.errors + plan.counts.duplicate_keys, 0,
      `scenario ${index + 1}: ${JSON.stringify(plan.issues)} evening=${JSON.stringify(evening)} google=${JSON.stringify(google)}`);
    const next = f.context.pqmSandboxFullApplyPreview();
    if (index === 4) {
      assert.equal(plan.counts.pqm_newer_written, 1,
        'manual Google backdating is corrected forward from preserved PQM evidence');
    } else {
      assert.ok(plan.changes.every(change => !('8' in change.cells) && !('11' in change.cells)),
        `scenario ${index + 1}: next morning reverse I/L write`);
    }
    arm(f, next);
    const protectedBeforeNextMorning = protectedGoogleValues();
    assert.equal(f.context.pqmSandboxFullApply().status, 'COMPLETE');
    assert.deepEqual(protectedGoogleValues(), protectedBeforeNextMorning,
      `scenario ${index + 1}: next PQM → Google cycle must preserve Google-owned G/J/K/M`);
    const stable = f.context.pqmSandboxFullApplyPreview();
    const finalPlan = f.context.pqmGooglePlan_(f.body, f.context.pqmGoogleSnapshot_('sandbox-id'));
    assert.ok(finalPlan.changes.every(change => !('8' in change.cells) && !('11' in change.cells)),
      `scenario ${index + 1}: repeated morning I/L`);
  }
});

test('pending-only supplier stays out of morning queue until a decision; pending follow-up keeps H', () => {
  const f = fixture();
  const first = {...f.body.items[0], supplier_code: '9999999999',
    google_sync_eligible: false, google_writer_eligible: false, monitoring_eligible: true, last_application_date: '2026-09-20',
    google_sync_last_decided_application_date: null};
  f.body.items.push(first); f.body.count++;
  let plan = f.context.pqmGooglePlan_(f.body, f.context.pqmGoogleSnapshot_('sandbox-id'));
  assert.equal(plan.changes.some(x => x.append && x.cells[1] === first.supplier_code), false);
  first.google_sync_eligible = true;
  first.google_writer_eligible = true; first.google_sync_last_decided_application_decision = 'reject';
  first.google_sync_has_active_qualification = false; first.google_sync_has_admission_history = false;
  first.google_sync_latest_rejection_officer = 'Officer A';
  first.last_application_date = '2026-09-20';
  first.google_sync_last_decided_application_date = '2026-09-20';
  plan = f.context.pqmGooglePlan_(f.body, f.context.pqmGoogleSnapshot_('sandbox-id'));
  assert.equal(plan.changes.some(x => x.append && x.cells[1] === first.supplier_code), true);
  const existing = f.body.items[0];
  existing.last_application_date = '2026-09-22';
  plan = f.context.pqmGooglePlan_(f.body, f.context.pqmGoogleSnapshot_('sandbox-id'));
  const before = plan.changes.find(x => x.tab === 'ФОП' && x.row === 2).cells[7];
  // A later pending application must not change the decision-derived H supplied by the API.
  existing.last_application_date = '2026-09-25';
  plan = f.context.pqmGooglePlan_(f.body, f.context.pqmGoogleSnapshot_('sandbox-id'));
  assert.equal(plan.changes.find(x => x.tab === 'ФОП' && x.row === 2).cells[7], before);
});

test('morning I/L planner keeps the evidence pair chronological and preserves Google same-day corrections', () => {
  const cases = [
    {name: 'Google blank', google: '', googleOfficer: '', pqm: '2026-09-20T10:00:00+03:00', pqmOfficer: 'Officer A',
      planned: true, reason: 'google_blank_filled'},
    {name: 'PQM newer', google: '2026-06-05T10:00:00+03:00', googleOfficer: 'Officer B', pqm: '2026-09-20T10:00:00+03:00', pqmOfficer: 'Officer A',
      planned: true, reason: 'pqm_newer_written'},
    {name: 'same pair', google: '2026-09-20T10:00:00+03:00', googleOfficer: 'Officer A', pqm: '2026-09-20T10:00:00+03:00', pqmOfficer: 'Officer A',
      planned: false, reason: 'same_date_equivalent'},
    {name: 'same instant Google officer', google: '2026-09-20T10:00:00+03:00', googleOfficer: 'Officer B', pqm: '2026-09-20T10:00:00+03:00', pqmOfficer: 'Officer A',
      planned: false, reason: 'same_date_google_officer_preserved'},
    {name: 'Google newer', google: '2026-09-25T10:00:00+03:00', googleOfficer: 'Officer B', pqm: '2026-09-20T10:00:00+03:00', pqmOfficer: 'Officer A',
      planned: false, reason: 'google_newer_preserved'},
    {name: 'PQM blank', google: '2026-09-25T10:00:00+03:00', googleOfficer: 'Officer B', pqm: null, pqmOfficer: null,
      planned: false, reason: 'pqm_blank_google_preserved'}
  ];
  for (const item of cases) {
    const f = fixture(), incoming = f.body.items[0];
    f.context.PQM_SANDBOX_FULL_CHUNK_MAX_CELLS = 400;
    incoming.verification_date = item.pqm;
    incoming.verification_officer = item.pqmOfficer;
    incoming.current_manager_name = 'Manager A'; incoming.edr_status_current = 'Зареєстровано';
    incoming.verification_datetime_precision = item.pqm ? 'second' : '';
    incoming.verification_event_type = 'google_clarity';
    setGoogleCell(f, 8, item.google ? f.context.pqmVerificationSerial_(Date.parse(item.google)) : '');
    setGoogleCell(f, 11, item.googleOfficer);
    if (item.name === 'same pair' || item.name === 'same instant Google officer') setGoogleCell(f, 3, 'Manager A');
    const original = clone([f.raw.get('1:2')[8], f.raw.get('1:2')[11]]);
    const preview = f.context.pqmSandboxFullApplyPreview();
    assert.equal(preview.verification_pair_decisions[item.reason], 1, item.name + ' preview reason');
    const plan = f.context.pqmGooglePlan_(f.body, f.context.pqmGoogleSnapshot_('sandbox-id'));
    const change = plan.changes.find(x => x.tab === 'ФОП' && x.row === 2);
    assert.equal(Object.prototype.hasOwnProperty.call(change.cells, '8'), item.planned, item.name + ' I');
    assert.equal(Object.prototype.hasOwnProperty.call(change.cells, '11'), item.planned, item.name + ' L');
    assert.equal(plan.counts[item.reason], 1, item.name + ' reason');
    arm(f, preview);
    const applied = f.context.pqmSandboxFullApply();
    assert.equal(applied.status, 'COMPLETE', item.name);
    if (!item.planned) assert.deepEqual(clone([f.raw.get('1:2')[8], f.raw.get('1:2')[11]]), original, item.name);
    else {
      assert.equal(f.context.pqmVerificationDatetime_(f.raw.get('1:2')[8].effectiveValue.numberValue).value,
        Date.parse(item.pqm), item.name);
      assert.equal(f.raw.get('1:2')[11].effectiveValue.stringValue, item.pqmOfficer, item.name);
    }
  }
});

test('invalid Google/PQM verification dates fail closed before any write', () => {
  for (const origin of ['Google', 'PQM']) {
    const f = fixture();
    f.body.items[0].verification_date = origin === 'PQM' ? 'bad-date' : '2026-09-20';
    f.body.items[0].verification_officer = 'Officer A';
    setGoogleCell(f, 8, origin === 'Google' ? 'bad-date' : f.context.pqmGoogleDate_('2026-09-19'));
    assert.throws(() => f.context.pqmSandboxFullApplyPreview(), /BLOCKED_/);
    assert.equal(f.writes, 0);
  }
});

test('morning writer preserves Google G/J/K/M and explicit no-information E', () => {
  const f = fixture();
  for (const [column, value] of [[6, 'G'], [9, '2026-09-20'], [10, 'K'], [12, 'M'], [4, 'Немає інформації']]) {
    setGoogleCell(f, column, value);
  }
  f.body.items[0].edr_status_current = 'Зареєстровано';
  const before = clone([6, 9, 10, 12, 4].map(c => f.raw.get('1:2')[c]));
  const preview = f.context.pqmSandboxFullApplyPreview();
  arm(f, preview);
  assert.equal(f.context.pqmSandboxFullApply().status, 'COMPLETE');
  assert.deepEqual(clone([6, 9, 10, 12, 4].map(c => f.raw.get('1:2')[c])), before);
  assert.ok(f.requests.flat().every(request => ![6, 9, 10, 12].includes(request.updateCells.range.startColumnIndex)));
});

test('four Apps Script sources parse together; Full Preview is aggregate-only and zero-write', () => {
  const f = fixture(), p = f.context.pqmSandboxFullApplyPreview();
  assert.equal(p.google_writes, 0);
  assert.equal(p.total_pqm_suppliers, 8);
  assert.equal(p.matched, 8);
  assert.equal(p.skipped, 0);
  assert.equal(p.appended + p.conflicts + p.duplicate_keys + p.errors, 0);
  assert.equal(p.total_planned_cells, 24);
  assert.deepEqual(Object.fromEntries(Object.entries(p.changes_by_column)), {C: 8, D: 0, E: 0, F: 8, H: 8, I: 0, L: 0});
  assert.equal(f.writes, 0);
  assert.equal(JSON.stringify(p).includes('verified-name'), false);
  assert.equal(JSON.stringify(p).includes(f.body.items[0].supplier_code), false);
});

test('expanded impact Preview is aggregate-only, zero-write and exposes blockers', () => {
  const f = fixture();
  f.body.items[0].supplier_name = 'old-name';
  f.body.items[0].edr_status_current = 'Зареєстровано';
  f.body.items[0].current_manager_name = 'Updated Manager';
  f.body.items[0].verification_date = '2026-09-23T10:00:00+03:00';
  f.body.items[0].verification_datetime_precision = 'second';
  f.body.items[0].verification_event_type = 'google_clarity';
  f.body.items[0].verification_officer = 'verified officer';
  const impact = f.context.pqmSandboxExpandedImpactPreview();
  assert.deepEqual(Object.fromEntries(Object.entries(impact.changes_by_column)),
    {C: 7, D: 1, E: 1, F: 8, H: 8, I: 1, L: 1});
  assert.equal(impact.total_planned_matched_cells, 27);
  assert.equal(impact.a_writes, 0);
  assert.equal(impact.formulas_touched, 0);
  assert.equal(impact.full_apply_blocked, false);
  assert.equal(f.writes, 0);
  assert.equal(JSON.stringify(impact).includes('verified officer'), false);
  f.body.items.push({...f.body.items[0], supplier_code: 'new-supplier'});
  f.body.count++;
  assert.equal(f.context.pqmSandboxExpandedImpactPreview().full_apply_blocked, true);
  assert.equal(f.writes, 0);
});

test('full preview blocks append, conflict, duplicate and planner error', () => {
  const types = ['appended', 'conflicts', 'duplicate_keys', 'errors'];
  types.forEach(type => {
    const f = fixture(), original = f.context.pqmGooglePlan_;
    f.context.pqmGooglePlan_ = (body, tabs) => {
      const p = original(body, tabs); p.counts[type]++; return p;
    };
    assert.throws(() => f.context.pqmSandboxFullApplyPreview(), /BLOCKED_/);
    assert.equal(f.writes, 0);
  });
});

test('cancelled confirmation and stale digest cause zero writes', () => {
  const f = fixture(), p = f.context.pqmSandboxFullApplyPreview();
  f.setPrompts([response(p.plan_digest)]);
  assert.equal(f.context.pqmSandboxFullApply().google_writes, 0);
  f.setPrompts([response('x'.repeat(43))]); f.confirm('YES');
  assert.throws(() => f.context.pqmSandboxFullApply(), /PLAN_OR_GOOGLE_STATE_CHANGED/);
  assert.equal(f.writes, 0);
});

test('current PQM payload drift invalidates the old Preview before first write', () => {
  const f = fixture(), preview = f.context.pqmSandboxFullApplyPreview();
  f.body.items[0].supplier_name = 'different';
  arm(f, preview);
  assert.throws(() => f.context.pqmSandboxFullApply(), /PLAN_OR_GOOGLE_STATE_CHANGED/);
  assert.equal(f.writes, 0);
});

test('same full business state yields a deterministic digest despite generated_at', () => {
  const f = fixture();
  f.body.generated_at = 'first';
  const a = f.context.pqmSandboxFullApplyPreview();
  f.body.generated_at = 'second';
  const b = f.context.pqmSandboxFullApplyPreview();
  assert.equal(a.plan_digest, b.plan_digest);
  assert.equal(f.writes, 0);
});

test('freshness-marker-only PQM change does not alter Full Preview or create A writes', () => {
  const f = fixture(), before = f.context.pqmSandboxFullApplyPreview();
  f.body.items[0].freshness_marker = 'different';
  const after = f.context.pqmSandboxFullApplyPreview();
  assert.equal(after.plan_digest, before.plan_digest);
  assert.equal(after.total_planned_cells, before.total_planned_cells);
  assert.equal(Object.hasOwn(after.changes_by_column, 'A'), false);
  assert.equal(f.writes, 0);
});

test('state change before first chunk causes zero writes', () => {
  const f = fixture(), p = f.context.pqmSandboxFullApplyPreview();
  const cell = f.raw.get('1:2')[0];
  f.beforeRead(n => {if (n === 1) {cell.userEnteredValue.stringValue = 'edited'; cell.effectiveValue.stringValue = 'edited';}});
  arm(f, p);
  const report = f.context.pqmSandboxFullApply();
  assert.equal(report.status, 'CHUNK_FAILED_NEW_PREVIEW_REQUIRED');
  assert.equal(report.cells_written, 0);
  assert.equal(f.writes, 0);
});

test('state change between chunks stops remaining writes', () => {
  const f = fixture(), p = f.context.pqmSandboxFullApplyPreview();
  f.afterWrite(n => {
    if (n === 1) {const cell = f.raw.get('1:3')[3]; cell.userEnteredValue.stringValue = 'external'; cell.effectiveValue.stringValue = 'external';}
  });
  arm(f, p);
  const report = f.context.pqmSandboxFullApply();
  assert.equal(report.status, 'CHUNK_FAILED_NEW_PREVIEW_REQUIRED');
  assert.equal(report.chunks_completed, 1);
  assert.equal(f.writes, 1);
  assert.ok(report.remaining_cells > 0);
});

test('post-write verification detects changed A and stops further chunks', () => {
  const f = fixture(), p = f.context.pqmSandboxFullApplyPreview();
  f.afterWrite(n => {if (n === 1) f.raw.get('1:2')[0].userEnteredValue.stringValue = 'external';});
  arm(f, p);
  const report = f.context.pqmSandboxFullApply();
  assert.equal(report.status, 'VERIFICATION_FAILED_NEW_PREVIEW_REQUIRED');
  assert.equal(f.writes, 1);
  assert.ok(report.failures > 0);
  assert.equal(report.chunks_completed, 0);
});

test('targeted readback detects validation or note mutation without bulk snapshot metadata', () => {
  for (const property of ['dataValidation', 'note']) {
    const f = fixture(), p = f.context.pqmSandboxFullApplyPreview();
    f.afterWrite(n => {if (n === 1) f.raw.get('1:2')[3][property] = property === 'note'
      ? 'changed note' : {strict: true};});
    arm(f, p);
    const report = f.context.pqmSandboxFullApply();
    assert.equal(report.status, 'VERIFICATION_FAILED_NEW_PREVIEW_REQUIRED');
    assert.equal(report.chunks_completed, 0);
    assert.equal(f.writes, 1);
  }
});

test('ambiguous batch response reports write uncertainty and requires a new Preview', () => {
  const f = fixture(), p = f.context.pqmSandboxFullApplyPreview();
  const original = f.context.Sheets.Spreadsheets.batchUpdate;
  f.context.Sheets.Spreadsheets.batchUpdate = request => {
    original(request);
    throw new Error('simulated response loss');
  };
  arm(f, p);
  const report = f.context.pqmSandboxFullApply();
  assert.equal(report.status, 'WRITE_OR_READBACK_UNCERTAIN_NEW_PREVIEW_REQUIRED');
  assert.equal(report.cells_attempted, 3);
  assert.equal(report.cells_written, 0, 'confirmed count does not claim uncertain writes');
  assert.equal(f.writes, 1, 'mock may have applied despite the exception');
  assert.equal(f.context.pqmSandboxFullApplyPreview().total_planned_cells, p.total_planned_cells - 3);
});

test('successful run writes only C/F/H in bounded chunks and preserves A and other untouched cells', () => {
  const f = fixture(), p = f.context.pqmSandboxFullApplyPreview();
  const untouched = [...f.raw].map(([key, cells]) => [key, cells.map((cell, column) =>
    [0, 1, 3, 4, 6, 8, 9, 10, 11, 12, 13, 14].includes(column) ? clone(cell) : null)]);
  arm(f, p);
  const report = f.context.pqmSandboxFullApply();
  assert.equal(report.status, 'COMPLETE');
  assert.equal(report.cells_written, 24);
  assert.equal(report.cells_verified, 24);
  assert.equal(report.failures, 0);
  assert.equal(report.remaining_cells, 0);
  assert.equal(f.released, 1);
  assert.ok(f.requests.every(batch => batch.length <= 4));
  assert.equal(f.fetches, 2, 'one Preview fetch and one initial Apply fetch; none per chunk');
  assert.equal(f.snapshots, 2, 'one full snapshot in Preview and one at Apply start; none per chunk');
  assert.equal(f.reads, 3 * report.chunks_total, 'two prewrite and one readback targeted reads per chunk');
  assert.deepEqual(Object.keys(report.timing_ms), [
    'initial_pqm_fetch', 'initial_google_guard', 'initial_plan_rebuild',
    'initial_google_phases', 'chunk_pre_read', 'chunk_write', 'chunk_after_read_verification'
  ]);
  assert.ok(Object.entries(report.timing_ms).every(([key, ms]) =>
    key === 'initial_google_phases' || (Number.isFinite(ms) && ms >= 0)));
  untouched.forEach(([key, cells]) => cells.forEach((cell, index) => {
    if (cell) assert.deepEqual(f.raw.get(key)[index], cell);
  }));
  assert.equal(f.context.pqmSandboxFullApplyPreview().total_planned_cells, 0);
});

test('expanded Full Apply writes D/E/I/L with C/F/H and preserves every untouched cell', () => {
  const f = fixture();
  f.context.PQM_SANDBOX_FULL_CHUNK_MAX_CELLS = 400;
  f.body.items[0].edr_status_current = 'Зареєстровано';
  f.body.items[0].current_manager_name = 'Updated Manager';
  f.body.items[0].verification_date = '2026-09-23T10:00:00+03:00';
  f.body.items[0].verification_datetime_precision = 'second';
  f.body.items[0].verification_event_type = 'google_clarity';
  f.body.items[0].verification_officer = 'verified officer';
  const before = clone(f.raw.get('1:2'));
  const preview = f.context.pqmSandboxFullApplyPreview();
  assert.deepEqual(Object.fromEntries(Object.entries(preview.changes_by_column)),
    {C: 8, D: 1, E: 1, F: 8, H: 8, I: 1, L: 1});
  arm(f, preview);
  const result = f.context.pqmSandboxFullApply();
  assert.equal(result.status, 'COMPLETE');
  assert.equal(result.cells_written, 28);
  assert.equal(result.cells_verified, 28);
  assert.equal(f.context.pqmSandboxFullApplyPreview().total_planned_cells, 0);
  for (const column of [0, 1, 6, 9, 10, 12, 13, 14]) {
    assert.deepEqual(f.raw.get('1:2')[column], before[column]);
  }
  assert.ok(f.requests.flat().every(request => [2, 3, 4, 5, 7, 8, 11].includes(request.updateCells.range.startColumnIndex)));
  const dateWrite = f.requests.flat().find(request => request.updateCells.range.startColumnIndex === 8);
  assert.equal(f.context.pqmVerificationDatetime_(dateWrite.updateCells.rows[0].values[0].userEnteredValue.numberValue).value,
    Date.parse('2026-09-23T10:00:00+03:00'));
});

test('blank E/I/L preserve Google values; older date-only I does not block newer PQM evidence', () => {
  const f = fixture();
  const row = f.raw.get('1:2');
  row[4].userEnteredValue.stringValue = 'Припинено'; row[4].effectiveValue.stringValue = 'Припинено';
  row[5].userEnteredValue.stringValue = 'Активний'; row[5].effectiveValue.stringValue = 'Активний';
  row[8].userEnteredValue.numberValue = 46287; row[8].effectiveValue.numberValue = 46287;
  delete row[8].userEnteredValue.stringValue; delete row[8].effectiveValue.stringValue;
  row[8].userEnteredFormat = {numberFormat: {type: 'DATE', pattern: 'dd.MM.yyyy'}};
  row[11].userEnteredValue.stringValue = 'existing'; row[11].effectiveValue.stringValue = 'existing';
  const original = clone([row[4], row[8], row[11]]);
  const preview = f.context.pqmSandboxFullApplyPreview();
  assert.equal(preview.changes_by_column.E + preview.changes_by_column.I + preview.changes_by_column.L, 0);
  arm(f, preview);
  assert.equal(f.context.pqmSandboxFullApply().status, 'COMPLETE');
  assert.deepEqual(clone([row[4], row[8], row[11]]), original);

  const g = fixture();
  g.body.items[0].current_manager_name = 'Manager';
  g.body.items[0].edr_status_current = 'Зареєстровано';
  g.body.items[0].verification_date = '2026-10-01T10:00:00+03:00';
  g.body.items[0].verification_datetime_precision = 'second';
  g.body.items[0].verification_event_type = 'google_clarity';
  g.body.items[0].verification_officer = 'Officer A';
  g.raw.get('1:2')[8].userEnteredValue.numberValue = 46287;
  g.raw.get('1:2')[8].effectiveValue.numberValue = 46287;
  delete g.raw.get('1:2')[8].userEnteredValue.stringValue; delete g.raw.get('1:2')[8].effectiveValue.stringValue;
  g.raw.get('1:2')[8].userEnteredFormat = {numberFormat: {type: 'DATE', pattern: 'dd.MM.yyyy'}};
  g.context.PQM_SANDBOX_FULL_CHUNK_MAX_CELLS = 400;
  const newerPreview = g.context.pqmSandboxFullApplyPreview();
  assert.ok(newerPreview.total_planned_cells > 0,
    'the 2026-10-01 precise PQM check is newer than Google date-only 2026-09-22');
  assert.equal(newerPreview.changes_by_column.I, 1);
  assert.equal(newerPreview.changes_by_column.E, 1);
  arm(g, newerPreview);
  const applied = g.context.pqmSandboxFullApply();
  assert.equal(applied.status, 'COMPLETE', JSON.stringify(applied));
  const resulting = g.raw.get('1:2');
  assert.equal(resulting[4].effectiveValue.stringValue, 'Зареєстровано');
  assert.equal(g.context.pqmVerificationDatetime_(resulting[8].effectiveValue.numberValue).value,
    Date.parse('2026-10-01T10:00:00+03:00'));
});

test('PQM snapshot remains frozen within one Apply; next Preview sees later PQM changes', () => {
  const f = fixture(), preview = f.context.pqmSandboxFullApplyPreview();
  f.afterWrite(n => {if (n === 1) f.body.items[7].supplier_name = 'later-verified-name';});
  arm(f, preview);
  const report = f.context.pqmSandboxFullApply();
  assert.equal(report.status, 'COMPLETE');
  assert.equal(f.fetches, 2, 'no hidden refetch during chunks');
  assert.equal(f.context.pqmSandboxFullApplyPreview().total_planned_cells, 1,
    'fresh Preview plans the one new business difference');
  assert.equal(f.fetches, 3);
});

test('blank PQM C and H preserve Google values', () => {
  const f = fixture(), code = f.body.items[0].supplier_code;
  f.body.items[0].supplier_name = null;
  f.body.items[0].last_application_date = null;
  f.body.items[0].google_sync_last_decided_application_date = null;
  const originalC = clone(f.raw.get('1:2')[2]), originalH = clone(f.raw.get('1:2')[7]);
  const p = f.context.pqmSandboxFullApplyPreview();
  assert.equal(p.total_planned_cells, 22);
  arm(f, p);
  assert.equal(f.context.pqmSandboxFullApply().status, 'COMPLETE');
  assert.deepEqual(f.raw.get('1:2')[2], originalC);
  assert.deepEqual(f.raw.get('1:2')[7], originalH);
  assert.ok(f.body.items.some(x => x.supplier_code === code));
});

test('new Preview after partial success plans only remaining differences', () => {
  const f = fixture(), initial = f.context.pqmSandboxFullApplyPreview();
  f.afterWrite(n => {if (n === 1) {const cell = f.raw.get('1:3')[3]; cell.userEnteredValue.stringValue = 'external'; cell.effectiveValue.stringValue = 'external';}});
  arm(f, initial);
  const stopped = f.context.pqmSandboxFullApply();
  assert.equal(stopped.chunks_completed, 1);
  const next = f.context.pqmSandboxFullApplyPreview();
  assert.equal(next.total_planned_cells, initial.total_planned_cells - 3);
  assert.notEqual(next.plan_digest, initial.plan_digest);
  const changed = f.raw.get('1:3')[3];
  changed.userEnteredValue.stringValue = '';
  changed.effectiveValue.stringValue = '';
  const resumed = f.context.pqmSandboxFullApplyPreview();
  arm(f, resumed);
  assert.equal(f.context.pqmSandboxFullApply().status, 'COMPLETE');
  assert.equal(f.context.pqmSandboxFullApplyPreview().total_planned_cells, 0);
});

test('time budget and lock fail closed before any write', () => {
  const f = fixture(), preview = f.context.pqmSandboxFullApplyPreview();
  f.context.PQM_SANDBOX_FULL_RUN_BUDGET_MS = -1;
  arm(f, preview);
  const stopped = f.context.pqmSandboxFullApply();
  assert.equal(stopped.status, 'TIME_BUDGET_STOP_NEW_PREVIEW_REQUIRED');
  assert.equal(f.writes, 0);
  assert.equal(stopped.remaining_cells, preview.total_planned_cells);
  f.context.LockService = {getScriptLock: () => ({tryLock: () => false})};
  arm(f, preview);
  assert.throws(() => f.context.pqmSandboxFullApply(), /another operation/);
  assert.equal(f.writes, 0);
});

test('default bounded chunks allow at most 200 rows and 400 planned cells', () => {
  const f = fixture();
  f.context.PQM_SANDBOX_FULL_CHUNK_MAX_CELLS = 400;
  f.context.PQM_SANDBOX_FULL_CHUNK_MAX_ROWS = 200;
  const entries = Array.from({length: 301}, (_, index) => ({
    row: index + 2, columns: index % 2 ? [2, 5, 7] : [2]
  }));
  const chunks = f.context.pqmSandboxFullChunks_(entries);
  assert.ok(chunks.length > 1);
  assert.ok(chunks.every(chunk => chunk.length <= 200 &&
    chunk.reduce((n, entry) => n + entry.columns.length, 0) <= 400));
  assert.equal(chunks.flat().length, entries.length);
  assert.equal(f.writes, 0);
});

test('sandbox host and token guards remain the only source of registry credentials', () => {
  const context = {Date, Map, Set, console: {log: () => {}}};
  vm.createContext(context); vm.runInContext(source, context);
  let property = null, fetched = false;
  context.PropertiesService = {getScriptProperties: () => ({getProperty: key => {
    property = key; return 'sandbox-only-token';
  }})};
  context.UrlFetchApp = {fetch: (url, options) => {
    fetched = true;
    assert.equal(new URL(url).host, 'pqm-sandbox.onrender.com');
    assert.equal(options.followRedirects, false);
    return {getResponseCode: () => 200, getContentText: () => JSON.stringify({count: 0, items: []})};
  }};
  context.pqmSandboxFetchRegistry_();
  assert.equal(property, 'PQM_SANDBOX_SUPPLIER_REGISTRY_TOKEN');
  assert.equal(fetched, true);
  context.PQM_SANDBOX_FULL_REGISTRY_URL = 'https://pqm-production-1.onrender.com/api/integrations/suppliers/full-registry';
  fetched = false;
  assert.throws(() => context.pqmSandboxFetchRegistry_(), /endpoint guard/);
  assert.equal(fetched, false);
});

test('Execution API keeps one canonical Preview digest through receipt and guarded Apply', () => {
  const digest = crypto.createHash('sha256').update('synthetic canonical plan').digest('base64url');
  assert.equal(digest.length, 43);
  const f = executionFixture(digest);
  const preview = f.context.pqmSandboxExecution(f.request('preview', 'a'.repeat(32)));
  assert.equal(preview.digest, digest);
  assert.equal(f.applyCalls, 0);

  const first = f.context.pqmSandboxExecution(f.request('apply', 'b'.repeat(32), preview.digest, 0));
  assert.equal(first.digest, digest);
  assert.equal(first.status, 'APPLY_CHUNK_VERIFIED');
  assert.equal(first.more, true);
  assert.equal(f.applyCalls, 1);
  const replayedChunk = f.context.pqmSandboxExecution(f.request('apply', 'b'.repeat(32), preview.digest, 0));
  assert.deepEqual(clone(replayedChunk), clone(first));
  assert.equal(f.applyCalls, 1, 'verified duplicate chunk returns stored receipt without another write');
  const result = f.context.pqmSandboxExecution(f.request('apply', 'b'.repeat(32), preview.digest, 1,'ALL',first.checkpointDigest));
  assert.equal(result.digest, digest);
  assert.equal(result.status, 'COMPLETE');
  assert.equal(f.applyCalls, 2);
  const replay = f.context.pqmSandboxExecution(f.request('apply', 'b'.repeat(32), preview.digest, 1));
  assert.deepEqual(clone(replay), clone(result));
  assert.equal(f.applyCalls, 2);

  const stale = crypto.createHash('sha256').update('different plan').digest('base64url');
  assert.throws(() => f.context.pqmSandboxExecution(f.request('apply', 'c'.repeat(32), stale)),
    /stale execution Preview; zero writes/);
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';
  const lastValue = alphabet.indexOf(digest.at(-1));
  const nonCanonical = digest.slice(0, -1) + alphabet[lastValue ^ 1];
  for (const invalid of ['a'.repeat(64), digest + '=', digest.slice(0, -1), nonCanonical]) {
    assert.equal(f.context.pqmSandboxIsCanonicalDigest_(invalid), false);
    assert.throws(() => f.context.pqmSandboxExecution(f.request('apply', 'd'.repeat(32), invalid)),
      /identity or lifetime rejected/);
  }
  const tampered = f.request('preview', 'e'.repeat(32));
  tampered.signature = 'A'.repeat(43);
  assert.throws(() => f.context.pqmSandboxExecution(tampered), /execution authorization rejected/);
  assert.equal(f.applyCalls, 2);
});

test('Execution API holds after a lost chunk response and never repeats that write', () => {
  const digest = crypto.createHash('sha256').update('synthetic canonical plan').digest('base64url');
  const f = executionFixture(digest);
  const preview = f.context.pqmSandboxExecution(f.request('preview', 'f'.repeat(32)));
  f.failAfterNextWrite();
  assert.throws(() => f.context.pqmSandboxExecution(f.request('apply','a'.repeat(32),preview.digest,0)),
    /Apply may be partial/);
  assert.equal(f.applyCalls,1);
  assert.equal(f.properties.get('PQM_EXECUTION_UNCERTAIN'),'a'.repeat(32));
  assert.throws(() => f.context.pqmSandboxExecution(f.request('apply','a'.repeat(32),preview.digest,0)),
    /outcome uncertain/);
  assert.equal(f.applyCalls,1,'uncertain chunk is not replayed');
});

test('Execution API stops before the next chunk if source or Google state changed', () => {
  const digest = crypto.createHash('sha256').update('synthetic canonical plan').digest('base64url');
  for (const changed of ['source','sheet']) {
    const f=executionFixture(digest), preview=f.context.pqmSandboxExecution(f.request('preview','b'.repeat(32)));
    const first=f.context.pqmSandboxExecution(f.request('apply','c'.repeat(32),preview.digest,0));
    assert.equal(first.status,'APPLY_CHUNK_VERIFIED');
    if(changed==='source')f.setSourceDigest('changed-source');
    else f.setSheetDigest('changed-sheet');
    assert.throws(()=>f.context.pqmSandboxExecution(f.request('apply','c'.repeat(32),preview.digest,1,'ALL',first.checkpointDigest)),
      /source or Google state changed/);
    assert.equal(f.applyCalls,1,'changed inputs block the next write');
    assert.equal(f.properties.has('PQM_EXECUTION_UNCERTAIN'),false,
      'pre-write change is a safe stop, not an uncertain write');
  }
});

test('checkpoint append metadata is verified with one batched Sheets metadata read', () => {
  const f=executionFixture('A'.repeat(43)), calls=[];
  const rows=(count)=>Array.from({length:count},()=>({values:Array.from({length:19},(_,column)=>
    column >= 16 ? {userEnteredFormat:{numberFormat:{pattern:'@'}}} : {})}));
  f.context.Sheets={Spreadsheets:{get:(id,options)=>{
    calls.push({id,options});
    return {sheets:[
      {properties:{title:'ФОП'},data:[{rowData:rows(2),rowMetadata:[{pixelSize:28},{pixelSize:28}]}]},
      {properties:{title:'ЮО'},data:[{rowData:rows(1),rowMetadata:[{pixelSize:28}]}]}
    ]};
  }}};
  const selected=[
    {tab:'ФОП',row:2,cells:{}},{tab:'ФОП',row:3,cells:{}},{tab:'ЮО',row:2,cells:{}}
  ];
  const templates={ФОП:{cells:Array.from({length:15},()=>({})),height:28},
    ЮО:{cells:Array.from({length:15},()=>({})),height:28}};
  f.context.pqmSandboxAppendVerifyMetadata_('sheet-sandbox',selected,templates);
  assert.equal(calls.length,1);
  assert.deepEqual(Array.from(calls[0].options.ranges),["'ФОП'!A2:S3","'ЮО'!A2:S2"]);
  assert.equal(calls[0].options.includeGridData,true);
});

test('bounded checkpoint steps confirm all APPEND pages before starting UPDATE', () => {
  const f=checkpointStepFixture(30,1),props=new Map(),key='PQM_EXECUTION_RUN_'+('c'.repeat(32));
  const record={payloadDigest:'pqm-source-stable',googleDigest:crypto.createHash('sha256')
      .update(JSON.stringify({version:0}),'utf8').digest('base64url'),
    aggregate:{append:0,update:0,batches:0},steps:[],nextChunk:0,inflight:null,state:'ready'};
  props.set(key,JSON.stringify(record));
  const receipt=(status,counts,digest)=>({status,counts,digest});
  function run(index){
    const request={chunkIndex:index,expectedDigest:'Q'.repeat(43)};
    return f.context.pqmSandboxApplyCheckpointStep_('sheet-sandbox',f.loaded(),request,
      {setProperty:(k,v)=>props.set(k,v)},key,record,receipt);
  }
  const first=run(0);
  assert.equal(first.status,'APPLY_CHUNK_VERIFIED');assert.equal(first.counts.append,25);
  assert.equal(f.appendLeft(),5);assert.deepEqual(f.writeKinds(),['append']);
  const second=run(1);
  assert.equal(second.status,'APPLY_CHUNK_VERIFIED');assert.equal(second.counts.append,5);
  assert.equal(f.appendLeft(),0);assert.deepEqual(f.writeKinds(),['append','append']);
  const third=run(2);
  assert.equal(third.status,'COMPLETE_WITH_CONFLICTS');assert.equal(third.phase,'update');
  assert.equal(f.updateLeft(),0);assert.deepEqual(f.writeKinds(),['append','append','update']);
  assert.equal(f.verifiedAppend,30);assert.equal(f.metadataVerifyCalls,2);
  assert.equal(record.aggregate.append,30);assert.equal(record.aggregate.update,1);
  assert.equal(record.steps.length,3);assert.equal(record.state,'complete');
});

test('APPEND_ONLY checkpoint completes append pages without entering UPDATE phase', () => {
  const f=checkpointStepFixture(30,1),props=new Map(),key='PQM_EXECUTION_RUN_'+('e'.repeat(32));
  const record={payloadDigest:'pqm-source-stable',googleDigest:crypto.createHash('sha256')
      .update(JSON.stringify({version:0}),'utf8').digest('base64url'),
    aggregate:{append:0,update:0,batches:0},steps:[],nextChunk:0,inflight:null,state:'ready'};
  props.set(key,JSON.stringify(record));
  const receipt=(status,counts,digest)=>({status,counts,digest});
  function run(index){return f.context.pqmSandboxApplyCheckpointStep_('sheet-sandbox',f.loaded(),
    {chunkIndex:index,expectedDigest:'S'.repeat(43),planScope:'APPEND_ONLY'},
    {setProperty:(k,v)=>props.set(k,v)},key,record,receipt);}
  const first=run(0);
  assert.equal(first.status,'APPLY_CHUNK_VERIFIED');assert.equal(first.phase,'append');
  assert.equal(first.counts.append,25);assert.equal(first.counts.update,0);
  const second=run(1);
  assert.equal(second.status,'COMPLETE_WITH_CONFLICTS');assert.equal(second.phase,'append');
  assert.equal(second.counts.append,5);assert.equal(second.counts.update,0);
  assert.equal(f.appendLeft(),0);assert.equal(f.updateLeft(),1);
  assert.deepEqual(f.writeKinds(),['append','append']);
  assert.equal(record.aggregate.append,30);assert.equal(record.aggregate.update,0);
});

test('shared checkpoint engine bounds UPDATE pages by rows and cells', () => {
  const f=checkpointStepFixture(0,60),props=new Map(),key='PQM_EXECUTION_RUN_'+('d'.repeat(32));
  const record={payloadDigest:'pqm-source-stable',googleDigest:crypto.createHash('sha256')
      .update(JSON.stringify({version:0}),'utf8').digest('base64url'),
    aggregate:{append:0,update:0,batches:0},steps:[],nextChunk:0,inflight:null,state:'ready'};
  const receipt=(status,counts,digest)=>({status,counts,digest});
  function run(index){return f.context.pqmSandboxApplyCheckpointStep_('sheet-sandbox',f.loaded(),
    {chunkIndex:index,expectedDigest:'R'.repeat(43)},{setProperty:(k,v)=>props.set(k,v)},key,record,receipt);}
  const first=run(0);
  assert.equal(first.status,'APPLY_CHUNK_VERIFIED');assert.equal(first.counts.update,50);
  assert.equal(f.updateLeft(),10);assert.deepEqual(f.writeKinds(),['update']);
  const second=run(1);
  assert.equal(second.status,'COMPLETE_WITH_CONFLICTS');assert.equal(second.counts.update,10);
  assert.equal(f.updateLeft(),0);assert.deepEqual(f.writeKinds(),['update','update']);
  assert.equal(record.aggregate.update,60);
});

test('Apps Script v6 normal Preview and APPEND plan retain formula A v1.2 and literal E status', () => {
  const body={count:1,items:[v6Item()]};
  const templateValues=Array(15).fill(''),templateFormulas=Array(15).fill('');
  templateFormulas[0]='=IF(B2="","",1)';
  const f=v6PlannerFixture(body.items,{ФОП:[v6Row(templateValues,templateFormulas,'')],ЮО:[]}),c=f.context;
  c.pqmSandboxFetchRegistry_=()=>clone(body);
  c.pqmGoogleSnapshot_=()=>clone(f.tabs);
  c.pqmSandboxControlledProtectionCheck_=()=>{};
  const preview=c.pqmSandboxFullApplyPreview();
  assert.equal(preview.google_writes,0);
  assert.equal(preview.appended,1,JSON.stringify(c.pqmGooglePlan_(body,f.tabs)));
  assert.equal(preview.updated,0);
  assert.equal(preview.conflicts,0);
  assert.match(preview.plan_digest,/^[A-Za-z0-9_-]{43}$/);

  c.pqmSandboxControlledDigest_=()=> 'synthetic-state-digest';
  c.pqmSandboxFullState_=()=>({payload_digest:'stable-source'});
  const plan=c.pqmGooglePlan_(body,f.tabs);
  const loaded=c.pqmSandboxAppendLoad_('sheet-sandbox',undefined,
    {body,tabs:f.tabs,plan},25);
  assert.equal(loaded.selected.length,1);
  const selected=loaded.selected[0];
  assert.equal(selected.cells[1],'0000000123');
  assert.equal(selected.cells[4],'Немає інформації');
  assert.match(selected.cells[0],/^=IF\(/);
  assert.match(selected.cells[0],/TODAY\(\)/);
  assert.match(selected.cells[0],/REGEXREPLACE/);
  assert.match(selected.cells[0],/ISDATE\(/);
  assert.match(selected.cells[0],/⚪️\|⚪\|➖\|🟠\|🟢\|🔴/);

  assert.throws(()=>c.pqmSandboxAppendRequests_(loaded.selected,loaded.tabs),/durable run journal required/,
    'a planning-only legacy call cannot bypass the durable execution journal');
});

test('Apps Script v6 UPDATE preserves column A and existing E against Немає інформації', () => {
  const item=v6Item({verification_date:'2026-11-01',verification_datetime_precision:'day',
    verification_officer:'Тестовий Керівник'});
  const values=Array(15).fill('');
  values[0]='existing freshness value';values[1]=item.supplier_code;values[2]=item.supplier_name;
  values[3]=item.current_manager_name;values[4]='Зареєстровано';values[5]='Активний';
  values[8]='2026-10-31T12:00:00Z';values[11]=item.verification_officer;
  const formulas=Array(15).fill('');formulas[0]='=TODAY()';
  const f=v6PlannerFixture([item],{ФОП:[v6Row(values,formulas)],ЮО:[]});
  const plan=f.context.pqmGooglePlan_(f.body,f.tabs);
  assert.equal(plan.counts.updated,1);
  assert.equal(plan.counts.conflicts,0);
  assert.equal(plan.changes.length,1);
  assert.equal(plan.changes[0].append,false);
  assert.deepEqual(Object.keys(plan.changes[0].cells),['8']);
  assert.equal(plan.changes[0].cells[8],Date.parse('2026-11-01T00:00:00Z')/86400000+25569,
    'date-only is represented as midnight wall time in Europe/Kyiv');
  assert.equal(plan.changes[0].cells[0],undefined,'UPDATE does not modify Google-owned A');
  assert.equal(plan.changes[0].cells[4],undefined,'Немає інформації does not overwrite a nonblank E');
});

test('Detailed Sandbox Preview renders frozen APPEND, UPDATE cells and conflict reasons without replanning', () => {
  const f=v6PlannerFixture([]),c=f.context;
  c.pqmGooglePlan_=()=>{throw new Error('details must not rerun planner');};
  const formula='=IF(B3="","",TODAY())';
  const loaded={body:{items:[{supplier_code:'000001',supplier_name:'Test append'},
      {supplier_code:'000002',supplier_name:'Test update'}]},
    tabs:{ФОП:{rows:[{values:Array(15).fill(''),codeDisplay:'000002'}]},ЮО:{rows:[]}},
    plan:{counts:{appended:1,updated:1,conflicts:1,errors:1},changes:[
      {tab:'ФОП',row:3,append:true,cells:{0:formula,1:'000001',2:'New supplier'}},
      {tab:'ФОП',row:2,append:false,cells:{4:'Зареєстровано'}}],
      conflicts:[{supplier_code:'000003',tab:'ЮО',reason:'routing_mismatch'}],
      errors:[{supplier_code:'000004',tab:'ФОП',reason:'invalid_date'}]},
    plan_digest:'P'.repeat(43),append_only_digest:'A'.repeat(43),
    state:{payload_digest:'source-fixture'}};
  loaded.tabs.ФОП.rows[0].values[2]='Old supplier';loaded.tabs.ФОП.rows[0].values[4]='Припинено';
  const details=c.pqmSandboxFullPreviewDetails_(loaded);
  assert.equal(details.counts.append,1);assert.equal(details.counts.update,1);
  assert.equal(details.appends[0].operation,'APPEND');
  assert.equal(details.appends[0].cells.find(cell=>cell.column==='A').formula,true);
  assert.equal(details.appends[0].cells.find(cell=>cell.column==='B').new_value,'000001');
  assert.deepEqual(Array.from(details.updates[0].cells,cell=>cell.column),['E']);
  assert.equal(details.updates[0].cells[0].old_value,'Припинено');
  assert.equal(details.conflicts[0].explanation,'Тип постачальника не відповідає вкладці');
  assert.equal(details.errors[0].explanation,'Некоректна дата в даних PQM');
});

test('Apps Script v6 persists real checkpoint state and read-only resume preflight across calls', () => {
  const digest=crypto.createHash('sha256').update('v6 preview plan').digest('base64url');
  const f=realCheckpointExecutionFixture(digest,30),id='e'.repeat(32);
  const preview=f.context.pqmSandboxExecution(f.request('preview','f'.repeat(32)));
  assert.equal(preview.status,'PREVIEW');assert.equal(preview.digest,digest);assert.equal(f.writes,0);
  let first;try{first=f.context.pqmSandboxExecution(f.request('apply',id,digest,0,'APPEND_ONLY'));}
  catch(error){assert.fail(String(error)+'; internal='+f.context.lastCheckpointError);}
  assert.equal(first.status,'APPLY_CHUNK_VERIFIED');assert.equal(first.more,true);
  assert.equal(first.counts.append,25);assert.equal(first.planScope,'APPEND_ONLY');
  assert.match(first.checkpointDigest,/^[A-Za-z0-9_-]{43}$/);assert.equal(f.remaining,5);assert.equal(f.writes,1);
  const stored=JSON.parse(f.properties.get('PQM_EXECUTION_RUN_'+id));
  assert.equal(stored.state,'ready');assert.equal(stored.nextChunk,1);assert.equal(stored.steps[0].verified,true);
  assert.equal(f.context.pqmSandboxFullLoad_().state.google_digest,stored.googleDigest,'the read-only source snapshot matches the checkpoint');
  const beforeReadOnly=JSON.stringify([...f.properties]);
  const checked=f.context.pqmSandboxExecution(f.request('resume_check',id,digest,1,'APPEND_ONLY',first.checkpointDigest));
  assert.equal(checked.status,'RESUME_READY');assert.equal(checked.counts.append,5);assert.equal(checked.counts.update,0);
  assert.deepEqual(clone(checked.planDetails.updates),[]);assert.equal(checked.checkpointDigest,first.checkpointDigest);
  assert.equal(f.writes,1);assert.equal(JSON.stringify([...f.properties]),beforeReadOnly,'read-only preflight does not mutate Script Properties');
  const replayedFirst=f.context.pqmSandboxExecution(f.request('apply',id,digest,0,'APPEND_ONLY'));
  assert.equal(replayedFirst.checkpointDigest,first.checkpointDigest);assert.equal(f.writes,1,'receipt replay does not repeat an append');
  const second=f.context.pqmSandboxExecution(f.request('apply',id,digest,1,'APPEND_ONLY',first.checkpointDigest));
  assert.equal(second.status,'COMPLETE');assert.equal(second.more,false);
  assert.equal(second.counts.append,30);assert.equal(second.counts.update,0);assert.equal(second.planScope,'APPEND_ONLY');
  assert.equal(f.remaining,0);assert.equal(f.writes,2);
  const replay=f.context.pqmSandboxExecution(f.request('apply',id,digest,1,'APPEND_ONLY',first.checkpointDigest));
  assert.deepEqual(clone(replay),clone(second));assert.equal(f.writes,2,'verified replay returns receipt without repeating a write');
});

test('351 APPEND rows fit the durable checkpoint chain and finish in 15 verified pages', () => {
  const digest=crypto.createHash('sha256').update('351 append checkpoint fixture').digest('base64url');
  const f=realCheckpointExecutionFixture(digest,351),id='d'.repeat(32);
  f.context.pqmSandboxExecution(f.request('preview','c'.repeat(32)));
  let checkpoint=null,result;
  for(let chunk=0;chunk<15;chunk++){
    result=f.context.pqmSandboxExecution(f.request('apply',id,digest,chunk,'APPEND_ONLY',checkpoint));
    if(chunk<14){assert.equal(result.status,'APPLY_CHUNK_VERIFIED');assert.equal(result.more,true);}
    checkpoint=result.checkpointDigest;
  }
  assert.equal(result.status,'COMPLETE');assert.equal(result.counts.append,351);assert.equal(result.counts.update,0);
  assert.equal(f.remaining,0);assert.equal(f.writes,15);
  const stored=JSON.parse(f.properties.get('PQM_EXECUTION_RUN_'+id));
  assert.equal(stored.steps.length,15);assert.ok(Buffer.byteLength(JSON.stringify(stored))<8000);
});

test('uncertain or changed-source APPEND_ONLY checkpoint cannot resume', () => {
  const digest=crypto.createHash('sha256').update('resume hold fixture').digest('base64url');
  const uncertain=realCheckpointExecutionFixture(digest,30),id='6'.repeat(32);
  uncertain.context.pqmSandboxExecution(uncertain.request('preview','7'.repeat(32)));
  uncertain.loseNextResponse();
  assert.throws(()=>uncertain.context.pqmSandboxExecution(uncertain.request('apply',id,digest,0,'APPEND_ONLY')),/Apply may be partial/);
  assert.throws(()=>uncertain.context.pqmSandboxExecution(uncertain.request('resume_check',id,digest,1,'APPEND_ONLY',digest)),/outcome uncertain/);
  assert.equal(uncertain.writes,1);

  const stale=realCheckpointExecutionFixture(digest,30),staleId='8'.repeat(32);
  stale.context.pqmSandboxExecution(stale.request('preview','9'.repeat(32)));
  const first=stale.context.pqmSandboxExecution(stale.request('apply',staleId,digest,0,'APPEND_ONLY'));
  stale.setSheetDigest('out-of-band-change');
  assert.throws(()=>stale.context.pqmSandboxExecution(stale.request('resume_check',staleId,digest,1,'APPEND_ONLY',first.checkpointDigest)),/changed since the verified checkpoint/);
  assert.equal(stale.writes,1,'stale Google state stops before another write');

  const staleSource=realCheckpointExecutionFixture(digest,30),sourceId='9'.repeat(32);
  staleSource.context.pqmSandboxExecution(staleSource.request('preview','0'.repeat(32)));
  const sourceFirst=staleSource.context.pqmSandboxExecution(staleSource.request('apply',sourceId,digest,0,'APPEND_ONLY'));
  staleSource.setSourceDigest('out-of-band-source-change');
  assert.throws(()=>staleSource.context.pqmSandboxExecution(staleSource.request('resume_check',sourceId,digest,1,'APPEND_ONLY',sourceFirst.checkpointDigest)),/sources or Google Sheets changed/);
  assert.equal(staleSource.writes,1,'stale source stops before another write');
});

test('Apps Script v6 does not replay a chunk when Execution API loses its response', () => {
  const digest=crypto.createHash('sha256').update('v6 uncertain plan').digest('base64url');
  const f=realCheckpointExecutionFixture(digest,30),id='a'.repeat(32);
  f.context.pqmSandboxExecution(f.request('preview','b'.repeat(32)));
  f.loseNextResponse();
  assert.throws(()=>f.context.pqmSandboxExecution(f.request('apply',id,digest,0)),/Apply may be partial/);
  assert.equal(f.writes,1);assert.equal(f.remaining,5);
  assert.equal(f.properties.get('PQM_EXECUTION_UNCERTAIN'),id);
  assert.throws(()=>f.context.pqmSandboxExecution(f.request('apply',id,digest,0)),/outcome uncertain/);
  assert.equal(f.writes,1,'uncertain chunk remains held and is never replayed');
});
