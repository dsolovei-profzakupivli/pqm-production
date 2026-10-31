const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const base = __dirname;
const source = ['PqmSandboxPreviewDependencies.gs', 'PqmGoogleBusinessMatrix.gs',
  'PqmVerificationDatetime.gs', 'PqmSandboxControlledApply.gs', 'PqmSandboxFullApply.gs',
  'PqmSandboxAppendApply.gs'].map(name => fs.readFileSync(path.join(base, name), 'utf8')).join('\n');

function makeItem(overrides = {}) {
  return {supplier_code: '12345678', entity_type: 'legal_entity', monitoring_eligible: true,
    google_sync_eligible: true, google_writer_eligible: true,
    classification_version: 'subject-nature-20261030-v2', classification_status: 'resolved',
    classification_reason: 'established_subject_nature',
    classification_reason_label: 'Тип підтверджено первинними даними або погодженим розглядом',
    target_sheet: 'ЮО', append_allowed: true,
    google_sync_has_active_qualification: false, google_sync_has_admission_history: false,
    supplier_name: 'ТОВ Контроль', latest_submission_name: 'ТОВ Контроль', current_manager_name: 'Керівник А',
    edr_status_current: 'Зареєстровано', prozorro_status_google: 'Неактивний', freshness_marker: '',
    last_application_date: '2026-10-10', google_sync_last_decided_application_date: '2026-10-10',
    google_sync_last_decided_application_decision: 'reject', google_sync_last_decided_protocol_at: '',
    google_sync_last_decided_protocol_officer: 'УО Відхилення', google_sync_last_decided_submission_id: 's1',
    google_sync_latest_rejection_officer: 'УО Відхилення', verification_date: '',
    verification_datetime_precision: '', verification_officer: '', verification_event_type: null,
    ...overrides};
}

function makeTab(name, existing) {
  const row = {values: Array(15).fill(''), formulas: Array(15).fill(''), codeDisplay: '',
    dateFormat: 'dd.MM.yyyy', verificationDateFormat: 'dd.MM.yyyy HH:mm:ss'};
  row.formulas[0] = '=IF(B2="", "", 1)';
  if (existing) {
    Object.assign(row.values, existing.values);
    row.codeDisplay = existing.code;
  } else {
    row.values[1] = '00000001'; row.codeDisplay = '00000001';
  }
  return {id: name === 'ЮО' ? 2 : 1, maxRows: 10, headers: [], rows: [row],
    templateRowHeight: 28, merges: [], protectedRanges: [], conditionalFormats: []};
}

function setup(item, googleRow) {
  const context = {Date, Map, Set, console: {log() {}}, Utilities: {formatDate(date, zone, pattern) {
    assert.ok(zone === 'Europe/Kyiv' || zone === 'Europe/Kiev');
    const parts = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {timeZone: zone,
      year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
      second: '2-digit', hourCycle: 'h23'}).formatToParts(date).map(part => [part.type, part.value]));
    const millis = String(date.getUTCMilliseconds()).padStart(3, '0');
    return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}.${millis}`;
  }}};
  vm.createContext(context); vm.runInContext(source, context);
  context.PQM_GOOGLE_TABS = ['ФОП', 'ЮО'];
  context.pqmGoogleProzorroCategory_ = value => {
    if (value == null || value === '') return '';
    const key = String(value).replace(/^[^\p{L}\p{N}]+/u, '').trim().toLocaleLowerCase('uk-UA');
    return ({'активний': 'active', 'неактивний': 'inactive', 'призупинений': 'suspended',
      'ще не в реєстрі': 'not_yet'})[key] || null;
  };
  context.pqmGoogleProtected_ = () => false;
  const headers = ['Маркер актуальності', 'Код ЄДРПОУ', 'Найменування', 'ПІБ для перевірки',
    'Статус в реєстрі (ЄДР)', 'Статус (Prozorro)', 'Реквізити рішення про припинення',
    'Дата останньої заявки', 'Дата перевірки', 'Дата запису', 'Номер запису', 'УО', 'Примітки',
    'Повна назва з ЄДР', 'Скорочена назва з ЄДР'];
  context.PQM_GOOGLE_HEADERS = headers;
  const values = Array(15).fill('');
  if (googleRow) {
    Object.assign(values, googleRow.values);
    values[1] = googleRow.code;
  }
  const row = {values, formulas: Array(15).fill(''), codeDisplay: googleRow ? googleRow.code : '00000001',
    dateFormat: 'dd.MM.yyyy', verificationDateFormat: googleRow && googleRow.dateFormat || 'dd.MM.yyyy HH:mm:ss'};
  row.formulas[0] = '=IF(B2="", "", 1)';
  const tabs = {ФОП: makeTab('ФОП'), ЮО: {...makeTab('ЮО'), headers,
    rows: googleRow ? [row] : [Object.assign(makeTab('ЮО').rows[0], {values: [...values], formulas: [...row.formulas], codeDisplay: row.codeDisplay})]}};
  tabs.ФОП.headers = headers;
  const body = {count: 1, items: [item]};
  return {context, tabs, body, row: tabs.ЮО.rows[0]};
}

const keys = cells => Object.keys(cells).map(Number).sort((a, b) => a - b);
const allowed = [1, 2, 3, 4, 5, 7, 8, 11];

test('first rejected supplier appends status and rejection UO but leaves I blank', () => {
  const f = setup(makeItem(), null); const plan = f.context.pqmGooglePlan_(f.body, f.tabs);
  assert.equal(plan.counts.appended, 1); const change = plan.changes[0];
  assert.equal(change.cells[4], 'Неактуально'); assert.equal(change.cells[5], 'Ще не в реєстрі');
  assert.equal(change.cells[8], undefined); assert.equal(change.cells[11], 'УО Відхилення');
  assert.ok(keys(change.cells).every(column => allowed.includes(column)));
  const requests = f.context.pqmSandboxAppendRequests_([change], f.tabs);
  assert.ok(requests.some(request => request.copyPaste && request.copyPaste.pasteType === 'PASTE_FORMULA'));
  assert.ok(requests.filter(request => request.updateCells).every(request =>
    allowed.includes(request.updateCells.range.startColumnIndex)));
});

test('monitored supplier without a decided application is skipped, not a blocking conflict', () => {
  const item = makeItem({google_writer_eligible: false, google_sync_eligible: true,
    google_sync_last_decided_application_decision: '', google_sync_last_decided_submission_id: ''});
  const f = setup(item, null); const plan = f.context.pqmGooglePlan_(f.body, f.tabs);
  assert.equal(plan.counts.skipped, 1);
  assert.equal(plan.counts.conflicts, 0);
  assert.equal(plan.changes.length, 0);
  assert.equal(plan.issues[0].reason, 'no_decided_application_event');
});

test('first admission appends E/F/H/I/L from one event with exact seconds', () => {
  const item = makeItem({google_sync_has_active_qualification: true, google_sync_has_admission_history: true,
    google_sync_last_decided_application_decision: 'admit', google_sync_last_decided_application_date: '2026-10-11',
    verification_date: '2026-10-11T13:04:05+03:00', verification_datetime_precision: 'second',
    verification_officer: 'УО Допуску', verification_event_type: 'admission'});
  const f = setup(item, null); const change = f.context.pqmGooglePlan_(f.body, f.tabs).changes[0];
  assert.equal(change.cells[4], 'Зареєстровано'); assert.equal(change.cells[5], 'Активний');
  assert.equal(change.cells[7], f.context.pqmGoogleDate_('2026-10-11'));
  assert.equal(change.cells[11], 'УО Допуску');
  assert.equal(f.context.pqmGoogleMatrixVerification_(change.cells[8], 'datetime').kind, 'datetime');
  assert.equal(new Date(f.context.pqmVerificationDatetime_(change.cells[8]).value).toISOString(), '2026-10-11T10:04:05.000Z');
});

test('post-admission verification never borrows UO from a later rejection', () => {
  const item = makeItem({google_sync_has_active_qualification: true, google_sync_has_admission_history: true,
    google_sync_last_decided_application_decision: 'reject',
    verification_date: '2026-10-11T13:04:05+03:00', verification_datetime_precision: 'second',
    verification_officer: '', verification_event_type: 'google_clarity'});
  const f = setup(item, null); const plan = f.context.pqmGooglePlan_(f.body, f.tabs);
  assert.equal(plan.counts.conflicts, 1);
  assert.equal(plan.changes.length, 0);
  assert.equal(plan.issues[0].reason, 'admission_verification_pair_missing_or_invalid');
});

test('first admission after prior rejection updates the existing row and never appends a duplicate', () => {
  const item = makeItem({google_sync_has_active_qualification: true, google_sync_has_admission_history: true,
    google_sync_last_decided_application_decision: 'admit', google_sync_last_decided_application_date: '2026-10-11',
    verification_date: '2026-10-11T13:04:05+03:00', verification_datetime_precision: 'second',
    verification_officer: 'УО Допуску', verification_event_type: 'admission'});
  const values = Array(15).fill(''); Object.assign(values, {1: '12345678', 2: 'ТОВ Контроль', 3: 'Керівник А',
    4: 'Неактуально', 5: 'Ще не в реєстрі', 7: fnum('2026-10-10'), 11: 'УО Відхилення'});
  const f = setup(item, {code: '12345678', values}); const plan = f.context.pqmGooglePlan_(f.body, f.tabs);
  assert.equal(plan.counts.updated, 1); assert.equal(plan.counts.appended, 0);
  assert.equal(plan.changes[0].cells[5], 'Активний'); assert.equal(plan.changes[0].cells[4], 'Зареєстровано');
  assert.ok(Object.hasOwn(plan.changes[0].cells, 8)); assert.equal(plan.changes[0].cells[11], 'УО Допуску');
});

test('later rejection keeps active qualification and does not rewrite I/L', () => {
  const item = makeItem({google_sync_has_active_qualification: true, google_sync_has_admission_history: true,
    google_sync_last_decided_application_decision: 'reject', google_sync_last_decided_application_date: '2026-10-12',
    verification_date: '2026-10-11T13:04:05+03:00', verification_datetime_precision: 'second',
    verification_officer: 'УО Допуску', verification_event_type: 'admission'});
  const values = Array(15).fill(''); Object.assign(values, {1: '12345678', 2: 'ТОВ Контроль', 3: 'Керівник А',
    4: 'Зареєстровано', 5: 'Активний', 7: fnum('2026-10-10'), 8: fnum('2026-10-11T13:04:05+03:00'), 11: 'УО Допуску'});
  const f = setup(item, {code: '12345678', values}); const plan = f.context.pqmGooglePlan_(f.body, f.tabs);
  assert.equal(plan.changes.length, 1); assert.equal(plan.changes[0].cells[5], undefined);
  assert.equal(f.row.values[5], 'Активний');
  assert.equal(plan.changes[0].cells[7], fnum('2026-10-12'));
  assert.equal(plan.changes[0].cells[8], undefined); assert.equal(plan.changes[0].cells[11], undefined);
});

test('losing every active qualification changes only E/F/H and preserves verification history', () => {
  const item = makeItem({google_sync_has_admission_history: true, google_sync_has_active_qualification: false,
    google_sync_last_decided_application_date: '2026-10-12', google_sync_last_decided_application_decision: 'reject',
    verification_date: '2026-10-11T13:04:05+03:00', verification_datetime_precision: 'second',
    verification_officer: 'УО Допуску', verification_event_type: 'admission'});
  const values = Array(15).fill(''); Object.assign(values, {1: '12345678', 2: 'ТОВ Контроль', 3: 'Керівник А',
    4: 'Зареєстровано', 5: 'Активний', 7: fnum('2026-10-10'), 8: fnum('2026-10-11T13:04:05+03:00'), 11: 'УО Допуску'});
  const f = setup(item, {code: '12345678', values}); const plan = f.context.pqmGooglePlan_(f.body, f.tabs);
  assert.equal(plan.changes[0].cells[4], 'Неактуально'); assert.equal(plan.changes[0].cells[5], 'Неактивний');
  assert.equal(plan.changes[0].cells[8], undefined); assert.equal(plan.changes[0].cells[11], undefined);
});

test('newer EDR check updates D/E/I/L atomically, older keeps Google verification', () => {
  const values = Array(15).fill(''); Object.assign(values, {1: '12345678', 2: 'ТОВ Контроль', 3: 'Керівник А',
    4: 'Зареєстровано', 5: 'Активний', 7: fnum('2026-10-10'), 8: fnum('2026-10-10T13:04:05+03:00'), 11: 'УО Старе'});
  const newer = makeItem({google_sync_has_active_qualification: true, google_sync_has_admission_history: true,
    google_sync_last_decided_application_decision: 'admit', verification_date: '2026-10-11T13:04:05+03:00',
    verification_datetime_precision: 'second', verification_officer: 'УО Нове', verification_event_type: 'google_clarity',
    current_manager_name: 'Керівник Б', edr_status_current: 'В стані припинення'});
  const f = setup(newer, {code: '12345678', values}); const plan = f.context.pqmGooglePlan_(f.body, f.tabs);
  assert.deepEqual(keys(plan.changes[0].cells), [3, 4, 8, 11]);
  assert.equal(plan.changes[0].cells[3], 'Керівник Б'); assert.equal(plan.changes[0].cells[4], 'В стані припинення');
  const older = {...newer, verification_date: '2026-10-09T13:04:05+03:00', verification_officer: 'УО Старіше'};
  const f2 = setup(older, {code: '12345678', values}); const olderPlan = f2.context.pqmGooglePlan_(f2.body, f2.tabs);
  assert.equal(olderPlan.changes.length, 0); assert.equal(olderPlan.counts.unchanged, 1);
});

test('equal precise timestamp with different manager is a blocking conflict', () => {
  const instant = '2026-10-11T13:04:05+03:00';
  const item = makeItem({google_sync_has_active_qualification: true, google_sync_has_admission_history: true,
    google_sync_last_decided_application_decision: 'admit', verification_date: instant,
    verification_datetime_precision: 'second', verification_officer: 'УО', verification_event_type: 'google_clarity',
    current_manager_name: 'Керівник Б'});
  const values = Array(15).fill(''); Object.assign(values, {1: '12345678', 2: 'ТОВ Контроль', 3: 'Керівник А',
    4: 'Зареєстровано', 5: 'Активний', 7: fnum('2026-10-10'), 8: fnum(instant), 11: 'УО'});
  const f = setup(item, {code: '12345678', values}); const plan = f.context.pqmGooglePlan_(f.body, f.tabs);
  assert.equal(plan.counts.conflicts, 1); assert.equal(plan.issues[0].reason, 'same_timestamp_verification_conflict');
  assert.equal(plan.changes.length, 0);
});

test('date-only cannot prove a newer verification; unrelated decided status can still be previewed', () => {
  const item = makeItem({google_sync_has_active_qualification: true, google_sync_has_admission_history: true,
    google_sync_last_decided_application_decision: 'reject', google_sync_last_decided_application_date: '2026-10-12',
    verification_date: '2026-10-11', verification_datetime_precision: 'day',
    verification_officer: 'УО', verification_event_type: 'google_clarity'});
  const values = Array(15).fill(''); Object.assign(values, {1: '12345678', 2: 'ТОВ Контроль', 3: 'Керівник А',
    4: 'Зареєстровано', 5: 'Неактивний', 7: fnum('2026-10-10'), 8: fnum('2026-10-10T13:04:05+03:00'), 11: 'УО'});
  const f = setup(item, {code: '12345678', values}); const plan = f.context.pqmGooglePlan_(f.body, f.tabs);
  assert.equal(plan.counts.conflicts, 1); assert.equal(plan.issues[0].reason, 'date_only_cannot_prove_verification_order');
  assert.equal(plan.changes.length, 1); assert.equal(plan.changes[0].cells[5], 'Активний');
  assert.equal(plan.changes[0].cells[7], fnum('2026-10-12'));
  assert.equal(plan.changes[0].cells[8], undefined); assert.equal(plan.changes[0].cells[11], undefined);
});

test('verification-pair conflict keeps independent F/H changes but removes all D/E/I/L writes', () => {
  const item = makeItem({google_sync_has_active_qualification: true, google_sync_has_admission_history: true,
    google_sync_last_decided_application_decision: 'admit', google_sync_last_decided_application_date: '2026-10-12',
    verification_date: '2026-10-11T13:04:05+03:00', verification_datetime_precision: 'second',
    verification_officer: 'УО Перевірки', verification_event_type: 'google_clarity',
    current_manager_name: 'Керівник Б', edr_status_current: 'Зареєстровано'});
  const values = Array(15).fill(''); Object.assign(values, {1:'12345678', 2:'ТОВ Контроль', 3:'Керівник А',
    4:'🟡 Немає інформації', 5:'Неактивний', 7:fnum('2026-10-10'),
    8:fnum('2026-10-10T13:04:05+03:00'), 11:'УО Старе'});
  const f = setup(item, {code:'12345678', values});
  const plan = f.context.pqmGooglePlan_(f.body, f.tabs);
  assert.equal(plan.counts.conflicts, 1);
  assert.equal(plan.issues[0].reason, 'manual_edr_information_marker_blocks_verification_pair');
  assert.deepEqual(keys(plan.changes[0].cells), [5, 7]);
  for (const column of [3, 4, 8, 11]) assert.equal(Object.hasOwn(plan.changes[0].cells, column), false);
});

test('repeat planning after applying a transition is idempotent and keeps non-owned columns out of request ranges', () => {
  const item = makeItem({google_sync_has_active_qualification: true, google_sync_has_admission_history: true,
    google_sync_last_decided_application_decision: 'admit', verification_date: '2026-10-11T13:04:05+03:00',
    verification_datetime_precision: 'second', verification_officer: 'УО', verification_event_type: 'admission'});
  const values = Array(15).fill(''); Object.assign(values, {1: '12345678', 2: 'ТОВ Контроль', 3: 'Керівник А',
    4: 'Неактуально', 5: 'Ще не в реєстрі', 7: fnum('2026-10-10'), 11: 'УО Відхилення'});
  const f = setup(item, {code: '12345678', values}); const plan = f.context.pqmGooglePlan_(f.body, f.tabs);
  const request = f.context.pqmSandboxFullRequests_([{tab: 'ЮО', row: 2, change: plan.changes[0], columns: keys(plan.changes[0].cells)}], f.tabs);
  assert.ok(request.every(entry => entry.updateCells.range.endColumnIndex === entry.updateCells.range.startColumnIndex + 1));
  assert.ok(request.every(entry => allowed.includes(entry.updateCells.range.startColumnIndex)));
  for (const [column, value] of Object.entries(plan.changes[0].cells)) values[Number(column)] = value;
  values[8] = plan.changes[0].cells[8]; values[5] = 'Активний'; values[4] = 'Зареєстровано';
  const next = setup(item, {code: '12345678', values, dateFormat: 'dd.MM.yyyy HH:mm:ss'});
  assert.equal(next.context.pqmGooglePlan_(next.body, next.tabs).counts.unchanged, 1);
});

test('confirmed individual entrepreneurs route only to ФОП and legal subjects route only to ЮО', () => {
  const fop = makeItem({supplier_code: '0012345678', entity_type: 'individual_entrepreneur', target_sheet: 'ФОП'});
  const legal = makeItem({supplier_code: '00123456', entity_type: 'legal_entity', target_sheet: 'ЮО'});
  const fopFixture = setup(fop, null), legalFixture = setup(legal, null);
  assert.equal(fopFixture.context.pqmGooglePlan_(fopFixture.body, fopFixture.tabs).changes[0].tab, 'ФОП');
  assert.equal(legalFixture.context.pqmGooglePlan_(legalFixture.body, legalFixture.tabs).changes[0].tab, 'ЮО');
});

test('unresolved type blocks APPEND and carries an explanation into Preview', () => {
  const item = makeItem({entity_type: 'unknown', classification_status: 'needs_review',
    classification_reason: 'subject_nature_not_established',
    classification_reason_label: 'Природу суб’єкта не встановлено; формат коду недостатній',
    target_sheet: null, append_allowed: false});
  const fixture = setup(item, null), plan = fixture.context.pqmGooglePlan_(fixture.body, fixture.tabs);
  assert.equal(plan.changes.length, 0);
  assert.equal(plan.counts.conflicts, 1);
  assert.equal(plan.issues[0].reason, 'subject_nature_not_established');
  assert.equal(plan.issues[0].detail, item.classification_reason_label);
});

test('confirmed legal entity cannot be silently routed to FOP', () => {
  const item = makeItem({target_sheet: 'ФОП'});
  const fixture = setup(item, null), plan = fixture.context.pqmGooglePlan_(fixture.body, fixture.tabs);
  assert.equal(plan.changes.length, 0);
  assert.equal(plan.counts.conflicts, 1);
  assert.equal(plan.issues[0].reason, 'classification_contract_unverified');
});

test('literal identifier text including leading zeroes is written unchanged', () => {
  const item = makeItem({supplier_code: '00123456'});
  const fixture = setup(item, null), plan = fixture.context.pqmGooglePlan_(fixture.body, fixture.tabs);
  assert.equal(plan.changes[0].cells[1], '00123456');
});

test('Google and PQM whitespace variants are conflicts, never normalized into one ID', () => {
  const item = makeItem({supplier_code: '00123456'}), fixture = setup(item, null);
  fixture.tabs['ЮО'].rows[0].codeDisplay = '0012 3456';
  fixture.tabs['ЮО'].rows[0].values[1] = '0012 3456';
  const plan = fixture.context.pqmGooglePlan_(fixture.body, fixture.tabs);
  assert.equal(plan.changes.length, 0);
  assert.equal(plan.counts.conflicts, 1);
  assert.equal(plan.issues[0].reason, 'identifier_text_conflict');
});

function fnum(value) {
  if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return Date.parse(value + 'T00:00:00Z') / 86400000 + 25569;
  }
  const date = new Date(value);
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {timeZone: 'Europe/Kyiv',
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
    second: '2-digit', hourCycle: 'h23'}).formatToParts(date).map(part => [part.type, part.value]));
  const wall = Date.UTC(Number(parts.year), Number(parts.month) - 1, Number(parts.day),
    Number(parts.hour), Number(parts.minute), Number(parts.second), date.getUTCMilliseconds());
  return wall / 86400000 + 25569;
}

function tabFor(values, code) {
  const tab = makeTab('ЮО'); tab.headers = ['Маркер актуальності', 'Код ЄДРПОУ', 'Найменування', 'ПІБ для перевірки',
    'Статус в реєстрі (ЄДР)', 'Статус (Prozorro)', 'Реквізити рішення про припинення', 'Дата останньої заявки',
    'Дата перевірки', 'Дата запису', 'Номер запису', 'УО', 'Примітки', 'Повна назва з ЄДР', 'Скорочена назва з ЄДР'];
  tab.rows[0].values = values; tab.rows[0].codeDisplay = code; return tab;
}
