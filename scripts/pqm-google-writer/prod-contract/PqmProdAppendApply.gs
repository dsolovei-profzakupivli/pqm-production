// Dedicated bounded append stage. Uses the same canonical planner as Full Preview.
var PQM_PROD_APPEND_MAX_ROWS = 50;
var PQM_PROD_APPEND_CONFIRMATION = 'APPLY_PROD_SUPPLIER_APPEND_MAX_50';

function pqmProdAppendLoad_(id) {
  var body = pqmProdFetchRegistry_(), tabs = pqmGoogleSnapshot_(id);
  var plan = pqmGooglePlan_(body, tabs, {appendOnly: true});
  if (plan.counts.conflicts || plan.counts.duplicate_keys || plan.counts.errors) {
    throw new Error('PQM PROD APPEND: planner blocked; zero writes.');
  }
  var selected = plan.changes.filter(function(change) { return change.append; })
    .slice(0, PQM_PROD_APPEND_MAX_ROWS);
  var state = pqmProdFullState_(body, tabs, plan);
  var digest = pqmProdControlledDigest_({version: 1, spreadsheet_id: id,
    state: state, selected: selected});
  return {body: body, tabs: tabs, plan: plan, selected: selected, digest: digest};
}

function pqmProdAppendPreview() {
  var id = pqmProdControlledSpreadsheetId_(), loaded = pqmProdAppendLoad_(id);
  var output = {dry_run: true, google_writes: 0, selected: loaded.selected.length,
    remaining: loaded.plan.counts.appended - loaded.selected.length,
    append_digest: loaded.digest, blocked: 0, ambiguous: 0};
  console.log(JSON.stringify(output));
  return output;
}

function pqmProdAppendRange_(id, row, column, height, width) {
  return {sheetId: id, startRowIndex: row - 1, endRowIndex: row - 1 + height,
    startColumnIndex: column, endColumnIndex: column + width};
}

function pqmProdAppendRequests_(selected, tabs) {
  var requests = [], allowed = [1, 2, 3, 5, 7, 8, 11];
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
      // E is frozen, including template formatting and validation writes.
      [[0, 4], [5, 10]].forEach(function(span) {
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
        if (isDate) cell.userEnteredFormat = {numberFormat: {type: 'DATE', pattern: 'dd.MM.yyyy'}};
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
      if (column === 4) continue; // E does not inherit the template; its value is checked separately.
      var expected = template.cells[column] || {}, actual = after.cells[column] || {};
      if (JSON.stringify(expected.dataValidation || null) !== JSON.stringify(actual.dataValidation || null)) {
        throw new Error('PQM PROD APPEND: validation mismatch.');
      }
      var expectedFormat = JSON.parse(JSON.stringify(expected.userEnteredFormat || {}));
      var actualFormat = JSON.parse(JSON.stringify(actual.userEnteredFormat || {}));
      if ([1, 7, 8].indexOf(column) >= 0 && Object.prototype.hasOwnProperty.call(change.cells, column)) {
        delete expectedFormat.numberFormat;
        if (!actualFormat.numberFormat || actualFormat.numberFormat.pattern !==
            (column === 1 ? '@' : 'dd.MM.yyyy')) throw new Error('PQM PROD APPEND: date/code format mismatch.');
        delete actualFormat.numberFormat;
      }
      if (JSON.stringify(expectedFormat) !== JSON.stringify(actualFormat)) {
        throw new Error('PQM PROD APPEND: format mismatch.');
      }
    }
  });
}

function pqmProdAppendVerify_(id, selected, before) {
  var after = pqmGoogleSnapshot_(id);
  selected.forEach(function(change) {
    var oldTab = before[change.tab], newTab = after[change.tab], row = newTab && newTab.rows[change.row - 2];
    if (!row || String(row.codeDisplay || '').trim() !== change.cells[1] ||
        row.formulas[0] !== pqmGoogleTranslatedAppendFormula_(
          oldTab.rows[oldTab.rows.length - 1].formulas[0], oldTab.rows.length + 1, change.row) ||
        oldTab.rows.length >= newTab.rows.length ||
        [6, 9, 10, 12].some(function(column) { return !pqmGoogleBlank_(row.values[column]); })) {
      throw new Error('PQM PROD APPEND: AFTER verification failed; new Preview required.');
    }
    Object.keys(change.cells).forEach(function(column) {
      var actual = row.values[column], expected = change.cells[column];
      if (Number(column) === 7 || Number(column) === 8) {
        if (pqmGoogleCalendarDate_(actual).value !== pqmGoogleCalendarDate_(expected).value)
          throw new Error('PQM PROD APPEND: AFTER date mismatch; new Preview required.');
      } else if (String(actual) !== String(expected)) {
        throw new Error('PQM PROD APPEND: AFTER value mismatch; new Preview required.');
      }
    });
  });
  return after;
}

function pqmProdAppendApply() {
  var ui = SpreadsheetApp.getUi();
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
    var id = pqmProdControlledSpreadsheetId_(), loaded = pqmProdAppendLoad_(id);
    if (!loaded.selected.length || loaded.digest !== digest) {
      throw new Error('PQM PROD APPEND: stale or empty selection; zero writes.');
    }
    // Re-read the full Sheet before mutation; a moved row or new identity invalidates the digest.
    var rechecked = pqmProdAppendLoad_(id);
    if (rechecked.digest !== digest) throw new Error('PQM PROD APPEND: source changed; zero writes.');
    var templates = {};
    loaded.selected.forEach(function(change) {
      if (!templates[change.tab]) templates[change.tab] = pqmProdAppendRowMetadata_(id,
        change.tab, loaded.tabs[change.tab].rows.length + 1);
    });
    var requests = pqmProdAppendRequests_(loaded.selected, loaded.tabs);
    if (!requests.length) throw new Error('PQM PROD APPEND: empty request; zero writes.');
    try { Sheets.Spreadsheets.batchUpdate({requests: requests}, id); }
    catch (_) { throw new Error('PQM PROD APPEND: write outcome unknown; new Preview required.'); }
    pqmProdAppendVerify_(id, loaded.selected, loaded.tabs);
    pqmProdAppendVerifyMetadata_(id, loaded.selected, templates);
    return {selected: loaded.selected.length, verified: loaded.selected.length,
      google_writes: loaded.selected.length, status: 'COMPLETE'};
  } finally { lock.releaseLock(); }
}
