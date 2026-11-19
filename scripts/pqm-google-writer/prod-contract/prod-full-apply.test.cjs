const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');
const path = require('node:path');
const {spawnSync} = require('node:child_process');

const source = ['PqmProdPreviewDependencies.gs', 'PqmProdPreview.gs',
  'PqmProdControlledApply.gs', 'PqmProdFullApply.gs']
  .map(name => fs.readFileSync(__dirname + '/' + name, 'utf8')).join('\n');
const clone = value => JSON.parse(JSON.stringify(value));
function response(text) { return {getSelectedButton: () => 'OK', getResponseText: () => text}; }

function fixture() {
  const logs = [], context = {console: {log: text => logs.push(text)}, Date, Map, Set};
  vm.createContext(context);
  vm.runInContext(source, context);
  context.PQM_PROD_CONTROLLED_SPREADSHEET_ID = 'synthetic-prod';
  const tabs = Object.fromEntries(['ФОП', 'ЮО'].map((name, index) => [name, {
    id: index + 1, maxRows: 40, headers: Array.from(context.PQM_GOOGLE_HEADERS),
    merges: [], protectedRanges: [], conditionalFormats: [], templateRowHeight: 28, rows: []
  }]));
  const body = {count: 8, items: []}, raw = new Map();
  const serial = context.pqmGoogleDate_('2026-09-22');
  for (let i = 0; i < 8; i++) {
    const name = i < 4 ? 'ФОП' : 'ЮО', tab = tabs[name];
    const code = name === 'ФОП' ? String(1000000000 + i) : String(10000000 + i);
    const row = tab.rows.length + 2;
    const values = Array(15).fill('');
    values[0] = 'old'; values[1] = code; values[2] = 'old-name';
    values[5] = 'old-status'; values[7] = serial - 1;
    values[8] = '2026-09-21'; values[11] = 'Officer';
    tab.rows.push({values, formulas: Array(15).fill(''), codeDisplay: code, dateFormat: 'dd.MM.yyyy'});
    body.items.push({supplier_code: code, entity_type: name === 'ФОП' ? 'individual_entrepreneur' : 'legal_entity',
      monitoring_eligible: true, google_sync_eligible: true,
      freshness_marker: 'fresh', current_manager_name: null, supplier_name: 'verified-name',
      edr_status_current: null, verification_date: '2026-09-22', verification_officer: 'Officer',
      prozorro_status_google: 'Active', last_application_date: '2026-09-22',
      google_sync_last_decided_application_date: '2026-09-22'});
    raw.set(tab.id + ':' + row, values.map((value, column) => {
      const v = typeof value === 'number' ? {numberValue: value} : {stringValue: value};
      const cell = {userEnteredValue: clone(v), effectiveValue: clone(v), formattedValue: String(value)};
      if (column === 7) cell.userEnteredFormat = {numberFormat: {type: 'DATE', pattern: 'dd.MM.yyyy'}};
      return cell;
    }));
  }
  let writes = 0, requests = [], reads = 0, fetches = 0, snapshots = 0, beforeRead = null, afterWrite = null;
  let prompts = [], confirmation = 'NO', released = 0, locked = false;
  context.PQM_PROD_FULL_CHUNK_MAX_CELLS = 4;
  context.PQM_PROD_FULL_CHUNK_MAX_ROWS = 2;
  context.pqmProdFetchRegistry_ = () => { fetches++; return clone(body); };
  context.pqmProdRegistryUrl_ = () => 'https://pqm-sandbox.onrender.com/api/integrations/suppliers/full-registry';
  context.pqmGoogleSnapshot_ = () => {
    snapshots++;
    const result = clone(tabs);
    Object.values(result).forEach(tab => tab.rows.forEach((row, index) => {
      const cells = raw.get(tab.id + ':' + (index + 2));
      row.values = cells.map(cell => {
        const v = cell.effectiveValue || {};
        return v.stringValue !== undefined ? v.stringValue : v.numberValue !== undefined ? v.numberValue : '';
      });
      row.formulas = cells.map(cell => (cell.userEnteredValue || {}).formulaValue || '');
      row.codeDisplay = cells[1].formattedValue;
      row.dateFormat = ((cells[7].userEnteredFormat || {}).numberFormat || {}).pattern || '';
      row.verificationDateFormat = ((cells[8].userEnteredFormat || {}).numberFormat || {}).pattern || '';
    }));
    return result;
  };
  context.Utilities = {DigestAlgorithm: {SHA_256: 'SHA_256'}, Charset: {UTF_8: 'UTF_8'},
    computeDigest: (_, value) => crypto.createHash('sha256').update(value).digest(),
    base64EncodeWebSafe: buffer => Buffer.from(buffer).toString('base64url')};
  context.SpreadsheetApp = {
    getActiveSpreadsheet: () => ({getId: () => context.PQM_PROD_CONTROLLED_SPREADSHEET_ID}),
    getUi: () => ({ButtonSet: {OK_CANCEL: 'OK_CANCEL', YES_NO: 'YES_NO'}, Button: {OK: 'OK', YES: 'YES'},
      prompt: () => prompts.shift() || {getSelectedButton: () => 'CANCEL'}, alert: () => confirmation})
  };
  context.LockService = {getScriptLock: () => ({
    tryLock: () => {if (locked) return false; locked = true; return true;},
    releaseLock: () => {locked = false; released++;}
  })};
  context.Sheets = {Spreadsheets: {
    get: (_, options) => {
      reads++;
      if (beforeRead) beforeRead(reads);
      const grouped = new Map();
      options.ranges.forEach(range => {
        const match = /^'(ФОП|ЮО)'!A(\d+):O\2$/.exec(range);
        assert.ok(match, 'targeted A:O row read only');
        const tab = tabs[match[1]], row = Number(match[2]);
        if (!grouped.has(tab.id)) grouped.set(tab.id, []);
        grouped.get(tab.id).push({startRow: row - 1,
          rowData: [{values: clone(raw.get(tab.id + ':' + row))}]});
      });
      return {sheets: [...grouped].map(([id, data]) => ({properties: {sheetId: id}, data}))};
    },
    batchUpdate: ({requests: next}) => {
      writes++; requests.push(clone(next));
      next.forEach(request => {
        assert.deepEqual(Object.keys(request), ['updateCells']);
        const update = request.updateCells, range = update.range;
        assert.ok([2, 3, 4, 5, 7, 8, 11].includes(range.startColumnIndex));
        const cell = raw.get(range.sheetId + ':' + (range.startRowIndex + 1))[range.startColumnIndex];
        cell.userEnteredValue = clone(update.rows[0].values[0].userEnteredValue);
        cell.effectiveValue = clone(cell.userEnteredValue);
        cell.formattedValue = String(cell.userEnteredValue.stringValue ?? cell.userEnteredValue.numberValue);
        if (range.startColumnIndex === 7 || range.startColumnIndex === 8) {
          cell.userEnteredFormat = clone(update.rows[0].values[0].userEnteredFormat);
        }
      });
      if (afterWrite) afterWrite(writes);
    }
  }};
  return {context, body, tabs, raw, logs, requests,
    get writes() {return writes;}, get reads() {return reads;}, get fetches() {return fetches;},
    get snapshots() {return snapshots;},
    get released() {return released;}, setPrompts: list => {prompts = list;},
    confirm: value => {confirmation = value;}, beforeRead: hook => {beforeRead = hook;},
    afterWrite: hook => {afterWrite = hook;}};
}

function arm(f, preview) {
  f.setPrompts([response(preview.plan_digest)]);
  f.confirm('YES');
}

function setGoogleCell(f, column, value) {
  const cell = f.raw.get('1:2')[column];
  const entered = typeof value === 'number' ? {numberValue: value} : {stringValue: value};
  cell.userEnteredValue = clone(entered);
  cell.effectiveValue = clone(entered);
  cell.formattedValue = String(value);
  if (column === 8) cell.userEnteredFormat = {numberFormat: {type: 'DATE', pattern: 'dd.MM.yyyy'}};
}

test('invalid Google/PQM verification dates fail closed before any write', () => {
  for (const origin of ['Google', 'PQM']) {
    const f = fixture();
    f.body.items[0].verification_date = origin === 'PQM' ? 'bad-date' : '2026-09-20';
    f.body.items[0].verification_officer = 'Officer A';
    setGoogleCell(f, 8, origin === 'Google' ? 'bad-date' : f.context.pqmGoogleDate_('2026-09-19'));
    assert.throws(() => f.context.pqmProdFullApplyPreview(), /BLOCKED_/);
    assert.equal(f.writes, 0);
  }
});

test('four Apps Script sources parse together; Full Preview is aggregate-only and zero-write', () => {
  const f = fixture(), p = f.context.pqmProdFullApplyPreview();
  assert.equal(p.google_writes, 0);
  assert.equal(p.total_pqm_suppliers, 8);
  assert.equal(p.matched, 8);
  assert.equal(p.skipped, 0);
  assert.equal(p.appended + p.conflicts + p.duplicate_keys + p.errors, 0);
  assert.equal(p.total_planned_cells, 32);
  assert.deepEqual(Object.fromEntries(Object.entries(p.changes_by_column)), {C: 8, D: 0, E: 0, F: 8, H: 8, I: 8, L: 0});
  assert.equal(f.writes, 0);
  assert.equal(JSON.stringify(p).includes('verified-name'), false);
  assert.equal(JSON.stringify(p).includes(f.body.items[0].supplier_code), false);
});

test('expanded impact Preview is aggregate-only, zero-write and exposes blockers', () => {
  const f = fixture();
  f.body.items[0].edr_status_current = 'Зареєстровано';
  f.body.items[0].verification_date = '2026-09-23';
  f.body.items[0].verification_officer = 'verified officer';
  const impact = f.context.pqmProdExpandedImpactPreview();
  assert.deepEqual(Object.fromEntries(Object.entries(impact.changes_by_column)),
    {C: 8, D: 0, E: 0, F: 8, H: 8, I: 8, L: 1});
  assert.equal(impact.total_planned_matched_cells, 33);
  assert.equal(impact.a_writes, 0);
  assert.equal(impact.formulas_touched, 0);
  assert.equal(impact.full_apply_blocked, false);
  assert.equal(f.writes, 0);
  assert.equal(JSON.stringify(impact).includes('verified officer'), false);
  f.body.items.push({...f.body.items[0], supplier_code: 'new-supplier'});
  f.body.count++;
  assert.equal(f.context.pqmProdExpandedImpactPreview().full_apply_blocked, true);
  assert.equal(f.writes, 0);
});

test('full preview blocks append, conflict, duplicate and planner error', () => {
  const types = ['appended', 'conflicts', 'duplicate_keys', 'errors'];
  types.forEach(type => {
    const f = fixture(), original = f.context.pqmGooglePlan_;
    f.context.pqmGooglePlan_ = (body, tabs) => {
      const p = original(body, tabs); p.counts[type]++; return p;
    };
    assert.throws(() => f.context.pqmProdFullApplyPreview(), /BLOCKED_/);
    assert.equal(f.writes, 0);
  });
});

test('cancelled confirmation and stale digest cause zero writes', () => {
  const f = fixture(), p = f.context.pqmProdFullApplyPreview();
  f.setPrompts([response(p.plan_digest)]);
  assert.equal(f.context.pqmProdFullApply().google_writes, 0);
  f.setPrompts([response('x'.repeat(43))]); f.confirm('YES');
  assert.throws(() => f.context.pqmProdFullApply(), /PLAN_OR_GOOGLE_STATE_CHANGED/);
  assert.equal(f.writes, 0);
});

test('current PQM payload drift invalidates the old Preview before first write', () => {
  const f = fixture(), preview = f.context.pqmProdFullApplyPreview();
  f.body.items[0].supplier_name = 'different';
  arm(f, preview);
  assert.throws(() => f.context.pqmProdFullApply(), /PLAN_OR_GOOGLE_STATE_CHANGED/);
  assert.equal(f.writes, 0);
});

test('same full business state yields a deterministic digest despite generated_at', () => {
  const f = fixture();
  f.body.generated_at = 'first';
  const a = f.context.pqmProdFullApplyPreview();
  f.body.generated_at = 'second';
  const b = f.context.pqmProdFullApplyPreview();
  assert.equal(a.plan_digest, b.plan_digest);
  assert.equal(f.writes, 0);
});

test('freshness-marker-only PQM change does not alter Full Preview or create A writes', () => {
  const f = fixture(), before = f.context.pqmProdFullApplyPreview();
  f.body.items[0].freshness_marker = 'different';
  const after = f.context.pqmProdFullApplyPreview();
  assert.equal(after.plan_digest, before.plan_digest);
  assert.equal(after.total_planned_cells, before.total_planned_cells);
  assert.equal(Object.hasOwn(after.changes_by_column, 'A'), false);
  assert.equal(f.writes, 0);
});

test('state change before first chunk causes zero writes', () => {
  const f = fixture(), p = f.context.pqmProdFullApplyPreview();
  const cell = f.raw.get('1:2')[0];
  f.beforeRead(n => {if (n === 1) {cell.userEnteredValue.stringValue = 'edited'; cell.effectiveValue.stringValue = 'edited';}});
  arm(f, p);
  const report = f.context.pqmProdFullApply();
  assert.equal(report.status, 'CHUNK_FAILED_NEW_PREVIEW_REQUIRED');
  assert.equal(report.cells_written, 0);
  assert.equal(f.writes, 0);
});

test('state change between chunks stops remaining writes', () => {
  const f = fixture(), p = f.context.pqmProdFullApplyPreview();
  f.afterWrite(n => {
    if (n === 1) {const cell = f.raw.get('1:3')[3]; cell.userEnteredValue.stringValue = 'external'; cell.effectiveValue.stringValue = 'external';}
  });
  arm(f, p);
  const report = f.context.pqmProdFullApply();
  assert.equal(report.status, 'CHUNK_FAILED_NEW_PREVIEW_REQUIRED');
  assert.equal(report.chunks_completed, 1);
  assert.equal(f.writes, 1);
  assert.ok(report.remaining_cells > 0);
});

test('post-write verification detects changed A and stops further chunks', () => {
  const f = fixture(), p = f.context.pqmProdFullApplyPreview();
  f.afterWrite(n => {if (n === 1) f.raw.get('1:2')[0].userEnteredValue.stringValue = 'external';});
  arm(f, p);
  const report = f.context.pqmProdFullApply();
  assert.equal(report.status, 'VERIFICATION_FAILED_NEW_PREVIEW_REQUIRED');
  assert.equal(f.writes, 1);
  assert.ok(report.failures > 0);
  assert.equal(report.chunks_completed, 0);
});

test('targeted readback detects validation or note mutation without bulk snapshot metadata', () => {
  for (const property of ['dataValidation', 'note']) {
    const f = fixture(), p = f.context.pqmProdFullApplyPreview();
    f.afterWrite(n => {if (n === 1) f.raw.get('1:2')[3][property] = property === 'note'
      ? 'changed note' : {strict: true};});
    arm(f, p);
    const report = f.context.pqmProdFullApply();
    assert.equal(report.status, 'VERIFICATION_FAILED_NEW_PREVIEW_REQUIRED');
    assert.equal(report.chunks_completed, 0);
    assert.equal(f.writes, 1);
  }
});

test('ambiguous batch response reports write uncertainty and requires a new Preview', () => {
  const f = fixture(), p = f.context.pqmProdFullApplyPreview();
  const original = f.context.Sheets.Spreadsheets.batchUpdate;
  f.context.Sheets.Spreadsheets.batchUpdate = request => {
    original(request);
    throw new Error('simulated response loss');
  };
  arm(f, p);
  const report = f.context.pqmProdFullApply();
  assert.equal(report.status, 'WRITE_OR_READBACK_UNCERTAIN_NEW_PREVIEW_REQUIRED');
  assert.equal(report.cells_attempted, 4);
  assert.equal(report.cells_written, 0, 'confirmed count does not claim uncertain writes');
  assert.equal(f.writes, 1, 'mock may have applied despite the exception');
  assert.equal(f.context.pqmProdFullApplyPreview().total_planned_cells, p.total_planned_cells - 4);
});

test('successful run writes only C/F/H/I in bounded chunks and preserves A and other untouched cells', () => {
  const f = fixture(), p = f.context.pqmProdFullApplyPreview();
  const untouched = [...f.raw].map(([key, cells]) => [key, cells.map((cell, column) =>
    [0, 1, 3, 4, 6, 9, 10, 11, 12, 13, 14].includes(column) ? clone(cell) : null)]);
  arm(f, p);
  const report = f.context.pqmProdFullApply();
  assert.equal(report.status, 'COMPLETE');
  assert.equal(report.cells_written, 32);
  assert.equal(report.cells_verified, 32);
  assert.equal(report.failures, 0);
  assert.equal(report.remaining_cells, 0);
  assert.equal(f.released, 1);
  assert.ok(f.requests.every(batch => batch.length <= 4));
  assert.equal(f.fetches, 2, 'one Preview fetch and one initial Apply fetch; none per chunk');
  assert.equal(f.snapshots, 2, 'one full snapshot in Preview and one at Apply start; none per chunk');
  assert.equal(f.reads, 3 * report.chunks_total, 'two prewrite and one readback targeted reads per chunk');
  assert.deepEqual(Object.keys(report.timing_ms), [
    'initial_pqm_fetch', 'initial_google_guard', 'initial_plan_rebuild',
    'initial_google_phases', 'chunk_pre_read', 'chunk_write', 'chunk_after_read_verification'
  ]);
  assert.ok(Object.entries(report.timing_ms).every(([key, ms]) =>
    key === 'initial_google_phases' || (Number.isFinite(ms) && ms >= 0)));
  untouched.forEach(([key, cells]) => cells.forEach((cell, index) => {
    if (cell) assert.deepEqual(f.raw.get(key)[index], cell);
  }));
  assert.equal(f.context.pqmProdFullApplyPreview().total_planned_cells, 0);
});

test('Full D Preview/Apply parity, stale manager and repeated Apply are guarded', () => {
  const f = fixture(); f.context.PQM_PROD_FULL_CHUNK_MAX_CELLS = 400;
  f.body.items[0].current_manager_name = 'Ready manager';
  const preview = f.context.pqmProdFullApplyPreview();
  assert.equal(preview.changes_by_column.D, 1);
  arm(f, preview);
  assert.equal(f.context.pqmProdFullApply().status, 'COMPLETE');
  assert.equal(f.raw.get('1:2')[3].userEnteredValue.stringValue, 'Ready manager');
  const writes = f.writes;
  arm(f, preview);
  assert.throws(() => f.context.pqmProdFullApply(), /PLAN_OR_GOOGLE_STATE_CHANGED/);
  assert.equal(f.writes, writes);
  assert.equal(f.context.pqmProdFullApplyPreview().total_planned_cells, 0);
  const g = fixture(); g.body.items[0].current_manager_name = 'Ready manager';
  const stale = g.context.pqmProdFullApplyPreview();
  g.body.items[0].current_manager_name = 'Changed after Preview';
  arm(g, stale);
  assert.throws(() => g.context.pqmProdFullApply(), /PLAN_OR_GOOGLE_STATE_CHANGED/);
  assert.equal(g.writes, 0);
});

test('blank E/I/L preserve existing Google values and stale I format fails before write', () => {
  const f = fixture();
  const row = f.raw.get('1:2');
  row[4].userEnteredValue.stringValue = 'Припинено'; row[4].effectiveValue.stringValue = 'Припинено';
  row[8].userEnteredValue.numberValue = 46287; row[8].effectiveValue.numberValue = 46287;
  delete row[8].userEnteredValue.stringValue; delete row[8].effectiveValue.stringValue;
  row[8].userEnteredFormat = {numberFormat: {type: 'DATE', pattern: 'dd.MM.yyyy'}};
  row[11].userEnteredValue.stringValue = 'existing'; row[11].effectiveValue.stringValue = 'existing';
  const original = clone([row[4], row[8], row[11]]);
  const preview = f.context.pqmProdFullApplyPreview();
  assert.equal(preview.changes_by_column.E, 0);
  assert.equal(preview.changes_by_column.I, 7);
  assert.equal(preview.changes_by_column.L, 0);
  arm(f, preview);
  assert.equal(f.context.pqmProdFullApply().status, 'COMPLETE');
  assert.deepEqual(clone([row[4], row[8], row[11]]), original);

  const g = fixture(), stale = g.context.pqmProdFullApplyPreview();
  g.beforeRead(n => {if (n === 1) g.raw.get('1:2')[8].userEnteredFormat = {numberFormat: {pattern: 'yyyy-mm-dd'}};});
  arm(g, stale);
  assert.equal(g.context.pqmProdFullApply().status, 'CHUNK_FAILED_NEW_PREVIEW_REQUIRED');
  assert.equal(g.writes, 0);
});

test('PQM snapshot remains frozen within one Apply; next Preview sees later PQM changes', () => {
  const f = fixture(), preview = f.context.pqmProdFullApplyPreview();
  f.afterWrite(n => {if (n === 1) {
    f.body.items[7].supplier_name = 'later-verified-name';
    f.body.items[7].verification_date = '2026-09-23';
  }});
  arm(f, preview);
  const report = f.context.pqmProdFullApply();
  assert.equal(report.status, 'COMPLETE');
  assert.equal(f.fetches, 2, 'no hidden refetch during chunks');
  assert.equal(f.context.pqmProdFullApplyPreview().total_planned_cells, 2,
    'fresh Preview plans name and its newer verification date');
  assert.equal(f.fetches, 3);
});

test('blank PQM C and H preserve Google values', () => {
  const f = fixture(), code = f.body.items[0].supplier_code;
  f.body.items[0].supplier_name = null;
  f.body.items[0].last_application_date = null;
  f.body.items[0].google_sync_last_decided_application_date = null;
  const originalC = clone(f.raw.get('1:2')[2]), originalH = clone(f.raw.get('1:2')[7]);
  const p = f.context.pqmProdFullApplyPreview();
  assert.equal(p.total_planned_cells, 30);
  arm(f, p);
  assert.equal(f.context.pqmProdFullApply().status, 'COMPLETE');
  assert.deepEqual(f.raw.get('1:2')[2], originalC);
  assert.deepEqual(f.raw.get('1:2')[7], originalH);
  assert.ok(f.body.items.some(x => x.supplier_code === code));
});

test('new Preview after partial success plans only remaining differences', () => {
  const f = fixture(), initial = f.context.pqmProdFullApplyPreview();
  f.afterWrite(n => {if (n === 1) {const cell = f.raw.get('1:3')[3]; cell.userEnteredValue.stringValue = 'external'; cell.effectiveValue.stringValue = 'external';}});
  arm(f, initial);
  const stopped = f.context.pqmProdFullApply();
  assert.equal(stopped.chunks_completed, 1);
  const next = f.context.pqmProdFullApplyPreview();
  assert.equal(next.total_planned_cells, initial.total_planned_cells - 4);
  assert.notEqual(next.plan_digest, initial.plan_digest);
  const changed = f.raw.get('1:3')[3];
  changed.userEnteredValue.stringValue = '';
  changed.effectiveValue.stringValue = '';
  const resumed = f.context.pqmProdFullApplyPreview();
  arm(f, resumed);
  assert.equal(f.context.pqmProdFullApply().status, 'COMPLETE');
  assert.equal(f.context.pqmProdFullApplyPreview().total_planned_cells, 0);
});

test('time budget and lock fail closed before any write', () => {
  const f = fixture(), preview = f.context.pqmProdFullApplyPreview();
  f.context.PQM_PROD_FULL_RUN_BUDGET_MS = -1;
  arm(f, preview);
  const stopped = f.context.pqmProdFullApply();
  assert.equal(stopped.status, 'TIME_BUDGET_STOP_NEW_PREVIEW_REQUIRED');
  assert.equal(f.writes, 0);
  assert.equal(stopped.remaining_cells, preview.total_planned_cells);
  f.context.LockService = {getScriptLock: () => ({tryLock: () => false})};
  arm(f, preview);
  assert.throws(() => f.context.pqmProdFullApply(), /another operation/);
  assert.equal(f.writes, 0);
});

test('default bounded chunks allow at most 200 rows and 400 planned cells', () => {
  const f = fixture();
  f.context.PQM_PROD_FULL_CHUNK_MAX_CELLS = 400;
  f.context.PQM_PROD_FULL_CHUNK_MAX_ROWS = 200;
  const entries = Array.from({length: 301}, (_, index) => ({
    row: index + 2, columns: index % 2 ? [2, 5, 7] : [2]
  }));
  const chunks = f.context.pqmProdFullChunks_(entries);
  assert.ok(chunks.length > 1);
  assert.ok(chunks.every(chunk => chunk.length <= 200 &&
    chunk.reduce((n, entry) => n + entry.columns.length, 0) <= 400));
  assert.equal(chunks.flat().length, entries.length);
  assert.equal(f.writes, 0);
});
