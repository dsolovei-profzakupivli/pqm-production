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
  assert.match(css,/\.edr-monitoring-filter-heading \.filter-accordion-toggle/,'EDR filter labels use the same row toggle layout');
  assert.match(css,/\.filter-panel-header-actions button\{[^}]*width:36px;height:36px/,'top drawer actions share identical icon button dimensions');
  assert.match(html,/<div id="edrMonitoringChips"[^>]*hidden><\/div>/,'legacy element remains hidden for compatibility');
  assert.match(css,/#edrMonitoringChips\.edr-monitoring-chips\{display:none!important\}/,'no separate active-filter chip row is displayed');
  assert.match(css,/html:has\(#edrMonitoringAdvanced\[open\]\)\{overflow:hidden\}/,'opening the panel locks page scrolling underneath it');
  assert.match(css,/\.edr-monitoring-filter-fields\{[^}]*overflow:auto[^}]*scrollbar-gutter:stable[^}]*scrollbar-width:thin[^}]*scrollbar-color:/,'filter content scrolls internally with a visible, theme-aware scrollbar');
  assert.match(css,/\.edr-monitoring-filter-fields::-webkit-scrollbar-thumb\{[^}]*background:#5d9bd8/,'light theme has a colored scrollbar thumb');
  assert.match(css,/html\[data-theme="dark"\] #edrMonitoringFilterPanel \.edr-monitoring-filter-fields::-webkit-scrollbar-thumb\{[^}]*background:#6488B5/,'dark theme has a contrasting scrollbar thumb');
  assert.match(app,/#edrMonitoringApply'\)\.onclick=\(\)=>\{saveEdrMonitoringFilters\(\);edrMonitoringPage=1;loadEdrMonitoring\(\);\$\('#edrMonitoringAdvanced'\)\.open=false\}/);
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
