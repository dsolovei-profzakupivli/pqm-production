const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const {spawnSync} = require('node:child_process');
const test = require('node:test');
const vm = require('node:vm');

const clone = value => JSON.parse(JSON.stringify(value));
const source = ['PqmSandboxPreviewDependencies.gs', 'PqmGoogleBusinessMatrix.gs', 'PqmVerificationDatetime.gs',
  'PqmSandboxControlledApply.gs',
  'PqmSandboxFullApply.gs', 'PqmSandboxAppendApply.gs']
  .map(name => fs.readFileSync(path.join(__dirname, name), 'utf8')).join('\n');

function fixture() {
  const context = {Date, Map, Set, console: {log() {}}};
  vm.createContext(context); vm.runInContext(source, context);
  const tabs = Object.fromEntries(['ФОП', 'ЮО'].map((name, index) => [name, {
    id: index + 1, maxRows: 2, headers: [...context.PQM_GOOGLE_HEADERS],
    merges: [], protectedRanges: [], conditionalFormats: [], templateRowHeight: 30,
    rows: [{values: Array(15).fill(''), formulas: Object.assign(Array(15).fill(''), {0: '=IF(B2="", "", 1)'}),
      codeDisplay: '', dateFormat: 'dd.MM.yyyy'}]
  }]));
  tabs['ФОП'].rows[0].values[1] = '00000001';
  tabs['ФОП'].rows[0].codeDisplay = '00000001';
  tabs['ЮО'].rows[0].values[1] = '00000002';
  tabs['ЮО'].rows[0].codeDisplay = '00000002';
  const supplier = {supplier_code: '12345678', entity_type: 'individual_entrepreneur',
    classification_version: 'subject-nature-20261030-v2', classification_status: 'resolved',
    classification_reason: 'established_subject_nature', classification_reason_label: 'ФОП підтверджено',
    target_sheet: 'ФОП', append_allowed: true,
    monitoring_eligible: true, google_sync_eligible: false, google_writer_eligible: false,
    google_sync_has_active_qualification: false, google_sync_has_admission_history: false,
    google_sync_last_decided_application_decision: '', google_sync_last_decided_protocol_at: '',
    google_sync_last_decided_protocol_officer: '', google_sync_last_decided_submission_id: '',
    google_sync_latest_rejection_officer: '', supplier_name: 'Supplier',
    edr_status_current: 'Зареєстровано', prozorro_status_google: '✅ Активний',
    freshness_marker: 'fresh', last_application_date: '2026-09-20',
    google_sync_last_decided_application_date: null,
    verification_date: '2026-09-20', verification_officer: 'Officer A', verification_event_type: null,
    verification_datetime_precision: ''};
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
    formatDate: (date, zone) => {
      const parts = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {timeZone: zone,
        year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
        second: '2-digit', hourCycle: 'h23'}).formatToParts(date).map(part => [part.type, part.value]));
      return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}.000`;
    },
    computeDigest: (_, value) => crypto.createHash('sha256').update(value).digest(),
    base64EncodeWebSafe: bytes => Buffer.from(bytes).toString('base64url')};
  context.SpreadsheetApp = {getUi: () => ({ButtonSet: {OK_CANCEL: 'OK_CANCEL'}, Button: {OK: 'OK'},
    prompt: () => ({getSelectedButton: () => 'OK', getResponseText: () => prompts.shift() || ''})})};
  context.LockService = {getScriptLock: () => ({tryLock: () => {if (locked) return false; locked = true; return true;},
    releaseLock: () => {locked = false;}})};
  context.Sheets = {Spreadsheets: {get: (_, options) => {
    const full = /^'(ФОП|ЮО)'!A(\d+):O\2$/.exec(options.ranges[0]);
    const formulaOnly = /^'(ФОП|ЮО)'!A(\d+):A\2$/.exec(options.ranges[0]);
    assert.ok(full || formulaOnly);
    if (formulaOnly) {
      const tab = tabs[formulaOnly[1]], rowNumber = Number(formulaOnly[2]);
      return {sheets: [{data: [{rowData: [{values: [{userEnteredValue: {
        formulaValue: tab.rows[rowNumber - 2].formulas[0] || ''}}]}]}]}]};
    }
    const state = metadata.get(full[1] + ':' + full[2]);
    return {sheets: [{data: [{rowData: [{values: clone(state.cells)}],
      rowMetadata: [{pixelSize: state.height}]}]}]};
  }, batchUpdate: ({requests: batch}) => {
    writes++; requests = clone(batch);
    batch.forEach(request => {
      if (request.appendDimension) tabs['ФОП'].maxRows += request.appendDimension.length;
      if (request.copyPaste) {
        const range = request.copyPaste.destination;
        for (let i = range.startRowIndex; i < range.endRowIndex; i++) {
          while (tabs['ФОП'].rows.length <= i - 1) tabs['ФОП'].rows.push({values: Array(15).fill(''),
            formulas: Array(15).fill(''), codeDisplay: '', dateFormat: 'dd.MM.yyyy'});
          tabs['ФОП'].rows[i - 1].formulas[0] = context.pqmGoogleTranslatedAppendFormula_(
            tabs['ФОП'].rows[0].formulas[0], 2, i + 1);
          metadata.set('ФОП:' + (i + 1), clone(metadata.get('ФОП:2')));
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

function activate(f) {
  Object.assign(f.supplier, {google_sync_eligible: true, google_writer_eligible: true,
    google_sync_has_active_qualification: true, google_sync_has_admission_history: true,
    google_sync_last_decided_application_decision: 'admit', google_sync_last_decided_protocol_at: '2026-09-20',
    google_sync_last_decided_application_date: '2026-09-20',
    google_sync_last_decided_protocol_officer: 'Officer A', google_sync_last_decided_submission_id: 's1',
    verification_datetime_precision: 'day', verification_event_type: 'admission'});
}

test('pending supplier cannot append; decision adds exactly one guarded row and next run is idempotent', () => {
  const f = fixture();
  const pending = f.context.pqmSandboxAppendPreview();
  assert.equal(pending.selected, 0);
  f.arm(pending);
  assert.throws(() => f.context.pqmSandboxAppendApply(), /stale or empty selection/);
  assert.equal(f.writes, 0);
  activate(f);
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
  assert.ok(f.requests.some(request => request.updateDimensionProperties));
});

test('duplicate identity and moved Sheet row fail closed before append write', () => {
  const duplicate = fixture();
  activate(duplicate);
  duplicate.body.items.push({...duplicate.supplier}); duplicate.body.count++;
  assert.throws(() => duplicate.context.pqmSandboxAppendPreview(), /planner blocked/);
  assert.equal(duplicate.writes, 0);
  const moved = fixture();
  activate(moved);
  const preview = moved.context.pqmSandboxAppendPreview();
  moved.tabs['ФОП'].rows[0].codeDisplay = 'MOVED';
  moved.arm(preview);
  assert.throws(() => moved.context.pqmSandboxAppendApply(), /stale/);
  assert.equal(moved.writes, 0);
});

test('append AFTER read-back rejects formatting drift and never retries an uncertain write', () => {
  const f = fixture();
  activate(f);
  f.supplier.google_sync_last_decided_application_date = '2026-09-20';
  const preview = f.context.pqmSandboxAppendPreview();
  const write = f.context.Sheets.Spreadsheets.batchUpdate;
  f.context.Sheets.Spreadsheets.batchUpdate = (...args) => {
    write(...args);
    f.metadata.get('ФОП:3').cells[6].dataValidation = null;
  };
  f.arm(preview);
  assert.throws(() => f.context.pqmSandboxAppendApply(), /validation mismatch/);
  assert.equal(f.writes, 1);
  assert.equal(f.context.pqmSandboxAppendPreview().selected, 0,
    'after uncertain read-back, new Preview observes the appended identity');
});

test('pending follow-up does not advance H and stale append digest prevents writes', () => {
  const f = fixture();
  activate(f);
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
  activate(f);
  f.supplier.google_sync_last_decided_application_date = '2026-09-20';
  const preview = f.context.pqmSandboxAppendPreview(); f.arm(preview);
  f.context.pqmSandboxAppendApply();
  const row = f.tabs['ФОП'].rows[1];
  row.values[8] = '25.09.2026 17:03:19';
  row.values[11] = 'Officer B';
  row.values[6] = 'New G'; row.values[9] = '2026-09-25';
  row.values[10] = 'New K'; row.values[12] = 'New M';
  const repo = process.env.PQM_PERMANENT_REPO || path.resolve(__dirname, '../..');
  const python = process.env.PQM_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
  const bridge = path.join(repo, 'validation/local_release_20260911/daily_cycle_evening_fixture.py');
  const google = {i: '25.09.2026 17:03:19', l: 'Officer B', e: row.values[4],
    g: row.values[6], j: row.values[9], k: row.values[10], m: row.values[12]};
  const result = spawnSync(python, [bridge], {cwd: repo, encoding: 'utf8',
    env: {...process.env, PYTHONIOENCODING: 'utf-8'},
    input: JSON.stringify({pqm_date: '2026-09-20', pqm_officer: 'Officer A', google})});
  assert.equal(result.status, 0, result.stderr);
  const evening = JSON.parse(result.stdout);
  assert.deepEqual([evening.date, evening.officer], ['2026-09-25T17:03:19.000+03:00', 'Officer B']);
  assert.deepEqual(evening.gjkm, ['New G', '2026-09-25', 'New K', 'New M']);
  f.supplier.verification_date = evening.date;
  f.supplier.verification_officer = evening.officer;
  const plan = f.context.pqmGooglePlan_(f.body, f.context.pqmGoogleSnapshot_('SANDBOX_FIXTURE'));
  assert.equal(plan.counts.appended, 0);
  assert.ok(plan.changes.every(change => !('8' in change.cells) && !('11' in change.cells)));
});
