/* Additive Sandbox ALL-scope Execution API entrypoint. The pinned legacy dispatcher remains unchanged. */
function pqmSandboxAllScopeExecution20261109(envelope) {
  if (!envelope || typeof envelope.payload !== 'string' || envelope.payload.length > 8192 ||
      typeof envelope.signature !== 'string') throw new Error('PQM: invalid execution envelope');
  var properties = PropertiesService.getScriptProperties();
  var secret = properties.getProperty('PQM_EXECUTION_SHARED_SECRET');
  if (!secret || secret.length < 32) throw new Error('PQM: execution authorization not configured');
  var signature = Utilities.base64EncodeWebSafe(
    Utilities.computeHmacSha256Signature(envelope.payload, secret, Utilities.Charset.UTF_8)).replace(/=+$/, '');
  var different = signature.length ^ envelope.signature.length;
  for (var n=0; n<signature.length; n++) different |= signature.charCodeAt(n) ^ (envelope.signature.charCodeAt(n) || 0);
  if (different) throw new Error('PQM: execution authorization rejected');
  var request = JSON.parse(envelope.payload), now = Math.floor(Date.now()/1000);
  if (request.environment!=='SANDBOX' || request.planScope!=='ALL' || request.trigger!=='manual' ||
      ['apply','recover_apply_chunk'].indexOf(request.action)<0)
    throw new Error('PQM: additive ALL-scope endpoint rejects this action or scope');
  if (request.action==='apply' && (!/^[0-9a-f]{32}$/.test(request.chunkId || '') ||
      !pqmSandboxIsCanonicalDigest_(request.chunkDigest) || request.planId!==request.requestId ||
      !pqmSandboxIsCanonicalDigest_(request.chunkDetailsDigest) ||
      ['append','update'].indexOf(request.chunkPhase)<0 ||
      (request.chunkPhase==='append' && (typeof request.chunkAddedAt!=='string' ||
        !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$/.test(request.chunkAddedAt))) ||
      (request.chunkPhase==='update' && request.chunkAddedAt!==undefined)))
    throw new Error('PQM: additive ALL-scope chunk binding rejected');
  if (request.environment !== PQM_MIRROR_ENV.environment || request.scriptId !== PQM_MIRROR_ENV.scriptId ||
      ScriptApp.getScriptId() !== PQM_MIRROR_ENV.scriptId || request.spreadsheetId !== PQM_MIRROR_ENV.spreadsheetId ||
      request.contract !== 'pqm-mirror-datetime-v1' ||
      ['preview','apply','resume_check','recover_append_chunk','recover_apply_chunk','reconcile_partial'].indexOf(request.action)<0 || ['manual','scheduled'].indexOf(request.trigger)<0 ||
      (request.action==='reconcile_partial' && request.trigger!=='manual') ||
      !/^[0-9a-f]{32}$/.test(request.requestId || '') ||
      typeof request.actor !== 'string' || !request.actor || request.actor.length>128 ||
      !Number.isInteger(request.issuedAt) || !Number.isInteger(request.expiresAt) ||
      request.issuedAt>now+30 || request.expiresAt<now || request.expiresAt-request.issuedAt>300 ||
      request.expiresAt<request.issuedAt ||
      (request.action==='apply' && (!pqmSandboxIsCanonicalDigest_(request.expectedDigest) ||
        !Number.isInteger(request.chunkIndex) || request.chunkIndex<0 || request.chunkIndex>499 ||
        ['ALL','APPEND_ONLY'].indexOf(request.planScope || 'ALL')<0)) ||
      (request.action==='apply' && request.planScope==='APPEND_ONLY' &&
        (request.chunkId!==undefined || request.chunkDigest!==undefined || request.planId!==undefined) &&
        (!/^[0-9a-f]{32}$/.test(request.chunkId || '') ||
         !pqmSandboxIsCanonicalDigest_(request.chunkDigest) || request.planId!==request.requestId)) ||
      (request.action==='apply' && request.planScope==='ALL' && request.chunkId!==undefined &&
        (!/^[0-9a-f]{32}$/.test(request.chunkId || '') ||
         !pqmSandboxIsCanonicalDigest_(request.chunkDigest) || request.planId!==request.requestId ||
         !pqmSandboxIsCanonicalDigest_(request.chunkDetailsDigest) ||
         ['append','update'].indexOf(request.chunkPhase)<0 ||
         (request.chunkPhase==='append' && (typeof request.chunkAddedAt!=='string' ||
           !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$/.test(request.chunkAddedAt))) ||
         (request.chunkPhase==='update' && request.chunkAddedAt!==undefined))) ||
      (request.action==='recover_append_chunk' && (request.environment!=='SANDBOX' || request.trigger!=='manual' ||
        request.planScope!=='APPEND_ONLY' || !pqmSandboxIsCanonicalDigest_(request.expectedDigest) ||
        !Number.isInteger(request.chunkIndex) || request.chunkIndex<0 || request.chunkIndex>499 ||
        !/^[0-9a-f]{32}$/.test(request.chunkId || '') ||
        !pqmSandboxIsCanonicalDigest_(request.chunkDigest) || request.planId!==request.requestId)) ||
      (request.action==='recover_apply_chunk' && (request.environment!=='SANDBOX' || request.trigger!=='manual' ||
        request.planScope!=='ALL' || !pqmSandboxIsCanonicalDigest_(request.expectedDigest) ||
        !Number.isInteger(request.chunkIndex) || request.chunkIndex<0 || request.chunkIndex>499 ||
        !/^[0-9a-f]{32}$/.test(request.chunkId || '') ||
        !pqmSandboxIsCanonicalDigest_(request.chunkDigest) || request.planId!==request.requestId ||
        !pqmSandboxIsCanonicalDigest_(request.chunkDetailsDigest) ||
        ['append','update'].indexOf(request.chunkPhase)<0 ||
        (request.chunkPhase==='append' && (typeof request.chunkAddedAt!=='string' ||
          !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$/.test(request.chunkAddedAt))) ||
        (request.chunkPhase==='update' && request.chunkAddedAt!==undefined))) ||
      (request.action==='resume_check' && (request.environment!=='SANDBOX' || request.trigger!=='manual' ||
        !pqmSandboxIsCanonicalDigest_(request.expectedDigest) || !pqmSandboxIsCanonicalDigest_(request.expectedCheckpointDigest) ||
        !Number.isInteger(request.chunkIndex) || request.chunkIndex<1 || request.chunkIndex>499 ||
        request.planScope!=='APPEND_ONLY')))
    throw new Error('PQM: execution identity or lifetime rejected');
  if (PQM_EXECUTION_CONTEXT_) throw new Error('PQM: nested execution rejected');
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(0)) throw new Error('PQM: another writer is running; zero writes');
  try {
    // No getActiveSpreadsheet or UI access in the API path.
    var spreadsheet = SpreadsheetApp.openById(PQM_MIRROR_ENV.spreadsheetId);
    if (!spreadsheet || spreadsheet.getId()!==PQM_MIRROR_ENV.spreadsheetId)
      throw new Error('PQM: explicit spreadsheet identity rejected');
    PQM_EXECUTION_CONTEXT_={spreadsheet:spreadsheet};
    var id = pqmSandboxControlledSpreadsheetId_();
    var planScope = request.planScope || 'ALL';
    function receipt(status,counts,digest) {
      var value = {environment:request.environment,scriptId:request.scriptId,spreadsheetId:request.spreadsheetId,
        contract:request.contract,requestId:request.requestId,status:status,counts:counts || {},digest:digest || null};
      if (request.action==='apply' || request.action==='recover_append_chunk' || request.action==='recover_apply_chunk') value.planScope = planScope;
      if ((request.action==='apply' || request.action==='recover_append_chunk' || request.action==='recover_apply_chunk') && request.chunkId) {
        value.chunkId=request.chunkId; value.chunkDigest=request.chunkDigest; value.planId=request.planId;
        if (request.chunkPhase) value.phase=request.chunkPhase;
      }
      return value;
    }
    var key='PQM_EXECUTION_RUN_'+request.requestId, stored=properties.getProperty(key);
    if (request.action==='reconcile_partial')
      return pqmSandboxReconcilePartial_(properties,request,receipt);
    if (request.action==='recover_append_chunk')
      return pqmSandboxRecoverAppendChunk_(id,properties,key,stored,request,receipt);
    if (request.action==='recover_apply_chunk')
      return pqmSandboxRecoverApplyChunk20261109_(id,properties,key,stored,request,receipt);
    if (stored) {
      var previous=JSON.parse(stored);
      if (previous.actor!==request.actor || previous.digest!==request.expectedDigest ||
          previous.trigger!==request.trigger || (previous.planScope || 'ALL')!==planScope ||
          ['apply','resume_check'].indexOf(request.action)<0)
        throw new Error('PQM: repeated execution identity rejected');
      if (previous.state==='uncertain' || previous.inflight!==null) {
        if (request.action!=='resume_check') properties.setProperty('PQM_EXECUTION_UNCERTAIN',request.requestId);
        throw new Error('PQM: execution chunk outcome uncertain; read-only reconciliation required');
      }
      if (request.action==='resume_check') {
        if (previous.checkpointProtocolVersion!==2 || previous.state!=='ready' ||
            request.planScope!=='APPEND_ONLY' || request.chunkIndex!==previous.nextChunk ||
            !pqmSandboxAllScopeCheckpointStepsValid20261109_(previous) ||
            request.expectedCheckpointDigest!==pqmExecutionCheckpointStateDigest_(previous))
          throw new Error('PQM: saved APPEND_ONLY checkpoint is not resumable');
      }
      if (request.chunkIndex<previous.nextChunk) {
        var saved=previous.steps && previous.steps[request.chunkIndex];
        if (!saved || !saved.verified || !saved.checkpointDigest)
          throw new Error('PQM: verified chunk receipt unavailable; no retry');
        if (!saved.more && previous.result) return previous.result;
        return pqmExecutionCheckpointReceipt_(request,receipt,saved);
      }
      if (request.action==='apply' && request.chunkIndex!==previous.nextChunk)
        throw new Error('PQM: unexpected Apply checkpoint sequence');
      if (request.action==='apply' && request.chunkIndex>0 &&
          (previous.checkpointProtocolVersion!==2 || !pqmSandboxAllScopeCheckpointStepsValid20261109_(previous) ||
           request.expectedCheckpointDigest!==pqmExecutionCheckpointStateDigest_(previous)))
        throw new Error('PQM: Apply checkpoint receipt mismatch; read-only review required');
      if (request.action==='apply' && previous.state==='complete')
        throw new Error('PQM: unexpected Apply checkpoint sequence');
    } else if ((request.action==='apply' && request.chunkIndex!==0) || request.action==='resume_check') {
      throw new Error('PQM: Apply checkpoint must start at chunk zero');
    }
    var uncertain=properties.getProperty('PQM_EXECUTION_UNCERTAIN');
    if (uncertain && request.action!=='preview')
      throw new Error('PQM: unresolved execution outcome; reconciliation required');
    var loaded=pqmSandboxFullLoad_(id);
    if (request.action==='preview') {
      var detailReceipt = receipt('PREVIEW', {
        append:loaded.plan.counts.appended,update:loaded.plan.counts.updated,
        conflict:loaded.plan.counts.conflicts,error:loaded.plan.counts.errors,skipped:loaded.plan.counts.unchanged
      },loaded.plan_digest);
      detailReceipt.planDetails = pqmSandboxFullPreviewDetails_(loaded);
      return detailReceipt;
    }
    if (request.action==='resume_check') {
      if (loaded.state.payload_digest!==previous.payloadDigest || loaded.state.google_digest!==previous.googleDigest)
        throw new Error('PQM: sources or Google Sheets changed since the verified checkpoint');
      var remainingDetails=pqmSandboxFullPreviewDetails_(loaded);
      remainingDetails.updates=[];
      remainingDetails.plan_digest=request.expectedDigest;
      remainingDetails.remaining_plan_digest=loaded.append_only_digest;
      remainingDetails.counts.update=0;
      var resumeReceipt=receipt('RESUME_READY',{
        append:remainingDetails.appends.length,update:0,
        conflict:remainingDetails.conflicts.length,error:remainingDetails.errors.length,
        remaining_safe:remainingDetails.appends.length
      },request.expectedDigest);
      resumeReceipt.planScope='APPEND_ONLY';
      resumeReceipt.chunkIndex=request.chunkIndex;
      resumeReceipt.nextChunk=previous.nextChunk;
      resumeReceipt.checkpointDigest=pqmExecutionCheckpointStateDigest_(previous);
      resumeReceipt.planDetails=remainingDetails;
      return resumeReceipt;
    }
    var scopedDigest = planScope==='APPEND_ONLY' ? loaded.append_only_digest : loaded.plan_digest;
    if (!stored && scopedDigest!==request.expectedDigest) throw new Error('PQM: stale execution Preview; zero writes');
    if (stored && (loaded.state.payload_digest!==previous.payloadDigest ||
        loaded.state.google_digest!==previous.googleDigest))
      throw new Error('PQM: source or Google state changed since the last verified Apply chunk');
    // Bounded persistent receipts. Never evict a run and allow it to be applied twice.
    var all=stored ? null : properties.getProperties();
    if (!stored && Object.keys(all).filter(function(k){return k.indexOf('PQM_EXECUTION_RUN_')===0;}).length>=250)
      throw new Error('PQM: execution receipt capacity reached; audited maintenance required');
    var record=stored ? previous : {checkpointProtocolVersion:2,actor:request.actor,trigger:request.trigger,digest:request.expectedDigest,
      planScope:planScope,
      result:null,state:'ready',nextChunk:0,inflight:null,payloadDigest:loaded.state.payload_digest,
      googleDigest:loaded.state.google_digest,aggregate:{append:0,update:0,batches:0},steps:[]};
    if (stored && ((previous.chunkJournalVersion===1 && (!request.chunkId || planScope!=='APPEND_ONLY')) ||
        (previous.chunkJournalVersion===2 && (!request.chunkId || planScope!=='ALL')) ||
        (request.chunkId && previous.chunkJournalVersion!==1 && previous.chunkJournalVersion!==2))) {
      throw new Error('PQM: Apply chunk journal protocol changed; read-only review required');
    }
    if (!stored && request.chunkId) {
      record.chunkJournalVersion=2;
      record.planId=request.planId;
      record.runId=request.requestId;
    }
    if (!stored) pqmExecutionCheckpointSave_(properties,key,record,PQM_SANDBOX_EXECUTION_CHECKPOINT_MAX_BYTES);
    try {
      var result=pqmSandboxApplyCheckpointStep_(id,loaded,request,properties,key,record,receipt);
      if (record.steps && record.steps.length) {
        var confirmed=record.steps[record.steps.length-1];
        if (confirmed.checkpointDigest) pqmExecutionCheckpointSave_(properties,key,record,PQM_SANDBOX_EXECUTION_CHECKPOINT_MAX_BYTES);
      }
      if (result.more) return result;
      return record.result || result;
    } catch (_) {
      var safeStages=['source_and_sheet_guard','chunk_selection','append_prewrite_guard','append_request_build',
        'append_inflight_save','append_batch_update','append_read_back','append_metadata_read_back',
        'append_projection','update_chunk_selection','update_inflight_save','update_batch_update',
        'update_read_back','postwrite_sheet_snapshot','postwrite_plan','checkpoint_receipt_save'];
      var stage=safeStages.indexOf(record.lastStage)>=0?record.lastStage:'apply_step';
      var exceptionType=(_ && ['Error','TypeError','RangeError','ReferenceError'].indexOf(_.name)>=0)?_.name:'Other';
      var provenPrewriteStages=['source_and_sheet_guard','chunk_selection','append_prewrite_guard',
        'append_request_build','append_inflight_save','update_chunk_selection','update_inflight_save'];
      if (provenPrewriteStages.indexOf(stage)>=0) {
        record.state='ready'; record.inflight=null; record.inflightManifest=null; record.uncertainChunk=null;
        record.lastError={stage:stage,category:'prewrite_rejected',exceptionType:exceptionType};
        pqmExecutionCheckpointSave_(properties,key,record,PQM_SANDBOX_EXECUTION_CHECKPOINT_MAX_BYTES);
        throw new Error('PQM: Apply rejected before write. PQM_APPLY_DIAG:'+stage+':'+exceptionType);
      }
      record.state='uncertain';
      record.uncertainChunk=request.chunkIndex;
      record.lastError={stage:stage,category:'apply_stage_failed',exceptionType:exceptionType};
      try { pqmExecutionCheckpointSave_(properties,key,record,PQM_SANDBOX_EXECUTION_CHECKPOINT_MAX_BYTES); } catch (ignored) {}
      properties.setProperty('PQM_EXECUTION_UNCERTAIN',request.requestId);
      throw new Error('PQM: Apply may be partial; no retry. PQM_APPLY_DIAG:'+stage+':'+exceptionType);
    }
  } finally {
    PQM_EXECUTION_CONTEXT_=null;
    lock.releaseLock();
  }
}

/* Read-only support view. Returns no operation values, digests, tokens, or supplier identifiers. */
function pqmSandboxApplyStateReadOnly(requestId) {
  if (typeof requestId!=='string' || !/^[0-9a-f]{32}$/.test(requestId))
    throw new Error('PQM: invalid read-only run identity');
  var properties=PropertiesService.getScriptProperties();
  var raw=properties.getProperty('PQM_EXECUTION_RUN_'+requestId);
  var marker=properties.getProperty('PQM_EXECUTION_UNCERTAIN');
  var record=null,valid=false;
  if (raw) {
    try { record=JSON.parse(raw); valid=!!record && typeof record==='object' && !Array.isArray(record); }
    catch (_) { record=null; }
  }
  var steps=record && Array.isArray(record.steps) ? record.steps : [];
  var result=record && record.result && typeof record.result==='object' ? record.result : null;
  var lastStep=steps.length ? steps[steps.length-1] : null;
  var checkpoint=record && record.checkpointDigest || lastStep && lastStep.checkpointDigest || result && result.checkpointDigest || null;
  var lastError=record && record.lastError && typeof record.lastError==='object' ? record.lastError : null;
  return {request_id_matches:true,marker_present:marker!==null && marker!=='',
    marker_matches_request:marker===requestId,run_record_present:raw!==null,
    run_record_valid_json:valid,state:record && typeof record.state==='string' ? record.state : null,
    plan_scope:record && typeof record.planScope==='string' ? record.planScope : null,
    inflight:Number.isInteger(record && record.inflight) ? record.inflight : null,
    uncertain_chunk:Number.isInteger(record && record.uncertainChunk) ? record.uncertainChunk : null,
    steps_count:steps.length,checkpoint_present:!!checkpoint,
    checkpoint_valid:pqmSandboxIsCanonicalDigest_(checkpoint),
    result_present:!!result,result_status:result && typeof result.status==='string' ? result.status : null,
    receipt_present:!!(lastStep && lastStep.checkpointDigest),
    receipt_valid:!!(lastStep && lastStep.verified===true && pqmSandboxIsCanonicalDigest_(lastStep.checkpointDigest)),
    last_error_present:!!lastError,
    last_error_stage:lastError && typeof lastError.stage==='string' ? lastError.stage : null,
    last_error_category:lastError && typeof lastError.category==='string' ? lastError.category : null,
    last_error_type:lastError && typeof lastError.exceptionType==='string' ? lastError.exceptionType : null,
    result_counts:result && result.counts && Number.isInteger(result.counts.append) &&
      Number.isInteger(result.counts.update) ? {append:result.counts.append,update:result.counts.update} : null};
}

function pqmSandboxAllScopeCheckpointStepsValid20261109_(record) {
  if (!record || record.checkpointProtocolVersion!==2 || record.state!=='ready' ||
      record.inflight!==null || !Array.isArray(record.steps) ||
      record.steps.length!==record.nextChunk || ['ALL','APPEND_ONLY'].indexOf(record.planScope)<0 ||
      !pqmSandboxIsCanonicalDigest_(record.digest) ||
      typeof record.payloadDigest!=='string' || typeof record.googleDigest!=='string') return false;
  var totals={append:0,update:0,batches:0};
  for (var i=0;i<record.steps.length;i++) {
    var step=record.steps[i], counts=step && step.counts;
    if (!step || !counts || step.verified!==true || step.chunkIndex!==i || step.nextChunk!==i+1 ||
        ['append','update'].indexOf(step.phase)<0 || step.planScope!==record.planScope ||
        (record.planScope==='APPEND_ONLY' && (step.phase!=='append' || counts.update!==0)) || step.digest!==record.digest ||
        step.payloadDigest!==record.payloadDigest || !pqmSandboxIsCanonicalDigest_(step.googleDigest) ||
        !pqmSandboxIsCanonicalDigest_(step.checkpointDigest) ||
        !Number.isInteger(counts.append) || counts.append<0 || !Number.isInteger(counts.update) || counts.update<0 ||
        !Number.isInteger(counts.batches) || counts.batches<0 ||
        !Number.isInteger(counts.remaining_safe) || counts.remaining_safe<0 ||
        typeof step.more!=='boolean' || step.more!==(step.status==='APPLY_CHUNK_VERIFIED')) return false;
    if (step.chunkId && (!/^[0-9a-f]{32}$/.test(step.chunkId) ||
        !pqmSandboxIsCanonicalDigest_(step.chunkDigest) || step.planId!==record.planId)) return false;
    if (step.chunkId && record.chunkJournalVersion===1 &&
        (!Array.isArray(step.serviceRanges) || !step.serviceRanges.length || step.phase!=='append' ||
         step.serviceRanges.some(function(range) {
          return !range || ['ФОП','ЮО'].indexOf(range.tab)<0 || !Number.isInteger(range.first) ||
            !Number.isInteger(range.last) || range.first<2 || range.last<range.first ||
            range.planId!==record.planId || range.runId!==record.runId;
        }))) return false;
    totals.append+=counts.append;
    totals.update+=counts.update;
    totals.batches+=counts.batches;
  }
  var aggregate=record.aggregate || {};
  if (record.steps.length && record.steps[record.steps.length-1].googleDigest!==record.googleDigest) return false;
  return aggregate.append===totals.append && aggregate.update===totals.update && aggregate.batches===totals.batches;
}

/* Recover one ALL-scope chunk only after exact, bounded read-back proves every row. */
function pqmSandboxRecoverApplyChunk20261109_(id,properties,key,stored,request,receipt) {
  if (!stored) throw new Error('PQM: Apply chunk recovery record is missing');
  var record;
  try { record=JSON.parse(stored); } catch (_) { throw new Error('PQM: Apply chunk recovery record is invalid'); }
  var manifest=record.inflightManifest,marker=properties.getProperty('PQM_EXECUTION_UNCERTAIN');
  if (marker && marker!==request.requestId) throw new Error('PQM: another execution is uncertain');
  if (record.actor!==request.actor || record.trigger!=='manual' || record.planScope!=='ALL' ||
      record.digest!==request.expectedDigest || record.chunkJournalVersion!==2 ||
      record.planId!==request.planId || record.runId!==request.requestId ||
      !manifest || manifest.chunkId!==request.chunkId || manifest.chunkDigest!==request.chunkDigest ||
      manifest.detailsDigest!==request.chunkDetailsDigest || manifest.phase!==request.chunkPhase ||
      manifest.planId!==request.planId || manifest.runId!==request.requestId ||
      record.inflight!==request.chunkIndex || record.nextChunk!==request.chunkIndex ||
      !['writing','uncertain'].includes(record.state) || !Array.isArray(manifest.rows) ||
      !manifest.rows.length || manifest.rows.length>PQM_SANDBOX_FULL_CHUNK_MAX_ROWS) {
    var saved=record.steps && record.steps[request.chunkIndex];
    if (record.state==='ready' && saved && saved.verified===true &&
        saved.chunkId===request.chunkId && saved.chunkDigest===request.chunkDigest &&
        saved.planId===request.planId && saved.phase===request.chunkPhase &&
        saved.planScope==='ALL' && pqmSandboxIsCanonicalDigest_(saved.checkpointDigest)) {
      var replay=pqmExecutionCheckpointReceipt_(request,receipt,saved);
      replay.status='CHUNK_RECOVERED';
      return replay;
    }
    throw new Error('PQM: Apply chunk recovery binding rejected');
  }
  if (!Array.isArray(record.steps) || record.steps.length!==request.chunkIndex ||
      (record.steps.length && !pqmSandboxCheckpointStepsValid_(record)) ||
      manifest.rows.some(function(row) {
        return !row || PQM_GOOGLE_TABS.indexOf(row.tab)<0 || !Number.isInteger(row.row) || row.row<2 ||
          !Array.isArray(row.columns) || !row.columns.length ||
          !pqmSandboxIsCanonicalDigest_(row.beforeDigest) || !pqmSandboxIsCanonicalDigest_(row.afterDigest) ||
          !pqmSandboxIsCanonicalDigest_(row.codeDigest);
      })) throw new Error('PQM: Apply chunk manifest or checkpoint chain is invalid');
  var loaded=pqmSandboxFullLoad_(id);
  if (loaded.state.payload_digest!==record.payloadDigest)
    throw new Error('PQM: Preview source changed; Apply recovery held');
  var actual=pqmSandboxExecutionReadChunkEvidence_(id,manifest),allBefore=true,allAfter=true;
  manifest.rows.forEach(function(expected,index) {
    var observed=actual[index];
    if (!observed || observed.tab!==expected.tab || observed.row!==expected.row) { allBefore=false; allAfter=false; return; }
    if (observed.digest!==expected.beforeDigest) allBefore=false;
    if (observed.digest!==expected.afterDigest || observed.codeDigest!==expected.codeDigest) allAfter=false;
  });
  if (allBefore) {
    var notApplied=receipt('CHUNK_NOT_APPLIED',{append:0,update:0,batches:0},request.expectedDigest);
    notApplied.chunkIndex=request.chunkIndex; notApplied.nextChunk=request.chunkIndex;
    notApplied.more=true; notApplied.phase=request.chunkPhase; notApplied.planScope='ALL';
    notApplied.chunkId=request.chunkId; notApplied.chunkDigest=request.chunkDigest; notApplied.planId=request.planId;
    return notApplied;
  }
  if (!allAfter) throw new Error('PQM: Apply chunk read-back is partial or ambiguous; hold retained');
  var codes=manifest.rows.map(function(row) { return row.codeDigest; });
  var codeValues=[];
  manifest.rows.forEach(function(row) {
    var loadedRow=loaded.tabs[row.tab].rows[row.row-2];
    if (!loadedRow || !loadedRow.codeDisplay) throw new Error('PQM: Apply chunk identity is unavailable');
    var code=String(loadedRow.codeDisplay).trim(),occurrences=0;
    PQM_GOOGLE_TABS.forEach(function(tabName) {
      (loaded.tabs[tabName].rows||[]).forEach(function(item) {
        if (String(item.codeDisplay||'').trim()===code) occurrences++;
      });
    });
    if (occurrences!==1) throw new Error('PQM: Apply chunk identity is duplicated');
    codeValues.push(code);
  });
  if (new Set(codeValues).size!==manifest.rows.length || codes.some(function(hash,index) {
      return pqmSandboxControlledDigest_(codeValues[index])!==hash;
    })) throw new Error('PQM: Apply chunk identities are duplicated or changed');
  var appendCount=manifest.phase==='append'?manifest.rows.length:0;
  var updateCount=manifest.phase==='update'?manifest.rows.length:0;
  var remaining=loaded.plan.counts.appended+loaded.plan.counts.updated;
  record.aggregate=record.aggregate||{append:0,update:0,batches:0};
  record.aggregate.append+=appendCount; record.aggregate.update+=updateCount; record.aggregate.batches+=1;
  record.payloadDigest=loaded.state.payload_digest; record.googleDigest=loaded.state.google_digest;
  record.inflight=null; record.inflightManifest=null; record.uncertainChunk=null;
  record.nextChunk=request.chunkIndex+1; record.state=remaining?'ready':'complete';
  var status=remaining?'APPLY_CHUNK_VERIFIED':
    (loaded.plan.counts.conflicts||loaded.plan.counts.errors?'COMPLETE_WITH_CONFLICTS':'COMPLETE');
  var counts={append:appendCount,update:updateCount,conflict:loaded.plan.counts.conflicts,
    error:loaded.plan.counts.errors,remaining_safe:remaining,batches:1};
  var step={status:status,chunkIndex:request.chunkIndex,nextChunk:record.nextChunk,more:remaining>0,
    phase:manifest.phase,counts:counts,verified:true,digest:request.expectedDigest,planScope:'ALL',
    payloadDigest:record.payloadDigest,googleDigest:record.googleDigest,chunkId:request.chunkId,
    chunkDigest:request.chunkDigest,planId:request.planId};
  record.steps.push(step);
  if (!step.more) {
    record.result=receipt(status,{append:record.aggregate.append,update:record.aggregate.update,
      conflict:counts.conflict,error:counts.error,remaining_safe:remaining,batches:record.aggregate.batches},request.expectedDigest);
    record.result.chunkIndex=step.chunkIndex; record.result.nextChunk=step.nextChunk;
    record.result.more=false; record.result.phase=step.phase; record.result.planScope='ALL';
  }
  step.checkpointDigest=pqmExecutionCheckpointStateDigest_(record);
  if (record.result) record.result.checkpointDigest=step.checkpointDigest;
  pqmExecutionCheckpointSave_(properties,key,record,PQM_SANDBOX_EXECUTION_CHECKPOINT_MAX_BYTES);
  if (marker===request.requestId) properties.deleteProperty('PQM_EXECUTION_UNCERTAIN');
  var recovered=pqmExecutionCheckpointReceipt_(request,receipt,step);
  recovered.status='CHUNK_RECOVERED';
  return recovered;
}

var PQM_SANDBOX_PARTIAL_RECONCILIATION_FINGERPRINT_='9be34ff2df1e661346176eeb';
var PQM_SANDBOX_PARTIAL_RECONCILIATION_APPEND_ONLY_FINGERPRINT_='30331b560493209210f1e507';
var PQM_SANDBOX_PARTIAL_RECONCILIATION_LEGACY_20261108_FINGERPRINT_='816c6424279bff220878b0c4';
var PQM_SANDBOX_PARTIAL_RECONCILIATION_LEGACY_20261108_REQUEST_ID_='592128d9837d4b71bbeb330ef8aabf4b';
var PQM_SANDBOX_PARTIAL_RECONCILIATION_LEGACY_20261108_V1_STATUS_='RETIRED_INVALID_DATE_NORMALIZATION_EVIDENCE';
