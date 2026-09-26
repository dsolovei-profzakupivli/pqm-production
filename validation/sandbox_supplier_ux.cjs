const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const root=path.resolve(__dirname,'..');
const app=fs.readFileSync(path.join(root,'app.js'),'utf8');
const history=fs.readFileSync(path.join(root,'history_ui.js'),'utf8');
const css=fs.readFileSync(path.join(root,'styles.css'),'utf8');
const section=(source,from,to)=>source.slice(source.indexOf(from),source.indexOf(to,source.indexOf(from)));
const dates=section(app,'function displayDate(value)','function addCalendarDays(');
const context=vm.createContext({Intl,Date,Object,String});
vm.runInContext(dates,context);
vm.runInContext(section(app,'function environmentBannerText(features)','async function loadRuntimeFeatures()'),context);
assert.equal(context.environmentBannerText({environment:'production',sandbox_mode:false}),'PQM');
assert.equal(context.environmentBannerText({environment:'test_web',sandbox_mode:true}),'PQM · SANDBOX');
assert.equal(context.environmentBannerText({environment:'local',sandbox_mode:false}),'PQM · LOCAL');
assert.equal(context.environmentBannerText({environment:'test_web',sandbox_mode:false}),'PQM');
assert.match(fs.readFileSync(path.join(root,'index.html'),'utf8'),/id="environmentBanner"[^>]*>PQM<\/em>/);
assert.doesNotMatch(fs.readFileSync(path.join(root,'index.html'),'utf8'),/Розроблено для ДУ/);
assert.match(css,/\.topbar \.brand\{flex:0 0 auto;min-width:0;gap:8px\}/);
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
assert.match(app,/sandbox\/supplier-google-row/);
assert.match(app,/supplier-google-row\/\$\{encodeURIComponent\(code\)\}\?open=1/);
assert.match(app,/Відкрити картку постачальника/);
const html=fs.readFileSync(path.join(root,'index.html'),'utf8');
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
assert.match(app,/cell\.classList\.add\('supplier-code-action-cell'\)/);
assert.match(css,/\.supplier-code-action-cell \.supplier-card-action\{position:absolute;right:8px/);
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
  assert.deepEqual(children,['supplier-profile-identity','supplier-profile-section supplier-profile-contacts','supplier-profile-section supplier-shared-note']);
  assert.equal(stack.length,0,'top summary sections must close cleanly');
  assert.equal((markup.match(/class="supplier-profile-section supplier-shared-note"/g)||[]).length,1);
}
assertNoteIsThirdTopCard(sampleOverview);
assertNoteIsThirdTopCard(sampleOverviewWithNote);
assert.match(app,/body\.innerHTML=`\$\{supplierProfileOverviewHtml\(/);
assert.doesNotMatch(app,/\.supplier-profile-edr'\)\.after\(body\.querySelector\('\.supplier-shared-note'\)\)/);
assert.match(css,/\.supplier-profile-overview\{grid-template-columns:minmax\(0,\.9fr\)/);
assert.match(app,/supplierAction\.textContent='↗ Картка постачальника'/);
assert.match(app,/supplier-context-card-action/);
console.log('SANDBOX supplier UX: date/status/note/navigation/card-shell checks passed');
