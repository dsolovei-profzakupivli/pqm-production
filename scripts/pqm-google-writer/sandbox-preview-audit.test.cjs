const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(__dirname + '/PqmSandboxPreviewDependencies.gs', 'utf8');
const context = {};
vm.createContext(context);
vm.runInContext(source, context);

function row(code, values) {
  const result = Array(15).fill('');
  result[1] = code;
  Object.assign(result, values || {});
  return {values: result, formulas: Array(15).fill(''), codeDisplay: code, dateFormat: 'dd.MM.yyyy'};
}
function tabs() {
  return Object.fromEntries(['ФОП', 'ЮО'].map((name, index) => [name, {
    id: index + 1, maxRows: 10, templateRowHeight: 20,
    headers: Array.from(context.PQM_GOOGLE_HEADERS), rows: [],
    merges: [], protectedRanges: [], conditionalFormats: []
  }]));
}
function body(items) { return {count: items.length, items}; }
function item(overrides) {
  return Object.assign({supplier_code: '1000000000', entity_type: 'individual_entrepreneur',
    supplier_name: 'Name', monitoring_eligible: true, google_sync_eligible: true,
    freshness_marker: 'fresh',
    edr_status_current: null, verification_date: null, verification_officer: null,
    prozorro_status_google: 'Active', last_application_date: '2026-09-22',
    google_sync_last_decided_application_date: '2026-09-22'}, overrides || {});
}

test('aggregate diagnostic counts only columns and types, never cell values', () => {
  const fixture = tabs();
  fixture['ФОП'].rows.push(row('1000000000', {0: 'old', 2: 'Name', 5: 'old', 7: 46287}));
  fixture['ЮО'].rows.push(row('20000000', {0: 'fresh', 2: 'Same', 5: 'Active', 7: 46287}));
  const plan = context.pqmGooglePlan_(body([
    item(),
    item({supplier_code: '20000000', entity_type: 'legal_entity', supplier_name: 'Same', last_application_date: '2026-09-22'})
  ]), fixture);
  const aggregate = context.pqmGooglePlanAggregate_(plan);
  const comparison = context.pqmGooglePlanComparisonAudit_(plan, fixture);
  assert.deepEqual(JSON.parse(JSON.stringify(aggregate.by_column)), {F: 1});
  assert.deepEqual(JSON.parse(JSON.stringify(aggregate.by_action)), {update: 1});
  assert.deepEqual(JSON.parse(JSON.stringify(aggregate.by_combination)), {F: 1});
  assert.equal(aggregate.unchanged, 1);
  assert.equal(comparison.value_mismatch, 1);
  assert.equal(comparison.date_format_only, 0);
  assert.equal(comparison.planned_matched_cells, comparison.value_mismatch + comparison.date_format_only);
  assert.equal(comparison.planned_append_cells, 0);
  assert.deepEqual(Object.keys(comparison.current_value_types).sort(), ['F:string']);
  assert.equal(JSON.stringify({aggregate, comparison}).includes('1000000000'), false);
  assert.equal(JSON.stringify({aggregate, comparison}).includes('Name'), false);
});

test('serial and dd.MM.yyyy representations of the same date are unchanged', () => {
  const fixture = tabs();
  const r = row('1000000000', {0: 'fresh', 2: 'Name', 5: 'Active', 7: 46287});
  r.dateFormat = 'yyyy-mm-dd';
  fixture['ФОП'].rows.push(r);
  const plan = context.pqmGooglePlan_(body([item()]), fixture);
  assert.equal(plan.counts.unchanged, 1);
  assert.equal(plan.changes.length, 0);
  r.values[7] = '22.09.2026';
  assert.equal(context.pqmGooglePlan_(body([item()]), fixture).counts.unchanged, 1);
});

test('freshness marker alone never updates an existing supplier or enters diagnostics', () => {
  const fixture = tabs();
  fixture['ФОП'].rows.push(row('1000000000', {0: 'old marker', 2: 'Name', 5: 'Active', 7: 46287}));
  const plan = context.pqmGooglePlan_(body([item({freshness_marker: 'new marker'})]), fixture);
  assert.equal(plan.counts.matched, 1);
  assert.equal(plan.counts.updated, 0);
  assert.equal(plan.counts.unchanged, 1);
  assert.equal(plan.changes.length, 0);
  assert.deepEqual(JSON.parse(JSON.stringify(context.pqmGooglePlanAggregate_(plan).by_column)), {});
  assert.equal(context.pqmGooglePlanComparisonAudit_(plan, fixture).planned_matched_cells, 0);
});

test('append proposes B/C/F/H only and leaves A blank', () => {
  const fixture = tabs();
  fixture['ФОП'].rows.push(row('9999999999', {0: 'template'}));
  const plan = context.pqmGooglePlan_(body([item()]), fixture);
  assert.equal(plan.counts.appended, 1);
  assert.deepEqual(Object.keys(plan.changes[0].cells), ['1', '2', '5', '7']);
  assert.equal(Object.hasOwn(plan.changes[0].cells, '0'), false);
});

test('different, blank, and invalid date values remain safe', () => {
  const fixture = tabs();
  fixture['ФОП'].rows.push(row('1000000000', {0: 'fresh', 2: 'Name', 5: 'Active', 7: 46286}));
  let plan = context.pqmGooglePlan_(body([item()]), fixture);
  assert.deepEqual(Object.keys(plan.changes[0].cells), ['7']);
  plan = context.pqmGooglePlan_(body([item({google_sync_last_decided_application_date: null})]), fixture);
  assert.equal(plan.counts.unchanged, 1);
  plan = context.pqmGooglePlan_(body([item({google_sync_last_decided_application_date: '2026-02-30'})]), fixture);
  assert.equal(plan.counts.errors, 1);
  assert.equal(plan.changes.length, 0);
  fixture['ФОП'].rows[0].values[7] = 'not-a-date';
  plan = context.pqmGooglePlan_(body([item()]), fixture);
  assert.deepEqual(Object.keys(plan.changes[0].cells), ['7']);
  const appsScriptDate = vm.runInContext('new Date(Date.UTC(2026, 8, 22))', context);
  assert.deepEqual(JSON.parse(JSON.stringify(context.pqmGoogleCalendarDate_(appsScriptDate))),
    {kind: 'date', value: '2026-09-22'});
  assert.deepEqual(JSON.parse(JSON.stringify(context.pqmGoogleCalendarDate_('01/02/2026'))),
    {kind: 'invalid', value: null});
});

test('representative old and optimized snapshot contracts plan identically', () => {
  const oldContract = tabs();
  oldContract['ФОП'].rows.push(row('1000000000', {0: 'fresh', 2: 'Name', 5: 'Active', 7: 46287}));
  const optimizedContract = JSON.parse(JSON.stringify(oldContract));
  const payload = body([item()]);
  assert.deepEqual(
    JSON.parse(JSON.stringify(context.pqmGooglePlan_(payload, oldContract))),
    JSON.parse(JSON.stringify(context.pqmGooglePlan_(payload, optimizedContract)))
  );
});

test('Phase 1 E is authoritative in both directions; blank E/I/L preserve', () => {
  const fixture = tabs();
  const current = row('1000000000', {2: 'Name', 4: 'Припинено', 5: 'Active',
    7: 46287, 8: 46287, 11: 'existing officer'});
  fixture['ФОП'].rows.push(current);
  let plan = context.pqmGooglePlan_(body([item({edr_status_current: 'Зареєстровано',
    verification_date: '2026-09-22', verification_officer: 'existing officer'})]), fixture);
  assert.deepEqual(Object.keys(plan.changes[0].cells), ['4']);
  current.values[4] = 'Зареєстровано';
  plan = context.pqmGooglePlan_(body([item({edr_status_current: 'Неактуально'})]), fixture);
  assert.deepEqual(Object.keys(plan.changes[0].cells), ['4']);
  assert.equal(plan.changes[0].cells[4], 'Неактуально');
  plan = context.pqmGooglePlan_(body([item({edr_status_current: 'Припинено'})]), fixture);
  assert.equal(plan.changes[0].cells[4], 'Припинено');
  plan = context.pqmGooglePlan_(body([item({edr_status_current: null,
    verification_date: null, verification_officer: null})]), fixture);
  assert.equal(plan.counts.unchanged, 1);
  assert.equal(plan.changes.length, 0);
});

test('Google Немає інформації is preserved while ordinary E transitions still plan', () => {
  const fixture = tabs();
  const current = row('1000000000', {2:'Name', 4:'Немає інформації',
    5:'Active', 7:46287});
  fixture['ФОП'].rows.push(current);
  for (const source of ['Немає інформації', '🟡 Немає   інформації']) {
    current.values[4] = source;
    for (const pqm of ['Зареєстровано', 'Неактуально']) {
      const plan = context.pqmGooglePlan_(body([item({edr_status_current:pqm})]), fixture);
      assert.equal(plan.changes.some(change => Object.prototype.hasOwnProperty.call(change.cells, '4')), false);
      assert.equal(plan.counts.errors, 0);
    }
  }
  for (const [google,pqm] of [
    ['Неактуально','Зареєстровано'],
    ['Зареєстровано','Неактуально'],
    ['Припинено','Неактуально']]) {
    current.values[4] = google;
    const plan = context.pqmGooglePlan_(body([item({edr_status_current:pqm})]), fixture);
    assert.equal(plan.changes[0].cells[4], pqm);
  }
});

test('current E vocabulary, emoji equivalence, and unknown PQM status fail closed', () => {
  const allowed = ['Неактуально', 'Зареєстровано', 'Припинено',
    'В стані припинення', 'Порушено справу про банкрутство', 'Банкрут'];
  for (const status of allowed) {
    const fixture = tabs();
    fixture['ФОП'].rows.push(row('1000000000', {2:'Name', 4:'🔴 '+status,
      5:'Active', 7:46287}));
    const same = context.pqmGooglePlan_(body([item({edr_status_current:status})]), fixture);
    assert.equal(same.changes.length, 0, status);
    fixture['ФОП'].rows[0].values[4] = 'Припинено';
    const changed = context.pqmGooglePlan_(body([item({edr_status_current:status})]), fixture);
    if (status === 'Припинено') assert.equal(changed.changes.length, 0);
    else assert.equal(changed.changes[0].cells[4], status);
  }
  for (const prior of ['Припинено', 'В стані припинення',
    'Порушено справу про банкрутство']) {
    const fixture = tabs();
    fixture['ФОП'].rows.push(row('1000000000', {2:'Name', 4:prior,
      5:'Неактивний', 7:46287}));
    const plan = context.pqmGooglePlan_(body([item({edr_status_current:'Неактуально',
      prozorro_status_google:'Неактивний'})]), fixture);
    assert.equal(plan.changes[0].cells[4], 'Неактуально');
  }
  const notRegistered = tabs();
  notRegistered['ФОП'].rows.push(row('1000000000', {2:'Name',
    4:'Порушено справу про банкрутство', 5:'Ще не в реєстрі', 7:46287}));
  const notRegisteredPlan = context.pqmGooglePlan_(body([item({
    edr_status_current:'Неактуально', prozorro_status_google:'Ще не в реєстрі'})]),
    notRegistered);
  assert.equal(notRegisteredPlan.changes[0].cells[4], 'Неактуально');
  const fixture = tabs();
  fixture['ФОП'].rows.push(row('1000000000', {2:'Name', 4:'Припинено',
    5:'Active', 7:46287}));
  const rejected = context.pqmGooglePlan_(body([item({edr_status_current:'unknown'})]), fixture);
  assert.equal(rejected.counts.errors, 1);
  assert.equal(rejected.changes.length, 0);
});

test('same-day officer normalization and different Google officer both preserve Google L', () => {
  const fixture = tabs();
  fixture['ФОП'].rows.push(row('1000000000', {2: 'Name', 5: 'Active', 7: 46287,
    8: '22.09.2026', 11: '  Іван   ПЕТРЕНКО '}));
  let plan = context.pqmGooglePlan_(body([item({verification_date: '2026-09-22',
    verification_officer: 'іван петренко'})]), fixture);
  assert.equal(plan.counts.unchanged, 1);
  assert.equal(plan.changes.length, 0);
  plan = context.pqmGooglePlan_(body([item({verification_date: '2026-09-22',
    verification_officer: 'Марія ПЕТРЕНКО'})]), fixture);
  assert.equal(plan.counts.same_date_google_officer_preserved, 1);
  assert.equal(plan.changes.length, 0);
});

test('I/L move only as a valid chronological pair, never from H', () => {
  const fixture = tabs();
  fixture['ФОП'].rows.push(row('1000000000', {2: 'Name', 5: 'Active', 7: 46287,
    8: '22.09.2026', 11: 'old officer'}));
  let plan = context.pqmGooglePlan_(body([item({verification_date: '2026-09-22',
    verification_officer: 'new officer'})]), fixture);
  assert.equal(plan.counts.same_date_google_officer_preserved, 1);
  assert.equal(plan.changes.length, 0);
  plan = context.pqmGooglePlan_(body([item({last_application_date: '2026-09-22',
    verification_date: '2026-09-23', verification_officer: null})]), fixture);
  assert.equal(plan.counts.conflicts, 1);
  assert.equal(plan.changes.length, 0);
  plan = context.pqmGooglePlan_(body([item({verification_date: '2026-09-23',
    verification_officer: 'new officer'})]), fixture);
  assert.deepEqual(Object.keys(plan.changes[0].cells), ['8', '11']);
  assert.equal(plan.changes[0].cells[8], context.pqmGoogleDate_('2026-09-23'));
  plan = context.pqmGooglePlan_(body([item({verification_date: 'not a date'})]), fixture);
  assert.equal(plan.counts.conflicts, 1);
});

test('formula conflicts cover E/I/L and append includes only owned initial B/C/E/F/H/I/L', () => {
  for (const column of [4, 8, 11]) {
    const fixture = tabs();
    const current = row('1000000000', {2: 'Name', 5: 'Active', 7: 46287});
    current.formulas[column] = '=NA()';
    fixture['ФОП'].rows.push(current);
    const plan = context.pqmGooglePlan_(body([item()]), fixture);
    assert.equal(plan.counts.conflicts, 1);
    assert.equal(plan.changes.length, 0);
  }
  const fixture = tabs();
  fixture['ФОП'].rows.push(row('9999999999'));
  const plan = context.pqmGooglePlan_(body([item({edr_status_current: 'Зареєстровано',
    verification_date: '2026-09-22', verification_officer: 'officer'})]), fixture);
  assert.deepEqual(Object.keys(plan.changes[0].cells), ['1', '2', '4', '5', '7', '8', '11']);
});
