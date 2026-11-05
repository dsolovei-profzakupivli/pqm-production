/* Shared checkpoint mechanics. Environment-specific writers provide a guarded adapter. */
function pqmExecutionCheckpointSave_(properties, key, record, maxBytes) {
  var encoded = JSON.stringify(record);
  if (Utilities.newBlob(encoded, 'application/json').getBytes().length > maxBytes) {
    throw new Error('PQM EXECUTION CHECKPOINT: storage bound exceeded; no next write.');
  }
  properties.setProperty(key, encoded);
}

function pqmExecutionCheckpointReceipt_(request, receipt, step) {
  var result = receipt(step.status, step.counts, request.expectedDigest);
  result.chunkIndex = step.chunkIndex;
  result.nextChunk = step.nextChunk;
  result.more = step.more;
  result.phase = step.phase;
  return result;
}

function pqmExecutionUpdatePage_(chunks, maxRows, maxCells) {
  var page = [], cells = 0;
  for (var i = 0; i < chunks.length; i++) {
    for (var j = 0; j < chunks[i].length; j++) {
      var entry = chunks[i][j], width = entry.columns.length;
      if (page.length && (page.length >= maxRows || cells + width > maxCells)) return page;
      if (!page.length && width > maxCells) throw new Error('PQM EXECUTION CHECKPOINT: invalid UPDATE page bound.');
      page.push(entry); cells += width;
    }
  }
  return page;
}

function pqmExecutionApplyCheckpointStep_(adapter, id, loaded, request, properties, key,
    record, receipt, limits) {
  var beforeGoogleDigest = loaded.state.google_digest;
  if (loaded.state.payload_digest !== record.payloadDigest ||
      beforeGoogleDigest !== record.googleDigest) {
    throw new Error('PQM EXECUTION CHECKPOINT: source or sheet changed since last verified step.');
  }

  var append = adapter.appendLoad(id, undefined, loaded, limits.appendPageRows);
  var phase = append.selected.length ? 'append' : 'update';
  var counts = {append: 0, update: 0, conflict: loaded.plan.counts.conflicts,
    error: loaded.plan.counts.errors, remaining_safe: 0, batches: 0};

  if (phase === 'append') {
    adapter.appendPrewriteGuard(id, append);
    var templates = {};
    append.selected.forEach(function(change) {
      if (!templates[change.tab]) templates[change.tab] = adapter.appendRowMetadata(id,
        change.tab, append.tabs[change.tab].rows.length + 1);
    });
    var requests = adapter.appendRequests(append.selected, append.tabs);
    if (!requests.length) throw new Error('PQM EXECUTION CHECKPOINT: empty APPEND chunk.');
    record.inflight = request.chunkIndex;
    record.state = 'writing';
    pqmExecutionCheckpointSave_(properties, key, record, limits.maxBytes);
    adapter.batchUpdate({requests: requests}, id);
    adapter.appendVerify(id, append.selected, append.tabs);
    adapter.appendVerifyMetadata(id, append.selected, templates);
    counts.append = append.selected.length;
    counts.batches = 1;
  } else {
    var chunks = adapter.fullChunks(loaded.entries);
    var chunk = pqmExecutionUpdatePage_(chunks, limits.updatePageRows, limits.updatePageCells);
    if (chunk.length) {
      var before, updateRequests;
      var freshBody = adapter.fetchRegistry();
      if (adapter.appendPayloadDigest(freshBody) !== record.payloadDigest) {
        throw new Error('PQM EXECUTION CHECKPOINT: PQM source changed before UPDATE.');
      }
      adapter.protectionCheck(chunk, loaded.tabs);
      before = adapter.readRows(id, chunk, loaded.tabs);
      adapter.fullBeforeCheck(chunk, before, loaded.tabs);
      var rechecked = adapter.readRows(id, chunk, loaded.tabs);
      if (adapter.controlledDigest(before.map(adapter.rowState)) !==
          adapter.controlledDigest(rechecked.map(adapter.rowState))) {
        throw new Error('PQM EXECUTION CHECKPOINT: UPDATE row changed before write.');
      }
      updateRequests = adapter.fullRequests(chunk, loaded.tabs);
      if (!updateRequests.length) throw new Error('PQM EXECUTION CHECKPOINT: empty UPDATE chunk.');
      record.inflight = request.chunkIndex;
      record.state = 'writing';
      pqmExecutionCheckpointSave_(properties, key, record, limits.maxBytes);
      adapter.batchUpdate({requests: updateRequests}, id);
      var verified = adapter.controlledVerify(chunk, before,
        adapter.readRows(id, chunk, loaded.tabs));
      if (!verified.verification_passed) {
        throw new Error('PQM EXECUTION CHECKPOINT: UPDATE read-back failed.');
      }
      counts.update = chunk.length;
      counts.batches = 1;
    }
  }

  // A full post-write state digest is retained so the next invocation detects
  // any out-of-band Google edit before another write is allowed.
  var afterTabs = adapter.snapshot(id);
  var afterGoogleDigest = adapter.controlledDigest(adapter.fullSheetState(afterTabs));
  var afterPlan = adapter.plan(loaded.body, afterTabs);
  counts.conflict = afterPlan.counts.conflicts;
  counts.error = afterPlan.counts.errors;
  counts.remaining_safe = afterPlan.counts.appended + afterPlan.counts.updated;
  record.googleDigest = afterGoogleDigest;
  record.payloadDigest = loaded.state.payload_digest;
  record.aggregate = record.aggregate || {append: 0, update: 0, batches: 0};
  record.aggregate.append += counts.append;
  record.aggregate.update += counts.update;
  record.aggregate.batches += counts.batches;
  record.steps = record.steps || [];
  record.inflight = null;
  record.state = counts.remaining_safe ? 'ready' : 'complete';
  record.nextChunk = request.chunkIndex + 1;
  var finalStatus = counts.remaining_safe ? 'APPLY_CHUNK_VERIFIED' :
    (counts.conflict || counts.error ? 'COMPLETE_WITH_CONFLICTS' : 'COMPLETE');
  var step = {status: finalStatus, chunkIndex: request.chunkIndex,
    nextChunk: record.nextChunk, more: counts.remaining_safe > 0, phase: phase,
    counts: counts};
  record.steps.push(step);
  if (!step.more) {
    record.result = receipt(finalStatus, {
      append: record.aggregate.append, update: record.aggregate.update,
      conflict: counts.conflict, error: counts.error, remaining_safe: counts.remaining_safe,
      batches: record.aggregate.batches
    }, request.expectedDigest);
    record.result.chunkIndex = step.chunkIndex;
    record.result.nextChunk = step.nextChunk;
    record.result.more = false;
    record.result.phase = step.phase;
  }
  pqmExecutionCheckpointSave_(properties, key, record, limits.maxBytes);
  return pqmExecutionCheckpointReceipt_(request, receipt, step);
}
