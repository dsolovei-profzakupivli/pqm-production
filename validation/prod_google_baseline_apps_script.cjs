const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const crypto = require('node:crypto');
const source = fs.readFileSync('scripts/prod-google-baseline/PqmProdGoogleBaselineAudit.gs', 'utf8');
const sent = [], logs = [];
const props = {
  PQM_PROD_GOOGLE_BASELINE_URL: 'https://pqm-production-1.onrender.com/api/integrations/google/baseline/audit',
  PQM_PROD_GOOGLE_BASELINE_TOKEN: 'fixture-token',
  PQM_PROD_GOOGLE_REGISTRY_SPREADSHEET_ID: 'prod-registry',
};
const values = [
  Array.from({length: 503}, (_, i) => i === 0 ? ['B', 'C'] :
    [String(i), '', '', 'Припинено', '', 'private-decision', '', '04.09.2026',
      '02.09.2026', 'private-record', 'private-officer', 'private-note']),
  [['B', 'C'], ['900', '', '', 'Зареєстровано']],
];
const context = {
  PropertiesService: {getScriptProperties: () => ({getProperty: k => props[k]})},
  SpreadsheetApp: {getActiveSpreadsheet: () => ({getId: () => 'prod-registry'})},
  Sheets: {Spreadsheets: {Values: {batchGet: () => ({valueRanges: values.map(v => ({values: v}))})}}},
  Utilities: {DigestAlgorithm: {SHA_256: 'SHA256'}, Charset: {UTF_8: 'UTF8'},
    computeDigest: (_, text) => [...crypto.createHash('sha256').update(text).digest()].map(b => b > 127 ? b - 256 : b)},
  UrlFetchApp: {fetch: (_, req) => {
    const body = JSON.parse(req.payload);
    sent.push(body);
    const canonical = value => Array.isArray(value) ? value.map(canonical) : value && typeof value === 'object' ?
      Object.fromEntries(Object.keys(value).sort().map(k => [k, canonical(value[k])])) : value;
    assert.equal(body.source_digest,
      crypto.createHash('sha256').update(JSON.stringify(canonical(body.records))).digest('hex'));
    return {getResponseCode: () => 200, getContentText: () => JSON.stringify({
      factual_e: {google_status_counts: {'Припинено': body.records.length}},
      verification: {google_supplier_rows: body.records.length}, termination_notes: {},
      received: body.records.length, query_only: 1, db_writes: 0, google_writes: 0})};
  }},
  console: {log: text => logs.push(text)},
};
vm.runInNewContext(source, context);
const result = context.pqmProdGoogleBaselineAudit();
assert.deepEqual(sent.map(x => x.records.length), [500, 3]);
assert.equal(result.received, 503);
assert.equal(result.verification.google_supplier_rows, 503);
assert.ok(logs.every(x => !/private-decision|private-record|private-officer|private-note/.test(x)));
assert.equal(source.includes('batchUpdate'), false);
assert.equal(source.includes('Apply('), false);
props.PQM_PROD_GOOGLE_BASELINE_TOKEN = '';
assert.throws(() => context.pqmProdGoogleBaselineAudit(), /configuration guard/);
assert.equal(sent.length, 2);
process.stdout.write('PROD baseline Apps Script candidate: 2 bounded batches, aggregate-only, no writes OK\n');
