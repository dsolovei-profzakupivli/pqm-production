const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');
const path = require('node:path');
const {spawnSync} = require('node:child_process');

const source = ['PqmSandboxPreviewDependencies.gs', 'PqmSandboxPreview.gs',
  'PqmSandboxControlledApply.gs', 'PqmSandboxFullApply.gs']
  .map(name => fs.readFileSync(__dirname + '/' + name, 'utf8')).join('\n');
const clone = value => JSON.parse(JSON.stringify(value));
function response(text) { return {getSelectedButton: () => 'OK', getResponseText: () => text}; }

function fixture() {
  const logs = [], context = {console: {log: text => logs.push(text)}, Date, Map, Set};
  vm.createContext(context);
  vm.runInContext(source, context);
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
    tab.rows.push({values, formulas: Array(15).fill(''), codeDisplay: code, dateFormat: 'dd.MM.yyyy'});
    body.items.push({supplier_code: code, entity_type: name === 'ФОП' ? 'individual_entrepreneur' : 'legal_entity',
      monitoring_eligible: true, google_sync_eligible: true,
      freshness_marker: 'fresh', supplier_name: 'verified-name',
      edr_status_current: null, verification_date: null, verification_officer: null,
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
  context.PQM_SANDBOX_FULL_CHUNK_MAX_CELLS = 4;
  context.PQM_SANDBOX_FULL_CHUNK_MAX_ROWS = 2;
  context.pqmSandboxFetchRegistry_ = () => { fetches++; return clone(body); };
  context.pqmSandboxRegistryUrl_ = () => 'https://pqm-sandbox.onrender.com/api/integrations/suppliers/full-registry';
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
    getActiveSpreadsheet: () => ({getId: () => context.PQM_SANDBOX_CONTROLLED_SPREADSHEET_ID}),
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
        assert.ok([2, 4, 5, 7, 8, 11].includes(range.startColumnIndex));
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

test('eight complete daily cycles converge across real morning and evening code', () => {
  const python = process.env.PQM_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
  const repo = process.env.PQM_PERMANENT_REPO || path.resolve(__dirname, '../..');
  const bridge = path.join(repo, 'validation/local_release_20260911/daily_cycle_evening_fixture.py');
  const scenarios = [
    {pqm: '2026-09-20', po: 'Officer A', google: '2026-09-20', go: 'Officer A', final: ['2026-09-20', 'Officer A']},
    {pqm: '2026-09-20', po: 'Officer A', google: '2026-09-25', go: 'Officer B', final: ['2026-09-25', 'Officer B']},
    {pqm: '2026-09-20', po: 'Officer A', google: '2026-09-20', go: 'Officer B', final: ['2026-09-20', 'Officer B']},
    {pqm: '2026-09-25', po: 'Officer B', google: '2026-06-05', go: 'Officer A', final: ['2026-09-25', 'Officer B']},
    {pqm: '2026-09-25', po: 'Officer B', google: '2026-09-25', go: 'Officer B',
      daytime: {i: '2026-06-05', l: 'Officer A'}, final: ['2026-09-25', 'Officer B']},
    {pqm: '2026-09-20', po: 'Officer A', google: '2026-09-20', go: 'Officer A',
      startingGjkm: ['Old G', '2026-09-20', 'Old K', 'Old M'],
      daytime: {g: 'Changed G', j: '', k: 'Changed K', m: ''},
      final: ['2026-09-20', 'Officer A']},
    {pqm: '2026-09-20', po: 'Officer A', google: '2026-09-20', go: 'Officer A',
      e: 'Немає інформації', final: ['2026-09-20', 'Officer A']},
    {pqm: '2026-09-20', po: 'Officer A', google: '2026-09-20', go: 'Officer B',
      e: 'Зареєстровано', factual: 'Припинено', final: ['2026-09-20', 'Officer B']}
  ];
  for (const [index, s] of scenarios.entries()) {
    const f = fixture(), item = f.body.items[0];
    f.context.PQM_SANDBOX_FULL_CHUNK_MAX_CELLS = 6;
    item.verification_date = s.pqm; item.verification_officer = s.po;
    item.edr_status_current = s.factual || 'Зареєстровано';
    setGoogleCell(f, 8, f.context.pqmGoogleDate_(s.google));
    setGoogleCell(f, 11, s.go);
    if (s.startingGjkm) for (const [position, column] of [6, 9, 10, 12].entries()) {
      setGoogleCell(f, column, s.startingGjkm[position]);
    }
    if (s.e) setGoogleCell(f, 4, s.e);
    const morning = f.context.pqmSandboxFullApplyPreview();
    arm(f, morning);
    assert.equal(f.context.pqmSandboxFullApply().status, 'COMPLETE', index + 1);
    if (index === 6) assert.equal(f.raw.get('1:2')[4].effectiveValue.stringValue, s.e);
    if (s.daytime) for (const [key, value] of Object.entries(s.daytime)) {
      const column = {i: 8, l: 11, g: 6, j: 9, k: 10, m: 12}[key];
      setGoogleCell(f, column, key === 'i' ? f.context.pqmGoogleDate_(value) : value);
    }
    const cell = column => f.raw.get('1:2')[column].effectiveValue;
    const value = column => cell(column).stringValue ?? cell(column).numberValue ?? '';
    const google = {i: f.context.pqmGoogleCalendarDate_(value(8)).value, l: value(11),
      e: value(4), g: value(6), j: value(9), k: value(10), m: value(12)};
    const run = spawnSync(python, [bridge], {cwd: repo, encoding: 'utf8',
      env: {...process.env, PYTHONIOENCODING: 'utf-8',
        PQM_GOOGLE_REGISTRY_SPREADSHEET_ID: 'SYNTHETIC_AUTHORIZED'},
      input: JSON.stringify({pqm_date: s.pqm, pqm_officer: s.po, pqm_status: s.factual || 'Зареєстровано',
        factual: s.factual, pqm_gjkm: s.startingGjkm, google})});
    assert.equal(run.status, 0, `scenario ${index + 1}: ${run.stderr}`);
    const evening = JSON.parse(run.stdout);
    assert.deepEqual([evening.date, evening.officer], s.final, `scenario ${index + 1}`);
    assert.equal(evening.second.verification_event_changes, 0, `scenario ${index + 1}: repeat evening`);
    if (index === 5) assert.deepEqual(evening.gjkm, ['Changed G', '', 'Changed K', '']);
    if (index === 7) assert.equal(evening.status, 'Припинено');
    item.verification_date = evening.date; item.verification_officer = evening.officer;
    item.edr_status_current = evening.status;
    const plan = f.context.pqmGooglePlan_(f.body, f.context.pqmGoogleSnapshot_('sandbox-id'));
    assert.equal(plan.counts.conflicts + plan.counts.errors + plan.counts.duplicate_keys, 0,
      `scenario ${index + 1}: ${JSON.stringify(plan.issues)} evening=${JSON.stringify(evening)} google=${JSON.stringify(google)}`);
    const next = f.context.pqmSandboxFullApplyPreview();
    if (index === 4) {
      assert.equal(plan.counts.pqm_newer_written, 1,
        'manual Google backdating is corrected forward from preserved PQM evidence');
    } else {
      assert.ok(plan.changes.every(change => !('8' in change.cells) && !('11' in change.cells)),
        `scenario ${index + 1}: next morning reverse I/L write`);
    }
    arm(f, next);
    assert.equal(f.context.pqmSandboxFullApply().status, 'COMPLETE');
    const stable = f.context.pqmSandboxFullApplyPreview();
    const finalPlan = f.context.pqmGooglePlan_(f.body, f.context.pqmGoogleSnapshot_('sandbox-id'));
    assert.ok(finalPlan.changes.every(change => !('8' in change.cells) && !('11' in change.cells)),
      `scenario ${index + 1}: repeated morning I/L`);
  }
});

test('pending-only supplier stays out of morning queue until a decision; pending follow-up keeps H', () => {
  const f = fixture();
  const first = {...f.body.items[0], supplier_code: '9999999999',
    google_sync_eligible: false, monitoring_eligible: true, last_application_date: '2026-09-20',
    google_sync_last_decided_application_date: null};
  f.body.items.push(first); f.body.count++;
  let plan = f.context.pqmGooglePlan_(f.body, f.context.pqmGoogleSnapshot_('sandbox-id'));
  assert.equal(plan.changes.some(x => x.append && x.cells[1] === first.supplier_code), false);
  first.google_sync_eligible = true;
  first.last_application_date = '2026-09-20';
  first.google_sync_last_decided_application_date = '2026-09-20';
  plan = f.context.pqmGooglePlan_(f.body, f.context.pqmGoogleSnapshot_('sandbox-id'));
  assert.equal(plan.changes.some(x => x.append && x.cells[1] === first.supplier_code), true);
  const existing = f.body.items[0];
  existing.last_application_date = '2026-09-22';
  plan = f.context.pqmGooglePlan_(f.body, f.context.pqmGoogleSnapshot_('sandbox-id'));
  const before = plan.changes.find(x => x.tab === 'ФОП' && x.row === 2).cells[7];
  // A later pending application must not change the decision-derived H supplied by the API.
  existing.last_application_date = '2026-09-25';
  plan = f.context.pqmGooglePlan_(f.body, f.context.pqmGoogleSnapshot_('sandbox-id'));
  assert.equal(plan.changes.find(x => x.tab === 'ФОП' && x.row === 2).cells[7], before);
});

test('morning I/L planner keeps the evidence pair chronological and preserves Google same-day corrections', () => {
  const cases = [
    {name: 'Google blank', google: '', googleOfficer: '', pqm: '2026-09-20', pqmOfficer: 'Officer A',
      planned: true, reason: 'google_blank_filled'},
    {name: 'PQM newer', google: '2026-06-05', googleOfficer: 'Officer B', pqm: '2026-09-20', pqmOfficer: 'Officer A',
      planned: true, reason: 'pqm_newer_written'},
    {name: 'same pair', google: '2026-09-20', googleOfficer: 'Officer A', pqm: '2026-09-20', pqmOfficer: 'Officer A',
      planned: false, reason: 'same_date_equivalent'},
    {name: 'same-day Google officer', google: '2026-09-20', googleOfficer: 'Officer B', pqm: '2026-09-20', pqmOfficer: 'Officer A',
      planned: false, reason: 'same_date_google_officer_preserved'},
    {name: 'Google newer', google: '2026-09-25', googleOfficer: 'Officer B', pqm: '2026-09-20', pqmOfficer: 'Officer A',
      planned: false, reason: 'google_newer_preserved'},
    {name: 'PQM blank', google: '2026-09-25', googleOfficer: 'Officer B', pqm: null, pqmOfficer: null,
      planned: false, reason: 'pqm_blank_google_preserved'}
  ];
  for (const item of cases) {
    const f = fixture(), incoming = f.body.items[0];
    f.context.PQM_SANDBOX_FULL_CHUNK_MAX_CELLS = 6;
    incoming.verification_date = item.pqm;
    incoming.verification_officer = item.pqmOfficer;
    setGoogleCell(f, 8, item.google ? f.context.pqmGoogleDate_(item.google) : '');
    setGoogleCell(f, 11, item.googleOfficer);
    const original = clone([f.raw.get('1:2')[8], f.raw.get('1:2')[11]]);
    const preview = f.context.pqmSandboxFullApplyPreview();
    assert.equal(preview.verification_pair_decisions[item.reason], 1, item.name + ' preview reason');
    const plan = f.context.pqmGooglePlan_(f.body, f.context.pqmGoogleSnapshot_('sandbox-id'));
    const change = plan.changes.find(x => x.tab === 'ФОП' && x.row === 2);
    assert.equal(Object.prototype.hasOwnProperty.call(change.cells, '8'), item.planned, item.name + ' I');
    assert.equal(Object.prototype.hasOwnProperty.call(change.cells, '11'), item.planned, item.name + ' L');
    assert.equal(plan.counts[item.reason], 1, item.name + ' reason');
    arm(f, preview);
    const applied = f.context.pqmSandboxFullApply();
    assert.equal(applied.status, 'COMPLETE', item.name);
    if (!item.planned) assert.deepEqual(clone([f.raw.get('1:2')[8], f.raw.get('1:2')[11]]), original, item.name);
    else {
      assert.equal(f.raw.get('1:2')[8].effectiveValue.numberValue, f.context.pqmGoogleDate_(item.pqm), item.name);
      assert.equal(f.raw.get('1:2')[11].effectiveValue.stringValue, item.pqmOfficer, item.name);
    }
  }
});

test('invalid Google/PQM verification dates fail closed before any write', () => {
  for (const origin of ['Google', 'PQM']) {
    const f = fixture();
    f.body.items[0].verification_date = origin === 'PQM' ? 'bad-date' : '2026-09-20';
    f.body.items[0].verification_officer = 'Officer A';
    setGoogleCell(f, 8, origin === 'Google' ? 'bad-date' : f.context.pqmGoogleDate_('2026-09-19'));
    assert.throws(() => f.context.pqmSandboxFullApplyPreview(), /BLOCKED_/);
    assert.equal(f.writes, 0);
  }
});

test('morning writer preserves Google G/J/K/M and explicit no-information E', () => {
  const f = fixture();
  for (const [column, value] of [[6, 'G'], [9, '2026-09-20'], [10, 'K'], [12, 'M'], [4, 'Немає інформації']]) {
    setGoogleCell(f, column, value);
  }
  f.body.items[0].edr_status_current = 'Зареєстровано';
  const before = clone([6, 9, 10, 12, 4].map(c => f.raw.get('1:2')[c]));
  const preview = f.context.pqmSandboxFullApplyPreview();
  arm(f, preview);
  assert.equal(f.context.pqmSandboxFullApply().status, 'COMPLETE');
  assert.deepEqual(clone([6, 9, 10, 12, 4].map(c => f.raw.get('1:2')[c])), before);
  assert.ok(f.requests.flat().every(request => ![6, 9, 10, 12].includes(request.updateCells.range.startColumnIndex)));
});

test('four Apps Script sources parse together; Full Preview is aggregate-only and zero-write', () => {
  const f = fixture(), p = f.context.pqmSandboxFullApplyPreview();
  assert.equal(p.google_writes, 0);
  assert.equal(p.total_pqm_suppliers, 8);
  assert.equal(p.matched, 8);
  assert.equal(p.skipped, 0);
  assert.equal(p.appended + p.conflicts + p.duplicate_keys + p.errors, 0);
  assert.equal(p.total_planned_cells, 24);
  assert.deepEqual(Object.fromEntries(Object.entries(p.changes_by_column)), {C: 8, E: 0, F: 8, H: 8, I: 0, L: 0});
  assert.equal(f.writes, 0);
  assert.equal(JSON.stringify(p).includes('verified-name'), false);
  assert.equal(JSON.stringify(p).includes(f.body.items[0].supplier_code), false);
});

test('expanded impact Preview is aggregate-only, zero-write and exposes blockers', () => {
  const f = fixture();
  f.body.items[0].edr_status_current = 'Зареєстровано';
  f.body.items[0].verification_date = '2026-09-23';
  f.body.items[0].verification_officer = 'verified officer';
  const impact = f.context.pqmSandboxExpandedImpactPreview();
  assert.deepEqual(Object.fromEntries(Object.entries(impact.changes_by_column)),
    {C: 8, E: 1, F: 8, H: 8, I: 1, L: 1});
  assert.equal(impact.total_planned_matched_cells, 27);
  assert.equal(impact.a_writes, 0);
  assert.equal(impact.formulas_touched, 0);
  assert.equal(impact.full_apply_blocked, false);
  assert.equal(f.writes, 0);
  assert.equal(JSON.stringify(impact).includes('verified officer'), false);
  f.body.items.push({...f.body.items[0], supplier_code: 'new-supplier'});
  f.body.count++;
  assert.equal(f.context.pqmSandboxExpandedImpactPreview().full_apply_blocked, true);
  assert.equal(f.writes, 0);
});

test('full preview blocks append, conflict, duplicate and planner error', () => {
  const types = ['appended', 'conflicts', 'duplicate_keys', 'errors'];
  types.forEach(type => {
    const f = fixture(), original = f.context.pqmGooglePlan_;
    f.context.pqmGooglePlan_ = (body, tabs) => {
      const p = original(body, tabs); p.counts[type]++; return p;
    };
    assert.throws(() => f.context.pqmSandboxFullApplyPreview(), /BLOCKED_/);
    assert.equal(f.writes, 0);
  });
});

test('cancelled confirmation and stale digest cause zero writes', () => {
  const f = fixture(), p = f.context.pqmSandboxFullApplyPreview();
  f.setPrompts([response(p.plan_digest)]);
  assert.equal(f.context.pqmSandboxFullApply().google_writes, 0);
  f.setPrompts([response('x'.repeat(43))]); f.confirm('YES');
  assert.throws(() => f.context.pqmSandboxFullApply(), /PLAN_OR_GOOGLE_STATE_CHANGED/);
  assert.equal(f.writes, 0);
});

test('current PQM payload drift invalidates the old Preview before first write', () => {
  const f = fixture(), preview = f.context.pqmSandboxFullApplyPreview();
  f.body.items[0].supplier_name = 'different';
  arm(f, preview);
  assert.throws(() => f.context.pqmSandboxFullApply(), /PLAN_OR_GOOGLE_STATE_CHANGED/);
  assert.equal(f.writes, 0);
});

test('same full business state yields a deterministic digest despite generated_at', () => {
  const f = fixture();
  f.body.generated_at = 'first';
  const a = f.context.pqmSandboxFullApplyPreview();
  f.body.generated_at = 'second';
  const b = f.context.pqmSandboxFullApplyPreview();
  assert.equal(a.plan_digest, b.plan_digest);
  assert.equal(f.writes, 0);
});

test('freshness-marker-only PQM change does not alter Full Preview or create A writes', () => {
  const f = fixture(), before = f.context.pqmSandboxFullApplyPreview();
  f.body.items[0].freshness_marker = 'different';
  const after = f.context.pqmSandboxFullApplyPreview();
  assert.equal(after.plan_digest, before.plan_digest);
  assert.equal(after.total_planned_cells, before.total_planned_cells);
  assert.equal(Object.hasOwn(after.changes_by_column, 'A'), false);
  assert.equal(f.writes, 0);
});

test('state change before first chunk causes zero writes', () => {
  const f = fixture(), p = f.context.pqmSandboxFullApplyPreview();
  const cell = f.raw.get('1:2')[0];
  f.beforeRead(n => {if (n === 1) {cell.userEnteredValue.stringValue = 'edited'; cell.effectiveValue.stringValue = 'edited';}});
  arm(f, p);
  const report = f.context.pqmSandboxFullApply();
  assert.equal(report.status, 'CHUNK_FAILED_NEW_PREVIEW_REQUIRED');
  assert.equal(report.cells_written, 0);
  assert.equal(f.writes, 0);
});

test('state change between chunks stops remaining writes', () => {
  const f = fixture(), p = f.context.pqmSandboxFullApplyPreview();
  f.afterWrite(n => {
    if (n === 1) {const cell = f.raw.get('1:3')[3]; cell.userEnteredValue.stringValue = 'external'; cell.effectiveValue.stringValue = 'external';}
  });
  arm(f, p);
  const report = f.context.pqmSandboxFullApply();
  assert.equal(report.status, 'CHUNK_FAILED_NEW_PREVIEW_REQUIRED');
  assert.equal(report.chunks_completed, 1);
  assert.equal(f.writes, 1);
  assert.ok(report.remaining_cells > 0);
});

test('post-write verification detects changed A and stops further chunks', () => {
  const f = fixture(), p = f.context.pqmSandboxFullApplyPreview();
  f.afterWrite(n => {if (n === 1) f.raw.get('1:2')[0].userEnteredValue.stringValue = 'external';});
  arm(f, p);
  const report = f.context.pqmSandboxFullApply();
  assert.equal(report.status, 'VERIFICATION_FAILED_NEW_PREVIEW_REQUIRED');
  assert.equal(f.writes, 1);
  assert.ok(report.failures > 0);
  assert.equal(report.chunks_completed, 0);
});

test('targeted readback detects validation or note mutation without bulk snapshot metadata', () => {
  for (const property of ['dataValidation', 'note']) {
    const f = fixture(), p = f.context.pqmSandboxFullApplyPreview();
    f.afterWrite(n => {if (n === 1) f.raw.get('1:2')[3][property] = property === 'note'
      ? 'changed note' : {strict: true};});
    arm(f, p);
    const report = f.context.pqmSandboxFullApply();
    assert.equal(report.status, 'VERIFICATION_FAILED_NEW_PREVIEW_REQUIRED');
    assert.equal(report.chunks_completed, 0);
    assert.equal(f.writes, 1);
  }
});

test('ambiguous batch response reports write uncertainty and requires a new Preview', () => {
  const f = fixture(), p = f.context.pqmSandboxFullApplyPreview();
  const original = f.context.Sheets.Spreadsheets.batchUpdate;
  f.context.Sheets.Spreadsheets.batchUpdate = request => {
    original(request);
    throw new Error('simulated response loss');
  };
  arm(f, p);
  const report = f.context.pqmSandboxFullApply();
  assert.equal(report.status, 'WRITE_OR_READBACK_UNCERTAIN_NEW_PREVIEW_REQUIRED');
  assert.equal(report.cells_attempted, 3);
  assert.equal(report.cells_written, 0, 'confirmed count does not claim uncertain writes');
  assert.equal(f.writes, 1, 'mock may have applied despite the exception');
  assert.equal(f.context.pqmSandboxFullApplyPreview().total_planned_cells, p.total_planned_cells - 3);
});

test('successful run writes only C/F/H in bounded chunks and preserves A and other untouched cells', () => {
  const f = fixture(), p = f.context.pqmSandboxFullApplyPreview();
  const untouched = [...f.raw].map(([key, cells]) => [key, cells.map((cell, column) =>
    [0, 1, 3, 4, 6, 8, 9, 10, 11, 12, 13, 14].includes(column) ? clone(cell) : null)]);
  arm(f, p);
  const report = f.context.pqmSandboxFullApply();
  assert.equal(report.status, 'COMPLETE');
  assert.equal(report.cells_written, 24);
  assert.equal(report.cells_verified, 24);
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
  assert.equal(f.context.pqmSandboxFullApplyPreview().total_planned_cells, 0);
});

test('expanded Full Apply writes E/I/L with C/F/H and preserves every untouched cell', () => {
  const f = fixture();
  f.context.PQM_SANDBOX_FULL_CHUNK_MAX_CELLS = 400;
  f.body.items[0].edr_status_current = 'Зареєстровано';
  f.body.items[0].verification_date = '2026-09-23';
  f.body.items[0].verification_officer = 'verified officer';
  const before = clone(f.raw.get('1:2'));
  const preview = f.context.pqmSandboxFullApplyPreview();
  assert.deepEqual(Object.fromEntries(Object.entries(preview.changes_by_column)),
    {C: 8, E: 1, F: 8, H: 8, I: 1, L: 1});
  arm(f, preview);
  const result = f.context.pqmSandboxFullApply();
  assert.equal(result.status, 'COMPLETE');
  assert.equal(result.cells_written, 27);
  assert.equal(result.cells_verified, 27);
  assert.equal(f.context.pqmSandboxFullApplyPreview().total_planned_cells, 0);
  for (const column of [0, 1, 3, 6, 9, 10, 12, 13, 14]) {
    assert.deepEqual(f.raw.get('1:2')[column], before[column]);
  }
  assert.ok(f.requests.flat().every(request => [2, 4, 5, 7, 8, 11].includes(request.updateCells.range.startColumnIndex)));
  const dateWrite = f.requests.flat().find(request => request.updateCells.range.startColumnIndex === 8);
  assert.equal(dateWrite.updateCells.rows[0].values[0].userEnteredValue.numberValue,
    f.context.pqmGoogleDate_('2026-09-23'));
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
  const preview = f.context.pqmSandboxFullApplyPreview();
  assert.equal(preview.changes_by_column.E + preview.changes_by_column.I + preview.changes_by_column.L, 0);
  arm(f, preview);
  assert.equal(f.context.pqmSandboxFullApply().status, 'COMPLETE');
  assert.deepEqual(clone([row[4], row[8], row[11]]), original);

  const g = fixture(), stale = g.context.pqmSandboxFullApplyPreview();
  g.beforeRead(n => {if (n === 1) g.raw.get('1:2')[8].userEnteredFormat = {numberFormat: {pattern: 'yyyy-mm-dd'}};});
  arm(g, stale);
  assert.equal(g.context.pqmSandboxFullApply().status, 'CHUNK_FAILED_NEW_PREVIEW_REQUIRED');
  assert.equal(g.writes, 0);
});

test('PQM snapshot remains frozen within one Apply; next Preview sees later PQM changes', () => {
  const f = fixture(), preview = f.context.pqmSandboxFullApplyPreview();
  f.afterWrite(n => {if (n === 1) f.body.items[7].supplier_name = 'later-verified-name';});
  arm(f, preview);
  const report = f.context.pqmSandboxFullApply();
  assert.equal(report.status, 'COMPLETE');
  assert.equal(f.fetches, 2, 'no hidden refetch during chunks');
  assert.equal(f.context.pqmSandboxFullApplyPreview().total_planned_cells, 1,
    'fresh Preview plans the one new business difference');
  assert.equal(f.fetches, 3);
});

test('blank PQM C and H preserve Google values', () => {
  const f = fixture(), code = f.body.items[0].supplier_code;
  f.body.items[0].supplier_name = null;
  f.body.items[0].last_application_date = null;
  f.body.items[0].google_sync_last_decided_application_date = null;
  const originalC = clone(f.raw.get('1:2')[2]), originalH = clone(f.raw.get('1:2')[7]);
  const p = f.context.pqmSandboxFullApplyPreview();
  assert.equal(p.total_planned_cells, 22);
  arm(f, p);
  assert.equal(f.context.pqmSandboxFullApply().status, 'COMPLETE');
  assert.deepEqual(f.raw.get('1:2')[2], originalC);
  assert.deepEqual(f.raw.get('1:2')[7], originalH);
  assert.ok(f.body.items.some(x => x.supplier_code === code));
});

test('new Preview after partial success plans only remaining differences', () => {
  const f = fixture(), initial = f.context.pqmSandboxFullApplyPreview();
  f.afterWrite(n => {if (n === 1) {const cell = f.raw.get('1:3')[3]; cell.userEnteredValue.stringValue = 'external'; cell.effectiveValue.stringValue = 'external';}});
  arm(f, initial);
  const stopped = f.context.pqmSandboxFullApply();
  assert.equal(stopped.chunks_completed, 1);
  const next = f.context.pqmSandboxFullApplyPreview();
  assert.equal(next.total_planned_cells, initial.total_planned_cells - 3);
  assert.notEqual(next.plan_digest, initial.plan_digest);
  const changed = f.raw.get('1:3')[3];
  changed.userEnteredValue.stringValue = '';
  changed.effectiveValue.stringValue = '';
  const resumed = f.context.pqmSandboxFullApplyPreview();
  arm(f, resumed);
  assert.equal(f.context.pqmSandboxFullApply().status, 'COMPLETE');
  assert.equal(f.context.pqmSandboxFullApplyPreview().total_planned_cells, 0);
});

test('time budget and lock fail closed before any write', () => {
  const f = fixture(), preview = f.context.pqmSandboxFullApplyPreview();
  f.context.PQM_SANDBOX_FULL_RUN_BUDGET_MS = -1;
  arm(f, preview);
  const stopped = f.context.pqmSandboxFullApply();
  assert.equal(stopped.status, 'TIME_BUDGET_STOP_NEW_PREVIEW_REQUIRED');
  assert.equal(f.writes, 0);
  assert.equal(stopped.remaining_cells, preview.total_planned_cells);
  f.context.LockService = {getScriptLock: () => ({tryLock: () => false})};
  arm(f, preview);
  assert.throws(() => f.context.pqmSandboxFullApply(), /another operation/);
  assert.equal(f.writes, 0);
});

test('default bounded chunks allow at most 200 rows and 400 planned cells', () => {
  const f = fixture();
  f.context.PQM_SANDBOX_FULL_CHUNK_MAX_CELLS = 400;
  f.context.PQM_SANDBOX_FULL_CHUNK_MAX_ROWS = 200;
  const entries = Array.from({length: 301}, (_, index) => ({
    row: index + 2, columns: index % 2 ? [2, 5, 7] : [2]
  }));
  const chunks = f.context.pqmSandboxFullChunks_(entries);
  assert.ok(chunks.length > 1);
  assert.ok(chunks.every(chunk => chunk.length <= 200 &&
    chunk.reduce((n, entry) => n + entry.columns.length, 0) <= 400));
  assert.equal(chunks.flat().length, entries.length);
  assert.equal(f.writes, 0);
});

test('sandbox host and token guards remain the only source of registry credentials', () => {
  const context = {Date, Map, Set, console: {log: () => {}}};
  vm.createContext(context); vm.runInContext(source, context);
  let property = null, fetched = false;
  context.PropertiesService = {getScriptProperties: () => ({getProperty: key => {
    property = key; return 'sandbox-only-token';
  }})};
  context.UrlFetchApp = {fetch: (url, options) => {
    fetched = true;
    assert.equal(new URL(url).host, 'pqm-sandbox.onrender.com');
    assert.equal(options.followRedirects, false);
    return {getResponseCode: () => 200, getContentText: () => JSON.stringify({count: 0, items: []})};
  }};
  context.pqmSandboxFetchRegistry_();
  assert.equal(property, 'PQM_SANDBOX_SUPPLIER_REGISTRY_TOKEN');
  assert.equal(fetched, true);
  context.PQM_SANDBOX_FULL_REGISTRY_URL = 'https://pqm-production-1.onrender.com/api/integrations/suppliers/full-registry';
  fetched = false;
  assert.throws(() => context.pqmSandboxFetchRegistry_(), /endpoint guard/);
  assert.equal(fetched, false);
});
