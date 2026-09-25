const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

const files = ['PqmSandboxPreviewDependencies.gs', 'PqmSandboxPreview.gs', 'PqmSandboxControlledApply.gs'];
const source = files.map(name => fs.readFileSync(__dirname + '/' + name, 'utf8')).join('\n');
const clone = value => JSON.parse(JSON.stringify(value));
const combinations = ['C', 'F', 'H', 'C+F', 'C+H', 'F+H', 'C+F+H', 'C', 'F', 'H'];

function fixture() {
  const logs = [];
  const context = {console: {log: message => logs.push(message)}, Date, Map, Set};
  vm.createContext(context);
  vm.runInContext(source, context);
  const tabs = Object.fromEntries(['ФОП', 'ЮО'].map((name, index) => [name, {
    id: index + 1, maxRows: 30, templateRowHeight: 30,
    headers: Array.from(context.PQM_GOOGLE_HEADERS), rows: [],
    merges: [], protectedRanges: [], conditionalFormats: []
  }]));
  const body = {count: 10, items: []};
  const state = new Map();
  combinations.forEach((combination, index) => {
    const tab = index < 5 ? 'ФОП' : 'ЮО';
    const code = String(1000000000 + index);
    const rowNumber = tabs[tab].rows.length + 2;
    const columns = combination.split('+');
    const values = Array(15).fill('');
    values[0] = 'old'; values[1] = code;
    values[2] = columns.includes('C') ? 'old-name' : 'Name';
    values[5] = columns.includes('F') ? 'old-status' : 'Active';
    values[7] = columns.includes('H') ? 46286 : 46287;
    const row = {values, formulas: Array(15).fill(''), codeDisplay: code, dateFormat: 'dd.MM.yyyy'};
    tabs[tab].rows.push(row);
    body.items.push({supplier_code: code, entity_type: tab === 'ФОП' ? 'individual_entrepreneur' : 'legal_entity',
      supplier_name: 'Name', monitoring_eligible: true, google_sync_eligible: true,
      freshness_marker: 'fresh',
      edr_status_current: null, verification_date: null, verification_officer: null,
      prozorro_status_google: 'Active', last_application_date: '2026-09-22',
      google_sync_last_decided_application_date: '2026-09-22'});
    const cells = values.map((value, column) => {
      const c = {userEnteredValue: typeof value === 'number' ? {numberValue: value} : {stringValue: value},
        effectiveValue: typeof value === 'number' ? {numberValue: value} : {stringValue: value},
        formattedValue: String(value)};
      if (column === 7) c.userEnteredFormat = {numberFormat: {type: 'DATE', pattern: 'dd.MM.yyyy'}};
      return c;
    });
    state.set(tabs[tab].id + ':' + rowNumber, cells);
  });

  let writes = 0, requests = [], reads = 0, beforeReadHook = null;
  let prompts = [], confirmation = 'NO';
  const cache = new Map();
  context.CacheService = {getScriptCache: () => ({
    put: (key, value, seconds) => {assert.equal(seconds, 21600); cache.set(key, value);},
    get: key => cache.get(key) || null
  })};
  context.pqmSandboxFetchRegistry_ = () => clone(body);
  context.pqmGoogleSnapshot_ = () => clone(tabs);
  context.pqmSandboxRegistryUrl_ = () => 'https://pqm-sandbox.onrender.com/api/integrations/suppliers/full-registry';
  context.SpreadsheetApp = {
    getActiveSpreadsheet: () => ({getId: () => context.PQM_SANDBOX_CONTROLLED_SPREADSHEET_ID}),
    getUi: () => ({ButtonSet: {OK_CANCEL: 'OK_CANCEL', YES_NO: 'YES_NO'}, Button: {OK: 'OK', YES: 'YES'},
      prompt: () => prompts.shift() || {getSelectedButton: () => 'CANCEL'},
      alert: () => confirmation})
  };
  context.LockService = {getScriptLock: () => ({tryLock: () => true, releaseLock: () => {}})};
  context.Utilities = {DigestAlgorithm: {SHA_256: 'SHA_256'}, Charset: {UTF_8: 'UTF_8'},
    computeDigest: (_algorithm, value) => crypto.createHash('sha256').update(value).digest(),
    base64EncodeWebSafe: buffer => Buffer.from(buffer).toString('base64url')};
  context.Sheets = {Spreadsheets: {
    get: (_id, options) => {
      reads++;
      if (beforeReadHook) beforeReadHook(reads);
      const grouped = new Map();
      options.ranges.forEach(range => {
        const match = /^'(ФОП|ЮО)'!A(\d+):O\2$/.exec(range);
        assert.ok(match, 'read only one bounded selected row');
        const sheet = tabs[match[1]], row = Number(match[2]);
        if (!grouped.has(sheet.id)) grouped.set(sheet.id, []);
        grouped.get(sheet.id).push({startRow: row - 1,
          rowData: [{values: clone(state.get(sheet.id + ':' + row))}]});
      });
      return {sheets: [...grouped].map(([id, data]) => ({properties: {sheetId: id}, data}))};
    },
    batchUpdate: ({requests: next}, id) => {
      assert.equal(id, context.PQM_SANDBOX_CONTROLLED_SPREADSHEET_ID);
      writes++; requests = clone(next);
      next.forEach(request => {
        assert.deepEqual(Object.keys(request), ['updateCells']);
        const update = request.updateCells, range = update.range;
        const cells = state.get(range.sheetId + ':' + (range.startRowIndex + 1));
        const cell = cells[range.startColumnIndex];
        cell.userEnteredValue = clone(update.rows[0].values[0].userEnteredValue);
        cell.effectiveValue = clone(cell.userEnteredValue);
        cell.formattedValue = String(cell.userEnteredValue.stringValue ?? cell.userEnteredValue.numberValue);
        if (range.startColumnIndex === 7 || range.startColumnIndex === 8) {
          cell.userEnteredFormat = clone(update.rows[0].values[0].userEnteredFormat);
        }
      });
    }
  }};
  return {context, tabs, body, state, logs, cache, get writes() {return writes;}, get requests() {return requests;},
    get reads() {return reads;}, setBeforeReadHook: fn => {beforeReadHook = fn;},
    setPrompts: values => {prompts = values;}, setConfirmation: value => {confirmation = value;}};
}

test('selector covers all seven combinations, both tabs, and at most ten rows', () => {
  const f = fixture();
  const preview = f.context.pqmSandboxControlledPreview();
  assert.equal(preview.google_writes, 0);
  assert.equal(preview.selected_rows, 10);
  assert.ok(preview.planned_cells <= 30);
  assert.deepEqual(new Set(preview.selected.map(x => x.tab)), new Set(['ФОП', 'ЮО']));
  assert.deepEqual(new Set(preview.available_combinations), new Set(combinations));
  assert.equal(new Set(preview.selected.map(x => x.combination)).size, 7);
  assert.ok(preview.selected.every(x => x.before_digest && x.row >= 2 && x.planned_columns.every(c => 'CFH'.includes(c))));
  assert.equal(f.writes, 0);
});

test('Preview log is compact and full guard manifest stays only in transient cache', () => {
  const f = fixture(), preview = f.context.pqmSandboxControlledPreview();
  const logged = JSON.parse(f.logs.at(-1));
  assert.equal(logged.dry_run, true);
  assert.equal(logged.google_writes, 0);
  assert.equal(logged.plan_digest, preview.plan_digest);
  assert.equal(logged.selected_rows, preview.selected_rows);
  assert.equal(logged.planned_cells, preview.planned_cells);
  assert.ok(Array.isArray(logged.available_combinations));
  assert.ok(logged.selected.every(x => 'supplier_code' in x && 'tab' in x && 'row' in x &&
    'planned_columns' in x && 'before_digest' in x));
  assert.equal('guard_manifest' in logged, false);
  assert.equal('cell_digests' in logged, false);
  assert.equal('guard_manifest' in preview, false);
  assert.equal(f.cache.has(preview.plan_digest), true);
  assert.ok(JSON.parse(f.cache.get(preview.plan_digest)).entries.every(x => x.cell_digests.length === 15));
  assert.equal(f.writes, 0);
});

test('exact service identity 00000000 is excluded only from controlled selection and rejected if explicit', () => {
  const f = fixture();
  const tab = f.tabs['ЮО'], row = tab.rows[0], oldCode = row.codeDisplay;
  row.codeDisplay = '00000000'; row.values[1] = '00000000';
  f.body.items.find(x => x.supplier_code === oldCode).supplier_code = '00000000';
  f.state.get(tab.id + ':2')[1].formattedValue = '00000000';
  f.state.get(tab.id + ':2')[1].userEnteredValue.stringValue = '00000000';
  const body = f.context.pqmSandboxFetchRegistry_(), tabs = f.context.pqmGoogleSnapshot_();
  const plan = f.context.pqmSandboxControlledPlan_(body, tabs);
  assert.ok(plan.changes.some(change => change.tab === 'ЮО' && change.row === 2),
    'general planner semantics remain unchanged');
  const preview = f.context.pqmSandboxControlledPreview();
  assert.equal(preview.selected_rows, 9);
  assert.equal(preview.selected.some(x => x.supplier_code === '00000000'), false);
  const codes = preview.selected.map(x => x.supplier_code).concat('00000000');
  f.setPrompts([response(codes.join(','))]);
  assert.throws(() => f.context.pqmSandboxControlledApply(), /UNSAFE_PLACEHOLDER_IDENTITY/);
  assert.equal(f.writes, 0);
});

test('cancelled or denied confirmation never writes', () => {
  const f = fixture();
  assert.equal(f.context.pqmSandboxControlledApply().google_writes, 0);
  const preview = f.context.pqmSandboxControlledPreview();
  f.setPrompts([response(preview.selected.map(x => x.supplier_code).join(',')), response(preview.plan_digest)]);
  f.setConfirmation('NO');
  assert.equal(f.context.pqmSandboxControlledApply().google_writes, 0);
  assert.equal(f.writes, 0);
});

test('explicit confirmed sample writes only planned C/F/H and verifies every other cell including A', () => {
  const f = fixture();
  const preview = f.context.pqmSandboxControlledPreview();
  f.setPrompts([response(preview.selected.map(x => x.supplier_code).join(',')), response(preview.plan_digest)]);
  f.setConfirmation('YES');
  const report = f.context.pqmSandboxControlledApply();
  assert.equal(f.writes, 1);
  assert.equal(report.verification_passed, true);
  assert.equal(report.selected_rows, 10);
  assert.equal(report.written_cells, preview.planned_cells);
  assert.ok(f.requests.every(r => [2, 5, 7].includes(r.updateCells.range.startColumnIndex)));
  assert.ok(f.requests.every(r => r.updateCells.range.endRowIndex - r.updateCells.range.startRowIndex === 1));
  assert.ok(f.requests.every(r => r.updateCells.range.endColumnIndex - r.updateCells.range.startColumnIndex === 1));
});

test('expanded controlled sample safely writes E/I/L and verifies untouched A/B/D/G/J/K/M/N/O', () => {
  const f = fixture();
  f.body.items[0].edr_status_current = 'Зареєстровано';
  f.body.items[0].verification_date = '2026-09-23';
  f.body.items[0].verification_officer = 'verified officer';
  const preview = f.context.pqmSandboxControlledPreview();
  const chosen = preview.selected.find(entry => entry.supplier_code === f.body.items[0].supplier_code);
  assert.ok(chosen);
  assert.deepEqual(Array.from(chosen.planned_columns), ['C', 'E', 'I', 'L']);
  f.setPrompts([response(preview.selected.map(x => x.supplier_code).join(',')), response(preview.plan_digest)]);
  f.setConfirmation('YES');
  const result = f.context.pqmSandboxControlledApply();
  assert.equal(result.verification_passed, true);
  assert.ok(f.requests.every(request => [2, 4, 5, 7, 8, 11].includes(request.updateCells.range.startColumnIndex)));
  assert.equal(f.requests.filter(request => request.updateCells.range.startColumnIndex === 8).length, 1);
});

test('a stale digest or changed row fails closed before batchUpdate', () => {
  const f = fixture(), preview = f.context.pqmSandboxControlledPreview();
  const codes = preview.selected.map(x => x.supplier_code).join(',');
  f.setPrompts([response(codes), response('a'.repeat(43))]);
  f.setConfirmation('YES');
  assert.throws(() => f.context.pqmSandboxControlledApply(), /GUARD_MANIFEST_EXPIRED/);
  assert.equal(f.writes, 0);
  const first = preview.selected[0];
  const sheetId = f.tabs[first.tab].id;
  f.state.get(sheetId + ':' + first.row)[0].userEnteredValue.stringValue = 'concurrent edit';
  f.setPrompts([response(codes), response(preview.plan_digest)]);
  assert.throws(() => f.context.pqmSandboxControlledApply(), /UNTOUCHED_CELL_CHANGED/);
  assert.equal(f.writes, 0);
});

test('append, conflict, duplicate or protected selected cells fail closed', () => {
  const f = fixture();
  f.body.items.push({...f.body.items[0], supplier_code: '9999999999'});
  f.body.count++;
  assert.throws(() => f.context.pqmSandboxControlledPreview(), /append/);
  f.body.items.pop(); f.body.count--;
  f.tabs['ФОП'].protectedRanges.push({range: {startRowIndex: 1, endRowIndex: 2,
    startColumnIndex: 2, endColumnIndex: 3}, requestingUserCanEdit: false});
  assert.throws(() => f.context.pqmSandboxControlledPreview(), /protection/);
  assert.equal(f.writes, 0);
});

test('blank PQM C/H are preserved by the controlled request builder', () => {
  const f = fixture();
  f.body.items[6].supplier_name = null;
  f.body.items[6].last_application_date = null;
  f.body.items[6].google_sync_last_decided_application_date = null;
  const preview = f.context.pqmSandboxControlledPreview();
  const selected = preview.selected.find(x => x.supplier_code === f.body.items[6].supplier_code);
  assert.ok(selected);
  assert.deepEqual(Array.from(selected.planned_columns), ['F']);
  assert.equal(f.writes, 0);
});

test('AFTER verification detects a changed unowned cell', () => {
  const f = fixture();
  const preview = f.context.pqmSandboxControlledPreview();
  const first = preview.selected[0];
  const originalUpdate = f.context.Sheets.Spreadsheets.batchUpdate;
  f.context.Sheets.Spreadsheets.batchUpdate = function(request, id) {
    originalUpdate(request, id);
    f.state.get(f.tabs[first.tab].id + ':' + first.row)[0].userEnteredValue.stringValue = 'external edit';
  };
  f.setPrompts([response(preview.selected.map(x => x.supplier_code).join(',')), response(preview.plan_digest)]);
  f.setConfirmation('YES');
  const report = f.context.pqmSandboxControlledApply();
  assert.equal(f.writes, 1);
  assert.equal(report.verification_passed, false);
  assert.ok(report.failures.some(failure => failure.column === 1 && failure.reason === 'unplanned_cell_changed'));
});

test('sample protection exception applies only to its covered column', () => {
  const f = fixture();
  f.tabs['ФОП'].protectedRanges.push({range: {startRowIndex: 1, endRowIndex: 2,
    startColumnIndex: 0, endColumnIndex: 3}, requestingUserCanEdit: false,
    unprotectedRanges: [{startRowIndex: 1, endRowIndex: 2, startColumnIndex: 0, endColumnIndex: 1}]});
  assert.throws(() => f.context.pqmSandboxControlledPreview(), /protection/);
  assert.equal(f.writes, 0);
});

test('wrong spreadsheet and edit between two prewrite reads fail closed', () => {
  const wrong = fixture();
  wrong.context.SpreadsheetApp.getActiveSpreadsheet = () => ({getId: () => 'different-spreadsheet'});
  assert.throws(() => wrong.context.pqmSandboxControlledPreview(), /spreadsheet guard/);
  assert.equal(wrong.writes, 0);

  const f = fixture(), preview = f.context.pqmSandboxControlledPreview();
  const first = preview.selected[0];
  f.setBeforeReadHook(readNumber => {
    if (readNumber === 3) {
      f.state.get(f.tabs[first.tab].id + ':' + first.row)[0].userEnteredValue.stringValue = 'changed after first guard';
    }
  });
  f.setPrompts([response(preview.selected.map(x => x.supplier_code).join(',')), response(preview.plan_digest)]);
  f.setConfirmation('YES');
  assert.throws(() => f.context.pqmSandboxControlledApply(), /UNTOUCHED_CELL_CHANGED/);
  assert.equal(f.writes, 0);
});

test('guard digest is deterministic across runs and object property order', () => {
  const first = fixture(), second = fixture();
  const a = first.context.pqmSandboxControlledPreview();
  const b = second.context.pqmSandboxControlledPreview();
  assert.equal(a.plan_digest, b.plan_digest);
  const value = {z: [{b: 2, a: 1}], a: {y: true, x: false}};
  const reordered = {a: {x: false, y: true}, z: [{a: 1, b: 2}]};
  assert.equal(first.context.pqmSandboxControlledDigest_(value),
    second.context.pqmSandboxControlledDigest_(reordered));
  assert.equal(first.writes + second.writes, 0);
});

test('equivalent selected rows and changes in different order have the same plan digest', () => {
  const f = fixture(), body = f.context.pqmSandboxFetchRegistry_();
  const tabs = f.context.pqmGoogleSnapshot_();
  const plan = f.context.pqmSandboxControlledPlan_(body, tabs);
  const candidates = f.context.pqmSandboxControlledCandidates_(plan, tabs, body);
  const selected = f.context.pqmSandboxControlledSelect_(candidates);
  const rows = f.context.pqmSandboxControlledReadRows_(f.context.PQM_SANDBOX_CONTROLLED_SPREADSHEET_ID, selected, tabs);
  const original = f.context.pqmSandboxControlledState_(selected, rows);
  const reversed = f.context.pqmSandboxControlledState_(selected.slice().reverse(), rows.slice().reverse());
  assert.equal(original.plan_digest, reversed.plan_digest);
  assert.equal(original.plan_digest, f.context.pqmSandboxControlledPlanDigest_(original.entries.slice().reverse()));
  f.context.pqmSandboxControlledGuard_(
    {entries: original.entries.slice().reverse(), plan_digest: original.plan_digest}, original);
  assert.equal(f.writes, 0);
});

test('two consecutive reads of identical 15 cells produce the same before digest', () => {
  const f = fixture(), a = f.context.pqmSandboxControlledPreview();
  const b = f.context.pqmSandboxControlledPreview();
  assert.deepEqual(a.selected.map(x => x.before_digest), b.selected.map(x => x.before_digest));
  assert.equal(f.writes, 0);
});

test('volatile effective and formatted values do not change stable row digest', () => {
  const f = fixture(), before = f.context.pqmSandboxControlledPreview();
  const first = before.selected[0], cell = f.state.get(f.tabs[first.tab].id + ':' + first.row)[2];
  const originalEntered = clone(cell.userEnteredValue);
  cell.effectiveValue = {stringValue: 'recalculated'};
  cell.formattedValue = 'reformatted';
  cell.userEnteredValue = {formulaValue: '=A1'};
  const withFormula = f.context.pqmSandboxControlledPreview();
  assert.notEqual(before.plan_digest, withFormula.plan_digest, 'formula edit is a real persisted change');
  cell.userEnteredValue = originalEntered;
  const after = f.context.pqmSandboxControlledPreview();
  assert.equal(before.plan_digest, after.plan_digest);
  assert.equal(f.writes, 0);
});

test('generated_at, timing, and equivalent PQM date representations do not affect plan digest', () => {
  const f = fixture();
  f.body.generated_at = '2026-09-22T22:00:00Z';
  f.body.timing_ms = {pqm_fetch: 100};
  const before = f.context.pqmSandboxControlledPreview();
  f.body.generated_at = '2026-09-22T23:00:00Z';
  f.body.timing_ms = {pqm_fetch: 999};
  f.body.items.forEach(item => {item.last_application_date = '22.09.2026';});
  const after = f.context.pqmSandboxControlledPreview();
  assert.equal(before.plan_digest, after.plan_digest);
  assert.equal(f.writes, 0);
});

test('freshness-marker-only payload change does not alter controlled plan digest', () => {
  const f = fixture();
  const before = f.context.pqmSandboxControlledPreview();
  f.body.items[0].freshness_marker = 'new marker';
  const after = f.context.pqmSandboxControlledPreview();
  assert.equal(before.plan_digest, after.plan_digest);
  assert.ok(after.selected.every(entry => !entry.planned_columns.includes('A')));
  assert.equal(f.writes, 0);
});

test('protected A is not an owned-cell protection conflict', () => {
  const f = fixture();
  f.tabs['ФОП'].protectedRanges.push({range: {startRowIndex: 1, endRowIndex: 2,
    startColumnIndex: 0, endColumnIndex: 1}, requestingUserCanEdit: false});
  assert.equal(f.context.pqmSandboxControlledPreview().selected_rows, 10);
  assert.equal(f.writes, 0);
});

test('guard classifies PQM, plan, row position and Google state independently', () => {
  const f = fixture(), preview = f.context.pqmSandboxControlledPreview();
  const original = JSON.parse(f.cache.get(preview.plan_digest));
  const current = clone(original);
  const guard = f.context.pqmSandboxControlledGuard_;
  current.entries[0].pqm_value_digest = 'changed';
  current.plan_digest = f.context.pqmSandboxControlledDigest_(current.entries);
  assert.throws(() => guard(original, current), /PQM_PLANNED_VALUES_CHANGED/);
  current.entries[0] = clone(original.entries[0]);
  current.entries[0].planned_cells_digest = 'changed';
  current.plan_digest = f.context.pqmSandboxControlledDigest_(current.entries);
  assert.throws(() => guard(original, current), /PLAN_DIGEST_CHANGED/);
  current.entries[0] = clone(original.entries[0]);
  current.entries[0].before_digest = 'changed';
  current.plan_digest = f.context.pqmSandboxControlledDigest_(current.entries);
  current.entries[0].cell_digests[2] = 'changed';
  current.plan_digest = f.context.pqmSandboxControlledDigest_(current.entries);
  assert.throws(() => guard(original, current), /GOOGLE_BEFORE_DIGEST_CHANGED/);
  current.entries[0] = clone(original.entries[0]);
  current.entries[0].row++;
  current.plan_digest = f.context.pqmSandboxControlledDigest_(current.entries);
  assert.throws(() => guard(original, current), /ROW_MOVED/);
  assert.equal(f.writes, 0);
});

test('tampered manifest and nondeterministic digest fail before any write', () => {
  const f = fixture(), preview = f.context.pqmSandboxControlledPreview();
  const original = JSON.parse(f.cache.get(preview.plan_digest)), current = clone(original);
  original.entries[0].row++;
  assert.throws(() => f.context.pqmSandboxControlledGuard_(original, current), /PLAN_DIGEST_CHANGED/);
  original.entries[0].row--;
  current.plan_digest = 'incorrect';
  assert.throws(() => f.context.pqmSandboxControlledGuard_(original, current), /DIGEST_NONDETERMINISTIC/);
  assert.equal(f.writes, 0);
});

test('actual PQM planned value and untouched Google cell changes fail closed with safe logs', () => {
  const f = fixture(), preview = f.context.pqmSandboxControlledPreview();
  const codes = preview.selected.map(x => x.supplier_code).join(',');
  f.body.items[0].supplier_name = 'different';
  f.setPrompts([response(codes), response(preview.plan_digest)]);
  f.setConfirmation('YES');
  assert.throws(() => f.context.pqmSandboxControlledApply(), /PQM_PLANNED_VALUES_CHANGED/);
  assert.equal(f.writes, 0);
  const log = JSON.parse(f.logs.at(-1));
  assert.deepEqual(Object.keys(log), ['reason', 'tab', 'row', 'planned_columns',
    'old_digest_prefix', 'new_digest_prefix']);
  assert.equal(log.reason, 'PQM_PLANNED_VALUES_CHANGED');
  assert.equal(log.old_digest_prefix.length, 8);
  assert.equal(log.new_digest_prefix.length, 8);
  assert.ok(!f.logs.at(-1).includes(f.body.items[0].supplier_code));

  f.body.items[0].supplier_name = 'Name';
  const first = preview.selected[0];
  f.state.get(f.tabs[first.tab].id + ':' + first.row)[3].userEnteredValue.stringValue = 'edited';
  f.setPrompts([response(codes), response(preview.plan_digest)]);
  assert.throws(() => f.context.pqmSandboxControlledApply(), /UNTOUCHED_CELL_CHANGED/);
  assert.equal(f.writes, 0);
});

test('different explicit code set is diagnosed without logging codes', () => {
  const f = fixture(), preview = f.context.pqmSandboxControlledPreview();
  const codes = preview.selected.map(x => x.supplier_code);
  codes[0] = '9999999999';
  f.setPrompts([response(codes.join(',')), response(preview.plan_digest)]);
  assert.throws(() => f.context.pqmSandboxControlledApply(), /SELECTED_CODES_CHANGED/);
  const log = JSON.parse(f.logs.at(-1));
  assert.equal(log.reason, 'SELECTED_CODES_CHANGED');
  assert.ok(!f.logs.at(-1).includes('9999999999'));
  assert.equal(f.writes, 0);
});

test('supplier code display changes before targeted read are diagnosed without writes', () => {
  const f = fixture(), preview = f.context.pqmSandboxControlledPreview();
  const first = preview.selected[0];
  f.setBeforeReadHook(readNumber => {
    if (readNumber === 2) f.state.get(f.tabs[first.tab].id + ':' + first.row)[1].formattedValue = 'different';
  });
  f.setPrompts([response(preview.selected.map(x => x.supplier_code).join(',')), response(preview.plan_digest)]);
  f.setConfirmation('YES');
  assert.throws(() => f.context.pqmSandboxControlledApply(), /SUPPLIER_CODE_CHANGED/);
  assert.equal(f.writes, 0);
});

function response(text) {
  return {getSelectedButton: () => 'OK', getResponseText: () => text};
}
