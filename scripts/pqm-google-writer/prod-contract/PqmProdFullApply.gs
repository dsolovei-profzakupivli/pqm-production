/* Separate PROD writer. Install only with this package's Preview and Controlled Apply files. */
// One targeted grid read requests three times per chunk; keep range count bounded.
var PQM_PROD_FULL_CHUNK_MAX_CELLS = 400;
var PQM_PROD_FULL_CHUNK_MAX_ROWS = 200;
var PQM_PROD_FULL_RUN_BUDGET_MS = 270000;

function pqmProdFullTimed_(timing, key, action) {
  var started = Date.now();
  try { return action(); }
  finally { timing[key] += Date.now() - started; }
}

function pqmProdFullBlocked_(plan) {
  return !!(plan.counts.appended || plan.counts.conflicts || plan.counts.duplicate_keys ||
    plan.counts.errors || plan.changes.some(function(change) { return change.append; }));
}

function pqmProdFullEntries_(plan, tabs) {
  var seen = {};
  return plan.changes.map(function(change) {
    var tab = tabs[change.tab], row = tab && tab.rows[change.row - 2];
    var code = row && String(row.codeDisplay || '').trim();
    var columns = pqmProdControlledColumns_(change);
    if (!tab || !row || !code || change.append || change.row < 2 || change.row > tab.maxRows ||
        seen[change.tab + ':' + change.row] || columns.some(function(column) { return [2, 3, 5, 7, 8, 11].indexOf(column) < 0; })) {
      throw new Error('PQM PROD FULL: invalid matched-only plan; no writes.');
    }
    seen[change.tab + ':' + change.row] = true;
    return {code: code, tab: change.tab, row: change.row, change: change, columns: columns};
  }).sort(function(a, b) {
    return a.tab < b.tab ? -1 : a.tab > b.tab ? 1 : a.row - b.row;
  });
}

function pqmProdFullSheetState_(tabs) {
  return PQM_GOOGLE_TABS.map(function(name) {
    var tab = tabs[name];
    return {name: name, id: tab.id, maxRows: tab.maxRows, headers: tab.headers,
      rows: tab.rows.map(function(row) {
        return {values: row.values, formulas: row.formulas,
          codeDisplay: row.codeDisplay, dateFormat: row.dateFormat,
          verificationDateFormat: row.verificationDateFormat};
      }), merges: tab.merges, protectedRanges: tab.protectedRanges,
      conditionalFormats: tab.conditionalFormats};
  });
}

function pqmProdFullState_(body, tabs, plan, profile) {
  var payload = body.items.map(pqmProdControlledPqmState_).sort(function(a, b) {
    return a.supplier_code < b.supplier_code ? -1 : a.supplier_code > b.supplier_code ? 1 : 0;
  });
  var changes = plan.changes.map(function(change) {
    return {tab: change.tab, row: change.row, append: change.append, cells: change.cells};
  }).sort(function(a, b) {
    return a.tab < b.tab ? -1 : a.tab > b.tab ? 1 : a.row - b.row;
  });
  var localStarted = Date.now(), payloadDigest = pqmProdControlledDigest_(payload);
  var googleStarted = Date.now(), googleDigest = pqmProdControlledDigest_(pqmProdFullSheetState_(tabs));
  if (profile) profile.google_state_digest = {total_ms: Date.now() - googleStarted};
  var changesDigest = pqmProdControlledDigest_(changes), countsDigest = pqmProdControlledDigest_(plan.counts);
  if (profile) profile.payload_plan_digests = {total_ms: Date.now() - localStarted - profile.google_state_digest.total_ms};
  return {payload_digest: payloadDigest,
    google_digest: googleDigest,
    changes_digest: changesDigest,
    counts_digest: countsDigest};
}

function pqmProdFullDigest_(state) {
  return pqmProdControlledDigest_({version: 1, state: state});
}

function pqmProdFullLoad_(spreadsheetId) {
  var fetchStarted = Date.now(), body = pqmProdFetchRegistry_();
  var fetchMs = Date.now() - fetchStarted;
  var googlePhases = {};
  var snapshotStarted = Date.now(), tabs = pqmGoogleSnapshot_(spreadsheetId, googlePhases);
  var snapshotMs = Date.now() - snapshotStarted;
  var apiMs = Object.keys(googlePhases).reduce(function(sum, key) {
    return sum + googlePhases[key].total_ms;
  }, 0);
  googlePhases.snapshot_reconstruction = {total_ms: Math.max(0, snapshotMs - apiMs)};
  var plannerStarted = Date.now(), plan = pqmGooglePlan_(body, tabs);
  var plannerMs = Date.now() - plannerStarted;
  if (pqmProdFullBlocked_(plan)) {
    throw new Error('PQM PROD FULL: BLOCKED_APPEND_CONFLICT_DUPLICATE_OR_ERROR; no writes.');
  }
  var entries = pqmProdFullEntries_(plan, tabs);
  pqmProdControlledProtectionCheck_(entries, tabs);
  var guardStarted = Date.now(), state = pqmProdFullState_(body, tabs, plan, googlePhases);
  var guardMs = Date.now() - guardStarted;
  return {body: body, tabs: tabs, plan: plan, entries: entries, state: state,
    plan_digest: pqmProdFullDigest_(state),
    timing_ms: {pqm_fetch: fetchMs, google_snapshot: snapshotMs,
      planner: plannerMs, google_state_guard: guardMs, initial_google_phases: googlePhases}};
}

function pqmProdFullApplyPreview() {
  var id = pqmProdControlledSpreadsheetId_();
  var started = Date.now(), loaded = pqmProdFullLoad_(id);
  var byColumn = {C: 0, D: 0, E: 0, F: 0, H: 0, I: 0, L: 0}, total = 0;
  loaded.entries.forEach(function(entry) {
    entry.columns.forEach(function(column) {
      byColumn[PQM_PROD_CONTROLLED_COLUMNS[column]]++;
      total++;
    });
  });
  var output = {dry_run: true, google_writes: 0,
    total_pqm_suppliers: loaded.body.count,
    matched: loaded.plan.counts.matched, skipped: loaded.plan.counts.skipped,
    updated: loaded.plan.counts.updated, unchanged: loaded.plan.counts.unchanged,
    appended: 0, conflicts: 0, duplicate_keys: 0, errors: 0,
    verification_pair_decisions: {
      google_newer_preserved: loaded.plan.counts.google_newer_preserved,
      same_date_google_officer_preserved: loaded.plan.counts.same_date_google_officer_preserved,
      same_date_equivalent: loaded.plan.counts.same_date_equivalent,
      pqm_newer_written: loaded.plan.counts.pqm_newer_written,
      google_blank_filled: loaded.plan.counts.google_blank_filled,
      pqm_blank_google_preserved: loaded.plan.counts.pqm_blank_google_preserved},
    changes_by_column: byColumn, total_planned_cells: total,
    plan_digest: loaded.plan_digest,
    timing_ms: {pqm_fetch: loaded.timing_ms.pqm_fetch,
      google_snapshot: loaded.timing_ms.google_snapshot,
      planner: loaded.timing_ms.planner,
      google_state_guard: loaded.timing_ms.google_state_guard,
      initial_google_phases: loaded.timing_ms.initial_google_phases,
      total: Date.now() - started}};
  console.log(JSON.stringify(output));
  return output;
}

/* Read-only Phase 1 impact report, including blockers that Full Preview rejects. */
function pqmProdExpandedImpactPreview() {
  var started = Date.now();
  var id = pqmProdControlledSpreadsheetId_();
  var body = pqmProdFetchRegistry_();
  var tabs = pqmGoogleSnapshot_(id);
  var plan = pqmGooglePlan_(body, tabs);
  var byColumn = {C: 0, D: 0, E: 0, F: 0, H: 0, I: 0, L: 0};
  var matchedCells = 0;
  plan.changes.forEach(function(change) {
    if (change.append) return;
    Object.keys(change.cells).forEach(function(rawColumn) {
      var column = Number(rawColumn);
      var letter = PQM_PROD_CONTROLLED_COLUMNS[column];
      if (!letter) throw new Error('PQM PROD: unowned planned cell; no writes.');
      byColumn[letter]++;
      matchedCells++;
    });
  });
  var output = {dry_run: true, google_writes: 0,
    total_pqm_suppliers: body.count, matched: plan.counts.matched,
    updated: plan.counts.updated, unchanged: plan.counts.unchanged,
    skipped: plan.counts.skipped, appended: plan.counts.appended,
    conflicts: plan.counts.conflicts, duplicate_keys: plan.counts.duplicate_keys,
    errors: plan.counts.errors,
    verification_pair_decisions: {
      google_newer_preserved: plan.counts.google_newer_preserved,
      same_date_google_officer_preserved: plan.counts.same_date_google_officer_preserved,
      same_date_equivalent: plan.counts.same_date_equivalent,
      pqm_newer_written: plan.counts.pqm_newer_written,
      google_blank_filled: plan.counts.google_blank_filled,
      pqm_blank_google_preserved: plan.counts.pqm_blank_google_preserved},
    changes_by_column: byColumn,
    total_planned_matched_cells: matchedCells, a_writes: 0, formulas_touched: 0,
    full_apply_blocked: pqmProdFullBlocked_(plan), timing_ms: {total: Date.now() - started}};
  console.log(JSON.stringify(output));
  return output;
}

/* Read-only profile of the exact Google snapshot path and sheet-state digest. */
function pqmProdProfileInitialGoogleGuard() {
  var spreadsheetId = pqmProdControlledSpreadsheetId_();
  var started = Date.now(), phases = {};
  var snapshotStarted = Date.now();
  var tabs = pqmGoogleSnapshot_(spreadsheetId, phases);
  var snapshotMs = Date.now() - snapshotStarted;
  var apiMs = Object.keys(phases).reduce(function(sum, key) {
    return sum + phases[key].total_ms;
  }, 0);
  phases.snapshot_reconstruction = {total_ms: Math.max(0, snapshotMs - apiMs)};
  var digestStarted = Date.now();
  pqmProdControlledDigest_(pqmProdFullSheetState_(tabs));
  phases.google_state_digest = {total_ms: Date.now() - digestStarted};
  var output = {dry_run: true, google_writes: 0,
    total_ms: Date.now() - started, phases: phases};
  console.log(JSON.stringify(output));
  return output;
}

function pqmProdFullChunks_(entries) {
  var chunks = [], chunk = [], cells = 0;
  entries.forEach(function(entry) {
    if (chunk.length && (chunk.length >= PQM_PROD_FULL_CHUNK_MAX_ROWS ||
        cells + entry.columns.length > PQM_PROD_FULL_CHUNK_MAX_CELLS)) {
      chunks.push(chunk); chunk = []; cells = 0;
    }
    chunk.push(entry); cells += entry.columns.length;
  });
  if (chunk.length) chunks.push(chunk);
  return chunks;
}

function pqmProdFullCellValue_(cell) {
  var value = cell.effectiveValue || {};
  return value.stringValue !== undefined ? value.stringValue :
    value.numberValue !== undefined ? value.numberValue :
    value.boolValue !== undefined ? value.boolValue : '';
}

function pqmProdFullBeforeCheck_(chunk, rawRows, tabs) {
  chunk.forEach(function(entry, index) {
    var expected = tabs[entry.tab].rows[entry.row - 2], cells = rawRows[index];
    if (!expected || !cells || cells.length !== 15) {
      throw new Error('PQM PROD FULL: ROW_STATE_CHANGED; no further writes.');
    }
    for (var column = 0; column < 15; column++) {
      var cell = cells[column] || {}, actual = pqmProdFullCellValue_(cell);
      var planned = expected.values[column] === undefined ? '' : expected.values[column];
      if (actual !== planned) throw new Error('PQM PROD FULL: ROW_STATE_CHANGED; no further writes.');
      if ([0, 1, 2, 4, 5, 7, 8, 11].indexOf(column) >= 0 &&
          ((cell.userEnteredValue || {}).formulaValue || '') !== (expected.formulas[column] || '')) {
        throw new Error('PQM PROD FULL: FORMULA_STATE_CHANGED; no further writes.');
      }
    }
    if (String((cells[1] || {}).formattedValue || '').trim() !== entry.code ||
        String(expected.codeDisplay || '').trim() !== entry.code ||
        ((((cells[7] || {}).userEnteredFormat || {}).numberFormat || {}).pattern || '') !==
          (expected.dateFormat || '') ||
        ((((cells[8] || {}).userEnteredFormat || {}).numberFormat || {}).pattern || '') !==
          (expected.verificationDateFormat || '')) {
      throw new Error('PQM PROD FULL: IDENTITY_OR_DATE_FORMAT_CHANGED; no further writes.');
    }
  });
}

function pqmProdFullRequests_(chunk, tabs) {
  var requests = [];
  chunk.forEach(function(entry) {
    if (Object.keys(entry.change.cells).concat(entry.columns).some(function(column) {
      return !Object.prototype.hasOwnProperty.call(PQM_PROD_CONTROLLED_COLUMNS, column);
    })) throw new Error('PQM PROD FULL: unowned or frozen E cell; no writes.');
    entry.columns.forEach(function(column) {
      var value = entry.change.cells[column];
      if (pqmGoogleBlank_(value)) throw new Error('PQM PROD FULL: blank planned value; no further writes.');
      var dateColumn = column === 7 || column === 8;
      var cell = {userEnteredValue: dateColumn ? {numberValue: value} : {stringValue: value}};
      if (dateColumn) cell.userEnteredFormat = {numberFormat: {type: 'DATE', pattern: 'dd.MM.yyyy'}};
      requests.push({updateCells: {range: {sheetId: tabs[entry.tab].id,
        startRowIndex: entry.row - 1, endRowIndex: entry.row,
        startColumnIndex: column, endColumnIndex: column + 1},
        rows: [{values: [cell]}],
        fields: dateColumn ? 'userEnteredValue,userEnteredFormat.numberFormat' : 'userEnteredValue'}});
    });
  });
  if (!requests.length || requests.length > PQM_PROD_FULL_CHUNK_MAX_CELLS ||
      chunk.length > PQM_PROD_FULL_CHUNK_MAX_ROWS) {
    throw new Error('PQM PROD FULL: chunk bound exceeded; no further writes.');
  }
  return requests;
}

function pqmProdFullProgress_(progress, status) {
  progress.status = status;
  progress.remaining_chunks = progress.chunks_total - progress.chunks_completed;
  progress.remaining_cells = progress.cells_total - progress.cells_written;
  console.log(JSON.stringify(progress));
  return progress;
}

function pqmProdFullApply() {
  var ui = SpreadsheetApp.getUi();
  var digestAnswer = ui.prompt('PQM PROD FULL Apply',
    'Paste plan_digest from the immediately preceding FULL Preview.', ui.ButtonSet.OK_CANCEL);
  if (digestAnswer.getSelectedButton() !== ui.Button.OK) return {cancelled: true, google_writes: 0};
  var expectedDigest = digestAnswer.getResponseText().trim();
  if (!/^[A-Za-z0-9_-]{40,}$/.test(expectedDigest)) {
    throw new Error('PQM PROD FULL: invalid Preview digest; zero writes.');
  }
  var answer = ui.alert('PQM PROD FULL Apply',
    'Confirm bounded writes to ONLY current planned C/D/F/H/I/L cells in the reviewed PROD destination; E is frozen. ' +
      'A time-limited run may stop partially; a NEW Preview is required before another run.', ui.ButtonSet.YES_NO);
  if (answer !== ui.Button.YES) return {cancelled: true, google_writes: 0};
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(0)) throw new Error('PQM PROD FULL: another operation is running; zero writes.');
  var started = Date.now();
  try {
    var id = pqmProdControlledSpreadsheetId_();
    var loaded = pqmProdFullLoad_(id);
    if (loaded.plan_digest !== expectedDigest) {
      throw new Error('PQM PROD FULL: PLAN_OR_GOOGLE_STATE_CHANGED; zero writes.');
    }
    var chunks = pqmProdFullChunks_(loaded.entries);
    var progress = {chunks_total: chunks.length, chunks_completed: 0,
      rows_total: loaded.entries.length, rows_processed: 0,
      cells_total: loaded.entries.reduce(function(n, entry) { return n + entry.columns.length; }, 0),
      cells_written: 0, cells_attempted: 0, cells_verified: 0, failures: 0, remaining_chunks: chunks.length,
      remaining_cells: 0, google_writes: 0,
      timing_ms: {initial_pqm_fetch: loaded.timing_ms.pqm_fetch,
        initial_google_guard: loaded.timing_ms.google_snapshot + loaded.timing_ms.google_state_guard,
        initial_plan_rebuild: loaded.timing_ms.planner,
        initial_google_phases: loaded.timing_ms.initial_google_phases,
        chunk_pre_read: 0, chunk_write: 0,
        chunk_after_read_verification: 0}};
    // The freshly fetched and digest-validated PQM plan is frozen for this one
    // time-bounded execution. Every later execution requires a new Preview.
    for (var i = 0; i < chunks.length; i++) {
      if (Date.now() - started >= PQM_PROD_FULL_RUN_BUDGET_MS) {
        return pqmProdFullProgress_(progress, 'TIME_BUDGET_STOP_NEW_PREVIEW_REQUIRED');
      }
      var chunk = chunks[i];
      var writeStarted = false;
      try {
        var before, prewriteStable = pqmProdFullTimed_(progress.timing_ms, 'chunk_pre_read', function() {
          pqmProdControlledProtectionCheck_(chunk, loaded.tabs);
          before = pqmProdControlledReadRows_(id, chunk, loaded.tabs);
          pqmProdFullBeforeCheck_(chunk, before, loaded.tabs);
          var rechecked = pqmProdControlledReadRows_(id, chunk, loaded.tabs);
          return pqmProdControlledDigest_(before.map(pqmProdControlledRowState_)) ===
            pqmProdControlledDigest_(rechecked.map(pqmProdControlledRowState_));
        });
        if (!prewriteStable) {
          progress.failures++;
          return pqmProdFullProgress_(progress, 'ROW_CHANGED_BEFORE_WRITE_NEW_PREVIEW_REQUIRED');
        }
        var requests = pqmProdFullRequests_(chunk, loaded.tabs);
        if (Date.now() - started >= PQM_PROD_FULL_RUN_BUDGET_MS) {
          return pqmProdFullProgress_(progress, 'TIME_BUDGET_STOP_NEW_PREVIEW_REQUIRED');
        }
        progress.cells_attempted += requests.length;
        writeStarted = true;
        pqmProdFullTimed_(progress.timing_ms, 'chunk_write', function() {
          Sheets.Spreadsheets.batchUpdate({requests: requests}, id);
        });
        progress.google_writes++;
        progress.cells_written += requests.length;
        var verification = pqmProdFullTimed_(progress.timing_ms, 'chunk_after_read_verification', function() {
          var after = pqmProdControlledReadRows_(id, chunk, loaded.tabs);
          return pqmProdControlledVerify_(chunk, before, after);
        });
        if (!verification.verification_passed) {
          progress.failures += verification.failures.length;
          return pqmProdFullProgress_(progress, 'VERIFICATION_FAILED_NEW_PREVIEW_REQUIRED');
        }
        progress.cells_verified += verification.verified_owned_cells;
        progress.chunks_completed++;
        progress.rows_processed += chunk.length;
        pqmProdFullProgress_(progress, 'IN_PROGRESS');
      } catch (error) {
        progress.failures++;
        return pqmProdFullProgress_(progress,
          writeStarted ? 'WRITE_OR_READBACK_UNCERTAIN_NEW_PREVIEW_REQUIRED' :
            'CHUNK_FAILED_NEW_PREVIEW_REQUIRED');
      }
    }
    return pqmProdFullProgress_(progress, 'COMPLETE');
  } finally {
    lock.releaseLock();
  }
}
