// Dedicated bounded append stage. Uses the same canonical planner as Full Preview.
var PQM_SANDBOX_APPEND_MAX_ROWS = 50;
var PQM_SANDBOX_APPEND_CONFIRMATION = 'APPLY_SANDBOX_SUPPLIER_APPEND_MAX_50';

function pqmSandboxAppendLoad_(id) {
  var body = pqmSandboxFetchRegistry_(), tabs = pqmGoogleSnapshot_(id);
  var plan = pqmGooglePlan_(body, tabs);
  pqmGoogleValidateWriteSet_(plan.changes);
  var selected = plan.changes.filter(function(change) { return change.append; })
    .slice(0, PQM_SANDBOX_APPEND_MAX_ROWS);
  var state = pqmSandboxFullState_(body, tabs, plan);
  var digest = pqmSandboxControlledDigest_({version: 1, spreadsheet_id: id,
    state: state, selected: selected});
  return {tabs: tabs, plan: plan, selected: selected, digest: digest,
    payload_digest: pqmSandboxAppendPayloadDigest_(body)};
}

function pqmSandboxAppendPayloadDigest_(body) {
  if (!body || body.count !== body.items.length) throw new Error('PQM SANDBOX APPEND: incomplete PQM source.');
  return pqmSandboxControlledDigest_(body.items.slice().sort(function(a, b) {
    return String(a.supplier_code).localeCompare(String(b.supplier_code));
  }));
}

function pqmSandboxAppendGroups_(selected) {
  return PQM_GOOGLE_TABS.map(function(name) {
    var rows = selected.filter(function(change) { return change.tab === name; });
    return rows.length ? {name: name, rows: rows, first: rows[0].row,
      last: rows[rows.length - 1].row} : null;
  }).filter(Boolean);
}

function pqmSandboxAppendDimensions_(id, tabs) {
  var response = Sheets.Spreadsheets.get(id, {includeGridData: false,
    fields: 'sheets(properties(title,sheetId,gridProperties(rowCount)))'});
  var actual = new Map((response.sheets || []).map(function(sheet) {
    return [sheet.properties.title, sheet.properties];
  }));
  PQM_GOOGLE_TABS.forEach(function(name) {
    var sheet = actual.get(name);
    if (!sheet || sheet.sheetId !== tabs[name].id ||
        sheet.gridProperties.rowCount !== tabs[name].maxRows) {
      throw new Error('PQM SANDBOX APPEND: Sheet dimensions changed; zero writes.');
    }
  });
}

function pqmSandboxAppendPrewriteGuard_(id, loaded) {
  if (pqmSandboxAppendPayloadDigest_(pqmSandboxFetchRegistry_()) !== loaded.payload_digest) {
    throw new Error('PQM SANDBOX APPEND: PQM source changed; zero writes.');
  }
  pqmSandboxAppendDimensions_(id, loaded.tabs);
  var groups = pqmSandboxAppendGroups_(loaded.selected), ranges = [];
  groups.forEach(function(group) {
    var last = Math.min(group.last, loaded.tabs[group.name].maxRows);
    if (group.first <= last) ranges.push("'" + group.name.replace(/'/g, "''") +
      "'!A" + group.first + ':O' + last);
  });
  if (!ranges.length) return;
  var result = Sheets.Spreadsheets.Values.batchGet(id, {ranges: ranges,
    valueRenderOption: 'FORMULA'});
  if (!result || !Array.isArray(result.valueRanges) || result.valueRanges.length !== ranges.length) {
    throw new Error('PQM SANDBOX APPEND: target-row guard incomplete; zero writes.');
  }
  result.valueRanges.forEach(function(range) {
    if ((range.values || []).some(function(row) {
      return row.some(function(value) { return !pqmGoogleBlank_(value); });
    })) throw new Error('PQM SANDBOX APPEND: destination row changed; zero writes.');
  });
}

function pqmSandboxAppendPreview() {
  var id = pqmSandboxControlledSpreadsheetId_(), loaded = pqmSandboxAppendLoad_(id);
  var output = {dry_run: true, google_writes: 0, selected: loaded.selected.length,
    remaining: loaded.plan.counts.appended - loaded.selected.length,
    append_digest: loaded.digest, blocked: 0, ambiguous: loaded.plan.counts.conflicts,
    duplicate_keys: loaded.plan.counts.duplicate_keys, errors: loaded.plan.counts.errors};
  console.log(JSON.stringify(output));
  return output;
}

function pqmSandboxAppendRange_(id, row, column, height, width) {
  return {sheetId: id, startRowIndex: row - 1, endRowIndex: row - 1 + height,
    startColumnIndex: column, endColumnIndex: column + width};
}

function pqmSandboxAppendRequests_(selected, tabs) {
  pqmGoogleValidateWriteSet_(selected);
  var requests = [], allowed = [1, 2, 3, 4, 5, 7, 8, 11];
  PQM_GOOGLE_TABS.forEach(function(name) {
    var tab = tabs[name], additions = selected.filter(function(change) { return change.tab === name; });
    if (!additions.length) return;
    var first = additions[0].row, last = additions[additions.length - 1].row;
    var template = tab.rows.length + 1;
    if (first !== template + 1 || additions.some(function(change, index) {
      return change.row !== first + index || !change.append ||
        Object.keys(change.cells).some(function(column) { return allowed.indexOf(Number(column)) < 0; });
    })) throw new Error('PQM SANDBOX APPEND: noncontiguous or unsafe plan; zero writes.');
    if (last > tab.maxRows) requests.push({appendDimension: {sheetId: tab.id,
      dimension: 'ROWS', length: last - tab.maxRows}});
    ['PASTE_FORMAT', 'PASTE_DATA_VALIDATION'].forEach(function(type) {
      allowed.forEach(function(column) {
        requests.push({copyPaste: {source: pqmSandboxAppendRange_(tab.id, template, column, 1, 1),
          destination: pqmSandboxAppendRange_(tab.id, first, column, additions.length, 1), pasteType: type}});
      });
    });
    requests.push({updateDimensionProperties: {range: {sheetId: tab.id, dimension: 'ROWS',
      startIndex: first - 1, endIndex: last}, properties: {pixelSize: tab.templateRowHeight}, fields: 'pixelSize'}});
    tab.conditionalFormats.forEach(function(rule, index) {
      if (!(rule.ranges || []).every(function(range) {
        var start = range.startColumnIndex || 0, end = range.endColumnIndex === undefined ? 15 : range.endColumnIndex;
        for (var column = start; column < end; column++) if (allowed.indexOf(column) < 0) return false;
        return true;
      })) return;
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
        requests.push({updateCells: {range: pqmSandboxAppendRange_(tab.id, change.row, column, 1, 1),
          rows: [{values: [cell]}], fields: 'userEnteredValue' +
            (isDate || column === 1 ? ',userEnteredFormat.numberFormat' : '')}});
      });
    });
  });
  pqmSandboxAppendValidateRequests_(requests);
  return requests;
}

function pqmSandboxAppendValidateRequests_(requests) {
  var allowed = PQM_GOOGLE_WRITE_ALLOWLIST;
  function checkRange(range) {
    if (!range || !Number.isInteger(range.startColumnIndex) ||
        !Number.isInteger(range.endColumnIndex)) throw new Error('PQM SANDBOX APPEND: unbounded column write; zero writes.');
    for (var column = range.startColumnIndex; column < range.endColumnIndex; column++) {
      if (allowed.indexOf(column) < 0) throw new Error('PQM SANDBOX APPEND: forbidden column metadata write; zero writes.');
    }
  }
  requests.forEach(function(request) {
    if (request.copyPaste) {
      checkRange(request.copyPaste.source); checkRange(request.copyPaste.destination);
    } else if (request.updateCells) checkRange(request.updateCells.range);
    else if (request.updateConditionalFormatRule) {
      (request.updateConditionalFormatRule.rule.ranges || []).forEach(checkRange);
    } else if (request.appendDimension) {
      if (request.appendDimension.dimension !== 'ROWS') throw new Error('PQM SANDBOX APPEND: forbidden dimension write; zero writes.');
    } else if (request.updateDimensionProperties) {
      if (request.updateDimensionProperties.range.dimension !== 'ROWS' ||
          request.updateDimensionProperties.fields !== 'pixelSize') {
        throw new Error('PQM SANDBOX APPEND: forbidden dimension metadata write; zero writes.');
      }
    } else {
      throw new Error('PQM SANDBOX APPEND: unknown request; zero writes.');
    }
  });
}

function pqmSandboxAppendReadMetadata_(id, groups) {
  var ranges = groups.map(function(group) {
    return "'" + group.name.replace(/'/g, "''") + "'!A" + group.first + ':O' + group.last;
  });
  var response = Sheets.Spreadsheets.get(id, {ranges: ranges, includeGridData: true,
    fields: 'sheets(properties(title,sheetId),data(startRow,startColumn,rowData(values(userEnteredFormat,dataValidation)),rowMetadata(pixelSize)))'});
  var result = {};
  groups.forEach(function(group) {
    var sheet = (response.sheets || []).find(function(entry) {
      return entry.properties && entry.properties.title === group.name;
    });
    var data = (sheet && sheet.data || []).find(function(entry) {
      return entry.startRow === group.first - 1 && (entry.startColumn || 0) === 0;
    });
    var rowData = data && data.rowData || [], heights = data && data.rowMetadata || [];
    if (rowData.length !== group.last - group.first + 1 || heights.length !== rowData.length) {
      throw new Error('PQM SANDBOX APPEND: batch metadata incomplete; no write/retry.');
    }
    result[group.name] = rowData.map(function(row, index) {
      var cells = row.values || [], height = heights[index].pixelSize;
      if (cells.length !== 15 || !Number.isInteger(height) || height <= 0) {
        throw new Error('PQM SANDBOX APPEND: row metadata unavailable; no write/retry.');
      }
      return {cells: cells, height: height};
    });
  });
  return result;
}

function pqmSandboxAppendCanonicalMetadata_(value) {
  if (Array.isArray(value)) return value.map(pqmSandboxAppendCanonicalMetadata_);
  if (value && typeof value === 'object') {
    var result = {};
    Object.keys(value).sort().forEach(function(key) {
      result[key] = pqmSandboxAppendCanonicalMetadata_(value[key]);
    });
    return result;
  }
  return value;
}

function pqmSandboxAppendVerifyMetadata_(id, selected, templates) {
  var groups = pqmSandboxAppendGroups_(selected);
  var afterByTab = pqmSandboxAppendReadMetadata_(id, groups);
  groups.forEach(function(group) { group.rows.forEach(function(change) {
    var template = templates[change.tab];
    var after = afterByTab[change.tab][change.row - group.first];
    if (after.height !== template.height) throw new Error('PQM SANDBOX APPEND: row height mismatch.');
    PQM_GOOGLE_WRITE_ALLOWLIST.forEach(function(column) {
      var expected = template.cells[column] || {}, actual = after.cells[column] || {};
      if (JSON.stringify(pqmSandboxAppendCanonicalMetadata_(expected.dataValidation || null)) !==
          JSON.stringify(pqmSandboxAppendCanonicalMetadata_(actual.dataValidation || null))) {
        throw new Error('PQM SANDBOX APPEND: validation mismatch.');
      }
      var expectedFormat = JSON.parse(JSON.stringify(expected.userEnteredFormat || {}));
      var actualFormat = JSON.parse(JSON.stringify(actual.userEnteredFormat || {}));
      if ([1, 7, 8].indexOf(column) >= 0 && Object.prototype.hasOwnProperty.call(change.cells, column)) {
        delete expectedFormat.numberFormat;
        if (!actualFormat.numberFormat || actualFormat.numberFormat.type !==
            (column === 1 ? 'TEXT' : 'DATE') || actualFormat.numberFormat.pattern !==
            (column === 1 ? '@' : 'dd.MM.yyyy')) throw new Error('PQM SANDBOX APPEND: date/code format mismatch.');
        delete actualFormat.numberFormat;
      }
      if (JSON.stringify(pqmSandboxAppendCanonicalMetadata_(expectedFormat)) !==
          JSON.stringify(pqmSandboxAppendCanonicalMetadata_(actualFormat))) {
        throw new Error('PQM SANDBOX APPEND: format mismatch.');
      }
    });
  }); });
}

function pqmSandboxAppendVerify_(id, selected, before) {
  var groups = pqmSandboxAppendGroups_(selected);
  var rawRanges = groups.map(function(group) {
    return "'" + group.name.replace(/'/g, "''") + "'!A" + group.first + ':O' + group.last;
  });
  var codeRanges = groups.map(function(group) {
    return "'" + group.name.replace(/'/g, "''") + "'!B" + group.first + ':B' + group.last;
  });
  var raw = Sheets.Spreadsheets.Values.batchGet(id, {ranges: rawRanges,
    valueRenderOption: 'UNFORMATTED_VALUE'});
  var codes = Sheets.Spreadsheets.Values.batchGet(id, {ranges: codeRanges,
    valueRenderOption: 'FORMATTED_VALUE'});
  if (!raw || !codes || !Array.isArray(raw.valueRanges) ||
      !Array.isArray(codes.valueRanges) || raw.valueRanges.length !== groups.length ||
      codes.valueRanges.length !== groups.length) {
    throw new Error('PQM SANDBOX APPEND: AFTER batch read incomplete; new Preview required.');
  }
  groups.forEach(function(group, index) {
    var rows = raw.valueRanges[index].values || [], displayed = codes.valueRanges[index].values || [];
    group.rows.forEach(function(change) {
      var offset = change.row - group.first, row = rows[offset] || [];
      if (String((displayed[offset] || [])[0] || '').trim() !== String(change.cells[1]).trim() ||
          [0, 6, 9, 10, 12, 13, 14].some(function(column) { return !pqmGoogleBlank_(row[column]); })) {
        throw new Error('PQM SANDBOX APPEND: AFTER identity or forbidden-column mismatch; new Preview required.');
      }
      Object.keys(change.cells).forEach(function(column) {
        var actual = row[column], expected = change.cells[column];
        if (Number(column) === 7 || Number(column) === 8) {
          if (pqmGoogleCalendarDate_(actual).value !== pqmGoogleCalendarDate_(expected).value)
            throw new Error('PQM SANDBOX APPEND: AFTER date mismatch; new Preview required.');
        } else if (String(actual) !== String(expected)) {
          throw new Error('PQM SANDBOX APPEND: AFTER value mismatch; new Preview required.');
        }
      });
    });
  });
  var after = {};
  PQM_GOOGLE_TABS.forEach(function(name) {
    var last = groups.filter(function(group) { return group.name === name; })
      .reduce(function(max, group) { return Math.max(max, group.last); }, before[name].maxRows);
    after[name] = {id: before[name].id, maxRows: last};
  });
  pqmSandboxAppendDimensions_(id, after);
}

function pqmSandboxAppendApply() {
  var ui = SpreadsheetApp.getUi();
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
    var id = pqmSandboxControlledSpreadsheetId_(), loaded = pqmSandboxAppendLoad_(id);
    if (!loaded.selected.length || loaded.digest !== digest) {
      throw new Error('PQM SANDBOX APPEND: stale or empty selection; zero writes.');
    }
    // Keep the one initial snapshot. Re-read only the PQM payload and selected
    // destination rows; never materialize another full Google grid in Apply.
    delete loaded.plan;
    pqmSandboxAppendPrewriteGuard_(id, loaded);
    var templateGroups = pqmSandboxAppendGroups_(loaded.selected).map(function(group) {
      var row = loaded.tabs[group.name].rows.length + 1;
      return {name: group.name, first: row, last: row};
    });
    var templateRows = pqmSandboxAppendReadMetadata_(id, templateGroups), templates = {};
    templateGroups.forEach(function(group) { templates[group.name] = templateRows[group.name][0]; });
    var requests = pqmSandboxAppendRequests_(loaded.selected, loaded.tabs);
    if (!requests.length) throw new Error('PQM SANDBOX APPEND: empty request; zero writes.');
    try { Sheets.Spreadsheets.batchUpdate({requests: requests}, id); }
    catch (_) { throw new Error('PQM SANDBOX APPEND: write outcome unknown; new Preview required.'); }
    pqmSandboxAppendVerify_(id, loaded.selected, loaded.tabs);
    pqmSandboxAppendVerifyMetadata_(id, loaded.selected, templates);
    return {selected: loaded.selected.length, verified: loaded.selected.length,
      google_writes: loaded.selected.length, status: 'COMPLETE'};
  } finally { lock.releaseLock(); }
}
