/* SANDBOX-only factual Google E restore. Sheet reads never mutate Google. */
var PQM_FACTUAL_EDR_TICKET_PROPERTY = 'PQM_FACTUAL_EDR_PREVIEW_TICKET';
var PQM_FACTUAL_EDR_DIGEST_PROPERTY = 'PQM_FACTUAL_EDR_APPLY_SELECTION_DIGEST';
var PQM_FACTUAL_EDR_CONFIRMATION_PROPERTY = 'PQM_FACTUAL_EDR_APPLY_CONFIRMATION';
var PQM_FACTUAL_EDR_BATCH_CONFIRMATION = 'APPLY_SANDBOX_FACTUAL_EDR_BATCH_MAX_50';
function pqmSandboxFactualEdrRestorePayload_() {
  var spreadsheetId = pqmSandboxControlledSpreadsheetId_();
  var registryUrl = pqmSandboxRegistryUrl_();
  if (registryUrl !== 'https://pqm-sandbox.onrender.com/api/integrations/suppliers/full-registry') {
    throw new Error('PQM SANDBOX: factual restore URL guard failed.');
  }
  var token = PropertiesService.getScriptProperties().getProperty(
    PQM_SANDBOX_FULL_REGISTRY_TOKEN_PROPERTY);
  if (!token) throw new Error('PQM SANDBOX: factual restore token missing.');
  var tabs = pqmGoogleSnapshot_(spreadsheetId);
  var allowed = {'Припинено':true, 'В стані припинення':true,
    'Порушено справу про банкрутство':true, 'Банкрут':true};
  function semantic(value) {
    return String(value == null ? '' : value).trim().replace(/^[^\p{L}\p{N}]+/u, '').trim();
  }
  function prozorro(value) {
    var text = semantic(value);
    if (text.indexOf('Ще не в реєстрі') !== -1) return 'Ще не в реєстрі';
    if (text.indexOf('Неактивний') !== -1) return 'Неактивний';
    if (text.indexOf('Активний') !== -1) return 'Активний';
    return 'other';
  }
  var all = [], seen = {}, skippedFormula = 0, skippedInvalidPair = 0;
  PQM_GOOGLE_TABS.forEach(function(tab) {
    if (!tabs[tab] || JSON.stringify(tabs[tab].headers) !== JSON.stringify(PQM_GOOGLE_HEADERS)) {
      throw new Error('PQM SANDBOX: factual restore header mismatch.');
    }
    tabs[tab].rows.forEach(function(row, index) {
      var code = String(row.codeDisplay || '').trim();
      var values = row.values || [], formulas = row.formulas || [];
      var status = semantic(values[4]);
      if (!code) return;
      seen[code] = (seen[code] || 0) + 1;
      if (!allowed[status]) return;
      if (formulas[4] || formulas[8] || formulas[11]) { skippedFormula++; return; }
      var date = pqmGoogleCalendarDate_(values[8]);
      var officer = String(values[11] == null ? '' : values[11]).trim();
      if (date.kind !== 'date' || !officer) { skippedInvalidPair++; return; }
      all.push({supplier_code:code, source_tab:tab, source_row:index+2,
        verification_date:date.value, verification_officer:officer,
        factual_edr_status:status, source:'legacy_google_registry', formulas:[],
        google_activity:prozorro(values[5])});
    });
  });
  if (Object.keys(seen).some(function(code) { return seen[code] > 1; })) {
    throw new Error('PQM SANDBOX: duplicate factual supplier identity; no POST.');
  }
  var selected = [];
  function take(predicate, count) {
    all.forEach(function(item) {
      if (count <= 0 || selected.indexOf(item) >= 0 || !predicate(item)) return;
      selected.push(item); count--;
    });
  }
  take(function(x) { return x.factual_edr_status === 'Припинено' &&
    x.google_activity === 'Активний' && x.source_tab === 'ФОП'; }, 1);
  take(function(x) { return x.factual_edr_status === 'Припинено' &&
    x.google_activity === 'Активний' && x.source_tab === 'ЮО'; }, 1);
  take(function(x) { return x.factual_edr_status === 'Припинено' &&
    x.google_activity === 'Неактивний'; }, 1);
  take(function(x) { return x.factual_edr_status === 'В стані припинення'; }, 2);
  take(function(x) { return x.factual_edr_status === 'Порушено справу про банкрутство'; }, 2);
  take(function() { return true; }, 10-selected.length);
  if (!selected.length || selected.length > 10) throw new Error('PQM SANDBOX: selection bound failed.');
  selected.sort(function(a,b) {
    return a.source_tab < b.source_tab ? -1 : a.source_tab > b.source_tab ? 1 :
      a.source_row-b.source_row || (a.supplier_code < b.supplier_code ? -1 : 1);
  });
  var records = selected.map(function(x) { return {
    supplier_code:x.supplier_code, source_tab:x.source_tab, source_row:x.source_row,
    verification_date:x.verification_date, verification_officer:x.verification_officer,
    factual_edr_status:x.factual_edr_status, source:x.source, formulas:x.formulas};
  });
  var keys = ['supplier_code','source_tab','source_row','verification_date',
    'verification_officer','factual_edr_status','source','formulas'];
  var sourceRows = records.map(function(x) { return keys.map(function(key) { return x[key]; }); });
  var digest = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256,
    JSON.stringify(sourceRows), Utilities.Charset.UTF_8).map(function(byte) {
      return ('0'+(byte & 255).toString(16)).slice(-2);
    }).join('');
  all.sort(function(a,b) {
    return a.source_tab < b.source_tab ? -1 : a.source_tab > b.source_tab ? 1 :
      a.source_row-b.source_row || (a.supplier_code < b.supplier_code ? -1 : 1);
  });
  return {url:registryUrl.replace('/api/integrations/suppliers/full-registry',
      '/api/integrations/google/factual-edr/preview'), token:token,
    payload:{spreadsheet_id:spreadsheetId, source_digest:digest, records:records},
    candidates:all.map(function(x) { return {
      supplier_code:x.supplier_code, source_tab:x.source_tab, source_row:x.source_row,
      verification_date:x.verification_date, verification_officer:x.verification_officer,
      factual_edr_status:x.factual_edr_status, source:x.source, formulas:x.formulas}; }),
    skipped_formula:skippedFormula, skipped_invalid_pair:skippedInvalidPair};
}

function pqmSandboxFactualEdrPayloadFor_(spreadsheetId, records) {
  if (!records.length || records.length > 50) throw new Error('PQM SANDBOX: max-50 bound failed.');
  var keys = ['supplier_code','source_tab','source_row','verification_date',
    'verification_officer','factual_edr_status','source','formulas'];
  var sourceRows = records.map(function(x) { return keys.map(function(key) { return x[key]; }); });
  var digest = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256,
    JSON.stringify(sourceRows), Utilities.Charset.UTF_8).map(function(byte) {
      return ('0'+(byte & 255).toString(16)).slice(-2);
    }).join('');
  return {spreadsheet_id:spreadsheetId, source_digest:digest, records:records};
}

/* Bounded read-only scan: equivalents are skipped, blockers stop the batch. */
function pqmSandboxFactualEdrNextBatch_() {
  var current = pqmSandboxFactualEdrRestorePayload_();
  var candidates = current.candidates, eligible = [], equivalent = 0, scanned = 0,
    blocked = 0, ambiguous = 0;
  for (var offset=0; offset<candidates.length; offset+=50) {
    var window = candidates.slice(offset, offset+50);
    var payload = pqmSandboxFactualEdrPayloadFor_(current.payload.spreadsheet_id, window);
    var check = pqmSandboxFactualEdrPost_(current.url, current.token, payload);
    if (check.db_writes !== 0 || check.google_writes !== 0 || check.query_only !== 1 ||
        check.received !== window.length || !Array.isArray(check.rows) ||
        check.rows.length !== window.length) {
      throw new Error('PQM SANDBOX: factual batch scan blocked; no Apply.');
    }
    window.forEach(function(record, index) {
      var result = check.rows[index];
      if (result.source_tab !== record.source_tab || result.source_row !== record.source_row) {
        throw new Error('PQM SANDBOX: factual scan row mismatch.');
      }
      if (result.result === 'new_event_needed' || result.result === 'existing_event_enrichment') {
        if (eligible.length < 50) eligible.push(record);
      } else if (result.result === 'equivalent_factual_evidence') equivalent++;
      else if (result.result.indexOf('ambiguous') >= 0 ||
               result.result.indexOf('routing') >= 0) ambiguous++;
      else blocked++;
    });
    scanned += window.length;
  }
  current.scan = {candidates:candidates.length, scanned:scanned, equivalent:equivalent,
    blocked:blocked, ambiguous:ambiguous,
    remaining_selected:eligible.length};
  current.payload = eligible.length ?
    pqmSandboxFactualEdrPayloadFor_(current.payload.spreadsheet_id, eligible) : null;
  return current;
}

function pqmSandboxFactualEdrPost_(url, token, payload) {
  var response = pqmMirrorFetch_(url, {method:'post', contentType:'application/json',
    headers:{Authorization:'Bearer '+token}, payload:JSON.stringify(payload),
    muteHttpExceptions:true, followRedirects:false});
  if (response.getResponseCode() !== 200) {
    throw new Error('PQM SANDBOX: factual restore HTTP '+response.getResponseCode());
  }
  return JSON.parse(response.getContentText());
}

function pqmSandboxFactualEdrRestorePreview() {
  pqmMirrorContext_();
  var current = pqmSandboxFactualEdrNextBatch_();
  if (!current.payload) {
    console.log(JSON.stringify({dry_run:true, selected:0, remaining:0,
      scan:current.scan, db_writes:0, google_writes:0}));
    return {selected:0, received:0, scan:current.scan, db_writes:0, google_writes:0};
  }
  var records = current.payload.records;
  var result = pqmSandboxFactualEdrPost_(current.url, current.token, current.payload);
  if (result.db_writes !== 0 || result.google_writes !== 0 || result.query_only !== 1 ||
      result.received !== records.length || result.selected !== records.length ||
      result.selected > 50 || result.blocked !== 0 || result.ambiguous !== 0 ||
      !result.preview_ticket || !result.selection_digest) {
    throw new Error('PQM SANDBOX: factual restore Preview safety invariant.');
  }
  var props = PropertiesService.getScriptProperties();
  props.setProperty(PQM_FACTUAL_EDR_TICKET_PROPERTY, result.preview_ticket);
  if (props.getProperty(PQM_FACTUAL_EDR_TICKET_PROPERTY) !== result.preview_ticket) {
    throw new Error('PQM SANDBOX: Preview ticket property read-back failed.');
  }
  result.scan = current.scan;
  result.batch_apply_ready = current.scan.blocked === 0 && current.scan.ambiguous === 0 &&
    current.skipped_formula === 0 && current.skipped_invalid_pair === 0;
  console.log(JSON.stringify({dry_run:true, google_writes:0, db_writes:0,
    selected:result.selected, received:result.received, skipped_formula:current.skipped_formula,
    skipped_invalid_pair:current.skipped_invalid_pair, by_reason:result.by_reason,
    by_status_reason:result.by_status_reason, by_activity_reason:result.by_activity_reason,
    scan:current.scan, batch_apply_ready:result.batch_apply_ready,
    source_digest:result.source_digest, selection_digest:result.selection_digest,
    preview_ticket_present:!!result.preview_ticket, rows:result.rows}));
  return result;
}

/* Operator sets digest and confirmation in Script Properties after reviewing Preview. */
function pqmSandboxFactualEdrApplyPropertyStatus() {
  var props = PropertiesService.getScriptProperties();
  var status = {ticket_present:!!props.getProperty(PQM_FACTUAL_EDR_TICKET_PROPERTY),
    digest_present:!!props.getProperty(PQM_FACTUAL_EDR_DIGEST_PROPERTY),
    confirmation_valid:props.getProperty(PQM_FACTUAL_EDR_CONFIRMATION_PROPERTY) ===
      PQM_FACTUAL_EDR_BATCH_CONFIRMATION};
  console.log(JSON.stringify(status));
  return status;
}

function pqmSandboxFactualEdrControlledApply() {
  pqmMirrorContext_();
  var props = PropertiesService.getScriptProperties();
  var digest = props.getProperty(PQM_FACTUAL_EDR_DIGEST_PROPERTY) || '';
  var ticket = props.getProperty(PQM_FACTUAL_EDR_TICKET_PROPERTY) || '';
  var confirmation = props.getProperty(PQM_FACTUAL_EDR_CONFIRMATION_PROPERTY) || '';
  if (!digest || !ticket || confirmation !== PQM_FACTUAL_EDR_BATCH_CONFIRMATION) {
    throw new Error('PQM SANDBOX: explicit digest, ticket and confirmation required; no POST.');
  }
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) throw new Error('PQM SANDBOX: factual Apply locked.');
  try {
    var current = pqmSandboxFactualEdrNextBatch_(); // Fresh B/E/I/L snapshot.
    if (!current.payload) throw new Error('PQM SANDBOX: no remaining factual candidates.');
    if (current.scan.blocked || current.scan.ambiguous ||
        current.skipped_formula || current.skipped_invalid_pair) {
      throw new Error('PQM SANDBOX: factual scan has blocked identities; no Apply.');
    }
    var source = current.payload;
    var check = pqmSandboxFactualEdrPost_(current.url, current.token, source);
    if (check.db_writes !== 0 || check.google_writes !== 0 ||
        check.selection_digest !== digest ||
        check.selected !== source.records.length || check.blocked !== 0 ||
        check.ambiguous !== 0 ||
        check.new_event_needed + check.existing_event_enrichment !== source.records.length) {
      throw new Error('PQM SANDBOX: source/state changed; new Preview required.');
    }
    var applyPayload = {spreadsheet_id:source.spreadsheet_id,
      source_digest:source.source_digest, records:source.records,
      selection_digest:digest, preview_ticket:ticket, confirmation:confirmation};
    var result = pqmSandboxFactualEdrPost_(current.url.replace('/preview', '/apply'),
      current.token, applyPayload);
    if (result.google_writes !== 0 || result.verified !== source.records.length ||
        result.inserted + result.enriched !== source.records.length ||
        result.transaction_status !== 'COMMITTED') {
      throw new Error('PQM SANDBOX: factual Apply response requires manual review.');
    }
    props.deleteProperty(PQM_FACTUAL_EDR_TICKET_PROPERTY);
    props.deleteProperty(PQM_FACTUAL_EDR_DIGEST_PROPERTY);
    props.deleteProperty(PQM_FACTUAL_EDR_CONFIRMATION_PROPERTY);
    console.log(JSON.stringify(result));
    return result;
  } finally {
    lock.releaseLock();
  }
}
