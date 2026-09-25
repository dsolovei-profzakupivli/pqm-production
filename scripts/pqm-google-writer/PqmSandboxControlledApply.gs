/* Install only in the SANDBOX spreadsheet after local review. */
var PQM_SANDBOX_CONTROLLED_SPREADSHEET_ID = '1lZtneKmCTvFcEL0erlJbegVzTTLNA-IKnjempn1G8Ww';
var PQM_SANDBOX_CONTROLLED_MIN_ROWS = 8;
var PQM_SANDBOX_CONTROLLED_MAX_ROWS = 10;
var PQM_SANDBOX_CONTROLLED_GUARD_CACHE_SECONDS = 21600;
var PQM_SANDBOX_CONTROLLED_COLUMNS = {2: 'C', 4: 'E', 5: 'F', 7: 'H', 8: 'I', 11: 'L'};
var PQM_SANDBOX_CONTROLLED_DESIRED_COMBINATIONS = [
  'C', 'F', 'H', 'C+F', 'C+H', 'F+H', 'C+F+H'
];

function pqmSandboxControlledSpreadsheetId_() {
  var id = SpreadsheetApp.getActiveSpreadsheet().getId();
  if (id !== PQM_SANDBOX_CONTROLLED_SPREADSHEET_ID) {
    throw new Error('PQM SANDBOX: spreadsheet guard rejected this file.');
  }
  pqmSandboxRegistryUrl_();
  return id;
}

function pqmSandboxControlledCanonical_(value) {
  if (Array.isArray(value)) return value.map(pqmSandboxControlledCanonical_);
  if (value && typeof value === 'object') {
    var sorted = {};
    Object.keys(value).sort().forEach(function(key) {
      sorted[key] = pqmSandboxControlledCanonical_(value[key]);
    });
    return sorted;
  }
  return value;
}

function pqmSandboxControlledDigest_(value) {
  var source = JSON.stringify(pqmSandboxControlledCanonical_(value));
  return Utilities.base64EncodeWebSafe(Utilities.computeDigest(
    Utilities.DigestAlgorithm.SHA_256, source, Utilities.Charset.UTF_8
  )).replace(/=+$/, '');
}

function pqmSandboxControlledPlanDigest_(entries) {
  return pqmSandboxControlledDigest_(entries.slice().sort(function(a, b) {
    return a.code < b.code ? -1 : a.code > b.code ? 1 :
      a.tab < b.tab ? -1 : a.tab > b.tab ? 1 : a.row - b.row;
  }));
}

function pqmSandboxControlledUnsafeIdentity_(code) {
  return String(code || '').trim() === '00000000';
}

function pqmSandboxControlledGuardCache_() {
  return CacheService.getScriptCache();
}

function pqmSandboxControlledFail_(reason, entry, oldDigest, newDigest) {
  function prefix(digest) {
    return typeof digest === 'string' && /^[A-Za-z0-9_-]{40,}$/.test(digest) ? digest.slice(0, 8) : null;
  }
  console.log(JSON.stringify({reason: reason,
    tab: entry && (entry.tab === 'ФОП' || entry.tab === 'ЮО') ? entry.tab : null,
    row: entry && Number.isInteger(entry.row) ? entry.row : null,
    planned_columns: entry && Array.isArray(entry.planned_columns) ?
      entry.planned_columns.filter(function(column) { return ['C', 'E', 'F', 'H', 'I', 'L'].indexOf(column) >= 0; }) : [],
    old_digest_prefix: prefix(oldDigest), new_digest_prefix: prefix(newDigest)}));
  throw new Error('PQM SANDBOX: ' + reason + '; no writes.');
}

function pqmSandboxControlledColumns_(change) {
  var columns = Object.keys(change.cells).map(Number).sort(function(a, b) { return a - b; });
  if (!columns.length || columns.some(function(column) {
    return !Object.prototype.hasOwnProperty.call(PQM_SANDBOX_CONTROLLED_COLUMNS, column);
  })) throw new Error('PQM SANDBOX: controlled plan includes an unowned column.');
  return columns;
}

function pqmSandboxControlledPlan_(body, tabs) {
  var plan = pqmGooglePlan_(body, tabs);
  if (plan.counts.appended || plan.counts.conflicts || plan.counts.duplicate_keys || plan.counts.errors ||
      plan.changes.some(function(change) { return change.append; })) {
    throw new Error('PQM SANDBOX: plan contains append, conflict, duplicate or error.');
  }
  return plan;
}

function pqmSandboxControlledCandidates_(plan, tabs, body) {
  var seen = {};
  var itemsByCode = {};
  (body.items || []).forEach(function(item) {
    var code = String(item.supplier_code || '').trim();
    if (!itemsByCode[code]) itemsByCode[code] = [];
    itemsByCode[code].push(item);
  });
  return plan.changes.map(function(change) {
    var tab = tabs[change.tab];
    var row = tab && tab.rows[change.row - 2];
    var code = row && String(row.codeDisplay || '').trim();
    if (pqmSandboxControlledUnsafeIdentity_(code)) return null;
    if (!code || seen[code] || change.row < 2 || change.row > tab.maxRows) {
      throw new Error('PQM SANDBOX: selected row identity is not unique.');
    }
    seen[code] = true;
    if (!itemsByCode[code] || itemsByCode[code].length !== 1) {
      throw new Error('PQM SANDBOX: PQM_VALUE_CHANGED: supplier payload identity is ambiguous.');
    }
    var columns = pqmSandboxControlledColumns_(change);
    return {code: code, tab: change.tab, row: change.row, change: change,
      pqmItem: itemsByCode[code][0],
      columns: columns, combination: columns.map(function(c) { return PQM_SANDBOX_CONTROLLED_COLUMNS[c]; }).join('+')};
  }).filter(Boolean).sort(function(a, b) { return a.code < b.code ? -1 : a.code > b.code ? 1 : 0; });
}

function pqmSandboxControlledSelect_(candidates) {
  var selected = [], used = {}, perTab = {'ФОП': 0, 'ЮО': 0};
  function take(candidate) {
    if (!candidate || used[candidate.code] || selected.length >= PQM_SANDBOX_CONTROLLED_MAX_ROWS) return;
    selected.push(candidate); used[candidate.code] = true; perTab[candidate.tab]++;
  }
  PQM_SANDBOX_CONTROLLED_DESIRED_COMBINATIONS.forEach(function(combination) {
    var matches = candidates.filter(function(c) { return c.combination === combination && !used[c.code]; });
    matches.sort(function(a, b) {
      return perTab[a.tab] - perTab[b.tab] || (a.code < b.code ? -1 : a.code > b.code ? 1 : 0);
    });
    take(matches[0]);
  });
  ['ФОП', 'ЮО'].forEach(function(tab) {
    if (!perTab[tab]) take(candidates.filter(function(c) { return c.tab === tab && !used[c.code]; })[0]);
  });
  for (var i = 0; i < candidates.length && selected.length < PQM_SANDBOX_CONTROLLED_MAX_ROWS; i++) {
    take(candidates[i]);
  }
  if (selected.length < PQM_SANDBOX_CONTROLLED_MIN_ROWS) {
    throw new Error('PQM SANDBOX: fewer than eight safe matched rows are available.');
  }
  return selected.sort(function(a, b) { return a.code < b.code ? -1 : a.code > b.code ? 1 : 0; });
}

function pqmSandboxControlledProtectionCheck_(selected, tabs) {
  selected.forEach(function(entry) {
    (tabs[entry.tab].protectedRanges || []).forEach(function(protection) {
      if (protection.warningOnly) return;
      var range = protection.range || {};
      var row = entry.row - 1;
      if (row < (range.startRowIndex || 0) || row >= (range.endRowIndex === undefined ? Infinity : range.endRowIndex)) return;
      if (entry.columns.some(function(column) {
        var protectedColumn = column >= (range.startColumnIndex || 0) &&
          column < (range.endColumnIndex === undefined ? Infinity : range.endColumnIndex);
        var unprotectedColumn = (protection.unprotectedRanges || []).some(function(exception) {
          return row >= (exception.startRowIndex || 0) &&
            row < (exception.endRowIndex === undefined ? Infinity : exception.endRowIndex) &&
            column >= (exception.startColumnIndex || 0) &&
            column < (exception.endColumnIndex === undefined ? Infinity : exception.endColumnIndex);
        });
        return protectedColumn && !unprotectedColumn;
      }) && protection.requestingUserCanEdit !== true) {
        throw new Error('PQM SANDBOX: selected cell has unaudited protection.');
      }
    });
  });
}

function pqmSandboxControlledReadRows_(spreadsheetId, selected, tabs) {
  var ranges = selected.map(function(entry) {
    return "'" + entry.tab.replace(/'/g, "''") + "'!A" + entry.row + ':O' + entry.row;
  });
  var result = pqmGoogleReadRetry_(function() {
    return Sheets.Spreadsheets.get(spreadsheetId, {
      ranges: ranges, includeGridData: true,
      fields: 'sheets(properties(sheetId),data(startRow,rowData(values(userEnteredValue,effectiveValue,formattedValue,userEnteredFormat,dataValidation,note))))'
    });
  });
  var bySheet = {};
  (result.sheets || []).forEach(function(sheet) {
    (sheet.data || []).forEach(function(data) {
      var cells = ((data.rowData || [])[0] || {}).values || [];
      if (!Number.isInteger(data.startRow) || !cells.length) return;
      bySheet[sheet.properties.sheetId + ':' + (data.startRow + 1)] =
        Array.from({length: 15}, function(_, index) { return cells[index] || {}; });
    });
  });
  return selected.map(function(entry) {
    var cells = bySheet[tabs[entry.tab].id + ':' + entry.row];
    if (!cells) pqmSandboxControlledFail_('ROW_MOVED', entry, null, null);
    if (String(cells[1].formattedValue || '').trim() !== entry.code) {
      pqmSandboxControlledFail_('SUPPLIER_CODE_CHANGED', entry,
        pqmSandboxControlledDigest_(entry.code),
        pqmSandboxControlledDigest_(String(cells[1].formattedValue || '').trim()));
    }
    return cells;
  });
}

function pqmSandboxControlledRowState_(cells) {
  return cells.map(function(cell, index) {
    var stable = {userEnteredValue: cell.userEnteredValue || null,
      userEnteredFormat: cell.userEnteredFormat || null,
      dataValidation: cell.dataValidation || null, note: cell.note || null};
    if (index === 1) stable.codeDisplay = cell.formattedValue || '';
    return stable;
  });
}

function pqmSandboxControlledPqmState_(item) {
  function blankAsNull(value) { return pqmGoogleBlank_(value) ? null : value; }
  var date = pqmGoogleCalendarDate_(item.google_sync_last_decided_application_date);
  var verificationDate = pqmGoogleCalendarDate_(item.verification_date);
  return {supplier_code: item.supplier_code, entity_type: item.entity_type,
    monitoring_eligible: item.monitoring_eligible,
    google_sync_eligible: item.google_sync_eligible,
    supplier_name: blankAsNull(item.supplier_name),
    edr_status_current: blankAsNull(item.edr_status_current),
    prozorro_status_google: blankAsNull(item.prozorro_status_google),
    google_sync_last_decided_application_date: date.kind === 'date' ? date.value :
      blankAsNull(item.google_sync_last_decided_application_date),
    verification_date: verificationDate.kind === 'date' ? verificationDate.value : blankAsNull(item.verification_date),
    verification_officer: blankAsNull(item.verification_officer)};
}

function pqmSandboxControlledState_(selected, rows) {
  var entries = selected.map(function(entry, index) {
    var cells = pqmSandboxControlledRowState_(rows[index]);
    var cellDigests = cells.map(pqmSandboxControlledDigest_);
    return {code: entry.code, tab: entry.tab, row: entry.row,
      planned_columns: entry.columns.map(function(column) { return PQM_SANDBOX_CONTROLLED_COLUMNS[column]; }),
      pqm_value_digest: pqmSandboxControlledDigest_(pqmSandboxControlledPqmState_(entry.pqmItem)),
      planned_cells_digest: pqmSandboxControlledDigest_(entry.change.cells),
      cell_digests: cellDigests,
      before_digest: pqmSandboxControlledDigest_(cellDigests)};
  }).sort(function(a, b) {
    return a.code < b.code ? -1 : a.code > b.code ? 1 :
      a.tab < b.tab ? -1 : a.tab > b.tab ? 1 : a.row - b.row;
  });
  return {entries: entries, plan_digest: pqmSandboxControlledPlanDigest_(entries)};
}

function pqmSandboxControlledGuard_(expected, current) {
  if (pqmSandboxControlledPlanDigest_(expected.entries) !== expected.plan_digest) {
    pqmSandboxControlledFail_('PLAN_DIGEST_CHANGED', null, expected.plan_digest,
      pqmSandboxControlledPlanDigest_(expected.entries));
  }
  var computed = pqmSandboxControlledPlanDigest_(current.entries);
  if (computed !== pqmSandboxControlledPlanDigest_(current.entries) || computed !== current.plan_digest) {
    pqmSandboxControlledFail_('DIGEST_NONDETERMINISTIC', null, current.plan_digest, computed);
  }
  var previousEntries = expected.entries.slice().sort(function(a, b) {
    return a.code < b.code ? -1 : a.code > b.code ? 1 : 0;
  });
  var currentEntries = current.entries.slice().sort(function(a, b) {
    return a.code < b.code ? -1 : a.code > b.code ? 1 : 0;
  });
  var beforeCodes = previousEntries.map(function(entry) { return entry.code; });
  var afterCodes = currentEntries.map(function(entry) { return entry.code; });
  if (pqmSandboxControlledDigest_(beforeCodes) !== pqmSandboxControlledDigest_(afterCodes)) {
    pqmSandboxControlledFail_('SELECTED_CODES_CHANGED', null,
      pqmSandboxControlledDigest_(beforeCodes), pqmSandboxControlledDigest_(afterCodes));
  }
  previousEntries.forEach(function(before, index) {
    var now = currentEntries[index];
    if (!now || before.code !== now.code) {
      pqmSandboxControlledFail_('SELECTED_CODES_CHANGED', before,
        pqmSandboxControlledDigest_(before.code), now ? pqmSandboxControlledDigest_(now.code) : null);
    }
    if (before.tab !== now.tab || before.row !== now.row) {
      pqmSandboxControlledFail_('ROW_MOVED', before,
        pqmSandboxControlledDigest_([before.tab, before.row]),
        pqmSandboxControlledDigest_([now.tab, now.row]));
    }
    if (before.pqm_value_digest !== now.pqm_value_digest) {
      pqmSandboxControlledFail_('PQM_PLANNED_VALUES_CHANGED', before,
        before.pqm_value_digest, now.pqm_value_digest);
    }
    if (pqmSandboxControlledDigest_(before.planned_columns) !==
        pqmSandboxControlledDigest_(now.planned_columns) ||
        before.planned_cells_digest !== now.planned_cells_digest) {
      pqmSandboxControlledFail_('PLAN_DIGEST_CHANGED', before,
        before.planned_cells_digest, now.planned_cells_digest);
    }
    if (before.before_digest !== now.before_digest) {
      if (!Array.isArray(before.cell_digests) || !Array.isArray(now.cell_digests) ||
          before.cell_digests.length !== 15 || now.cell_digests.length !== 15) {
        pqmSandboxControlledFail_('GOOGLE_BEFORE_DIGEST_CHANGED', before,
          before.before_digest, now.before_digest);
      }
      for (var column = 0; column < 15; column++) {
        if (before.cell_digests[column] === now.cell_digests[column]) continue;
        var letter = String.fromCharCode(65 + column);
        pqmSandboxControlledFail_(before.planned_columns.indexOf(letter) < 0 ?
          'UNTOUCHED_CELL_CHANGED' : 'GOOGLE_BEFORE_DIGEST_CHANGED', before,
          before.cell_digests[column], now.cell_digests[column]);
      }
      pqmSandboxControlledFail_('DIGEST_NONDETERMINISTIC', before,
        before.before_digest, now.before_digest);
    }
  });
  if (expected.plan_digest !== current.plan_digest) {
    pqmSandboxControlledFail_('DIGEST_NONDETERMINISTIC', null,
      expected.plan_digest, current.plan_digest);
  }
}

function pqmSandboxControlledPreview() {
  var id = pqmSandboxControlledSpreadsheetId_();
  var body = pqmSandboxFetchRegistry_();
  var tabs = pqmGoogleSnapshot_(id);
  var plan = pqmSandboxControlledPlan_(body, tabs);
  var candidates = pqmSandboxControlledCandidates_(plan, tabs, body);
  var selected = pqmSandboxControlledSelect_(candidates);
  pqmSandboxControlledProtectionCheck_(selected, tabs);
  var rows = pqmSandboxControlledReadRows_(id, selected, tabs);
  var state = pqmSandboxControlledState_(selected, rows);
  pqmSandboxControlledGuardCache_().put(state.plan_digest, JSON.stringify(state),
    PQM_SANDBOX_CONTROLLED_GUARD_CACHE_SECONDS);
  var output = {dry_run: true, google_writes: 0, plan_digest: state.plan_digest,
    available_combinations: PQM_SANDBOX_CONTROLLED_DESIRED_COMBINATIONS.filter(function(combination) {
      return candidates.some(function(candidate) { return candidate.combination === combination; });
    }),
    selected: state.entries.map(function(entry, index) {
      return {supplier_code: entry.code, tab: entry.tab, row: entry.row,
        planned_columns: entry.planned_columns,
        combination: selected[index].combination, before_digest: entry.before_digest};
    }),
    selected_rows: selected.length,
    planned_cells: selected.reduce(function(total, entry) { return total + entry.columns.length; }, 0)};
  console.log(JSON.stringify(output));
  return output;
}

function pqmSandboxControlledRequests_(selected, tabs) {
  var requests = [];
  selected.forEach(function(entry) {
    entry.columns.forEach(function(column) {
      var value = entry.change.cells[column];
      if (pqmGoogleBlank_(value)) throw new Error('PQM SANDBOX: blank planned value.');
      var dateColumn = column === 7 || column === 8;
      var cell = {userEnteredValue: dateColumn ? {numberValue: value} : {stringValue: value}};
      if (dateColumn) cell.userEnteredFormat = {numberFormat: {type: 'DATE', pattern: 'dd.MM.yyyy'}};
      requests.push({updateCells: {
        range: {sheetId: tabs[entry.tab].id, startRowIndex: entry.row - 1,
          endRowIndex: entry.row, startColumnIndex: column, endColumnIndex: column + 1},
        rows: [{values: [cell]}],
        fields: dateColumn ? 'userEnteredValue,userEnteredFormat.numberFormat' : 'userEnteredValue'
      }});
    });
  });
  if (!requests.length || requests.length > PQM_SANDBOX_CONTROLLED_MAX_ROWS * 6) {
    throw new Error('PQM SANDBOX: controlled write limit exceeded.');
  }
  return requests;
}

function pqmSandboxControlledVerify_(selected, before, after) {
  var failures = [], changedCells = 0;
  selected.forEach(function(entry, rowIndex) {
    var stableBefore = pqmSandboxControlledRowState_(before[rowIndex]);
    var stableAfter = pqmSandboxControlledRowState_(after[rowIndex]);
    for (var column = 0; column < 15; column++) {
      var actual = after[rowIndex][column] || {};
      if (entry.columns.indexOf(column) < 0) {
        if (pqmSandboxControlledDigest_(stableBefore[column]) !==
            pqmSandboxControlledDigest_(stableAfter[column])) failures.push({row: entry.row, tab: entry.tab, column: column + 1,
              reason: 'unplanned_cell_changed'});
        continue;
      }
      changedCells++;
      var expected = entry.change.cells[column];
      var entered = actual.userEnteredValue || {};
      var equal = (column === 7 || column === 8) ? entered.numberValue === expected : entered.stringValue === expected;
      if (column === 7 || column === 8) {
        equal = equal && (((actual.userEnteredFormat || {}).numberFormat || {}).pattern === 'dd.MM.yyyy');
      }
      if (!equal) failures.push({row: entry.row, tab: entry.tab, column: column + 1,
        reason: 'planned_cell_not_expected'});
    }
  });
  return {verification_passed: failures.length === 0, verified_owned_cells: changedCells,
    failures: failures};
}

function pqmSandboxControlledApply() {
  var ui = SpreadsheetApp.getUi();
  var codesAnswer = ui.prompt('PQM SANDBOX controlled Apply',
    'Paste 8–10 supplier codes from controlled Preview, separated by commas.', ui.ButtonSet.OK_CANCEL);
  if (codesAnswer.getSelectedButton() !== ui.Button.OK) return {cancelled: true, google_writes: 0};
  var codes = codesAnswer.getResponseText().split(/[,\n]/).map(function(code) { return code.trim(); }).filter(Boolean);
  if (codes.length < PQM_SANDBOX_CONTROLLED_MIN_ROWS ||
      codes.length > PQM_SANDBOX_CONTROLLED_MAX_ROWS || new Set(codes).size !== codes.length) {
    throw new Error('PQM SANDBOX: select 8–10 distinct supplier codes.');
  }
  if (codes.some(pqmSandboxControlledUnsafeIdentity_)) {
    pqmSandboxControlledFail_('UNSAFE_PLACEHOLDER_IDENTITY', null, null, null);
  }
  var digestAnswer = ui.prompt('PQM SANDBOX controlled Apply',
    'Paste plan_digest from the NEW controlled Preview.', ui.ButtonSet.OK_CANCEL);
  if (digestAnswer.getSelectedButton() !== ui.Button.OK) return {cancelled: true, google_writes: 0};
  var digest = digestAnswer.getResponseText().trim();
  if (!/^[A-Za-z0-9_-]{40,}$/.test(digest)) {
    pqmSandboxControlledFail_('PLAN_DIGEST_CHANGED', null, null, null);
  }
  var saved = pqmSandboxControlledGuardCache_().get(digest);
  if (!saved) pqmSandboxControlledFail_('GUARD_MANIFEST_EXPIRED', null, digest, null);
  var expected;
  try { expected = JSON.parse(saved); } catch (_) {
    pqmSandboxControlledFail_('PLAN_DIGEST_CHANGED', null, digest, null);
  }
  if (!expected || !Array.isArray(expected.entries) ||
      expected.plan_digest !== digest) {
    pqmSandboxControlledFail_('PLAN_DIGEST_CHANGED', null, digest,
      expected && expected.plan_digest);
  }
  if (pqmSandboxControlledDigest_(expected.entries.map(function(entry) { return entry.code; }).sort()) !==
      pqmSandboxControlledDigest_(codes.slice().sort())) {
    pqmSandboxControlledFail_('SELECTED_CODES_CHANGED', null,
      pqmSandboxControlledDigest_(expected.entries.map(function(entry) { return entry.code; }).sort()),
      pqmSandboxControlledDigest_(codes.slice().sort()));
  }
  var answer = ui.alert('PQM SANDBOX controlled Apply',
    'Write only the planned C/E/F/H/I/L cells in ' + codes.length +
      ' explicitly selected rows? This does not run Apply for the full registry.', ui.ButtonSet.YES_NO);
  if (answer !== ui.Button.YES) return {cancelled: true, google_writes: 0};

  var lock = LockService.getScriptLock();
  if (!lock.tryLock(0)) throw new Error('PQM SANDBOX: another operation is running.');
  try {
    var id = pqmSandboxControlledSpreadsheetId_();
    var body = pqmSandboxFetchRegistry_();
    var tabs = pqmGoogleSnapshot_(id);
    var plan = pqmSandboxControlledPlan_(body, tabs);
    var candidates = pqmSandboxControlledCandidates_(plan, tabs, body);
    var byCode = {};
    candidates.forEach(function(candidate) { byCode[candidate.code] = candidate; });
    var selected = codes.map(function(code) {
      if (!byCode[code]) {
        var previous = expected.entries.filter(function(entry) { return entry.code === code; })[0];
        var found = null;
        Object.keys(tabs).forEach(function(tab) {
          (tabs[tab].rows || []).forEach(function(row, index) {
            if (String(row.codeDisplay || '').trim() === code) found = {tab: tab, row: index + 2};
          });
        });
        if (found && previous && (found.tab !== previous.tab || found.row !== previous.row)) {
          pqmSandboxControlledFail_('ROW_MOVED', previous,
            pqmSandboxControlledDigest_([previous.tab, previous.row]),
            pqmSandboxControlledDigest_([found.tab, found.row]));
        }
        if (previous && tabs[previous.tab] && tabs[previous.tab].rows[previous.row - 2] &&
            String(tabs[previous.tab].rows[previous.row - 2].codeDisplay || '').trim() !== code) {
          pqmSandboxControlledFail_('SUPPLIER_CODE_CHANGED', previous,
            pqmSandboxControlledDigest_(code),
            pqmSandboxControlledDigest_(String(tabs[previous.tab].rows[previous.row - 2].codeDisplay || '').trim()));
        }
        pqmSandboxControlledFail_('PLAN_DIGEST_CHANGED', previous || null, null, null);
      }
      return byCode[code];
    }).sort(function(a, b) { return a.code < b.code ? -1 : a.code > b.code ? 1 : 0; });
    pqmSandboxControlledProtectionCheck_(selected, tabs);
    var before = pqmSandboxControlledReadRows_(id, selected, tabs);
    var state = pqmSandboxControlledState_(selected, before);
    pqmSandboxControlledGuard_(expected, state);
    var rechecked = pqmSandboxControlledReadRows_(id, selected, tabs);
    pqmSandboxControlledGuard_(expected, pqmSandboxControlledState_(selected, rechecked));
    var requests = pqmSandboxControlledRequests_(selected, tabs);
    Sheets.Spreadsheets.batchUpdate({requests: requests}, id);
    var after;
    try {
      after = pqmSandboxControlledReadRows_(id, selected, tabs);
    } catch (_) {
      console.log(JSON.stringify({selected_rows: selected.length, written_cells: requests.length,
        verification_passed: false, failures: [{reason: 'after_read_failed'}]}));
      throw new Error('PQM SANDBOX: write completed but AFTER verification could not read rows.');
    }
    var verification = pqmSandboxControlledVerify_(selected, before, after);
    var report = {selected_rows: selected.length, written_cells: requests.length,
      verification_passed: verification.verification_passed,
      verified_owned_cells: verification.verified_owned_cells,
      failures: verification.failures};
    console.log(JSON.stringify(report));
    return report;
  } finally {
    lock.releaseLock();
  }
}
