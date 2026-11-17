const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('queue_statistics_ui.js', 'utf8');
const appSource = fs.readFileSync('app.js', 'utf8');
const serverSource = fs.readFileSync('server.py', 'utf8');
const indexSource = fs.readFileSync('index.html', 'utf8');
const stylesSource = fs.readFileSync('styles.css', 'utf8') + fs.readFileSync('uo_work_page.css', 'utf8');
const themeSource = fs.readFileSync('theme.css', 'utf8') + fs.readFileSync('uo_work_page.css', 'utf8');
const formatterDefinition = appSource.match(/const titleCaseWord=[^\n]+\r?\nconst formatOfficerName=[^\n]+;\r?\nconst formatQueueOfficer=[^\n]+;/)?.[0];
assert.ok(formatterDefinition, 'app.js exposes the shared officer-name formatters');
const formatterContext = vm.createContext({esc:value=>String(value)});
vm.runInContext(`${formatterDefinition};globalThis.formatOfficerName=formatOfficerName;globalThis.formatQueueOfficer=formatQueueOfficer;`, formatterContext);
const formatOfficerName = formatterContext.formatOfficerName;
const formatQueueOfficer = formatterContext.formatQueueOfficer;

function makeNode(value = '') {
  const classes = new Set();
  const summary = {textContent:'',title:''};
  return {
    value, dataset:{}, options:[], innerHTML:'', textContent:'', hidden:false, disabled:false, style:{},
    listeners:{}, classes, summary,
    classList:{toggle(name,active){if(active)classes.add(name);else classes.delete(name);},contains(name){return classes.has(name);}},
    addEventListener(type,handler){this.listeners[type]=handler;},
    replaceChildren(...children){this.options=children;},
    setAttribute(){}, removeAttribute(){},
    querySelector(selector){return selector==='summary'?summary:selector==='thead'?{getBoundingClientRect:()=>({height:28})}:null;},
    querySelectorAll(selector){return selector==='tr'?[...this.innerHTML.matchAll(/<tr>/g)].map(()=>({getBoundingClientRect:()=>({height:30})})):[];},
    closest(){return null;},
  };
}

function harness(items) {
  const ids = [
    'queueProtocolOfficerCards','queueStatisticsDkFilter','queueStatisticsDkOptions','queueStatisticsFilterPanel','queueStatisticsKpis','queueStatisticsRows','queueStatisticsMessage',
    'queueStatisticsFrom','queueStatisticsTo','queueStatisticsGroup','queueStatisticsFilters','queueStatisticsReset',
    'queueStatisticsFilterSummary','queueStatisticsPending','queueStatisticsFromField','queueStatisticsToField','queueStatisticsGroupField',
    'queueProtocolFrom','queueProtocolTo','queueProtocolApply','dateFromFilter','dateToFilter','protocolDecisionFilter','queueRegistryScope',
    'clearFiltersBtn','statusFilter','dkFilter',
  ];
  const nodes=Object.fromEntries(ids.map(id=>[id,makeNode()]));
  nodes.queueStatisticsTable=makeNode();
  nodes.queueStatisticsFrom.value='2026-01-01';
  nodes.queueStatisticsTo.value='2026-01-31';
  nodes.queueProtocolFrom.value='2026-01-01';
  nodes.queueProtocolTo.value='2026-01-31';
  nodes.queueStatisticsGroup.value='review_officer';
  nodes.queueStatisticsPending.hidden=true;
  const controls=['category','review_officer','protocol_officer'].map(key=>{const node=makeNode();node.dataset.statisticsFilter=key;return node;});
  const labels=controls.map(()=>makeNode());
  controls.forEach((control,index)=>{control.closest=selector=>selector==='label'?labels[index]:null;});
  const calls=[];
  const context=vm.createContext({
    API:'/api',URLSearchParams,Option:function Option(text,value){this.text=text;this.value=value;},window:{},
    $(selector){return selector.startsWith('.')?nodes.queueStatisticsTable:nodes[selector.replace(/^#/,'')];},
    $$(selector){return selector==='[data-statistics-filter]'?controls:[];},
    request:async url=>{calls.push(url);return{items};},esc:value=>String(value),formatOfficerName,
    filterSelections:{dk:new Set(),status:new Set()},queueRegistryFilters:{},categoryFilter:'',resetApplicationsForExternalKpi(){},
    syncPrimaryFilters(){},updateMultiSummary(){},saveFilterState(){},updateApplicationFilterStyles(){},showModule(){},
    loadApplicationsForExternalKpi:async()=>{},page:1,
  });
  vm.runInContext(source,context,{filename:'queue_statistics_ui.js'});
  return{context,nodes,calls,controls,labels};
}

const sample=[
  {review_officer:'ДМИТРО САВВА',protocol_officer:'ОЛЕНА ЄРЬОМІНА',dk_code:'02100000-6',category:'ЇЖА',status:'active',total:3},
  {review_officer:'ДМИТРО САВВА',protocol_officer:'ТЕТЯНА ФЕДЧЕНКО',dk_code:'02100000-6',category:'ЇЖА',status:'unsuccessful',total:1},
  {review_officer:'СВІТЛАНА НАМЯСЕНКО',protocol_officer:'ТЕТЯНА ФЕДЧЕНКО',dk_code:'03000000-1',category:'ПОСЛУГИ',status:'pending',total:2},
];

test('statistics keeps existing default grouping and supports protocol grouping without changing totals',async()=>{
  const h=harness(sample);
  h.context.window.refreshQueueApplicationStatistics();
  await new Promise(resolve=>setImmediate(resolve));
  const requests=h.calls.map(url=>new URL(url,'https://pqm.test'));
  const progress=requests.find(url=>url.searchParams.get('summary')==='review-progress');
  const stats=requests.find(url=>url.searchParams.get('summary')==='application-statistics');
  assert.equal(progress.searchParams.get('group_by'),'protocol_officer');
  assert.equal(progress.searchParams.get('date_from'),'2026-01-01');
  assert.equal(progress.searchParams.get('date_to'),'2026-01-31');
  assert.equal(stats.searchParams.has('group_by'),false);
  assert.match(h.nodes.queueStatisticsKpis.innerHTML,/Допущено/);
  assert.match(h.nodes.queueStatisticsKpis.innerHTML,/>3</);
  assert.match(h.nodes.queueStatisticsKpis.innerHTML,/Відхилено/);
  assert.match(h.nodes.queueStatisticsRows.innerHTML,/Дмитро САВВА/);
  assert.match(h.nodes.queueStatisticsRows.innerHTML,/Світлана НАМЯСЕНКО/);
  assert.equal(h.nodes.queueStatisticsMessage.textContent,'');
  assert.ok(h.nodes.queueStatisticsFromField.classList.contains('filter-active'));
  assert.ok(h.nodes.queueStatisticsToField.classList.contains('filter-active'));
  assert.equal(h.nodes.queueStatisticsFilterSummary.textContent,'Фільтри');
  assert.equal(h.nodes.queueStatisticsGroup.value,'review_officer');
});

test('inverted statistics date range is rejected without issuing a request',async()=>{
  const h=harness([]);
  h.nodes.queueStatisticsFrom.value='2026-02-01';
  h.nodes.queueStatisticsTo.value='2026-01-01';
  h.nodes.queueStatisticsFilters.onsubmit({preventDefault(){}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(h.calls.length,0);
  assert.equal(h.nodes.queueStatisticsMessage.textContent,'Дата «До» має бути не раніше дати «Від»');
});

test('statistics table shows at most five rows before internal scrolling and clears the limit for five or fewer',async()=>{
  for(const count of [3,5,8]){
    const items=Array.from({length:count},(_,index)=>({review_officer:`УО ${index}`,protocol_officer:`УО ${index}`,dk_code:'',category:'',status:'active',total:1}));
    const h=harness(items);
    h.context.window.refreshQueueApplicationStatistics();
    await new Promise(resolve=>setImmediate(resolve));
    const scroll=h.nodes.queueStatisticsTable.classList.contains('queue-statistics-table--scroll');
    assert.equal(scroll,count>5);
    assert.equal(h.nodes.queueStatisticsTable.style.maxHeight,count>5?'178px':'');
  }
});

test('filter edits remain distinct from applied dates; grouping does not change aggregate totals',async()=>{
  const h=harness(sample);
  h.context.window.refreshQueueApplicationStatistics();
  await new Promise(resolve=>setImmediate(resolve));
  const before=h.nodes.queueStatisticsKpis.innerHTML;
  h.nodes.queueStatisticsFrom.value='2026-01-02';
  h.nodes.queueStatisticsFrom.listeners.input();
  assert.ok(!h.nodes.queueStatisticsFromField.classList.contains('filter-active'));
  assert.equal(h.nodes.queueStatisticsPending.hidden,false);
  assert.match(h.nodes.queueStatisticsPending.textContent,/ще не застосовано/);
  h.nodes.queueStatisticsGroup.value='protocol_officer';
  h.nodes.queueStatisticsGroup.onchange();
  assert.ok(h.nodes.queueStatisticsGroupField.classList.contains('filter-active'));
  assert.match(h.nodes.queueStatisticsRows.innerHTML,/Олена ЄРЬОМІНА/);
  assert.match(h.nodes.queueStatisticsRows.innerHTML,/Тетяна ФЕДЧЕНКО/);
  assert.equal(h.nodes.queueStatisticsKpis.innerHTML,before);
  h.controls[0].value='ЇЖА';
  h.controls[0].onchange();
  assert.equal(h.nodes.queueStatisticsFilterSummary.textContent,'Фільтри · 1');
  assert.ok(h.labels[0].classList.contains('filter-active'));
  h.nodes.queueStatisticsReset.onclick();
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(h.nodes.queueStatisticsFilterSummary.textContent,'Фільтри');
  assert.ok(h.labels.every(label=>!label.classList.contains('filter-active')));
  assert.ok(!h.nodes.queueStatisticsGroupField.classList.contains('filter-active'));
  assert.equal(h.nodes.queueStatisticsGroup.value,'review_officer');
  assert.equal(h.nodes.queueStatisticsFrom.value,'2026-01-01');
  assert.equal(h.nodes.queueStatisticsTo.value,'2026-01-31');
});

test('DK code accepts multiple selected values as one applied filter dimension',async()=>{
  const h=harness(sample);
  h.context.window.refreshQueueApplicationStatistics();
  await new Promise(resolve=>setImmediate(resolve));
  const first={value:'02100000-6',checked:true,closest:selector=>selector==='[data-statistics-dk-option]'?first:null};
  h.nodes.queueStatisticsDkOptions.onchange({target:first});
  assert.equal(h.nodes.queueStatisticsFilterSummary.textContent,'Фільтри · 1');
  assert.equal(h.nodes.queueStatisticsDkFilter.summary.textContent,'Коди ДК · 1');
  assert.ok(h.nodes.queueStatisticsDkFilter.classList.contains('filter-active'));
  assert.match(h.nodes.queueStatisticsKpis.innerHTML,/>3</);
  const second={value:'03000000-1',checked:true,closest:selector=>selector==='[data-statistics-dk-option]'?second:null};
  h.nodes.queueStatisticsDkOptions.onchange({target:second});
  assert.equal(h.nodes.queueStatisticsFilterSummary.textContent,'Фільтри · 1');
  assert.match(h.nodes.queueStatisticsKpis.innerHTML,/>2</);
});

test('protocol officer cards use the protocol progress API and separate the two click targets',()=>{
  assert.match(appSource,/renderProtocolOfficer=item=>`<article[^`]+data-protocol-officer=/);
  assert.match(appSource,/data-protocol-main/);
  assert.match(appSource,/data-protocol-pending/);
  assert.match(appSource,/window\.openQueueProtocolApplications\?\.\(card\.dataset\.protocolOfficer,action\.hasAttribute\('data-protocol-pending'\)\)/);
  assert.match(source,/group_by:'protocol_officer'/);
  assert.match(source,/Розглянуто: \$\{number\(reviewed\)\} із \$\{number\(total\)\} \(\$\{ratio\}%\)/);
  assert.match(source,/Не розглянуто: \$\{number\(notReviewed\)\}\. Відкрити в реєстрі заявок/);
  assert.match(source,/pendingButton\.disabled=notReviewed===0/);
  assert.match(source,/window\.openQueueProtocolApplications=/);
  assert.match(serverSource,/group_by=params\.get\("group_by", \["review_officer"\]\)\[0\]/);
  assert.match(serverSource,/protocol_card_officer/);
  assert.match(serverSource,/CASEFOLD\(\{protocol_group\}\)=CASEFOLD\(\?\)/);
});

test('protocol card drilldown uses its matching date cohort and optionally only undecided applications',async()=>{
  const h=harness(sample);
  h.context.window.openQueueProtocolApplications('ТЕТЯНА ФЕДЧЕНКО',true);
  assert.equal(h.context.queueRegistryFilters.protocol_card_officer,'ТЕТЯНА ФЕДЧЕНКО');
  assert.equal(h.nodes.dateFromFilter.value,'2026-01-01');
  assert.equal(h.nodes.dateToFilter.value,'2026-01-31');
  assert.equal(h.nodes.protocolDecisionFilter.value,'__empty__');
  h.context.window.openQueueProtocolApplications('ОЛЕНА ЄРЬОМІНА',false);
  assert.equal(h.context.queueRegistryFilters.protocol_card_officer,'ОЛЕНА ЄРЬОМІНА');
  assert.equal(h.nodes.protocolDecisionFilter.value,'');
});

test('approved Work UO layout order, filters, dark palette and long-table behavior are present',()=>{
  const left=indexSource.slice(indexSource.indexOf('id="queueProtocolCategoryCards"'),indexSource.indexOf('<section class="queue-publication-control">'));
  const right=indexSource.slice(indexSource.indexOf('id="queueCategoryCards"'),indexSource.indexOf('</article>',indexSource.indexOf('id="queueCategoryCards"')));
  assert.ok(left.indexOf('queueProtocolCategoryCards')<left.indexOf('queueProtocolOfficerCards'));
  assert.ok(right.indexOf('queueCategoryCards')<right.indexOf('queueQualificationCards'));
  const stats=indexSource.slice(indexSource.indexOf('queue-statistics-card'),indexSource.indexOf('class="work-queue-toolbar"'));
  assert.match(stats,/form="queueStatisticsFilters"[^>]+title="Застосувати"/);
  assert.match(stats,/id="queueStatisticsReset"[^>]+title="Очистити"/);
  assert.ok(stats.indexOf('queueStatisticsFromField')<stats.indexOf('queueStatisticsFilterPanel'));
  assert.ok(stats.indexOf('queueStatisticsFilterPanel')<stats.indexOf('queueStatisticsGroupField'));
  assert.doesNotMatch(stats,/data-statistics-filter="status"/);
  assert.match(stylesSource,/queue-statistics-heading\{display:flex/);
  assert.match(stylesSource,/queue-statistics-controls\{display:flex/);
  assert.match(stylesSource,/queue-statistics-table--scroll\{max-height/);
  assert.match(themeSource,/--uo-kpi-rejected-bg:#482932/);
  assert.match(themeSource,/--uo-kpi-pending-bg:#443b26/);
  assert.match(stylesSource,/queue-statistics-table td button\.publication-kpi[^}]+color:var\(--ink\)!important/);
});

test('shared officer formatter uses first-name then uppercase-surname and preserves special values',()=>{
  assert.equal(formatOfficerName('ДМИТРО САВВА'),'Дмитро САВВА');
  assert.equal(formatOfficerName('ОЛЕНА ЄРЬОМІНА'),'Олена ЄРЬОМІНА');
  assert.equal(formatOfficerName('СВІТЛАНА НАМЯСЕНКО'),'Світлана НАМЯСЕНКО');
  assert.equal(formatOfficerName('ТЕТЯНА ФЕДЧЕНКО'),'Тетяна ФЕДЧЕНКО');
  assert.equal(formatOfficerName('НЕ ПРИЗНАЧЕНО'),'НЕ ПРИЗНАЧЕНО');
  assert.equal(formatOfficerName('MANAGER'),'MANAGER');
  assert.equal(formatQueueOfficer('ДМИТРО САВВА'),'<span>Дмитро</span><span>САВВА</span>');
});
