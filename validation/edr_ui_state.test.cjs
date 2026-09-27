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
  assert.match(app,/link\.textContent='↗ Google ЄДР'/);
  assert.doesNotMatch(app,/source\.replaceChildren\(link\)/);
});

test('one exact-code Google action works for PROD/SANDBOX, ЮО/ФОП, modal/floating',async()=>{
  const start=app.indexOf('function decorateSupplierEdrCard('),end=app.indexOf('\nfunction formatLegacyCardDates(',start);
  for(const environment of ['production','sandbox'])for(const [code,tab] of [['46130719','ЮО'],['1234567890','ФОП']])for(const mode of ['modal','floating']){
    const rows=['Статус у Prozorro','Статус у реєстрі (ЄДР)','Актуальність ЄДР','Дата перевірки','Синхронізовано з Google Sheets','Джерело snapshot'].map(label=>({label,dt:{textContent:label},dd:{textContent:'',isConnected:true},querySelector(selector){return selector==='dt'?this.dt:this.dd}}));
    const section={querySelectorAll:()=>rows,querySelector(selector){if(selector==='h3')return{after(){}};if(selector==='.supplier-profile-grid')return{after(){}};return null}};
    const body={dataset:{detailWindow:mode},querySelector(selector){return selector==='.supplier-profile-edr'?section:{}}};
    const created=[],requests=[];
    const context=vm.createContext({document:{documentElement:{dataset:{pqmEnvironment:environment}},createElement:()=>{const element={children:[],append(child){this.children.push(child)}};created.push(element);return element}},$:(selector)=>selector==='#supplierProfileSubtitle'?{textContent:`ЄДРПОУ / РНОКПП: ${code}`}:null,compactSupplierNote(){},role:()=> 'admin',displayEdrStatus:value=>value,request:url=>{requests.push(url);return Promise.resolve({source_tab:tab})},API:'/api',encodeURIComponent});
    vm.runInContext(app.slice(start,end),context);
    context.decorateSupplierEdrCard(body,code,{edr_status:'Зареєстровано'},{note:''});
    await Promise.resolve();
    const expected=`/api/${environment==='sandbox'?'sandbox/supplier-google-row':'supplier-google-row'}/${code}`;
    assert.deepEqual(requests,[expected]);
    const actions=created.find(element=>element.className==='supplier-edr-actions');
    const googleLinks=actions.children.filter(child=>child.textContent==='↗ Google ЄДР');
    assert.equal(googleLinks.length,1);
    assert.equal(googleLinks[0].href,`${expected}?open=1`);
    assert.equal(rows.at(-1).dd.textContent,tab);
    assert.ok(created.find(element=>element.className==='supplier-edr-metadata').children.includes(actions));
  }
});
