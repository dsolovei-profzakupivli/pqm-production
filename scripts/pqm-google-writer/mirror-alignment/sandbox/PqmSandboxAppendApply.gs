// Dedicated bounded append stage. Uses the same canonical planner as Full Preview.
var PQM_SANDBOX_APPEND_MAX_ROWS = 50;
var PQM_SANDBOX_APPEND_CODE_SCAN_ROWS = 1000;
var PQM_SANDBOX_APPEND_CONFIRMATION = 'APPLY_SANDBOX_SUPPLIER_APPEND_MAX_50';

function pqmSandboxAppendLoad_(id, allowlist, fullLoaded, maxRows) {
  var full = fullLoaded || null;
  var body = full ? full.body : pqmSandboxFetchRegistry_();
  var tabs = full ? full.tabs : pqmGoogleSnapshot_(id);
  var plan = full ? full.plan : pqmGooglePlan_(body, tabs);
  var candidates = plan.changes.filter(function(change) { return change.append; });
  if (allowlist !== undefined) {
    if (!Array.isArray(allowlist) || !allowlist.length ||
        allowlist.length > PQM_SANDBOX_APPEND_MAX_ROWS || new Set(allowlist).size !== allowlist.length) {
      throw new Error('PQM SANDBOX APPEND: invalid supplier allowlist.');
    }
    var byCode = {};
    candidates.forEach(function(change) { byCode[String(change.cells[1]).trim()] = change; });
    candidates = allowlist.map(function(code) {
      if (!byCode[code]) throw new Error('PQM SANDBOX APPEND: allowlisted supplier has no safe APPEND.');
      return byCode[code];
    });
  }
  var limit = maxRows === undefined ? PQM_SANDBOX_APPEND_MAX_ROWS : maxRows;
  if (!Number.isInteger(limit) || limit < 1 || limit > PQM_SANDBOX_APPEND_MAX_ROWS) {
    throw new Error('PQM SANDBOX APPEND: invalid bounded page size.');
  }
  var selected = candidates.slice(0, limit);
  var next = {};
  PQM_GOOGLE_TABS.forEach(function(name) { next[name] = tabs[name].rows.length + 2; });
  selected = selected.map(function(change) {
    var row = next[change.tab]++, cells = Object.assign({}, change.cells);
    cells[0] = pqmGoogleFreshnessFormula_(row, tabs[change.tab].formulaLocale);
    return {tab: change.tab, row: row, append: true, cells: cells};
  });
  var state = pqmSandboxFullState_(body, tabs, plan);
  var digest = pqmSandboxControlledDigest_({version: 1, spreadsheet_id: id,
    state: state, selected: selected});
  return {body: body, tabs: tabs, plan: plan, selected: selected, digest: digest,
    payload_digest: state.payload_digest};
}

function pqmSandboxAppendPayloadDigest_(body) {
  return pqmSandboxControlledDigest_(body.items.map(pqmSandboxControlledPqmState_).sort(function(a, b) {
    return a.supplier_code < b.supplier_code ? -1 : a.supplier_code > b.supplier_code ? 1 : 0;
  }));
}

/* Scan only displayed B values, in bounded chunks; never retain another full Sheet snapshot. */
function pqmSandboxAppendCodeCounts_(id, tabs, selected) {
  var counts = new Map(selected.map(function(change) { return [String(change.cells[1]).trim(), 0]; }));
  PQM_GOOGLE_TABS.forEach(function(name) {
    var tab = tabs[name], esc = "'" + name.replace(/'/g, "''") + "'";
    for (var first = 2; first <= tab.maxRows; first += PQM_SANDBOX_APPEND_CODE_SCAN_ROWS) {
      var last = Math.min(tab.maxRows, first + PQM_SANDBOX_APPEND_CODE_SCAN_ROWS - 1);
      var response = Sheets.Spreadsheets.Values.batchGet(id, {
        ranges: [esc + '!B' + first + ':B' + last], valueRenderOption: 'FORMATTED_VALUE'
      });
      if (!response || !Array.isArray(response.valueRanges) || response.valueRanges.length !== 1) {
        throw new Error('PQM SANDBOX APPEND: identity scan incomplete; no write/retry.');
      }
      (response.valueRanges[0].values || []).forEach(function(row) {
        var code = String((row || [])[0] || '').trim();
        if (counts.has(code)) counts.set(code, counts.get(code) + 1);
      });
    }
  });
  return counts;
}

function pqmSandboxAppendGridCounts_(id, tabs) {
  var response = Sheets.Spreadsheets.get(id, {includeGridData: false,
    fields: 'sheets(properties(title,sheetId,gridProperties(rowCount)))'});
  var actual = new Map((response.sheets || []).map(function(sheet) {
    return [sheet.properties.title, sheet.properties];
  }));
  PQM_GOOGLE_TABS.forEach(function(name) {
    var property = actual.get(name);
    if (!property || property.sheetId !== tabs[name].id ||
        property.gridProperties.rowCount !== tabs[name].maxRows) {
      throw new Error('PQM SANDBOX APPEND: Sheet dimensions changed; no write/retry.');
    }
  });
}

function pqmSandboxAppendPrewriteGuard_(id, loaded) {
  var freshBody = pqmSandboxFetchRegistry_();
  if (freshBody.count !== freshBody.items.length ||
      pqmSandboxAppendPayloadDigest_(freshBody) !== loaded.payload_digest) {
    throw new Error('PQM SANDBOX APPEND: PQM source changed; zero writes.');
  }
  pqmSandboxAppendGridCounts_(id, loaded.tabs);
  var counts = pqmSandboxAppendCodeCounts_(id, loaded.tabs, loaded.selected);
  counts.forEach(function(count) {
    if (count !== 0) throw new Error('PQM SANDBOX APPEND: selected identity already exists; zero writes.');
  });
  var ranges = [], selectedTabs = [];
  PQM_GOOGLE_TABS.forEach(function(name) {
    var additions = loaded.selected.filter(function(change) { return change.tab === name; });
    if (!additions.length || additions[0].row > loaded.tabs[name].maxRows) return;
    var last = Math.min(additions[additions.length - 1].row, loaded.tabs[name].maxRows);
    ranges.push("'" + name.replace(/'/g, "''") + "'!A" + additions[0].row + ':O' + last);
    selectedTabs.push(name);
  });
  if (!ranges.length) return;
  var response = Sheets.Spreadsheets.Values.batchGet(id, {
    ranges: ranges, valueRenderOption: 'FORMULA'
  });
  if (!response || !Array.isArray(response.valueRanges) || response.valueRanges.length !== ranges.length) {
    throw new Error('PQM SANDBOX APPEND: target-row guard incomplete; zero writes.');
  }
  response.valueRanges.forEach(function(range) {
    if ((range.values || []).some(function(row) { return row.some(function(value) { return !pqmGoogleBlank_(value); }); })) {
      throw new Error('PQM SANDBOX APPEND: destination row changed; zero writes.');
    }
  });
}

function pqmSandboxAppendPreview(allowlist) {
  var id = pqmSandboxControlledSpreadsheetId_(), loaded = pqmSandboxAppendLoad_(id, allowlist);
  var output = {dry_run: true, google_writes: 0, selected: loaded.selected.length,
    selected_codes: loaded.selected.map(function(change) { return change.cells[1]; }),
    remaining: loaded.plan.counts.appended - loaded.selected.length,
    conflicts: loaded.plan.counts.conflicts, append_digest: loaded.digest, blocked: 0};
  console.log(JSON.stringify(output));
  return output;
}

function pqmSandboxAppendAllowlistPreview() {
  var ui = SpreadsheetApp.getUi();
  var answer = ui.prompt('PQM SANDBOX append Preview',
    'Paste 1–50 exact supplier codes, separated by commas.', ui.ButtonSet.OK_CANCEL);
  if (answer.getSelectedButton() !== ui.Button.OK) return {cancelled: true, google_writes: 0};
  var codes = answer.getResponseText().split(/[,\n]/).map(function(code) { return code.trim(); }).filter(Boolean);
  return pqmSandboxAppendPreview(codes);
}

function pqmSandboxAppendRange_(id, row, column, height, width) {
  return {sheetId: id, startRowIndex: row - 1, endRowIndex: row - 1 + height,
    startColumnIndex: column, endColumnIndex: column + width};
}

function pqmSandboxAppendRequests_(selected, tabs) {
  var requests = [], allowed = [0, 1, 2, 3, 4, 5, 7, 8, 11];
  PQM_GOOGLE_TABS.forEach(function(name) {
    var tab = tabs[name], additions = selected.filter(function(change) { return change.tab === name; });
    if (!additions.length) return;
    var first = additions[0].row, last = additions[additions.length - 1].row;
    var template = tab.rows.length + 1;
    if (first !== template + 1 || additions.some(function(change, index) {
      return change.row !== first + index || !change.append ||
        change.cells[0] !== pqmGoogleFreshnessFormula_(change.row, tab.formulaLocale) ||
        Object.keys(change.cells).some(function(column) { return allowed.indexOf(Number(column)) < 0; });
    })) throw new Error('PQM SANDBOX APPEND: noncontiguous or unsafe plan; zero writes.');
    if (last > tab.maxRows) requests.push({appendDimension: {sheetId: tab.id,
      dimension: 'ROWS', length: last - tab.maxRows}});
    ['PASTE_FORMAT', 'PASTE_DATA_VALIDATION'].forEach(function(type) {
      // Copy formatting/validation only, never template manual values.
      [[0, 15]].forEach(function(span) {
        requests.push({copyPaste: {source: pqmSandboxAppendRange_(tab.id, template, span[0], 1, span[1]),
          destination: pqmSandboxAppendRange_(tab.id, first, span[0], additions.length, span[1]), pasteType: type}});
      });
    });
    requests.push({updateDimensionProperties: {range: {sheetId: tab.id, dimension: 'ROWS',
      startIndex: first - 1, endIndex: last}, properties: {pixelSize: tab.templateRowHeight}, fields: 'pixelSize'}});
    tab.conditionalFormats.forEach(function(rule, index) {
      var copy = JSON.parse(JSON.stringify(rule)), changed = false;
      (copy.ranges || []).forEach(function(range) {
        if ((range.startRowIndex || 0) <= template - 1 && range.endRowIndex !== undefined &&
            range.endRowIndex >= template && range.endRowIndex < last) {
          range.endRowIndex = last; changed = true;
        }
      });
      if (changed) requests.push({updateConditionalFormatRule: {sheetId: tab.id, index: index, rule: copy}});
    });
    additions.forEach(function(change) {
      requests.push({updateCells: {range: pqmSandboxAppendRange_(tab.id, change.row, 0, 1, 1),
        rows: [{values: [{userEnteredValue: {formulaValue: change.cells[0]}}]}], fields: 'userEnteredValue'}});
      allowed.forEach(function(column) {
        if (column === 0) return;
        if (!Object.prototype.hasOwnProperty.call(change.cells, column)) return;
        var value = change.cells[column], isDate = column === 7 || column === 8;
        var cell = {userEnteredValue: isDate ? {numberValue: value} : {stringValue: value}};
        if (isDate) cell.userEnteredFormat = {numberFormat: {type: column === 8 ? 'DATE_TIME' : 'DATE', pattern: column === 8 ? 'dd.MM.yyyy HH:mm:ss' : 'dd.MM.yyyy'}};
        if (column === 1) cell.userEnteredFormat = {numberFormat: {type: 'TEXT', pattern: '@'}};
        requests.push({updateCells: {range: pqmSandboxAppendRange_(tab.id, change.row, column, 1, 1),
          rows: [{values: [cell]}], fields: 'userEnteredValue' +
            (isDate || column === 1 ? ',userEnteredFormat.numberFormat' : '')}});
      });
    });
  });
  return requests;
}

function pqmSandboxAppendRowMetadata_(id, tab, row) {
  var range = "'" + tab.replace(/'/g, "''") + "'!A" + row + ':O' + row;
  var response = Sheets.Spreadsheets.get(id, {ranges: [range], includeGridData: true,
    fields: 'sheets(data(rowData(values(userEnteredFormat,dataValidation)),rowMetadata(pixelSize)))'});
  var data = (((response.sheets || [])[0] || {}).data || [])[0] || {};
  var cells = (((data.rowData || [])[0] || {}).values || []);
  var height = (((data.rowMetadata || [])[0] || {}).pixelSize);
  if (cells.length !== 15 || !Number.isInteger(height) || height <= 0) {
    throw new Error('PQM SANDBOX APPEND: row metadata unavailable; zero writes.');
  }
  return {cells: cells, height: height};
}

function pqmSandboxAppendVerifyMetadata_(id, selected, templates) {
  var ranges = [], names = [];
  PQM_GOOGLE_TABS.forEach(function(name) {
    var rows = selected.filter(function(change) { return change.tab === name; });
    if (!rows.length) return;
    if (rows.some(function(change, index) { return change.row !== rows[0].row + index; })) {
      throw new Error('PQM SANDBOX APPEND: metadata rows are not contiguous.');
    }
    ranges.push("'" + name.replace(/'/g, "''") + "'!A" + rows[0].row + ':O' + rows[rows.length - 1].row);
    names.push(name);
  });
  if (!ranges.length) return;
  var response = Sheets.Spreadsheets.get(id, {ranges: ranges, includeGridData: true,
    fields: 'sheets(properties(title),data(startRow,startColumn,rowData(values(userEnteredFormat,dataValidation)),rowMetadata(pixelSize)))'});
  var byName = new Map((response.sheets || []).map(function(sheet) {
    return [sheet.properties.title, sheet];
  }));
  names.forEach(function(name) {
    var sheet = byName.get(name), data = sheet && sheet.data && sheet.data[0];
    var rowData = data && data.rowData || [], rowMetadata = data && data.rowMetadata || [];
    var rows = selected.filter(function(change) { return change.tab === name; });
    if (rowData.length !== rows.length || rowMetadata.length !== rows.length) {
      throw new Error('PQM SANDBOX APPEND: batched row metadata incomplete.');
    }
    rows.forEach(function(change, index) {
      var template = templates[name], cells = rowData[index].values || [], height = rowMetadata[index].pixelSize;
      if (!template || cells.length !== 15 || !Number.isInteger(height) || height !== template.height) {
        throw new Error('PQM SANDBOX APPEND: row metadata mismatch.');
      }
      for (var column = 0; column < 15; column++) {
        var expected = template.cells[column] || {}, actual = cells[column] || {};
        if (JSON.stringify(expected.dataValidation || null) !== JSON.stringify(actual.dataValidation || null)) {
          throw new Error('PQM SANDBOX APPEND: validation mismatch.');
        }
        var expectedFormat = JSON.parse(JSON.stringify(expected.userEnteredFormat || {}));
        var actualFormat = JSON.parse(JSON.stringify(actual.userEnteredFormat || {}));
        if ([1, 7, 8].indexOf(column) >= 0 && Object.prototype.hasOwnProperty.call(change.cells, column)) {
          delete expectedFormat.numberFormat;
          if (!actualFormat.numberFormat || actualFormat.numberFormat.pattern !==
              (column === 1 ? '@' : column === 8 ? 'dd.MM.yyyy HH:mm:ss' : 'dd.MM.yyyy')) {
            throw new Error('PQM SANDBOX APPEND: date/code format mismatch.');
          }
          delete actualFormat.numberFormat;
        }
        if (JSON.stringify(expectedFormat) !== JSON.stringify(actualFormat)) {
          throw new Error('PQM SANDBOX APPEND: format mismatch.');
        }
      }
    });
  });
}

function pqmSandboxAppendVerify_(id, selected, before) {
  var rawRanges = [], codeRanges = [], groups = [];
  PQM_GOOGLE_TABS.forEach(function(name) {
    var additions = selected.filter(function(change) { return change.tab === name; });
    if (!additions.length) return;
    var esc = "'" + name.replace(/'/g, "''") + "'", first = additions[0].row;
    var last = additions[additions.length - 1].row;
    rawRanges.push(esc + '!A' + first + ':O' + last);
    codeRanges.push(esc + '!B' + first + ':B' + last);
    groups.push({name: name, additions: additions, first: first, last: last});
  });
  var rawResponse = Sheets.Spreadsheets.Values.batchGet(id, {
    ranges: rawRanges, valueRenderOption: 'UNFORMATTED_VALUE'
  });
  var codeResponse = Sheets.Spreadsheets.Values.batchGet(id, {
    ranges: codeRanges, valueRenderOption: 'FORMATTED_VALUE'
  });
  if (!rawResponse || !Array.isArray(rawResponse.valueRanges) ||
      rawResponse.valueRanges.length !== rawRanges.length ||
      !codeResponse || !Array.isArray(codeResponse.valueRanges) ||
      codeResponse.valueRanges.length !== codeRanges.length) {
    throw new Error('PQM SANDBOX APPEND: AFTER read-back incomplete; new Preview required.');
  }
  var formulaResponse = Sheets.Spreadsheets.Values.batchGet(id, {ranges: rawRanges, valueRenderOption: 'FORMULA'});
  if (!formulaResponse || !Array.isArray(formulaResponse.valueRanges) || formulaResponse.valueRanges.length !== rawRanges.length) {
    throw new Error('PQM SANDBOX APPEND: formula read-back incomplete; new Preview required.');
  }
  groups.forEach(function(group, index) {
    var raw = rawResponse.valueRanges[index].values || [];
    var codes = codeResponse.valueRanges[index].values || [];
    group.additions.forEach(function(change) {
      var offset = change.row - group.first, row = raw[offset] || [];
      var formulas = (formulaResponse.valueRanges[index].values || [])[offset] || [];
      var expectedA = pqmGoogleFreshnessFormula_(change.row, before[group.name].formulaLocale);
      if (formulas[0] !== expectedA) throw new Error('PQM SANDBOX APPEND: formula A mismatch; new Preview required.');
      if (String((codes[offset] || [])[0] || '').trim() !== String(change.cells[1]).trim() ||
          [6, 9, 10, 12, 13, 14].some(function(column) { return !pqmGoogleBlank_(row[column]); })) {
        throw new Error('PQM SANDBOX APPEND: AFTER verification failed; new Preview required.');
      }
      Object.keys(change.cells).forEach(function(column) {
        if (Number(column) === 0) return; // Formula A is verified from FORMULA read-back above.
        var actual = row[column], expected = change.cells[column];
        if (Number(column) === 7 || Number(column) === 8) {
          var matches = Number(column) === 8 ?
            pqmVerificationDatetime_(actual).kind === 'datetime' &&
              pqmVerificationDatetime_(actual).value === pqmVerificationDatetime_(expected).value :
            pqmGoogleCalendarDate_(actual).value === pqmGoogleCalendarDate_(expected).value;
          if (!matches) {
            throw new Error('PQM SANDBOX APPEND: AFTER date mismatch; new Preview required.');
          }
        } else if (String(actual) !== String(expected)) {
          throw new Error('PQM SANDBOX APPEND: AFTER value mismatch; new Preview required.');
        }
      });
    });
  });
  var afterTabs = {};
  PQM_GOOGLE_TABS.forEach(function(name) {
    var last = selected.filter(function(change) { return change.tab === name; })
      .reduce(function(max, change) { return Math.max(max, change.row); }, before[name].maxRows);
    afterTabs[name] = {id: before[name].id, maxRows: last};
  });
  pqmSandboxAppendGridCounts_(id, afterTabs);
}

function pqmSandboxAppendApply() {
  pqmMirrorContext_();
  var ui = SpreadsheetApp.getUi();
  var codesAnswer = ui.prompt('PQM SANDBOX append',
    'Optional: paste exact supplier codes from allowlist Preview, or leave blank for the first safe batch.',
    ui.ButtonSet.OK_CANCEL);
  if (codesAnswer.getSelectedButton() !== ui.Button.OK) return {cancelled: true, google_writes: 0};
  var codes = codesAnswer.getResponseText().split(/[,\n]/).map(function(code) { return code.trim(); }).filter(Boolean);
  var digestAnswer = ui.prompt('PQM SANDBOX append', 'Paste append_digest from fresh Preview.',
    ui.ButtonSet.OK_CANCEL);
  if (digestAnswer.getSelectedButton() !== ui.Button.OK) return {cancelled: true, google_writes: 0};
  var digest = digestAnswer.getResponseText().trim();
  var confirmAnswer = ui.prompt('PQM SANDBOX append', 'Type ' + PQM_SANDBOX_APPEND_CONFIRMATION,
    ui.ButtonSet.OK_CANCEL);
  if (confirmAnswer.getSelectedButton() !== ui.Button.OK ||
      confirmAnswer.getResponseText().trim() !== PQM_SANDBOX_APPEND_CONFIRMATION || !digest) {
    throw new Error('PQM SANDBOX APPEND: explicit confirmation and digest required; zero writes.');
  }
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(0)) throw new Error('PQM SANDBOX APPEND: locked; zero writes.');
  try {
    var id = pqmSandboxControlledSpreadsheetId_(), loaded = pqmSandboxAppendLoad_(id, codes.length ? codes : undefined);
    if (!loaded.selected.length || loaded.digest !== digest) {
      throw new Error('PQM SANDBOX APPEND: stale or empty selection; zero writes.');
    }
    // The initial full-state digest matches Preview; only selected identities,
    // destination rows and the PQM source need another read before mutation.
    delete loaded.body;
    delete loaded.plan;
    pqmSandboxAppendPrewriteGuard_(id, loaded);
    var templates = {};
    loaded.selected.forEach(function(change) {
      if (!templates[change.tab]) templates[change.tab] = pqmSandboxAppendRowMetadata_(id,
        change.tab, loaded.tabs[change.tab].rows.length + 1);
    });
    var requests = pqmSandboxAppendRequests_(loaded.selected, loaded.tabs);
    if (!requests.length) throw new Error('PQM SANDBOX APPEND: empty request; zero writes.');
    try { pqmMirrorSheetsBatchUpdate_({requests: requests}, id); }
    catch (_) { throw new Error('PQM SANDBOX APPEND: write outcome unknown; new Preview required.'); }
    pqmSandboxAppendVerify_(id, loaded.selected, loaded.tabs);
    pqmSandboxAppendVerifyMetadata_(id, loaded.selected, templates);
    return {selected: loaded.selected.length, verified: loaded.selected.length,
      google_writes: loaded.selected.length, status: 'COMPLETE'};
  } finally { lock.releaseLock(); }
}
