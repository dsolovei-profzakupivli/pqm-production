/* Environment-only safety. No settings, triggers or business data are mutated. */
var PQM_MIRROR_ENV = Object.freeze({"environment":"PROD","scriptId":"1TPR8GjoKeiWIlMJkXKpSM2X4rJrq8hIlFqMBn5kzyzurRbZPD_GZQOd6","spreadsheetId":"1rqghaEduW8Aer4ri36aysMurEdK2UH5laXKw_Oo1FKA","apiBase":"https://pqm-production-1.onrender.com","prefix":"pqmProd","writerPrefix":"pqmProd"});
var PQM_EXECUTION_CONTEXT_ = null;
function pqmMirrorContext_() {
  if (typeof ScriptApp === 'undefined' || ScriptApp.getScriptId() !== PQM_MIRROR_ENV.scriptId)
    throw new Error('PQM: script environment identity mismatch; zero writes.');
  var active = PQM_EXECUTION_CONTEXT_ ? PQM_EXECUTION_CONTEXT_.spreadsheet : SpreadsheetApp.getActiveSpreadsheet();
  if (!active || active.getId() !== PQM_MIRROR_ENV.spreadsheetId)
    throw new Error('PQM: spreadsheet environment identity mismatch; zero writes.');
  return PQM_MIRROR_ENV;
}
function pqmMirrorSpreadsheetId_(id) {
  var cfg = pqmMirrorContext_();
  if (String(id || '') !== cfg.spreadsheetId)
    throw new Error('PQM: cross-environment destination rejected; zero writes.');
  return cfg.spreadsheetId;
}
function pqmMirrorOpenById_(id) {
  return SpreadsheetApp.openById(pqmMirrorSpreadsheetId_(id));
}
function pqmMirrorSheet_(sheet) {
  if (!sheet || typeof sheet.getParent !== 'function')
    throw new Error('PQM: sheet identity unavailable; zero writes.');
  pqmMirrorSpreadsheetId_(sheet.getParent().getId());
  return sheet;
}
function pqmMirrorRange_(range) {
  if (!range || typeof range.getSheet !== 'function')
    throw new Error('PQM: range identity unavailable; zero writes.');
  pqmMirrorSheet_(range.getSheet());
  return range;
}
function pqmMirrorEvent_(event) {
  pqmMirrorContext_();
  if (event && event.source) pqmMirrorSpreadsheetId_(event.source.getId());
  if (event && event.range) pqmMirrorRange_(event.range);
}
function pqmMirrorSheetsBatchUpdate_(body, id) {
  return Sheets.Spreadsheets.batchUpdate(body, pqmMirrorSpreadsheetId_(id));
}
function pqmMirrorValuesBatchUpdate_(body, id) {
  return Sheets.Spreadsheets.Values.batchUpdate(body, pqmMirrorSpreadsheetId_(id));
}
function pqmMirrorFetch_(url, options) {
  var cfg = pqmMirrorContext_();
  if (typeof url !== 'string' || url.indexOf(cfg.apiBase + '/api/') !== 0)
    throw new Error('PQM: cross-environment API rejected; zero writes.');
  var safeOptions = Object.assign({}, options || {}, {followRedirects: false});
  return UrlFetchApp.fetch(url, safeOptions);
}
