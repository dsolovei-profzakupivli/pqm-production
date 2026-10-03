const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = ['PqmSandboxPreviewDependencies.gs', 'PqmSandboxAppendApply.gs']
  .map(name => fs.readFileSync(path.join(__dirname, name), 'utf8')).join('\n');
const context = {Date, Map, Set};
vm.createContext(context);
vm.runInContext(source, context);

test('physical writer allowlist is default-deny for every future column', () => {
  for (const column of [0, 6, 9, 10, 12, 13, 14, 15, 25]) {
    assert.throws(() => context.pqmGoogleValidateWriteSet_([
      {tab: 'ЮО', row: 2, append: true, cells: {[column]: 'forbidden'}}
    ]), /forbidden planned column/);
  }
});

test('B is APPEND-only and the other approved columns still need their field guards', () => {
  assert.throws(() => context.pqmGoogleValidateWriteSet_([
    {tab: 'ЮО', row: 2, append: false, cells: {1: '12345678'}}
  ]), /forbidden planned column/);
  assert.equal(context.pqmGoogleValidateWriteSet_([
    {tab: 'ЮО', row: 2, append: true, cells: {1: '12345678', 2: 'Name', 3: 'Manager',
      4: 'Зареєстровано', 5: 'Активний', 7: 1, 8: 1, 11: 'Officer'}}
  ]), true);
});

test('APPEND request guard rejects forbidden value, formatting, validation and conditional metadata', () => {
  for (const pasteType of ['PASTE_FORMAT', 'PASTE_DATA_VALIDATION']) {
    assert.throws(() => context.pqmSandboxAppendValidateRequests_([{copyPaste: {
      source: {startColumnIndex: 0, endColumnIndex: 1},
      destination: {startColumnIndex: 0, endColumnIndex: 1}, pasteType}}]),
    /forbidden column metadata write/);
  }
  assert.throws(() => context.pqmSandboxAppendValidateRequests_([{updateCells: {
    range: {startColumnIndex: 13, endColumnIndex: 14}, rows: []}}]),
  /forbidden column metadata write/);
  assert.throws(() => context.pqmSandboxAppendValidateRequests_([{updateConditionalFormatRule: {
    rule: {ranges: [{startColumnIndex: 2, endColumnIndex: 7}]}}}]),
  /forbidden column metadata write/);
});

function sharedFixture(existing = false) {
  const code = '00000001', values = Array(15).fill('');
  if (existing) {
    values[1] = code; values[2] = 'Робоча назва А'; values[3] = 'Керівник А';
    values[4] = '✅ Зареєстровано'; values[5] = '✅ Активний';
    values[7] = context.pqmGoogleDate_('2026-09-01');
    values[8] = context.pqmGoogleDate_('2026-09-02'); values[11] = 'УО А';
    values[13] = 'ЄДР повна назва'; values[14] = 'ЄДР скорочена назва';
  }
  const row = {values, formulas: Array(15).fill(''), codeDisplay: existing ? code : ''};
  const tabs = Object.fromEntries(['ФОП', 'ЮО'].map(name => [name, {
    id: name === 'ЮО' ? 2 : 1, maxRows: 100, headers: [...context.PQM_GOOGLE_HEADERS],
    templateRowHeight: 28, merges: [], protectedRanges: [], conditionalFormats: [],
    rows: name === 'ЮО' ? [row] : [{values: Array(15).fill(''), formulas: Array(15).fill(''), codeDisplay: ''}]
  }]));
  const provenance = (source_type, date, id) => ({source_type, event_date: date,
    source_id: id, confirmed: true, ambiguous: false});
  const state = {supplier_code: code, prozorro_status: 'Активний', conflicts: [],
    manager_for_verification: 'Керівник Б', edr_status: 'Зареєстровано',
    last_application_date: '2026-09-03', verification_date: '2026-09-02',
    verification_officer: 'УО А', latest_submission_name: 'Назва із заявки',
    working_supplier_name: '', working_name_update_confirmed: false,
    provenance: {D: provenance('application_manager', '2026-09-03', 's2'),
      E: provenance('qualification_verification', '2026-09-02', 'q1'),
      I: provenance('qualification_verification', '2026-09-02', 'q1'),
      L: provenance('qualification_verification', '2026-09-02', 'q1')}};
  const item = {supplier_code: code, entity_type: 'legal_entity',
    google_sync_eligible: true, monitoring_eligible: true,
    supplier_name: 'ЄДР повна назва', latest_submission_name: 'Назва із заявки',
    edr_status_current: 'Зареєстровано', prozorro_status_google: '✅ Активний',
    freshness_marker: '', last_application_date: '2026-09-03',
    google_sync_last_decided_application_date: '2026-09-01',
    verification_date: '2026-09-02', verification_officer: 'УО А', shared_projection: state};
  return {body: {count: 1, items: [item]}, tabs, state, item};
}

test('shared APPEND uses latest submission C, confirmed D, factual E, H and one I/L event', () => {
  const f = sharedFixture();
  const plan = context.pqmGooglePlan_(f.body, f.tabs);
  assert.equal(plan.counts.appended, 1);
  assert.deepEqual(Object.keys(plan.changes[0].cells).map(Number).sort((a, b) => a - b),
    [1, 2, 3, 4, 5, 7, 8, 11]);
  assert.equal(plan.changes[0].cells[2], 'Назва із заявки');
  assert.equal(plan.changes[0].cells[3], 'Керівник Б');
  assert.equal(plan.changes[0].cells[7], context.pqmGoogleDate_('2026-09-03'));
});

test('shared UPDATE writes newer application D and latest H, but never N/O or format-only F/E', () => {
  const f = sharedFixture(true);
  const plan = context.pqmGooglePlan_(f.body, f.tabs);
  assert.deepEqual(Object.keys(plan.changes[0].cells).map(Number).sort((a, b) => a - b), [3, 7]);
  f.state.working_supplier_name = 'Робоча назва Б';
  f.state.working_name_update_confirmed = true;
  const rename = context.pqmGooglePlan_(f.body, f.tabs);
  assert.deepEqual(Object.keys(rename.changes[0].cells).map(Number).sort((a, b) => a - b), [2, 3, 7]);
  f.state.provenance.D.event_date = '2026-09-02';
  const preserved = context.pqmGooglePlan_(f.body, f.tabs);
  assert.deepEqual(Object.keys(preserved.changes[0].cells).map(Number).sort((a, b) => a - b), [2, 7]);
});

test('shared APPEND converges and unknown legacy F does not receive implicit mapping', () => {
  const f = sharedFixture();
  const first = context.pqmGooglePlan_(f.body, f.tabs).changes[0];
  const row = f.tabs['ЮО'].rows[0];
  row.values[1] = first.cells[1]; row.codeDisplay = first.cells[1];
  Object.entries(first.cells).forEach(([column, value]) => { row.values[Number(column)] = value; });
  const again = context.pqmGooglePlan_(f.body, f.tabs);
  assert.equal(again.counts.unchanged, 1);
  assert.equal(again.changes.length, 0);
  row.values[5] = 'old-status';
  const legacy = context.pqmGooglePlan_(f.body, f.tabs);
  assert.equal(legacy.counts.conflicts, 1);
  assert.equal(legacy.changes.length, 0);
});
