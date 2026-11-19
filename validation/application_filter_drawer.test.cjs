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

test('filter application, close, and shared checkbox rows retain existing interaction semantics',()=>{
  assert.match(app,/\$\('#applicationFilterApply'\)\.onclick=\(\)=>\{page=1;statsSignature='';loadRows\(\);\$\('#applicationFilters'\)\.open=false\}/);
  assert.match(app,/\$\('#applicationFilterClose'\)\.onclick=\(\)=>\{\$\('#applicationFilters'\)\.open=false\}/);
  assert.match(app,/event\.key==='Escape'&&\$\('#applicationFilters'\)\.open&&\$\('#applicationFilterPanel'\)\.contains\(document\.activeElement\)/,'Escape still closes the application drawer when focus is inside it');
  assert.match(app,/\$\('#applicationOfficerFilter'\)\.onchange=\(\)=>\{officerFilter=\$\('#applicationOfficerFilter'\)\.value;page=1;statsSignature='';loadRows\(\)\}/);
  assert.match(app,/\$\('#applicationEntityTypeFilter'\)\.onchange=\(\)=>\{queueRegistryFilters\.entity_type=\$\('#applicationEntityTypeFilter'\)\.value;page=1;statsSignature='';loadRows\(\)\}/);
  assert.match(app,/function renderDynamicFilter\([\s\S]+?includes\(query\)/,'dynamic supplier/framework/DK search remains substring based');
  assert.match(filtersCss,/\.multi-panel label\{[^}]*grid-template-columns:16px minmax\(0,1fr\)[^}]*align-items:start/);
  assert.match(filtersCss,/\.multi-panel label input\[type="checkbox"\]\{[^}]*width:15px;height:15px;[^}]*flex:none/);
  assert.match(filtersCss,/\.multi-panel label span\{min-width:0;overflow-wrap:anywhere;white-space:normal\}/);
  assert.match(filtersCss,/\.multi-panel label\{[^}]*display:grid;grid-template-columns:16px minmax\(0,1fr\)[^}]*gap:7px/,'checkboxes remain in a fixed leading column with consistent text spacing');
  assert.match(filtersCss,/\.multi-panel label:focus-within\{outline:2px solid var\(--blue\)/,'keyboard focus remains visible on a checkbox row');
});
