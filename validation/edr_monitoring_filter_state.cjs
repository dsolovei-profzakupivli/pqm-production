const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const app = fs.readFileSync(path.join(__dirname, '..', 'app.js'), 'utf8');
function source(name) {
  const line = app.split('\n').find(value => value.startsWith(`${name}(`) || value.startsWith(`async function ${name}(`) || value.startsWith(`function ${name}(`));
  assert.ok(line, `missing ${name}`);
  return line;
}
const controls = new Map();
function control(selector) {
  if (!controls.has(selector)) controls.set(selector, {value: '', textContent: ''});
  return controls.get(selector);
}
const requests = [];
const ctx = {
  URLSearchParams, Set, API: '/api', edrMonitoringLoadSequence: 0,
  edrMonitoringPage: 1, edrMonitoringSort: 'freshness', edrMonitoringDirection: 'asc',
  edrMonitoringStatusSelections: {prozorro_status: new Set(), edr_status: new Set()},
  $: control, updateEdrMonitoringFilters() { this.chipCount = this.edrMonitoringStatusSelections.edr_status.size + this.edrMonitoringStatusSelections.prozorro_status.size; },
  loadEdrMonitoring() {},
  request(url) { return new Promise((resolve, reject) => requests.push({url, resolve, reject})); },
};
vm.createContext(ctx);
vm.runInContext([
  source('function edrMonitoringParams'),
  source('function updateEdrMonitoringMultiSummary'),
  source('function bindEdrMonitoringStatusMulti'),
  source('function clearEdrMonitoringFilter'),
  source('async function edrMonitoringLatestResponse'),
].join('\n'), ctx);

async function main() {
  const statuses = ['Припинено', 'В стані припинення', 'Порушено справу про банкрутство', 'Банкрут'];
  const inputs = statuses.map(value => ({value, checked: false}));
  const details = {querySelectorAll: () => inputs};
  const summary = {textContent: ''};
  ctx.$ = selector => selector === '#edrMonitoringEdr' ? details : selector === '#edrMonitoringProzorro' ? {querySelectorAll: () => []} : selector === '#edrMonitoringEdr summary' ? summary : control(selector);
  ctx.updateEdrMonitoringFilters = () => { ctx.chipCount = ctx.edrMonitoringStatusSelections.edr_status.size + ctx.edrMonitoringStatusSelections.prozorro_status.size; };
  ctx.bindEdrMonitoringStatusMulti('edrMonitoringEdr', 'edr_status');
  const selected = ctx.edrMonitoringStatusSelections.edr_status;
  function choose(index, checked) {
    inputs[index].checked = checked;
    inputs[index].onchange();
    assert.equal(ctx.chipCount, selected.size);
    assert.deepEqual(new Set(ctx.edrMonitoringParams().edr_status.split(',').filter(Boolean)), new Set(selected));
  }
  choose(0, true); assert.equal(summary.textContent, statuses[0]);
  choose(1, true); choose(2, true); assert.equal(ctx.chipCount, 3);
  const older = ctx.edrMonitoringLatestResponse();
  choose(3, true); choose(3, false); assert.equal(ctx.chipCount, 3);
  const latest = ctx.edrMonitoringLatestResponse();
  requests[1].resolve({items: [{edr_status: statuses[0]}], total: 1});
  assert.equal((await latest).total, 1);
  requests[0].resolve({items: [{edr_status: 'Зареєстровано'}], total: 11287});
  assert.equal(await older, null, 'old response cannot overwrite newer filtered rows');
  choose(1, false); assert.equal(ctx.chipCount, 2);
  ctx.clearEdrMonitoringFilter('edr_status', statuses[0]); assert.equal(ctx.chipCount, 1);
  choose(1, true); choose(1, false); assert.equal(ctx.chipCount, 1);
  choose(2, false); assert.equal(ctx.chipCount, 0);
  choose(0, true); ctx.edrMonitoringStatusSelections.prozorro_status.add('Активний');
  assert.equal(ctx.edrMonitoringParams().prozorro_status, 'Активний');
  assert.equal(ctx.edrMonitoringParams().edr_status, statuses[0]);
  ctx.edrMonitoringSelected = new Set(['supplier']);
  const resetLine = app.split('\n').find(line => line.startsWith("$('#edrMonitoringReset').onclick="));
  assert.ok(resetLine);
  vm.runInContext(resetLine, ctx);
  control('#edrMonitoringReset').onclick();
  assert.equal(ctx.chipCount, 0);
  assert.equal(ctx.edrMonitoringParams().edr_status, '');
  assert.equal(ctx.edrMonitoringParams().prozorro_status, '');
  assert.equal(ctx.edrMonitoringSelected.size, 0);
  choose(0, true); ctx.edrMonitoringStatusSelections.prozorro_status.add('Активний');
  ctx.edrMonitoringStatusSelections.prozorro_status.clear();
  ctx.clearEdrMonitoringFilter('edr_status'); assert.equal(ctx.chipCount, 0);
  ctx.bindEdrMonitoringStatusMulti('edrMonitoringEdr', 'edr_status'); assert.equal(inputs[0].checked, false);
  const staleError = ctx.edrMonitoringLatestResponse();
  ctx.edrMonitoringStatusSelections.edr_status.add(statuses[2]);
  requests[2].reject(new Error('obsolete failure'));
  assert.equal(await staleError, null);
  const body = control('#edrMonitoringBody');
  body.querySelectorAll = () => [];
  ctx.$$ = () => [];
  ctx.performance = {now: () => 1};
  ctx.edrMonitoringSelected = new Set();
  ctx.edrFreshnessLabels = {not_checked: 'not checked'};
  ctx.esc = value => String(value ?? '');
  ctx.displayDateOnly = value => value || '';
  ctx.renderEdrMonitoringEdrStatuses = () => {};
  ctx.applyEdrMonitoringColumns = () => {};
  ctx.updateEdrMonitoringSelection = () => {};
  vm.runInContext(source('async function loadEdrMonitoring'), ctx);
  selected.add(statuses[0]);
  const obsoleteLoad = ctx.loadEdrMonitoring();
  selected.add(statuses[1]);
  const currentLoad = ctx.loadEdrMonitoring();
  requests[4].resolve({items: [{supplier_code: '1', edr_status: statuses[1], prozorro_status: 'Активний'}], total: 1, pages: 1});
  await currentLoad;
  requests[3].resolve({items: [{supplier_code: '2', edr_status: 'Зареєстровано'}], total: 11287, pages: 113});
  await obsoleteLoad;
  assert.equal(ctx.edrMonitoringTotal, 1);
  assert.match(body.innerHTML, /data-edr-code="1"/);
  assert.doesNotMatch(body.innerHTML, /data-edr-code="2"/);
  console.log('EDR multiselect state and stale-response regressions: OK');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
