/** NEXT LOCAL. Requires the Apps Script advanced Google Sheets service (Sheets v4).
 * No onOpen/trigger: integrate pqmGooglePreview in the existing menu.
 * All spreadsheet mutations use one atomic batchUpdate, with literal typed values.
 */
var PQM_GOOGLE_HEADERS = [
  'Маркер актуальності', 'Код ЄДРПОУ', 'Найменування', 'ПІБ для перевірки',
  'Статус в реєстрі (ЄДР)', 'Статус (Prozorro)', 'Реквізити рішення про припинення',
  'Дата останньої заявки', 'Дата перевірки', 'Дата запису', 'Номер запису',
  'УО', 'Примітки', 'Повна назва з ЄДР', 'Скорочена назва з ЄДР'
];
var PQM_GOOGLE_TABS = ['ФОП', 'ЮО'];
var PQM_GOOGLE_OWNED = [0, 1, 2, 5, 7];

function pqmGoogleCounts_() {
  return {api_records: 0, matched: 0, appended: 0, updated: 0, unchanged: 0,
    skipped: 0, conflicts: 0, duplicate_keys: 0, errors: 0};
}

function pqmGoogleSchema_(body) {
  if (!body || !Array.isArray(body.items) || !Number.isInteger(body.count) ||
      body.count !== body.items.length) throw new Error('PQM: schema mismatch (count/items).');
  body.items.forEach(function(x) {
    if (!x || typeof x.supplier_code !== 'string' || !x.supplier_code.trim() ||
        ['individual_entrepreneur', 'legal_entity', 'foreign_legal_entity', 'unknown'].indexOf(x.entity_type) < 0 ||
        typeof x.monitoring_eligible !== 'boolean' ||
        ['supplier_name', 'prozorro_status_google', 'freshness_marker', 'last_application_date'].some(function(k) {
          return !Object.prototype.hasOwnProperty.call(x, k) || (x[k] !== null && typeof x[k] !== 'string');
        })) throw new Error('PQM: schema mismatch (item).');
  });
}

function pqmGoogleDate_(s) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return null;
  var parts = s.split('-').map(Number);
  if (parts[0] < 1900 || parts[0] > 9999) return null;
  var ms = Date.UTC(parts[0], parts[1] - 1, parts[2]);
  if (new Date(ms).toISOString().slice(0, 10) !== s) return null;
  return ms / 86400000 + 25569;
}

function pqmGoogleBlank_(v) { return v === null || v === undefined || (typeof v === 'string' && !v.trim()); }

/** Pure planner. Snapshots contain headers, rows (values/formulas), id and maxRows. */
function pqmGooglePlan_(body, tabs) {
  pqmGoogleSchema_(body);
  var result = pqmGoogleCounts_(), perTab = {}, issues = [], changes = [], index = new Map(), apiKeys = new Map();
  result.api_records = body.items.length;
  function issue(code, key, tab) { issues.push({reason: code, supplier_code: key, tab: tab || null}); }
  PQM_GOOGLE_TABS.forEach(function(name) {
    var t = tabs[name]; perTab[name] = pqmGoogleCounts_();
    if (!t || JSON.stringify(t.headers) !== JSON.stringify(PQM_GOOGLE_HEADERS))
      throw new Error('PQM: header mismatch: ' + name);
    t.rows.forEach(function(row, i) {
      var raw = row.values[1];
      // Display text keeps leading zeroes in legacy numeric cells. Never rewrite B.
      var key = String(row.codeDisplay === undefined ? (raw == null ? '' : raw) : row.codeDisplay).trim();
      if (!key) return;
      if (!index.has(key)) index.set(key, []);
      index.get(key).push({tab: name, row: i + 2, data: row});
    });
  });
  body.items.forEach(function(x) { var k = x.supplier_code.trim(); apiKeys.set(k, (apiKeys.get(k) || 0) + 1); });
  var duplicates = new Set();
  index.forEach(function(v, k) { if (v.length > 1) duplicates.add(k); });
  apiKeys.forEach(function(v, k) { if (v > 1) duplicates.add(k); });
  result.duplicate_keys = duplicates.size;
  duplicates.forEach(function(k) {
    issue('duplicate_key', k);
    PQM_GOOGLE_TABS.forEach(function(t) {
      if ((index.get(k) || []).some(function(r) { return r.tab === t; }) || body.items.some(function(x) {
        return x.supplier_code.trim() === k && (x.entity_type === 'legal_entity' ? 'ЮО' : x.entity_type === 'individual_entrepreneur' ? 'ФОП' : '') === t;
      })) perTab[t].duplicate_keys++;
    });
  });
  var gaps = [];
  PQM_GOOGLE_TABS.forEach(function(name) {
    var t = tabs[name], template = t.rows[t.rows.length - 1];
    if (template && template.formulas.some(Boolean)) gaps.push({tab: name,
      reason: 'append_formulas_not_audited_left_blank', row: t.rows.length + 1});
  });
  var nextRows = {};
  PQM_GOOGLE_TABS.forEach(function(t) { nextRows[t] = tabs[t].rows.length + 2; });
  body.items.forEach(function(x) {
    var key = x.supplier_code.trim();
    var name = x.entity_type === 'individual_entrepreneur' ? 'ФОП' : x.entity_type === 'legal_entity' ? 'ЮО' : null;
    function count(k) { result[k]++; if (name) perTab[name][k]++; }
    if (name) perTab[name].api_records++;
    if (duplicates.has(key)) { count('conflicts'); return; }
    if (!name) { count('skipped'); return; }
    var found = (index.get(key) || [])[0];
    if (found && found.tab !== name) { count('conflicts'); issue('routing_mismatch', key, name); return; }
    if (found) count('matched');
    if (found && tabs[name].merges.some(function(r) {
      return (r.startRowIndex || 0) <= found.row - 1 && r.endRowIndex >= found.row &&
        PQM_GOOGLE_OWNED.some(function(c) { return c >= (r.startColumnIndex || 0) && c < r.endColumnIndex; });
    })) { count('conflicts'); issue('merged_owned_cell', key, name); return; }
    if (found && PQM_GOOGLE_OWNED.some(function(c) { return !!found.data.formulas[c]; })) {
      count('conflicts'); issue('formula_in_owned_cell', key, name); return;
    }
    if (!found && !x.monitoring_eligible) { count('skipped'); return; }
    if (!found && !tabs[name].rows.length) {
      count('conflicts'); issue('missing_append_template', key, name); return;
    }
    if (!found && (!Number.isInteger(tabs[name].templateRowHeight) || tabs[name].templateRowHeight <= 0)) {
      count('conflicts'); issue('missing_template_row_height', key, name); return;
    }
    if (!found && tabs[name].merges.some(function(r) {
      return r.endRowIndex > tabs[name].rows.length &&
        (r.startColumnIndex || 0) < 15 && r.endColumnIndex > 0;
    })) { count('conflicts'); issue('merged_append_template_or_destination', key, name); return; }
    if (!found && PQM_GOOGLE_OWNED.some(function(c) {
      return !!tabs[name].rows[tabs[name].rows.length - 1].formulas[c];
    })) { count('conflicts'); issue('formula_in_append_template_owned_cell', key, name); return; }
    var incoming = {0: x.freshness_marker, 2: x.supplier_name, 5: x.prozorro_status_google, 7: x.last_application_date};
    var cells = {};
    if (!found) cells[1] = key;
    Object.keys(incoming).forEach(function(c) {
      var value = incoming[c];
      if (pqmGoogleBlank_(value)) return;
      if (c === '7') {
        value = pqmGoogleDate_(value);
        if (value === null) { count('errors'); issue('invalid_date', key, name); return; }
      }
      if (!found || found.data.values[c] !== value || (c === '7' && found.data.dateFormat !== 'dd.MM.yyyy')) cells[c] = value;
    });
    if (!found || Object.keys(cells).length) {
      changes.push({tab: name, row: found ? found.row : nextRows[name]++, append: !found, cells: cells});
      count(found ? 'updated' : 'appended');
    } else count('unchanged');
  });
  return {counts: result, per_tab: perTab, issues: issues, gaps: gaps, changes: changes};
}

function pqmGoogleFetch_() {
  var p = PropertiesService.getScriptProperties();
  var url = p.getProperty('PQM_FULL_REGISTRY_URL'), token = p.getProperty('PQM_FULL_REGISTRY_TOKEN');
  if (!url || !/^https:\/\/[^\s/?#@]+\/api\/integrations\/suppliers\/full-registry\/?$/.test(url) || !token ||
      /^https:\/\/(localhost|127\.|\[::1\])/i.test(url)) throw new Error('PQM: configure HTTPS URL and token in Script Properties.');
  var response;
  try {
    response = UrlFetchApp.fetch(url, {method: 'get', headers: {Authorization: 'Bearer ' + token},
      muteHttpExceptions: true, followRedirects: false});
  } catch (_) { throw new Error('PQM: API transport failure.'); }
  if (response.getResponseCode() !== 200) throw new Error('PQM: API HTTP ' + response.getResponseCode() + '; no writes.');
  var body;
  try { body = JSON.parse(response.getContentText()); } catch (_) { throw new Error('PQM: invalid JSON; no writes.'); }
  pqmGoogleSchema_(body);
  return body;
}

/** Sheets values are read unformatted: dates are serial numbers, codes use formattedValue. */
function pqmGoogleSnapshot_(spreadsheetId) {
  var raw = Sheets.Spreadsheets.get(spreadsheetId, {ranges: ["'ФОП'!A:O", "'ЮО'!A:O"], includeGridData: true});
  var tabs = {};
  (raw.sheets || []).forEach(function(s) {
    var data = (s.data || [])[0] || {}, rows = data.rowData || [];
    function value(c) {
      var v = c.effectiveValue || {};
      return v.stringValue !== undefined ? v.stringValue : v.numberValue !== undefined ? v.numberValue : v.boolValue !== undefined ? v.boolValue : '';
    }
    function values(r) { return Array.from({length: 15}, function(_, i) { return value((r.values || [])[i] || {}); }); }
    // Ignore formatting-only rows when deciding where to append.
    while (rows.length > 1 && !(rows[rows.length - 1].values || []).some(function(c) { return !!c.userEnteredValue || !!c.effectiveValue; })) rows.pop();
    tabs[s.properties.title] = {id: s.properties.sheetId, maxRows: s.properties.gridProperties.rowCount,
      headers: rows.length ? values(rows[0]) : [],
      templateRowHeight: ((data.rowMetadata || [])[rows.length - 1] || {}).pixelSize || null,
      rows: rows.slice(1).map(function(r) {
        var cells = r.values || [], h = cells[7] || {};
        return {values: values(r), formulas: Array.from({length: 15}, function(_, i) { return ((cells[i] || {}).userEnteredValue || {}).formulaValue || ''; }),
          codeDisplay: (cells[1] || {}).formattedValue || '',
          dateFormat: ((h.userEnteredFormat || {}).numberFormat || {}).pattern || '',
          // Full cell metadata participates in stale-preview detection (validation, protection-independent formatting, notes).
          metadata: cells};
      }), conditionalFormats: s.conditionalFormats || [], merges: s.merges || [], protectedRanges: s.protectedRanges || []};
  });
  return tabs;
}

function pqmGoogleRequests_(plan, tabs) {
  var requests = [];
  function range(id, row, col, height, width) { return {sheetId: id, startRowIndex: row - 1, endRowIndex: row - 1 + height, startColumnIndex: col, endColumnIndex: col + width}; }
  PQM_GOOGLE_TABS.forEach(function(name) {
    var t = tabs[name], adds = plan.changes.filter(function(c) { return c.tab === name && c.append; });
    if (!adds.length) return;
    var first = adds[0].row, last = adds[adds.length - 1].row, template = t.rows.length + 1;
    if (last > t.maxRows) requests.push({appendDimension: {sheetId: t.id, dimension: 'ROWS', length: last - t.maxRows}});
    ['PASTE_FORMAT', 'PASTE_DATA_VALIDATION'].forEach(function(type) {
      requests.push({copyPaste: {source: range(t.id, template, 0, 1, 15), destination: range(t.id, first, 0, adds.length, 15), pasteType: type}});
    });
    requests.push({updateDimensionProperties: {
      range: {sheetId: t.id, dimension: 'ROWS', startIndex: first - 1, endIndex: last},
      properties: {pixelSize: t.templateRowHeight}, fields: 'pixelSize'}});
    // Confirmed existing behavior: onEdit parses G into J/K using regex.
    // Preserve existing G/J/K; new G/J/K stay blank. Never copy or generate J/K formulas.
    // Other Google-owned cells also stay blank; no formula propagation is enabled.
    // Extend established conditional rules that cover the template row, preserving each rule otherwise.
    t.conditionalFormats.forEach(function(rule, i) {
      var copy = JSON.parse(JSON.stringify(rule)), changed = false;
      copy.ranges.forEach(function(r) {
        if ((r.startRowIndex || 0) <= template - 1 && r.endRowIndex !== undefined && r.endRowIndex >= template && r.endRowIndex < last) {
          r.endRowIndex = last; changed = true;
        }
      });
      if (changed) requests.push({updateConditionalFormatRule: {sheetId: t.id, index: i, rule: copy}});
    });
  });
  // Batch adjacent changed rows in each owned column. Never include untouched cells.
  PQM_GOOGLE_TABS.forEach(function(name) {
    PQM_GOOGLE_OWNED.forEach(function(col) {
      var cells = plan.changes.filter(function(c) { return c.tab === name && Object.prototype.hasOwnProperty.call(c.cells, col); }).sort(function(a, b) { return a.row - b.row; });
      for (var i = 0; i < cells.length;) {
        var start = i++;
        while (i < cells.length && cells[i].row === cells[i - 1].row + 1) i++;
        requests.push({updateCells: {range: range(tabs[name].id, cells[start].row, col, i - start, 1),
          rows: cells.slice(start, i).map(function(c) {
            var v = c.cells[col], cell = {userEnteredValue: typeof v === 'number' ? {numberValue: v} : {stringValue: v}};
            if (col === 7) cell.userEnteredFormat = {numberFormat: {type: 'DATE', pattern: 'dd.MM.yyyy'}};
            if (col === 1) cell.userEnteredFormat = {numberFormat: {type: 'TEXT', pattern: '@'}};
            return {values: [cell]};
          }), fields: 'userEnteredValue' + (col === 7 || col === 1 ? ',userEnteredFormat.numberFormat' : '')}});
      }
    });
  });
  return requests;
}

/** Shared manual/future scheduled entry. Default is strictly read-only preview.
 * Apply requires a digest from a fresh preview; no trigger is created here.
 */
function pqmGoogleWriter(options) {
  options = options || {};
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(0)) throw new Error('PQM: another writer is running.');
  try {
    var id = SpreadsheetApp.getActiveSpreadsheet().getId();
    var body = pqmGoogleFetch_(), tabs = pqmGoogleSnapshot_(id), plan = pqmGooglePlan_(body, tabs);
    // generated_at is deliberately excluded: identical data fetched later is still the same plan.
    var digest = Utilities.base64EncodeWebSafe(Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256,
      JSON.stringify({id: id, items: body.items, tabs: tabs}), Utilities.Charset.UTF_8));
    var requests = pqmGoogleRequests_(plan, tabs);
    if (options.apply === true) {
      if (!options.expectedDigest || options.expectedDigest !== digest) throw new Error('PQM: preview missing or stale; preview again.');
      if (requests.length) {
        try { Sheets.Spreadsheets.batchUpdate({requests: requests}, id); }
        catch (_) { throw new Error('PQM: apply failed or outcome unknown; preview again before retry.'); }
      }
    }
    return {dry_run: options.apply !== true, digest: digest, counts: plan.counts, per_tab: plan.per_tab,
      issues: plan.issues, gaps: plan.gaps, changes: plan.changes, batch_requests: requests.length};
  } finally { lock.releaseLock(); }
}

function pqmGooglePreview() {
  var preview = pqmGoogleWriter(), ui = SpreadsheetApp.getUi();
  var message = 'Preview — заплановані зміни:\n' + JSON.stringify(preview.counts, null, 2) +
    '\nФОП: ' + JSON.stringify(preview.per_tab['ФОП']) + '\nЮО: ' + JSON.stringify(preview.per_tab['ЮО']) +
    '\nПрогалини аудиту: ' + JSON.stringify(preview.gaps) +
    '\nКонфліктні записи пропускаються.\n\nApply: застосувати ці зміни?';
  if (ui.alert('PQM → Google', message, ui.ButtonSet.YES_NO) !== ui.Button.YES) return preview;
  var applied = pqmGoogleWriter({apply: true, expectedDigest: preview.digest});
  ui.alert('PQM → Google', 'Apply завершено.\n' + JSON.stringify(applied.counts, null, 2), ui.ButtonSet.OK);
  return applied;
}

/** Call from the existing onOpen with its three verified handler names.
 * Refuses missing handlers; does not replace or guess existing business functions.
 */
function pqmGoogleBuildMenu(handlers) {
  if (!handlers || ['clarityChecker', 'dateAndOfficer', 'organizationEditor'].some(function(k) {
    return typeof handlers[k] !== 'string' || !/^[A-Za-z_$][\w$]*$/.test(handlers[k]);
  })) throw new Error('PQM: existing menu handler names are required.');
  SpreadsheetApp.getUi().createMenu('⚙️ Робота з даними')
    .addItem('PQM → Google', 'pqmGooglePreview').addSeparator()
    .addItem('🏢 Заповнити дані з файлу ClarityChecker', handlers.clarityChecker).addSeparator()
    .addItem('📆 Оновити Дату та УО для виділених рядків', handlers.dateAndOfficer).addSeparator()
    .addItem('✏️ Редактор ЮО', handlers.organizationEditor).addToUi();
}

if (typeof module !== 'undefined') module.exports = {
  headers: PQM_GOOGLE_HEADERS, plan: pqmGooglePlan_, requests: pqmGoogleRequests_, date: pqmGoogleDate_,
  writer: pqmGoogleWriter, preview: pqmGooglePreview, snapshot: pqmGoogleSnapshot_, menu: pqmGoogleBuildMenu
};
