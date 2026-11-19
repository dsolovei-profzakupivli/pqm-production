const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const sourcePath = path.join(__dirname, 'PqmSandboxAppendApply.gs');
const source = fs.readFileSync(sourcePath, 'utf8');

function fixture() {
  const context = vm.createContext({
    Date, Map, Set, JSON, Object, Array, Number, String, Math, RegExp,
    PQM_GOOGLE_TABS: ['ФОП', 'ЮО'],
    Utilities: {formatDate: (_date, zone, pattern) => {
      assert.equal(zone, 'Europe/Kyiv');
      return pattern === 'Z' ? '+0200' : '2026-11-08T12:34:56';
    }},
    console: {log() {}},
  });
  context.pqmSandboxControlledDigest_ = value => crypto.createHash('sha256').update(JSON.stringify(value)).digest('base64url');
  context.pqmGoogleFreshnessFormula_ = row => `=IF(B${row}="","",TODAY())`;
  context.pqmGoogleBlank_ = value => value === '' || value === null || value === undefined;
  vm.runInContext(source, context, {filename: 'PqmSandboxAppendApply.gs'});
  return context;
}

function tab(row, maxRows = 1000) {
  return {id: row === 5 ? 1 : 2, rows: Array.from({length: row - 2}, () => ({})),
    maxRows, maxColumns: 19, formulaLocale: 'en_US', templateRowHeight: 21,
    conditionalFormats: []};
}

function rowChange(name, row, code) {
  return {tab: name, row, append: true, cells: {0: `=IF(B${row}="","",TODAY())`,
    1: code, 2: 'Synthetic supplier', 3: '', 4: 'Немає інформації', 5: '✅ Активний',
    7: 46334, 8: '', 11: 'Test officer'}};
}

test('Sandbox APPEND binds Kyiv timestamp, stable plan/run IDs, and metadata in the same batch', () => {
  const c = fixture();
  const selected = [rowChange('ФОП', 5, '0000000001'), rowChange('ЮО', 7, '0000000002')];
  const tabs = {'ФОП': tab(5), 'ЮО': tab(7)};
  const requests = c.pqmSandboxAppendRequests_(selected, tabs, {
    journaled: true, planId: 'b'.repeat(32), runId: 'a'.repeat(32),
  });
  assert.equal(selected[0].serviceMetadata.addedAt, '2026-11-08T12:34:56+02:00');
  assert.equal(selected[0].serviceMetadata.planId, 'b'.repeat(32));
  assert.equal(selected[0].serviceMetadata.runId, 'a'.repeat(32));
  assert.deepEqual(selected[1].serviceMetadata, selected[0].serviceMetadata);
  for (const change of selected) {
    for (let offset = 0; offset < 3; offset++) {
      const request = requests.find(item => item.updateCells &&
        item.updateCells.range.sheetId === tabs[change.tab].id &&
        item.updateCells.range.startRowIndex === change.row - 1 &&
        item.updateCells.range.startColumnIndex === 16 + offset);
      assert.ok(request, `metadata column ${16 + offset} is written for ${change.tab}`);
      assert.equal(request.updateCells.rows[0].values[0].userEnteredValue.stringValue,
        [change.serviceMetadata.addedAt, change.serviceMetadata.planId, change.serviceMetadata.runId][offset]);
      assert.equal(request.updateCells.rows[0].values[0].userEnteredFormat.numberFormat.pattern, '@');
    }
  }
  assert.ok(requests.some(item => item.updateCells && item.updateCells.range.startColumnIndex === 0),
    'formula A is committed with row and service metadata');
  assert.equal(requests.some(item => item.updateCells && item.updateCells.range.startColumnIndex === 15),
    false, 'the extra ЮО column P is untouched');
});

test('legacy direct writer path without a durable journal fails before constructing writes', () => {
  const c = fixture();
  assert.throws(() => c.pqmSandboxAppendRequests_([rowChange('ФОП', 5, '0000000001')],
    {'ФОП': tab(5), 'ЮО': tab(2)}), /durable run journal required/);
});

test('UPDATE entries cannot be passed to the journaled APPEND request builder', () => {
  const c = fixture();
  const update = rowChange('ФОП', 5, '0000000001'); update.append = false;
  assert.throws(() => c.pqmSandboxAppendRequests_([update], {'ФОП': tab(5), 'ЮО': tab(2)},
    {journaled: true, planId: 'b'.repeat(32), runId: 'a'.repeat(32)}), /unsafe plan; zero writes/);
});

test('service-column migration reads existing Q/R before extending and preserves extra sheet data', () => {
  const c = fixture(); let writeRequests = null, release = 0;
  c.pqmMirrorContext_ = () => ({environment: 'SANDBOX'});
  c.pqmSandboxControlledSpreadsheetId_ = () => 'sandbox-sheet';
  c.LockService = {getScriptLock: () => ({tryLock: () => true, releaseLock: () => {release++;}})};
  c.Sheets = {Spreadsheets: {
    get: (_id, options) => {
      if (!options.ranges) return {sheets: [
        {properties: {title: 'ФОП', sheetId: 1, gridProperties: {rowCount: 100, columnCount: 17}}},
        {properties: {title: 'ЮО', sheetId: 2, gridProperties: {rowCount: 100, columnCount: 18}}},
      ]};
      return {sheets: []};
    },
    Values: {batchGet: (_id, options) => {
      assert.deepEqual(Array.from(options.ranges), ["'ФОП'!Q1:Q100", "'ЮО'!Q1:R100"]);
      return {valueRanges: [{values: []}, {values: []}]};
    }},
    batchUpdate: (_body, id) => {assert.equal(id, 'sandbox-sheet');writeRequests = _body.requests;},
  }};
  c.pqmGoogleSnapshot_ = () => ({'ФОП': {id: 1, maxColumns: 19}, 'ЮО': {id: 2, maxColumns: 19}});
  c.pqmSandboxAppendServiceColumnsReady_ = () => {};
  const result = c.pqmSandboxInstallAppendServiceColumns20261108();
  assert.equal(result.status, 'INSTALLED');
  assert.equal(result.data_rows_modified, 0);
  assert.equal(writeRequests.filter(item => item.appendDimension).length, 2);
  const headers = writeRequests.filter(item => item.updateCells);
  assert.equal(headers.length, 2);
  assert.ok(headers.every(item => item.updateCells.range.startColumnIndex === 16 &&
    item.updateCells.range.endColumnIndex === 19));
  assert.ok(headers.every(item => item.updateCells.fields.includes('userEnteredFormat.textFormat.bold')));
  assert.equal(release, 1);
});
