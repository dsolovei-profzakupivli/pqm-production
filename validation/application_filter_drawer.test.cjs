const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const html=fs.readFileSync('index.html','utf8');
const app=fs.readFileSync('app.js','utf8');
const css=fs.readFileSync('ui_final.css','utf8');
const filtersCss=fs.readFileSync('filters.css','utf8');
const popovers=fs.readFileSync('registry_popovers.js','utf8');
const accordions=fs.readFileSync('filter_panels_ui.js','utf8');

test('application registry keeps quick filters and profiles in the toolbar and moves only advanced controls into the drawer',()=>{
  const toolbarStart=html.indexOf('<section class="toolbar card applications-toolbar">');
  const toolbar=html.slice(toolbarStart,html.indexOf('<section class="table-card card">',toolbarStart));
  const panel=html.match(/<aside id="applicationFilterPanel"[\s\S]*?<\/aside>/)?.[0];
  assert.ok(toolbar&&panel,'registry toolbar and side panel are present');
  assert.match(panel,/<h3>Фільтри заявок<\/h3>/);
  for(const id of ['applicationOfficerFilter','applicationEntityTypeFilter','supplierCodeFilter','registryStatusFilter','protocolNumberFilter','protocolDecisionFilter','complianceStatusFilter','frameworkFilter','dkFilter','dateFromFilter','dateToFilter'])assert.match(panel,new RegExp(`id="${id}"`),`${id} stays in the drawer`);
  for(const id of ['searchInput','applicationCategoryFilter','statusFilter','marketplaceDecisionFilter','applicationFiltersSummary','profileSelect','saveProfileBtn','clearFiltersBtn'])assert.match(toolbar,new RegExp(`id="${id}"`),`${id} stays in the toolbar`);
  assert.ok(toolbar.indexOf('id="marketplaceDecisionFilter"')<toolbar.indexOf('id="applicationFilters"'));
  assert.ok(toolbar.indexOf('id="applicationFilters"')<toolbar.indexOf('id="profileSelect"'));
  assert.match(panel,/id="applicationFilterClear"/);
  assert.match(panel,/id="applicationFilterApply"/);
  assert.match(panel,/id="applicationFilterClose"/);
  assert.doesNotMatch(html,/<div id="applicationFilterChips"/,'no extra active-filter row is introduced');
  for(const selector of ['#applicationFilterPanel\.application-filter-panel','\.application-filter-fields\{[^}]*overflow:auto'])assert.match(css,new RegExp(selector));
  assert.ok(css.includes('html:has(#applicationFilters[open]){overflow:hidden}'),'the page behind the drawer cannot scroll');
  assert.match(popovers,/application-filter-panel/,'drawer and nested multiselects use the shared popover manager');
  assert.match(accordions,/prepareApplicationFilters\(\)/,'registry sections are transformed into compact accordions');
  assert.match(accordions,/dateFromFilter:'application_date',dateToFilter:'application_date'/,'the from/to dates remain grouped as one filter section');
  assert.match(accordions,/button\?\.setAttribute\('aria-expanded',String\(active\)\)/,'opening one registry section collapses its siblings without clearing controls');
  assert.match(accordions,/prepareQueueStatisticsFilters\(\)/,'Work UO uses the shared single-open accordion interaction');
  assert.match(accordions,/prepareEdrFilters\(\)/,'EDR uses the same accordion interaction');
  assert.match(accordions,/if\(source\)source\.classList\.add\('filter-field-caption'\)/,'duplicate registry field captions are visually suppressed while labels remain in the accessibility tree');
  assert.match(accordions,/caption\.textContent\.trim\(\)==='Виберіть тип'\)caption\.classList\.add\('filter-field-caption'/,'the redundant EDR type prompt stays available to assistive technology');
  assert.match(css,/\.filter-field-caption\{position:absolute!important;width:1px!important;height:1px!important/,'redundant captions use a screen-reader-only treatment rather than display:none');
  assert.match(css,/#edrMonitoringFilterPanel \.edr-monitoring-filter-fields\{gap:7px\}/,'EDR uses the application registry section gap');
  assert.match(filtersCss,/\.multi-filter > summary::after\s*\{[^}]*content: "›";/,'collapsed checkbox/multiselect dropdowns use the right-pointing icon');
  assert.match(filtersCss,/\.multi-filter\[open\] > summary::after\s*\{\s*content: "⌃";/,'expanded checkbox/multiselect dropdowns use the upward icon');
});

test('advanced clear resets only drawer state, preserving quick filters, search, profile, and external registry scope',()=>{
  const source=app.match(/function clearApplicationAdvancedFilters\(\)\{[\s\S]*?\n\}/)?.[0];
  assert.ok(source,'advanced drawer has an isolated clear action');
  const initial={protocolNumberFilter:'P-1',dateFromFilter:'2026-01-01',dateToFilter:'2026-01-31',protocolDecisionFilter:'admit',complianceStatusFilter:'approved',applicationEntityTypeFilter:'individual_entrepreneur'};
  const nodes=Object.fromEntries(Object.entries(initial).map(([id,value])=>[id,{value}]));
  const registryCheckboxes=[{checked:true},{checked:true}];
  const calls=[];
  const context=vm.createContext({
    $:selector=>nodes[selector.slice(1)]||{value:''},
    $$:selector=>selector==='#registryStatusFilter input[type="checkbox"]'?registryCheckboxes:[],
    filterSelections:{registry:new Set(['Активний']),supplier:new Set(['123']),framework:new Set(['f1']),dk:new Set(['45000000-7'])},
    filterDrafts:{registry:new Set(['Активний','Неактивний']),supplier:new Set(['123']),framework:new Set(['f1']),dk:new Set(['45000000-7'])},
    queueRegistryFilters:{entity_type:'individual_entrepreneur',protocol_card_officer:'Олена'},
    frameworkOptions:[{id:'f1',pretty_id:'UA-F-1',title:'Тест',applications_count:2,dk_code:'45000000-7'}],
    updateMultiSummary:(...args)=>calls.push(['summary',...args]),
    renderDynamicFilter:(...args)=>calls.push(['render',args[0]]),
    loadSupplierOptions:()=>calls.push(['supplierOptions']),
    loadRows:()=>calls.push(['loadRows']),
    page:4,statsSignature:'old'
  });
  vm.runInContext(`${source};clearApplicationAdvancedFilters()`,context);
  for(const id of Object.keys(initial))assert.equal(nodes[id].value,'',`${id} is cleared`);
  for(const value of Object.values(context.filterSelections))assert.equal(value.size,0,'all advanced multiselects are cleared');
  assert.deepEqual(registryCheckboxes.map(input=>input.checked),[false,false]);
  assert.equal(context.queueRegistryFilters.entity_type,undefined);
  assert.equal(context.queueRegistryFilters.protocol_card_officer,'Олена','external scope remains intact');
  assert.equal(context.page,1);assert.equal(context.statsSignature,'');
  assert.ok(calls.some(call=>call[0]==='supplierOptions')&&calls.some(call=>call[0]==='loadRows'));
});

test('multiselect drafts apply only from their reserved check controls and stay unapplied on close',()=>{
  assert.match(app,/\$\('#applicationFilterApply'\)\.onclick=\(\)=>\{const keys=\['supplier','registry','framework','dk'\],changed=keys\.some/);
  assert.match(app,/if\(changed\)\{page=1;statsSignature='';loadRows\(\)\}/,'applying an unchanged draft does not issue a duplicate request');
  assert.match(app,/function applyApplicationFilterDimension\(name\)[\s\S]*?filterSelections\[key\]\.clear\(\);filterDrafts\[key\]\.forEach/);
  assert.doesNotMatch(app,/applyApplicationFilterDimension\(apply\.dataset\.applicationFilterApply\);const section=apply\.closest\('.application-filter-section'\);section\?\.querySelector\('\.filter-accordion-toggle'\)\?\.click\(\)/,'applying a filter does not programmatically toggle the accordion again');
  assert.match(accordions,/if\(event\.target\.closest\('\.filter-row-actions'\)\)return/,'check and x action areas are excluded from accordion toggling');
  assert.match(accordions,/event\.target\.closest\('\.filter-section-heading,\.edr-monitoring-filter-heading,\.queue-statistics-filter-section-heading'\)/,'unused space in each heading toggles its own section');
  assert.match(app,/function resetApplicationFilterDimension\(name\)[\s\S]*?filterSelections\[key\]\.clear\(\);filterDrafts\[key\]\.clear\(\)/);
  assert.match(app,/\[data-application-filter-apply\]/);
  assert.match(app,/\[data-application-filter-reset\]/);
  assert.match(app,/document\.addEventListener\('click',event=>\{const drawer=\$\('#applicationFilters'\)/,'clicking outside closes the drawer without clearing its draft state');
  assert.match(app,/\$\('#applicationFilterClose'\)\.onclick=\(\)=>\{\$\('#applicationFilters'\)\.open=false\}/);
  assert.match(app,/event\.key==='Escape'&&\$\('#applicationFilters'\)\.open&&\$\('#applicationFilterPanel'\)\.contains\(document\.activeElement\)/,'Escape still closes the application drawer when focus is inside it');
  assert.match(app,/\$\('#applicationOfficerFilter'\)\.onchange=function\(\)\{officerFilter=this\.value;page=1;statsSignature='';loadRows\(\);collapseApplicationFilterControl\(this\)\}/);
  assert.match(app,/\$\('#applicationEntityTypeFilter'\)\.onchange=function\(\)\{queueRegistryFilters\.entity_type=this\.value;page=1;statsSignature='';loadRows\(\);collapseApplicationFilterControl\(this\)\}/);
  assert.match(app,/function renderDynamicFilter\([\s\S]+?includes\(query\)/,'dynamic supplier/framework/DK search remains substring based');
  assert.match(filtersCss,/\.multi-panel label\{[^}]*grid-template-columns:16px minmax\(0,1fr\)[^}]*align-items:start/);
  assert.match(filtersCss,/\.multi-panel label input\[type="checkbox"\]\{[^}]*width:15px;height:15px;[^}]*flex:none/);
  assert.match(filtersCss,/\.multi-panel label span\{min-width:0;overflow-wrap:anywhere;white-space:normal\}/);
  assert.match(filtersCss,/\.multi-panel label\{[^}]*display:grid;grid-template-columns:16px minmax\(0,1fr\)[^}]*gap:7px/,'checkboxes remain in a fixed leading column with consistent text spacing');
  assert.match(filtersCss,/\.multi-panel label:focus-within\{outline:2px solid var\(--blue\)/,'keyboard focus remains visible on a checkbox row');
  assert.match(accordions,/data-application-filter-apply/,'application multi-filters expose a per-dimension Apply check');
  assert.match(css,/\.filter-row-actions>button:hover\{background:#0000000c/,'row action backgrounds appear only on hover');
  assert.match(css,/\.filter-row-actions>button:focus-visible\{outline:2px solid/,'row actions keep visible keyboard focus');
});

test('registry mono filters apply on change and collapse only their own section',()=>{
  const lines=app.split(/\r?\n/);
  const handlerSource=[
    lines.find(line=>line.startsWith('function collapseApplicationFilterControl')),
    lines.find(line=>line.startsWith("$('#dateFromFilter').onchange=")),
    lines.find(line=>line.startsWith("$('#protocolNumberFilter').onchange=")),
    lines.find(line=>line.startsWith("$('#protocolDecisionFilter').onchange=")),
    lines.find(line=>line.startsWith("$('#applicationOfficerFilter').onchange=")),
    lines.find(line=>line.startsWith("$('#applicationEntityTypeFilter').onchange="))
  ].join('\n');
  assert.ok(handlerSource.includes("window.PqmFilterAccordion?.collapseControl(control)"));
  const ids=['dateFromFilter','dateToFilter','protocolNumberFilter','protocolDecisionFilter','complianceStatusFilter','applicationOfficerFilter','applicationEntityTypeFilter'];
  const controls=Object.fromEntries(ids.map(id=>[id,{id,value:'',onchange:null}]));
  const collapsed=[],loads=[];
  const context=vm.createContext({
    window:{PqmFilterAccordion:{collapseControl(control){collapsed.push(control.id)}}},
    $(selector){return controls[selector.slice(1)]},
    $$(){return[]},filterSelections:{supplier:new Set(),registry:new Set(),framework:new Set(),dk:new Set()},filterDrafts:{supplier:new Set(),registry:new Set(),framework:new Set(),dk:new Set()},
    page:1,statsSignature:'old',officerFilter:'',queueRegistryFilters:{},loadRows(){loads.push('load')},updateApplicationFilterStyles(){}
  });
  vm.runInContext(handlerSource,context);

  controls.applicationOfficerFilter.value='Олена';controls.applicationOfficerFilter.onchange.call(controls.applicationOfficerFilter);
  assert.equal(context.officerFilter,'Олена');
  assert.deepEqual(collapsed,['applicationOfficerFilter']);
  assert.equal(loads.length,1,'selection refreshes the registry immediately');

  controls.applicationEntityTypeFilter.value='individual_entrepreneur';controls.applicationEntityTypeFilter.onchange.call(controls.applicationEntityTypeFilter);
  assert.equal(context.queueRegistryFilters.entity_type,'individual_entrepreneur');
  assert.deepEqual(collapsed,['applicationOfficerFilter','applicationEntityTypeFilter'],'another filter remains untouched');
  assert.equal(loads.length,2);

  for(const id of ['protocolDecisionFilter','complianceStatusFilter']){
    controls[id].value=id==='protocolDecisionFilter'?'admit':'approved';
    controls[id].onchange.call(controls[id]);
    assert.equal(collapsed.at(-1),id,`${id} applies and collapses after selection`);
  }

  const beforeDate=collapsed.length;controls.dateFromFilter.value='2026-01-01';controls.dateFromFilter.onchange.call(controls.dateFromFilter);
  assert.equal(collapsed.length,beforeDate,'choosing only the first date boundary leaves the section open');
  controls.dateToFilter.value='2026-01-31';controls.dateToFilter.onchange.call(controls.dateToFilter);
  assert.equal(collapsed.at(-1),'dateToFilter','the completed date range collapses only after its second boundary');

  controls.protocolNumberFilter.value='P-42';controls.protocolNumberFilter.onchange.call(controls.protocolNumberFilter);
  assert.equal(collapsed.at(-1),'protocolNumberFilter','text filter collapses on change, not on each keystroke');

  const resetSource=app.match(/function resetApplicationFilterDimension\(name\)\{[\s\S]*?\n\}/)?.[0];
  assert.ok(resetSource,'the independent per-filter reset handler remains present');
  vm.runInContext(resetSource,context);
  const collapseCount=collapsed.length;controls.applicationEntityTypeFilter.value='individual_entrepreneur';context.queueRegistryFilters.entity_type='individual_entrepreneur';
  context.resetApplicationFilterDimension('entity_type');
  assert.equal(controls.applicationEntityTypeFilter.value,'');
  assert.equal(context.officerFilter,'Олена','clearing one dimension preserves the other mono filter');
  assert.equal(collapsed.length,collapseCount,'x clears the filter without opening or toggling its accordion');
});

test('shared accordion collapse helper closes only the section containing the selected control',()=>{
  const sections=[];
  const document={querySelector(){return null},querySelectorAll(){return []}};
  const window={};
  const context=vm.createContext({document,window});
  vm.runInContext(accordions,context);
  function section(){
    const toggle={attributes:{'aria-expanded':'true'},setAttribute(name,value){this.attributes[name]=value}};
    const content={hidden:false};
    const item={querySelector(selector){return selector.includes('filter-accordion-toggle')||selector.includes('queue-statistics-section-toggle')?toggle:content}};
    const control={closest(){return item}};
    sections.push({item,toggle,content,control});
    return sections.at(-1);
  }
  const selected=section(),sibling=section();
  assert.equal(window.PqmFilterAccordion.collapseControl(selected.control),true);
  assert.equal(selected.toggle.attributes['aria-expanded'],'false');
  assert.equal(selected.content.hidden,true);
  assert.equal(sibling.toggle.attributes['aria-expanded'],'true','other accordion rows are not toggled');
  assert.equal(sibling.content.hidden,false);
});
