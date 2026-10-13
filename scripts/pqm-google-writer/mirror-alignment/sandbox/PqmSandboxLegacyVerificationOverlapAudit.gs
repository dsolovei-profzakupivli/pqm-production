/* Manual SANDBOX read-only paired B/I/L audit. Install only after backend audit deploy. */
function pqmSandboxLegacyVerificationOverlapAudit() {
  var spreadsheetId = pqmSandboxControlledSpreadsheetId_();
  var tabs = pqmGoogleSnapshot_(spreadsheetId);
  var identities = [], records = [];
  PQM_GOOGLE_TABS.forEach(function(tab) {
    if (!tabs[tab] || JSON.stringify(tabs[tab].headers) !== JSON.stringify(PQM_GOOGLE_HEADERS)) {
      throw new Error('PQM SANDBOX: Google header mismatch; no POST.');
    }
    tabs[tab].rows.forEach(function(row, index) {
      var code = String(row.codeDisplay || '').trim();
      if (!code) return;
      var identity = {supplier_code: code, source_tab: tab, source_row: index + 2};
      identities.push(identity);
      if ((row.formulas || [])[8] || (row.formulas || [])[11]) return;
      var day = pqmGoogleCalendarDate_(row.values[8]);
      var officer = pqmSandboxLegacyVerificationOfficer_(row.values[11]);
      if (day.kind === 'date' && officer) {
        records.push({supplier_code: code, source_tab: tab, source_row: index + 2,
          verification_date: day.value, verification_officer: officer});
      }
    });
  });
  function order(a, b) {
    return a.source_tab.localeCompare(b.source_tab, 'uk') || a.source_row - b.source_row ||
      a.supplier_code.localeCompare(b.supplier_code);
  }
  identities.sort(order); records.sort(order);
  var raw = {identities: identities.map(function(x) {
    return [x.supplier_code, x.source_tab, x.source_row];
  }), records: records.map(function(x) {
    return [x.supplier_code, x.source_tab, x.source_row,
      x.verification_date, x.verification_officer];
  })};
  var payload = {spreadsheet_id: spreadsheetId,
    source_digest: pqmSandboxLegacySha256_(JSON.stringify(raw)),
    identities: identities, records: records};
  if (!identities.length || identities.length > 20000 || records.length > 20000) {
    throw new Error('PQM SANDBOX: overlap audit size guard; no POST.');
  }
  var registryUrl = pqmSandboxRegistryUrl_();
  var url = registryUrl.replace(/\/api\/integrations\/suppliers\/full-registry$/,
    '/api/integrations/google/verification-events/overlap-audit');
  if (url === registryUrl) throw new Error('PQM SANDBOX: endpoint URL guard; no POST.');
  var token = PropertiesService.getScriptProperties().getProperty(
    PQM_SANDBOX_FULL_REGISTRY_TOKEN_PROPERTY);
  if (!token) throw new Error('PQM SANDBOX: integration token missing; no POST.');
  var response = pqmMirrorFetch_(url, {method: 'post', contentType: 'application/json',
    headers: {Authorization: 'Bearer ' + token}, payload: JSON.stringify(payload),
    muteHttpExceptions: true, followRedirects: false});
  if (response.getResponseCode() !== 200) {
    throw new Error('PQM SANDBOX: overlap audit HTTP ' + response.getResponseCode());
  }
  var result = JSON.parse(response.getContentText());
  if (result.db_writes !== 0 || result.google_writes !== 0 || result.query_only !== 1 ||
      result.source_digest !== payload.source_digest || !result.counts ||
      result.counts.google_supplier_rows !== identities.length ||
      result.counts.google_valid_date_officer !== records.length) {
    throw new Error('PQM SANDBOX: overlap audit response invariant failed.');
  }
  console.log(JSON.stringify(result));
  return result;
}
