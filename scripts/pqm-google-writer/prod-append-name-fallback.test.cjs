const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const context = {Map, Set, Date};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, 'PqmProdPreviewDependencies.gs'), 'utf8'), context);

function tab(id, rows = []) {
  return {id, headers: [...context.PQM_GOOGLE_HEADERS], merges: [], protectedRanges: [],
    templateRowHeight: 25, rows};
}

function row(code, name) {
  const values = Array(15).fill('');
  values[1] = code; values[2] = name; values[5] = 'Активний'; values[7] = '01.10.2026';
  return {values, formulas: Array(15).fill(''), codeDisplay: code};
}

function item(code, overrides = {}) {
  return {supplier_code: code, entity_type: 'legal_entity', monitoring_eligible: true,
    google_sync_eligible: true, supplier_name: '', latest_submission_name: 'Name from latest submission',
    edr_status_current: '', prozorro_status_google: 'Активний', freshness_marker: '',
    last_application_date: '2026-10-01', google_sync_last_decided_application_date: '2026-10-01',
    verification_date: '', verification_officer: '', ...overrides};
}

test('142 append candidates with application names plan B+C+F+H', () => {
  const items = Array.from({length: 142}, (_, i) => item(String(i + 1).padStart(8, '0')));
  const plan = context.pqmGooglePlan_({count: items.length, items}, {
    'ФОП': tab(1, [row('9000000000', 'Template')]),
    'ЮО': tab(2, [row('99999999', 'Template')]),
  });
  assert.equal(plan.counts.safe_append, 142);
  assert.equal(plan.counts.conflict, 0);
  for (const change of plan.changes) {
    assert.equal(change.append, true);
    assert.equal(change.cells[2], 'Name from latest submission');
    assert.deepEqual(Object.keys(change.cells).sort(), ['1', '2', '5', '7']);
  }
});

test('verified name wins on append; missing both names conflicts', () => {
  const items = [item('00000001', {supplier_name: 'Verified EDR name'}),
    item('00000002', {latest_submission_name: ''})];
  const plan = context.pqmGooglePlan_({count: 2, items}, {
    'ФОП': tab(1, [row('9000000000', 'Template')]),
    'ЮО': tab(2, [row('99999999', 'Template')]),
  });
  assert.equal(plan.counts.safe_append, 1);
  assert.equal(plan.counts.conflict, 1);
  assert.equal(plan.changes[0].cells[2], 'Verified EDR name');
  assert.ok(plan.issues.some(issue => issue.reason === 'missing_append_supplier_name' &&
    issue.supplier_code === '00000002'));
});

test('old payload without fallback fails closed for a nameless append', () => {
  const source = item('00000003');
  delete source.latest_submission_name;
  const plan = context.pqmGooglePlan_({count: 1, items: [source]}, {
    'ФОП': tab(1, [row('9000000000', 'Template')]),
    'ЮО': tab(2, [row('99999999', 'Template')]),
  });
  assert.equal(plan.counts.safe_append, 0);
  assert.equal(plan.counts.conflict, 1);
  assert.equal(plan.changes.length, 0);
});

test('existing C never updates from latest_submission_name; verified C still can', () => {
  const tabs = {'ФОП': tab(1, [row('9000000000', 'Template')]),
    'ЮО': tab(2, [row('00000001', 'Google C'), row('00000002', 'Old C')])};
  const items = [item('00000001'), item('00000002', {supplier_name: 'Verified EDR name'})];
  const plan = context.pqmGooglePlan_({count: 2, items}, tabs);
  assert.equal(plan.counts.updated, 1);
  assert.equal(plan.counts.unchanged, 1);
  assert.equal(plan.changes[0].append, false);
  assert.deepEqual(Object.keys(plan.changes[0].cells), ['2']);
  assert.equal(plan.changes[0].cells[2], 'Verified EDR name');
});
