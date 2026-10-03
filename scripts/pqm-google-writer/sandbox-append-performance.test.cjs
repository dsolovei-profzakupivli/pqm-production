const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = ['PqmSandboxPreviewDependencies.gs', 'PqmSandboxControlledApply.gs',
  'PqmSandboxFullApply.gs', 'PqmSandboxAppendApply.gs']
  .map(name => fs.readFileSync(path.join(__dirname, name), 'utf8')).join('\n');

function runBatch(size) {
  const context = {Date, Map, Set, console: {log() {}}};
  vm.createContext(context); vm.runInContext(source, context);
  // Exercise the same Apply implementation beyond its operational 50-row cap;
  // the production cap itself remains unchanged.
  context.PQM_SANDBOX_APPEND_MAX_ROWS = 150;
  const first = 15002, date = context.pqmGoogleDate_('2026-10-03');
  const items = Array.from({length: size}, (_, i) => ({supplier_code: String(10000000 + i)}));
  const changes = items.map((item, i) => ({tab: 'ФОП', row: first + i, append: true,
    cells: {1: item.supplier_code, 2: 'Назва ' + i, 3: 'Керівник ' + i,
      4: 'Зареєстровано', 5: 'Активний', 7: date, 8: date, 11: 'УО'}}));
  const body = {count: size, items};
  const tabs = Object.fromEntries(['ФОП', 'ЮО'].map((name, i) => [name, {
    id: i + 1, maxRows: name === 'ФОП' ? first + 150 : 15001,
    headers: [...context.PQM_GOOGLE_HEADERS], merges: [], protectedRanges: [],
    conditionalFormats: [], templateRowHeight: 30,
    rows: Array.from({length: 15000}, () => ({values: Array(15).fill(''),
      formulas: Array(15).fill(''), codeDisplay: '', dateFormat: 'dd.MM.yyyy'}))
  }]));
  const written = new Map(), calls = {fullSnapshot: 0, fullRange: 0,
    prewrite: 0, write: 0, postwrite: 0};
  let wrote = false, prompts = [];
  context.pqmGoogleSnapshot_ = () => {
    // The separate 15k-row snapshot profiler verifies 25 internal read calls.
    calls.fullSnapshot++; calls.fullRange += 25;
    return tabs;
  };
  context.pqmSandboxFetchRegistry_ = () => body;
  context.pqmGooglePlan_ = () => ({changes, counts: {appended: size, conflicts: 0,
    errors: 0, duplicate_keys: 0}});
  context.pqmSandboxFullState_ = () => ({payload_digest: 'source', google_digest: 'grid',
    changes_digest: 'changes', counts_digest: 'counts'});
  context.pqmSandboxControlledSpreadsheetId_ = () => 'SANDBOX_FIXTURE';
  context.Utilities = {DigestAlgorithm: {SHA_256: 'SHA_256'}, Charset: {UTF_8: 'UTF_8'},
    computeDigest: (_, value) => crypto.createHash('sha256').update(value).digest(),
    base64EncodeWebSafe: value => Buffer.from(value).toString('base64url')};
  context.SpreadsheetApp = {getUi: () => ({ButtonSet: {OK_CANCEL: 'OK_CANCEL'}, Button: {OK: 'OK'},
    prompt: () => ({getSelectedButton: () => 'OK', getResponseText: () => prompts.shift()})})};
  context.LockService = {getScriptLock: () => ({tryLock: () => true, releaseLock() {}})};
  function metadata(row) {
    const cells = Array.from({length: 15}, () => ({userEnteredFormat: {textFormat: {bold: false}},
      dataValidation: {condition: {type: 'TEXT_EQ'}}}));
    if (row >= first && written.has(row)) {
      cells[1].userEnteredFormat.numberFormat = {type: 'TEXT', pattern: '@'};
      for (const column of [7, 8]) cells[column].userEnteredFormat.numberFormat =
        {type: 'DATE', pattern: 'dd.MM.yyyy'};
    }
    return {values: cells, height: 30};
  }
  context.Sheets = {Spreadsheets: {
    get: (_, options) => {
      (wrote ? calls.postwrite++ : calls.prewrite++);
      if (!options.includeGridData) return {sheets: Object.entries(tabs).map(([title, tab]) =>
        ({properties: {title, sheetId: tab.id, gridProperties: {rowCount: tab.maxRows}}}))};
      const byTab = new Map();
      for (const range of options.ranges) {
        const match = /^'(ФОП|ЮО)'!A(\d+):O(\d+)$/.exec(range);
        assert.ok(match, range);
        const [, title, start, end] = match;
        if (!byTab.has(title)) byTab.set(title, {properties: {title}, data: []});
        const rows = Array.from({length: Number(end) - Number(start) + 1}, (_, i) =>
          metadata(Number(start) + i));
        byTab.get(title).data.push({startRow: Number(start) - 1, startColumn: 0,
          rowData: rows.map(row => ({values: row.values})),
          rowMetadata: rows.map(row => ({pixelSize: row.height}))});
      }
      return {sheets: [...byTab.values()]};
    },
    Values: {batchGet: (_, options) => {
      (wrote ? calls.postwrite++ : calls.prewrite++);
      return {valueRanges: options.ranges.map(range => {
        const match = /^'(ФОП|ЮО)'!(A|B)(\d+):(O|B)(\d+)$/.exec(range);
        assert.ok(match, range);
        const [, , column, start, , end] = match;
        return {values: Array.from({length: Number(end) - Number(start) + 1}, (_, i) => {
          const row = written.get(Number(start) + i) || Array(15).fill('');
          return column === 'B' ? [row[1]] : [...row];
        })};
      })};
    }},
    batchUpdate: ({requests}) => {
      calls.write++; wrote = true;
      for (const request of requests) if (request.updateCells) {
        const range = request.updateCells.range, row = range.startRowIndex + 1;
        const values = written.get(row) || Array(15).fill('');
        const entered = request.updateCells.rows[0].values[0].userEnteredValue;
        values[range.startColumnIndex] = entered.stringValue ?? entered.numberValue;
        written.set(row, values);
      }
    }
  }};
  const preview = context.pqmSandboxAppendPreview();
  // Preview and Apply are separate operations; measure the Apply invocation.
  for (const key of Object.keys(calls)) calls[key] = 0;
  prompts = [preview.append_digest, context.PQM_SANDBOX_APPEND_CONFIRMATION];
  const applied = context.pqmSandboxAppendApply();
  assert.equal(applied.verified, size);
  assert.equal(written.size, size);
  return {...calls, totalGoogleApiCalls: calls.fullRange + calls.prewrite +
    calls.write + calls.postwrite};
}

for (const size of [1, 50, 150]) test(`APPEND batch ${size} keeps Google API calls constant`, () => {
  const calls = runBatch(size);
  assert.deepEqual(calls, {fullSnapshot: 1, fullRange: 25, prewrite: 3,
    write: 1, postwrite: 4, totalGoogleApiCalls: 33});
});
