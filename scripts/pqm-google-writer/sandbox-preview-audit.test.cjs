const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

const source = ['PqmSandboxPreviewDependencies.gs', 'PqmGoogleBusinessMatrix.gs', 'PqmVerificationDatetime.gs']
  .map(name => fs.readFileSync(__dirname + '/' + name, 'utf8')).join('\n');
const context = {};
vm.createContext(context);
vm.runInContext(source, context);
context.Utilities = {formatDate(date, zone) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {timeZone: zone,
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
    second: '2-digit', hourCycle: 'h23'}).formatToParts(date).map(part => [part.type, part.value]));
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}.000`;
}};

function row(code, values) {
  const result = Array(15).fill('');
  result[1] = code;
  Object.assign(result, values || {});
  return {values: result, formulas: Array(15).fill(''), codeDisplay: code,
    dateFormat: 'dd.MM.yyyy', verificationDateFormat: 'dd.MM.yyyy'};
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
  const result = Object.assign({supplier_code: '1000000000', entity_type: 'individual_entrepreneur',
    classification_version: 'subject-nature-20261030-v2', classification_status: 'resolved',
    classification_reason: 'established_subject_nature', classification_reason_label: 'Тип підтверджено у fixture',
    target_sheet: 'ФОП', append_allowed: true,
    supplier_name: 'Name', monitoring_eligible: true, google_sync_eligible: true,
    google_writer_eligible: true, google_sync_has_active_qualification: true,
    google_sync_has_admission_history: true, google_sync_last_decided_application_decision: 'admit',
    google_sync_last_decided_protocol_at: '', google_sync_last_decided_protocol_officer: '',
    google_sync_last_decided_submission_id: 's1', google_sync_latest_rejection_officer: '',
    freshness_marker: 'fresh',
    edr_status_current: null, verification_date: null, verification_officer: null, verification_event_type: null,
    prozorro_status_google: 'Активний', last_application_date: '2026-09-22',
    google_sync_last_decided_application_date: '2026-09-22'}, overrides || {});
  if (!Object.prototype.hasOwnProperty.call(overrides || {}, 'target_sheet')) {
    result.target_sheet = result.entity_type === 'individual_entrepreneur' ? 'ФОП' :
      result.entity_type === 'legal_entity' ? 'ЮО' : null;
  }
  return result;
}

test('aggregate diagnostic counts only columns and types, never cell values', () => {
  const fixture = tabs();
  fixture['ФОП'].rows.push(row('1000000000', {0: 'old', 2: 'Name', 5: 'Неактивний', 7: 46287}));
  fixture['ЮО'].rows.push(row('20000000', {0: 'fresh', 2: 'Same', 5: 'Активний', 7: 46287}));
  const plan = context.pqmGooglePlan_(body([
    item(),
    item({supplier_code: '20000000', entity_type: 'legal_entity', supplier_name: 'Same', last_application_date: '2026-09-22'})
  ]), fixture);
  const aggregate = context.pqmGooglePlanAggregate_(plan);
  const comparison = context.pqmGooglePlanComparisonAudit_(plan, fixture);
  assert.deepEqual(JSON.parse(JSON.stringify(aggregate.by_column)), {E: 1, F: 1});
  assert.deepEqual(JSON.parse(JSON.stringify(aggregate.by_action)), {update: 1});
  assert.deepEqual(JSON.parse(JSON.stringify(aggregate.by_combination)), {'E+F': 1});
  assert.equal(aggregate.unchanged, 1);
  assert.equal(comparison.value_mismatch, 2);
  assert.equal(comparison.date_format_only, 0);
  assert.equal(comparison.planned_matched_cells, comparison.value_mismatch + comparison.date_format_only);
  assert.equal(comparison.planned_append_cells, 0);
  assert.deepEqual(Object.keys(comparison.current_value_types).sort(), ['E:string', 'F:string']);
  assert.equal(JSON.stringify({aggregate, comparison}).includes('1000000000'), false);
  assert.equal(JSON.stringify({aggregate, comparison}).includes('Name'), false);
});

test('serial and dd.MM.yyyy representations of the same date are unchanged', () => {
  const fixture = tabs();
  const r = row('1000000000', {0: 'fresh', 2: 'Name', 5: 'Активний', 7: 46287});
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
  fixture['ФОП'].rows.push(row('1000000000', {0: 'old marker', 2: 'Name', 5: 'Активний', 7: 46287}));
  const plan = context.pqmGooglePlan_(body([item({freshness_marker: 'new marker'})]), fixture);
  assert.equal(plan.counts.matched, 1);
  assert.equal(plan.counts.updated, 0);
  assert.equal(plan.counts.unchanged, 1);
  assert.equal(plan.changes.length, 0);
  assert.deepEqual(JSON.parse(JSON.stringify(context.pqmGooglePlanAggregate_(plan).by_column)), {});
  assert.equal(context.pqmGooglePlanComparisonAudit_(plan, fixture).planned_matched_cells, 0);
});

test('admission append writes only approved business fields and leaves formula A intact', () => {
  const fixture = tabs();
  const template = row('9999999999', {0: 'template'});
  template.formulas[0] = '=IF(B2="", "", 1)';
  fixture['ФОП'].rows.push(template);
  const plan = context.pqmGooglePlan_(body([item({current_manager_name: 'Manager',
    verification_date: '2026-09-23T10:00:00+03:00', verification_datetime_precision: 'second',
    verification_officer: 'Protocol Officer', verification_event_type: 'admission',
    google_sync_last_decided_protocol_at: '2026-09-23T10:00:00+03:00',
    google_sync_last_decided_protocol_officer: 'Protocol Officer'})]), fixture);
  assert.equal(plan.counts.appended, 1);
  assert.deepEqual(Object.keys(plan.changes[0].cells), ['1', '2', '3', '4', '5', '7', '8', '11']);
  assert.equal(Object.hasOwn(plan.changes[0].cells, '0'), false);
});

test('different, blank, and invalid date values remain safe', () => {
  const fixture = tabs();
  fixture['ФОП'].rows.push(row('1000000000', {0: 'fresh', 2: 'Name', 5: 'Активний', 7: 46286}));
  let plan = context.pqmGooglePlan_(body([item()]), fixture);
  assert.deepEqual(Object.keys(plan.changes[0].cells), ['7']);
  plan = context.pqmGooglePlan_(body([item({google_sync_last_decided_application_date: null})]), fixture);
  assert.equal(plan.counts.unchanged, 1);
  plan = context.pqmGooglePlan_(body([item({google_sync_last_decided_application_date: '2026-02-30'})]), fixture);
  assert.equal(plan.counts.conflicts, 1);
  assert.equal(plan.changes.length, 0);
  fixture['ФОП'].rows[0].values[7] = 'not-a-date';
  plan = context.pqmGooglePlan_(body([item()]), fixture);
  assert.equal(plan.counts.conflicts, 1);
  assert.equal(plan.changes.length, 0);
  const appsScriptDate = vm.runInContext('new Date(Date.UTC(2026, 8, 22))', context);
  assert.deepEqual(JSON.parse(JSON.stringify(context.pqmGoogleCalendarDate_(appsScriptDate))),
    {kind: 'date', value: '2026-09-22'});
  assert.deepEqual(JSON.parse(JSON.stringify(context.pqmGoogleCalendarDate_('01/02/2026'))),
    {kind: 'invalid', value: null});
});

test('representative old and optimized snapshot contracts plan identically', () => {
  const oldContract = tabs();
  oldContract['ФОП'].rows.push(row('1000000000', {0: 'fresh', 2: 'Name', 5: 'Активний', 7: 46287}));
  const optimizedContract = JSON.parse(JSON.stringify(oldContract));
  const payload = body([item()]);
  assert.deepEqual(
    JSON.parse(JSON.stringify(context.pqmGooglePlan_(payload, oldContract))),
    JSON.parse(JSON.stringify(context.pqmGooglePlan_(payload, optimizedContract)))
  );
});

test('qualification transitions update E/F while blank verification evidence preserves I/L', () => {
  const fixture = tabs();
  const current = row('1000000000', {2: 'Name', 4: 'Неактуально', 5: 'Неактивний',
    7: 46287, 8: 46287, 11: 'existing officer'});
  fixture['ФОП'].rows.push(current);
  const reactivated = context.pqmGooglePlan_(body([item({edr_status_current: 'Зареєстровано'})]), fixture);
  assert.equal(reactivated.changes[0].cells[4], 'Зареєстровано');
  assert.equal(reactivated.changes[0].cells[5], 'Активний');
  current.values[4] = reactivated.changes[0].cells[4];
  current.values[5] = reactivated.changes[0].cells[5];
  const inactive = context.pqmGooglePlan_(body([item({google_sync_has_active_qualification: false,
    prozorro_status_google: 'Неактивний'})]), fixture);
  assert.equal(inactive.changes[0].cells[4], 'Неактуально');
  assert.equal(inactive.changes[0].cells[5], 'Неактивний');
  assert.equal(Object.hasOwn(inactive.changes[0].cells, '8'), false);
  assert.equal(Object.hasOwn(inactive.changes[0].cells, '11'), false);
  const withoutEvidence = context.pqmGooglePlan_(body([item({verification_date: null, verification_officer: null})]), fixture);
  assert.equal(Object.hasOwn(withoutEvidence.changes[0]?.cells || {}, '8'), false);
  assert.equal(Object.hasOwn(withoutEvidence.changes[0]?.cells || {}, '11'), false);
});

test('Google Немає інформації is preserved while qualification events change E/F', () => {
  const fixture = tabs();
  const current = row('1000000000', {2:'Name', 4:'Немає інформації',
    5:'Активний', 7:46287});
  fixture['ФОП'].rows.push(current);
  for (const source of ['Немає інформації', '🟡 Немає   інформації']) {
    current.values[4] = source;
    for (const pqm of ['Зареєстровано', 'Неактуально']) {
      const plan = context.pqmGooglePlan_(body([item({edr_status_current:pqm})]), fixture);
      assert.equal(plan.changes.some(change => Object.prototype.hasOwnProperty.call(change.cells, '4')), false);
      assert.equal(plan.counts.errors, 0);
    }
  }
  current.values[4] = 'Неактуально'; current.values[5] = 'Неактивний';
  let plan = context.pqmGooglePlan_(body([item({edr_status_current:'Зареєстровано'})]), fixture);
  assert.equal(plan.changes[0].cells[4], 'Зареєстровано');
  assert.equal(plan.changes[0].cells[5], 'Активний');
  current.values[4] = 'Зареєстровано'; current.values[5] = 'Активний';
  plan = context.pqmGooglePlan_(body([item({google_sync_has_active_qualification:false,
    prozorro_status_google:'Неактивний'})]), fixture);
  assert.equal(plan.changes[0].cells[4], 'Неактуально');
  assert.equal(plan.changes[0].cells[5], 'Неактивний');
});

test('current E vocabulary, emoji equivalence, and unknown PQM status fail closed', () => {
  const allowed = ['Неактуально', 'Зареєстровано', 'Припинено',
    'В стані припинення', 'Порушено справу про банкрутство', 'Банкрут'];
  for (const status of allowed) {
    assert.equal(context.pqmGoogleEdrCurrentStatus_('🔴 '+status), status);
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
    5:'Активний', 7:46287}));
  const rejected = context.pqmGooglePlan_(body([item({edr_status_current:'unknown'})]), fixture);
    assert.equal(rejected.counts.conflicts, 1);
  assert.equal(rejected.changes.length, 0);
});

test('same-day officer normalization and different Google officer both preserve Google L', () => {
  const fixture = tabs();
  fixture['ФОП'].rows.push(row('1000000000', {2: 'Name', 4: 'Зареєстровано', 5: 'Активний', 7: 46287,
    8: '22.09.2026', 11: '  Іван   ПЕТРЕНКО '}));
  let plan = context.pqmGooglePlan_(body([item({verification_date: '2026-09-22',
    verification_officer: 'іван петренко'})]), fixture);
  assert.equal(plan.counts.unchanged, 1);
  assert.equal(plan.changes.length, 0);
  plan = context.pqmGooglePlan_(body([item({verification_date: '2026-09-22',
    verification_officer: 'Марія ПЕТРЕНКО'})]), fixture);
  assert.equal(plan.counts.conflicts, 1);
  assert.ok(plan.issues.some(issue => issue.reason === 'date_only_cannot_prove_verification_order'));
  assert.equal(plan.changes.length, 0);
});

test('D/E/I/L move only as a valid chronological pair, never from H', () => {
  const fixture = tabs();
  const current = row('1000000000', {2: 'Name', 3:'Manager', 4: 'Зареєстровано', 5: 'Активний', 7: 46287,
    8: context.pqmVerificationSerial_(Date.parse('2026-09-22T10:00:00+03:00')), 11: 'old officer'});
  current.verificationDateFormat = 'dd.MM.yyyy HH:mm:ss';
  fixture['ФОП'].rows.push(current);
  let plan = context.pqmGooglePlan_(body([item({current_manager_name:'Manager', edr_status_current:'Зареєстровано',
    verification_date: '2026-09-22T10:00:00+03:00', verification_datetime_precision: 'second',
    verification_event_type:'google_clarity', verification_officer: 'new officer'})]), fixture);
  assert.equal(plan.counts.same_date_google_officer_preserved, 1);
  assert.equal(plan.changes.length, 0);
  plan = context.pqmGooglePlan_(body([item({current_manager_name:'Manager', edr_status_current:'Зареєстровано',
    last_application_date: '2026-09-22',
    verification_date: '2026-09-23T10:00:00+03:00', verification_datetime_precision:'second',
    verification_event_type:'google_clarity', verification_officer: 'Officer New'})]), fixture);
  assert.equal(plan.counts.conflicts, 0);
  assert.equal(context.pqmVerificationDatetime_(plan.changes[0].cells[8]).value,
    Date.parse('2026-09-23T10:00:00+03:00'));
  assert.equal(plan.changes[0].cells[11], 'Officer New');
  plan = context.pqmGooglePlan_(body([item({current_manager_name:'Manager', edr_status_current:'Зареєстровано',
    verification_date: '2026-09-23T10:00:00+03:00', verification_datetime_precision:'second', verification_event_type:'google_clarity',
    verification_officer: 'new officer'})]), fixture);
  assert.deepEqual(Object.keys(plan.changes[0].cells), ['3', '4', '8', '11']);
  assert.equal(context.pqmVerificationDatetime_(plan.changes[0].cells[8]).value,
    Date.parse('2026-09-23T10:00:00+03:00'));
  plan = context.pqmGooglePlan_(body([item({verification_date: 'not a date'})]), fixture);
  assert.equal(plan.counts.conflicts, 1);
});

test('formula conflicts cover D/E/I/L and append includes only approved initial columns', () => {
  for (const column of [3, 4, 8, 11]) {
    const fixture = tabs();
    const current = row('1000000000', {2: 'Name', 5: 'Активний', 7: 46287});
    current.formulas[column] = '=NA()';
    fixture['ФОП'].rows.push(current);
    const plan = context.pqmGooglePlan_(body([item()]), fixture);
    assert.equal(plan.counts.conflicts, 1);
    assert.equal(plan.changes.length, 0);
  }
  const fixture = tabs();
  const template = row('9999999999'); template.formulas[0] = '=IF(B2="", "", 1)';
  fixture['ФОП'].rows.push(template);
  const plan = context.pqmGooglePlan_(body([item({edr_status_current: 'Зареєстровано', current_manager_name:'Manager',
    verification_date: '2026-09-22T10:00:00+03:00', verification_datetime_precision:'second',
    verification_event_type:'admission', verification_officer: 'officer',
    google_sync_last_decided_protocol_at:'2026-09-22T10:00:00+03:00'})]), fixture);
  assert.deepEqual(Object.keys(plan.changes[0].cells), ['1', '2', '3', '4', '5', '7', '8', '11']);
});
