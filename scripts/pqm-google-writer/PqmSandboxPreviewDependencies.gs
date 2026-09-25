var PQM_GOOGLE_HEADERS = [
  'Маркер актуальності', 'Код ЄДРПОУ', 'Найменування', 'ПІБ для перевірки',
  'Статус в реєстрі (ЄДР)', 'Статус (Prozorro)', 'Реквізити рішення про припинення',
  'Дата останньої заявки', 'Дата перевірки', 'Дата запису', 'Номер запису',
  'УО', 'Примітки', 'Повна назва з ЄДР', 'Скорочена назва з ЄДР'
];
var PQM_GOOGLE_TABS = ['ФОП', 'ЮО'];
var PQM_GOOGLE_OWNED = [1, 2, 4, 5, 7, 8, 11];
var PQM_GOOGLE_APPEND_OWNED = [1, 2, 4, 5, 7, 8, 11];
var PQM_GOOGLE_SNAPSHOT_CHUNK_ROWS = 500;

function pqmGoogleCounts_() {
  return {api_records: 0, matched: 0, appended: 0, updated: 0, unchanged: 0,
    skipped: 0, conflicts: 0, duplicate_keys: 0, errors: 0,
    google_newer_preserved: 0, same_date_google_officer_preserved: 0,
    same_date_equivalent: 0, pqm_newer_written: 0, google_blank_filled: 0,
    pqm_blank_google_preserved: 0};
}

function pqmGoogleSchema_(body) {
  if (!body || !Array.isArray(body.items) || !Number.isInteger(body.count) ||
      body.count !== body.items.length) throw new Error('PQM: schema mismatch (count/items).');
  body.items.forEach(function(x) {
    if (!x || typeof x.supplier_code !== 'string' || !x.supplier_code.trim() ||
        ['individual_entrepreneur', 'legal_entity', 'foreign_legal_entity', 'unknown'].indexOf(x.entity_type) < 0 ||
        typeof x.monitoring_eligible !== 'boolean' || typeof x.google_sync_eligible !== 'boolean' ||
        ['supplier_name', 'edr_status_current', 'prozorro_status_google', 'freshness_marker',
          'last_application_date', 'google_sync_last_decided_application_date',
          'verification_date', 'verification_officer'].some(function(k) {
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

function pqmGoogleCalendarDate_(value) {
  if (pqmGoogleBlank_(value)) return {kind: 'blank', value: null};
  function iso(year, month, day) {
    var ms = Date.UTC(year, month - 1, day);
    var actual = new Date(ms);
    if (actual.getUTCFullYear() !== year || actual.getUTCMonth() !== month - 1 || actual.getUTCDate() !== day) return null;
    return actual.toISOString().slice(0, 10);
  }
  if (Object.prototype.toString.call(value) === '[object Date]') {
    if (isNaN(value.getTime())) return {kind: 'invalid', value: null};
    return {kind: 'date', value: value.toISOString().slice(0, 10)};
  }
  if (typeof value === 'number') {
    if (!isFinite(value)) return {kind: 'invalid', value: null};
    var serialDate = new Date((Math.floor(value) - 25569) * 86400000);
    if (isNaN(serialDate.getTime())) return {kind: 'invalid', value: null};
    return {kind: 'date', value: serialDate.toISOString().slice(0, 10)};
  }
  if (typeof value !== 'string') return {kind: 'invalid', value: null};
  var text = value.trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) {
    var serial = pqmGoogleDate_(text);
    return {kind: serial === null ? 'invalid' : 'date', value: serial === null ? null : text};
  }
  var parts = /^(\d{2})\.(\d{2})\.(\d{4})$/.exec(text);
  if (parts) {
    var converted = iso(Number(parts[3]), Number(parts[2]), Number(parts[1]));
    return {kind: converted ? 'date' : 'invalid', value: converted};
  }
  return {kind: 'invalid', value: null};
}

function pqmGoogleBlank_(v) {
  return v === null || v === undefined || (typeof v === 'string' && !v.trim());
}

var PQM_GOOGLE_EDR_CURRENT_STATUSES = [
  'Неактуально', 'Зареєстровано', 'Припинено',
  'В стані припинення', 'Порушено справу про банкрутство', 'Банкрут'
];
function pqmGoogleEdrCurrentStatus_(value) {
  if (pqmGoogleBlank_(value)) return '';
  var text = String(value).trim().replace(/^[^\p{L}\p{N}]+/u, '').trim();
  return PQM_GOOGLE_EDR_CURRENT_STATUSES.indexOf(text) >= 0 ? text : null;
}

function pqmGoogleEdrPreserveInformation_(value) {
  if (pqmGoogleBlank_(value)) return false;
  return String(value).trim().replace(/^[^\p{L}\p{N}]+/u, '').trim()
    .replace(/\s+/g, ' ').toLocaleLowerCase('uk-UA') === 'немає інформації';
}

function pqmGoogleOfficerComparable_(value) {
  return String(value || '').normalize('NFC').trim().replace(/\s+/g, ' ').toLocaleLowerCase('uk-UA');
}

function pqmGooglePlan_(body, tabs) {
  pqmGoogleSchema_(body);
  var result = pqmGoogleCounts_(), perTab = {}, issues = [], changes = [], index = new Map(), apiKeys = new Map();
  result.api_records = body.items.length;
  function issue(code, key, tab) { issues.push({reason: code, supplier_code: key, tab: tab || null}); }
  PQM_GOOGLE_TABS.forEach(function(name) {
    var t = tabs[name]; perTab[name] = pqmGoogleCounts_();
    if (!t || JSON.stringify(t.headers) !== JSON.stringify(PQM_GOOGLE_HEADERS)) throw new Error('PQM: header mismatch: ' + name);
    t.rows.forEach(function(row, i) {
      var raw = row.values[1];
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
    if (template && template.formulas.some(Boolean)) gaps.push({tab: name, reason: 'append_formulas_not_audited_left_blank', row: t.rows.length + 1});
  });
  var nextRows = {};
  PQM_GOOGLE_TABS.forEach(function(t) { nextRows[t] = tabs[t].rows.length + 2; });
  body.items.forEach(function(x) {
    var key = x.supplier_code.trim();
    var name = x.entity_type === 'individual_entrepreneur' ? 'ФОП' : x.entity_type === 'legal_entity' ? 'ЮО' : null;
    function count(k) { result[k]++; if (name) perTab[name][k]++; }
    if (name) perTab[name].api_records++;
    if (!x.google_sync_eligible) { count('skipped'); return; }
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
    if (!found && !tabs[name].rows.length) { count('conflicts'); issue('missing_append_template', key, name); return; }
    if (!found && (!Number.isInteger(tabs[name].templateRowHeight) || tabs[name].templateRowHeight <= 0)) {
      count('conflicts'); issue('missing_template_row_height', key, name); return;
    }
    if (!found && tabs[name].merges.some(function(r) {
      return r.endRowIndex > tabs[name].rows.length && (r.startColumnIndex || 0) < 15 && r.endColumnIndex > 0;
    })) { count('conflicts'); issue('merged_append_template_or_destination', key, name); return; }
    if (!found && PQM_GOOGLE_APPEND_OWNED.some(function(c) { return !!tabs[name].rows[tabs[name].rows.length - 1].formulas[c]; })) {
      count('conflicts'); issue('formula_in_append_template_owned_cell', key, name); return;
    }
    var incoming = {2: x.supplier_name, 5: x.prozorro_status_google,
      7: x.google_sync_last_decided_application_date};
    if (found) {
      incoming[4] = x.edr_status_current;
    }
    var cells = {};
    if (!found) cells[1] = key;
    if (!found) {
      var initialDate = pqmGoogleCalendarDate_(x.verification_date);
      if (initialDate.kind === 'invalid' ||
          (initialDate.kind === 'date' && pqmGoogleBlank_(x.verification_officer))) {
        count('conflicts'); issue('invalid_initial_verification_pair', key, name); return;
      }
      if (initialDate.kind === 'date') {
        cells[8] = pqmGoogleDate_(initialDate.value);
        cells[11] = x.verification_officer;
        count('google_blank_filled');
      }
      if (!pqmGoogleBlank_(x.edr_status_current)) {
        var initialStatus = pqmGoogleEdrCurrentStatus_(x.edr_status_current);
        if (initialStatus === null) { count('errors'); issue('unknown_edr_current_status', key, name); return; }
        cells[4] = initialStatus;
      }
    }
    if (found) {
      var pqmDate = pqmGoogleCalendarDate_(x.verification_date);
      var googleDate = pqmGoogleCalendarDate_(found.data.values[8]);
      if (pqmDate.kind === 'invalid' || googleDate.kind === 'invalid') {
        count('conflicts'); issue('invalid_verification_date', key, name); return;
      }
      if (pqmDate.kind === 'date' && pqmGoogleBlank_(x.verification_officer)) {
        count('conflicts'); issue('incomplete_pqm_verification_pair', key, name); return;
      }
      if (pqmDate.kind === 'blank') {
        if (googleDate.kind === 'date') count('pqm_blank_google_preserved');
      } else if (googleDate.kind === 'blank') {
        cells[8] = pqmGoogleDate_(pqmDate.value);
        cells[11] = x.verification_officer;
        count('google_blank_filled');
      } else if (pqmDate.value > googleDate.value) {
        cells[8] = pqmGoogleDate_(pqmDate.value);
        cells[11] = x.verification_officer;
        count('pqm_newer_written');
      } else if (pqmDate.value < googleDate.value) {
        count('google_newer_preserved');
      } else if (pqmGoogleOfficerComparable_(x.verification_officer) !==
                 pqmGoogleOfficerComparable_(found.data.values[11])) {
        count('same_date_google_officer_preserved');
      } else {
        count('same_date_equivalent');
      }
    }
    Object.keys(incoming).forEach(function(c) {
      var value = incoming[c];
      if (pqmGoogleBlank_(value)) return;
      if (c === '4') {
        value = pqmGoogleEdrCurrentStatus_(value);
        if (value === null) { count('errors'); issue('unknown_edr_current_status', key, name); return; }
        if (found && pqmGoogleEdrPreserveInformation_(found.data.values[c])) return;
        if (found && pqmGoogleEdrCurrentStatus_(found.data.values[c]) === value) return;
      }
      if (c === '7') {
        var incomingDate = pqmGoogleCalendarDate_(value);
        if (incomingDate.kind !== 'date') { count('errors'); issue('invalid_date', key, name); return; }
        value = pqmGoogleDate_(incomingDate.value);
        if (found && pqmGoogleCalendarDate_(found.data.values[c]).value === incomingDate.value) return;
      }
      if (!found || found.data.values[c] !== value) cells[c] = value;
    });
    if (!found || Object.keys(cells).length) {
      changes.push({tab: name, row: found ? found.row : nextRows[name]++, append: !found, cells: cells});
      count(found ? 'updated' : 'appended');
    } else count('unchanged');
  });
  return {counts: result, per_tab: perTab, issues: issues, gaps: gaps, changes: changes};
}

function pqmGoogleSnapshot_(spreadsheetId) {
  var metadata = Sheets.Spreadsheets.get(spreadsheetId, {
    includeGridData: false,
    fields: 'sheets(properties(title,sheetId,gridProperties(rowCount)),merges,protectedRanges,conditionalFormats)'
  });
  var sheets = {};
  (metadata.sheets || []).forEach(function(s) { sheets[s.properties.title] = s; });
  function value(c) {
    var v = c.effectiveValue || {};
    return v.stringValue !== undefined ? v.stringValue : v.numberValue !== undefined ? v.numberValue : v.boolValue !== undefined ? v.boolValue : '';
  }
  function values(r) { return Array.from({length: 15}, function(_, i) { return value((r.values || [])[i] || {}); }); }
  function hasContent(r) { return (r.values || []).some(function(c) { return !!c.userEnteredValue || !!c.effectiveValue; }); }
  function compactRow(r) {
    var cells = r.values || [], h = cells[7] || {};
    return {
      values: values(r),
      formulas: Array.from({length: 15}, function(_, i) { return ((cells[i] || {}).userEnteredValue || {}).formulaValue || ''; }),
      codeDisplay: (cells[1] || {}).formattedValue || '',
      dateFormat: ((h.userEnteredFormat || {}).numberFormat || {}).pattern || ''
    };
  }
  var tabs = {};
  PQM_GOOGLE_TABS.forEach(function(name) {
    var sheet = sheets[name];
    if (!sheet) return;
    var rowCount = sheet.properties.gridProperties.rowCount;
    var rowsByIndex = [], heightsByIndex = [], highestContentRow = -1;
    var header = Sheets.Spreadsheets.Values.get(
      spreadsheetId,
      "'" + name.replace(/'/g, "''") + "'!A1:O1",
      {valueRenderOption: 'UNFORMATTED_VALUE'}
    );
    for (var start = 1; start < rowCount; start += PQM_GOOGLE_SNAPSHOT_CHUNK_ROWS) {
      var end = Math.min(rowCount, start + PQM_GOOGLE_SNAPSHOT_CHUNK_ROWS);
      var range = "'" + name.replace(/'/g, "''") + "'!A" + (start + 1) + ':O' + end;
      var raw = Sheets.Spreadsheets.get(spreadsheetId, {
        ranges: [range],
        includeGridData: true,
        fields: 'sheets(data(startRow,rowData(values(effectiveValue,formattedValue,userEnteredValue,userEnteredFormat(numberFormat))),rowMetadata(pixelSize)))'
      });
      var data = (((raw.sheets || [])[0] || {}).data || [])[0] || {};
      var dataStart = Number.isInteger(data.startRow) ? data.startRow : start;
      (data.rowData || []).forEach(function(row, offset) {
        var index = dataStart + offset;
        rowsByIndex[index] = compactRow(row);
        if (hasContent(row)) highestContentRow = Math.max(highestContentRow, index);
      });
      (data.rowMetadata || []).forEach(function(meta, offset) { heightsByIndex[dataStart + offset] = meta; });
    }
    var retainedRows = highestContentRow < 1 ? [] : Array.from({length: highestContentRow}, function(_, i) { return rowsByIndex[i + 1] || compactRow({}); });
    var templateIndex = highestContentRow;
    tabs[name] = {
      id: sheet.properties.sheetId,
      maxRows: rowCount,
      headers: (header.values || [])[0] || [],
      templateRowHeight: templateIndex >= 0 && heightsByIndex[templateIndex] ? heightsByIndex[templateIndex].pixelSize || null : null,
      rows: retainedRows,
      conditionalFormats: sheet.conditionalFormats || [],
      merges: sheet.merges || [],
      protectedRanges: sheet.protectedRanges || []
    };
  });
  return tabs;
}


function pqmSandboxDebugHeaders() {
  var spreadsheetId = SpreadsheetApp.getActiveSpreadsheet().getId();

  ['ФОП', 'ЮО'].forEach(function(name) {
    var response = Sheets.Spreadsheets.Values.get(
      spreadsheetId,
      "'" + name + "'!A1:O1",
      {valueRenderOption: 'UNFORMATTED_VALUE'}
    );

    var actual = (response.values || [])[0] || [];

    console.log('=== ' + name + ' ===');

    PQM_GOOGLE_HEADERS.forEach(function(expected, i) {
      var got = actual[i] === undefined ? '' : String(actual[i]);

      if (got !== expected) {
        console.log(JSON.stringify({
          column: String.fromCharCode(65 + i),
          index: i,
          actual: got,
          expected: expected,
          actualLength: got.length,
          expectedLength: expected.length,
          actualCodes: Array.from(got).map(function(c) {
            return c.charCodeAt(0);
          }),
          expectedCodes: Array.from(expected).map(function(c) {
            return c.charCodeAt(0);
          })
        }));
      }
    });
  });
}

function pqmGooglePlanAggregate_(plan) {
  var letters={1:'B',2:'C',4:'E',5:'F',7:'H',8:'I',11:'L'}, out={by_tab:{},by_column:{},by_action:{},by_reason:{},by_combination:{},unchanged:plan.counts.unchanged};
  plan.changes.forEach(function(change){
    var action=change.append?'append':'update', cols=Object.keys(change.cells).map(function(c){return letters[Number(c)];}).sort().join('+')||'(none)';
    out.by_tab[change.tab]=(out.by_tab[change.tab]||0)+1;
    out.by_action[action]=(out.by_action[action]||0)+1;
    out.by_reason['PQM-owned nonblank field']=(out.by_reason['PQM-owned nonblank field']||0)+1;
    out.by_combination[cols]=(out.by_combination[cols]||0)+1;
    Object.keys(change.cells).forEach(function(c){var k=letters[Number(c)];out.by_column[k]=(out.by_column[k]||0)+1;});
  }); return out;
}

/* Aggregate-only diagnostic.  It deliberately retains no sheet or PQM values. */
function pqmGooglePlanComparisonAudit_(plan, tabs) {
  var letters = {1:'B',2:'C',4:'E',5:'F',7:'H',8:'I',11:'L'};
  var out = {planned_matched_cells: 0, planned_append_cells: 0,
    value_mismatch: 0, date_format_only: 0, current_value_types: {}};
  plan.changes.forEach(function(change) {
    if (change.append) {
      out.planned_append_cells += Object.keys(change.cells).length;
      return;
    }
    var row = (tabs[change.tab].rows || [])[change.row - 2] || {values: [], dateFormat: ''};
    Object.keys(change.cells).forEach(function(rawColumn) {
      out.planned_matched_cells++;
      var column = Number(rawColumn);
      var current = row.values[column];
      var type = current === null ? 'null' : Array.isArray(current) ? 'array' : typeof current;
      var key = letters[column] + ':' + type;
      out.current_value_types[key] = (out.current_value_types[key] || 0) + 1;
      if (column === 7 && current === change.cells[rawColumn] && row.dateFormat !== 'dd.MM.yyyy') {
        out.date_format_only++;
      } else {
        out.value_mismatch++;
      }
    });
  });
  return out;
}

/* Optimized read-only snapshot; this final definition replaces the legacy one. */
var PQM_GOOGLE_SNAPSHOT_VALUE_CHUNK_ROWS = 1000;
var PQM_GOOGLE_SNAPSHOT_VALUES_BATCH_RANGES = 3;
var PQM_GOOGLE_SNAPSHOT_H_BATCH_RANGES = 4;
function pqmGoogleReadRetry_(action) {
  for (var attempt = 0; attempt < 4; attempt++) {
    try { return action(); }
    catch (error) {
      var message = String((error && error.message) || error);
      var quota = (error && (error.code === 429 || error.responseCode === 429)) ||
        /(?:\b429\b|quota exceeded for quota metric ['"]?Read requests|read requests per minute per user)/i.test(message);
      if (!quota || attempt === 3) throw error;
      Utilities.sleep(5000 * Math.pow(2, attempt));
    }
  }
}
function pqmGoogleSnapshotProfileCall_(profile, phase, rows, cells, ranges, action) {
  if (!profile) return pqmGoogleReadRetry_(action);
  var entry = profile[phase] || (profile[phase] = {
    calls: 0, total_ms: 0, max_single_call_ms: 0,
    requested_rows: 0, requested_cells: 0, requested_ranges: 0
  });
  var started = Date.now();
  try { return pqmGoogleReadRetry_(action); }
  finally {
    var elapsed = Date.now() - started;
    entry.calls++;
    entry.total_ms += elapsed;
    entry.max_single_call_ms = Math.max(entry.max_single_call_ms, elapsed);
    entry.requested_rows += rows;
    entry.requested_cells += cells;
    entry.requested_ranges += ranges;
  }
}

function pqmGoogleSnapshot_(spreadsheetId, profile) {
  var meta = pqmGoogleSnapshotProfileCall_(profile,'sheet_metadata',0,0,0,function(){
    return Sheets.Spreadsheets.get(spreadsheetId, {includeGridData:false,
      fields:'sheets(properties(title,sheetId,gridProperties(rowCount)),merges,protectedRanges,conditionalFormats)'});
  });
  var byName={}; (meta.sheets||[]).forEach(function(s){byName[s.properties.title]=s;});
  var tabs={};
  function blank(){return {values:Array(15).fill(''),formulas:Array(15).fill(''),codeDisplay:'',dateFormat:'',verificationDateFormat:''};}
  PQM_GOOGLE_TABS.forEach(function(name){
    var sheet=byName[name]; if(!sheet)return;
    var count=sheet.properties.gridProperties.rowCount, esc="'"+name.replace(/'/g,"''")+"'";
    var chunks=[];
    for(var first=2;first<=count;first+=PQM_GOOGLE_SNAPSHOT_VALUE_CHUNK_ROWS){
      chunks.push({start:first,end:Math.min(count,first+PQM_GOOGLE_SNAPSHOT_VALUE_CHUNK_ROWS-1)});
    }
    function batchValues(ranges,render,phase,rows,cells){
      var result=pqmGoogleSnapshotProfileCall_(profile,phase,rows,cells,ranges.length,function(){
        return Sheets.Spreadsheets.Values.batchGet(spreadsheetId,{ranges:ranges,valueRenderOption:render});
      });
      if(!result||!Array.isArray(result.valueRanges)||result.valueRanges.length!==ranges.length){
        throw new Error('PQM: batched values response incomplete.');
      }
      return result.valueRanges;
    }
    var header, dataValues=[],displayValues=[],formulaValues=[],gridValues=[];
    for(var batchStart=0;batchStart<chunks.length||batchStart===0;batchStart+=PQM_GOOGLE_SNAPSHOT_VALUES_BATCH_RANGES){
      var part=chunks.slice(batchStart,batchStart+PQM_GOOGLE_SNAPSHOT_VALUES_BATCH_RANGES);
      var ranges=part.map(function(x){return esc+'!A'+x.start+':O'+x.end;});
      if(batchStart===0)ranges.unshift(esc+'!A1:O1');
      var read=batchValues(ranges,'UNFORMATTED_VALUE','data_values_A_O',
        part.reduce(function(n,x){return n+x.end-x.start+1;},batchStart===0?1:0),
        part.reduce(function(n,x){return n+(x.end-x.start+1)*15;},batchStart===0?15:0));
      if(batchStart===0)header=read.shift();
      Array.prototype.push.apply(dataValues,read);
    }
    if(!header)throw new Error('PQM: header values response incomplete.');
    var bRanges=chunks.map(function(x){return esc+'!B'+x.start+':B'+x.end;});
    if(bRanges.length)displayValues=batchValues(bRanges,'FORMATTED_VALUE','formatted_code_B',count-1,count-1);
    var formulaColumns=[{letter:'A',column:0},{letter:'B',column:1},{letter:'C',column:2},
      {letter:'E',column:4},{letter:'F',column:5},{letter:'L',column:11}];
    var formulaRanges=[];
    chunks.forEach(function(x){formulaColumns.forEach(function(c){formulaRanges.push(esc+'!'+c.letter+x.start+':'+c.letter+x.end);});});
    if(formulaRanges.length)formulaValues=batchValues(formulaRanges,'FORMULA','formula_values_A_B_C_E_F_L',(count-1)*6,(count-1)*6);
    for(var hStart=0;hStart<chunks.length;hStart+=PQM_GOOGLE_SNAPSHOT_H_BATCH_RANGES){
      var hPart=chunks.slice(hStart,hStart+PQM_GOOGLE_SNAPSHOT_H_BATCH_RANGES);
      var hRanges=[]; hPart.forEach(function(x){hRanges.push(esc+'!H'+x.start+':H'+x.end,esc+'!I'+x.start+':I'+x.end);});
      var hRaw=pqmGoogleSnapshotProfileCall_(profile,'grid_metadata_H_I',
        hPart.reduce(function(n,x){return n+x.end-x.start+1;},0),
        hPart.reduce(function(n,x){return n+(x.end-x.start+1)*2;},0),hRanges.length,function(){
          return Sheets.Spreadsheets.get(spreadsheetId,{ranges:hRanges,includeGridData:true,
            fields:'sheets(data(startRow,startColumn,rowData(values(userEnteredValue(formulaValue),userEnteredFormat(numberFormat)))))'});
        });
      var hData=((((hRaw.sheets||[])[0]||{}).data)||[]);
      if(hData.length!==hPart.length*2)throw new Error('PQM: H/I grid metadata response incomplete.');
      hData.forEach(function(data,i){
        if(data.startRow!==hPart[Math.floor(i/2)].start-1||data.startColumn!==7+i%2)throw new Error('PQM: H/I grid metadata range mismatch.');
      });
      Array.prototype.push.apply(gridValues,hData);
    }
    var rows=[], highest=0;
    chunks.forEach(function(chunk,chunkIndex){
      var start=chunk.start,end=chunk.end;
      var values=dataValues[chunkIndex].values||[];
      for(var i=0;i<values.length;i++){var r=blank(),v=values[i]||[];for(var c=0;c<15;c++)r.values[c]=v[c]===undefined?'':v[c];if(v.length)highest=Math.max(highest,start+i);rows[start+i-2]=r;}
      var display=displayValues[chunkIndex].values||[];
      display.forEach(function(v,i){var r=rows[start+i-2]||(rows[start+i-2]=blank());r.codeDisplay=v&&v[0]!==undefined?String(v[0]):'';});
      var formulaResult={valueRanges:formulaValues.slice(chunkIndex*6,chunkIndex*6+6)};
      var suspicious=[];
      formulaColumns.forEach(function(x,j){
        var valueRows=formulaResult.valueRanges[j].values||[],found=false;
        valueRows.forEach(function(v,i){if(typeof (v||[])[0]==='string'&&(v[0].charAt(0)==='='))found=true;});
        if(found)suspicious.push(x);
      });
      function applyGrid(data,allowed){
        var column=data.startColumn===undefined&&allowed.indexOf(0)>=0?0:data.startColumn;
        if(!Number.isInteger(data.startRow)||!Number.isInteger(column)||allowed.indexOf(column)<0){
          throw new Error('PQM: grid metadata range mismatch.');
        }
        (data.rowData||[]).forEach(function(rd,i){
          var idx=data.startRow+i-1,r=rows[idx]||(rows[idx]=blank()),cell=(rd.values||[])[0]||{};
          r.formulas[column]=((cell.userEnteredValue||{}).formulaValue||'');
          if(column===7)r.dateFormat=(((cell.userEnteredFormat||{}).numberFormat||{}).pattern||'');
          if(column===8)r.verificationDateFormat=(((cell.userEnteredFormat||{}).numberFormat||{}).pattern||'');
        });
      }
      var gridData=gridValues.slice(chunkIndex*2,chunkIndex*2+2);
      if(gridData.length!==2)throw new Error('PQM: H/I grid metadata response incomplete.');
      gridData.forEach(function(data){applyGrid(data,[7,8]);});
      if(suspicious.length){
        var suspectRanges=suspicious.map(function(x){return esc+'!'+x.letter+start+':'+x.letter+end;});
        var fallback=pqmGoogleSnapshotProfileCall_(profile,'formula_disambiguation_A_B_C_E_F_L',end-start+1,(end-start+1)*suspicious.length,suspicious.length,function(){
          return Sheets.Spreadsheets.get(spreadsheetId,{ranges:suspectRanges,includeGridData:true,
            fields:'sheets(data(startRow,startColumn,rowData(values(userEnteredValue(formulaValue)))))'});
        });
        var fallbackData=((((fallback.sheets||[])[0]||{}).data)||[]);
        if(fallbackData.length!==suspicious.length)throw new Error('PQM: formula disambiguation incomplete.');
        var actualColumns=fallbackData.map(function(data){return data.startColumn===undefined?0:data.startColumn;}).sort().join(',');
        var expectedColumns=suspicious.map(function(x){return x.column;}).sort().join(',');
        if(actualColumns!==expectedColumns)throw new Error('PQM: formula disambiguation columns mismatch.');
        fallbackData.forEach(function(data){applyGrid(data,suspicious.map(function(x){return x.column;}));});
      }
    });
    // highest is already the 1-based A1 row number of the final content row.
    // Never add one here: a last-row value at physical row N has template A1=N.
    var template=highest >= 2 ? highest : 1, h=pqmGoogleSnapshotProfileCall_(profile,'template_row_height',1,1,1,function(){
      return Sheets.Spreadsheets.get(spreadsheetId,{ranges:[esc+'!A'+template+':A'+template],includeGridData:true,fields:'sheets(data(startRow,rowMetadata(pixelSize)))'});
    });
    var height=(((((h.sheets||[])[0]||{}).data||[])[0]||{}).rowMetadata||[])[0]||{};
    tabs[name]={id:sheet.properties.sheetId,maxRows:count,headers:(header.values||[])[0]||[],rows:rows.slice(0,Math.max(0,highest-1)),templateRowHeight:height.pixelSize||null,conditionalFormats:sheet.conditionalFormats||[],merges:sheet.merges||[],protectedRanges:sheet.protectedRanges||[]};
  }); return tabs;
}
