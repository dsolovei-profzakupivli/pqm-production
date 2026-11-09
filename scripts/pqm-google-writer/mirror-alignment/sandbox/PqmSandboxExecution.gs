/* Server-authenticated API entrypoint; uses the existing planner and DailySync only. */
function pqmSandboxExecution(envelope) {
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
      return pqmSandboxRecoverApplyChunk_(id,properties,key,stored,request,receipt);
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
            !pqmSandboxCheckpointStepsValid_(previous) ||
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
          (previous.checkpointProtocolVersion!==2 || !pqmSandboxCheckpointStepsValid_(previous) ||
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
      record.chunkJournalVersion=1;
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

function pqmSandboxCheckpointStepsValid_(record) {
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

/* Recover one lost APPEND response from a read-only exact-row audit. */
function pqmSandboxRecoverAppendChunk_(id,properties,key,stored,request,receipt) {
  if (!stored) throw new Error('PQM: APPEND chunk recovery record is missing');
  var record;
  try { record=JSON.parse(stored); } catch (_) { throw new Error('PQM: APPEND chunk recovery record is invalid'); }
  var manifest=record.inflightManifest;
  if (record.chunkJournalVersion!==1 || record.planId!==request.planId || record.runId!==request.requestId ||
      record.planScope!=='APPEND_ONLY' || record.digest!==request.expectedDigest ||
      !manifest || manifest.chunkId!==request.chunkId || manifest.chunkDigest!==request.chunkDigest ||
      manifest.planId!==request.planId || manifest.runId!==request.requestId ||
      !((record.state==='uncertain' && record.uncertainChunk===request.chunkIndex) ||
        (record.state==='writing' && record.uncertainChunk==null && record.inflight===request.chunkIndex)) ||
      !Number.isInteger(record.inflight) || record.inflight!==request.chunkIndex ||
      record.nextChunk!==request.chunkIndex ||
      !Array.isArray(manifest.rows) || !manifest.rows.length || manifest.rows.length>PQM_SANDBOX_EXECUTION_APPEND_PAGE_ROWS) {
    var saved=record.steps && record.steps[request.chunkIndex];
    if (record.state==='ready' && saved && saved.verified===true && saved.chunkId===request.chunkId &&
        saved.chunkDigest===request.chunkDigest && saved.planId===request.planId) {
      var replay=pqmExecutionCheckpointReceipt_(request,receipt,saved);
      replay.status='CHUNK_RECOVERED';
      return replay;
    }
    throw new Error('PQM: APPEND chunk recovery binding rejected');
  }
  if (!Array.isArray(record.steps) || record.steps.length!==request.chunkIndex ||
      (record.steps.length && !pqmSandboxCheckpointStepsValid_(record))) {
    throw new Error('PQM: prior verified checkpoint chain is invalid');
  }
  var loaded=pqmSandboxFullLoad_(id);
  if (loaded.state.payload_digest!==record.payloadDigest) throw new Error('PQM: PQM source changed; recovery held');
  var original=pqmSandboxAppendLoad_(id,undefined,loaded,PQM_SANDBOX_EXECUTION_APPEND_PAGE_ROWS);
  if (manifest.rows.some(function(row) {
    return !row || PQM_GOOGLE_TABS.indexOf(row.tab)<0 || !Number.isInteger(row.row) ||
      typeof row.code!=='string' || !row.code || !pqmSandboxIsCanonicalDigest_(row.cellsDigest) ||
      !row.serviceMetadata || row.serviceMetadata.planId!==request.planId ||
      row.serviceMetadata.runId!==request.requestId;
  })) throw new Error('PQM: persisted APPEND chunk manifest is invalid');

  var codeCounts=new Map(original.selected.map(function(change) { return [String(change.cells[1]).trim(),0]; }));
  PQM_GOOGLE_TABS.forEach(function(tabName) {
    (loaded.tabs[tabName].rows||[]).forEach(function(row) {
      var code=String(row.codeDisplay||'').trim();
      if (codeCounts.has(code)) codeCounts.set(code,codeCounts.get(code)+1);
    });
  });
  var totalPresent=Array.from(codeCounts.values()).reduce(function(sum,count) { return sum+count; },0);
  if (totalPresent===0 && loaded.state.google_digest===record.googleDigest &&
      loaded.append_only_digest===request.expectedDigest && original.digest===request.expectedDigest &&
      original.selected.length===manifest.rows.length && original.selected.every(function(change,index) {
        var row=manifest.rows[index];
        return row.tab===change.tab && row.row===change.row && row.code===String(change.cells[1]).trim() &&
          row.cellsDigest===pqmSandboxControlledDigest_(change.cells) && row.formulaA===change.cells[0];
      })) {
    // Prove the exact pre-write state and blank destinations before releasing
    // this one attempt for a retry. This is not a retry of an uncertain write.
    pqmSandboxAppendPrewriteGuard_(id,original);
    var serviceRanges=original.selected.map(function(change) {
      return "'" + change.tab.replace(/'/g,"''") + "'!Q" + change.row + ':S' + change.row;
    });
    var service=Sheets.Spreadsheets.Values.batchGet(id,{ranges:serviceRanges,valueRenderOption:'FORMULA'});
    if (!service || !Array.isArray(service.valueRanges) || service.valueRanges.length!==serviceRanges.length ||
        service.valueRanges.some(function(item) { return (item.values||[]).some(function(row) {
          return row.some(function(value) { return !pqmGoogleBlank_(value); });
        }); })) throw new Error('PQM: destination service metadata is not blank; recovery held');
    // A proved zero-write outcome is still held. A human must explicitly
    // decide whether to start a fresh Preview; never replay this chunk here.
    var notApplied=receipt('CHUNK_NOT_APPLIED',{append:0,update:0,batches:0,remaining_safe:original.plan.counts.appended},request.expectedDigest);
    notApplied.chunkIndex=request.chunkIndex; notApplied.nextChunk=request.chunkIndex;
    notApplied.more=true; notApplied.phase='append'; notApplied.planScope='APPEND_ONLY';
    notApplied.chunkId=request.chunkId; notApplied.chunkDigest=request.chunkDigest; notApplied.planId=request.planId;
    return notApplied;
  }
  if (totalPresent!==manifest.rows.length) throw new Error('PQM: partial or duplicate APPEND chunk; recovery held');
  var blankTabs=JSON.parse(JSON.stringify(loaded.tabs));
  manifest.rows.forEach(function(expected) {
    var tab=blankTabs[expected.tab], index=expected.row-2, row=tab && tab.rows[index];
    if (!row || String(row.codeDisplay||'').trim()!==expected.code) {
      throw new Error('PQM: exact APPEND destination row mismatch; recovery held');
    }
    tab.rows[index]={values:Array(15).fill(''),formulas:Array(15).fill(''),codeDisplay:'',dateFormat:'',verificationDateFormat:''};
  });
  PQM_GOOGLE_TABS.forEach(function(name) {
    var rows=blankTabs[name].rows;
    while (rows.length) {
      var last=rows[rows.length-1];
      if (String(last.codeDisplay||'').trim() || last.values.some(function(value) { return !pqmGoogleBlank_(value); }) ||
          last.formulas.some(function(value) { return !pqmGoogleBlank_(value); })) break;
      rows.pop();
    }
  });
  var rebuiltPlan=pqmGooglePlan_(loaded.body,blankTabs);
  var rebuilt=pqmSandboxAppendLoad_(id,undefined,{body:loaded.body,tabs:blankTabs,plan:rebuiltPlan},manifest.rows.length);
  if (rebuilt.digest!==request.expectedDigest || rebuilt.selected.length!==manifest.rows.length || rebuilt.selected.some(function(change,index) {
      var expected=manifest.rows[index];
      return !expected || change.tab!==expected.tab || change.row!==expected.row ||
        String(change.cells[1]).trim()!==expected.code ||
        pqmSandboxControlledDigest_(change.cells)!==expected.cellsDigest;
  })) throw new Error('PQM: planned APPEND values do not match the persisted chunk; recovery held');
  rebuilt.selected.forEach(function(change,index) { change.serviceMetadata=manifest.rows[index].serviceMetadata; });
  var duplicates=new Map(rebuilt.selected.map(function(change) { return [String(change.cells[1]).trim(),0]; }));
  PQM_GOOGLE_TABS.forEach(function(name) { loaded.tabs[name].rows.forEach(function(row) {
    var code=String(row.codeDisplay||'').trim(); if (duplicates.has(code)) duplicates.set(code,duplicates.get(code)+1);
  }); });
  if (Array.from(duplicates.values()).some(function(count) { return count!==1; })) {
    throw new Error('PQM: duplicate or missing APPEND identity; recovery held');
  }
  pqmSandboxAppendServiceColumnsReady_(id,loaded.tabs);
  pqmSandboxAppendVerify_(id,rebuilt.selected,loaded.tabs);
  var templates={};
  PQM_GOOGLE_TABS.forEach(function(name) {
    var rows=rebuilt.selected.filter(function(change) { return change.tab===name; });
    if (rows.length) templates[name]=pqmSandboxAppendRowMetadata_(id,name,rows[0].row-1);
  });
  pqmSandboxAppendVerifyMetadata_(id,rebuilt.selected,templates);

  var counts={append:manifest.rows.length,update:0,conflict:loaded.plan.counts.conflicts,
    error:loaded.plan.counts.errors,remaining_safe:loaded.plan.counts.appended,batches:1};
  record.aggregate=record.aggregate||{append:0,update:0,batches:0};
  record.aggregate.append+=counts.append; record.aggregate.batches+=1;
  record.payloadDigest=loaded.state.payload_digest; record.googleDigest=loaded.state.google_digest;
  record.inflight=null; record.inflightManifest=null; record.uncertainChunk=null;
  record.nextChunk=request.chunkIndex+1; record.state=counts.remaining_safe?'ready':'complete';
  var status=counts.remaining_safe?'APPLY_CHUNK_VERIFIED':
    (counts.conflict||counts.error?'COMPLETE_WITH_CONFLICTS':'COMPLETE');
  var step={status:status,chunkIndex:request.chunkIndex,nextChunk:record.nextChunk,
    more:counts.remaining_safe>0,phase:'append',counts:counts,verified:true,
    digest:request.expectedDigest,planScope:'APPEND_ONLY',payloadDigest:record.payloadDigest,
    googleDigest:record.googleDigest,chunkId:request.chunkId,chunkDigest:request.chunkDigest,
    planId:request.planId,serviceRanges:pqmSandboxAppendServiceRanges_(rebuilt.selected)};
  record.steps.push(step);
  if (!step.more) {
    record.result=receipt(status,{append:record.aggregate.append,update:record.aggregate.update,
      conflict:counts.conflict,error:counts.error,remaining_safe:0,batches:record.aggregate.batches},request.expectedDigest);
    record.result.chunkIndex=step.chunkIndex; record.result.nextChunk=step.nextChunk;
    record.result.more=false; record.result.phase='append'; record.result.planScope='APPEND_ONLY';
  }
  step.checkpointDigest=pqmExecutionCheckpointStateDigest_(record);
  if (record.result) record.result.checkpointDigest=step.checkpointDigest;
  pqmExecutionCheckpointSave_(properties,key,record,PQM_SANDBOX_EXECUTION_CHECKPOINT_MAX_BYTES);
  if (properties.getProperty('PQM_EXECUTION_UNCERTAIN')===request.requestId)
    properties.deleteProperty('PQM_EXECUTION_UNCERTAIN');
  var recovered=pqmExecutionCheckpointReceipt_(request,receipt,step);
  recovered.status='CHUNK_RECOVERED';
  return recovered;
}

/* Recover one ALL-scope chunk only after exact, bounded read-back proves every row. */
function pqmSandboxRecoverApplyChunk_(id,properties,key,stored,request,receipt) {
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

function pqmSandboxPartialReconciliationEvidence_() {
  return {
    initial_plan:{append:451,update:2,conflict:2},
    verified_append_rows:50,
    append_value_mismatches:0,
    duplicate_rows:0,
    routing_mismatches:0,
    protected_cell_mutations:0,
    date_only_format_exceptions:12,
    date_only_format_exceptions_approved:true,
    updates_disposition:'RECOMPUTE_WITH_NEW_PREVIEW'
  };
}

function pqmSandboxPartialReconciliationLegacy20261108V1Archive_() {
  return {
    status:PQM_SANDBOX_PARTIAL_RECONCILIATION_LEGACY_20261108_V1_STATUS_,
    profile:{
      expectedRequestId:PQM_SANDBOX_PARTIAL_RECONCILIATION_LEGACY_20261108_REQUEST_ID_,
      evidence:{
        evidence_version:1,
        request_id:PQM_SANDBOX_PARTIAL_RECONCILIATION_LEGACY_20261108_REQUEST_ID_,
        plan_scope:'APPEND_ONLY',
        initial_plan:{append:326,update:2,conflict:2},
        attempted_chunk:0,
        checkpoint_present:false,
        saved_preview_source_digest:{present:false,historical_schema:'PRE_SOURCE_DIGEST',substitute_used:false},
        audit_type:'READ_ONLY_SAVED_PREVIEW_AND_LIVE_SHEETS',
        audit:{rows_found:25,full_matches:20,partial_rows:5,
          partial_operation_numbers:[6,12,14,17,25],partial_columns:{I:5},
          missing:0,duplicates:0,wrong_tab:0,formula_a_matches:25,
          protected_cell_mutations:0,saved_preview_binding:'PASS',writes_performed:0},
        recovery_disposition:'PARTIAL_ROWS_I_UNVERIFIED_NO_REAPPEND_NEW_PREVIEW_REQUIRED'
      },
      resultCounts:{rows_found:25,fully_matching_rows:20,partial_rows:5,
        unverified_column_i_rows:5,checkpoint_receipts:0},
      receiptFields:{checkpointPresent:false,resumeAuthorized:false,
        nextAction:'NEW_PREVIEW_REQUIRED',partialOperationNumbers:[6,12,14,17,25]},
      requireUncertainFirstChunk:true
    }
  };
}

function pqmSandboxPartialReconciliationProfile_(fingerprint) {
  if (fingerprint===PQM_SANDBOX_PARTIAL_RECONCILIATION_FINGERPRINT_) {
    return {
      evidence:pqmSandboxPartialReconciliationEvidence_(),
      resultCounts:{verified_append_rows:50,unverified_original_updates:2,accepted_date_only_formats:12},
      receiptFields:{}
    };
  }
  if (fingerprint===PQM_SANDBOX_PARTIAL_RECONCILIATION_APPEND_ONLY_FINGERPRINT_) {
    return {
      evidence:{
        evidence_version:1,
        plan_scope:'APPEND_ONLY',
        initial_plan:{append:351},
        attempted_chunk:0,
        checkpoint_present:false,
        audit_type:'READ_ONLY_SAVED_PREVIEW_AND_SHEETS',
        audit:{full_matches:25,partial_or_wrong_tab:0,missing:0,duplicates:0,
          saved_preview_binding:'PASS',writes_performed:0},
        recovery_disposition:'AUDIT_EVIDENCE_ONLY_NEW_PREVIEW_REQUIRED'
      },
      resultCounts:{audit_confirmed_existing_append_rows:25,checkpoint_receipts:0},
      receiptFields:{checkpointPresent:false,resumeAuthorized:false,nextAction:'NEW_PREVIEW_REQUIRED'},
      requireUncertainFirstChunk:true
    };
  }
  if (fingerprint===PQM_SANDBOX_PARTIAL_RECONCILIATION_LEGACY_20261108_FINGERPRINT_) {
    return {
      expectedRequestId:PQM_SANDBOX_PARTIAL_RECONCILIATION_LEGACY_20261108_REQUEST_ID_,
      evidence:{
        evidence_version:2,
        request_id:PQM_SANDBOX_PARTIAL_RECONCILIATION_LEGACY_20261108_REQUEST_ID_,
        plan_scope:'APPEND_ONLY',
        initial_plan:{append:326,update:2,conflict:2},
        attempted_chunk:0,
        checkpoint_present:false,
        saved_preview_source_digest:{present:false,historical_schema:'PRE_SOURCE_DIGEST',substitute_used:false},
        audit_type:'READ_ONLY_SAVED_PREVIEW_AND_LIVE_SHEETS',
        audit:{rows_found:25,full_matches:25,partial_rows:0,
          partial_operation_numbers:[],partial_columns:{I:0},
          missing:0,duplicates:0,wrong_tab:0,formula_a_matches:25,
          protected_cell_mutations:0,saved_preview_binding:'PASS',writes_performed:0},
        recovery_disposition:'FULL_FIRST_CHUNK_MATCH_NO_REAPPEND_NEW_PREVIEW_REQUIRED'
      },
      resultCounts:{rows_found:25,fully_matching_rows:25,partial_rows:0,
        unverified_column_i_rows:0,checkpoint_receipts:0},
      receiptFields:{checkpointPresent:false,resumeAuthorized:false,
        nextAction:'NEW_PREVIEW_REQUIRED',partialOperationNumbers:[]},
      profileVersion:2,
      requireUncertainFirstChunk:true
    };
  }
  return null;
}

function pqmSandboxAuditOnlyInitialRunValid_(run) {
  return !!run && run.planScope==='APPEND_ONLY' && run.state==='uncertain' &&
    run.uncertainChunk===0 && run.inflight===0 && run.nextChunk===0 &&
    Array.isArray(run.steps) && run.steps.length===0 &&
    !!run.aggregate && run.aggregate.append===0 && run.aggregate.update===0 &&
    run.aggregate.batches===0 && run.result===null;
}

function pqmSandboxCanonicalReconciliationJson_(value) {
  if (Array.isArray(value)) return '['+value.map(pqmSandboxCanonicalReconciliationJson_).join(',')+']';
  if (value && typeof value==='object') {
    return '{'+Object.keys(value).sort().map(function(key) {
      return JSON.stringify(key)+':'+pqmSandboxCanonicalReconciliationJson_(value[key]);
    }).join(',')+'}';
  }
  return JSON.stringify(value);
}

function pqmSandboxReconciliationDigest_(value) {
  return Utilities.base64EncodeWebSafe(Utilities.computeDigest(
    Utilities.DigestAlgorithm.SHA_256,pqmSandboxCanonicalReconciliationJson_(value),Utilities.Charset.UTF_8
  )).replace(/=+$/,'');
}

function pqmSandboxRequestFingerprint_(requestId) {
  var bytes=Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256,requestId,Utilities.Charset.UTF_8);
  return bytes.slice(0,12).map(function(value) {
    var n=(value+256)%256;
    return ('0'+n.toString(16)).slice(-2);
  }).join('');
}

function pqmSandboxReconcilePartial_(properties,request,receipt) {
  var profile=pqmSandboxPartialReconciliationProfile_(request.requestFingerprint);
  if (request.environment!=='SANDBOX' || PQM_MIRROR_ENV.environment!=='SANDBOX' ||
      request.trigger!=='manual' || !/^[0-9a-f]{32}$/.test(request.reconciliationId||'') ||
      request.expectedDigest!==null ||
      !profile ||
      (profile.expectedRequestId && request.requestId!==profile.expectedRequestId) ||
      pqmSandboxRequestFingerprint_(request.requestId)!==request.requestFingerprint)
    throw new Error('PQM: partial reconciliation identity rejected');
  var expectedEvidence=profile.evidence;
  if (pqmSandboxCanonicalReconciliationJson_(request.evidence)!==
        pqmSandboxCanonicalReconciliationJson_(expectedEvidence) ||
      !pqmSandboxIsCanonicalDigest_(request.evidenceDigest) ||
      pqmSandboxReconciliationDigest_(expectedEvidence)!==request.evidenceDigest)
    throw new Error('PQM: partial reconciliation evidence rejected');

  var runKey='PQM_EXECUTION_RUN_'+request.requestId;
  var eventKey='PQM_EXECUTION_RECONCILIATION_'+request.reconciliationId;
  var marker=properties.getProperty('PQM_EXECUTION_UNCERTAIN');
  var runRaw=properties.getProperty(runKey);
  var run=null,eventRaw=properties.getProperty(eventKey),event=null;
  try { if (runRaw) run=JSON.parse(runRaw); } catch (_) { run=null; }
  try { if (eventRaw) event=JSON.parse(eventRaw); } catch (_) { event=null; }
  if (!runRaw || !run || typeof run!=='object' || Array.isArray(run) ||
      typeof run.actor!=='string' || !run.actor || run.trigger!=='manual' ||
      !pqmSandboxIsCanonicalDigest_(run.digest))
    throw new Error('PQM: partial reconciliation run record rejected');

  if (eventRaw && (!event || event.reconciliationId!==request.reconciliationId ||
      event.requestFingerprint!==request.requestFingerprint || event.evidenceDigest!==request.evidenceDigest ||
      event.actor!==request.actor || event.requestId!==request.requestId ||
      event.environment!=='SANDBOX' || typeof event.originalRunRecordRaw!=='string' ||
      !['PREPARED','RECONCILED_PARTIAL'].includes(event.state)))
    throw new Error('PQM: existing reconciliation record mismatch');

  if (!event) {
    if (marker!==request.requestId || run.result!==null && run.result!==undefined)
      throw new Error('PQM: unresolved run state changed; reconciliation stopped');
    if (profile.requireUncertainFirstChunk && !pqmSandboxAuditOnlyInitialRunValid_(run))
      throw new Error('PQM: APPEND_ONLY first-chunk state is not the expected no-checkpoint state');
    event={state:'PREPARED',environment:'SANDBOX',requestId:request.requestId,
      requestFingerprint:request.requestFingerprint,reconciliationId:request.reconciliationId,
      evidenceDigest:request.evidenceDigest,evidence:expectedEvidence,actor:request.actor,
      preparedAt:new Date().toISOString(),originalRunRecordRaw:runRaw};
    properties.setProperty(eventKey,JSON.stringify(event));
  }

  if (event.state==='RECONCILED_PARTIAL') {
    if (!run.reconciliation || run.reconciliation.reconciliationId!==request.reconciliationId ||
        !run.result || run.result.status!=='RECONCILED_PARTIAL' ||
        run.result.evidenceDigest!==request.evidenceDigest)
      throw new Error('PQM: reconciled history is inconsistent');
    if (marker && marker!==request.requestId)
      throw new Error('PQM: a different uncertain run is active');
    if (marker===request.requestId) properties.deleteProperty('PQM_EXECUTION_UNCERTAIN');
    return run.result;
  }

  var originalRun;
  try { originalRun=JSON.parse(event.originalRunRecordRaw); } catch (_) { originalRun=null; }
  if (!originalRun || originalRun.result!==null && originalRun.result!==undefined ||
      originalRun.actor!==run.actor || originalRun.digest!==run.digest || originalRun.trigger!==run.trigger)
    throw new Error('PQM: original uncertain run evidence changed');
  if (profile.requireUncertainFirstChunk && !pqmSandboxAuditOnlyInitialRunValid_(originalRun))
    throw new Error('PQM: original APPEND_ONLY audit run did not have the expected no-checkpoint state');
  if (marker!==request.requestId)
    throw new Error('PQM: uncertain marker changed; reconciliation stopped');

  var result=receipt('RECONCILED_PARTIAL',profile.resultCounts,run.digest);
  Object.keys(profile.receiptFields).forEach(function(key) { result[key]=profile.receiptFields[key]; });
  result.reconciliationId=request.reconciliationId;
  result.requestFingerprint=request.requestFingerprint;
  result.evidenceDigest=request.evidenceDigest;
  run.reconciliation={reconciliationId:request.reconciliationId,
    evidenceDigest:request.evidenceDigest,status:'RECONCILED_PARTIAL',
    originalStatus:'outcome_unknown',recordedAt:new Date().toISOString()};
  Object.keys(profile.receiptFields).forEach(function(key) { run.reconciliation[key]=profile.receiptFields[key]; });
  run.result=result;
  properties.setProperty(runKey,JSON.stringify(run));
  event.state='RECONCILED_PARTIAL';
  event.reconciledAt=new Date().toISOString();
  event.result=result;
  properties.setProperty(eventKey,JSON.stringify(event));
  if (properties.getProperty('PQM_EXECUTION_UNCERTAIN')!==request.requestId)
    throw new Error('PQM: uncertain marker changed before final release');
  properties.deleteProperty('PQM_EXECUTION_UNCERTAIN');
  return result;
}
