/* TEMPORARY READ-ONLY PROD baseline. Advanced Sheets service (Sheets v4) required.
 * No Google writes, no PQM Apply, no supplier names/officers in logs.
 * Install only after source attestation and manual review of PROD properties.
 */
var PQM_PROD_BASELINE_BATCH_MAX = 500;
var PQM_PROD_BASELINE_PROPERTY_URL = 'PQM_PROD_GOOGLE_BASELINE_URL';
var PQM_PROD_BASELINE_PROPERTY_TOKEN = 'PQM_PROD_GOOGLE_BASELINE_TOKEN';
var PQM_PROD_BASELINE_PROPERTY_SHEET = 'PQM_PROD_GOOGLE_REGISTRY_SPREADSHEET_ID';

function pqmProdBaselineCanonical_(value) {
  if (Array.isArray(value)) return value.map(pqmProdBaselineCanonical_);
  if (value && typeof value === 'object') {
    var sorted = {};
    Object.keys(value).sort().forEach(function(key) { sorted[key] = pqmProdBaselineCanonical_(value[key]); });
    return sorted;
  }
  return value;
}

function pqmProdBaselineDigest_(value) {
  var bytes = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256,
    JSON.stringify(pqmProdBaselineCanonical_(value)), Utilities.Charset.UTF_8);
  return bytes.map(function(b) { return ('0' + (b & 255).toString(16)).slice(-2); }).join('');
}

function pqmProdBaselineRows_(sheetId) {
  var response = Sheets.Spreadsheets.Values.batchGet(sheetId, {
    ranges: ["'ФОП'!B:M", "'ЮО'!B:M"], valueRenderOption: 'FORMATTED_VALUE'
  });
  var rows = [], seen = {}, ranges = response.valueRanges || [];
  ['ФОП', 'ЮО'].forEach(function(tab, index) {
    var values = ranges[index] && ranges[index].values || [];
    for (var offset = 1; offset < values.length; offset++) {
      var cells = values[offset] || [], code = String(cells[0] || '').trim();
      if (!code) continue;
      var row = {supplier_code: code, source_tab: tab, source_row: offset + 1,
        e: String(cells[3] || ''), g: String(cells[5] || ''),
        i: String(cells[7] || ''), j: String(cells[8] || ''),
        k: String(cells[9] || ''), l: String(cells[10] || ''),
        m: String(cells[11] || ''), duplicate_google_identity: false};
      rows.push(row);
      seen[code] = (seen[code] || 0) + 1;
    }
  });
  rows.forEach(function(row) { row.duplicate_google_identity = seen[row.supplier_code] > 1; });
  return rows;
}

function pqmProdBaselineMerge_(target, source) {
  Object.keys(source || {}).forEach(function(key) {
    var value = source[key];
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      if (!target[key]) target[key] = {};
      pqmProdBaselineMerge_(target[key], value);
    } else if (typeof value === 'number') {
      target[key] = (target[key] || 0) + value;
    }
  });
}

function pqmProdGoogleBaselineAudit() {
  var props = PropertiesService.getScriptProperties();
  var url = String(props.getProperty(PQM_PROD_BASELINE_PROPERTY_URL) || '').trim();
  var token = String(props.getProperty(PQM_PROD_BASELINE_PROPERTY_TOKEN) || '').trim();
  var sheetId = String(props.getProperty(PQM_PROD_BASELINE_PROPERTY_SHEET) || '').trim();
  if (!sheetId || SpreadsheetApp.getActiveSpreadsheet().getId() !== sheetId || !token ||
      !/^https:\/\/[^/?#]+\/api\/integrations\/google\/baseline\/audit$/.test(url) ||
      /sandbox/i.test(url)) throw new Error('PROD baseline configuration guard failed; no POST');
  var rows = pqmProdBaselineRows_(sheetId), aggregate = {factual_e: {}, verification: {},
    termination_notes: {}, received: 0, query_only: 1, db_writes: 0, google_writes: 0};
  for (var offset = 0; offset < rows.length; offset += PQM_PROD_BASELINE_BATCH_MAX) {
    var selected = rows.slice(offset, offset + PQM_PROD_BASELINE_BATCH_MAX);
    var payload = {spreadsheet_id: sheetId, source_digest: pqmProdBaselineDigest_(selected),
      records: selected};
    var response = UrlFetchApp.fetch(url, {method: 'post', contentType: 'application/json',
      headers: {Authorization: 'Bearer ' + token}, payload: JSON.stringify(payload),
      muteHttpExceptions: true, followRedirects: false});
    if (response.getResponseCode() !== 200) throw new Error(
      'PROD baseline batch failed at offset ' + offset + '; aggregate incomplete; no writes');
    var result = JSON.parse(response.getContentText());
    if (result.db_writes !== 0 || result.google_writes !== 0 || result.query_only !== 1 ||
        result.received !== selected.length) throw new Error('PROD baseline invariant failed');
    pqmProdBaselineMerge_(aggregate.factual_e, result.factual_e);
    pqmProdBaselineMerge_(aggregate.verification, result.verification);
    pqmProdBaselineMerge_(aggregate.termination_notes, result.termination_notes);
    aggregate.received += result.received;
  }
  if (aggregate.received !== rows.length) throw new Error('PROD baseline incomplete');
  console.log(JSON.stringify(aggregate));
  return aggregate;
}
