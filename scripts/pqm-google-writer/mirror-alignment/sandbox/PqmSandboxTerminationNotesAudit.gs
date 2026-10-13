/* SANDBOX-only, read-only paired audit of Google G/J/K/M against PQM profiles. */
function pqmSandboxTerminationNotesAudit() {
  var spreadsheetId = pqmSandboxControlledSpreadsheetId_();
  var registryUrl = pqmSandboxRegistryUrl_();
  if (!/^https:\/\/pqm-sandbox\.onrender\.com\/api\/integrations\/suppliers\/full-registry$/.test(registryUrl)) {
    throw new Error('PQM SANDBOX: audit endpoint guard failed.');
  }
  var token = PropertiesService.getScriptProperties().getProperty(
    PQM_SANDBOX_FULL_REGISTRY_TOKEN_PROPERTY);
  if (!token) throw new Error('PQM SANDBOX: audit token missing.');
  var tabs = pqmGoogleSnapshot_(spreadsheetId);
  var all = [], seenRows = {};
  PQM_GOOGLE_TABS.forEach(function(tab) {
    if (!tabs[tab] || JSON.stringify(tabs[tab].headers) !== JSON.stringify(PQM_GOOGLE_HEADERS)) {
      throw new Error('PQM SANDBOX: audit header mismatch.');
    }
    tabs[tab].rows.forEach(function(row, index) {
      var code = String(row.codeDisplay || '').trim();
      if (!code) return;
      var number = index + 2, key = tab + ':' + number;
      if (seenRows[key]) throw new Error('PQM SANDBOX: duplicate audit row.');
      seenRows[key] = true;
      var values = row.values || [], formulas = row.formulas || [];
      var j = pqmGoogleCalendarDate_(values[9]);
      all.push({supplier_code: code, source_tab: tab, source_row: number,
        g: String(values[6] == null ? '' : values[6]).trim(),
        j: j.kind === 'date' ? j.value : String(values[9] == null ? '' : values[9]).trim(),
        k: String(values[10] == null ? '' : values[10]).trim(),
        m: String(values[12] == null ? '' : values[12]).trim(),
        formulas: ['g', 'j', 'k', 'm'].filter(function(field, offset) {
          return !!formulas[[6, 9, 10, 12][offset]];
        })});
    });
  });
  var googleRows = all.length, codeCounts = {};
  all.forEach(function(x) { codeCounts[x.supplier_code] = (codeCounts[x.supplier_code] || 0) + 1; });
  var duplicateRows = all.filter(function(x) { return codeCounts[x.supplier_code] > 1; }).length;
  all = all.filter(function(x) { return codeCounts[x.supplier_code] === 1; });
  // The writer snapshot does not populate formula metadata for G/J/K/M.
  // Read these columns explicitly, then clarify only cells whose FORMULA value starts '='.
  PQM_GOOGLE_TABS.forEach(function(tab) {
    var tabRows = all.filter(function(x) { return x.source_tab === tab; });
    if (!tabRows.length) return;
    var maxRow = tabRows[tabRows.length - 1].source_row;
    var byRow = {};
    tabRows.forEach(function(x) { byRow[x.source_row] = x; });
    for (var first = 2; first <= maxRow; first += 1000) {
      var last = Math.min(maxRow, first + 999);
      var ranges = ['G', 'J', 'K', 'M'].map(function(letter) {
        return "'" + tab + "'!" + letter + first + ':' + letter + last;
      });
      var response = Sheets.Spreadsheets.Values.batchGet(spreadsheetId, {
        ranges: ranges, valueRenderOption: 'FORMULA'});
      if (!response.valueRanges || response.valueRanges.length !== 4) {
        throw new Error('PQM SANDBOX: audit formula read incomplete.');
      }
      response.valueRanges.forEach(function(range, index) {
        (range.values || []).forEach(function(cell, offset) {
          var value = (cell || [])[0], item = byRow[first + offset];
          if (!item || typeof value !== 'string' || value.charAt(0) !== '=') return;
          var field = ['g', 'j', 'k', 'm'][index];
          var grid = Sheets.Spreadsheets.get(spreadsheetId, {
            ranges: [ranges[index].split(':')[0].replace(/[0-9]+$/, first + offset) + ':' +
              ranges[index].split(':')[0].replace(/[0-9]+$/, first + offset)],
            includeGridData: true,
            fields: 'sheets(data(rowData(values(userEnteredValue(formulaValue,stringValue)))))'});
          var data = (((grid.sheets || [])[0] || {}).data || [])[0] || {};
          var entered = (((data.rowData || [])[0] || {}).values || [])[0] || {};
          if ((entered.userEnteredValue || {}).formulaValue) item.formulas.push(field);
        });
      });
    }
  });
  var totals = {dry_run: true, google_writes: 0, db_writes: 0, google_rows: googleRows,
    compared: 0, fields: {}, termination_group: {},
    issues: {duplicate_google_identity_rows: duplicateRows}, target_2791715838: null};
  var url = registryUrl.replace(/\/api\/integrations\/suppliers\/full-registry$/,
    '/api/integrations/google/termination-notes/audit');
  function add(target, source) {
    Object.keys(source || {}).forEach(function(key) { target[key] = (target[key] || 0) + source[key]; });
  }
  for (var start = 0; start < all.length; start += 100) {
    var records = all.slice(start, start + 100);
    var rows = records.map(function(x) {
      return [x.supplier_code, x.source_tab, x.source_row, x.g, x.j, x.k, x.m, x.formulas];
    });
    var sourceDigest = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256,
      JSON.stringify(rows), Utilities.Charset.UTF_8).map(function(x) {
        return ('0' + (x & 255).toString(16)).slice(-2);
      }).join('');
    var response = pqmMirrorFetch_(url, {method: 'post', contentType: 'application/json',
      headers: {Authorization: 'Bearer ' + token}, payload: JSON.stringify({
        spreadsheet_id: spreadsheetId, source_digest: sourceDigest, records: records}),
      muteHttpExceptions: true, followRedirects: false});
    if (response.getResponseCode() !== 200) {
      throw new Error('PQM SANDBOX: audit HTTP ' + response.getResponseCode() +
        '; partial aggregate discarded.');
    }
    var result = JSON.parse(response.getContentText());
    if (result.db_writes !== 0 || result.google_writes !== 0 || result.query_only !== 1 ||
        result.received !== records.length) throw new Error('PQM SANDBOX: audit safety invariant.');
    totals.compared += result.compared;
    Object.keys(result.fields || {}).forEach(function(field) {
      add(totals.fields[field] || (totals.fields[field] = {}), result.fields[field]);
    });
    add(totals.termination_group, result.termination_group);
    add(totals.issues, result.issues);
    if (result.target_2791715838) totals.target_2791715838 = result.target_2791715838;
  }
  console.log(JSON.stringify(totals));
  return totals;
}
