/* Additive Sandbox ALL-scope Execution API entrypoint. The pinned legacy dispatcher remains unchanged. */
function pqmSandboxAllScopeExecution20261109(envelope) {
  var maxExecutionPayloadChars=8192;
  var maxReadOnlyPreflightPayloadChars=32768;
  if (!envelope || typeof envelope.payload !== 'string' ||
      envelope.payload.length > maxReadOnlyPreflightPayloadChars ||
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
  if (envelope.payload.length>maxExecutionPayloadChars && request.action!=='prewrite_close_preflight')
    throw new Error('PQM: oversized execution payload is restricted to read-only preflight');
  var closeAction=request.action==='close_unknown_run';
  var prewriteCloseAction=request.action==='close_prewrite_failure';
  var prewriteCheckAction=request.action==='prewrite_close_preflight';
  var prewriteEvidenceAction=prewriteCloseAction||prewriteCheckAction;
  var appendRecovery=request.action==='recover_append_chunk';
  if (request.environment!=='SANDBOX' ||
      (closeAction ? ['ALL','APPEND_ONLY'].indexOf(request.planScope)<0 :
        (prewriteEvidenceAction ? request.planScope!=='APPEND_ONLY' :
        (appendRecovery ? request.planScope!=='APPEND_ONLY' : request.planScope!=='ALL'))) ||
      request.trigger!=='manual' ||
      ['apply','recover_apply_chunk','recover_append_chunk','close_unknown_run','close_prewrite_failure','prewrite_close_preflight'].indexOf(request.action)<0 ||
      request.requestId==='592128d9837d4b71bbeb330ef8aabf4b')
    throw new Error('PQM: additive ALL-scope endpoint rejects this action or scope');
  if (closeAction && (!/^[0-9a-f]{32}$/.test(request.closeId || '') ||
      !pqmSandboxIsCanonicalDigest_(request.expectedDigest) ||
      !pqmSandboxIsCanonicalDigest_(request.closeEvidenceDigest) ||
      !pqmSandboxIsCanonicalDigest_(request.reasonDigest)))
    throw new Error('PQM: administrative close binding rejected');
  if (prewriteEvidenceAction && (!pqmSandboxIsCanonicalDigest_(request.expectedDigest) ||
      !pqmSandboxIsCanonicalDigest_(request.targetIdentityDigest) ||
      !pqmSandboxIsCanonicalDigest_(request.chunkDigest) ||
      !/^[0-9a-f]{32}$/.test(request.chunkId || '') || request.planId!==request.requestId ||
      request.chunkIndex!==0 || !/^[A-Za-z0-9_]{1,40}$/.test(request.prewriteStage || '') ||
      !Array.isArray(request.targetIdentities) || request.targetIdentities.length<1 ||
      request.targetIdentities.length>25))
    throw new Error('PQM: prewrite evidence binding rejected');
  if (prewriteCloseAction && (!/^[0-9a-f]{32}$/.test(request.closeId || '') ||
      !pqmSandboxIsCanonicalDigest_(request.closeEvidenceDigest) ||
      !pqmSandboxIsCanonicalDigest_(request.reasonDigest)))
    throw new Error('PQM: prewrite close authorization binding rejected');
  if (prewriteEvidenceAction && request.prewriteStage==='LEGACY_V1_WRITEAHEAD_LIMIT_PROOF_V1' &&
      (request.requestId!=='b11433e8efb84b4492bf2df7c7c25908' ||
       !pqmSandboxIsCanonicalDigest_(request.legacyManifestProjectionDigest) ||
       !Array.isArray(request.legacyManifestRows) || request.legacyManifestRows.length<1 ||
       request.legacyManifestRows.length>25))
    throw new Error('PQM: historical v1 manifest proof is not allowed');
  if (prewriteEvidenceAction && request.prewriteStage!=='LEGACY_V1_WRITEAHEAD_LIMIT_PROOF_V1' &&
      (request.legacyManifestRows!==undefined || request.legacyManifestProjectionDigest!==undefined))
    throw new Error('PQM: unexpected legacy manifest proof fields');
  if (appendRecovery && (!pqmSandboxIsCanonicalDigest_(request.expectedDigest) ||
      !Number.isInteger(request.chunkIndex) || request.chunkIndex<0 || request.chunkIndex>499 ||
      !/^[0-9a-f]{32}$/.test(request.chunkId || '') ||
      !pqmSandboxIsCanonicalDigest_(request.chunkDigest) || request.planId!==request.requestId))
    throw new Error('PQM: APPEND_ONLY recovery binding rejected');
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
      ['preview','apply','resume_check','recover_append_chunk','recover_apply_chunk','reconcile_partial','close_unknown_run','close_prewrite_failure','prewrite_close_preflight'].indexOf(request.action)<0 || ['manual','scheduled'].indexOf(request.trigger)<0 ||
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
      (request.action==='close_unknown_run' && (request.environment!=='SANDBOX' || request.trigger!=='manual' ||
        ['ALL','APPEND_ONLY'].indexOf(request.planScope)<0 ||
        !/^[0-9a-f]{32}$/.test(request.closeId || '') ||
        !pqmSandboxIsCanonicalDigest_(request.expectedDigest) ||
        !pqmSandboxIsCanonicalDigest_(request.closeEvidenceDigest) ||
        !pqmSandboxIsCanonicalDigest_(request.reasonDigest))) ||
      (request.action==='close_prewrite_failure' && (request.environment!=='SANDBOX' || request.trigger!=='manual' ||
        request.planScope!=='APPEND_ONLY' || !/^[0-9a-f]{32}$/.test(request.closeId || '') ||
        !pqmSandboxIsCanonicalDigest_(request.expectedDigest) ||
        !pqmSandboxIsCanonicalDigest_(request.closeEvidenceDigest) ||
        !pqmSandboxIsCanonicalDigest_(request.reasonDigest) ||
        !pqmSandboxIsCanonicalDigest_(request.targetIdentityDigest) ||
        !/^[0-9a-f]{32}$/.test(request.chunkId || '') || !pqmSandboxIsCanonicalDigest_(request.chunkDigest) ||
        request.planId!==request.requestId || request.chunkIndex!==0 ||
        !/^[A-Za-z0-9_]{1,40}$/.test(request.prewriteStage || '') ||
        !Array.isArray(request.targetIdentities) || request.targetIdentities.length<1 ||
        request.targetIdentities.length>25)) ||
      (request.action==='prewrite_close_preflight' && (request.environment!=='SANDBOX' || request.trigger!=='manual' ||
        request.planScope!=='APPEND_ONLY' || !pqmSandboxIsCanonicalDigest_(request.expectedDigest) ||
        !pqmSandboxIsCanonicalDigest_(request.targetIdentityDigest) || !/^[0-9a-f]{32}$/.test(request.chunkId || '') ||
        !pqmSandboxIsCanonicalDigest_(request.chunkDigest) || request.planId!==request.requestId || request.chunkIndex!==0 ||
        !/^[A-Za-z0-9_]{1,40}$/.test(request.prewriteStage || '') ||
        !Array.isArray(request.targetIdentities) || request.targetIdentities.length<1 ||
        request.targetIdentities.length>25 || request.closeId!==undefined ||
        request.closeEvidenceDigest!==undefined || request.reasonDigest!==undefined)) ||
      (request.action==='resume_check' && (request.environment!=='SANDBOX' || request.trigger!=='manual' ||
        !pqmSandboxIsCanonicalDigest_(request.expectedDigest) || !pqmSandboxIsCanonicalDigest_(request.expectedCheckpointDigest) ||
        !Number.isInteger(request.chunkIndex) || request.chunkIndex<1 || request.chunkIndex>499 ||
        request.planScope!=='APPEND_ONLY')))
    throw new Error('PQM: execution identity or lifetime rejected');
  if (PQM_EXECUTION_CONTEXT_) throw new Error('PQM: nested execution rejected');
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(0)) throw new Error('PQM: another writer is running; zero writes');
  try {
    if (closeAction) return pqmSandboxCloseUnknownRun20261109_(properties,request);
    if (prewriteEvidenceAction) return pqmSandboxClosePrewriteFailure20261109_(request.spreadsheetId,properties,request);
    var closeTombstone=properties.getProperty('PQM_EXECUTION_CLOSED_'+request.requestId);
    var prewriteTombstone=properties.getProperty('PQM_EXECUTION_PREWRITE_CLOSED_'+request.requestId);
    if ((closeTombstone || prewriteTombstone) && request.action!=='preview')
      throw new Error('PQM: administratively closed run is permanently non-replayable');
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
        var storedManifest=record.inflightManifest;
        record.state='ready'; record.inflight=null; record.inflightManifest=null; record.uncertainChunk=null;
        record.lastError={stage:stage,category:'prewrite_rejected',exceptionType:exceptionType};
        pqmExecutionCheckpointSave_(properties,key,record,PQM_SANDBOX_EXECUTION_CHECKPOINT_MAX_BYTES);
        pqmExecutionCheckpointDeleteManifestShards_(properties,request.requestId,storedManifest);
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

function pqmSandboxCloseUnknownRun20261109_(properties,request) {
  var runKey='PQM_EXECUTION_RUN_'+request.requestId;
  var closeKey='PQM_EXECUTION_CLOSED_'+request.requestId;
  function digest(value) {
    return Utilities.base64EncodeWebSafe(
      Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256,value,Utilities.Charset.UTF_8)).replace(/=+$/,'');
  }
  function receiptFrom(event,idempotent) {
    var value={environment:'SANDBOX',scriptId:request.scriptId,spreadsheetId:request.spreadsheetId,
      contract:request.contract,requestId:request.requestId,status:'ADMIN_CLOSED_UNKNOWN',
      closeId:request.closeId,planScope:request.planScope,
      disposition:'OUTCOME_UNKNOWN_NOT_CONFIRMED',evidenceDigest:request.closeEvidenceDigest,
      reasonDigest:request.reasonDigest,runRecordDigest:event.runRecordDigest,
      closedAt:event.closedAt,actor:request.actor};
    value.digest=digest(['environment','scriptId','spreadsheetId','contract','requestId','status',
      'closeId','planScope','disposition','evidenceDigest','reasonDigest','runRecordDigest',
      'closedAt','actor'].map(function(key){return value[key];}).join('\n'));
    value.idempotent=!!idempotent;
    return value;
  }
  var marker=properties.getProperty('PQM_EXECUTION_UNCERTAIN');
  var saved=properties.getProperty(closeKey),event=null;
  if (saved!==null) {
    try { event=JSON.parse(saved); } catch (_) { throw new Error('PQM: administrative close tombstone is invalid'); }
    if (!event || event.version!==1 || event.requestId!==request.requestId ||
        event.closeId!==request.closeId || event.planScope!==request.planScope ||
        event.actor!==request.actor || event.expectedDigest!==request.expectedDigest ||
        event.evidenceDigest!==request.closeEvidenceDigest ||
        event.reasonDigest!==request.reasonDigest ||
        !pqmSandboxIsCanonicalDigest_(event.runRecordDigest) ||
        !pqmSandboxIsCanonicalDigest_(event.digest) ||
        event.digest!==digest(['version','environment','scriptId','spreadsheetId','contract',
          'requestId','status','closeId','planScope','disposition','evidenceDigest','reasonDigest',
          'runRecordDigest','expectedDigest','actor','closedAt'].map(function(key){return event[key];}).join('\n')))
      throw new Error('PQM: administrative close retry binding rejected');
    if (marker && marker!==request.requestId)
      throw new Error('PQM: another uncertain run remains active');
    if (marker===request.requestId) properties.deleteProperty('PQM_EXECUTION_UNCERTAIN');
    return receiptFrom(event,true);
  }
  if (marker!==request.requestId)
    throw new Error('PQM: uncertain marker no longer matches the requested run');
  var raw=properties.getProperty(runKey),record=null;
  if (typeof raw!=='string' || !raw) throw new Error('PQM: uncertain Apps Script run record is missing');
  try { record=JSON.parse(raw); } catch (_) { throw new Error('PQM: uncertain Apps Script run record is invalid'); }
  var recordedScope=record && (record.planScope || (record.chunkJournalVersion===1?'APPEND_ONLY':null));
  if (!record || record.state!=='uncertain' || recordedScope!==request.planScope ||
      record.digest!==request.expectedDigest)
    throw new Error('PQM: uncertain Apps Script run binding changed');
  var runRecordDigest=digest(raw);
  var closedAt=new Date().toISOString();
  event={version:1,environment:'SANDBOX',scriptId:request.scriptId,
    spreadsheetId:request.spreadsheetId,contract:request.contract,
    requestId:request.requestId,status:'ADMIN_CLOSED_UNKNOWN',closeId:request.closeId,
    planScope:request.planScope,disposition:'OUTCOME_UNKNOWN_NOT_CONFIRMED',
    evidenceDigest:request.closeEvidenceDigest,reasonDigest:request.reasonDigest,
    runRecordDigest:runRecordDigest,expectedDigest:request.expectedDigest,
    actor:request.actor,closedAt:closedAt};
  event.digest=digest(['version','environment','scriptId','spreadsheetId','contract','requestId',
    'status','closeId','planScope','disposition','evidenceDigest','reasonDigest','runRecordDigest',
    'expectedDigest','actor','closedAt'].map(function(key){return event[key];}).join('\n'));
  // Durable non-success tombstone first; release the global hold only after it exists.
  properties.setProperty(closeKey,JSON.stringify(event));
  if (properties.getProperty('PQM_EXECUTION_UNCERTAIN')!==request.requestId)
    throw new Error('PQM: uncertain marker changed before administrative release');
  properties.deleteProperty('PQM_EXECUTION_UNCERTAIN');
  return receiptFrom(event,false);
}

/* Close only a positively identified APPEND_ONLY prewrite rejection; this never issues a Sheets write. */
function pqmSandboxClosePrewriteFailure20261109_(id,properties,request) {
  var readOnlyCheck=request.action==='prewrite_close_preflight';
  var closeKey='PQM_EXECUTION_PREWRITE_CLOSED_'+request.requestId;
  var legacyCloseKey='PQM_EXECUTION_CLOSED_'+request.requestId;
  var runKey='PQM_EXECUTION_RUN_'+request.requestId;
  var allowedStages=['source_and_sheet_guard','chunk_selection','append_prewrite_guard',
    'append_request_build','append_inflight_save'];
  var legacyLimitProof=request.prewriteStage==='LEGACY_V1_WRITEAHEAD_LIMIT_PROOF_V1';
  function digest(value) {
    return Utilities.base64EncodeWebSafe(
      Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256,value,Utilities.Charset.UTF_8)).replace(/=+$/,'');
  }
  function receiptFrom(event,idempotent) {
    var value={environment:'SANDBOX',scriptId:request.scriptId,spreadsheetId:request.spreadsheetId,
      contract:request.contract,requestId:request.requestId,status:'ADMIN_CLOSED_PREWRITE_NO_WRITE',
      closeId:request.closeId,planScope:'APPEND_ONLY',
      disposition:'PREWRITE_FAILURE_CONFIRMED_NO_SHEET_WRITE',
      evidenceDigest:request.closeEvidenceDigest,reasonDigest:request.reasonDigest,
      chunkId:request.chunkId,chunkDigest:request.chunkDigest,chunkIndex:0,
      targetIdentityDigest:request.targetIdentityDigest,prewriteStage:event.prewriteStage,
      runRecordDigest:event.runRecordDigest,closedAt:event.closedAt,actor:request.actor,
      proofType:event.proofType,writeAheadBytes:event.writeAheadBytes,
      checkpointMaxBytes:event.checkpointMaxBytes,
      legacyManifestProjectionDigest:event.legacyManifestProjectionDigest};
    value.digest=digest(['environment','scriptId','spreadsheetId','contract','requestId','status',
      'closeId','planScope','disposition','evidenceDigest','reasonDigest','chunkId','chunkDigest',
      'chunkIndex','targetIdentityDigest','prewriteStage','runRecordDigest','closedAt','actor','proofType',
      'writeAheadBytes','checkpointMaxBytes','legacyManifestProjectionDigest']
      .map(function(key){return String(value[key]);}).join('\n'));
    value.idempotent=!!idempotent;
    return value;
  }
  function preflightResult(status,reasonCodes,extra) {
    return Object.assign({environment:request.environment,scriptId:request.scriptId,
      spreadsheetId:request.spreadsheetId,contract:request.contract,requestId:request.requestId,
      status:status,digest:request.expectedDigest,planScope:'APPEND_ONLY',chunkIndex:0,
      chunkId:request.chunkId,chunkDigest:request.chunkDigest,
      targetIdentityDigest:request.targetIdentityDigest,prewriteStage:request.prewriteStage,
      targetCount:identities.length,targetCodeMatches:0,runMarkerMatches:0,
      writeAheadBytes:0,checkpointMaxBytes:PQM_SANDBOX_EXECUTION_CHECKPOINT_MAX_BYTES,
      proofType:'APPS_SCRIPT_LAST_ERROR',runRecordDigest:'',legacyManifestProjectionDigest:'',
      reasonCodes:reasonCodes||[],readOnly:true},extra||{});
  }
  if (properties.getProperty(legacyCloseKey)!==null)
    throw new Error('PQM: another administrative close already owns this run');
  var identities=request.targetIdentities.map(function(item) {
    if (!item || Object.keys(item).sort().join(',')!=='code,tab' ||
        ['ФОП','ЮО'].indexOf(item.tab)<0 || typeof item.code!=='string' ||
        !/^\d{8,10}$/.test(item.code) || item.code!==item.code.trim())
      throw new Error('PQM: prewrite target identity rejected');
    return [item.tab,item.code];
  });
  var uniqueCodes=Object.create(null);
  identities.forEach(function(item) {
    if (uniqueCodes[item[1]]) throw new Error('PQM: duplicate prewrite target identity rejected');
    uniqueCodes[item[1]]=true;
  });
  if (digest(JSON.stringify(identities))!==request.targetIdentityDigest)
    throw new Error('PQM: prewrite target identity digest mismatch');
  var marker=properties.getProperty('PQM_EXECUTION_UNCERTAIN');
  var saved=readOnlyCheck?null:properties.getProperty(closeKey),event=null;
  if (readOnlyCheck && properties.getProperty(closeKey)!==null)
    return preflightResult('BLOCKED',['APPS_SCRIPT_TOMBSTONE_EXISTS']);
  if (readOnlyCheck && properties.getProperty(legacyCloseKey)!==null)
    return preflightResult('BLOCKED',['LEGACY_CLOSE_EXISTS']);
  if (saved!==null) {
    try { event=JSON.parse(saved); } catch (_) { throw new Error('PQM: prewrite close tombstone invalid'); }
    if (!event || event.version!==1 || event.requestId!==request.requestId ||
        event.closeId!==request.closeId || event.planScope!=='APPEND_ONLY' ||
        event.expectedDigest!==request.expectedDigest || event.evidenceDigest!==request.closeEvidenceDigest ||
        event.reasonDigest!==request.reasonDigest || event.chunkId!==request.chunkId ||
        event.chunkDigest!==request.chunkDigest || event.chunkIndex!==0 ||
        event.targetIdentityDigest!==request.targetIdentityDigest ||
        ((request.prewriteStage==='APPS_SCRIPT_PREWRITE_GUARD_V1' || legacyLimitProof) ?
          allowedStages.indexOf(event.prewriteStage)<0 : event.prewriteStage!==request.prewriteStage) ||
        (legacyLimitProof && event.legacyManifestProjectionDigest!==request.legacyManifestProjectionDigest) ||
        event.actor!==request.actor || !pqmSandboxIsCanonicalDigest_(event.runRecordDigest) ||
        !pqmSandboxIsCanonicalDigest_(event.digest) ||
        event.digest!==digest(['version','environment','scriptId','spreadsheetId','contract','requestId','status',
          'closeId','planScope','disposition','evidenceDigest','reasonDigest','chunkId','chunkDigest','chunkIndex',
          'targetIdentityDigest','prewriteStage','runRecordDigest','expectedDigest','actor','closedAt','proofType',
          'writeAheadBytes','checkpointMaxBytes','legacyManifestProjectionDigest']
          .map(function(key){return String(event[key]);}).join('\n')))
      throw new Error('PQM: prewrite close retry binding rejected');
    if (marker && marker!==request.requestId) {
      if (readOnlyCheck) return preflightResult('BLOCKED',['UNCERTAINTY_MARKER_MISMATCH']);
      throw new Error('PQM: another uncertain run remains active');
    }
    if (marker===request.requestId) properties.deleteProperty('PQM_EXECUTION_UNCERTAIN');
    return receiptFrom(event,true);
  }
  if (marker!==request.requestId) {
    if (readOnlyCheck) return preflightResult('BLOCKED',['UNCERTAINTY_MARKER_MISMATCH']);
    throw new Error('PQM: uncertain marker no longer matches the requested run');
  }
  var raw=properties.getProperty(runKey),record=null;
  if (typeof raw!=='string' || !raw) {
    if (readOnlyCheck) return preflightResult('BLOCKED',['RUN_RECORD_INVALID']);
    throw new Error('PQM: prewrite Apps Script run record missing');
  }
  try { record=JSON.parse(raw); } catch (_) {
    if (readOnlyCheck) return preflightResult('BLOCKED',['RUN_RECORD_INVALID']);
    throw new Error('PQM: prewrite Apps Script run record invalid');
  }
  var aggregate=record && record.aggregate, lastError=record && record.lastError;
  if (!record || record.state!=='ready' || record.planScope!=='APPEND_ONLY' ||
      record.chunkJournalVersion!==1 || record.digest!==request.expectedDigest ||
      record.nextChunk!==0 || record.inflight!==null ||
      (record.inflightManifest!==null && record.inflightManifest!==undefined) ||
      (record.uncertainChunk!==null && record.uncertainChunk!==undefined) ||
      !Array.isArray(record.steps) || record.steps.length!==0 || !aggregate ||
      aggregate.append!==0 || aggregate.update!==0 || aggregate.batches!==0 || record.result!==null)
    {
      if (readOnlyCheck) return preflightResult('BLOCKED',['RUN_NOT_UNTOUCHED'],
        {runRecordDigest:digest(raw)});
      throw new Error('PQM: Apps Script record does not prove an untouched prewrite failure');
    }
  var proofType='APPS_SCRIPT_LAST_ERROR',proofStage=null,writeAheadBytes=0,checkpointMaxBytes=0;
  var legacyProjectionDigest='';
  if (legacyLimitProof) {
    if (request.requestId!=='b11433e8efb84b4492bf2df7c7c25908' ||
        !Array.isArray(request.legacyManifestRows) || request.legacyManifestRows.length!==identities.length)
      throw new Error('PQM: historical v1 manifest proof is not allowed');
    var projection=request.legacyManifestRows.map(function(item) {
      if (!item || Object.keys(item).sort().join(',')!=='code,formulaA,row,tab' ||
          ['ФОП','ЮО'].indexOf(item.tab)<0 || !Number.isInteger(item.row) || item.row<2 ||
          typeof item.code!=='string' || !/^\d{8,10}$/.test(item.code) ||
          typeof item.formulaA!=='string' || item.formulaA.charAt(0)!=='=')
        throw new Error('PQM: legacy manifest projection rejected');
      return {code:item.code,formulaA:item.formulaA,row:item.row,tab:item.tab};
    });
    if (projection.length!==request.targetIdentities.length ||
        projection.some(function(item,index) {
          return item.tab!==request.targetIdentities[index].tab || item.code!==request.targetIdentities[index].code;
        })) throw new Error('PQM: legacy manifest projection identity mismatch');
    if (digest(JSON.stringify(projection))!==request.legacyManifestProjectionDigest)
      throw new Error('PQM: legacy manifest projection digest mismatch');
    legacyProjectionDigest=request.legacyManifestProjectionDigest;
    if (lastError!==null && lastError!==undefined)
      {
        if (readOnlyCheck) return preflightResult('BLOCKED',['PREWRITE_STAGE_UNVERIFIED'],
          {runRecordDigest:digest(raw)});
        throw new Error('PQM: legacy v1 proof cannot override a saved Apps Script error stage');
      }
    var manifestRows=projection.map(function(item) {
      return {tab:item.tab,row:item.row,code:item.code,cellsDigest:'A'.repeat(43),formulaA:item.formulaA,
        serviceMetadata:{addedAt:'2000-01-01T00:00:00+00:00',planId:request.planId,runId:request.requestId}};
    });
    var probe=JSON.parse(JSON.stringify(record));
    probe.inflight=request.chunkIndex;
    probe.planId=request.planId;
    probe.runId=request.requestId;
    probe.chunkJournalVersion=1;
    probe.inflightManifest={chunkId:request.chunkId,chunkDigest:request.chunkDigest,
      planId:request.planId,runId:request.requestId,rows:manifestRows};
    probe.state='writing';
    probe.lastStage='append_inflight_save';
    writeAheadBytes=Utilities.newBlob(JSON.stringify(probe),'application/json').getBytes().length;
    checkpointMaxBytes=PQM_SANDBOX_EXECUTION_CHECKPOINT_MAX_BYTES;
    if (writeAheadBytes<=checkpointMaxBytes) {
      if (readOnlyCheck) return preflightResult('BLOCKED',['MANIFEST_NOT_OVERSIZED'],
        {writeAheadBytes:writeAheadBytes,checkpointMaxBytes:checkpointMaxBytes,
         proofType:'LEGACY_V1_WRITEAHEAD_OVERSIZE',runRecordDigest:digest(raw),
         legacyManifestProjectionDigest:legacyProjectionDigest});
      throw new Error('PQM: reconstructed legacy v1 write-ahead record fits the old bound');
    }
    proofType='LEGACY_V1_WRITEAHEAD_OVERSIZE';
    proofStage='append_inflight_save';
  } else {
    if (!lastError || lastError.category!=='prewrite_rejected' || allowedStages.indexOf(lastError.stage)<0 ||
        (request.prewriteStage!=='APPS_SCRIPT_PREWRITE_GUARD_V1' && lastError.stage!==request.prewriteStage))
      {
        if (readOnlyCheck) return preflightResult('BLOCKED',['PREWRITE_STAGE_UNVERIFIED'],
          {runRecordDigest:digest(raw)});
        throw new Error('PQM: Apps Script record does not prove an untouched prewrite failure');
      }
    proofStage=lastError.stage;
  }
  var runRecordDigest=digest(raw);

  // Read-only sheet evidence: reject closure if any planned identity exists anywhere or
  // if the run marker is present in the writer service column on either target tab.
  var metadata=Sheets.Spreadsheets.get(id,{includeGridData:false,
    fields:'sheets(properties(title,sheetId,gridProperties(rowCount,columnCount)))'});
  var tabs=Object.create(null);
  (metadata.sheets||[]).forEach(function(sheet) {
    var p=sheet.properties||{},g=p.gridProperties||{};
    if (typeof p.title==='string') tabs[p.title]={id:p.sheetId,maxRows:g.rowCount,maxColumns:g.columnCount};
  });
  PQM_GOOGLE_TABS.forEach(function(name) {
    if (!tabs[name] || !Number.isInteger(tabs[name].maxRows) || tabs[name].maxRows<2 ||
        !Number.isInteger(tabs[name].maxColumns) || tabs[name].maxColumns<19)
      {
        if (readOnlyCheck) return;
        throw new Error('PQM: prewrite sheet identity scan bounds unavailable');
      }
  });
  if (readOnlyCheck && PQM_GOOGLE_TABS.some(function(name) {
      var tab=tabs[name]; return !tab || !Number.isInteger(tab.maxRows) || tab.maxRows<2 ||
        !Number.isInteger(tab.maxColumns) || tab.maxColumns<19;
  })) return preflightResult('BLOCKED',['SHEET_BOUNDS_UNAVAILABLE'],{runRecordDigest:runRecordDigest});
  var selected=identities.map(function(item){return {cells:{1:item[1]}};});
  var counts;
  try { counts=pqmSandboxAppendCodeCounts_(id,tabs,selected); }
  catch (scanError) {
    if (readOnlyCheck) return preflightResult('BLOCKED',['SHEET_READ_INCOMPLETE'],
      {runRecordDigest:runRecordDigest,writeAheadBytes:writeAheadBytes,checkpointMaxBytes:checkpointMaxBytes,
       proofType:proofType,legacyManifestProjectionDigest:legacyProjectionDigest});
    throw scanError;
  }
  var targetCodeMatches=0;
  counts.forEach(function(count) {
    targetCodeMatches+=count;
    if (count!==0 && !readOnlyCheck) throw new Error('PQM: planned APPEND identity exists; prewrite closure refused');
  });
  var runMarkerMatches=0,markerScanIncomplete=false;
  PQM_GOOGLE_TABS.forEach(function(name) {
    var tab=tabs[name],esc="'"+name.replace(/'/g,"''")+"'";
    for (var first=2;first<=tab.maxRows;first+=PQM_SANDBOX_APPEND_CODE_SCAN_ROWS) {
      var last=Math.min(tab.maxRows,first+PQM_SANDBOX_APPEND_CODE_SCAN_ROWS-1);
      var response=Sheets.Spreadsheets.Values.batchGet(id,{ranges:[esc+'!S'+first+':S'+last],
        valueRenderOption:'UNFORMATTED_VALUE'});
      if (!response || !Array.isArray(response.valueRanges) || response.valueRanges.length!==1) {
        if (readOnlyCheck) { markerScanIncomplete=true; return; }
        throw new Error('PQM: prewrite run-marker scan incomplete');
      }
      (response.valueRanges[0].values||[]).forEach(function(row) {
        if (String((row||[])[0]||'')===request.requestId) {
          runMarkerMatches++;
          if (!readOnlyCheck) throw new Error('PQM: run marker exists; prewrite closure refused');
        }
      });
    }
  });
  if (readOnlyCheck) {
    if (markerScanIncomplete) return preflightResult('BLOCKED',['SHEET_READ_INCOMPLETE'],
      {runRecordDigest:runRecordDigest,targetCodeMatches:targetCodeMatches,
       writeAheadBytes:writeAheadBytes,checkpointMaxBytes:checkpointMaxBytes,proofType:proofType,
       legacyManifestProjectionDigest:legacyProjectionDigest});
    var reasons=[];
    if (targetCodeMatches) reasons.push('TARGET_CODES_PRESENT');
    if (runMarkerMatches) reasons.push('RUN_MARKER_PRESENT');
    var ready=reasons.length===0;
    return preflightResult(ready?'READY':'BLOCKED',reasons,{runRecordDigest:runRecordDigest,
      targetCodeMatches:targetCodeMatches,runMarkerMatches:runMarkerMatches,
      writeAheadBytes:writeAheadBytes,checkpointMaxBytes:checkpointMaxBytes,proofType:proofType,
      prewriteStage:proofStage,legacyManifestProjectionDigest:legacyProjectionDigest});
  }
  event={version:1,environment:'SANDBOX',scriptId:request.scriptId,spreadsheetId:request.spreadsheetId,
    contract:request.contract,requestId:request.requestId,status:'ADMIN_CLOSED_PREWRITE_NO_WRITE',
    closeId:request.closeId,planScope:'APPEND_ONLY',disposition:'PREWRITE_FAILURE_CONFIRMED_NO_SHEET_WRITE',
    evidenceDigest:request.closeEvidenceDigest,reasonDigest:request.reasonDigest,
    chunkId:request.chunkId,chunkDigest:request.chunkDigest,chunkIndex:0,
    targetIdentityDigest:request.targetIdentityDigest,prewriteStage:proofStage,
    runRecordDigest:runRecordDigest,expectedDigest:request.expectedDigest,actor:request.actor,
    closedAt:new Date().toISOString(),proofType:proofType,writeAheadBytes:writeAheadBytes,
    checkpointMaxBytes:checkpointMaxBytes,legacyManifestProjectionDigest:legacyProjectionDigest};
  event.digest=digest(['version','environment','scriptId','spreadsheetId','contract','requestId','status',
    'closeId','planScope','disposition','evidenceDigest','reasonDigest','chunkId','chunkDigest','chunkIndex',
    'targetIdentityDigest','prewriteStage','runRecordDigest','expectedDigest','actor','closedAt','proofType',
    'writeAheadBytes','checkpointMaxBytes','legacyManifestProjectionDigest']
    .map(function(key){return String(event[key]);}).join('\n'));
  // Save an immutable non-success tombstone before releasing the global uncertainty marker.
  properties.setProperty(closeKey,JSON.stringify(event));
  if (properties.getProperty('PQM_EXECUTION_UNCERTAIN')!==request.requestId)
    throw new Error('PQM: uncertainty marker changed before prewrite close release');
  properties.deleteProperty('PQM_EXECUTION_UNCERTAIN');
  return receiptFrom(event,false);
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
  var prior=record.steps && record.steps[request.chunkIndex];
  if (['ready','complete'].indexOf(record.state)>=0 && prior && prior.verified===true &&
      prior.chunkId===request.chunkId && prior.chunkDigest===request.chunkDigest &&
      prior.planId===request.planId && prior.phase===request.chunkPhase && prior.planScope==='ALL' &&
      pqmSandboxIsCanonicalDigest_(prior.checkpointDigest)) {
    var priorReceipt=pqmExecutionCheckpointReceipt_(request,receipt,prior);
    priorReceipt.status='CHUNK_RECOVERED';
    return priorReceipt;
  }
  var storedManifest=record.inflightManifest;
  var manifest=pqmExecutionCheckpointResolveManifest_(properties,request.requestId,storedManifest);
  var marker=properties.getProperty('PQM_EXECUTION_UNCERTAIN');
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
    if (['ready','complete'].indexOf(record.state)>=0 && saved && saved.verified===true &&
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
  pqmExecutionCheckpointDeleteManifestShards_(properties,request.requestId,storedManifest);
  var recovered=pqmExecutionCheckpointReceipt_(request,receipt,step);
  recovered.status='CHUNK_RECOVERED';
  return recovered;
}

var PQM_SANDBOX_PARTIAL_RECONCILIATION_FINGERPRINT_='9be34ff2df1e661346176eeb';
var PQM_SANDBOX_PARTIAL_RECONCILIATION_APPEND_ONLY_FINGERPRINT_='30331b560493209210f1e507';
var PQM_SANDBOX_PARTIAL_RECONCILIATION_LEGACY_20261108_FINGERPRINT_='816c6424279bff220878b0c4';
var PQM_SANDBOX_PARTIAL_RECONCILIATION_LEGACY_20261108_REQUEST_ID_='592128d9837d4b71bbeb330ef8aabf4b';
var PQM_SANDBOX_PARTIAL_RECONCILIATION_LEGACY_20261108_V1_STATUS_='RETIRED_INVALID_DATE_NORMALIZATION_EVIDENCE';
