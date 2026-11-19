const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('queue_statistics_ui.js', 'utf8');
const appSource = fs.readFileSync('app.js', 'utf8');
const historySource = fs.readFileSync('history_ui.js', 'utf8');
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
const protocolOfficerEditDefinition = appSource.match(/const protocolOfficerEditOptions=[^\n]+;/)?.[0];
assert.ok(protocolOfficerEditDefinition, 'registry editor builds options from stored and effective protocol officer values');
const protocolEditorContext = vm.createContext({
  protocolOfficers:['Активна УО'],
  formatOfficerName,
});
vm.runInContext(`${protocolOfficerEditDefinition};globalThis.protocolOfficerEditOptions=protocolOfficerEditOptions;`, protocolEditorContext);
const protocolOfficerEditOptions = protocolEditorContext.protocolOfficerEditOptions;

test('protocol officer editor preserves stored/manual values and does not persist a computed fallback implicitly', () => {
  const automatic = protocolOfficerEditOptions({protocolOfficer:'Олена ЄРЬОМІНА',protocolOfficerStored:''});
  assert.equal(automatic[0].value,'');
  assert.equal(automatic[0].label,'Автоматично: Олена ЄРЬОМІНА');
  assert.equal(automatic[0].selected,true);
  assert.equal(automatic.some(option=>option.value==='Олена ЄРЬОМІНА'),false);

  const historicalManual = protocolOfficerEditOptions({protocolOfficer:'Не визначено',protocolOfficerStored:'Колишня УО'});
  const stored = historicalManual.find(option=>option.value==='Колишня УО');
  assert.equal(stored.selected,true);
  assert.equal(historicalManual[0].selected,false);
  assert.match(appSource,/if\(key===['\"]protocolOfficer['\"]\)editor\.innerHTML=protocolOfficerEditOptions\(row\)/);
});

function makeNode(value = '') {
  const classes = new Set();
  const summary = {textContent:'',title:''};
  return {
    value, dataset:{}, options:[], innerHTML:'', textContent:'', hidden:false, disabled:false, style:{},
    listeners:{}, attributes:{}, classes, summary,
    classList:{toggle(name,active){if(active)classes.add(name);else classes.delete(name);},contains(name){return classes.has(name);}},
    addEventListener(type,handler){this.listeners[type]=handler;},
    replaceChildren(...children){this.options=children;},
    setAttribute(name,value){this.attributes[name]=value;}, removeAttribute(name){delete this.attributes[name];},
    querySelector(selector){return selector==='summary'?summary:selector==='thead'?{getBoundingClientRect:()=>({height:28})}:selector==='.queue-statistics-filter-section-content'?this.content:null;},
    querySelectorAll(selector){return selector==='tr'?[...this.innerHTML.matchAll(/<tr>/g)].map(()=>({getBoundingClientRect:()=>({height:30})})):[];},
    closest(){return null;},
  };
}

function harness(items) {
  const ids = [
    'queueProtocolOfficerCards','queueStatisticsDkSearch','queueStatisticsDkSummary','queueStatisticsDkOptions','queueStatisticsFilterPanel','queueStatisticsFilterToggle','queueStatisticsFilterClose','queueStatisticsWorkspace','queueStatisticsFilterApply','queueStatisticsFilterClear','queueStatisticsDkClear','queueStatisticsKpis','queueStatisticsRows','queueStatisticsMessage','queueStatisticsTrendSvg','queueStatisticsTrendChart','queueStatisticsTrendTooltip',
    'queueStatisticsFrom','queueStatisticsTo','queueStatisticsGroup','queueStatisticsFilters','queueStatisticsReset',
    'queueStatisticsFilterSummary','queueStatisticsPending','queueStatisticsFromField','queueStatisticsToField','queueStatisticsGroupField',
    'queueProtocolFrom','queueProtocolTo','queueProtocolApply','dateFromFilter','dateToFilter','protocolDecisionFilter','queueRegistryScope',
    'clearFiltersBtn','statusFilter','dkFilter',
  ];
  const nodes=Object.fromEntries(ids.map(id=>[id,makeNode()]));
  nodes.queueStatisticsTable=makeNode();
  nodes.queueStatisticsDkField=makeNode();
  nodes.queueStatisticsDkOptions.closest=selector=>selector==='.queue-statistics-dk-field'?nodes.queueStatisticsDkField:null;
  nodes.queueStatisticsTrendSvg.getBoundingClientRect=()=>({left:0,top:0,width:900,height:250});
  const sections=['supplier_type','category','dk_code','review_officer','protocol_officer'].map(key=>{
    const section=makeNode();section.dataset.statisticsFilterSection=key;
    section.state=makeNode();section.count=makeNode();section.reset=makeNode();section.content=makeNode();
    section.reset.dataset.statisticsFilterReset=key;
    section.querySelector=selector=>selector==='.queue-statistics-section-state'?section.state:selector==='.queue-statistics-section-count'?section.count:selector==='[data-statistics-filter-reset]'?section.reset:selector==='.queue-statistics-filter-section-content'?section.content:null;
    return section;
  });
  nodes.queueStatisticsFilterPanel.querySelectorAll=selector=>selector==='[data-statistics-filter-section]'?sections:[];
  nodes.queueStatisticsFilterPanel.onclick=null;
  nodes.queueStatisticsFilterPanel.hidden=true;
  nodes.queueStatisticsFrom.value='2026-01-01';
  nodes.queueStatisticsTo.value='2026-01-31';
  nodes.queueProtocolFrom.value='2026-01-01';
  nodes.queueProtocolTo.value='2026-01-31';
  nodes.queueStatisticsGroup.value='review_officer';
  nodes.queueStatisticsPending.hidden=true;
  const controls=['supplier_type','category','review_officer','protocol_officer'].map(key=>{const node=makeNode();node.dataset.statisticsFilter=key;return node;});
  controls[0].options=['','individual_entrepreneur','legal_entity','foreign_legal_entity','unknown'].map(value=>({value}));
  const labels=controls.map(()=>makeNode());
  controls.forEach((control,index)=>{control.closest=selector=>selector==='label'?labels[index]:null;});
  const calls=[];
  const trendButtons=['day','week','month'].map(value=>{const node=makeNode();node.dataset.trendGranularity=value;return node;});
  const summarize=(rows)=>{
    const totals={total:0,active:0,unsuccessful:0,pending:0},byDate=new Map(),diagnostics={empty_status:0,unknown_status:0,null_status:0,missing_qualification:0,unknown_values:[]};
    for(const row of rows){const n=Number(row.total||0);totals.total+=n;if(Object.hasOwn(totals,row.status)&&row.status!=='total')totals[row.status]+=n;else if(row.status==='')diagnostics.empty_status+=n;else if(row.status!=null){diagnostics.unknown_status+=n;diagnostics.unknown_values.push({status:row.status,total:n});}
      const date=row.date||'2026-01-01',bucket=byDate.get(date)||{date,submitted:0,active:0,unsuccessful:0,pending:0,empty_status:0,unknown_status:0,null_status:0,missing_qualification:0};bucket.submitted+=n;if(Object.hasOwn(bucket,row.status))bucket[row.status]+=n;else if(row.status==='')bucket.empty_status+=n;else if(row.status!=null)bucket.unknown_status+=n;byDate.set(date,bucket);}
    return{items:rows,totals,diagnostics,trend:[...byDate.values()],filter_options:{category:[...new Set(items.map(row=>row.category||''))],dk_code:[...new Set(items.map(row=>row.dk_code||'').filter(Boolean))],review_officer:[...new Set(items.map(row=>row.review_officer||''))],protocol_officer:[...new Set(items.map(row=>row.protocol_officer||''))]}};
  };
  let context;
  context=vm.createContext({
    API:'/api',URLSearchParams,Option:function Option(text,value){this.text=text;this.value=value;},window:{},document:{body:makeNode(),addEventListener(){}},
    $(selector){return selector.startsWith('.')?nodes.queueStatisticsTable:nodes[selector.replace(/^#/,'')];},
    $$(selector){return selector==='[data-statistics-filter]'?controls:selector==='[data-trend-granularity]'?trendButtons:[];},
    request:async url=>{calls.push(url);const parsed=new URL(url,'https://pqm.test');if(parsed.searchParams.get('summary')==='review-progress')return{items:[]};let rows=items;const entityType=parsed.searchParams.get('entity_type');if(entityType)rows=rows.filter(row=>row.entity_type===entityType);for(const key of ['category','review_officer','protocol_officer']){const value=parsed.searchParams.get(key);if(value)rows=rows.filter(row=>(row[key]||'')===(value==='__unassigned__'?'':value));}const codes=parsed.searchParams.getAll('dk_code');if(codes.length)rows=rows.filter(row=>codes.includes(row.dk_code||''));return summarize(rows);},esc:value=>String(value),formatOfficerName,
    filterSelections:{dk:new Set(),status:new Set()},queueRegistryFilters:{},categoryFilter:'',resetApplicationsForExternalKpi(){context.queueRegistryFilters={};context.filterSelections.dk.clear();context.filterSelections.status.clear();context.categoryFilter='';},
    syncPrimaryFilters(){},updateMultiSummary(){},saveFilterState(){},updateApplicationFilterStyles(){},showModule(){},
    loadApplicationsForExternalKpi:async()=>{},page:1,
  });
  const testSource=source.replace('  function renderTrend() {','  window.__buildTrendBuckets=buildTrendBuckets;\n\n  function renderTrend() {');
  vm.runInContext(testSource,context,{filename:'queue_statistics_ui.js'});
  return{context,nodes,calls,controls,labels,sections,trendButtons};
}

const sample=[
  {review_officer:'ДМИТРО САВВА',protocol_officer:'ОЛЕНА ЄРЬОМІНА',dk_code:'02100000-6',category:'ЇЖА',entity_type:'individual_entrepreneur',status:'active',total:3,date:'2026-01-01'},
  {review_officer:'ДМИТРО САВВА',protocol_officer:'ТЕТЯНА ФЕДЧЕНКО',dk_code:'02100000-6',category:'ЇЖА',entity_type:'individual_entrepreneur',status:'unsuccessful',total:1,date:'2026-01-02'},
  {review_officer:'СВІТЛАНА НАМЯСЕНКО',protocol_officer:'ТЕТЯНА ФЕДЧЕНКО',dk_code:'03000000-1',category:'ПОСЛУГИ',entity_type:'legal_entity',status:'pending',total:2,date:'2026-01-03'},
];

test('FOP rejected KPI drilldown transfers every applied filter and canonical status to the registry',async()=>{
  const h=harness(sample);
  h.context.queueRegistryFilters={officer:'ЗАЛИШОК ПОПЕРЕДНЬОГО СТАНУ',entity_type:'legal_entity'};
  h.context.window.refreshQueueApplicationStatistics();
  await new Promise(resolve=>setImmediate(resolve));
  h.controls.find(control=>control.dataset.statisticsFilter==='supplier_type').value='individual_entrepreneur';
  h.controls.find(control=>control.dataset.statisticsFilter==='category').value='ЇЖА';
  h.controls.find(control=>control.dataset.statisticsFilter==='review_officer').value='ДМИТРО САВВА';
  h.controls.find(control=>control.dataset.statisticsFilter==='protocol_officer').value='ТЕТЯНА ФЕДЧЕНКО';
  const dkChoice={checked:true,value:'02100000-6'};
  h.nodes.queueStatisticsDkOptions.onchange({target:{closest:selector=>selector==='[data-statistics-dk-option]'?dkChoice:null}});
  h.nodes.queueStatisticsFilterApply.onclick();
  await new Promise(resolve=>setImmediate(resolve));
  h.nodes.queueStatisticsKpis.onclick({target:{closest:selector=>selector==='[data-statistics-action]'?{dataset:{statisticsAction:'2'}}:null}});
  assert.equal(h.context.queueRegistryFilters.entity_type,'individual_entrepreneur');
  assert.equal(h.context.queueRegistryFilters.protocol_officer,'ТЕТЯНА ФЕДЧЕНКО');
  assert.equal(h.context.queueRegistryFilters.officer,undefined,'previous registry filters are discarded');
  assert.equal(h.context.categoryFilter,'ЇЖА');
  assert.deepEqual([...h.context.filterSelections.dk],['02100000-6']);
  assert.deepEqual([...h.context.filterSelections.status],['Відхилено']);
  assert.equal(h.context.queueRegistryFilters.actual_status,undefined,'no broad status-only guard replaces the selected status');
  assert.equal(h.nodes.dateFromFilter.value,'2026-01-01');
  assert.equal(h.nodes.dateToFilter.value,'2026-01-31');
  assert.match(h.nodes.queueRegistryScope.textContent,/Тип постачальника · ФОП/);
});

test('ordinary registry supplier type filter is visible, persisted, query-backed, and cleared independently of saved views',()=>{
  const select=indexSource.match(/<select id="applicationEntityTypeFilter"[^>]*>([\s\S]*?)<\/select>/)?.[0]||'';
  assert.ok(select,'the registry exposes a dedicated supplier-type selector');
  for(const [value,label] of [['','Усі типи постачальника'],['individual_entrepreneur','ФОП'],['legal_entity','ЮО та інші'],['foreign_legal_entity','Нерезидент'],['unknown','Потребує перевірки']]){
    assert.ok(select.includes(`<option value="${value}">${label}</option>`),`registry selector offers ${label}`);
  }
  assert.match(appSource,/function currentFilterParams\(\)\{return \{\.\.\.queueRegistryFilters/,'the selected type participates in registry requests and counts');
  assert.match(appSource,/\$\('#applicationEntityTypeFilter'\)\.onchange=\(\)=>\{queueRegistryFilters\.entity_type=/,'changing the selector loads rows with the selected type');
  assert.match(appSource,/entityType:queueRegistryFilters\.entity_type\|\|''/,'the ordinary filter survives registry reloads');
  assert.match(appSource,/query\.get\('entity_type'\)\?\?state\.entityType/,'the type restores from the transition URL before the prior local filter');
  assert.match(appSource,/queueRegistryFilters=\{\};\$\('#applicationEntityTypeFilter'\)\.value=''/,'clear-all returns the type selector to All');
  assert.match(appSource,/toggle\('#applicationEntityTypeFilter',queueRegistryFilters\.entity_type\)/,'the active type is reflected in registry filter styling');
  assert.match(appSource,/body:JSON\.stringify\(\{name,columns:applicationProfileColumns\(\),kpis:profile\(\)\.kpis,sorts:multiSort,/,'saved user views continue to store only their existing columns, KPIs, and sorts');
});

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
  assert.match(h.nodes.queueStatisticsKpis.innerHTML,/Подано заявок/);
  assert.match(h.nodes.queueStatisticsTrendSvg.innerHTML,/trend-submitted/);
  assert.match(h.nodes.queueStatisticsTrendSvg.innerHTML,/trend-active/);
  assert.match(h.nodes.queueStatisticsTrendSvg.innerHTML,/trend-unsuccessful/);
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
  h.controls.find(control=>control.dataset.statisticsFilter==='category').value='ЇЖА';
  h.controls.find(control=>control.dataset.statisticsFilter==='category').onchange();
  assert.equal(h.nodes.queueStatisticsFilterSummary.textContent,'Фільтри');
  assert.ok(h.sections.find(section=>section.dataset.statisticsFilterSection==='category').classList.contains('filter-pending'));
  assert.equal(h.nodes.queueStatisticsPending.hidden,false);
  h.nodes.queueStatisticsFilterToggle.onclick();
  assert.equal(h.nodes.queueStatisticsFilterPanel.hidden,false);
  assert.equal(h.nodes.queueStatisticsFilterToggle.attributes['aria-expanded'],'true');
  h.nodes.queueStatisticsFilterToggle.onclick();
  assert.equal(h.nodes.queueStatisticsFilterPanel.hidden,true,'closing the panel does not discard a draft');
  assert.equal(h.nodes.queueStatisticsFilterToggle.attributes['aria-expanded'],'false');
  h.nodes.queueStatisticsFilterToggle.onclick();
  h.nodes.queueStatisticsFilterApply.onclick();
  assert.equal(h.nodes.queueStatisticsFilterSummary.textContent,'Фільтри · 1');
  assert.ok(h.sections.find(section=>section.dataset.statisticsFilterSection==='category').classList.contains('filter-active'));
  assert.equal(h.nodes.queueStatisticsFilterPanel.hidden,true);
  const appliedKpis=h.nodes.queueStatisticsKpis.innerHTML;
  h.nodes.queueStatisticsFilterToggle.onclick();
  h.nodes.queueStatisticsFilterToggle.onclick();
  assert.equal(h.nodes.queueStatisticsKpis.innerHTML,appliedKpis,'closing the panel preserves applied filters');
  h.nodes.queueStatisticsReset.onclick();
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(h.nodes.queueStatisticsFilterSummary.textContent,'Фільтри');
  assert.ok(h.sections.every(section=>!section.classList.contains('filter-active')));
  assert.ok(!h.nodes.queueStatisticsGroupField.classList.contains('filter-active'));
  assert.equal(h.nodes.queueStatisticsGroup.value,'review_officer');
  assert.equal(h.nodes.queueStatisticsFrom.value,'2026-01-01');
  assert.equal(h.nodes.queueStatisticsTo.value,'2026-01-31');
});

test('closing by the panel x keeps drafts and per-filter x clears only that applied filter',async()=>{
  const h=harness(sample);
  h.context.window.refreshQueueApplicationStatistics();
  await new Promise(resolve=>setImmediate(resolve));
  const category=h.controls.find(control=>control.dataset.statisticsFilter==='category');
  const officer=h.controls.find(control=>control.dataset.statisticsFilter==='review_officer');
  category.value='ЇЖА';h.nodes.queueStatisticsFilterApply.onclick();
  await new Promise(resolve=>setImmediate(resolve));
  h.nodes.queueStatisticsFilterToggle.onclick();
  officer.value='СВІТЛАНА НАМЯСЕНКО';officer.onchange();h.nodes.queueStatisticsFilterClose.onclick();
  assert.equal(h.nodes.queueStatisticsFilterPanel.hidden,true);
  assert.equal(officer.value,'СВІТЛАНА НАМЯСЕНКО','close preserves unapplied draft');
  h.nodes.queueStatisticsFilterToggle.onclick();
  const categorySection=h.sections.find(section=>section.dataset.statisticsFilterSection==='category');
  assert.ok(categorySection.classList.contains('filter-active'));
  assert.ok(h.sections.find(section=>section.dataset.statisticsFilterSection==='review_officer').classList.contains('filter-pending'));
  h.nodes.queueStatisticsFilterPanel.onclick({target:{closest(selector){return selector==='[data-statistics-filter-reset]'?categorySection.reset:null;}}});
  await new Promise(resolve=>setImmediate(resolve));
  const latest=new URL(h.calls.at(-1),'https://pqm.test');
  assert.equal(latest.searchParams.has('category'),false,'single x removes its applied filter');
  assert.equal(latest.searchParams.has('review_officer'),false,'another draft is not applied');
  assert.equal(officer.value,'СВІТЛАНА НАМЯСЕНКО','other draft remains for a later Apply');
  assert.ok(h.sections.find(section=>section.dataset.statisticsFilterSection==='review_officer').classList.contains('filter-pending'));
});

test('clear all resets drawer filters but preserves the selected date range',async()=>{
  const h=harness(sample);
  h.context.window.refreshQueueApplicationStatistics();
  await new Promise(resolve=>setImmediate(resolve));
  h.controls.find(control=>control.dataset.statisticsFilter==='category').value='ЇЖА';
  h.nodes.queueStatisticsFilterApply.onclick();
  await new Promise(resolve=>setImmediate(resolve));
  h.nodes.queueStatisticsFrom.value='2026-01-02';
  h.nodes.queueStatisticsTo.value='2026-01-20';
  h.nodes.queueStatisticsFilterClear.onclick();
  await new Promise(resolve=>setImmediate(resolve));
  const latest=new URL(h.calls.at(-1),'https://pqm.test');
  assert.equal(latest.searchParams.get('date_from'),'2026-01-02');
  assert.equal(latest.searchParams.get('date_to'),'2026-01-20');
  assert.equal(latest.searchParams.has('category'),false);
  assert.equal(h.nodes.queueStatisticsFilterSummary.textContent,'Фільтри');
});

test('submitted KPI and status values stay aligned while anomalies remain visible',async()=>{
  const rows=[
    {...sample[0],total:1},
    {...sample[1],total:1},
    {...sample[2],total:2},
    {...sample[2],status:'pending',total:1},
    {...sample[2],status:'pending',total:1},
    {...sample[2],status:'',total:1},
    {...sample[2],status:'paused',total:1},
  ];
  const h=harness(rows);h.context.window.refreshQueueApplicationStatistics();
  await new Promise(resolve=>setImmediate(resolve));
  assert.match(h.nodes.queueStatisticsKpis.innerHTML,/Подано заявок/);
  assert.match(h.nodes.queueStatisticsKpis.innerHTML,/>8</);
  assert.match(h.nodes.queueStatisticsKpis.innerHTML,/>4</,'NULL/missing status normalization is represented in the pending KPI');
  assert.match(h.nodes.queueStatisticsMessage.textContent,/порожній статус: 1/);
  assert.match(h.nodes.queueStatisticsMessage.textContent,/невідомий статус: 1/);
  assert.match(h.nodes.queueStatisticsMessage.textContent,/різниця 2/);
});

test('trend switches day/week/month, fills empty periods and exposes a keyboard tooltip',async()=>{
  const h=harness(sample);
  h.context.window.refreshQueueApplicationStatistics();
  await new Promise(resolve=>setImmediate(resolve));
  const daily=h.nodes.queueStatisticsTrendSvg.innerHTML;
  assert.equal((daily.match(/trend-axis-label/g)||[]).length,6,'daily view caps axis labels while retaining the selected range');
  assert.match(daily,/trend-line trend-submitted/);
  const week=h.trendButtons.find(button=>button.dataset.trendGranularity==='week');
  week.onclick();
  const weekly=h.nodes.queueStatisticsTrendSvg.innerHTML;
  assert.ok((weekly.match(/trend-axis-label/g)||[]).length<=6);
  assert.equal(week.attributes['aria-pressed'],'true');
  const month=h.trendButtons.find(button=>button.dataset.trendGranularity==='month');
  month.onclick();
  const monthly=h.nodes.queueStatisticsTrendSvg.innerHTML;
  assert.equal((monthly.match(/trend-axis-label/g)||[]).length,1,`monthly view includes the selected calendar month: ${monthly}`);
  h.nodes.queueStatisticsTrendSvg.onkeydown({key:'ArrowRight',preventDefault(){}});
  assert.equal(h.nodes.queueStatisticsTrendTooltip.hidden,false);
  assert.match(h.nodes.queueStatisticsTrendTooltip.innerHTML,/Надійшло:/);
  assert.equal(h.nodes.queueStatisticsKpis.innerHTML.match(/<span>Подано заявок<\/span>/g)?.length,1);
});

test('daily, Monday-based weekly and calendar-month buckets count intervals instead of accumulating',()=>{
  const h=harness([]);
  const rows=[
    {date:'2026-01-01',submitted:2,active:2,unsuccessful:0,pending:0},
    {date:'2026-01-03',submitted:5,active:0,unsuccessful:3,pending:2},
    {date:'2026-01-08',submitted:1,active:0,unsuccessful:0,pending:1},
    {date:'2026-01-11',submitted:3,active:1,unsuccessful:2,pending:0},
  ];
  const bucket=(granularity,start='2026-01-01',end='2026-01-11')=>JSON.parse(JSON.stringify(h.context.window.__buildTrendBuckets(rows,start,end,granularity)));
  const daily=bucket('day');
  assert.deepEqual(daily.map(row=>row.date),Array.from({length:11},(_,index)=>new Date(Date.UTC(2026,0,index+1)).toISOString().slice(0,10)));
  assert.deepEqual(daily.map(row=>row.submitted),[2,0,5,0,0,0,0,1,0,0,3],'empty calendar days are zero and daily values are not cumulative');
  assert.deepEqual(daily.map(row=>row.active),[2,0,0,0,0,0,0,0,0,0,1]);
  const weekly=bucket('week');
  assert.deepEqual(weekly.map(row=>row.date),['2025-12-29','2026-01-05'],'week keys begin on Monday');
  assert.deepEqual(weekly.map(row=>row.submitted),[7,4],'weekly values count only applications received in each Monday-based week, not cumulative totals');
  const monthly=bucket('month','2026-01-01','2026-03-31');
  assert.deepEqual(monthly.map(row=>row.date),['2026-01-01','2026-02-01','2026-03-01']);
  assert.deepEqual(monthly.map(row=>row.submitted),[11,0,0],'calendar months with no applications are zero');
});

test('DK code accepts multiple selected values as one applied filter dimension',async()=>{
  const h=harness(sample);
  h.context.window.refreshQueueApplicationStatistics();
  await new Promise(resolve=>setImmediate(resolve));
  const initial=h.nodes.queueStatisticsKpis.innerHTML;
  const first={value:'02100000-6',checked:true,closest:selector=>selector==='[data-statistics-dk-option]'?first:null};
  h.nodes.queueStatisticsDkOptions.onchange({target:first});
  assert.equal(h.nodes.queueStatisticsFilterSummary.textContent,'Фільтри');
  assert.equal(h.nodes.queueStatisticsDkSummary.textContent,'Чернетка: 1');
  assert.equal(h.nodes.queueStatisticsKpis.innerHTML,initial,'draft DK selection does not alter statistics before Apply');
  h.nodes.queueStatisticsDkSearch.value='030';
  h.nodes.queueStatisticsDkSearch.listeners.input();
  assert.match(h.nodes.queueStatisticsDkOptions.innerHTML,/value="02100000-6" checked/,'search preserves the selected code');
  assert.match(h.nodes.queueStatisticsDkOptions.innerHTML,/value="03000000-1"/,'search finds a partial code');
  const second={value:'03000000-1',checked:true,closest:selector=>selector==='[data-statistics-dk-option]'?second:null};
  h.nodes.queueStatisticsDkOptions.onchange({target:second});
  assert.equal(h.nodes.queueStatisticsFilterSummary.textContent,'Фільтри','draft selection remains unapplied until Apply');
  h.nodes.queueStatisticsFilterApply.onclick();
  assert.equal(h.nodes.queueStatisticsFilterSummary.textContent,'Фільтри · 1');
  assert.match(h.nodes.queueStatisticsKpis.innerHTML,/>3</);
  assert.match(h.nodes.queueStatisticsKpis.innerHTML,/>2</);
  h.nodes.queueStatisticsFilterToggle.onclick();
  h.nodes.queueStatisticsDkClear.onclick();
  assert.equal(h.nodes.queueStatisticsDkSummary.textContent,'Усі коди');
  assert.ok(h.nodes.queueStatisticsPending.textContent.includes('Зміни фільтрів ще не застосовано'));
  h.nodes.queueStatisticsFilterClear.onclick();
  assert.equal(h.nodes.queueStatisticsFilterSummary.textContent,'Фільтри');
  assert.equal(h.nodes.queueStatisticsFilterPanel.hidden,false,'Clear keeps the filter panel open');
  assert.match(h.nodes.queueStatisticsKpis.innerHTML,/>3</,'clearing filters restores admitted count');
  assert.match(h.nodes.queueStatisticsKpis.innerHTML,/>1</,'clearing filters restores rejected count');
  assert.match(h.nodes.queueStatisticsKpis.innerHTML,/>2</,'clearing filters restores pending count');
});

test('supplier type is sent to the server and filters KPI and officer rows before client-side dimensions',async()=>{
  const typed=[
    {entity_type:'individual_entrepreneur',review_officer:'УО ФОП',protocol_officer:'УО П',dk_code:'02100000-6',category:'ЇЖА',status:'active',total:1,date:'2026-01-01'},
    {entity_type:'individual_entrepreneur',review_officer:'УО ФОП',protocol_officer:'УО П',dk_code:'01000000-0',category:'ЇЖА',status:'pending',total:1,date:'2026-01-02'},
    {entity_type:'legal_entity',review_officer:'УО ЮО',protocol_officer:'УО П',dk_code:'03000000-1',category:'ПОСЛУГИ',status:'unsuccessful',total:4},
    {entity_type:'foreign_legal_entity',review_officer:'УО Н',protocol_officer:'УО Q',dk_code:'02100000-6',category:'ЇЖА',status:'pending',total:3},
    {entity_type:'unknown',review_officer:'УО ?',protocol_officer:'УО Q',dk_code:'03000000-1',category:'ПОСЛУГИ',status:'pending',total:5},
  ];
  const h=harness(typed);
  h.context.window.refreshQueueApplicationStatistics();
  await new Promise(resolve=>setImmediate(resolve));
  h.controls.find(control=>control.dataset.statisticsFilter==='supplier_type').value='individual_entrepreneur';
  h.controls.find(control=>control.dataset.statisticsFilter==='category').value='ЇЖА';
  h.controls.find(control=>control.dataset.statisticsFilter==='review_officer').value='УО ФОП';
  h.controls.find(control=>control.dataset.statisticsFilter==='protocol_officer').value='УО П';
  for(const code of ['02100000-6','01000000-0']){
    h.nodes.queueStatisticsDkOptions.onchange({target:{closest:()=>({value:code,checked:true})}});
  }
  h.nodes.queueStatisticsFilterApply.onclick();
  await new Promise(resolve=>setImmediate(resolve));
  const filtered=new URL(h.calls.at(-1),'https://pqm.test');
  assert.equal(filtered.searchParams.get('entity_type'),'individual_entrepreneur');
  assert.equal(filtered.searchParams.get('category'),'ЇЖА');
  assert.equal(filtered.searchParams.get('review_officer'),'УО ФОП');
  assert.equal(filtered.searchParams.get('protocol_officer'),'УО П');
  assert.deepEqual(filtered.searchParams.getAll('dk_code').sort(),['01000000-0','02100000-6']);
  assert.equal(filtered.searchParams.get('date_from'),'2026-01-01');
  assert.equal(h.nodes.queueStatisticsFilterSummary.textContent,'Фільтри · 5');
  assert.match(h.nodes.queueStatisticsKpis.innerHTML,/>2</,'submitted KPI uses the full filtered cohort');
  assert.match(h.nodes.queueStatisticsKpis.innerHTML,/>1</,'status KPIs use that same filtered cohort');
  assert.doesNotMatch(h.nodes.queueStatisticsRows.innerHTML,/УО ЮО|УО Н|УО \?/);
  const before={kpis:h.nodes.queueStatisticsKpis.innerHTML,table:h.nodes.queueStatisticsRows.innerHTML,filters:h.nodes.queueStatisticsFilterSummary.textContent,calls:h.calls.length};
  for(const button of h.trendButtons)button.onclick();
  assert.equal(h.nodes.queueStatisticsKpis.innerHTML,before.kpis,'scale changes do not alter KPI values');
  assert.equal(h.nodes.queueStatisticsRows.innerHTML,before.table,'scale changes do not alter table contents');
  assert.equal(h.nodes.queueStatisticsFilterSummary.textContent,before.filters,'scale changes do not alter applied filters');
  assert.equal(h.calls.length,before.calls,'scale changes do not issue extra API requests');
  assert.match(h.nodes.queueStatisticsRows.innerHTML,/Уо ФОП/);
  h.nodes.queueStatisticsFilterClear.onclick();
  await new Promise(resolve=>setImmediate(resolve));
  const cleared=new URL(h.calls.at(-1),'https://pqm.test');
  assert.equal(cleared.searchParams.has('entity_type'),false);
  assert.equal(h.nodes.queueStatisticsFilterSummary.textContent,'Фільтри');
  assert.match(h.nodes.queueStatisticsKpis.innerHTML,/>4</,'clearing restores all source categories and types');
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
  assert.match(serverSource,/CASEFOLD\(\{PROTOCOL_OFFICER_SQL\}\)=CASEFOLD\(\?\)/);
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
  assert.match(stats,/id="queueStatisticsFilterToggle"[^>]+aria-controls="queueStatisticsFilterPanel"/);
  assert.match(stats,/id="queueStatisticsSearch"[^>]+type="submit"/);
  assert.match(stats,/id="queueStatisticsReset"[^>]+title="Скинути все"/);
  assert.match(stats,/id="queueStatisticsDkSearch" type="search"[^>]*aria-label="Пошук коду ДК"/);
  assert.doesNotMatch(stats,/<label[^>]*for="queueStatisticsDkSearch">/,'the DK search no longer has a narrow visible label cell');
  for(const field of ['supplier_type','category','review_officer','protocol_officer'])assert.match(stats,new RegExp(`data-statistics-filter="${field}"`));
  const typeField=stats.match(/<select data-statistics-filter="supplier_type">([\s\S]*?)<\/select>/)?.[1]||'';
  for(const [value,label] of [['','Усі'],['individual_entrepreneur','ФОП'],['legal_entity','ЮО та інші'],['foreign_legal_entity','Нерезидент'],['unknown','Потребує перевірки']])
    assert.ok(typeField.includes(`<option value="${value}">${label}</option>`),`type option ${label} uses the registry value`);
  assert.match(serverSource,/entity_type=params\.get\("entity_type", \[""\]\)\[0\]/);
  assert.doesNotMatch(serverSource,/entity_type=\(params\.get\("entity_type", \[""\]\)\[0\][\s\S]+if summary == "application-statistics" else ""\)/);
  assert.match(stats,/id="queueStatisticsFilterApply"[^>]*aria-label="Застосувати вибрані фільтри"/);
  assert.match(stats,/id="queueStatisticsFilterClear"[^>]*aria-label="Очистити всі фільтри"/);
  assert.match(stats,/id="queueStatisticsFilterApply"[^>]*>[\s\S]*?<svg/);
  assert.match(stats,/id="queueStatisticsFilterClear"[^>]*>[\s\S]*?<svg/);
  assert.ok(stats.indexOf('queueStatisticsFromField')<stats.indexOf('queueStatisticsFilterToggle'));
  assert.ok(stats.indexOf('queueStatisticsToField')<stats.indexOf('queueStatisticsSearch'));
  assert.ok(stats.indexOf('queueStatisticsSearch')<stats.indexOf('queueStatisticsReset'));
  assert.ok(stats.indexOf('queueStatisticsReset')<stats.indexOf('queueStatisticsGroupField'));
  assert.ok(stats.indexOf('queueStatisticsGroupField')<stats.indexOf('queueStatisticsFilterToggle'));
  assert.ok(stats.indexOf('queueStatisticsFilterClear')<stats.indexOf('queueStatisticsFilterApply'));
  assert.ok(stats.indexOf('queueStatisticsFilterApply')<stats.indexOf('queueStatisticsFilterClose'));
  assert.match(stats,/id="queueStatisticsFilterClose"/);
  assert.match(stats,/id="queueStatisticsTrendSvg"/);
  assert.match(stats,/data-trend-granularity="day"/);
  assert.match(stats,/data-trend-granularity="week"/);
  assert.match(stats,/data-trend-granularity="month"/);
  for(const field of ['supplier_type','category','dk_code','review_officer','protocol_officer'])assert.match(stats,new RegExp(`data-statistics-filter-section="${field}"`));
  assert.doesNotMatch(stats,/data-statistics-filter="status"/);
  assert.match(stylesSource,/queue-statistics-heading\{display:flex/);
  assert.match(stylesSource,/queue-statistics-controls\{display:flex/);
  assert.match(stylesSource,/queue-statistics-table--scroll\{max-height/);
  assert.match(stylesSource,/queue-statistics-kpis\{grid-template-columns:repeat\(4,minmax\(0,1fr\)\)/);
  assert.match(stylesSource,/queue-statistics-filter-panel\{position:fixed/);
  assert.match(stylesSource,/queue-statistics-dk-heading\{display:grid;grid-template-columns:minmax\(0,1fr\)/);
  assert.match(stylesSource,/queue-statistics-filter-fields\{display:grid;align-content:start;gap:8px;min-height:0;overflow:auto/);
  assert.match(themeSource,/--uo-kpi-rejected-bg:#482932/);
  assert.match(themeSource,/--uo-kpi-pending-bg:#443b26/);
  assert.match(stylesSource,/queue-statistics-table td button\.publication-kpi[^}]+color:var\(--ink\)!important/);
});

test('shared officer formatter uses first-name then uppercase-surname and preserves special values',()=>{
  assert.equal(formatOfficerName('ДМИТРО САВВА'),'Дмитро САВВА');
  assert.equal(formatOfficerName('ОЛЕНА ЄРЬОМІНА'),'Олена ЄРЬОМІНА');
  assert.equal(formatOfficerName('СВІТЛАНА НАМЯСЕНКО'),'Світлана НАМЯСЕНКО');
  assert.equal(formatOfficerName('ТЕТЯНА ФЕДЧЕНКО'),'Тетяна ФЕДЧЕНКО');
  assert.equal(formatOfficerName('НЕ ПРИЗНАЧЕНО'),'Не визначено');
  assert.equal(formatOfficerName('Не визначено'),'Не визначено');
  assert.equal(formatQueueOfficer(''),'Не визначено');
  assert.equal(formatOfficerName('MANAGER'),'MANAGER');
  assert.equal(formatQueueOfficer('ДМИТРО САВВА'),'<span>Дмитро</span><span>САВВА</span>');
});

test('history review-officer search preserves multiple selections and summarizes them',()=>{
  assert.match(indexSource,/<input id="historyReviewOfficerSearch"[^>]*placeholder="УО \(розгляд\)"[^>]*aria-label="Пошук УО розгляду за частиною ПІБ"/,'the visible label is compact while the accessible name explains the search');
  const search={value:'',setAttribute(){}},options={innerHTML:'',hidden:true},summary={textContent:'',hidden:true};
  const nodes={
    '#historyReviewOfficerSearch':search,
    '#historyReviewOfficerOptions':options,
    '#historyReviewOfficerSummary':summary,
  };
  const context=vm.createContext({
    $:selector=>nodes[selector],esc:value=>String(value),formatOfficerName,
    historyReviewOfficerNames:['ДМИТРО САВВА','ОЛЕНА ЄРЬОМІНА','ТЕТЯНА ФЕДЧЕНКО'],
    historyReviewOfficerSelection:new Set(['ДМИТРО САВВА','ТЕТЯНА ФЕДЧЕНКО']),
    historyReviewOfficerMenuOpen:true,
  });
  const render=historySource.match(/function renderHistoryReviewOfficers\(\)\{[\s\S]*?\n\}/)?.[0];
  assert.ok(render,'the test exercises the actual officer-option renderer');
  vm.runInContext(`${render};renderHistoryReviewOfficers()`,context);
  assert.equal(summary.textContent,'Вибрано: 2');
  assert.equal(summary.hidden,false,'selected officers are summarized without cluttering the empty search field');
  assert.equal(options.hidden,false,'the searchable options are open while focused');
  assert.match(options.innerHTML,/value="ДМИТРО САВВА" checked/);
  assert.match(options.innerHTML,/value="ТЕТЯНА ФЕДЧЕНКО" checked/);
  assert.doesNotMatch(options.innerHTML,/value="ОЛЕНА ЄРЬОМІНА" checked/);
  search.value='Тетяна';
  vm.runInContext('renderHistoryReviewOfficers()',context);
  assert.equal(summary.textContent,'Вибрано: 2','searching does not change the current selection');
  assert.match(options.innerHTML,/value="ТЕТЯНА ФЕДЧЕНКО" checked/);
  assert.doesNotMatch(options.innerHTML,/ДМИТРО САВВА/,'nonmatching selected officers stay selected while filtered out of view');
  search.value='';
  vm.runInContext('renderHistoryReviewOfficers()',context);
  assert.match(options.innerHTML,/value="ДМИТРО САВВА" checked/,'clearing search restores the retained selection');
});
