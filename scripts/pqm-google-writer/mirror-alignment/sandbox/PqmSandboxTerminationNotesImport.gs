/* SANDBOX-only controlled G/J/K/M import. Reads Google; never writes Google. */
var PQM_TERMINATION_TICKET_PROPERTY = 'PQM_TERMINATION_NOTES_PREVIEW_TICKET';
var PQM_TERMINATION_DIGEST_PROPERTY = 'PQM_TERMINATION_NOTES_APPLY_SELECTION_DIGEST';
var PQM_TERMINATION_CONFIRMATION_PROPERTY = 'PQM_TERMINATION_NOTES_APPLY_CONFIRMATION';
var PQM_TERMINATION_CONFIRMATION = 'APPLY_SANDBOX_TERMINATION_NOTES_BATCH_MAX_500';
var PQM_TERMINATION_BATCH_SIZE = 500;

function pqmSandboxTerminationNotesDigest_(records) {
  var keys = ['supplier_code', 'source_tab', 'source_row', 'g', 'j', 'k', 'm', 'formulas'];
  var rows = records.map(function(row) { return keys.map(function(key) { return row[key]; }); });
  return Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256,
    JSON.stringify(rows), Utilities.Charset.UTF_8).map(function(byte) {
      return ('0' + (byte & 255).toString(16)).slice(-2);
    }).join('');
}

function pqmSandboxTerminationNotesPayload_(spreadsheetId, records) {
  if (!records.length || records.length > PQM_TERMINATION_BATCH_SIZE) {
    throw new Error('PQM SANDBOX: termination batch bound failed; no POST.');
  }
  return {spreadsheet_id:spreadsheetId,
    source_digest:pqmSandboxTerminationNotesDigest_(records), records:records};
}

function pqmSandboxTerminationNotesPost_(url, token, payload) {
  var response = pqmMirrorFetch_(url, {method:'post', contentType:'application/json',
    headers:{Authorization:'Bearer ' + token}, payload:JSON.stringify(payload),
    muteHttpExceptions:true, followRedirects:false});
  if (response.getResponseCode() !== 200) {
    throw new Error('PQM SANDBOX: termination endpoint HTTP ' + response.getResponseCode());
  }
  return JSON.parse(response.getContentText());
}

function pqmSandboxTerminationNotesSource_() {
  var spreadsheetId = pqmSandboxControlledSpreadsheetId_();
  var registryUrl = pqmSandboxRegistryUrl_();
  if (registryUrl !== 'https://pqm-sandbox.onrender.com/api/integrations/suppliers/full-registry') {
    throw new Error('PQM SANDBOX: termination URL guard failed.');
  }
  var token = PropertiesService.getScriptProperties().getProperty(
    PQM_SANDBOX_FULL_REGISTRY_TOKEN_PROPERTY);
  if (!token) throw new Error('PQM SANDBOX: integration token missing.');
  var tabs = pqmGoogleSnapshot_(spreadsheetId), candidates = [], seen = {};
  PQM_GOOGLE_TABS.forEach(function(tab) {
    if (!tabs[tab] || JSON.stringify(tabs[tab].headers) !== JSON.stringify(PQM_GOOGLE_HEADERS)) {
      throw new Error('PQM SANDBOX: termination header mismatch.');
    }
    var byRow = {};
    tabs[tab].rows.forEach(function(row, index) {
      var code = String(row.codeDisplay || '').trim();
      if (!code) return;
      seen[code] = (seen[code] || 0) + 1;
      var values = row.values || [], day = pqmGoogleCalendarDate_(values[9]);
      var item = {supplier_code:code, source_tab:tab, source_row:index+2,
        g:String(values[6] == null ? '' : values[6]).trim(),
        j:day.kind === 'date' ? day.value : String(values[9] == null ? '' : values[9]).trim(),
        k:String(values[10] == null ? '' : values[10]).trim(),
        m:String(values[12] == null ? '' : values[12]).trim(), formulas:[]};
      if (!item.g && !item.j && !item.k && !item.m) return;
      candidates.push(item); byRow[item.source_row] = item;
    });
    var physicalLast = tabs[tab].rows.length + 1;
    for (var first=2; first<=physicalLast; first+=1000) {
      var last = Math.min(first+999, physicalLast);
      var ranges = ['G','J','K','M'].map(function(letter) {
        return "'" + tab + "'!" + letter + first + ':' + letter + last;
      });
      var response = Sheets.Spreadsheets.Values.batchGet(spreadsheetId, {
        ranges:ranges, valueRenderOption:'FORMULA'});
      if (!response.valueRanges || response.valueRanges.length !== 4) {
        throw new Error('PQM SANDBOX: termination formula read incomplete.');
      }
      response.valueRanges.forEach(function(range, column) {
        (range.values || []).forEach(function(cell, offset) {
          var item = byRow[first+offset], value = (cell || [])[0];
          if (item && typeof value === 'string' && value.charAt(0) === '=') {
            item.formulas.push(['g','j','k','m'][column]);
          }
        });
      });
    }
  });
  if (Object.keys(seen).some(function(code) { return seen[code] > 1; })) {
    throw new Error('PQM SANDBOX: duplicate Google supplier identity; no POST.');
  }
  return {spreadsheet_id:spreadsheetId, token:token,
    preview_url:registryUrl.replace('/api/integrations/suppliers/full-registry',
      '/api/integrations/google/termination-notes/preview'), candidates:candidates};
}

function pqmSandboxTerminationNotesNextBatch_() {
  var source = pqmSandboxTerminationNotesSource_();
  var selected = [], scanned = 0, equivalent = 0, blocked = 0, ambiguous = 0,
    blockedByReason = {}, blockedIdentities = [];
  for (var offset=0; offset<source.candidates.length && selected.length<500; offset+=500) {
    var window = source.candidates.slice(offset, offset+500);
    var result = pqmSandboxTerminationNotesPost_(source.preview_url, source.token,
      pqmSandboxTerminationNotesPayload_(source.spreadsheet_id, window));
    if (result.db_writes !== 0 || result.google_writes !== 0 || result.query_only !== 1 ||
        result.received !== window.length || !Array.isArray(result.rows) ||
        result.rows.length !== window.length) {
      throw new Error('PQM SANDBOX: termination scan safety invariant.');
    }
    window.forEach(function(item, index) {
      var found = result.rows[index];
      if (found.source_tab !== item.source_tab || found.source_row !== item.source_row) {
        throw new Error('PQM SANDBOX: termination scan row mismatch.');
      }
      if (found.result === 'selected') {
        if (selected.length < 500) selected.push(item);
      } else if (found.result === 'equivalent') equivalent++;
      else if (found.result.indexOf('ambiguous') === 0) {
        ambiguous++;
        blockedByReason[found.result] = (blockedByReason[found.result] || 0) + 1;
        blockedIdentities.push({source_tab:item.source_tab, source_row:item.source_row,
          supplier_code:item.supplier_code, reason:found.result});
      }
      else if (found.result === 'blocked_missing_profile' || found.result === 'blocked_formula') {
        blocked++;
        blockedByReason[found.result] = (blockedByReason[found.result] || 0) + 1;
        blockedIdentities.push({source_tab:item.source_tab, source_row:item.source_row,
          supplier_code:item.supplier_code, reason:found.result});
      } else throw new Error('PQM SANDBOX: unknown termination Preview category; no Apply.');
    });
    scanned += window.length;
  }
  source.scan = {scanned:scanned, equivalent:equivalent, blocked:blocked,
    blocked_total:blocked+ambiguous, blocked_review_count:blocked+ambiguous,
    blocked_by_reason:blockedByReason, ambiguous:ambiguous, eligible:selected.length};
  source.blocked_identities = blockedIdentities;
  source.payload = selected.length ?
    pqmSandboxTerminationNotesPayload_(source.spreadsheet_id, selected) : null;
  return source;
}

/* On-demand technical identity diagnostic; no G/J/K/M values or names. */
function pqmSandboxTerminationNotesBlockedIdentityDiagnostic() {
  var source = pqmSandboxTerminationNotesNextBatch_();
  var result = {dry_run:true, scanned:source.scan.scanned,
    blocked_total:source.scan.blocked_total,
    blocked_review_count:source.scan.blocked_review_count,
    blocked_by_reason:source.scan.blocked_by_reason,
    blocked_identities:source.blocked_identities,
    db_writes:0, google_writes:0};
  console.log(JSON.stringify(result));
  return result;
}

function pqmSandboxTerminationNotesImportPreview() {
  pqmMirrorContext_();
  var source = pqmSandboxTerminationNotesNextBatch_();
  var props = PropertiesService.getScriptProperties();
  if (!source.payload) {
    props.deleteProperty(PQM_TERMINATION_TICKET_PROPERTY);
    var empty = {selected:0, scanned:source.scan.scanned, equivalent:source.scan.equivalent,
      eligible:0, blocked:source.scan.blocked,
      blocked_total:source.scan.blocked_total,
      blocked_review_count:source.scan.blocked_review_count,
      blocked_by_reason:source.scan.blocked_by_reason, ambiguous:source.scan.ambiguous,
      remaining:0, batch_apply_ready:false,
      db_writes:0, google_writes:0};
    console.log(JSON.stringify(empty));
    return empty;
  }
  var result = pqmSandboxTerminationNotesPost_(source.preview_url, source.token, source.payload);
  if (result.db_writes !== 0 || result.google_writes !== 0 || result.query_only !== 1 ||
      result.selected !== source.payload.records.length || !result.batch_apply_ready ||
      result.blocked !== 0 || result.ambiguous !== 0 ||
      !result.preview_ticket || !result.selection_digest) {
    throw new Error('PQM SANDBOX: termination final Preview safety invariant.');
  }
  props.setProperty(PQM_TERMINATION_TICKET_PROPERTY, result.preview_ticket);
  if (props.getProperty(PQM_TERMINATION_TICKET_PROPERTY) !== result.preview_ticket) {
    throw new Error('PQM SANDBOX: ticket property read-back failed.');
  }
  result.batch_apply_ready = result.selected === source.payload.records.length &&
    result.blocked === 0 && result.ambiguous === 0;
  var summary = {selected:result.selected, scanned:source.scan.scanned,
    equivalent:source.scan.equivalent, eligible:source.scan.eligible,
    blocked:source.scan.blocked, blocked_total:source.scan.blocked_total,
    blocked_review_count:source.scan.blocked_review_count,
    blocked_by_reason:source.scan.blocked_by_reason,
    ambiguous:source.scan.ambiguous,
    writes_by_field:{G:result.field_writes.g, J:result.field_writes.j,
      K:result.field_writes.k, M:result.field_writes.m},
    complete_termination_blocks:result.complete_termination_blocks,
    partial_termination_blocks:result.partial_termination_blocks, notes:result.notes,
    selection_digest:result.selection_digest, preview_ticket_present:true,
    batch_apply_ready:result.batch_apply_ready, db_writes:0, google_writes:0};
  console.log(JSON.stringify(summary));
  return summary;
}

function pqmSandboxTerminationNotesImportApplyPropertyStatus() {
  var props = PropertiesService.getScriptProperties();
  var status = {ticket_present:!!props.getProperty(PQM_TERMINATION_TICKET_PROPERTY),
    digest_present:!!props.getProperty(PQM_TERMINATION_DIGEST_PROPERTY),
    confirmation_valid:props.getProperty(PQM_TERMINATION_CONFIRMATION_PROPERTY) ===
      PQM_TERMINATION_CONFIRMATION};
  console.log(JSON.stringify(status));
  return status;
}

function pqmSandboxTerminationNotesImportControlledApply() {
  pqmMirrorContext_();
  var props = PropertiesService.getScriptProperties();
  var ticket = props.getProperty(PQM_TERMINATION_TICKET_PROPERTY) || '';
  var digest = props.getProperty(PQM_TERMINATION_DIGEST_PROPERTY) || '';
  var confirmation = props.getProperty(PQM_TERMINATION_CONFIRMATION_PROPERTY) || '';
  if (!ticket || !digest || confirmation !== PQM_TERMINATION_CONFIRMATION) {
    throw new Error('PQM SANDBOX: ticket, digest and explicit confirmation required; no POST.');
  }
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) throw new Error('PQM SANDBOX: termination Apply locked.');
  try {
    var source = pqmSandboxTerminationNotesNextBatch_();
    if (!source.payload) {
      throw new Error('PQM SANDBOX: no clean termination batch; no Apply.');
    }
    var check = pqmSandboxTerminationNotesPost_(source.preview_url, source.token, source.payload);
    if (check.selection_digest !== digest || check.selected !== source.payload.records.length ||
        !check.batch_apply_ready || check.blocked || check.ambiguous ||
        check.db_writes !== 0 || check.google_writes !== 0) {
      throw new Error('PQM SANDBOX: termination source/state changed; new Preview required.');
    }
    var payload = {spreadsheet_id:source.payload.spreadsheet_id,
      source_digest:source.payload.source_digest, records:source.payload.records,
      selection_digest:digest, preview_ticket:ticket, confirmation:confirmation};
    var result = pqmSandboxTerminationNotesPost_(source.preview_url.replace('/preview','/apply'),
      source.token, payload);
    if (result.transaction_status !== 'COMMITTED' || result.verified !== source.payload.records.length ||
        result.updated !== source.payload.records.length || result.google_writes !== 0) {
      throw new Error('PQM SANDBOX: termination Apply result requires manual review.');
    }
    props.deleteProperty(PQM_TERMINATION_TICKET_PROPERTY);
    props.deleteProperty(PQM_TERMINATION_DIGEST_PROPERTY);
    props.deleteProperty(PQM_TERMINATION_CONFIRMATION_PROPERTY);
    console.log(JSON.stringify(result));
    return result;
  } finally {
    lock.releaseLock();
  }
}
