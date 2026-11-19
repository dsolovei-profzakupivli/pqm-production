/* SANDBOX-only Google -> PQM verification preview. No DB or Google writes. */
function pqmSandboxLegacyVerificationOfficer_(value) {
  var text = String(value == null ? '' : value).trim().replace(/\s+/g, ' ');
  if (!text || ['-', '—', 'не визначено', 'не призначено', 'невідомо', 'n/a', 'null']
      .indexOf(text.toLocaleLowerCase('uk-UA')) >= 0) return null;
  return text;
}

/* Temporary evidence for this SANDBOX migration audit only; never writer policy. */
function pqmSandboxLegacyRecentOfficerMatches_(tab, officer) {
  var expected = tab === 'ФОП' ? 'Олена ЄРЬОМІНА' :
    tab === 'ЮО' ? 'Світлана НАМЯСЕНКО' : '';
  return !!expected && officer.normalize('NFC').toLocaleLowerCase('uk-UA') ===
    expected.normalize('NFC').toLocaleLowerCase('uk-UA');
}

function pqmSandboxLegacyVerificationPreviewFrom_(body, tabs, candidateSink) {
  pqmGoogleSchema_(body);
  var output = {dry_run: true, google_writes: 0, db_writes: 0,
    candidate_event_type: 'legacy_google_registry',
    google_supplier_rows: 0, google_valid_date_officer: 0,
    google_newer_than_pqm: 0, same_date: 0, google_older: 0,
    pqm_missing_google_present: 0, planned_verification_events: 0,
    officer_only_differences: 0, duplicates_prevented: 0,
    same_date_officer: {matching_after_normalization: 0,
      pqm_blank_google_present: 0, different_nonblank: 0},
    same_date_migration_evidence: {
      differences: 0, google_expected_recent_by_tab: {'ФОП': 0, 'ЮО': 0},
      google_unexpected_recent_by_tab: {'ФОП': 0, 'ЮО': 0},
      expected_google_pqm_blank: 0, expected_google_pqm_nonblank_different: 0,
      unexpected_google_pqm_blank: 0, unexpected_google_pqm_nonblank_different: 0,
      normalization_only: 0, same_date_provenance_completion_candidates: 0,
      same_date_review_not_auto_import: 0},
    newer_google_officer: {pqm_blank_google_present: 0,
      matching_after_normalization: 0, different_nonblank: 0},
    invalid_or_ambiguous: {invalid_date: 0, missing_officer: 0,
      formula_date_or_officer: 0,
      duplicate_google_identity: 0, duplicate_pqm_identity: 0,
      missing_pqm_identity: 0, routing_mismatch: 0, invalid_pqm_date: 0},
    by_tab: {'ФОП': {candidates: 0}, 'ЮО': {candidates: 0}}};
  var google = new Map(), pqm = new Map();
  PQM_GOOGLE_TABS.forEach(function(tab) {
    if (!tabs[tab] || JSON.stringify(tabs[tab].headers) !== JSON.stringify(PQM_GOOGLE_HEADERS)) {
      throw new Error('PQM SANDBOX: Google header mismatch; no writes.');
    }
    tabs[tab].rows.forEach(function(row, rowIndex) {
      var code = String(row.codeDisplay || '').trim();
      if (!code) return;
      output.google_supplier_rows++;
      if (!google.has(code)) google.set(code, []);
      google.get(code).push({tab: tab, row: row, rowNumber: rowIndex + 2});
    });
  });
  body.items.forEach(function(item) {
    var code = item.supplier_code.trim();
    if (!pqm.has(code)) pqm.set(code, []);
    pqm.get(code).push(item);
  });
  google.forEach(function(matches, code) {
    if (matches.length !== 1) {
      output.invalid_or_ambiguous.duplicate_google_identity += matches.length;
      return;
    }
    var match = matches[0], items = pqm.get(code) || [];
    if ((match.row.formulas || [])[8] || (match.row.formulas || [])[11]) {
      output.invalid_or_ambiguous.formula_date_or_officer++;
      return;
    }
    var googleDate = pqmGoogleCalendarDate_(match.row.values[8]);
    var officer = pqmSandboxLegacyVerificationOfficer_(match.row.values[11]);
    if (googleDate.kind === 'blank') return;
    if (googleDate.kind !== 'date') {
      output.invalid_or_ambiguous.invalid_date++;
      return;
    }
    if (!officer) {
      output.invalid_or_ambiguous.missing_officer++;
      return;
    }
    output.google_valid_date_officer++;
    if (items.length !== 1) {
      output.invalid_or_ambiguous[items.length ? 'duplicate_pqm_identity' : 'missing_pqm_identity']++;
      return;
    }
    var item = items[0];
    var target = item.entity_type === 'individual_entrepreneur' ? 'ФОП' :
      item.entity_type === 'legal_entity' ? 'ЮО' : null;
    if (target !== match.tab) {
      output.invalid_or_ambiguous.routing_mismatch++;
      return;
    }
    var pqmDate = pqmGoogleCalendarDate_(item.verification_date);
    if (pqmDate.kind === 'invalid') {
      output.invalid_or_ambiguous.invalid_pqm_date++;
      return;
    }
    if (pqmDate.kind === 'blank') {
      output.pqm_missing_google_present++;
      output.planned_verification_events++;
      output.by_tab[match.tab].candidates++;
      if (candidateSink) candidateSink.push(pqmSandboxLegacyCandidate_(code, match,
        googleDate.value, officer, item));
      return;
    }
    if (googleDate.value > pqmDate.value) {
      output.google_newer_than_pqm++;
      output.planned_verification_events++;
      output.by_tab[match.tab].candidates++;
      if (candidateSink) candidateSink.push(pqmSandboxLegacyCandidate_(code, match,
        googleDate.value, officer, item));
      var priorOfficer = pqmSandboxLegacyVerificationOfficer_(item.verification_officer);
      if (!priorOfficer) output.newer_google_officer.pqm_blank_google_present++;
      else if (officer.normalize('NFC').toLocaleLowerCase('uk-UA') ===
          priorOfficer.normalize('NFC').toLocaleLowerCase('uk-UA')) {
        output.newer_google_officer.matching_after_normalization++;
      } else output.newer_google_officer.different_nonblank++;
    } else if (googleDate.value < pqmDate.value) {
      output.google_older++;
    } else {
      output.same_date++;
      output.duplicates_prevented++;
      var pqmOfficer = pqmSandboxLegacyVerificationOfficer_(item.verification_officer);
      var expectedRecent = pqmSandboxLegacyRecentOfficerMatches_(match.tab, officer);
      if (!pqmOfficer) {
        output.same_date_officer.pqm_blank_google_present++;
        output.officer_only_differences++;
      } else if (officer.normalize('NFC').toLocaleLowerCase('uk-UA') !==
          pqmOfficer.normalize('NFC').toLocaleLowerCase('uk-UA')) {
        output.same_date_officer.different_nonblank++;
        output.officer_only_differences++;
      } else {
        output.same_date_officer.matching_after_normalization++;
        if (officer !== pqmOfficer) output.same_date_migration_evidence.normalization_only++;
      }
      if (!pqmOfficer || officer.normalize('NFC').toLocaleLowerCase('uk-UA') !==
          pqmOfficer.normalize('NFC').toLocaleLowerCase('uk-UA')) {
        var evidence = output.same_date_migration_evidence;
        evidence.differences++;
        evidence[expectedRecent ? 'google_expected_recent_by_tab' :
          'google_unexpected_recent_by_tab'][match.tab]++;
        evidence[(expectedRecent ? 'expected' : 'unexpected') + '_google_pqm_' +
          (pqmOfficer ? 'nonblank_different' : 'blank')]++;
        if (expectedRecent && !pqmOfficer) evidence.same_date_provenance_completion_candidates++;
        else evidence.same_date_review_not_auto_import++;
      }
    }
  });
  return output;
}

function pqmSandboxLegacyCandidate_(code, match, date, officer, item) {
  return {supplier_code: code, source_tab: match.tab, source_row: match.rowNumber,
    verification_date: date, verification_officer: officer,
    source: 'legacy_google_registry',
    pqm_verification_date_at_export: item.verification_date || '',
    pqm_verification_officer_at_export: item.verification_officer || ''};
}

function pqmSandboxLegacySha256_(text) {
  return Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, text,
    Utilities.Charset.UTF_8).map(function(x) {
      return ('0' + (x & 255).toString(16)).slice(-2);
    }).join('');
}

function pqmSandboxLegacyPreviewItem_(item) {
  return {supplier_code: item.supplier_code, source_tab: item.source_tab,
    source_row: item.source_row, verification_date: item.verification_date,
    verification_officer: item.verification_officer, source: item.source};
}

/* Deterministic next Phase-1 batch; Google and PQM are both read fresh. */
function pqmSandboxLegacyControlledPayload_(allowEmpty) {
  var spreadsheetId = pqmSandboxControlledSpreadsheetId_();
  var registryUrl = pqmSandboxRegistryUrl_();
  if (!/^https:\/\/pqm-sandbox\.onrender\.com\/api\/integrations\/suppliers\/full-registry$/.test(registryUrl)) {
    throw new Error('PQM SANDBOX: endpoint guard failed; no POST.');
  }
  var candidates = [];
  var audit = pqmSandboxLegacyVerificationPreviewFrom_(
    pqmSandboxFetchRegistry_(), pqmGoogleSnapshot_(spreadsheetId), candidates);
  if (candidates.length !== audit.planned_verification_events) {
    throw new Error('PQM SANDBOX: candidate selection mismatch; no POST.');
  }
  candidates.sort(function(a, b) {
    return a.source_tab.localeCompare(b.source_tab) || a.source_row - b.source_row ||
      a.supplier_code.localeCompare(b.supplier_code);
  });
  var selected = candidates.slice(0, 500);
  var items = selected.map(pqmSandboxLegacyPreviewItem_).sort(function(a, b) {
    return a.source_tab.localeCompare(b.source_tab) || a.source_row - b.source_row ||
      a.supplier_code.localeCompare(b.supplier_code);
  });
  var sourceRows = items.map(function(x) {
    return [x.supplier_code, x.source_tab, x.source_row, x.verification_date,
      x.verification_officer, x.source];
  });
  var payload = {spreadsheet_id: spreadsheetId, source_digest:
    pqmSandboxLegacySha256_(JSON.stringify(sourceRows)), records: items};
  if (items.length > 500 || (!allowEmpty && !items.length)) {
    throw new Error('PQM SANDBOX: selection bound failed.');
  }
  return payload;
}

function pqmSandboxLegacyControlledPost_(path, payload) {
  var registryUrl = pqmSandboxRegistryUrl_();
  var url = registryUrl.replace(/\/api\/integrations\/suppliers\/full-registry$/, path);
  if (url === registryUrl) throw new Error('PQM SANDBOX: endpoint URL guard failed.');
  var token = PropertiesService.getScriptProperties().getProperty(
    PQM_SANDBOX_FULL_REGISTRY_TOKEN_PROPERTY);
  if (!token) throw new Error('PQM SANDBOX: integration token missing; no POST.');
  var response = pqmMirrorFetch_(url, {method: 'post', contentType: 'application/json',
    headers: {Authorization: 'Bearer ' + token}, payload: JSON.stringify(payload),
    muteHttpExceptions: true, followRedirects: false});
  if (response.getResponseCode() !== 200) {
    throw new Error('PQM SANDBOX: verification endpoint HTTP ' + response.getResponseCode());
  }
  return JSON.parse(response.getContentText());
}

/* Sends the next deterministic batch of at most 500 pairs to SANDBOX Preview. */
function pqmSandboxLegacyVerificationSendPreview() {
  pqmMirrorContext_();
  var payload = pqmSandboxLegacyControlledPayload_(true);
  if (!payload.records.length) {
    PropertiesService.getScriptProperties().deleteProperty('PQM_LEGACY_APPLY_PREVIEW_TICKET');
    var empty = {dry_run: true, selected: 0, received: 0, incoming_newer: 0,
      initial: 0, equivalent_event: 0, blocked: 0, ambiguous: 0,
      batch_apply_ready: false, db_writes: 0, google_writes: 0};
    console.log(JSON.stringify(empty));
    return empty;
  }
  var result = pqmSandboxLegacyControlledPost_(
    '/api/integrations/google/verification-events/preview', payload);
  if (result.db_writes !== 0 || result.google_writes !== 0 ||
      result.received !== payload.records.length ||
      result.selected !== result.incoming_newer + result.initial ||
      result.selected > payload.records.length ||
      !result.selection_digest ||
      !result.preview_ticket ||
      !result.current_pqm_state_digest) {
    throw new Error('PQM SANDBOX: Preview response invariant failed.');
  }
  var props = PropertiesService.getScriptProperties();
  if (result.batch_apply_ready === true && result.selected === payload.records.length) {
    props.setProperty('PQM_LEGACY_APPLY_PREVIEW_TICKET', result.preview_ticket);
  } else {
    props.deleteProperty('PQM_LEGACY_APPLY_PREVIEW_TICKET');
  }
  var safeLog = Object.assign({}, result);
  delete safeLog.preview_ticket;
  console.log(JSON.stringify(safeLog));
  return result;
}

/* Manual input in Script Properties: PQM_LEGACY_APPLY_PREVIEW_DIGEST and
   PQM_LEGACY_APPLY_CONFIRMATION. Never stores supplier or officer values. */
function pqmSandboxLegacyVerificationControlledApply() {
  var props = PropertiesService.getScriptProperties();
  var expected = props.getProperty('PQM_LEGACY_APPLY_PREVIEW_DIGEST') || '';
  var ticket = props.getProperty('PQM_LEGACY_APPLY_PREVIEW_TICKET') || '';
  var confirmation = props.getProperty('PQM_LEGACY_APPLY_CONFIRMATION') || '';
  if (!expected || !ticket || confirmation !== 'APPLY_SANDBOX_LEGACY_VERIFICATION_BATCH_MAX_500') {
    throw new Error('PQM SANDBOX: explicit digest/confirmation required; no POST.');
  }
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) throw new Error('PQM SANDBOX: controlled Apply locked.');
  try {
    // Re-snapshot B/I/L and reselect the same bounded evidence before any write request.
    var payload = pqmSandboxLegacyControlledPayload_();
    var check = pqmSandboxLegacyControlledPost_(
      '/api/integrations/google/verification-events/preview', payload);
    if (check.selection_digest !== expected || check.batch_apply_ready !== true ||
        check.incoming_newer + check.initial !== payload.records.length) {
      throw new Error('PQM SANDBOX: stale Preview or selection; no Apply POST.');
    }
    payload.selection_digest = expected;
    payload.preview_ticket = ticket;
    payload.confirmation = confirmation;
    var result = pqmSandboxLegacyControlledPost_(
      '/api/integrations/google/verification-events/apply', payload);
    if (result.selected !== payload.records.length || result.verified !== result.inserted ||
        result.failures !== 0 || result.google_writes !== 0 ||
        !['COMMITTED', 'ALREADY_APPLIED'].includes(result.transaction_status)) {
      throw new Error('PQM SANDBOX: Apply verification failed.');
    }
    console.log(JSON.stringify(result));
    return result;
  } finally {
    lock.releaseLock();
  }
}

function pqmSandboxLegacyVerificationImportPreview() {
  var spreadsheetId = pqmSandboxControlledSpreadsheetId_();
  var body = pqmSandboxFetchRegistry_();
  var tabs = pqmGoogleSnapshot_(spreadsheetId);
  var output = pqmSandboxLegacyVerificationPreviewFrom_(body, tabs);
  console.log(JSON.stringify(output));
  return output;
}
