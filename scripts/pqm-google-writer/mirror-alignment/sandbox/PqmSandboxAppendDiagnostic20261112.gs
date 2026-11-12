/* Additive, signed, read-only APPEND_ONLY audit endpoint. */
function pqmSandboxAppendDiagnostic20261112(envelope) {
  if (!envelope || typeof envelope.payload!=='string' || envelope.payload.length>32768 ||
      typeof envelope.signature!=='string') throw new Error('PQM: invalid APPEND diagnostic envelope');
  var properties=PropertiesService.getScriptProperties();
  var secret=properties.getProperty('PQM_EXECUTION_SHARED_SECRET');
  if (!secret || secret.length<32) throw new Error('PQM: execution authorization not configured');
  var expectedSignature=Utilities.base64EncodeWebSafe(
    Utilities.computeHmacSha256Signature(envelope.payload,secret,Utilities.Charset.UTF_8)).replace(/=+$/,'');
  var different=expectedSignature.length^envelope.signature.length;
  for (var i=0;i<expectedSignature.length;i++)
    different|=expectedSignature.charCodeAt(i)^(envelope.signature.charCodeAt(i)||0);
  if (different) throw new Error('PQM: execution authorization rejected');
  var request;
  try { request=JSON.parse(envelope.payload); } catch (_) { throw new Error('PQM: invalid APPEND diagnostic payload'); }
  var keys=['action','actor','chunkDigest','chunkId','chunkIndex','contract','detailsDigest','environment',
    'expectedDigest','expiresAt','fullPlanDigest','issuedAt','planId','planScope','requestId','scriptId',
    'sourceDigest','spreadsheetId','targetIdentities','totalAppendCount','trigger'];
  if (!request || Object.keys(request).sort().join('|')!==keys.sort().join('|') ||
      request.action!=='diagnose_append_plan' || request.environment!=='SANDBOX' ||
      request.planScope!=='APPEND_ONLY' || request.trigger!=='manual' ||
      request.contract!=='pqm-mirror-datetime-v1' ||
      request.scriptId!==PQM_MIRROR_ENV.scriptId || ScriptApp.getScriptId()!==PQM_MIRROR_ENV.scriptId ||
      request.spreadsheetId!==PQM_MIRROR_ENV.spreadsheetId ||
      !/^[0-9a-f]{32}$/.test(request.requestId||'') || request.planId!==request.requestId ||
      request.requestId==='592128d9837d4b71bbeb330ef8aabf4b' ||
      typeof request.actor!=='string' || !request.actor.trim() || request.actor.length>128 ||
      !Number.isInteger(request.issuedAt) || !Number.isInteger(request.expiresAt) ||
      request.issuedAt>Math.floor(Date.now()/1000)+30 || request.expiresAt<Math.floor(Date.now()/1000) ||
      request.expiresAt-request.issuedAt>300 || request.expiresAt<request.issuedAt ||
      !pqmSandboxIsCanonicalDigest_(request.expectedDigest) ||
      !pqmSandboxIsCanonicalDigest_(request.detailsDigest) ||
      !pqmSandboxIsCanonicalDigest_(request.fullPlanDigest) ||
      !pqmSandboxIsCanonicalDigest_(request.sourceDigest) ||
      !pqmSandboxIsCanonicalDigest_(request.chunkDigest) ||
      !/^[0-9a-f]{32}$/.test(request.chunkId||'') || request.chunkIndex!==0 ||
      !Number.isInteger(request.totalAppendCount) || request.totalAppendCount<1 ||
      request.totalAppendCount>10000 || !Array.isArray(request.targetIdentities) ||
      request.targetIdentities.length!==request.totalAppendCount || request.targetIdentities.length>10000)
    throw new Error('PQM: APPEND diagnostic binding rejected');
  var seen={};
  request.targetIdentities.forEach(function(item) {
    if (!item || Object.keys(item).sort().join(',')!=='code,row,tab' ||
        ['ФОП','ЮО'].indexOf(item.tab)<0 || typeof item.code!=='string' ||
        !/^\d{8,10}$/.test(item.code) || !Number.isInteger(item.row) || item.row<2 || seen[item.code])
      throw new Error('PQM: APPEND diagnostic target rejected');
    seen[item.code]=true;
  });
  if (PQM_EXECUTION_CONTEXT_) throw new Error('PQM: nested execution rejected');
  var lock=LockService.getScriptLock();
  if (!lock.tryLock(0)) return pqmSandboxAppendDiagnosticBlocked_(request,'EXECUTION_LOCK_BUSY');
  try {
    var spreadsheet=SpreadsheetApp.openById(PQM_MIRROR_ENV.spreadsheetId);
    if (!spreadsheet || spreadsheet.getId()!==PQM_MIRROR_ENV.spreadsheetId)
      return pqmSandboxAppendDiagnosticBlocked_(request,'SPREADSHEET_IDENTITY_REJECTED');
    PQM_EXECUTION_CONTEXT_={spreadsheet:spreadsheet};
    var key='PQM_EXECUTION_RUN_'+request.requestId;
    return pqmSandboxDiagnoseAppendPlan_(request.spreadsheetId,properties,key,
      properties.getProperty(key),request);
  } finally {
    PQM_EXECUTION_CONTEXT_=null;
    lock.releaseLock();
  }
}

function pqmSandboxAppendDiagnosticBlocked_(request,code) {
  var total=request.totalAppendCount;
  return {environment:'SANDBOX',scriptId:request.scriptId,spreadsheetId:request.spreadsheetId,
    contract:request.contract,requestId:request.requestId,status:'BLOCKED',planScope:'APPEND_ONLY',
    digest:request.expectedDigest,detailsDigest:request.detailsDigest,fullPlanDigest:request.fullPlanDigest,
    sourceDigest:request.sourceDigest,chunkId:request.chunkId,chunkDigest:request.chunkDigest,
    planId:request.planId,chunkIndex:0,
    counts:{planned:total,confirmed:0,missing:0,conflict:0,unverified:total,remaining:total},
    reasonCodes:[code],manifestBinding:'BLOCKED',firstChunkRecoveryEvidence:false,readOnly:true};
}

function pqmSandboxDiagnoseAppendPlan_(id,properties,key,stored,request) {
  var targets=request.targetIdentities,total=targets.length;
  function summary(status,counts,reasons,manifestBinding,firstChunkReady) {
    return {environment:'SANDBOX',scriptId:request.scriptId,spreadsheetId:request.spreadsheetId,
      contract:request.contract,requestId:request.requestId,status:status,planScope:'APPEND_ONLY',
      digest:request.expectedDigest,detailsDigest:request.detailsDigest,fullPlanDigest:request.fullPlanDigest,
      sourceDigest:request.sourceDigest,chunkId:request.chunkId,chunkDigest:request.chunkDigest,
      planId:request.planId,chunkIndex:0,counts:counts,reasonCodes:reasons,
      manifestBinding:manifestBinding,firstChunkRecoveryEvidence:firstChunkReady===true,readOnly:true};
  }
  function allUnverified(code) {
    return summary('BLOCKED',{planned:total,confirmed:0,missing:0,conflict:0,unverified:total,remaining:total},
      [code],'BLOCKED',false);
  }
  if (!stored || properties.getProperty('PQM_EXECUTION_UNCERTAIN')!==request.requestId)
    return allUnverified('UNCERTAINTY_MARKER_MISMATCH');
  var record;
  try { record=JSON.parse(stored); } catch (_) { return allUnverified('RUN_RECORD_INVALID'); }
  if (record.state!=='uncertain' || record.chunkJournalVersion!==1 || record.planScope!=='APPEND_ONLY' ||
      record.runId!==request.requestId || record.planId!==request.requestId ||
      record.digest!==request.expectedDigest || record.inflight!==0 || record.uncertainChunk!==0 ||
      record.nextChunk!==0 || !Array.isArray(record.steps) || record.steps.length!==0 ||
      !record.inflightManifest) return allUnverified('RUN_RECORD_BINDING_MISMATCH');
  var manifest;
  try { manifest=pqmExecutionCheckpointResolveManifest_(properties,request.requestId,record.inflightManifest); }
  catch (_) { return allUnverified('MANIFEST_READ_INCOMPLETE'); }
  if (!manifest || manifest.chunkIndex!==0 || manifest.chunkId!==request.chunkId ||
      manifest.chunkDigest!==request.chunkDigest || manifest.planId!==request.requestId ||
      manifest.runId!==request.requestId || !Array.isArray(manifest.rows) ||
      manifest.rows.length!==Math.min(25,total)) return allUnverified('MANIFEST_BINDING_MISMATCH');
  var loaded;
  try { loaded=pqmSandboxFullLoad_(id); } catch (_) { return allUnverified('SHEET_OR_SOURCE_READ_INCOMPLETE'); }
  if (!loaded || !loaded.state || loaded.state.payload_digest!==request.sourceDigest)
    return allUnverified('SOURCE_BINDING_MISMATCH');
  var locations=new Map(targets.map(function(item){return [item.code,[]];}));
  PQM_GOOGLE_TABS.forEach(function(tabName) {
    (loaded.tabs[tabName].rows||[]).forEach(function(row,index) {
      var code=String(row.codeDisplay||'').trim();
      if (locations.has(code)) locations.get(code).push({tab:tabName,row:index+2,record:row});
    });
  });
  var blankTabs=JSON.parse(JSON.stringify(loaded.tabs));
  // Reconstruct the pre-Apply Preview using only the durable first-chunk
  // destinations. Never blank other planned rows: a later chunk may have
  // been written, and masking it could make an inconsistent plan look valid.
  manifest.rows.forEach(function(item) {
    var tab=blankTabs[item.tab];
    if (tab && Number.isInteger(item.row) && item.row>=2 && item.row<=tab.rows.length+1)
      tab.rows[item.row-2]={values:Array(15).fill(''),formulas:Array(15).fill(''),
        codeDisplay:'',dateFormat:'',verificationDateFormat:''};
  });
  PQM_GOOGLE_TABS.forEach(function(tabName) {
    var rows=blankTabs[tabName].rows;
    while (rows.length) {
      var last=rows[rows.length-1];
      if (String(last.codeDisplay||'').trim() || last.values.some(function(v){return !pqmGoogleBlank_(v);}) ||
          last.formulas.some(function(v){return !pqmGoogleBlank_(v);})) break;
      rows.pop();
    }
  });
  var rebuiltPlan=pqmGooglePlan_(loaded.body,blankTabs);
  if (pqmSandboxFullBlocked_(rebuiltPlan)) return allUnverified('REBUILT_PLAN_UNSAFE');
  var rebuiltState=pqmSandboxFullState_(loaded.body,blankTabs,rebuiltPlan);
  var rebuiltFullDigest=pqmSandboxFullDigest_(rebuiltState);
  var appendChanges=rebuiltPlan.changes.filter(function(change){return change.append;}).map(function(change){
    return {tab:change.tab,row:change.row,append:true,cells:change.cells};
  });
  var rebuiltAppendDigest=pqmSandboxFullDigest_({version:1,state:{scope:'APPEND_ONLY',
    parent_plan_digest:rebuiltFullDigest,payload_digest:rebuiltState.payload_digest,
    google_digest:rebuiltState.google_digest,changes_digest:pqmSandboxControlledDigest_(appendChanges),
    counts:{append:rebuiltPlan.counts.appended,update:0,conflict:rebuiltPlan.counts.conflicts,
      error:rebuiltPlan.counts.errors}}});
  if (rebuiltFullDigest!==request.fullPlanDigest || rebuiltAppendDigest!==request.expectedDigest ||
      rebuiltPlan.counts.appended!==total || appendChanges.length!==total)
    return allUnverified('PREVIEW_RECONSTRUCTION_MISMATCH');
  var expectedByCode=new Map();
  appendChanges.forEach(function(change){expectedByCode.set(String(change.cells[1]||'').trim(),change);});
  var outcome=Array(total).fill(null);
  targets.forEach(function(target,index) {
    var found=locations.get(target.code)||[],expected=expectedByCode.get(target.code);
    if (!found.length) { outcome[index]='missing';return; }
    if (found.length!==1 || found[0].tab!==target.tab || found[0].row!==target.row ||
        !expected || expected.tab!==target.tab || expected.row!==target.row) { outcome[index]='conflict';return; }
    var actual=found[0].record,mismatch=false;
    Object.keys(expected.cells).forEach(function(rawColumn) {
      var column=Number(rawColumn),want=expected.cells[rawColumn];
      if (column===0) {
        if (String(actual.formulas[column]||'')!==String(want||'')) mismatch=true;
      } else if (pqmSandboxExecutionComparableValue_(actual.values[column],column)!==
                 pqmSandboxExecutionComparableValue_(want,column)) mismatch=true;
    });
    [6,9,10,12,13,14].forEach(function(column){if(!pqmGoogleBlank_(actual.values[column]))mismatch=true;});
    if (mismatch) outcome[index]='conflict';
  });
  var present=[];outcome.forEach(function(value,index){if(value===null)present.push(index);});
  var serviceByTab={};
  try {
    var ranges=[],rangeInfo=[];
    PQM_GOOGLE_TABS.forEach(function(tabName) {
      var rows=present.map(function(index){return targets[index];}).filter(function(item){return item.tab===tabName;});
      if (!rows.length) return;
      var first=Math.min.apply(null,rows.map(function(item){return item.row;}));
      var last=Math.max.apply(null,rows.map(function(item){return item.row;}));
      ranges.push("'"+tabName.replace(/'/g,"''")+"'!Q"+first+':S'+last);
      rangeInfo.push({tab:tabName,first:first});
    });
    var response=ranges.length?Sheets.Spreadsheets.Values.batchGet(id,
      {ranges:ranges,valueRenderOption:'UNFORMATTED_VALUE'}):{valueRanges:[]};
    if (!response || !Array.isArray(response.valueRanges) || response.valueRanges.length!==ranges.length)
      return allUnverified('SERVICE_METADATA_READ_INCOMPLETE');
    rangeInfo.forEach(function(info,index){serviceByTab[info.tab]={first:info.first,
      rows:(response.valueRanges[index]||{}).values||[]};});
  } catch (_) { return allUnverified('SERVICE_METADATA_READ_INCOMPLETE'); }
  targets.forEach(function(target,index) {
    if (outcome[index]!==null) return;
    var range=serviceByTab[target.tab],values=range&&range.rows[target.row-range.first]||[];
    var addedAt=String(values[0]||''),planId=String(values[1]||''),runId=String(values[2]||'');
    if (planId!==request.requestId || runId!==request.requestId ||
        !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$/.test(addedAt)) {
      outcome[index]='conflict';return;
    }
    if (index<manifest.rows.length) {
      var service=manifest.rows[index].serviceMetadata;
      if (!service || addedAt!==service.addedAt || planId!==service.planId || runId!==service.runId)
        outcome[index]='conflict';
    }
  });
  var manifestBinding=true;
  manifest.rows.forEach(function(item,index) {
    var target=targets[index],change=target&&expectedByCode.get(target.code);
    if (!target || !change || item.tab!==target.tab || item.row!==target.row || item.code!==target.code ||
        item.cellsDigest!==pqmSandboxControlledDigest_(change.cells) || item.formulaA!==change.cells[0] ||
        !item.serviceMetadata || item.serviceMetadata.planId!==request.requestId ||
        item.serviceMetadata.runId!==request.requestId) manifestBinding=false;
  });
  if (!manifestBinding) for (var m=0;m<manifest.rows.length;m++)
    if (outcome[m]===null) outcome[m]='unverified';
  var groups=[];
  PQM_GOOGLE_TABS.forEach(function(tabName) {
    var indices=[];
    outcome.forEach(function(value,index){if(value===null&&targets[index].tab===tabName)indices.push(index);});
    indices.sort(function(a,b){return targets[a].row-targets[b].row;});
    var group=[];
    indices.forEach(function(index){
      if(group.length&&targets[index].row!==targets[group[group.length-1]].row+1){groups.push(group);group=[];}
      group.push(index);
    });
    if(group.length)groups.push(group);
  });
  groups.forEach(function(indices){
    try {
      var selected=indices.map(function(index){return expectedByCode.get(targets[index].code);});
      var tab=selected[0].tab,template=pqmSandboxAppendRowMetadata_(id,tab,selected[0].row-1);
      var templates={};templates[tab]=template;pqmSandboxAppendVerifyMetadata_(id,selected,templates);
    } catch (_) { indices.forEach(function(index){outcome[index]='unverified';}); }
  });
  var counts={planned:total,confirmed:0,missing:0,conflict:0,unverified:0,remaining:0};
  outcome.forEach(function(value){counts[value||'confirmed']++;});
  counts.remaining=counts.planned-counts.confirmed;
  var reasons=[];
  if(!manifestBinding)reasons.push('MANIFEST_BINDING_MISMATCH');
  if(counts.missing)reasons.push('TARGET_ROWS_MISSING');
  if(counts.conflict)reasons.push('TARGET_CONFLICT');
  if(counts.unverified)reasons.push('READBACK_OR_METADATA_UNVERIFIED');
  var firstReady=manifestBinding&&manifest.rows.length===Math.min(25,total)&&
    outcome.slice(0,manifest.rows.length).every(function(value){return value===null;});
  return summary(counts.unverified?'READ_INCOMPLETE':'DIAGNOSED',counts,reasons,
    manifestBinding?'PASS':'BLOCKED',firstReady);
}
