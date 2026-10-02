const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const root=path.resolve(__dirname,'..');
const app=fs.readFileSync(path.join(root,'app.js'),'utf8');
const history=fs.readFileSync(path.join(root,'history_ui.js'),'utf8');
const css=fs.readFileSync(path.join(root,'styles.css'),'utf8');
const html=fs.readFileSync(path.join(root,'index.html'),'utf8');
const sandboxRuntime=fs.readFileSync(path.join(root,'sandbox_runtime.py'),'utf8');
const sandboxTheme=fs.readFileSync(path.join(root,'sandbox_theme.css'),'utf8');
const section=(source,from,to)=>source.slice(source.indexOf(from),source.indexOf(to,source.indexOf(from)));
const dates=section(app,'function displayDate(value)','function addCalendarDays(');
const context=vm.createContext({Intl,Date,Object,String});
vm.runInContext(dates,context);
vm.runInContext(section(app,'function environmentBannerText(features)','async function loadRuntimeFeatures()'),context);
assert.equal(context.environmentBannerText({environment:'production',sandbox_mode:false}),'PQM');
assert.equal(context.environmentBannerText({environment:'test_web',sandbox_mode:true}),'PQM');
assert.equal(context.environmentBannerText({environment:'local',sandbox_mode:false}),'PQM');
assert.equal(context.environmentBannerText({environment:'test_web',sandbox_mode:false}),'PQM');
assert.match(html,/<div class="brand prod-brand">[\s\S]*?id="environmentBanner" class="prod-brand-accessible">PQM<\/em>/);
assert.match(html,/src="\/assets\/pqm-brand-mark-prod\.svg"/);
assert.match(html,/href="\/assets\/pqm-q-favicon-192\.png\?v=5"/);
assert.match(sandboxRuntime,/class="brand sandbox-brand"/);
assert.match(sandboxRuntime,/pqm-brand-mark\.svg/);
assert.match(sandboxRuntime,/pqm-q-favicon\.svg\?v=4/);
assert.match(css,/\.topbar \.brand\.prod-brand\{gap:0;align-items:center\}/);
assert.match(sandboxTheme,/html\[data-pqm-environment="sandbox"\] \.topbar \.brand\.sandbox-brand/);
assert.doesNotMatch(html,/Розроблено для ДУ/);
assert.match(css,/@media\(max-width:1280px\)\{[\s\S]*?\.topbar #mainNav\{order:5/);
assert.equal(context.displayDateOnly('2026-09-09'),'09.09.2026');
assert.equal(context.displayDate('2026-09-09'),'09.09.2026');
assert.equal(context.displayDate('2026-09-09T10:30:00+03:00'),'09.09.2026, 10:30');
for(const [canonical,marker] of Object.entries({
  'Зареєстровано':'✅','Неактуально':'⚪','Немає інформації':'⚪',
  'В стані припинення':'🟡','Порушено справу про банкрутство':'🟡',
  'Припинено':'🔴','Банкрут':'🔴'})){
  assert.ok(context.displayEdrStatus(canonical).startsWith(marker+' '));
}
assert.equal(context.displayEdrStatus('Невідомий стан'),'Невідомий стан');
vm.runInContext(section(history,'function historyDateCell(value)','let historyPage='),
  vm.createContext({displayDate:context.displayDate,esc:value=>value}));

const nodes=[];
const makeNode=()=>({hidden:false,after(){},focus(){this.focused=true},textContent:'',title:'',value:''});
const editor=makeNode(),save=makeNode(),meta=makeNode(),heading=makeNode();
const supplierNoteSection={querySelector(selector){return ({'#supplierProfileNote':editor,'#supplierProfileNoteSave':save,small:meta,h3:heading})[selector]}};
const noteContext=vm.createContext({document:{createElement(){const node=makeNode();nodes.push(node);return node}},String});
vm.runInContext(section(app,'function compactSupplierNote(','function decorateSupplierEdrCard('),noteContext);
noteContext.compactSupplierNote(supplierNoteSection,'',false);
assert.equal(editor.hidden,true);assert.equal(save.hidden,true);
assert.equal(nodes[0].textContent,'+ Додати примітку');
nodes[0].onclick();assert.equal(editor.hidden,false);assert.equal(save.hidden,false);
nodes[2].onclick();assert.equal(editor.hidden,true);assert.equal(save.hidden,true);
nodes.length=0;
noteContext.compactSupplierNote(supplierNoteSection,'Історична примітка',false);
assert.equal(nodes[0].textContent,'Редагувати');assert.equal(nodes[1].textContent,'Історична примітка');
for(const [environment,expected] of [
  ['production','/api/supplier-google-row/46130719'],
  ['sandbox','/api/sandbox/supplier-google-row/46130719'],
]){
  const requests=[],links=[];
  const edrSection={isConnected:true,querySelectorAll:()=>[],querySelector(selector){
    if(selector==='h3')return{after(){}};
    if(selector==='.supplier-profile-grid')return{after(){}};
  }};
  const body={querySelector(selector){return selector==='.supplier-profile-edr'?edrSection:{}}};
  const routeContext=vm.createContext({
    document:{documentElement:{dataset:{pqmEnvironment:environment}},createElement:()=>({append(node){links.push(node)}})},
    $:()=>({textContent:'ЄДРПОУ / РНОКПП: 46130719'}),
    compactSupplierNote(){},role:()=> 'admin',displayEdrStatus:value=>value,
    request:url=>{requests.push(url);return{then(callback){callback();return{catch(){}}}}},
    API:'/api',encodeURIComponent,
  });
  vm.runInContext(section(app,'function decorateSupplierEdrCard(','function formatLegacyCardDates('),routeContext);
  routeContext.decorateSupplierEdrCard(body,'46130719',{edr_status:'Зареєстровано'},{note:''});
  assert.deepEqual(requests,[expected],`${environment} must request its own Google-row route`);
  assert.equal(links.find(link=>link.textContent==='↗ Google ЄДР')?.href,`${expected}?open=1`,`${environment} must open its own Google-row route`);
}
assert.match(app,/Відкрити картку постачальника/);
const docs=html.match(/<dialog id="docsDialog">([\s\S]*?)<\/dialog>/)?.[1]||'';
assert.match(docs,/<form method="dialog"><header>/);
assert.match(docs,/<div id="docsList" class="docs-list"><\/div><footer>/);
assert.match(docs,/<footer>[\s\S]*?<a id="archiveDownloadBtn"[^>]*>⇩ Завантажити всі<\/a>/);
assert.match(css, /#docsDialog,#documentCheckDialog\)>form\{display:flex;flex-direction:column;max-height:min\(92vh,980px\);overflow:hidden\}/);
assert.match(css, /#docsDialog,#documentCheckDialog\)>form>footer\{flex:0 0 auto;position:relative/);
assert.match(css, /#docsList,#documentCheckBody\)\{min-height:0;max-height:none;overflow-y:auto/);
assert.match(app, /\$\('#archiveDownloadBtn'\)\.href=`\$\{API\}\/applications\/\$\{encodeURIComponent\(row\.id\)\}\/archive`/);
assert.match(css,/\.supplier-shared-note \[hidden\]\{display:none!important\}/);
assert.match(html,/id="operationalTaskTypes"/);
for(const type of ['amcu_exclusion','nazk_check','warning_block','termination_exclusion']){
  assert.match(app,new RegExp(`'${type}'`));
  assert.match(css,new RegExp(`data-task-type="${type}"`));
}
assert.match(app,/renderOperationalTaskTypes\(data\.type_counts\|\|\{\}\)/);
assert.match(app,/aria-pressed="\$\{selected===type\}"/);
assert.match(css,/\.operational-type-kpi\.active/);
const renderedTypes={innerHTML:''},renderedTypeFilter={value:'warning_block'};
const renderTypesContext=vm.createContext({$:selector=>selector==='#operationalTaskTypes'?renderedTypes:renderedTypeFilter,esc:value=>String(value),Number,operationalTaskTypeLabels:{nazk_check:'НАЗК',amcu_exclusion:'АМКУ',warning_block:'Звернення',termination_exclusion:'Припинення'}});
vm.runInContext(section(app,'function renderOperationalTaskTypes(counts){',"$('#operationalTaskTypes').onclick="),renderTypesContext);
renderTypesContext.renderOperationalTaskTypes({nazk_check:3,amcu_exclusion:2,warning_block:1,termination_exclusion:4});
for(const type of ['nazk_check','amcu_exclusion','warning_block','termination_exclusion'])assert.match(renderedTypes.innerHTML,new RegExp(`data-task-type="${type}"`));
assert.match(renderedTypes.innerHTML,/data-task-type="warning_block" aria-pressed="true"/);
assert.match(renderedTypes.innerHTML,/data-task-type="nazk_check" aria-pressed="false"/);
let typeReloads=0;
const typeSelect={value:''},typeKpiNode={},typeActions=vm.createContext({$:selector=>selector==='#operationalTaskTypes'?typeKpiNode:typeSelect,loadOperationalTasks(){typeReloads++}});
vm.runInContext(section(app,"$('#operationalTaskTypes').onclick=","function operationalTaskEmptyMessage"),typeActions);
for(const type of ['amcu_exclusion','nazk_check','warning_block','termination_exclusion']){
  const typeEvent={target:{closest:()=>({dataset:{taskType:type}})}};
  typeKpiNode.onclick(typeEvent);assert.equal(typeSelect.value,type);
  typeKpiNode.onclick(typeEvent);assert.equal(typeSelect.value,'');
}
assert.equal(typeReloads,8);
assert.match(app,/operationalTaskTypeMarker\(item\.task_type\)/);
let supplierCardOpens=0,supplierRowClicks=0;
const makeSupplierElement=()=>({children:[],append(...children){this.children.push(...children)},setAttribute(name,value){this[name]=value}});
const supplierCodeCell={textContent:'46130719',classList:{add(value){this.value=value}},replaceChildren(value){this.child=value}};
const supplierCardContext=vm.createContext({document:{createElement:makeSupplierElement}});
vm.runInContext(section(app,'function installSupplierCodeAction(','function supplierEdrDatesHtml('),supplierCardContext);
supplierCardContext.installSupplierCodeAction(supplierCodeCell,()=>supplierCardOpens++);
assert.equal(supplierCodeCell.classList.value,'supplier-code-action-cell');
assert.equal(supplierCodeCell.child.className,'supplier-code-line');
assert.equal(supplierCodeCell.child.children.length,2,'supplier code and action must both remain in the cell');
const [supplierCodeText,supplierCardButton]=supplierCodeCell.child.children;
assert.equal(supplierCodeText.className,'supplier-code-value');
assert.equal(supplierCodeText.textContent,'46130719');
assert.equal(supplierCardButton.className,'supplier-card-action');
assert.equal(supplierCardButton.type,'button');
assert.equal(supplierCardButton.title,'Відкрити картку постачальника');
assert.equal(supplierCardButton['aria-label'],supplierCardButton.title);
assert.equal(supplierCardButton.textContent,'↗');
assert.notEqual(supplierCardButton.hidden,true);
assert.match(css,/\.supplier-code-line\{[^}]*display:grid;[^}]*grid-template-columns:minmax\(0,1fr\) auto/);
assert.doesNotMatch(css.match(/\.supplier-code-action-cell \.supplier-card-action\{[^}]*\}/)?.[0]||'',/display:none|visibility:hidden/);
supplierCardButton.onclick({stopPropagation(){supplierRowClicks++}});
assert.equal(supplierCardOpens,1);
assert.equal(supplierRowClicks,1);
assert.match(app,/installSupplierCodeAction\(cell,\(\)=>openSupplierProfile\(row\.dataset\.supplierCode\)\)/);
const overviewContext=vm.createContext({esc:value=>String(value||''),displayDate:value=>String(value||'')});
vm.runInContext(section(app,'function supplierProfileOverviewHtml(','function compactSupplierNote('),overviewContext);
const sampleOverview=overviewContext.supplierProfileOverviewHtml('Постачальник','12345678',{}, {history:[]},{note:''},false);
const sampleOverviewWithNote=overviewContext.supplierProfileOverviewHtml('Постачальник','12345678',{}, {history:[]},{note:'Історична примітка'},false);
function assertNoteIsThirdTopCard(markup){
  const stack=[],children=[];
  for(const match of markup.matchAll(/<(?:section|div)\b[^>]*>|<\/(?:section|div)>/g)){
    if(match[0].startsWith('</')){stack.pop();continue}
    const className=match[0].match(/class="([^"]+)"/)?.[1]||'';
    if(stack.length===1&&stack[0].includes('supplier-profile-overview'))children.push(className);
    if(className.includes('supplier-shared-note'))assert.equal(stack.length,1,'note must be inside the top summary grid, not a full-width sibling');
    stack.push(className);
  }
  assert.deepEqual(children,['supplier-profile-section supplier-profile-contacts','supplier-profile-section supplier-shared-note']);
  assert.doesNotMatch(markup,/supplier-profile-identity|<span>Постачальник<\/span>/);
  assert.equal(stack.length,0,'top summary sections must close cleanly');
  assert.equal((markup.match(/class="supplier-profile-section supplier-shared-note"/g)||[]).length,1);
}
assertNoteIsThirdTopCard(sampleOverview);
assertNoteIsThirdTopCard(sampleOverviewWithNote);
assert.match(app,/body\.innerHTML=`\$\{supplierProfileOverviewHtml\(/);
assert.doesNotMatch(app,/\.supplier-profile-edr'\)\.after\(body\.querySelector\('\.supplier-shared-note'\)\)/);
assert.match(css,/\.supplier-profile-overview\{grid-template-columns:repeat\(2,minmax\(0,1fr\)\)/);
assert.ok(app.includes("$('#supplierProfileSubtitle').innerHTML=`ЄДРПОУ / РНОКПП: <strong>"));
assert.match(app,/supplierAction\.textContent='↗ Картка постачальника'/);
assert.match(app,/supplier-context-card-action/);
console.log('Supplier UX: date/status/note/navigation/card-shell checks passed');
