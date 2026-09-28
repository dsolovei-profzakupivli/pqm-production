const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const app=fs.readFileSync('app.js','utf8');
const navigation=fs.readFileSync('navigation.js','utf8');
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

test('shared topbar keeps the existing Back action separate from PQM and preserves its history handler',()=>{
  const html=fs.readFileSync('index.html','utf8');
  const css=fs.readFileSync('styles.css','utf8');
  assert.match(html,/<header class="topbar">[\s\S]*?<div class="brand">[\s\S]*?id="environmentBanner"[^>]*>PQM<\/em>/);
  assert.match(navigation,/button\.textContent='← Назад';button\.id='pqmBack'/);
  assert.match(navigation,/document\.querySelector\('header\.topbar'\);header\?\.insertBefore\(button,header\.querySelector\('#mainNav'\)\)/);
  assert.match(navigation,/dialogButton=button\.cloneNode\(true\);dialogButton\.id='pqmDialogBack'/);
  assert.match(navigation,/button\.hidden=!current\?\.previous/);
  assert.match(navigation,/dialogButton\.hidden=!current\?\.previous\|\|dialog\.dataset\.detailWindow==='floating'/);
  assert.match(navigation,/const back=\(\)=>\{if\(current\?\.previous&&!restoring\)\{snapshot\(\);history\.back\(\)\}\}/);
  assert.match(navigation,/button\.onclick=dialogButton\.onclick=back;window\.pqmNavigationBack=back/);
  assert.match(css,/\.topbar #pqmBack:not\(\[hidden\]\)\{[^}]*display:inline-flex;[^}]*white-space:nowrap/);
  for(const module of ['applications','suppliers','edrMonitoring','history','requests','workQueue'])
    assert.ok(app.includes(`'${module}'`),`${module} remains a shared PQM module`);
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
  const html=fs.readFileSync('index.html','utf8');
  const rule=selector=>[...css.matchAll(new RegExp(selector+'\\{([^}]*)\\}','g'))].at(-1)?.[1]||'';
  assert.match(nav,/frameworksTarget:'<span aria-hidden="true">🎯<\/span>'/);
  assert.match(nav,/edrSearch:'<span aria-hidden="true">🔎<\/span>'/);
  assert.match(nav,/administration:'<span aria-hidden="true">⚙️<\/span>'/);
  assert.match(html,/<em id="environmentBanner"[^>]*>PQM<\/em>/);
  assert.ok(Number(rule('\\.topbar #environmentBanner').match(/font-size:(\d+)px/)?.[1])>=30);
  assert.ok(Number(rule('\\.topbar #environmentBanner').match(/font-weight:(\d+)/)?.[1])>=700);
  assert.match(rule('\\.topbar #environmentBanner'),/background:#[\da-f]+/);
  const brandRule=[...css.matchAll(/\.topbar \.brand\{([^}]*)\}/g)].map(match=>match[1]).find(body=>body.includes('gap:'))||'';
  assert.ok(Number(brandRule.match(/gap:(\d+)px/)?.[1])>=20);
  assert.ok(Number(brandRule.match(/margin-right:(\d+)px/)?.[1])>=18);
  assert.match(rule('\\.supplier-code-line'),/display:grid;grid-template-columns:minmax\(0,1fr\) auto;align-items:center/);
  assert.match(rule('\\.supplier-code-action-cell \\.supplier-card-action'),/justify-self:end;align-self:center/);
  assert.match(app,/installSupplierCodeAction\(cell,\(\)=>openSupplierProfile\(row\.dataset\.supplierCode\)\)/);
  assert.match(app,/installSupplierCodeAction\(cell,\(\)=>openSupplierProfile\(String\(item\.supplier_code\)\)\)/);
  assert.match(app,/<td><strong>\$\{esc\(supplierDisplayName\(edr,item\.name\)\)\}<\/strong>/);
  assert.doesNotMatch(app,/supplier-card-link/);
  assert.match(app,/section\.querySelector\('h3'\)\.after\(actions\)/);
  assert.match(app,/link\.textContent='↗ Google ЄДР'/);
  assert.doesNotMatch(app,/source\.replaceChildren\(link\)|metadata\.append\(actions\)/);
});

test('one exact-code Google action works for PROD/SANDBOX, ЮО/ФОП, modal/floating',async()=>{
  const start=app.indexOf('function decorateSupplierEdrCard('),end=app.indexOf('\nfunction formatLegacyCardDates(',start);
  for(const environment of ['production','sandbox'])for(const [code,tab] of [['46130719','ЮО'],['1234567890','ФОП']])for(const mode of ['modal','floating']){
    const metadataLabels=['Статус у Prozorro','Статус у реєстрі (ЄДР)','Актуальність ЄДР','Дата перевірки','Синхронізовано з Google Sheets'];
    const rows=['Актуальний відомий керівник','ПІБ керівника у snapshot ЄДР','Повна назва з ЄДР','Скорочена назва з ЄДР',...metadataLabels].map(label=>({dt:{textContent:label},dd:{textContent:''},querySelector(selector){return selector==='dt'?this.dt:this.dd}}));
    let topActions,metadata;
    const section={isConnected:true,querySelectorAll:()=>rows,querySelector(selector){if(selector==='h3')return{after(value){topActions=value}};if(selector==='.supplier-profile-grid')return{after(value){metadata=value}};return null}};
    const body={dataset:{detailWindow:mode},querySelector(selector){return selector==='.supplier-profile-edr'?section:{}}};
    const created=[],requests=[];
    const context=vm.createContext({document:{documentElement:{dataset:{pqmEnvironment:environment}},createElement:()=>{const element={children:[],append(...children){this.children.push(...children)}};created.push(element);return element}},$:(selector)=>selector==='#supplierProfileSubtitle'?{textContent:`ЄДРПОУ / РНОКПП: ${code}`}:null,compactSupplierNote(){},role:()=> 'admin',displayEdrStatus:value=>value,request:url=>{requests.push(url);return Promise.resolve({source_tab:tab})},API:'/api',encodeURIComponent});
    vm.runInContext(app.slice(start,end),context);
    context.decorateSupplierEdrCard(body,code,{edr_status:'Зареєстровано'},{note:''});
    await Promise.resolve();
    const expected=`/api/${environment==='sandbox'?'sandbox/supplier-google-row':'supplier-google-row'}/${code}`;
    assert.deepEqual(requests,[expected]);
    assert.equal(topActions.className,'supplier-edr-actions');
    assert.equal(topActions.children[0].textContent,'↗ Clarity Project');
    const googleLinks=topActions.children.filter(child=>child.textContent==='↗ Google ЄДР');
    assert.equal(googleLinks.length,1);
    assert.equal(googleLinks[0].href,`${expected}?open=1`);
    assert.equal(metadata.className,'supplier-edr-metadata');
    assert.deepEqual(metadata.children.map(row=>row.dt.textContent),metadataLabels);
    assert.ok(!metadata.children.includes(topActions));
    assert.ok(!rows.some(row=>row.dt.textContent==='Джерело snapshot'));
  }
});

test('missing exact Google row leaves only the top Clarity action',async()=>{
  const start=app.indexOf('function decorateSupplierEdrCard('),end=app.indexOf('\nfunction formatLegacyCardDates(',start);
  const labels=['Актуальний відомий керівник','ПІБ керівника у snapshot ЄДР','Повна назва з ЄДР','Скорочена назва з ЄДР','Статус у Prozorro','Статус у реєстрі (ЄДР)','Актуальність ЄДР','Дата перевірки','Синхронізовано з Google Sheets'];
  const rows=labels.map(label=>({dt:{textContent:label},dd:{textContent:''},querySelector(selector){return selector==='dt'?this.dt:this.dd}}));
  let actions;
  const section={isConnected:true,querySelectorAll:()=>rows,querySelector(selector){if(selector==='h3')return{after(value){actions=value}};if(selector==='.supplier-profile-grid')return{after(){}}}};
  const context=vm.createContext({document:{documentElement:{dataset:{pqmEnvironment:'sandbox'}},createElement:()=>({children:[],append(...children){this.children.push(...children)}})},$:(selector)=>selector==='#supplierProfileSubtitle'?{textContent:'ЄДРПОУ / РНОКПП: 46130719'}:null,compactSupplierNote(){},role:()=> 'viewer',displayEdrStatus:value=>value,request:()=>Promise.reject(new Error('not found')),API:'/api',encodeURIComponent});
  vm.runInContext(app.slice(start,end),context);
  context.decorateSupplierEdrCard({querySelector:selector=>selector==='.supplier-profile-edr'?section:{}},'46130719',{edr_status:'Зареєстровано'},{note:''});
  await new Promise(setImmediate);
  assert.deepEqual(actions.children.map(child=>child.textContent),['↗ Clarity Project']);
});

test('shared supplier code action keeps code and arrow in one row',()=>{
  const start=app.indexOf('function installSupplierCodeAction('),end=app.indexOf('\nfunction supplierEdrDatesHtml(',start);
  let opened=0;
  const makeElement=()=>({children:[],classList:{add(){}},append(...children){this.children.push(...children)},setAttribute(name,value){this[name]=value}});
  const cell={textContent:'46130719',classList:{add(value){this.value=value}},replaceChildren(value){this.child=value}};
  const context=vm.createContext({document:{createElement:makeElement}});
  vm.runInContext(app.slice(start,end),context);
  context.installSupplierCodeAction(cell,()=>opened++);
  assert.equal(cell.classList.value,'supplier-code-action-cell');
  assert.equal(cell.child.className,'supplier-code-line');
  assert.equal(cell.child.children[0].textContent,'46130719');
  const action=cell.child.children[1];
  assert.equal(action.title,'Відкрити картку постачальника');
  assert.equal(action.textContent,'↗');
  let stopped=false;action.onclick({stopPropagation(){stopped=true}});
  assert.equal(opened,1);assert.equal(stopped,true);
});

test('five EDR metadata cards retain readable typography and SANDBOX theme',()=>{
  const css=fs.readFileSync('styles.css','utf8');
  const root=fs.readFileSync('index.html','utf8');
  const sandbox=fs.readFileSync('sandbox_runtime.py','utf8');
  const metadata=css.match(/\.supplier-edr-metadata\{([^}]*)\}/)?.[1]||'';
  const labels=css.match(/\.supplier-edr-metadata dt\{([^}]*)\}/)?.[1]||'';
  const values=css.match(/\.supplier-edr-metadata dd\{([^}]*)\}/)?.[1]||'';
  assert.match(metadata,/display:grid;grid-template-columns:repeat\(auto-fit,minmax\(/);
  assert.ok(Number(labels.match(/font-size:(\d+)px/)?.[1])>=12);
  assert.ok(Number(values.match(/font-size:(\d+)px/)?.[1])>=14);
  assert.ok(Number(values.match(/font-weight:(\d+)/)?.[1])>=700);
  assert.match(css,/html\[data-pqm-environment="sandbox"\] \.supplier-edr-metadata>div\{[^}]*background:/);
  assert.match(sandbox,/id="sandboxWarning"[^\n]*position:fixed;bottom:0/);
  assert.doesNotMatch(root,/id="sandboxWarning"|id="pqmSandboxTheme"/);
  const edr=app.slice(app.indexOf('<section class="supplier-profile-section supplier-profile-edr">'),app.indexOf('<section class="supplier-profile-section supplier-nazk-context">'));
  assert.doesNotMatch(edr,/Джерело snapshot|Поточний рядок Google не підтверджено|Google-таблиця ·/);
  assert.equal((edr.match(/<div><dt>/g)||[]).length,7);
  assert.match(edr,/\$\{supplierEdrDatesHtml\(edr\)\}/);
});
