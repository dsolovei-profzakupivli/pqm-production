const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const {spawnSync} = require('node:child_process');
const test = require('node:test');
const vm = require('node:vm');

const clone = value => JSON.parse(JSON.stringify(value));
const source = ['PqmSandboxPreviewDependencies.gs', 'PqmSandboxControlledApply.gs',
  'PqmSandboxFullApply.gs', 'PqmSandboxAppendApply.gs']
  .map(name => fs.readFileSync(path.join(__dirname, name), 'utf8')).join('\n');

function fixture() {
  const context = {Date, Map, Set, console: {log() {}}};
  vm.createContext(context); vm.runInContext(source, context);
  const tabs = Object.fromEntries(['ФОП', 'ЮО'].map((name, index) => [name, {
    id: index + 1, maxRows: 2, headers: [...context.PQM_GOOGLE_HEADERS],
    merges: [], protectedRanges: [], conditionalFormats: [], templateRowHeight: 30,
    rows: [{values: Array(15).fill(''), formulas: Array(15).fill(''), codeDisplay: '', dateFormat: 'dd.MM.yyyy'}]
  }]));
  tabs['ФОП'].rows[0].values[1] = '00000001';
  tabs['ФОП'].rows[0].codeDisplay = '00000001';
  tabs['ЮО'].rows[0].values[1] = '00000002';
  tabs['ЮО'].rows[0].codeDisplay = '00000002';
  const supplier = {supplier_code: '12345678', entity_type: 'individual_entrepreneur',
    monitoring_eligible: true, google_sync_eligible: false, supplier_name: 'Supplier',
    edr_status_current: 'Зареєстровано', prozorro_status_google: '✅ Активний',
    freshness_marker: 'fresh', last_application_date: '2026-09-20',
    google_sync_last_decided_application_date: null,
    verification_date: '2026-09-20', verification_officer: 'Officer A'};
  const body = {count: 1, items: [supplier]};
  let writes = 0, prompts = [], locked = false, requests = [];
  const metadata = new Map([['ФОП:2', {cells: Array.from({length: 15}, () => ({
    userEnteredFormat: {textFormat: {bold: false}}, dataValidation: {condition: {type: 'TEXT_EQ'}}})), height: 30}],
    ['ЮО:2', {cells: Array.from({length: 15}, () => ({
      userEnteredFormat: {textFormat: {bold: false}}, dataValidation: {condition: {type: 'TEXT_EQ'}}})), height: 30}]]);
  context.pqmSandboxFetchRegistry_ = () => clone(body);
  context.pqmGoogleSnapshot_ = () => clone(tabs);
  context.pqmSandboxControlledSpreadsheetId_ = () => 'SANDBOX_FIXTURE';
  context.Utilities = {DigestAlgorithm: {SHA_256: 'SHA_256'}, Charset: {UTF_8: 'UTF_8'},
    computeDigest: (_, value) => crypto.createHash('sha256').update(value).digest(),
    base64EncodeWebSafe: bytes => Buffer.from(bytes).toString('base64url')};
  context.SpreadsheetApp = {getUi: () => ({ButtonSet: {OK_CANCEL: 'OK_CANCEL'}, Button: {OK: 'OK'},
    prompt: () => ({getSelectedButton: () => 'OK', getResponseText: () => prompts.shift() || ''})})};
  context.LockService = {getScriptLock: () => ({tryLock: () => {if (locked) return false; locked = true; return true;},
    releaseLock: () => {locked = false;}})};
  context.Sheets = {Spreadsheets: {get: (_, options) => {
    if (!options.includeGridData) return {sheets: Object.entries(tabs).map(([title, tab]) => ({
      properties: {title, sheetId: tab.id, gridProperties: {rowCount: tab.maxRows}}}))};
    const sheets = new Map();
    for (const range of options.ranges) {
      const match = /^'(ФОП|ЮО)'!A(\d+):O(\d+)$/.exec(range);
      assert.ok(match);
      const [, title, firstRaw, lastRaw] = match;
      const first = Number(firstRaw), last = Number(lastRaw);
      if (!sheets.has(title)) sheets.set(title, {properties: {title, sheetId: tabs[title].id}, data: []});
      const states = Array.from({length: last - first + 1}, (_, index) =>
        metadata.get(title + ':' + (first + index)) || {cells: Array(15).fill({}), height: 30});
      sheets.get(title).data.push({startRow: first - 1, startColumn: 0,
        rowData: states.map(state => ({values: clone(state.cells)})),
        rowMetadata: states.map(state => ({pixelSize: state.height}))});
    }
    return {sheets: [...sheets.values()]};
  }, Values: {batchGet: (_, options) => ({valueRanges: options.ranges.map(range => {
    const match = /^'(ФОП|ЮО)'!(A|B)(\d+):(O|B)(\d+)$/.exec(range);
    assert.ok(match, range);
    const [, title, firstColumn, firstRaw, , lastRaw] = match;
    return {values: Array.from({length: Number(lastRaw) - Number(firstRaw) + 1}, (_, index) => {
      const row = tabs[title].rows[Number(firstRaw) + index - 2];
      if (firstColumn === 'B') return [row?.codeDisplay || ''];
      return clone(row?.values || Array(15).fill(''));
    })};
  })})}, batchUpdate: ({requests: batch}) => {
    writes++; requests = clone(batch);
    batch.forEach(request => {
      if (request.appendDimension) tabs['ФОП'].maxRows += request.appendDimension.length;
      if (request.copyPaste) {
        const range = request.copyPaste.destination;
        for (let i = range.startRowIndex; i < range.endRowIndex; i++) {
          while (tabs['ФОП'].rows.length <= i - 1) tabs['ФОП'].rows.push({values: Array(15).fill(''),
            formulas: Array(15).fill(''), codeDisplay: '', dateFormat: 'dd.MM.yyyy'});
          const key = 'ФОП:' + (i + 1);
          if (!metadata.has(key)) metadata.set(key, {cells: Array.from({length: 15}, () => ({})), height: 30});
          const cell = metadata.get(key).cells[range.startColumnIndex];
          const sourceCell = metadata.get('ФОП:2').cells[range.startColumnIndex];
          if (request.copyPaste.pasteType === 'PASTE_FORMAT') cell.userEnteredFormat = clone(sourceCell.userEnteredFormat);
          if (request.copyPaste.pasteType === 'PASTE_DATA_VALIDATION') cell.dataValidation = clone(sourceCell.dataValidation);
        }
      }
      if (request.updateCells) {
        const range = request.updateCells.range, column = range.startColumnIndex;
        const row = tabs['ФОП'].rows[range.startRowIndex - 1];
        const entry = request.updateCells.rows[0].values[0].userEnteredValue;
        row.values[column] = entry.stringValue ?? entry.numberValue;
        if (column === 1) row.codeDisplay = entry.stringValue;
        const meta = metadata.get('ФОП:' + (range.startRowIndex + 1));
        if (request.updateCells.rows[0].values[0].userEnteredFormat) {
          meta.cells[column].userEnteredFormat.numberFormat = clone(
            request.updateCells.rows[0].values[0].userEnteredFormat.numberFormat);
        }
      }
    });
  }}};
  return {context, tabs, body, supplier, get writes() {return writes;}, get requests() {return requests;},
    metadata,
    arm: preview => {prompts = [preview.append_digest, context.PQM_SANDBOX_APPEND_CONFIRMATION];}};
}

test('pending supplier cannot append; decision adds exactly one guarded row and next run is idempotent', () => {
  const f = fixture();
  const pending = f.context.pqmSandboxAppendPreview();
  assert.equal(pending.selected, 0);
  f.arm(pending);
  assert.throws(() => f.context.pqmSandboxAppendApply(), /stale or empty selection/);
  assert.equal(f.writes, 0);
  f.supplier.google_sync_eligible = true;
  f.supplier.google_sync_last_decided_application_date = '2026-09-20';
  const preview = f.context.pqmSandboxAppendPreview();
  assert.equal(preview.selected, 1);
  assert.equal(preview.google_writes, 0);
  f.arm(preview);
  const applied = f.context.pqmSandboxAppendApply();
  assert.equal(applied.verified, 1);
  assert.equal(f.writes, 1);
  assert.equal(f.tabs['ФОП'].rows.filter(row => row.codeDisplay === '12345678').length, 1);
  assert.equal(f.tabs['ФОП'].rows[1].values[4], 'Зареєстровано');
  assert.equal(f.tabs['ФОП'].rows[1].values[7], f.context.pqmGoogleDate_('2026-09-20'));
  assert.equal(f.tabs['ФОП'].rows[1].values[8], f.context.pqmGoogleDate_('2026-09-20'));
  assert.equal(f.tabs['ФОП'].rows[1].values[11], 'Officer A');
  assert.equal(f.context.pqmSandboxAppendPreview().selected, 0);
  assert.deepEqual([6, 9, 10, 12].map(i => f.tabs['ФОП'].rows[1].values[i]), ['', '', '', '']);
  assert.ok(f.requests.some(request => request.copyPaste && request.copyPaste.pasteType === 'PASTE_FORMAT'));
  assert.ok(f.requests.some(request => request.copyPaste && request.copyPaste.pasteType === 'PASTE_DATA_VALIDATION'));
  assert.ok(f.requests.filter(request => request.copyPaste).every(request =>
    f.context.PQM_GOOGLE_WRITE_ALLOWLIST.includes(request.copyPaste.destination.startColumnIndex) &&
    request.copyPaste.destination.endColumnIndex === request.copyPaste.destination.startColumnIndex + 1));
  assert.deepEqual([0, 6, 9, 10, 12, 13, 14].map(column => f.metadata.get('ФОП:3').cells[column]),
    Array.from({length: 7}, () => ({})));
  assert.ok(f.requests.some(request => request.updateDimensionProperties));
});

test('duplicate identity and moved Sheet row fail closed before append write', () => {
  const duplicate = fixture();
  duplicate.supplier.google_sync_eligible = true;
  duplicate.supplier.google_sync_last_decided_application_date = '2026-09-20';
  duplicate.body.items.push({...duplicate.supplier}); duplicate.body.count++;
  const duplicatePreview = duplicate.context.pqmSandboxAppendPreview();
  assert.equal(duplicatePreview.selected, 0);
  assert.equal(duplicatePreview.duplicate_keys, 1);
  assert.equal(duplicate.writes, 0);
  const moved = fixture();
  moved.supplier.google_sync_eligible = true;
  moved.supplier.google_sync_last_decided_application_date = '2026-09-20';
  const preview = moved.context.pqmSandboxAppendPreview();
  moved.tabs['ФОП'].rows[0].codeDisplay = 'MOVED';
  moved.arm(preview);
  assert.throws(() => moved.context.pqmSandboxAppendApply(), /stale/);
  assert.equal(moved.writes, 0);
});

test('append AFTER read-back rejects formatting drift and never retries an uncertain write', () => {
  const f = fixture();
  f.supplier.google_sync_eligible = true;
  f.supplier.google_sync_last_decided_application_date = '2026-09-20';
  const preview = f.context.pqmSandboxAppendPreview();
  const write = f.context.Sheets.Spreadsheets.batchUpdate;
  f.context.Sheets.Spreadsheets.batchUpdate = (...args) => {
    write(...args);
    f.metadata.get('ФОП:3').cells[5].dataValidation = null;
  };
  f.arm(preview);
  assert.throws(() => f.context.pqmSandboxAppendApply(), /validation mismatch/);
  assert.equal(f.writes, 1);
  assert.equal(f.context.pqmSandboxAppendPreview().selected, 0,
    'after uncertain read-back, new Preview observes the appended identity');
});

test('pending follow-up does not advance H and stale append digest prevents writes', () => {
  const f = fixture();
  f.supplier.google_sync_eligible = true;
  f.supplier.google_sync_last_decided_application_date = '2026-09-20';
  const preview = f.context.pqmSandboxAppendPreview();
  f.supplier.google_sync_last_decided_application_date = '2026-09-21';
  f.arm(preview);
  assert.throws(() => f.context.pqmSandboxAppendApply(), /stale/);
  assert.equal(f.writes, 0);
  f.supplier.google_sync_last_decided_application_date = '2026-09-20';
  f.supplier.last_application_date = '2026-09-25';
  const next = f.context.pqmSandboxAppendPreview();
  f.arm(next);
  f.context.pqmSandboxAppendApply();
  assert.equal(f.tabs['ФОП'].rows[1].values[7], f.context.pqmGoogleDate_('2026-09-20'));
});

test('append, daytime Google correction, evening real sync, next morning converge', () => {
  const f = fixture();
  f.supplier.google_sync_eligible = true;
  f.supplier.google_sync_last_decided_application_date = '2026-09-20';
  const preview = f.context.pqmSandboxAppendPreview(); f.arm(preview);
  f.context.pqmSandboxAppendApply();
  const row = f.tabs['ФОП'].rows[1];
  row.values[8] = f.context.pqmGoogleDate_('2026-09-25');
  row.values[11] = 'Officer B';
  row.values[6] = 'New G'; row.values[9] = '2026-09-25';
  row.values[10] = 'New K'; row.values[12] = 'New M';
  const repo = process.env.PQM_PERMANENT_REPO || path.resolve(__dirname, '../..');
  const python = process.env.PQM_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
  const bridge = path.join(repo, 'validation/local_release_20260911/daily_cycle_evening_fixture.py');
  const google = {i: '2026-09-25', l: 'Officer B', e: row.values[4],
    g: row.values[6], j: row.values[9], k: row.values[10], m: row.values[12]};
  const result = spawnSync(python, [bridge], {cwd: repo, encoding: 'utf8',
    env: {...process.env, PYTHONIOENCODING: 'utf-8'},
    input: JSON.stringify({pqm_date: '2026-09-20', pqm_officer: 'Officer A', google})});
  assert.equal(result.status, 0, result.stderr);
  const evening = JSON.parse(result.stdout);
  assert.deepEqual([evening.date, evening.officer], ['2026-09-25', 'Officer B']);
  assert.deepEqual(evening.gjkm, ['New G', '2026-09-25', 'New K', 'New M']);
  f.supplier.verification_date = evening.date;
  f.supplier.verification_officer = evening.officer;
  const plan = f.context.pqmGooglePlan_(f.body, f.context.pqmGoogleSnapshot_('SANDBOX_FIXTURE'));
  assert.equal(plan.counts.appended, 0);
  assert.ok(plan.changes.every(change => !('8' in change.cells) && !('11' in change.cells)));
});

test('append metadata verification ignores JSON key order but rejects real format drift', () => {
  const f = fixture();
  f.supplier.google_sync_eligible = true;
  f.supplier.google_sync_last_decided_application_date = '2026-09-20';
  const preview = f.context.pqmSandboxAppendPreview(); f.arm(preview);
  f.context.pqmSandboxAppendApply();
  const template = f.metadata.get('ФОП:2');
  const appended = f.metadata.get('ФОП:3');
  template.cells[2].userEnteredFormat = {textFormat: {bold: false, fontSize: 10},
    verticalAlignment: 'MIDDLE'};
  appended.cells[2].userEnteredFormat = {verticalAlignment: 'MIDDLE',
    textFormat: {fontSize: 10, bold: false}};
  const selection = [{tab: 'ФОП', row: 3, cells: {1: '12345678', 7: 1, 8: 1}}];
  const templates = {'ФОП': {cells: clone(template.cells), height: 30}};
  assert.doesNotThrow(() => f.context.pqmSandboxAppendVerifyMetadata_(
    'SANDBOX_FIXTURE', selection, templates));
  appended.cells[2].userEnteredFormat.textFormat.fontSize = 11;
  assert.throws(() => f.context.pqmSandboxAppendVerifyMetadata_(
    'SANDBOX_FIXTURE', selection, templates), /format mismatch/);
});
