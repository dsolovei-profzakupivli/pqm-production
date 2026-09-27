const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const app=fs.readFileSync('app.js','utf8');
const paramsCode=app.slice(app.indexOf('function edrMonitoringParams()'),app.indexOf('const edrMonitoringStorageKey='));
const filterCode=app.slice(app.indexOf("const edrMonitoringStorageKey="),app.indexOf('\nrestoreEdrMonitoringFilters();'));

function filterSession(saved){
  const controls=Object.fromEntries(['edrMonitoringSearch','edrMonitoringDk','edrMonitoringType','edrMonitoringNames','edrMonitoringFullName','edrMonitoringShortName','edrMonitoringFreshness','edrMonitoringVerifiedFrom','edrMonitoringVerifiedTo','edrMonitoringApplicationFrom','edrMonitoringApplicationTo'].map(id=>['#'+id,{value:''}]));
  const storage=new Map(saved||[]);
  const context=vm.createContext({Set,JSON,Object,localStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},$:(selector)=>controls[selector],edrMonitoringStatusSelections:{prozorro_status:new Set(),edr_status:new Set()},edrMonitoringSort:'freshness',edrMonitoringDirection:'asc',edrMonitoringPage:1});
  vm.runInContext(paramsCode+filterCode,context);
  return {context,controls,storage,run:code=>vm.runInContext(code,context)};
}

for(const scenario of [
  {name:'ФОП + припинено',type:'individual_entrepreneur',edr:'Припинено',prozorro:'',missing:''},
  {name:'ЮО + активний + бракує назви',type:'legal_entity',edr:'',prozorro:'Активний',missing:'missing_any'}
])test(`EDR filters survive F5: ${scenario.name}`,()=>{
  const first=filterSession();
  first.controls['#edrMonitoringType'].value=scenario.type;
  first.controls['#edrMonitoringNames'].value=scenario.missing;
  first.controls['#edrMonitoringSearch'].value='46130719';
  if(scenario.edr)first.context.edrMonitoringStatusSelections.edr_status.add(scenario.edr);
  if(scenario.prozorro)first.context.edrMonitoringStatusSelections.prozorro_status.add(scenario.prozorro);
  first.run('saveEdrMonitoringFilters()');
  const saved=first.storage.get('pqm.edrMonitoringFilters.v1');
  assert.ok(saved&&!saved.includes('edrMonitoringSelected'));
  const second=filterSession(first.storage);
  second.run('restoreEdrMonitoringFilters()');
  assert.equal(second.controls['#edrMonitoringType'].value,scenario.type);
  assert.equal(second.controls['#edrMonitoringNames'].value,scenario.missing);
  assert.equal(second.controls['#edrMonitoringSearch'].value,'46130719');
  assert.equal(second.context.edrMonitoringStatusSelections.edr_status.has(scenario.edr),Boolean(scenario.edr));
  assert.equal(second.context.edrMonitoringStatusSelections.prozorro_status.has(scenario.prozorro),Boolean(scenario.prozorro));
  const params=second.run('edrMonitoringParams()');
  assert.equal(params.entity_type,scenario.type);
  assert.equal(params.edr_status,scenario.edr);
  assert.equal(params.prozorro_status,scenario.prozorro);
  assert.equal(params.edr_names,scenario.missing);
});

test('termination details show structured date and number only once',()=>{
  const start=app.indexOf('function formatEdrTerminationDetails('),end=app.indexOf('\nfunction openGoogleNote(',start);
  const context=vm.createContext({});vm.runInContext(app.slice(start,end),context);
  const value=context.formatEdrTerminationDetails({termination_details:'ДР припинення ФОП за її рішенням Запис № 2000730060002034912 від 07.09.2026',termination_record_date:'2026-09-07',termination_record_number:'2000730060002034912'});
  assert.equal(value,'ДР припинення ФОП за її рішенням, Запис № 2000730060002034912 від 07.09.2026');
});

test('navbar and supplier-card presentation stay scoped to shared UI',()=>{
  const nav=fs.readFileSync('nav_icons.js','utf8');
  const css=fs.readFileSync('styles.css','utf8');
  assert.match(nav,/frameworksTarget:'<span aria-hidden="true">🎯<\/span>'/);
  assert.match(nav,/edrSearch:'<span aria-hidden="true">🔎<\/span>'/);
  assert.match(nav,/administration:'<span aria-hidden="true">⚙️<\/span>'/);
  assert.match(css,/#environmentBanner\{[^}]*background:#dbeeff/);
  assert.match(css,/\.supplier-code-action-cell \.supplier-card-action\{position:absolute;right:8px;top:50%/);
  assert.match(app,/nameAction\.replaceWith\(name\)/);
  assert.match(app,/metadata\.append\(actions\)/);
  assert.match(app,/compact\.textContent='↗ Google ЄДР'/);
  assert.doesNotMatch(app,/source\.replaceChildren\(link\)/);
});
