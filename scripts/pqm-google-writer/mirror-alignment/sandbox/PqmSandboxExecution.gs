/* Server-authenticated API entrypoint; uses the existing planner and DailySync only. */
function pqmSandboxExecution(envelope) {
  if (!envelope || typeof envelope.payload !== 'string' || envelope.payload.length > 8192 ||
      typeof envelope.signature !== 'string') throw new Error('PQM: invalid execution envelope');
  var properties = PropertiesService.getScriptProperties();
  var secret = properties.getProperty('PQM_EXECUTION_SHARED_SECRET');
  if (!secret || secret.length < 32) throw new Error('PQM: execution authorization not configured');
  var signature = Utilities.base64EncodeWebSafe(
    Utilities.computeHmacSha256Signature(envelope.payload, secret)).replace(/=+$/, '');
  var different = signature.length ^ envelope.signature.length;
  for (var n=0; n<signature.length; n++) different |= signature.charCodeAt(n) ^ (envelope.signature.charCodeAt(n) || 0);
  if (different) throw new Error('PQM: execution authorization rejected');
  var request = JSON.parse(envelope.payload), now = Math.floor(Date.now()/1000);
  if (request.environment !== PQM_MIRROR_ENV.environment || request.scriptId !== PQM_MIRROR_ENV.scriptId ||
      ScriptApp.getScriptId() !== PQM_MIRROR_ENV.scriptId || request.spreadsheetId !== PQM_MIRROR_ENV.spreadsheetId ||
      request.contract !== 'pqm-mirror-datetime-v1' ||
      ['preview','apply'].indexOf(request.action)<0 || ['manual','scheduled'].indexOf(request.trigger)<0 ||
      !/^[0-9a-f]{32}$/.test(request.requestId || '') ||
      typeof request.actor !== 'string' || !request.actor || request.actor.length>128 ||
      !Number.isInteger(request.issuedAt) || !Number.isInteger(request.expiresAt) ||
      request.issuedAt>now+30 || request.expiresAt<now || request.expiresAt-request.issuedAt>300 ||
      request.expiresAt<request.issuedAt ||
      (request.action==='apply' && !/^[0-9a-f]{64}$/.test(request.expectedDigest || '')))
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
    function receipt(status,counts,digest) {
      return {environment:request.environment,scriptId:request.scriptId,spreadsheetId:request.spreadsheetId,
        contract:request.contract,requestId:request.requestId,status:status,counts:counts || {},digest:digest || null};
    }
    var key='PQM_EXECUTION_RUN_'+request.requestId, stored=properties.getProperty(key);
    if (stored) {
      var previous=JSON.parse(stored);
      if (previous.actor!==request.actor || previous.digest!==request.expectedDigest ||
          previous.trigger!==request.trigger || request.action!=='apply')
        throw new Error('PQM: repeated execution identity rejected');
      if (!previous.result) throw new Error('PQM: execution outcome uncertain; no retry');
      return previous.result;
    }
    if (properties.getProperty('PQM_EXECUTION_UNCERTAIN'))
      throw new Error('PQM: unresolved execution outcome; reconciliation required');
    var loaded=pqmSandboxFullLoad_(id);
    if (request.action==='preview') return receipt('PREVIEW', {
      append:loaded.plan.counts.appended,update:loaded.plan.counts.updated,
      conflict:loaded.plan.counts.conflicts,error:loaded.plan.counts.errors,skipped:loaded.plan.counts.unchanged
    },loaded.plan_digest);
    if (loaded.plan_digest!==request.expectedDigest) throw new Error('PQM: stale execution Preview; zero writes');
    // Bounded persistent receipts. Never evict a run and allow it to be applied twice.
    var all=properties.getProperties();
    if (Object.keys(all).filter(function(k){return k.indexOf('PQM_EXECUTION_RUN_')===0;}).length>=250)
      throw new Error('PQM: execution receipt capacity reached; audited maintenance required');
    var record={actor:request.actor,trigger:request.trigger,digest:request.expectedDigest,result:null};
    properties.setProperty(key,JSON.stringify(record));
    try {
      var report=pqmSandboxDailySync({lock:lock,expectedDigest:request.expectedDigest,payloadDigest:loaded.state.payload_digest});
      var result=receipt(report.status, {
        append:report.append,update:report.update,conflict:report.conflict,error:report.error,
        remaining_safe:report.remaining_safe,batches:report.batches
      },request.expectedDigest);
      record.result=result; properties.setProperty(key,JSON.stringify(record));
      return result;
    } catch (_) {
      properties.setProperty('PQM_EXECUTION_UNCERTAIN',request.requestId);
      throw new Error('PQM: Apply may be partial; no retry, reconcile using a read-only audit');
    }
  } finally {
    PQM_EXECUTION_CONTEXT_=null;
    lock.releaseLock();
  }
}
