const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, 'PqmSandboxExecution.gs'), 'utf8');
const checkpointSource = fs.readFileSync(path.join(__dirname, '..', 'shared', 'PqmExecutionCheckpoint.gs'), 'utf8');
const digest = value => crypto.createHash('sha256').update(JSON.stringify(canonical(value))).digest('base64url');
function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort()
    .map(key => [key, canonical(value[key])]));
  return value;
}

function fixture() {
  const c = vm.createContext({Date, JSON, Object, Array, Number, String, Math, RegExp});
  vm.runInContext(source, c, {filename: 'PqmSandboxExecution.gs'});
  c.pqmSandboxControlledDigest_ = digest;
  c.pqmSandboxIsCanonicalDigest_ = value => typeof value === 'string' && /^[A-Za-z0-9_-]{43}$/.test(value);
  c.pqmSandboxExecutionComparableValue_ = value => value;
  const appends = Array.from({length: 251}, (_, i) => ({operation: 'APPEND', tab: i % 2 ? 'ЮО' : 'ФОП',
    row: 100 + i, code: String(10000000 + i), cells: [
      {column: 'A', new_value: `=IF(B${100 + i}="","",1)`, formula: true},
      {column: 'B', new_value: String(10000000 + i), formula: false},
    ]}));
  const updates = [
    {operation: 'UPDATE', tab: 'ЮО', row: 900, code: '90000001', cells: [
      {column: 'C', old_value: 'old', new_value: 'new', formula: false}]},
    {operation: 'UPDATE', tab: 'ФОП', row: 901, code: '90000003', cells: [
      {column: 'I', old_value: 46338, new_value: 46339, formula: false}]},
  ];
  const conflicts = [
    {tab: 'ФОП', code: '90000002', reason: 'routing_mismatch'},
    {tab: 'ЮО', code: '90000004', reason: 'routing_mismatch'},
  ];
  const preview = {appends, updates, conflicts, errors: []};
  c.pqmSandboxFullPreviewDetails_ = () => preview;
  const guardRows = [];
  const tabs = {'ФОП': {rows: []}, 'ЮО': {rows: []}};
  const valueRanges = [], serviceRanges = [];
  for (let i = 0; i < 25; i++) {
    const tab = i % 2 ? 'ЮО' : 'ФОП', row = 2 + Math.floor(i / 2), code = String(70000000 + i);
    const values = Array(15).fill(''); values[1] = code;
    const formulas = Array(15).fill('');
    const service = ['added-time', 'source-plan', 'source-run'];
    tabs[tab].rows[row - 2] = {codeDisplay: code};
    guardRows.push({tab, row,
      codeDigest: digest([tab, row, code]),
      rowDigest: digest({tab, row, code, values, formulas}),
      serviceDigest: digest([tab, code, row, service])});
    valueRanges.push({values: [values]}); serviceRanges.push({values: [service]});
  }
  let reads = 0;
  c.Sheets = {Spreadsheets: {Values: {batchGet(_id, options) {
    reads++;
    if (options.ranges[0].includes('!A') && options.ranges[0].includes(':O'))
      return {valueRanges: options.ranges.length === 25 ? valueRanges : options.ranges.map(() => ({values: []}))};
    return {valueRanges: options.ranges.length === 25 ? serviceRanges : options.ranges.map(() => ({values: []}))};
  }}}};
  const remainingOperations = appends.map(item => ({operation: 'APPEND', tab: item.tab, row: item.row,
    code: item.code, cells: item.cells.map(cell => ({column: cell.column, new_value: cell.new_value,
      formula: cell.formula})).sort((a, b) => a.column.localeCompare(b.column))}))
    .sort((a, b) => a.tab.localeCompare(b.tab) || a.row - b.row || a.code.localeCompare(b.code));
  const request = {action: 'apply', environment: 'SANDBOX', trigger: 'manual', planScope: 'APPEND_ONLY',
    continuationSourceRequestId: '71487a74779f4445a186a8dbe6252fbc',
    continuationPlanDigest: digest('operation-plan'), continuationRemainingDigest: digest(remainingOperations),
    continuationGuardRows: guardRows, continuationVersion: 2,
    continuationSourcePlanDigest: digest('source-plan'), continuationExclusionsDigest: null, chunkIndex: 0};
  request.continuationExclusionsDigest = digest(c.pqmSandboxContinuationExclusionsV2_(preview));
  const record = {continuationSourceRequestId: request.continuationSourceRequestId,
    continuationPlanDigest: request.continuationPlanDigest, continuationGuardDigest: digest(guardRows),
    continuationVersion: 2, continuationSourcePlanDigest: request.continuationSourcePlanDigest,
    continuationExclusionsDigest: request.continuationExclusionsDigest};
  return {c, preview, request, record, tabs, valueRanges, serviceRanges, reads: () => reads};
}

test('Apps Script v2 exclusion digest matches the Python historical fixture and retains unavailable conflict rows', () => {
  const {c, preview} = fixture();
  const exclusions = c.pqmSandboxContinuationExclusionsV2_(preview);
  assert.equal(digest(exclusions), 'roHFY7h0UcZWZPlrtxGjO2DkOx1ezNjvxbK0bzcUnf0');
  assert.equal(exclusions.conflicts.every(item => item.row_available === false && item.row === null), true);
});

test('Apps Script v2 prewrite guard permits exact APPEND-only projection and reads preserved rows only', () => {
  const f = fixture();
  assert.doesNotThrow(() => f.c.pqmSandboxContinuationPrewriteGuard_('sandbox-sheet',
    {plan: {counts: {appended: 251, updated: 2, conflicts: 2, errors: 0}}, tabs: f.tabs},
    f.request, f.record));
  assert.equal(f.reads(), 4);
});

test('Apps Script v2 prewrite guard rejects APPEND/UPDATE/conflict overlap and changed source bindings', () => {
  for (const kind of ['update-append', 'conflict-append', 'conflict-update', 'conflict-row']) {
    const f = fixture();
    if (kind === 'update-append') f.preview.updates[0].code = f.preview.appends[0].code;
    if (kind === 'conflict-append') f.preview.conflicts[0].code = f.preview.appends[0].code;
    if (kind === 'conflict-update') f.preview.conflicts[0].code = f.preview.updates[0].code;
    if (kind === 'conflict-row') f.preview.conflicts[0].row = f.preview.appends[0].row;
    if (kind === 'conflict-update') {
      assert.throws(() => f.c.pqmSandboxContinuationExclusionsV2_(f.preview), /overlapping/);
      assert.equal(f.reads(), 0);
      continue;
    }
    f.request.continuationExclusionsDigest = digest(f.c.pqmSandboxContinuationExclusionsV2_(f.preview));
    f.record.continuationExclusionsDigest = f.request.continuationExclusionsDigest;
    assert.throws(() => f.c.pqmSandboxContinuationPrewriteGuard_('sandbox-sheet',
      {plan: {counts: {appended: 251, updated: 2, conflicts: 2, errors: 0}}, tabs: f.tabs},
      f.request, f.record), /overlap/);
    assert.equal(f.reads(), 0, 'overlap is rejected before any Sheets read/write operation');
  }
  const f = fixture();
  f.request.continuationSourcePlanDigest = digest('changed-source');
  assert.throws(() => f.c.pqmSandboxContinuationPrewriteGuard_('sandbox-sheet',
    {plan: {counts: {appended: 251, updated: 2, conflicts: 2, errors: 0}}, tabs: f.tabs},
    f.request, f.record), /lineage changed/);
  assert.equal(f.reads(), 0);
});

test('Apps Script v2 prewrite guard blocks incomplete target reads and changed preserved Q/R/S or row data', () => {
  const incomplete = fixture();
  const original = incomplete.c.Sheets.Spreadsheets.Values.batchGet;
  let first = true;
  incomplete.c.Sheets.Spreadsheets.Values.batchGet = (id, options) => {
    if (first) { first = false; return {valueRanges: []}; }
    return original(id, options);
  };
  assert.throws(() => incomplete.c.pqmSandboxContinuationPrewriteGuard_('sandbox-sheet',
    {plan: {counts: {appended: 251, updated: 2, conflicts: 2, errors: 0}}, tabs: incomplete.tabs},
    incomplete.request, incomplete.record), /target read incomplete/);
  assert.equal(incomplete.reads(), 1, 'incomplete response stops before preserved-row reads');

  const changedQrs = fixture();
  changedQrs.serviceRanges[0].values[0][2] = 'changed-run-marker';
  assert.throws(() => changedQrs.c.pqmSandboxContinuationPrewriteGuard_('sandbox-sheet',
    {plan: {counts: {appended: 251, updated: 2, conflicts: 2, errors: 0}}, tabs: changedQrs.tabs},
    changedQrs.request, changedQrs.record), /preserved continuation metadata changed/);

  const changedRow = fixture();
  changedRow.valueRanges[0].values[0][2] = 'changed-cell';
  assert.throws(() => changedRow.c.pqmSandboxContinuationPrewriteGuard_('sandbox-sheet',
    {plan: {counts: {appended: 251, updated: 2, conflicts: 2, errors: 0}}, tabs: changedRow.tabs},
    changedRow.request, changedRow.record), /preserved continuation row content changed/);
});

test('Apps Script checkpoint receipt preserves v2 source lineage and state digest binds it', () => {
  const {c, request} = fixture();
  vm.runInContext(checkpointSource, c, {filename: 'PqmExecutionCheckpoint.gs'});
  const baseReceipt = (_status, _counts, digestValue) => ({digest: digestValue});
  const step = {status: 'APPLY_CHUNK_VERIFIED', counts: {append: 25, update: 0},
    chunkIndex: 0, nextChunk: 1, more: true, phase: 'append', checkpointDigest: digest('step')};
  const receipt = c.pqmExecutionCheckpointReceipt_(request, baseReceipt, step);
  assert.equal(receipt.continuationVersion, 2);
  assert.equal(receipt.continuationSourceRequestId, request.continuationSourceRequestId);
  assert.equal(receipt.continuationSourcePlanDigest, request.continuationSourcePlanDigest);
  assert.equal(receipt.continuationExclusionsDigest, request.continuationExclusionsDigest);
  const record = {actor: 'sandbox-admin', trigger: 'manual', digest: 'plan', planScope: 'APPEND_ONLY',
    state: 'ready', nextChunk: 1, inflight: null, payloadDigest: digest('payload'), googleDigest: digest('sheet'),
    aggregate: {append: 25, update: 0, batches: 1}, steps: [step], chunkJournalVersion: 1,
    continuationSourceRequestId: request.continuationSourceRequestId,
    continuationPlanDigest: request.continuationPlanDigest, continuationGuardDigest: digest('guard'),
    continuationVersion: 2, continuationSourcePlanDigest: request.continuationSourcePlanDigest,
    continuationExclusionsDigest: request.continuationExclusionsDigest};
  const original = c.pqmExecutionCheckpointStateDigest_(record);
  const changed = {...record, continuationExclusionsDigest: digest('different exclusions')};
  assert.notEqual(c.pqmExecutionCheckpointStateDigest_(changed), original);
});
