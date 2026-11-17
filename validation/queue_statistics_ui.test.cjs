const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('queue_statistics_ui.js', 'utf8');
const appSource = fs.readFileSync('app.js', 'utf8');
const stylesSource = fs.readFileSync('styles.css', 'utf8');
const formatterDefinition = appSource.match(/const titleCaseWord=[^\n]+\r?\nconst formatOfficerName=[^\n]+;\r?\nconst formatQueueOfficer=[^\n]+;/)?.[0];
assert.ok(formatterDefinition, 'app.js exposes the shared officer-name formatters');
const formatterContext = vm.createContext({esc:value=>String(value)});
vm.runInContext(`${formatterDefinition};globalThis.formatOfficerName=formatOfficerName;globalThis.formatQueueOfficer=formatQueueOfficer;`, formatterContext);
const formatOfficerName = formatterContext.formatOfficerName;
const formatQueueOfficer = formatterContext.formatQueueOfficer;

function makeNode(value = '') {
  const classes = new Set();
  return {
    value,
    dataset: {},
    options: [],
    innerHTML: '',
    textContent: '',
    hidden: false,
    listeners: {},
    classes,
    classList: {toggle(name, active) { if (active) classes.add(name); else classes.delete(name); }, contains(name) { return classes.has(name); }},
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
    'queueStatisticsReset', 'queueStatisticsFilterSummary', 'queueStatisticsPending',
    'queueStatisticsFromField', 'queueStatisticsToField', 'queueStatisticsGroupField',
    'queueProtocolFrom', 'queueProtocolTo', 'queueProtocolApply',
    'dateFromFilter', 'dateToFilter', 'protocolDecisionFilter', 'queueRegistryScope',
    'clearFiltersBtn', 'statusFilter', 'dkFilter',
  ];
  const nodes = Object.fromEntries(ids.map(id => [id, makeNode()]));
  nodes.queueStatisticsFrom.value = '2026-01-01';
  nodes.queueStatisticsTo.value = '2026-01-31';
  nodes.queueProtocolFrom.value = '2026-01-01';
  nodes.queueProtocolTo.value = '2026-01-31';
  nodes.queueStatisticsGroup.value = 'review_officer';
  nodes.queueStatisticsPending.hidden = true;
  const controls = ['dk_code', 'category', 'review_officer', 'protocol_officer'].map(key => {
    const node = makeNode(); node.dataset.statisticsFilter = key; return node;
  });
  const labels = controls.map(()=>makeNode());
  controls.forEach((control,index)=>{control.closest=selector=>selector==='label'?labels[index]:null;});
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
    formatOfficerName,
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
  return {context, nodes, calls, controls, labels};
}

test('queue statistics loads the selected period and renders status KPIs by officer', async () => {
  const h = harness([
    {review_officer: 'ДМИТРО САВВА', protocol_officer: 'ОЛЕНА ЄРЬОМІНА', status: 'active', total: 3,reviewed:2,pending:1},
    {review_officer: 'ДМИТРО САВВА', protocol_officer: 'ОЛЕНА ЄРЬОМІНА', status: 'unsuccessful', total: 1,reviewed:1,pending:0},
    {review_officer: 'СВІТЛАНА НАМЯСЕНКО', protocol_officer: 'ТЕТЯНА ФЕДЧЕНКО', status: 'pending', total: 2,reviewed:0,pending:2},
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
  assert.match(h.nodes.queueStatisticsRows.innerHTML, /Дмитро САВВА/);
  assert.match(h.nodes.queueStatisticsRows.innerHTML, /Світлана НАМЯСЕНКО/);
  assert.equal(h.nodes.queueStatisticsMessage.textContent, '');
  assert.ok(h.nodes.queueStatisticsFromField.classList.contains('filter-active'));
  assert.ok(h.nodes.queueStatisticsToField.classList.contains('filter-active'));
  assert.equal(h.nodes.queueStatisticsFilterSummary.textContent, 'Фільтри');
  assert.match(h.nodes.queueReviewProgress.innerHTML, /Дмитро САВВА/);
  assert.ok(h.controls[2].options.some(option=>option.text==='Дмитро САВВА'));
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

test('statistics marks only applied selections and reports active filter count', async () => {
  const h = harness([
    {review_officer: 'ДМИТРО САВВА', protocol_officer: 'ОЛЕНА ЄРЬОМІНА', dk_code:'02100000-6', status: 'active', total: 2},
    {review_officer: 'ДМИТРО САВВА', protocol_officer: 'ТЕТЯНА ФЕДЧЕНКО', dk_code:'02100000-6', status: 'active', total: 3},
  ]);
  h.context.window.refreshQueueApplicationStatistics();
  await new Promise(resolve => setImmediate(resolve));

  h.nodes.queueStatisticsFrom.value = '2026-01-02';
  h.nodes.queueStatisticsFrom.listeners.input();
  assert.ok(!h.nodes.queueStatisticsFromField.classList.contains('filter-active'));
  assert.equal(h.nodes.queueStatisticsPending.hidden, false);
  assert.match(h.nodes.queueStatisticsPending.textContent, /ще не застосовано/);

  h.controls[0].value = '02100000-6';
  h.controls[2].value = 'ДМИТРО САВВА';
  h.controls[2].onchange();
  assert.equal(h.nodes.queueStatisticsFilterSummary.textContent, 'Фільтри · 2');
  assert.ok(h.labels[0].classList.contains('filter-active'));
  assert.ok(h.labels[2].classList.contains('filter-active'));
  assert.ok(!h.labels[1].classList.contains('filter-active'));
  assert.equal(h.nodes.queueStatisticsKpis.innerHTML.includes('2'), true);

  h.nodes.queueStatisticsGroup.value = 'protocol_officer';
  h.nodes.queueStatisticsGroup.onchange();
  assert.ok(h.nodes.queueStatisticsGroupField.classList.contains('filter-active'));
  assert.match(h.nodes.queueStatisticsRows.innerHTML, /Олена ЄРЬОМІНА/);
  assert.match(h.nodes.queueStatisticsRows.innerHTML, /Тетяна ФЕДЧЕНКО/);

  h.nodes.queueStatisticsReset.onclick();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.nodes.queueStatisticsFilterSummary.textContent, 'Фільтри');
  assert.ok(h.labels.every(label=>!label.classList.contains('filter-active')));
  assert.ok(!h.nodes.queueStatisticsGroupField.classList.contains('filter-active'));
  assert.equal(h.nodes.queueStatisticsFrom.value, '2026-01-01');
  assert.equal(h.nodes.queueStatisticsTo.value, '2026-01-31');
  assert.ok(h.nodes.queueStatisticsFromField.classList.contains('filter-active'));
  assert.ok(h.nodes.queueStatisticsToField.classList.contains('filter-active'));
});

test('shared officer formatter uses first-name then uppercase-surname and preserves special values', () => {
  assert.equal(formatOfficerName('ДМИТРО САВВА'), 'Дмитро САВВА');
  assert.equal(formatOfficerName('ОЛЕНА ЄРЬОМІНА'), 'Олена ЄРЬОМІНА');
  assert.equal(formatOfficerName('СВІТЛАНА НАМЯСЕНКО'), 'Світлана НАМЯСЕНКО');
  assert.equal(formatOfficerName('ТЕТЯНА ФЕДЧЕНКО'), 'Тетяна ФЕДЧЕНКО');
  assert.equal(formatOfficerName('НЕ ПРИЗНАЧЕНО'), 'НЕ ПРИЗНАЧЕНО');
  assert.equal(formatOfficerName('MANAGER'), 'MANAGER');
  assert.equal(formatQueueOfficer('НЕ ПРИЗНАЧЕНО'), 'НЕ ПРИЗНАЧЕНО');
  assert.equal(formatQueueOfficer('MANAGER'), 'MANAGER');
  assert.equal(formatQueueOfficer('ДМИТРО САВВА'), '<span>Дмитро</span><span>САВВА</span>');
});

test('publication status KPIs share accessible colors and keep existing click routing', () => {
  for (const status of ['admitted','rejected','pending']) {
    assert.match(appSource, new RegExp(`publication-kpi--${status}`));
    assert.match(stylesSource, new RegExp(`publication-kpi--${status},\\.queue-statistics-kpis button\\.${status}`));
  }
  assert.match(stylesSource, /--uo-kpi-rejected-bg:#fff0f0/);
  assert.match(stylesSource, /--uo-kpi-ink:#1f2933/);
  assert.match(appSource, /\$\('#queuePublicationControl'\)\.onclick=e=>/);
  assert.match(source, /class="ghost publication-kpi \$\{tone\}"/);
  assert.match(source, /data-statistics-action="\$\{index\}"/);
});
