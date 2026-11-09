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
  if (record.chunkJournalVersion === 2) {
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
  record.lastStage='source_and_sheet_guard';
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

  record.lastStage='chunk_selection';
  var append = adapter.appendLoad(id, undefined, loaded, limits.appendPageRows);
  var appendOnly = request.planScope === 'APPEND_ONLY';
  var phase = append.selected.length || appendOnly ? 'append' : 'update';
  var counts = {append: 0, update: 0, conflict: loaded.plan.counts.conflicts,
    error: loaded.plan.counts.errors, remaining_safe: 0, batches: 0};

  if (phase === 'append' && append.selected.length) {
    record.lastStage='append_prewrite_guard';
    adapter.appendPrewriteGuard(id, append);
    var templates = {};
    append.selected.forEach(function(change) {
      if (!templates[change.tab]) templates[change.tab] = adapter.appendRowMetadata(id,
        change.tab, append.tabs[change.tab].rows.length + 1);
    });
    record.lastStage='append_request_build';
    var requests = adapter.appendRequests(append.selected, append.tabs, {
      requestId: request.requestId, runId: request.requestId,
      planId: request.planId || request.requestId,
      expectedDigest: request.expectedDigest, addedAt: request.chunkAddedAt || null,
      journaled: !!request.chunkId
    });
    if (!requests.length) throw new Error('PQM EXECUTION CHECKPOINT: empty APPEND chunk.');
    record.inflight = request.chunkIndex;
    if (request.chunkId) {
      record.planId = request.planId;
      record.runId = request.requestId;
      if (request.planScope === 'APPEND_ONLY') {
        // Preserve the exact v1 manifest consumed by the legacy APPEND_ONLY
        // recovery entrypoint. Existing Script Properties are never migrated.
        record.chunkJournalVersion = 1;
        record.inflightManifest = {chunkId: request.chunkId, chunkDigest: request.chunkDigest,
          planId: request.planId, runId: request.requestId,
          rows: append.selected.map(function(change) { return {tab: change.tab, row: change.row,
            code: String(change.cells[1]).trim(), cellsDigest: adapter.controlledDigest(change.cells),
            formulaA: change.cells[0], serviceMetadata: change.serviceMetadata}; })};
      } else {
        record.chunkJournalVersion = 2;
        record.inflightManifest = {chunkId: request.chunkId, chunkDigest: request.chunkDigest,
          detailsDigest: request.chunkDetailsDigest, planId: request.planId,
          runId: request.requestId, phase: 'append', rows: adapter.chunkEvidence ?
            adapter.chunkEvidence('append',append.selected,loaded,request) : []};
        if (!record.inflightManifest.rows.length)
          throw new Error('PQM EXECUTION CHECKPOINT: ALL APPEND recovery manifest unavailable.');
      }
    }
    record.state = 'writing';
    record.lastStage='append_inflight_save';
    pqmExecutionCheckpointSave_(properties, key, record, limits.maxBytes);
    record.lastStage='append_batch_update';
    adapter.batchUpdate({requests: requests}, id);
    record.lastStage='append_read_back';
    var appendVerification = adapter.appendVerify(id, append.selected, append.tabs);
    record.lastStage='append_metadata_read_back';
    adapter.appendVerifyMetadata(id, append.selected, templates);
    if (adapter.projectVerifiedAppend) adapter.projectVerifiedAppend(loaded, append.selected, appendVerification);
    counts.append = append.selected.length;
    counts.batches = 1;
  } else if (phase === 'update') {
    record.lastStage='update_chunk_selection';
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
      if (request.chunkId) {
        record.chunkJournalVersion = 2;
        record.planId = request.planId;
        record.runId = request.requestId;
        record.inflightManifest = {chunkId:request.chunkId,chunkDigest:request.chunkDigest,
          detailsDigest:request.chunkDetailsDigest,planId:request.planId,runId:request.requestId,
          phase:'update',rows:adapter.chunkEvidence ? adapter.chunkEvidence('update',chunk,loaded,request,before) : []};
        if (!record.inflightManifest.rows.length)
          throw new Error('PQM EXECUTION CHECKPOINT: UPDATE recovery manifest unavailable.');
      }
      record.inflight = request.chunkIndex;
      record.state = 'writing';
      record.lastStage='update_inflight_save';
      pqmExecutionCheckpointSave_(properties, key, record, limits.maxBytes);
      record.lastStage='update_batch_update';
      adapter.batchUpdate({requests: updateRequests}, id);
      record.lastStage='update_read_back';
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
  record.lastStage='postwrite_sheet_snapshot';
  var afterTabs = phase === 'append' && adapter.projectVerifiedAppend ? loaded.tabs : adapter.snapshot(id);
  var afterGoogleDigest = adapter.controlledDigest(adapter.fullSheetState(afterTabs));
  record.lastStage='postwrite_plan';
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
    record.chunkJournalVersion = request.planScope === 'APPEND_ONLY' ? 1 : 2;
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
  record.lastStage='checkpoint_receipt_save';
  pqmExecutionCheckpointSave_(properties, key, record, limits.maxBytes);
  return pqmExecutionCheckpointReceipt_(request, receipt, step);
}
