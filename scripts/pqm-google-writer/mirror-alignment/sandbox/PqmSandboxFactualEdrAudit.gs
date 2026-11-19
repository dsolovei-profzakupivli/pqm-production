/* Read-only SANDBOX Google E factual evidence audit. No Google or PQM writes. */
function pqmSandboxFactualEdrAudit() {
  var spreadsheetId = pqmSandboxControlledSpreadsheetId_();
  var registryUrl = pqmSandboxRegistryUrl_();
  if (registryUrl !== 'https://pqm-sandbox.onrender.com/api/integrations/suppliers/full-registry') {
    throw new Error('PQM SANDBOX: factual EDR audit URL guard failed.');
  }
  var token = PropertiesService.getScriptProperties().getProperty(
    PQM_SANDBOX_FULL_REGISTRY_TOKEN_PROPERTY);
  if (!token) throw new Error('PQM SANDBOX: factual EDR audit token missing.');
  var tabs = pqmGoogleSnapshot_(spreadsheetId);
  var special = {'Припинено':true, 'В стані припинення':true,
    'Порушено справу про банкрутство':true, 'Банкрут':true};
  var canonical = {'Неактуально':true, 'Зареєстровано':true,
    'Припинено':true, 'В стані припинення':true,
    'Порушено справу про банкрутство':true, 'Банкрут':true};
  function semantic(value) {
    return String(value == null ? '' : value).trim().replace(/^[^\p{L}\p{N}]+/u, '').trim();
  }
  function status(value) {
    var text = semantic(value);
    if (text.indexOf('Ще не в реєстрі') !== -1) return 'Ще не в реєстрі';
    if (text.indexOf('Неактивний') !== -1) return 'Неактивний';
    if (text.indexOf('Активний') !== -1) return 'Активний';
    if (text.indexOf('Призупинений') !== -1) return 'Призупинений';
    return '';
  }
  var google = {rows:0, distinct_e:{}, unknown_e_count:0, duplicate_identity_rows:0};
  var records = [], seen = {};
  PQM_GOOGLE_TABS.forEach(function(tab) {
    if (!tabs[tab] || JSON.stringify(tabs[tab].headers) !== JSON.stringify(PQM_GOOGLE_HEADERS)) {
      throw new Error('PQM SANDBOX: factual EDR audit header mismatch.');
    }
    tabs[tab].rows.forEach(function(row, index) {
      var code = String(row.codeDisplay || '').trim();
      if (!code) return;
      google.rows++;
      seen[code] = (seen[code] || 0) + 1;
      var values = row.values || [], formulas = row.formulas || [];
      var e = semantic(values[4]) || '(blank)';
      var eBucket = canonical[e] ? e : '(other)';
      var f = status(values[5]);
      var i = pqmGoogleCalendarDate_(values[8]);
      var l = String(values[11] == null ? '' : values[11]).trim();
      var count = google.distinct_e[eBucket] || (google.distinct_e[eBucket] = {
        total:0, 'ФОП':0, 'ЮО':0, i_present:0, l_present:0, valid_i_l:0,
        active:0, inactive:0, not_in_registry:0, suspended:0, unknown_f:0});
      count.total++; count[tab]++;
      count.i_present += !!String(values[8] == null ? '' : values[8]).trim() ? 1 : 0;
      count.l_present += !!l ? 1 : 0;
      count.valid_i_l += i.kind === 'date' && !!l ? 1 : 0;
      if (f === 'Активний') count.active++;
      else if (f === 'Неактивний') count.inactive++;
      else if (f === 'Ще не в реєстрі') count.not_in_registry++;
      else if (f === 'Призупинений') count.suspended++;
      else count.unknown_f++;
      if (!canonical[e]) google.unknown_e_count++;
      if (!special[e]) return;
      if (!f) throw new Error('PQM SANDBOX: factual EDR audit unknown F status.');
      records.push({supplier_code:code, source_tab:tab, source_row:index+2,
        google_edr_status:e, google_prozorro_status:f,
        verification_date:i.kind === 'date' ? i.value : String(values[8] == null ? '' : values[8]).trim(),
        verification_officer:l,
        formulas:['e','i','l'].filter(function(field, n) { return !!formulas[[4,8,11][n]]; })});
    });
  });
  records.forEach(function(item) { if (seen[item.supplier_code] !== 1) google.duplicate_identity_rows++; });
  if (google.duplicate_identity_rows) throw new Error('PQM SANDBOX: duplicate factual EDR identity; no paired audit sent.');
  var paired = {received:0, legacy_event_db_total:null, counts:{}, by_google_factual_status:{},
    pqm_to_google_e_overwrite_risk:{}, issues:{}};
  function add(to, from) {
    Object.keys(from || {}).forEach(function(key) { to[key] = (to[key] || 0) + from[key]; });
  }
  var url = registryUrl.replace('/api/integrations/suppliers/full-registry',
    '/api/integrations/google/factual-edr/audit');
  for (var start=0; start<records.length; start+=100) {
    var batch = records.slice(start, start+100);
    var keys = ['supplier_code','source_tab','source_row','google_edr_status',
      'google_prozorro_status','verification_date','verification_officer','formulas'];
    var digestRows = batch.map(function(item) { return keys.map(function(key) { return item[key]; }); });
    var digest = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256,
      JSON.stringify(digestRows), Utilities.Charset.UTF_8).map(function(byte) {
        return ('0' + (byte & 255).toString(16)).slice(-2);
      }).join('');
    var response = pqmMirrorFetch_(url, {method:'post', contentType:'application/json',
      headers:{Authorization:'Bearer '+token}, payload:JSON.stringify({
        spreadsheet_id:spreadsheetId, source_digest:digest, records:batch}),
      muteHttpExceptions:true, followRedirects:false});
    if (response.getResponseCode() !== 200) {
      throw new Error('PQM SANDBOX: factual EDR audit HTTP '+response.getResponseCode());
    }
    var result = JSON.parse(response.getContentText());
    if (result.db_writes !== 0 || result.google_writes !== 0 || result.query_only !== 1 ||
        result.received !== batch.length || result.counts.classified !== batch.length) {
      throw new Error('PQM SANDBOX: factual EDR audit invariant.');
    }
    if (paired.legacy_event_db_total !== null &&
        paired.legacy_event_db_total !== result.legacy_event_db_total) {
      throw new Error('PQM SANDBOX: factual EDR audit ledger changed between batches.');
    }
    paired.legacy_event_db_total = result.legacy_event_db_total;
    paired.received += result.received;
    add(paired.counts, result.counts);
    add(paired.pqm_to_google_e_overwrite_risk, result.pqm_to_google_e_overwrite_risk);
    add(paired.issues, result.issues);
    Object.keys(result.by_google_factual_status || {}).forEach(function(key) {
      add(paired.by_google_factual_status[key] || (paired.by_google_factual_status[key] = {}),
        result.by_google_factual_status[key]);
    });
  }
  var output = {dry_run:true, google_writes:0, db_writes:0,
    google:google, paired:paired};
  console.log(JSON.stringify(output));
  return output;
}
