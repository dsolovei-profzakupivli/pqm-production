const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const html=fs.readFileSync('index.html','utf8');
const app=fs.readFileSync('app.js','utf8');
const css=fs.readFileSync('ui_final.css','utf8');
const accordions=fs.readFileSync('filter_panels_ui.js','utf8');

test('EDR drawer contains every current filter, per-filter reset, and top actions without a chips row',()=>{
  const keys=['dk_code','entity_type','prozorro_status','edr_status','edr_names','edr_full_name','edr_short_name','freshness','verification_from','verification_to','application_from','application_to'];
  const panel=html.match(/<aside id="edrMonitoringFilterPanel"[\s\S]*?<\/aside>/)?.[0];
  assert.ok(panel,'EDR filters use a dedicated drawer');
  assert.match(html,/<summary id="edrMonitoringFilterSummary"[^>]*>Фільтри<\/summary>/);
  assert.ok(panel.indexOf('id="edrMonitoringReset"')<panel.indexOf('id="edrMonitoringApply"')&&panel.indexOf('id="edrMonitoringApply"')<panel.indexOf('id="edrMonitoringClose"'),'clear, apply and close stay together in the drawer header');
  for(const key of keys){
    const section=panel.match(new RegExp(`<section[^>]*data-edr-filter-section="${key}"[\\s\\S]*?<\\/section>`))?.[0];
    assert.ok(section,`filter section ${key} remains available`);
    assert.match(section,/data-edr-filter-current/);
    assert.match(section,new RegExp(`data-edr-filter-clear="${key}"`));
  }
  assert.match(panel,/id="edrMonitoringDk"[^>]*placeholder="Код або частина коду"/);
  assert.match(accordions,/prepareEdrFilters\(\)/,'EDR sections use the common collapsed accordion');
  assert.match(accordions,/buildToggle\(title,'data-edr-filter-count'\)/,'each EDR section has a numeric active-value badge');
  assert.match(accordions,/data-edr-filter-apply/,'EDR multi-select sections have an independent apply check');
  assert.match(accordions,/className='filter-row-actions'/,'EDR reserves fixed positions for per-filter actions');
  assert.match(accordions,/if\(event\.target\.closest\('\.filter-row-actions'\)\)return/,'EDR check and x buttons cannot toggle their accordion row');
  assert.match(css,/\.edr-monitoring-filter-heading \.filter-accordion-toggle/,'EDR filter labels use the same row toggle layout');
  assert.match(css,/\.filter-panel-header-actions button\{[^}]*width:36px;height:36px/,'top drawer actions share identical icon button dimensions');
  assert.match(html,/<div id="edrMonitoringChips"[^>]*hidden><\/div>/,'legacy element remains hidden for compatibility');
  assert.match(css,/#edrMonitoringChips\.edr-monitoring-chips\{display:none!important\}/,'no separate active-filter chip row is displayed');
  assert.match(css,/html:has\(#edrMonitoringAdvanced\[open\]\)\{overflow:hidden\}/,'opening the panel locks page scrolling underneath it');
  assert.match(css,/\.edr-monitoring-filter-fields\{[^}]*overflow:auto[^}]*scrollbar-gutter:stable[^}]*scrollbar-width:thin[^}]*scrollbar-color:/,'filter content scrolls internally with a visible, theme-aware scrollbar');
  assert.match(css,/\.edr-monitoring-filter-fields::-webkit-scrollbar-thumb\{[^}]*background:#5d9bd8/,'light theme has a colored scrollbar thumb');
  assert.match(css,/html\[data-theme="dark"\] #edrMonitoringFilterPanel \.edr-monitoring-filter-fields::-webkit-scrollbar-thumb\{[^}]*background:#6488B5/,'dark theme has a contrasting scrollbar thumb');
  assert.match(app,/#edrMonitoringApply'\)\.onclick=\(\)=>\{const changed=Object\.keys\(edrMonitoringStatusSelections\)\.some/);
  assert.match(app,/if\(changed\)\{saveEdrMonitoringFilters\(\);edrMonitoringPage=1;updateEdrMonitoringFilters\(\);loadEdrMonitoring\(\)\}/,'global apply avoids a request if no multiselect draft changed');
  assert.ok(app.includes('const section=document.querySelector(`[data-edr-filter-section="${key}"]`)') ,'applying one dimension collapses its own accordion row');
  assert.match(app,/\[data-edr-filter-clear\].*onclick=\(\)=>clearEdrMonitoringFilter\(button\.dataset\.edrFilterClear\)/);
});

test('EDR active filter state counts each selected dimension once and keeps multi-select dimensions distinct',()=>{
  const definition=app.match(/function edrMonitoringFilterIsActive\(key,params\)\{[^}]+\}/)?.[0];
  assert.ok(definition,'drawer state uses a shared active-filter predicate');
  const context=vm.createContext({edrMonitoringStatusSelections:{prozorro_status:new Set(['Активний','Неактивний']),edr_status:new Set()}});
  vm.runInContext(`${definition};globalThis.active=edrMonitoringFilterIsActive`,context);
  assert.equal(context.active('prozorro_status',{}),true,'multiple selected statuses still count as one active filter');
  assert.equal(context.active('edr_status',{}),false,'empty status selection is neutral');
  assert.equal(context.active('dk_code',{dk_code:'45'}),true);
  assert.equal(context.active('dk_code',{dk_code:''}),false);
});

test('EDR multi-select draft does not affect request until its own apply check is used',()=>{
  const params=app.slice(app.indexOf('function edrMonitoringParams()'),app.indexOf('const edrMonitoringStorageKey='));
  const apply=app.match(/function applyEdrMonitoringFilter\(key\)\{[^\n]+/)?.[0];
  const sets={prozorro_status:new Set(),edr_status:new Set()},drafts={prozorro_status:new Set(['Активний']),edr_status:new Set()};
  const controls=Object.fromEntries(['edrMonitoringSearch','edrMonitoringDk','edrMonitoringType','edrMonitoringNames','edrMonitoringFullName','edrMonitoringShortName','edrMonitoringFreshness','edrMonitoringVerifiedFrom','edrMonitoringVerifiedTo','edrMonitoringApplicationFrom','edrMonitoringApplicationTo'].map(id=>['#'+id,{value:''}]));
  const section={querySelector:selector=>selector==='.filter-accordion-toggle'?{setAttribute(){}}:{hidden:false}};
  const context=vm.createContext({edrMonitoringStatusSelections:sets,edrMonitoringStatusDrafts:drafts,edrMonitoringSort:'freshness',edrMonitoringDirection:'asc',edrMonitoringPage:1,saveEdrMonitoringFilters(){},updateEdrMonitoringFilters(){},loadEdrMonitoring(){},document:{querySelector:()=>section}});
  context.$=selector=>selector==='#edrMonitoringProzorro'?{open:true}:controls[selector];
  vm.runInContext(params+';'+apply+';globalThis.params=edrMonitoringParams;globalThis.apply=applyEdrMonitoringFilter',context);
  assert.equal(context.params().prozorro_status,'','draft does not leak into the API request');
  context.apply('prozorro_status');
  assert.equal(context.params().prozorro_status,'Активний','the per-filter check applies only that dimension');
  assert.equal(context.params().edr_status,'','the other status dimension remains unchanged');
});

test('EDR mono filters apply on completion, collapse only their own section, and remain independently clearable',()=>{
  const start=app.indexOf('function scheduleEdrMonitoringSearch()');
  const end=app.indexOf("$('#edrMonitoringKpis')",start);
  const handlers=app.slice(start,end);
  assert.ok(start>=0&&end>start,'the EDR mono filter handlers are present');
  const ids=['edrMonitoringSearch','edrMonitoringDk','edrMonitoringType','edrMonitoringNames','edrMonitoringFullName','edrMonitoringShortName','edrMonitoringFreshness','edrMonitoringVerifiedFrom','edrMonitoringVerifiedTo','edrMonitoringApplicationFrom','edrMonitoringApplicationTo'];
  const controls=Object.fromEntries(ids.map(id=>[id,{id,value:'',oninput:null,onchange:null}]));
  const calls={save:0,update:0,load:0,collapse:[]};
  let scheduled=null;
  const context=vm.createContext({
    edrMonitoringPage:1,edrMonitoringPages:1,edrMonitoringTimer:null,edrMonitoringTimerPending:false,
    edrMonitoringStatusSelections:{prozorro_status:new Set(),edr_status:new Set()},
    edrMonitoringStatusDrafts:{prozorro_status:new Set(),edr_status:new Set()},
    window:{PqmFilterAccordion:{collapseControl(control){calls.collapse.push(control.id)}}},
    $(selector){return controls[selector.slice(1)]},
    saveEdrMonitoringFilters(){calls.save++},updateEdrMonitoringFilters(){calls.update++},loadEdrMonitoring(){calls.load++},
    bindEdrMonitoringStatusMulti(){},
    clearTimeout(){},setTimeout(callback,delay){assert.equal(delay,250);scheduled=callback;return 1;}
  });
  vm.runInContext(handlers,context);

  controls.edrMonitoringType.value='individual_entrepreneur';controls.edrMonitoringType.onchange.call(controls.edrMonitoringType);
  assert.equal(calls.load,1,'single select applies immediately');
  assert.deepEqual(calls.collapse,['edrMonitoringType'],'only the changed section collapses');
  for(const [id,value] of [['edrMonitoringNames','missing_any'],['edrMonitoringFullName','missing'],['edrMonitoringShortName','filled'],['edrMonitoringFreshness','gt30']]){
    const before=calls.load;controls[id].value=value;controls[id].onchange.call(controls[id]);
    assert.equal(calls.load,before+1,`${id} applies immediately`);
    assert.equal(calls.collapse.at(-1),id,`${id} collapses its own section after selection`);
  }

  const beforeVerifiedDates=calls.collapse.length;
  controls.edrMonitoringVerifiedFrom.value='2026-01-01';controls.edrMonitoringVerifiedFrom.onchange.call(controls.edrMonitoringVerifiedFrom);
  assert.equal(calls.collapse.length,beforeVerifiedDates,'the first date boundary does not collapse the accordion');
  controls.edrMonitoringVerifiedTo.value='2026-01-31';controls.edrMonitoringVerifiedTo.onchange.call(controls.edrMonitoringVerifiedTo);
  assert.equal(calls.collapse.at(-1),'edrMonitoringVerifiedTo','the date section collapses only when both boundaries are present');

  const beforeApplicationDates=calls.collapse.length;
  controls.edrMonitoringApplicationFrom.value='2026-02-01';controls.edrMonitoringApplicationFrom.onchange.call(controls.edrMonitoringApplicationFrom);
  assert.equal(calls.collapse.length,beforeApplicationDates,'the first application-date boundary leaves its section available');
  controls.edrMonitoringApplicationTo.value='2026-02-28';controls.edrMonitoringApplicationTo.onchange.call(controls.edrMonitoringApplicationTo);
  assert.equal(calls.collapse.at(-1),'edrMonitoringApplicationTo','the application-date range collapses after its second boundary');

  const beforeDk=calls.load,beforeDkCollapse=calls.collapse.at(-1);controls.edrMonitoringDk.value='45000000';controls.edrMonitoringDk.oninput();
  assert.equal(calls.collapse.at(-1),beforeDkCollapse,'typing and debounce do not collapse the DK section');
  assert.equal(calls.load,beforeDk,'DK search remains debounced before completion');
  controls.edrMonitoringDk.onchange();
  assert.equal(calls.load,beforeDk+1,'completion flushes a pending DK request exactly once');
  assert.equal(calls.collapse.at(-1),'edrMonitoringDk');

  controls.edrMonitoringDk.oninput();scheduled();
  const afterDebounce=calls.load;
  controls.edrMonitoringDk.onchange();
  assert.equal(calls.load,afterDebounce,'blur after an elapsed debounce does not issue a duplicate request');
  assert.equal(calls.collapse.at(-1),'edrMonitoringDk');

  const clear=app.match(/function clearEdrMonitoringFilter\(key,statusValue=''\)\{[^\n]+/)?.[0];
  assert.ok(clear,'per-filter clear remains available');
  vm.runInContext(clear+';globalThis.clearMono=clearEdrMonitoringFilter',context);
  controls.edrMonitoringType.value='individual_entrepreneur';
  const collapseCount=calls.collapse.length;
  context.clearMono('entity_type');
  assert.equal(controls.edrMonitoringType.value,'');
  assert.equal(calls.collapse.length,collapseCount,'x clears the field without opening or toggling an accordion');
  assert.ok(calls.save>0&&calls.update>0,'selection and clear refresh the active filter presentation/count');
});
