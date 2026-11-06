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
      ['preview','apply','resume_check','reconcile_partial'].indexOf(request.action)<0 || ['manual','scheduled'].indexOf(request.trigger)<0 ||
      (request.action==='reconcile_partial' && request.trigger!=='manual') ||
      !/^[0-9a-f]{32}$/.test(request.requestId || '') ||
      typeof request.actor !== 'string' || !request.actor || request.actor.length>128 ||
      !Number.isInteger(request.issuedAt) || !Number.isInteger(request.expiresAt) ||
      request.issuedAt>now+30 || request.expiresAt<now || request.expiresAt-request.issuedAt>300 ||
      request.expiresAt<request.issuedAt ||
      (request.action==='apply' && (!pqmSandboxIsCanonicalDigest_(request.expectedDigest) ||
        !Number.isInteger(request.chunkIndex) || request.chunkIndex<0 || request.chunkIndex>499 ||
        ['ALL','APPEND_ONLY'].indexOf(request.planScope || 'ALL')<0)) ||
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
      if (request.action==='apply') value.planScope = planScope;
      return value;
    }
    var key='PQM_EXECUTION_RUN_'+request.requestId, stored=properties.getProperty(key);
    if (request.action==='reconcile_partial')
      return pqmSandboxReconcilePartial_(properties,request,receipt);
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
      record.state='uncertain';
      record.uncertainChunk=request.chunkIndex;
      try { pqmExecutionCheckpointSave_(properties,key,record,PQM_SANDBOX_EXECUTION_CHECKPOINT_MAX_BYTES); } catch (ignored) {}
      properties.setProperty('PQM_EXECUTION_UNCERTAIN',request.requestId);
      throw new Error('PQM: Apply may be partial; no retry, reconcile using a read-only audit');
    }
  } finally {
    PQM_EXECUTION_CONTEXT_=null;
    lock.releaseLock();
  }
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
    totals.append+=counts.append;
    totals.update+=counts.update;
    totals.batches+=counts.batches;
  }
  var aggregate=record.aggregate || {};
  if (record.steps.length && record.steps[record.steps.length-1].googleDigest!==record.googleDigest) return false;
  return aggregate.append===totals.append && aggregate.update===totals.update && aggregate.batches===totals.batches;
}

var PQM_SANDBOX_PARTIAL_RECONCILIATION_FINGERPRINT_='9be34ff2df1e661346176eeb';

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
  if (request.environment!=='SANDBOX' || PQM_MIRROR_ENV.environment!=='SANDBOX' ||
      request.trigger!=='manual' || !/^[0-9a-f]{32}$/.test(request.reconciliationId||'') ||
      request.expectedDigest!==null ||
      request.requestFingerprint!==PQM_SANDBOX_PARTIAL_RECONCILIATION_FINGERPRINT_ ||
      pqmSandboxRequestFingerprint_(request.requestId)!==request.requestFingerprint)
    throw new Error('PQM: partial reconciliation identity rejected');
  var expectedEvidence=pqmSandboxPartialReconciliationEvidence_();
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
  if (marker!==request.requestId)
    throw new Error('PQM: uncertain marker changed; reconciliation stopped');

  var result=receipt('RECONCILED_PARTIAL',{
    verified_append_rows:50,unverified_original_updates:2,accepted_date_only_formats:12
  },run.digest);
  result.reconciliationId=request.reconciliationId;
  result.requestFingerprint=request.requestFingerprint;
  result.evidenceDigest=request.evidenceDigest;
  run.reconciliation={reconciliationId:request.reconciliationId,
    evidenceDigest:request.evidenceDigest,status:'RECONCILED_PARTIAL',
    originalStatus:'outcome_unknown',recordedAt:new Date().toISOString()};
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
