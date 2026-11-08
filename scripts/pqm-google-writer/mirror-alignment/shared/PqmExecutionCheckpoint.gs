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
  result.checkpointDigest = step.checkpointDigest || null;
    if (step.chunkId) {
      result.chunkId = step.chunkId;
      result.chunkDigest = step.chunkDigest;
      result.planId = step.planId;
    }
  return result;
}

function pqmExecutionCheckpointStateDigest_(record) {
  var steps = (record.steps || []).map(function(step) {
    var copy = {};
    Object.keys(step).sort().forEach(function(key) {
      if (key !== 'checkpointDigest') copy[key] = step[key];
    });
    return copy;
  });
  var state = {version: 2, actor: record.actor, trigger: record.trigger,
    digest: record.digest, planScope: record.planScope, state: record.state,
    nextChunk: record.nextChunk, inflight: record.inflight, payloadDigest: record.payloadDigest,
    googleDigest: record.googleDigest, aggregate: record.aggregate, steps: steps};
  if (Object.prototype.hasOwnProperty.call(record, 'inflightManifest')) state.inflightManifest = record.inflightManifest;
  if (record.chunkJournalVersion === 1) {
    state.chunkJournalVersion = record.chunkJournalVersion;
    state.planId = record.planId;
    state.runId = record.runId;
  }
  return pqmSandboxControlledDigest_(state);
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
  if (adapter.verifyServiceRanges && record.steps && record.steps.some(function(step) {
      return Array.isArray(step.serviceRanges) && step.serviceRanges.length;
    })) {
    adapter.verifyServiceRanges(id, record.steps.reduce(function(all, step) {
      return all.concat(step.serviceRanges || []);
    }, []), request);
  }

  var append = adapter.appendLoad(id, undefined, loaded, limits.appendPageRows);
  var appendOnly = request.planScope === 'APPEND_ONLY';
  var phase = append.selected.length || appendOnly ? 'append' : 'update';
  var counts = {append: 0, update: 0, conflict: loaded.plan.counts.conflicts,
    error: loaded.plan.counts.errors, remaining_safe: 0, batches: 0};

  if (phase === 'append' && append.selected.length) {
    adapter.appendPrewriteGuard(id, append);
    var templates = {};
    append.selected.forEach(function(change) {
      if (!templates[change.tab]) templates[change.tab] = adapter.appendRowMetadata(id,
        change.tab, append.tabs[change.tab].rows.length + 1);
    });
    var requests = adapter.appendRequests(append.selected, append.tabs, {
      requestId: request.requestId, runId: request.requestId,
      planId: request.planId || request.requestId,
      expectedDigest: request.expectedDigest
    });
    if (!requests.length) throw new Error('PQM EXECUTION CHECKPOINT: empty APPEND chunk.');
    record.inflight = request.chunkIndex;
    if (request.chunkId) {
      record.inflightManifest = {chunkId: request.chunkId, chunkDigest: request.chunkDigest,
        planId: request.planId, runId: request.requestId,
        rows: append.selected.map(function(change) { return {tab: change.tab, row: change.row,
          code: String(change.cells[1]).trim(), cellsDigest: adapter.controlledDigest(change.cells),
          formulaA: change.cells[0], serviceMetadata: change.serviceMetadata}; })};
    }
    record.state = 'writing';
    pqmExecutionCheckpointSave_(properties, key, record, limits.maxBytes);
    adapter.batchUpdate({requests: requests}, id);
    var appendVerification = adapter.appendVerify(id, append.selected, append.tabs);
    adapter.appendVerifyMetadata(id, append.selected, templates);
    if (adapter.projectVerifiedAppend) adapter.projectVerifiedAppend(loaded, append.selected, appendVerification);
    counts.append = append.selected.length;
    counts.batches = 1;
  } else if (phase === 'update') {
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
  // APPEND has already been read back row-by-row and its verified state is
  // projected into the one full snapshot loaded before the write. Avoid a
  // second full-sheet read and planner pass after each bounded chunk.
  var afterTabs = phase === 'append' && adapter.projectVerifiedAppend ? loaded.tabs : adapter.snapshot(id);
  var afterGoogleDigest = adapter.controlledDigest(adapter.fullSheetState(afterTabs));
  var afterPlan = adapter.plan(loaded.body, afterTabs);
  counts.conflict = afterPlan.counts.conflicts;
  counts.error = afterPlan.counts.errors;
  counts.remaining_safe = afterPlan.counts.appended + (appendOnly ? 0 : afterPlan.counts.updated);
  record.googleDigest = afterGoogleDigest;
  record.payloadDigest = loaded.state.payload_digest;
  record.aggregate = record.aggregate || {append: 0, update: 0, batches: 0};
  record.aggregate.append += counts.append;
  record.aggregate.update += counts.update;
  record.aggregate.batches += counts.batches;
  record.steps = record.steps || [];
  record.inflight = null;
  record.inflightManifest = null;
  record.state = counts.remaining_safe ? 'ready' : 'complete';
  record.nextChunk = request.chunkIndex + 1;
  var finalStatus = counts.remaining_safe ? 'APPLY_CHUNK_VERIFIED' :
    (counts.conflict || counts.error ? 'COMPLETE_WITH_CONFLICTS' : 'COMPLETE');
  var step = {status: finalStatus, chunkIndex: request.chunkIndex,
    nextChunk: record.nextChunk, more: counts.remaining_safe > 0, phase: phase,
    counts: counts, verified: true, digest: request.expectedDigest,
    planScope: request.planScope || 'ALL', payloadDigest: record.payloadDigest,
    googleDigest: afterGoogleDigest};
  if (request.chunkId) {
    record.chunkJournalVersion = 1;
    step.chunkId = request.chunkId;
    step.chunkDigest = request.chunkDigest;
    step.planId = request.planId;
    step.serviceRanges = adapter.appendServiceRanges ?
      adapter.appendServiceRanges(append.selected) : [];
  }
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
  step.checkpointDigest = pqmExecutionCheckpointStateDigest_(record);
  if (record.result) {
    record.result.checkpointDigest = step.checkpointDigest;
    record.result.planScope = request.planScope || 'ALL';
  }
  pqmExecutionCheckpointSave_(properties, key, record, limits.maxBytes);
  return pqmExecutionCheckpointReceipt_(request, receipt, step);
}
