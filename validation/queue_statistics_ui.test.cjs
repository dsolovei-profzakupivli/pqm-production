const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('queue_statistics_ui.js', 'utf8');

function makeNode(value = '') {
  return {
    value,
    dataset: {},
    options: [],
    innerHTML: '',
    textContent: '',
    hidden: false,
    listeners: {},
    addEventListener(type, handler) { this.listeners[type] = handler; },
    replaceChildren(...children) { this.options = children; },
    replaceChildrenCount() { return this.options.length; },
    replaceChild() {},
    setAttribute() {},
    removeAttribute() {},
  };
}

function harness(items) {
  const ids = [
    'queueReviewProgress', 'queueStatisticsKpis', 'queueStatisticsRows', 'queueStatisticsMessage',
    'queueStatisticsFrom', 'queueStatisticsTo', 'queueStatisticsGroup', 'queueStatisticsFilters',
    'queueStatisticsReset', 'queueProtocolFrom', 'queueProtocolTo', 'queueProtocolApply',
    'dateFromFilter', 'dateToFilter', 'protocolDecisionFilter', 'queueRegistryScope',
    'clearFiltersBtn', 'statusFilter', 'dkFilter',
  ];
  const nodes = Object.fromEntries(ids.map(id => [id, makeNode()]));
  nodes.queueStatisticsFrom.value = '2026-01-01';
  nodes.queueStatisticsTo.value = '2026-01-31';
  nodes.queueProtocolFrom.value = '2026-01-01';
  nodes.queueProtocolTo.value = '2026-01-31';
  nodes.queueStatisticsGroup.value = 'review_officer';
  const controls = ['dk_code', 'category', 'review_officer', 'protocol_officer'].map(key => {
    const node = makeNode(); node.dataset.statisticsFilter = key; return node;
  });
  const calls = [];
  const context = vm.createContext({
    API: '/api',
    URLSearchParams,
    Option: function Option(text, value) { this.text = text; this.value = value; },
    window: {},
    $(selector) { return nodes[selector.replace(/^#/, '')]; },
    $$(selector) { return selector === '[data-statistics-filter]' ? controls : []; },
    request: async url => {
      calls.push(url);
      return {items};
    },
    esc: value => String(value),
    formatOfficerName: value => value,
    filterSelections: {dk: new Set(), status: new Set()},
    queueRegistryFilters: {},
    resetApplicationsForExternalKpi() {},
    syncPrimaryFilters() {},
    updateMultiSummary() {},
    saveFilterState() {},
    updateApplicationFilterStyles() {},
    showModule() {},
    loadApplicationsForExternalKpi: async () => {},
    page: 1,
  });
  vm.runInContext(source, context, {filename: 'queue_statistics_ui.js'});
  return {context, nodes, calls, controls};
}

test('queue statistics loads the selected period and renders status KPIs by officer', async () => {
  const h = harness([
    {review_officer: 'Officer A', protocol_officer: 'Officer B', status: 'active', total: 3},
    {review_officer: 'Officer A', protocol_officer: 'Officer B', status: 'unsuccessful', total: 1},
    {review_officer: 'Officer C', protocol_officer: 'Officer D', status: 'pending', total: 2},
  ]);
  h.context.window.refreshQueueApplicationStatistics();
  await new Promise(resolve => setImmediate(resolve));
  const query = new URL(h.calls.find(url => url.includes('application-statistics')), 'https://pqm.test');
  assert.equal(query.searchParams.get('date_from'), '2026-01-01');
  assert.equal(query.searchParams.get('date_to'), '2026-01-31');
  assert.match(h.nodes.queueStatisticsKpis.innerHTML, /Допущено/);
  assert.match(h.nodes.queueStatisticsKpis.innerHTML, /3/);
  assert.match(h.nodes.queueStatisticsKpis.innerHTML, /Відхилено/);
  assert.match(h.nodes.queueStatisticsKpis.innerHTML, /1/);
  assert.match(h.nodes.queueStatisticsRows.innerHTML, /Officer A/);
  assert.match(h.nodes.queueStatisticsRows.innerHTML, /Officer C/);
  assert.equal(h.nodes.queueStatisticsMessage.textContent, '');
});

test('queue statistics rejects an inverted date range without issuing a request', async () => {
  const h = harness([]);
  h.nodes.queueStatisticsFrom.value = '2026-02-01';
  h.nodes.queueStatisticsTo.value = '2026-01-01';
  h.nodes.queueStatisticsFilters.onsubmit({preventDefault() {}});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.calls.length, 0);
  assert.equal(h.nodes.queueStatisticsMessage.textContent, 'Дата «До» має бути не раніше дати «Від»');
});
