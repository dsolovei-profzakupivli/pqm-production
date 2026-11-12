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
  var baseKeys=['action','actor','contract','detailsDigest','environment','expectedDigest','expiresAt',
    'fullPlanDigest','issuedAt','planId','planScope','requestId','scriptId','sourceDigest',
    'spreadsheetId','totalAppendCount','trigger'];
  var recoveryKeys=baseKeys.concat(['chunkDigest','chunkId','chunkIndex','diagnosticMode','targetIdentities']);
  var auditKeys=baseKeys.concat(['auditTargets','auditTargetsDigest','chunkIndex','diagnosticMode']);
  var auditFieldKeys=baseKeys.concat(['auditFieldTargets','auditFieldTargetsDigest','chunkIndex','diagnosticMode']);
  var auditMode=request && request.diagnosticMode==='audit';
  var auditFieldsMode=request && request.diagnosticMode==='audit_fields';
  var keys=auditMode?auditKeys:(auditFieldsMode?auditFieldKeys:recoveryKeys);
  if (!request || Object.keys(request).sort().join('|')!==keys.sort().join('|') ||
      request.action!=='diagnose_append_plan' ||
      request.diagnosticMode!==(auditMode?'audit':(auditFieldsMode?'audit_fields':'recovery')) ||
      request.environment!=='SANDBOX' ||
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
      request.chunkIndex!==0 || !Number.isInteger(request.totalAppendCount) || request.totalAppendCount<1 ||
      request.totalAppendCount>10000 || (auditMode && (!Array.isArray(request.auditTargets) ||
        request.auditTargets.length!==request.totalAppendCount ||
        !pqmSandboxIsCanonicalDigest_(request.auditTargetsDigest) ||
        pqmSandboxControlledDigest_(request.auditTargets)!==request.auditTargetsDigest)) ||
      (auditFieldsMode && (!Array.isArray(request.auditFieldTargets) ||
        request.auditFieldTargets.length<1 || request.auditFieldTargets.length>25 ||
        !pqmSandboxIsCanonicalDigest_(request.auditFieldTargetsDigest) ||
        pqmSandboxControlledDigest_(request.auditFieldTargets)!==request.auditFieldTargetsDigest)) ||
      (!auditMode && !auditFieldsMode && (!pqmSandboxIsCanonicalDigest_(request.chunkDigest) ||
        !/^[0-9a-f]{32}$/.test(request.chunkId||'') || !Array.isArray(request.targetIdentities) ||
        request.targetIdentities.length!==request.totalAppendCount || request.targetIdentities.length>10000)))
    throw new Error('PQM: APPEND diagnostic binding rejected');
  if (auditMode) pqmSandboxValidateAppendAuditTargets_(request.auditTargets);
  else if (auditFieldsMode) pqmSandboxValidateAppendAuditFieldTargets_(request.auditFieldTargets);
  else {
    var seen={};
    request.targetIdentities.forEach(function(item) {
      if (!item || Object.keys(item).sort().join(',')!=='code,row,tab' ||
          ['ФОП','ЮО'].indexOf(item.tab)<0 || typeof item.code!=='string' ||
          !/^\d{8,10}$/.test(item.code) || !Number.isInteger(item.row) || item.row<2 || seen[item.code])
        throw new Error('PQM: APPEND diagnostic target rejected');
      seen[item.code]=true;
    });
  }
  if (PQM_EXECUTION_CONTEXT_) throw new Error('PQM: nested execution rejected');
  var lock=LockService.getScriptLock();
  if (!lock.tryLock(0)) return pqmSandboxAppendDiagnosticBlocked_(request,'EXECUTION_LOCK_BUSY');
  try {
    var spreadsheet=SpreadsheetApp.openById(PQM_MIRROR_ENV.spreadsheetId);
    if (!spreadsheet || spreadsheet.getId()!==PQM_MIRROR_ENV.spreadsheetId)
      return pqmSandboxAppendDiagnosticBlocked_(request,'SPREADSHEET_IDENTITY_REJECTED');
    PQM_EXECUTION_CONTEXT_={spreadsheet:spreadsheet};
    if (auditMode) return pqmSandboxAuditAppendRowsReadOnly_(request.spreadsheetId,request);
    if (auditFieldsMode) return pqmSandboxAuditAppendFieldsReadOnly_(request.spreadsheetId,request);
    var key='PQM_EXECUTION_RUN_'+request.requestId;
    return pqmSandboxDiagnoseAppendPlan_(request.spreadsheetId,properties,key,
      properties.getProperty(key),request);
  } finally {
    PQM_EXECUTION_CONTEXT_=null;
    lock.releaseLock();
  }
}

function pqmSandboxAppendDiagnosticBlocked_(request,code) {
  if (request.diagnosticMode==='audit') {
    var pageTotal=request.totalAppendCount;
    return {environment:'SANDBOX',scriptId:request.scriptId,spreadsheetId:request.spreadsheetId,
      contract:request.contract,requestId:request.requestId,status:'READ_INCOMPLETE',diagnosticMode:'audit',
      planScope:'APPEND_ONLY',digest:request.expectedDigest,detailsDigest:request.detailsDigest,
      fullPlanDigest:request.fullPlanDigest,sourceDigest:request.sourceDigest,planId:request.planId,
      auditTargetsDigest:request.auditTargetsDigest,
      counts:{planned:pageTotal,confirmed:0,missing:0,conflict:0,unverified:pageTotal,remaining:pageTotal},
      reasonCodes:[code],readOnly:true};
  }
  if (request.diagnosticMode==='audit_fields') {
    return {environment:'SANDBOX',scriptId:request.scriptId,spreadsheetId:request.spreadsheetId,
      contract:request.contract,requestId:request.requestId,status:'READ_INCOMPLETE',diagnosticMode:'audit_fields',
      planScope:'APPEND_ONLY',digest:request.expectedDigest,detailsDigest:request.detailsDigest,
      fullPlanDigest:request.fullPlanDigest,sourceDigest:request.sourceDigest,planId:request.planId,
      auditFieldTargetsDigest:request.auditFieldTargetsDigest,
      conflicts:(request.auditFieldTargets||[]).map(function(item){return {code:item[1],status:'UNVERIFIED',fields:[]};}),
      readOnly:true};
  }
  var total=request.totalAppendCount;
  return {environment:'SANDBOX',scriptId:request.scriptId,spreadsheetId:request.spreadsheetId,
    contract:request.contract,requestId:request.requestId,status:'BLOCKED',planScope:'APPEND_ONLY',
    digest:request.expectedDigest,detailsDigest:request.detailsDigest,fullPlanDigest:request.fullPlanDigest,
    sourceDigest:request.sourceDigest,chunkId:request.chunkId,chunkDigest:request.chunkDigest,
    planId:request.planId,chunkIndex:0,
    counts:{planned:total,confirmed:0,missing:0,conflict:0,unverified:total,remaining:total},
    reasonCodes:[code],manifestBinding:'BLOCKED',firstChunkRecoveryEvidence:false,readOnly:true};
}

function pqmSandboxValidateAppendAuditTargets_(targets) {
  var seen={};
  targets.forEach(function(item) {
    if (!Array.isArray(item) || item.length!==4 || ['ФОП','ЮО'].indexOf(item[0])<0 ||
        typeof item[1]!=='string' || !/^\d{8,10}$/.test(item[1]) || !Number.isInteger(item[2]) ||
        item[2]<2 || seen[item[1]] || !pqmSandboxIsCanonicalDigest_(item[3]))
      throw new Error('PQM: APPEND audit identity rejected');
    seen[item[1]]=true;
  });
}

function pqmSandboxValidateAppendAuditFieldTargets_(targets) {
  var seen={};
  targets.forEach(function(item) {
    if (!Array.isArray(item) || item.length!==5 || ['ФОП','ЮО'].indexOf(item[0])<0 ||
        typeof item[1]!=='string' || !/^\d{8,10}$/.test(item[1]) || !Number.isInteger(item[2]) ||
        item[2]<2 || seen[item[1]] || !pqmSandboxIsCanonicalDigest_(item[3]) ||
        !Array.isArray(item[4]) || item[4].length!==15 ||
        item[4].some(function(value){return !Array.isArray(value) || value.length!==2 ||
          ['blank','value','formula'].indexOf(value[0])<0 || !pqmSandboxIsCanonicalDigest_(value[1]);}))
      throw new Error('PQM: APPEND audit field target rejected');
    seen[item[1]]=true;
  });
}

function pqmSandboxAuditAppendFieldsReadOnly_(spreadsheetId,request) {
  var targets=request.auditFieldTargets,located={},formulaRows={},metadataRows={},failed=false;
  function response(status,conflicts) {
    return {environment:'SANDBOX',scriptId:request.scriptId,spreadsheetId:request.spreadsheetId,
      contract:request.contract,requestId:request.requestId,status:status,diagnosticMode:'audit_fields',
      planScope:'APPEND_ONLY',digest:request.expectedDigest,detailsDigest:request.detailsDigest,
      fullPlanDigest:request.fullPlanDigest,sourceDigest:request.sourceDigest,planId:request.planId,
      auditFieldTargetsDigest:request.auditFieldTargetsDigest,conflicts:conflicts,readOnly:true};
  }
  var tabs;
  try { tabs=pqmGoogleSnapshot_(spreadsheetId,null); }
  catch (_) { return response('READ_INCOMPLETE',targets.map(function(item){
    return {code:item[1],status:'UNVERIFIED',fields:[]};})); }
  if (!tabs || PQM_GOOGLE_TABS.some(function(name){return !tabs[name] || !Array.isArray(tabs[name].rows);}))
    return response('READ_INCOMPLETE',targets.map(function(item){return {code:item[1],status:'UNVERIFIED',fields:[]};}));
  var byCode={};targets.forEach(function(item){byCode[item[1]]=[];});
  PQM_GOOGLE_TABS.forEach(function(tab){tabs[tab].rows.forEach(function(row,index){
    var code=String(row.codeDisplay||'').trim();
    if (Object.prototype.hasOwnProperty.call(byCode,code)) byCode[code].push({tab:tab,row:index+2,record:row});
  });});
  var conflicts=targets.map(function(item){
    var found=byCode[item[1]]||[],fields=[];
    if (found.length!==1) return {code:item[1],status:'ROW_CHANGED',fields:[found.length>1?'duplicate':'row']};
    if (found[0].tab!==item[0]) fields.push('tab');
    if (found[0].row!==item[2]) fields.push('row');
    if (fields.length) return {code:item[1],status:'ROW_CHANGED',fields:fields};
    located[item[1]]=found[0];
    return null;
  });
  if (conflicts.some(function(item){return item!==null;})) {
    conflicts=conflicts.map(function(item,index){return item||{code:targets[index][1],status:'UNVERIFIED',fields:[]};});
    return response('AUDIT_DETAILS',conflicts);
  }
  try {
    var formulaRanges=targets.map(function(item){return "'"+item[0].replace(/'/g,"''")+"'!A"+item[2]+':O'+item[2];});
    var serviceRanges=targets.map(function(item){return "'"+item[0].replace(/'/g,"''")+"'!Q"+item[2]+':S'+item[2];});
    var formulas=Sheets.Spreadsheets.Values.batchGet(spreadsheetId,
      {ranges:formulaRanges,valueRenderOption:'FORMULA'});
    var services=Sheets.Spreadsheets.Values.batchGet(spreadsheetId,
      {ranges:serviceRanges,valueRenderOption:'UNFORMATTED_VALUE'});
    if (!formulas || !Array.isArray(formulas.valueRanges) || formulas.valueRanges.length!==targets.length ||
        !services || !Array.isArray(services.valueRanges) || services.valueRanges.length!==targets.length)
      throw new Error('incomplete');
    targets.forEach(function(item,index){
      formulaRows[item[1]]=formulas.valueRanges[index] && formulas.valueRanges[index].values && formulas.valueRanges[index].values[0];
      metadataRows[item[1]]=services.valueRanges[index] && services.valueRanges[index].values && services.valueRanges[index].values[0];
      if (!Array.isArray(formulaRows[item[1]]) || !Array.isArray(metadataRows[item[1]])) failed=true;
    });
  } catch (_) { failed=true; }
  if (failed) return response('READ_INCOMPLETE',targets.map(function(item){
    return {code:item[1],status:'UNVERIFIED',fields:[]};}));

  conflicts=targets.map(function(item,index){
    var actual=located[item[1]],formulaRow=formulaRows[item[1]],metadata=metadataRows[item[1]];
    var q=String(metadata[0]||''),r=String(metadata[1]||''),s=String(metadata[2]||''),fields=[];
    if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$/.test(q)) fields.push('metadata:Q');
    if (r!==request.planId) fields.push('metadata:R');
    if (s!==request.requestId) fields.push('metadata:S');
    var values=Array(15).fill(''),formulas=Array(15).fill('');
    for (var column=0;column<15;column++) {
      var f=formulaRow[column];
      if (typeof f==='string' && f.charAt(0)==='=') formulas[column]=f;
      else values[column]=pqmSandboxExecutionComparableValue_((actual.record.values||[])[column],column);
    }
    var projection={tab:item[0],row:item[2],code:item[1],values:values,formulas:formulas,
      service:{addedAtValid:true,planId:r,runId:s}};
    if (pqmSandboxControlledDigest_(projection)!==item[3])
      return {code:item[1],status:'UNVERIFIED',fields:[]};
    var differences=[];
    for (var c=0;c<15;c++) {
      var formulaValue=formulaRow[c],isFormula=typeof formulaValue==='string'&&formulaValue.charAt(0)==='=';
      var kind=isFormula?'formula':(pqmGoogleBlank_(actual.record.values[c])?'blank':'value');
      var value=isFormula?formulaValue:(kind==='blank'?'':pqmSandboxExecutionComparableValue_(actual.record.values[c],c));
      var expectedCell=item[4][c];
      if (expectedCell[0]!==kind || pqmSandboxControlledDigest_({kind:kind,value:value})!==expectedCell[1])
        differences.push((expectedCell[0]==='formula'||kind==='formula'?'formula:':'value:')+String.fromCharCode(65+c));
    }
    return {code:item[1],status:differences.length?'ROW_CHANGED':'UNVERIFIED',fields:differences};
  });
  return response('AUDIT_DETAILS',conflicts);
}

function pqmSandboxAuditAppendRowsReadOnly_(spreadsheetId,request) {
  var targets=request.auditTargets,total=targets.length;
  function response(status,counts,reasons,conflicts) {
    return {environment:'SANDBOX',scriptId:request.scriptId,spreadsheetId:request.spreadsheetId,
      contract:request.contract,requestId:request.requestId,status:status,diagnosticMode:'audit',
      planScope:'APPEND_ONLY',digest:request.expectedDigest,detailsDigest:request.detailsDigest,
      fullPlanDigest:request.fullPlanDigest,sourceDigest:request.sourceDigest,planId:request.planId,
      auditTargetsDigest:request.auditTargetsDigest,counts:counts,reasonCodes:reasons,
      conflicts:conflicts||[],readOnly:true};
  }
  var counts={planned:total,confirmed:0,missing:0,conflict:0,unverified:0,remaining:0};
  var reasons=[],tabs;
  try { tabs=pqmGoogleSnapshot_(spreadsheetId,null); }
  catch (_) {
    counts.unverified=total;counts.remaining=total;
    return response('READ_INCOMPLETE',counts,['SHEET_READ_INCOMPLETE']);
  }
  if (!tabs || PQM_GOOGLE_TABS.some(function(name){return !tabs[name] || !Array.isArray(tabs[name].rows);})) {
    counts.unverified=total;counts.remaining=total;
    return response('READ_INCOMPLETE',counts,['SHEET_READ_INCOMPLETE']);
  }
  var requested={};targets.forEach(function(item){requested[item[1]]=[];});
  PQM_GOOGLE_TABS.forEach(function(name){
    tabs[name].rows.forEach(function(row,index){
      var code=String(row.codeDisplay||'').trim();
      if (Object.prototype.hasOwnProperty.call(requested,code))
        requested[code].push({tab:name,row:index+2,record:row});
    });
  });
  var conflictDetails=Array(total).fill(null);
  var outcomes=targets.map(function(item,index){
    var found=requested[item[1]]||[];
    if (!found.length) return 'missing';
    if (found.length!==1) {conflictDetails[index]={code:item[1],fields:['duplicate']};return 'conflict';}
    var fields=[];
    if (found[0].tab!==item[0]) fields.push('tab');
    if (found[0].row!==item[2]) fields.push('row');
    if (fields.length) {conflictDetails[index]={code:item[1],fields:fields};return 'conflict';}
    return null;
  });
  var formulaByTab={},formulaFailed=false;
  try {
    var formulaRanges=[],formulaInfo=[];
    PQM_GOOGLE_TABS.forEach(function(tabName){
      var rows=targets.map(function(item,index){return outcomes[index]===null&&item[0]===tabName?item[2]:null;})
        .filter(function(row){return row!==null;});
      if (!rows.length) return;
      var first=Math.min.apply(null,rows),last=Math.max.apply(null,rows);
      formulaRanges.push("'"+tabName.replace(/'/g,"''")+"'!A"+first+':O'+last);
      formulaInfo.push({tab:tabName,first:first});
    });
    var formulaResponse=formulaRanges.length?Sheets.Spreadsheets.Values.batchGet(spreadsheetId,
      {ranges:formulaRanges,valueRenderOption:'FORMULA'}):{valueRanges:[]};
    if (!formulaResponse || !Array.isArray(formulaResponse.valueRanges) ||
        formulaResponse.valueRanges.length!==formulaRanges.length) throw new Error('incomplete');
    formulaInfo.forEach(function(info,index){
      var values=(formulaResponse.valueRanges[index]||{}).values;
      if (!Array.isArray(values)) throw new Error('incomplete');
      formulaByTab[info.tab]={first:info.first,values:values};
    });
  } catch (_) { formulaFailed=true;reasons.push('FORMULA_READ_INCOMPLETE'); }
  var service={},serviceFailed=false;
  try {
    var ranges=[],rangeInfo=[];
    PQM_GOOGLE_TABS.forEach(function(tabName){
      var rows=targets.map(function(item,index){return outcomes[index]===null&&item[0]===tabName?item[2]:null;})
        .filter(function(row){return row!==null;});
      if (!rows.length) return;
      var first=Math.min.apply(null,rows),last=Math.max.apply(null,rows);
      ranges.push("'"+tabName.replace(/'/g,"''")+"'!Q"+first+':S'+last);
      rangeInfo.push({tab:tabName,first:first});
    });
    var batch=ranges.length?Sheets.Spreadsheets.Values.batchGet(spreadsheetId,
      {ranges:ranges,valueRenderOption:'UNFORMATTED_VALUE'}):{valueRanges:[]};
    if (!batch || !Array.isArray(batch.valueRanges) || batch.valueRanges.length!==ranges.length)
      throw new Error('incomplete');
    rangeInfo.forEach(function(info,index){
      var values=(batch.valueRanges[index]||{}).values;
      if (!Array.isArray(values)) throw new Error('incomplete');
      service[info.tab]={first:info.first,values:values};
    });
  } catch (_) { serviceFailed=true;reasons.push('SERVICE_METADATA_READ_INCOMPLETE'); }
  targets.forEach(function(item,index){
    if (outcomes[index]!==null) return;
    if (formulaFailed || serviceFailed) {outcomes[index]='unverified';return;}
    var actual=(requested[item[1]][0]||{}).record;
    var formulaGroup=formulaByTab[item[0]],formulaRow=formulaGroup&&formulaGroup.values[item[2]-formulaGroup.first];
    var metadataGroup=service[item[0]],metadata=metadataGroup&&metadataGroup.values[item[2]-metadataGroup.first];
    if (!actual || !Array.isArray(formulaRow) || !Array.isArray(metadata)) {outcomes[index]='unverified';return;}
    var addedAt=String(metadata[0]||''),planId=String(metadata[1]||''),runId=String(metadata[2]||'');
    var metadataFields=[];
    if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$/.test(addedAt)) metadataFields.push('metadata:Q');
    if (planId!==request.planId) metadataFields.push('metadata:R');
    if (runId!==request.requestId) metadataFields.push('metadata:S');
    if (metadataFields.length) {outcomes[index]='conflict';conflictDetails[index]={code:item[1],fields:metadataFields};return;}
    var values=Array(15).fill(''),formulas=Array(15).fill('');
    for (var column=0;column<15;column++) {
      var formulaValue=formulaRow[column];
      if (typeof formulaValue==='string' && formulaValue.charAt(0)==='=') formulas[column]=formulaValue;
      else values[column]=pqmSandboxExecutionComparableValue_((actual.values||[])[column],column);
    }
    var projection={tab:item[0],row:item[2],code:item[1],values:values,formulas:formulas,
      service:{addedAtValid:true,planId:planId,runId:runId}};
    if (pqmSandboxControlledDigest_(projection)!==item[3]) {
      outcomes[index]='conflict';
      conflictDetails[index]={code:item[1],fields:[],observed_digest:pqmSandboxControlledDigest_(projection)};
    }
  });
  outcomes.forEach(function(value){counts[value||'confirmed']++;});
  counts.remaining=counts.planned-counts.confirmed;
  if (counts.missing) reasons.push('TARGET_ROWS_MISSING');
  if (counts.conflict) reasons.push('TARGET_CONFLICT');
  if (counts.unverified) reasons.push('ROW_READBACK_UNVERIFIED');
  var reportedConflicts=conflictDetails.filter(function(item){return item!==null;});
  return response(counts.unverified?'READ_INCOMPLETE':'AUDITED',counts,reasons,reportedConflicts);
}

function pqmSandboxDiagnoseAppendPlan_(id,properties,key,stored,request) {
  var targets=request.targetIdentities,total=targets.length;
  function summary(status,counts,reasons,manifestBinding,firstChunkReady,manifestMismatchFields) {
    return {environment:'SANDBOX',scriptId:request.scriptId,spreadsheetId:request.spreadsheetId,
      contract:request.contract,requestId:request.requestId,status:status,planScope:'APPEND_ONLY',
      digest:request.expectedDigest,detailsDigest:request.detailsDigest,fullPlanDigest:request.fullPlanDigest,
      sourceDigest:request.sourceDigest,chunkId:request.chunkId,chunkDigest:request.chunkDigest,
      planId:request.planId,chunkIndex:0,counts:counts,reasonCodes:reasons,
      manifestBinding:manifestBinding,manifestMismatchFields:manifestMismatchFields||[],
      firstChunkRecoveryEvidence:firstChunkReady===true,readOnly:true};
  }
  function allUnverified(code,manifestMismatchFields) {
    return summary('BLOCKED',{planned:total,confirmed:0,missing:0,conflict:0,unverified:total,remaining:total},
      [code],'BLOCKED',false,manifestMismatchFields||[]);
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
  var manifestHeaderMismatches=[];
  if (!manifest) manifestHeaderMismatches.push('manifest');
  else {
    var hasManifestChunkIndex=Object.prototype.hasOwnProperty.call(manifest,'chunkIndex');
    var legacyV1FirstAppendChunk=record.chunkJournalVersion===1 && record.planScope==='APPEND_ONLY' &&
      request.planScope==='APPEND_ONLY' && request.chunkIndex===0 && record.inflight===0 &&
      record.uncertainChunk===0 && record.nextChunk===0;
    if (hasManifestChunkIndex ? manifest.chunkIndex!==0 : !legacyV1FirstAppendChunk)
      manifestHeaderMismatches.push('manifest.chunkIndex');
    if (manifest.chunkId!==request.chunkId) manifestHeaderMismatches.push('manifest.chunkId');
    if (manifest.chunkDigest!==request.chunkDigest) manifestHeaderMismatches.push('manifest.chunkDigest');
    if (manifest.planId!==request.requestId) manifestHeaderMismatches.push('manifest.planId');
    if (manifest.runId!==request.requestId) manifestHeaderMismatches.push('manifest.runId');
    if (!Array.isArray(manifest.rows)) manifestHeaderMismatches.push('manifest.rows');
    else if (manifest.rows.length!==Math.min(25,total)) manifestHeaderMismatches.push('manifest.rows.length');
  }
  if (manifestHeaderMismatches.length)
    return allUnverified('MANIFEST_BINDING_MISMATCH',manifestHeaderMismatches);
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
  var manifestBinding=true,manifestMismatchFields=[];
  manifest.rows.forEach(function(item,index) {
    if (!item || typeof item!=='object' || Array.isArray(item)) {
      manifestMismatchFields.push('manifest.rows');return;
    }
    var target=targets[index],change=target&&expectedByCode.get(target.code);
    if (!target) manifestMismatchFields.push('manifest.rows['+index+'].target');
    if (!change) manifestMismatchFields.push('manifest.rows['+index+'].preview');
    if (item.tab!==(target&&target.tab)) manifestMismatchFields.push('manifest.rows['+index+'].tab');
    if (item.row!==(target&&target.row)) manifestMismatchFields.push('manifest.rows['+index+'].row');
    if (item.code!==(target&&target.code)) manifestMismatchFields.push('manifest.rows['+index+'].code');
    if (item.cellsDigest!==(change&&pqmSandboxControlledDigest_(change.cells)))
      manifestMismatchFields.push('manifest.rows['+index+'].cellsDigest');
    if (item.formulaA!==(change&&change.cells[0])) manifestMismatchFields.push('manifest.rows['+index+'].formulaA');
    if (!item.serviceMetadata) manifestMismatchFields.push('manifest.rows['+index+'].serviceMetadata');
    else {
      if (item.serviceMetadata.planId!==request.requestId)
        manifestMismatchFields.push('manifest.rows['+index+'].serviceMetadata.planId');
      if (item.serviceMetadata.runId!==request.requestId)
        manifestMismatchFields.push('manifest.rows['+index+'].serviceMetadata.runId');
    }
  });
  manifestBinding=manifestMismatchFields.length===0;
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
    manifestBinding?'PASS':'BLOCKED',firstReady,manifestMismatchFields);
}
