// Dedicated bounded append stage. Uses the same canonical planner as Full Preview.
var PQM_PROD_APPEND_MAX_ROWS = 50;
var PQM_PROD_APPEND_CODE_SCAN_ROWS = 1000;
var PQM_PROD_APPEND_CONFIRMATION = 'APPLY_PROD_SUPPLIER_APPEND_MAX_50';

function pqmProdAppendLoad_(id, allowlist) {
  var body = pqmProdFetchRegistry_(), tabs = pqmGoogleSnapshot_(id);
  var plan = pqmGooglePlan_(body, tabs);
  var candidates = plan.changes.filter(function(change) { return change.append; });
  if (allowlist !== undefined) {
    if (!Array.isArray(allowlist) || !allowlist.length ||
        allowlist.length > PQM_PROD_APPEND_MAX_ROWS || new Set(allowlist).size !== allowlist.length) {
      throw new Error('PQM PROD APPEND: invalid supplier allowlist.');
    }
    var byCode = {};
    candidates.forEach(function(change) { byCode[String(change.cells[1]).trim()] = change; });
    candidates = allowlist.map(function(code) {
      if (!byCode[code]) throw new Error('PQM PROD APPEND: allowlisted supplier has no safe APPEND.');
      return byCode[code];
    });
  }
  var selected = candidates.slice(0, PQM_PROD_APPEND_MAX_ROWS);
  var next = {};
  PQM_GOOGLE_TABS.forEach(function(name) { next[name] = tabs[name].rows.length + 2; });
  selected = selected.map(function(change) {
    return {tab: change.tab, row: next[change.tab]++, append: true, cells: change.cells};
  });
  var state = pqmProdFullState_(body, tabs, plan);
  var digest = pqmProdControlledDigest_({version: 1, spreadsheet_id: id,
    state: state, selected: selected});
  return {body: body, tabs: tabs, plan: plan, selected: selected, digest: digest,
    payload_digest: state.payload_digest};
}

function pqmProdAppendPayloadDigest_(body) {
  return pqmProdControlledDigest_(body.items.map(pqmProdControlledPqmState_).sort(function(a, b) {
    return a.supplier_code < b.supplier_code ? -1 : a.supplier_code > b.supplier_code ? 1 : 0;
  }));
}

/* Scan only displayed B values, in bounded chunks; never retain another full Sheet snapshot. */
function pqmProdAppendCodeCounts_(id, tabs, selected) {
  var counts = new Map(selected.map(function(change) { return [String(change.cells[1]).trim(), 0]; }));
  PQM_GOOGLE_TABS.forEach(function(name) {
    var tab = tabs[name], esc = "'" + name.replace(/'/g, "''") + "'";
    for (var first = 2; first <= tab.maxRows; first += PQM_PROD_APPEND_CODE_SCAN_ROWS) {
      var last = Math.min(tab.maxRows, first + PQM_PROD_APPEND_CODE_SCAN_ROWS - 1);
      var response = Sheets.Spreadsheets.Values.batchGet(id, {
        ranges: [esc + '!B' + first + ':B' + last], valueRenderOption: 'FORMATTED_VALUE'
      });
      if (!response || !Array.isArray(response.valueRanges) || response.valueRanges.length !== 1) {
        throw new Error('PQM PROD APPEND: identity scan incomplete; no write/retry.');
      }
      (response.valueRanges[0].values || []).forEach(function(row) {
        var code = String((row || [])[0] || '').trim();
        if (counts.has(code)) counts.set(code, counts.get(code) + 1);
      });
    }
  });
  return counts;
}

function pqmProdAppendGridCounts_(id, tabs) {
  var response = Sheets.Spreadsheets.get(id, {includeGridData: false,
    fields: 'sheets(properties(title,sheetId,gridProperties(rowCount)))'});
  var actual = new Map((response.sheets || []).map(function(sheet) {
    return [sheet.properties.title, sheet.properties];
  }));
  PQM_GOOGLE_TABS.forEach(function(name) {
    var property = actual.get(name);
    if (!property || property.sheetId !== tabs[name].id ||
        property.gridProperties.rowCount !== tabs[name].maxRows) {
      throw new Error('PQM PROD APPEND: Sheet dimensions changed; no write/retry.');
    }
  });
}

function pqmProdAppendPrewriteGuard_(id, loaded) {
  var freshBody = pqmProdFetchRegistry_();
  if (freshBody.count !== freshBody.items.length ||
      pqmProdAppendPayloadDigest_(freshBody) !== loaded.payload_digest) {
    throw new Error('PQM PROD APPEND: PQM source changed; zero writes.');
  }
  pqmProdAppendGridCounts_(id, loaded.tabs);
  var counts = pqmProdAppendCodeCounts_(id, loaded.tabs, loaded.selected);
  counts.forEach(function(count) {
    if (count !== 0) throw new Error('PQM PROD APPEND: selected identity already exists; zero writes.');
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
    throw new Error('PQM PROD APPEND: target-row guard incomplete; zero writes.');
  }
  response.valueRanges.forEach(function(range) {
    if ((range.values || []).some(function(row) { return row.some(function(value) { return !pqmGoogleBlank_(value); }); })) {
      throw new Error('PQM PROD APPEND: destination row changed; zero writes.');
    }
  });
}

function pqmProdAppendPreview(allowlist) {
  var id = pqmProdControlledSpreadsheetId_(), loaded = pqmProdAppendLoad_(id, allowlist);
  var output = {dry_run: true, google_writes: 0, selected: loaded.selected.length,
    selected_codes: loaded.selected.map(function(change) { return change.cells[1]; }),
    remaining: loaded.plan.counts.appended - loaded.selected.length,
    conflicts: loaded.plan.counts.conflicts, append_digest: loaded.digest, blocked: 0};
  console.log(JSON.stringify(output));
  return output;
}

function pqmProdAppendAllowlistPreview() {
  var ui = SpreadsheetApp.getUi();
  var answer = ui.prompt('PQM PROD append Preview',
    'Paste 1–50 exact supplier codes, separated by commas.', ui.ButtonSet.OK_CANCEL);
  if (answer.getSelectedButton() !== ui.Button.OK) return {cancelled: true, google_writes: 0};
  var codes = answer.getResponseText().split(/[,\n]/).map(function(code) { return code.trim(); }).filter(Boolean);
  return pqmProdAppendPreview(codes);
}

function pqmProdAppendRange_(id, row, column, height, width) {
  return {sheetId: id, startRowIndex: row - 1, endRowIndex: row - 1 + height,
    startColumnIndex: column, endColumnIndex: column + width};
}

function pqmProdAppendRequests_(selected, tabs) {
  var requests = [], allowed = [1, 2, 3, 4, 5, 7, 8, 11];
  PQM_GOOGLE_TABS.forEach(function(name) {
    var tab = tabs[name], additions = selected.filter(function(change) { return change.tab === name; });
    if (!additions.length) return;
    var first = additions[0].row, last = additions[additions.length - 1].row;
    var template = tab.rows.length + 1;
    if (!pqmGoogleSafeAppendFormula_(tab.rows[tab.rows.length - 1].formulas[0], template)) {
      throw new Error('PQM PROD APPEND: unsafe formula A; zero writes.');
    }
    if (first !== template + 1 || additions.some(function(change, index) {
      return change.row !== first + index || !change.append ||
        Object.keys(change.cells).some(function(column) { return allowed.indexOf(Number(column)) < 0; });
    })) throw new Error('PQM PROD APPEND: noncontiguous or unsafe plan; zero writes.');
    if (last > tab.maxRows) requests.push({appendDimension: {sheetId: tab.id,
      dimension: 'ROWS', length: last - tab.maxRows}});
    ['PASTE_FORMAT', 'PASTE_DATA_VALIDATION'].forEach(function(type) {
      // Copy formatting/validation only, never template manual values.
      [[0, 15]].forEach(function(span) {
        requests.push({copyPaste: {source: pqmProdAppendRange_(tab.id, template, span[0], 1, span[1]),
          destination: pqmProdAppendRange_(tab.id, first, span[0], additions.length, span[1]), pasteType: type}});
      });
    });
    requests.push({copyPaste: {source: pqmProdAppendRange_(tab.id, template, 0, 1, 1),
      destination: pqmProdAppendRange_(tab.id, first, 0, additions.length, 1),
      pasteType: 'PASTE_FORMULA'}});
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
      allowed.forEach(function(column) {
        if (!Object.prototype.hasOwnProperty.call(change.cells, column)) return;
        var value = change.cells[column], isDate = column === 7 || column === 8;
        var cell = {userEnteredValue: isDate ? {numberValue: value} : {stringValue: value}};
        if (isDate) cell.userEnteredFormat = {numberFormat: {type: column === 8 ? 'DATE_TIME' : 'DATE', pattern: column === 8 ? 'dd.MM.yyyy HH:mm:ss' : 'dd.MM.yyyy'}};
        if (column === 1) cell.userEnteredFormat = {numberFormat: {type: 'TEXT', pattern: '@'}};
        requests.push({updateCells: {range: pqmProdAppendRange_(tab.id, change.row, column, 1, 1),
          rows: [{values: [cell]}], fields: 'userEnteredValue' +
            (isDate || column === 1 ? ',userEnteredFormat.numberFormat' : '')}});
      });
    });
  });
  return requests;
}

function pqmProdAppendRowMetadata_(id, tab, row) {
  var range = "'" + tab.replace(/'/g, "''") + "'!A" + row + ':O' + row;
  var response = Sheets.Spreadsheets.get(id, {ranges: [range], includeGridData: true,
    fields: 'sheets(data(rowData(values(userEnteredFormat,dataValidation)),rowMetadata(pixelSize)))'});
  var data = (((response.sheets || [])[0] || {}).data || [])[0] || {};
  var cells = (((data.rowData || [])[0] || {}).values || []);
  var height = (((data.rowMetadata || [])[0] || {}).pixelSize);
  if (cells.length !== 15 || !Number.isInteger(height) || height <= 0) {
    throw new Error('PQM PROD APPEND: row metadata unavailable; zero writes.');
  }
  return {cells: cells, height: height};
}

function pqmProdAppendVerifyMetadata_(id, selected, templates) {
  selected.forEach(function(change) {
    var template = templates[change.tab];
    var after = pqmProdAppendRowMetadata_(id, change.tab, change.row);
    if (after.height !== template.height) throw new Error('PQM PROD APPEND: row height mismatch.');
    for (var column = 0; column < 15; column++) {
      var expected = template.cells[column] || {}, actual = after.cells[column] || {};
      if (JSON.stringify(expected.dataValidation || null) !== JSON.stringify(actual.dataValidation || null)) {
        throw new Error('PQM PROD APPEND: validation mismatch.');
      }
      var expectedFormat = JSON.parse(JSON.stringify(expected.userEnteredFormat || {}));
      var actualFormat = JSON.parse(JSON.stringify(actual.userEnteredFormat || {}));
      if ([1, 7, 8].indexOf(column) >= 0 && Object.prototype.hasOwnProperty.call(change.cells, column)) {
        delete expectedFormat.numberFormat;
        if (!actualFormat.numberFormat || actualFormat.numberFormat.pattern !==
            (column === 1 ? '@' : column === 8 ? 'dd.MM.yyyy HH:mm:ss' : 'dd.MM.yyyy')) throw new Error('PQM PROD APPEND: date/code format mismatch.');
        delete actualFormat.numberFormat;
      }
      if (JSON.stringify(expectedFormat) !== JSON.stringify(actualFormat)) {
        throw new Error('PQM PROD APPEND: format mismatch.');
      }
    }
  });
}

function pqmProdAppendVerify_(id, selected, before) {
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
    throw new Error('PQM PROD APPEND: AFTER read-back incomplete; new Preview required.');
  }
  var formulaResponse = Sheets.Spreadsheets.Values.batchGet(id, {ranges: rawRanges, valueRenderOption: 'FORMULA'});
  if (!formulaResponse || !Array.isArray(formulaResponse.valueRanges) || formulaResponse.valueRanges.length !== rawRanges.length) {
    throw new Error('PQM PROD APPEND: formula read-back incomplete; new Preview required.');
  }
  groups.forEach(function(group, index) {
    var raw = rawResponse.valueRanges[index].values || [];
    var codes = codeResponse.valueRanges[index].values || [];
    group.additions.forEach(function(change) {
      var offset = change.row - group.first, row = raw[offset] || [];
      var formulas = (formulaResponse.valueRanges[index].values || [])[offset] || [];
      var template = before[group.name].rows.length + 1;
      var expectedA = pqmGoogleTranslatedAppendFormula_(before[group.name].rows[before[group.name].rows.length-1].formulas[0], template, change.row);
      if (formulas[0] !== expectedA) throw new Error('PQM PROD APPEND: formula A mismatch; new Preview required.');
      if (String((codes[offset] || [])[0] || '').trim() !== String(change.cells[1]).trim() ||
          [6, 9, 10, 12, 13, 14].some(function(column) { return !pqmGoogleBlank_(row[column]); })) {
        throw new Error('PQM PROD APPEND: AFTER verification failed; new Preview required.');
      }
      Object.keys(change.cells).forEach(function(column) {
        var actual = row[column], expected = change.cells[column];
        if (Number(column) === 7 || Number(column) === 8) {
          var matches = Number(column) === 8 ?
            pqmVerificationDatetime_(actual).kind === 'datetime' &&
              pqmVerificationDatetime_(actual).value === pqmVerificationDatetime_(expected).value :
            pqmGoogleCalendarDate_(actual).value === pqmGoogleCalendarDate_(expected).value;
          if (!matches) {
            throw new Error('PQM PROD APPEND: AFTER date mismatch; new Preview required.');
          }
        } else if (String(actual) !== String(expected)) {
          throw new Error('PQM PROD APPEND: AFTER value mismatch; new Preview required.');
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
  pqmProdAppendGridCounts_(id, afterTabs);
}

function pqmProdAppendApply() {
  pqmMirrorContext_();
  var ui = SpreadsheetApp.getUi();
  var codesAnswer = ui.prompt('PQM PROD append',
    'Optional: paste exact supplier codes from allowlist Preview, or leave blank for the first safe batch.',
    ui.ButtonSet.OK_CANCEL);
  if (codesAnswer.getSelectedButton() !== ui.Button.OK) return {cancelled: true, google_writes: 0};
  var codes = codesAnswer.getResponseText().split(/[,\n]/).map(function(code) { return code.trim(); }).filter(Boolean);
  var digestAnswer = ui.prompt('PQM PROD append', 'Paste append_digest from fresh Preview.',
    ui.ButtonSet.OK_CANCEL);
  if (digestAnswer.getSelectedButton() !== ui.Button.OK) return {cancelled: true, google_writes: 0};
  var digest = digestAnswer.getResponseText().trim();
  var confirmAnswer = ui.prompt('PQM PROD append', 'Type ' + PQM_PROD_APPEND_CONFIRMATION,
    ui.ButtonSet.OK_CANCEL);
  if (confirmAnswer.getSelectedButton() !== ui.Button.OK ||
      confirmAnswer.getResponseText().trim() !== PQM_PROD_APPEND_CONFIRMATION || !digest) {
    throw new Error('PQM PROD APPEND: explicit confirmation and digest required; zero writes.');
  }
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(0)) throw new Error('PQM PROD APPEND: locked; zero writes.');
  try {
    var id = pqmProdControlledSpreadsheetId_(), loaded = pqmProdAppendLoad_(id, codes.length ? codes : undefined);
    if (!loaded.selected.length || loaded.digest !== digest) {
      throw new Error('PQM PROD APPEND: stale or empty selection; zero writes.');
    }
    // The initial full-state digest matches Preview; only selected identities,
    // destination rows and the PQM source need another read before mutation.
    delete loaded.body;
    delete loaded.plan;
    pqmProdAppendPrewriteGuard_(id, loaded);
    var templates = {};
    loaded.selected.forEach(function(change) {
      if (!templates[change.tab]) templates[change.tab] = pqmProdAppendRowMetadata_(id,
        change.tab, loaded.tabs[change.tab].rows.length + 1);
    });
    var requests = pqmProdAppendRequests_(loaded.selected, loaded.tabs);
    if (!requests.length) throw new Error('PQM PROD APPEND: empty request; zero writes.');
    try { pqmMirrorSheetsBatchUpdate_({requests: requests}, id); }
    catch (_) { throw new Error('PQM PROD APPEND: write outcome unknown; new Preview required.'); }
    pqmProdAppendVerify_(id, loaded.selected, loaded.tabs);
    pqmProdAppendVerifyMetadata_(id, loaded.selected, templates);
    return {selected: loaded.selected.length, verified: loaded.selected.length,
      google_writes: loaded.selected.length, status: 'COMPLETE'};
  } finally { lock.releaseLock(); }
}
