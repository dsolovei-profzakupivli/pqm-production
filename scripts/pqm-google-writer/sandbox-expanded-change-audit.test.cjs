const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

const source = ['PqmSandboxPreviewDependencies.gs', 'PqmSandboxPreview.gs',
  'PqmSandboxControlledApply.gs', 'PqmSandboxFullApply.gs',
  'PqmSandboxExpandedChangeAudit.gs']
  .map(name => fs.readFileSync(__dirname + '/' + name, 'utf8')).join('\n');
const plain = value => JSON.parse(JSON.stringify(value));

function fixture() {
  const logs = [];
  const context = {console: {log: text => logs.push(text)}, Date, Map, Set};
  vm.createContext(context);
  vm.runInContext(source, context);
  const tabs = Object.fromEntries(['ФОП', 'ЮО'].map((name, index) => [name, {
    id: index + 1, maxRows: 20, templateRowHeight: 25,
    headers: Array.from(context.PQM_GOOGLE_HEADERS), rows: [], merges: [],
    protectedRanges: [], conditionalFormats: []
  }]));
  function row(code, values) {
    const cells = Array(15).fill('');
    cells[1] = code;
    Object.assign(cells, values);
    return {values: cells, formulas: Array(15).fill(''), codeDisplay: code,
      dateFormat: 'dd.MM.yyyy', verificationDateFormat: 'dd.MM.yyyy'};
  }
  const day = context.pqmGoogleDate_('2026-09-22');
  tabs['ФОП'].rows.push(row('1000000000', {2: 'Name', 4: 'Припинено',
    5: 'Неактивний', 7: day - 1}));
  tabs['ЮО'].rows.push(row('20000000', {2: 'Name', 4: 'Зареєстровано',
    5: 'Активний', 7: day, 8: day, 11: 'Officer'}));
  tabs['ФОП'].rows.push(row('3000000000', {2: 'Name', 4: '',
    5: 'Ще не в реєстрі', 7: day, 8: day, 11: 'Preserve'}));
  const items = [
    {supplier_code: '1000000000', entity_type: 'individual_entrepreneur',
      edr_status_current: 'Зареєстровано', prozorro_status_google: 'Активний',
      last_application_date: '2026-09-22', verification_date: '2026-09-22',
      verification_officer: 'Officer', verification_event_type: 'admission'},
    {supplier_code: '20000000', entity_type: 'legal_entity',
      edr_status_current: 'Неактуально', prozorro_status_google: 'Неактивний',
      last_application_date: '2026-09-22', verification_date: '2026-09-22',
      verification_officer: ' officer ', verification_event_type: 'google_clarity'},
    {supplier_code: '3000000000', entity_type: 'individual_entrepreneur',
      edr_status_current: null, prozorro_status_google: 'Ще не в реєстрі',
      last_application_date: '2026-09-22', verification_date: null,
      verification_officer: null}
  ].map(item => ({...item,
    google_sync_last_decided_application_date: item.last_application_date,
    supplier_name: 'Name', freshness_marker: null,
    monitoring_eligible: true, google_sync_eligible: true}));
  const body = {count: items.length, items};
  let writes = 0;
  context.pqmSandboxControlledSpreadsheetId_ = () => 'sandbox-id';
  context.pqmSandboxFetchRegistry_ = () => body;
  context.pqmGoogleSnapshot_ = () => tabs;
  context.Utilities = {formatDate: () => '2026-09-23'};
  context.Sheets = {Spreadsheets: {batchUpdate: () => {writes++;}}};
  return {context, body, tabs, logs, get writes() {return writes;}};
}

test('read-only aggregate audit classifies E/I/L/F/H without identities or cell values', () => {
  const f = fixture();
  const output = f.context.pqmSandboxExpandedChangeAudit();
  assert.equal(output.google_writes, 0);
  assert.equal(output.full_apply_plan_created, false);
  assert.equal(output.e.planned, 2);
  assert.equal(output.e.transitions['Припинено -> Зареєстровано'], 1);
  assert.equal(output.e.transitions['Зареєстровано -> Неактуально'], 1);
  assert.equal(output.i.planned, 1);
  assert.equal(output.i.google_blank_to_pqm_date, 1);
  assert.equal(output.i.google_nonblank_same_calendar_not_planned, 1);
  assert.equal(output.i.pqm_blank_google_nonblank_preserved, 1);
  assert.equal(output.l.planned, 1);
  assert.equal(output.l.google_blank_to_pqm_officer, 1);
  assert.equal(output.l.google_blank_by_event_type.admission, 1);
  assert.equal(output.l.google_blank_with_i_write, 1);
  assert.equal(output.l.google_blank_without_i_write, 0);
  assert.equal(output.l.google_nonblank_different_officer, 0);
  assert.equal(output.l.normalization_equivalent_planned, 0);
  assert.equal(output.l.normalization_equivalent_preserved, 1);
  assert.equal(output.l.pqm_blank_google_nonblank_preserved, 1);
  assert.equal(output.f.planned, 2);
  assert.equal(output.h.planned, 1);
  assert.equal(f.writes, 0);
  assert.equal(f.logs.length, 1);
  for (const privateValue of ['1000000000', '20000000', '3000000000', 'Officer', 'Preserve']) {
    assert.equal(f.logs[0].includes(privateValue), false);
  }
  assert.deepEqual(plain(output), JSON.parse(f.logs[0]));
});

test('audit flags unknown E vocabulary and future or invalid I without logging raw values', () => {
  const f = fixture();
  f.body.items[0].edr_status_current = 'unapproved';
  f.body.items[0].verification_date = '2026-09-24';
  f.body.items[1].verification_date = 'not-a-date';
  const output = f.context.pqmSandboxExpandedChangeAudit();
  assert.equal(output.e.outside_known_vocabulary, 1);
  assert.equal(output.i.future_pqm_dates, 1);
  assert.equal(output.i.invalid_pqm_dates, 1);
  assert.equal(f.writes, 0);
  assert.equal(f.logs[0].includes('unapproved'), false);
  assert.equal(f.logs[0].includes('not-a-date'), false);
});

test('I provenance groups and L correlation distinguish older and newer PQM events', () => {
  const f = fixture();
  const day = f.context.pqmGoogleDate_('2026-09-23');
  f.tabs['ФОП'].rows[0].values[8] = day;
  f.tabs['ФОП'].rows[0].values[11] = 'Earlier officer';
  f.body.items[1].verification_date = '2026-09-23';
  const output = f.context.pqmSandboxExpandedChangeAudit();
  assert.equal(output.i.pqm_older, 0);
  assert.equal(output.i.pqm_newer, 1);
  assert.equal(output.i.older_by_event_type.admission, undefined);
  assert.equal(output.i.newer_by_event_type.google_clarity, 1);
  assert.equal(output.l.different_officer_by_i_relation.pqm_older, 0);
  assert.equal(output.l.different_officer_by_i_relation.pqm_newer, 1);
  assert.equal(output.verification_pair_decisions.google_newer_preserved, 1);
  assert.equal(output.verification_pair_decisions.pqm_newer_written, 1);
  assert.equal(f.writes, 0);
});

test('release-candidate E other, chronology and same-date officer stay aggregate-only', () => {
  const f = fixture();
  const day = f.context.pqmGoogleDate_('2026-09-22');
  f.tabs['ФОП'].rows[0].values[4] = '🟡 Немає інформації';
  f.tabs['ФОП'].rows[0].values[8] = day - 1;
  f.tabs['ФОП'].rows[0].values[11] = 'Earlier officer';
  f.body.items[1].verification_officer = 'Different officer';
  f.body.items[1].verification_event_type = 'legacy_google_registry';
  const output = f.context.pqmSandboxExpandedChangeAudit();
  assert.equal(f.context.pqmSandboxExpandedAuditGoogleOther_('🟡 Немає інформації'), 'Немає інформації');
  assert.equal(output.e.other_google_source_values['Немає інформації -> Зареєстровано'], undefined);
  assert.equal(output.e.planned, 1); // preserved Google E is not a planned write
  assert.equal(output.i.newer_by_event_type.admission, 1);
  assert.equal(output.l.newer_by_event_type.admission, 1);
  assert.equal(output.l.newer_with_i_write, 1);
  assert.equal(output.l.newer_without_i_write, 0);
  assert.equal(output.l.same_date_by_event_type.legacy_google_registry, undefined);
  assert.equal(output.verification_pair_decisions.same_date_google_officer_preserved, 1);
  assert.equal(output.h.source_field, 'last_application_date');
  assert.equal(output.h.pqm_newer, 1);
  assert.equal(f.writes, 0);
  for (const privateValue of ['1000000000', '20000000', 'Earlier officer', 'Different officer']) {
    assert.equal(f.logs[0].includes(privateValue), false);
  }
});
