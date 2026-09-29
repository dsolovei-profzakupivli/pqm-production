const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const root=path.resolve(__dirname,'..');
const app=fs.readFileSync(path.join(root,'app.js'),'utf8');
const history=fs.readFileSync(path.join(root,'history_ui.js'),'utf8');
const css=fs.readFileSync(path.join(root,'styles.css'),'utf8');
const sandboxCss=fs.readFileSync(path.join(root,'sandbox_theme.css'),'utf8');
const modulesCss=fs.readFileSync(path.join(root,'modules.css'),'utf8');
const navigation=fs.readFileSync(path.join(root,'navigation.js'),'utf8');
const widths=fs.readFileSync(path.join(root,'table_widths_ui.js'),'utf8');
const section=(source,from,to)=>source.slice(source.indexOf(from),source.indexOf(to,source.indexOf(from)));
const dates=section(app,'function displayDate(value)','function addCalendarDays(');
const context=vm.createContext({Intl,Date,Object,String});
vm.runInContext(dates,context);
vm.runInContext(section(app,'function environmentBannerText(features)','async function loadRuntimeFeatures()'),context);
assert.equal(context.environmentBannerText({environment:'production',sandbox_mode:false}),'PQM');
assert.equal(context.environmentBannerText({environment:'test_web',sandbox_mode:true}),'PQM');
assert.equal(context.environmentBannerText({environment:'local',sandbox_mode:false}),'PQM');
assert.equal(context.environmentBannerText({environment:'test_web',sandbox_mode:false}),'PQM');
assert.match(fs.readFileSync(path.join(root,'index.html'),'utf8'),/id="environmentBanner"[^>]*>PQM<\/em>/);
assert.doesNotMatch(fs.readFileSync(path.join(root,'index.html'),'utf8'),/Розроблено для ДУ/);
const brandLayout=css.match(/\.topbar \.brand\{([^}]*)\}/)?.[1]||'';
assert.ok(Number(brandLayout.match(/gap:(\d+)px/)?.[1])>=20);
assert.ok(Number(brandLayout.match(/margin-right:(\d+)px/)?.[1])>=18);
const productLabel=css.match(/\.topbar #environmentBanner\{([^}]*)\}/)?.[1]||'';
assert.match(productLabel,/font-size:32px/);
assert.match(productLabel,/font-weight:800/);
assert.match(sandboxCss,/\.sandbox-brand-initials\s*\{[^}]*font-size:36px;font-weight:800;line-height:1/);
assert.match(sandboxCss,/\.sandbox-brand-q\s*\{color:#86bdff\}/);
assert.match(sandboxCss,/\.sandbox-brand-divider\s*\{[^}]*height:32px/);
assert.match(sandboxCss,/\.sandbox-brand-copy strong\s*\{[^}]*font-size:15px/);
assert.match(sandboxCss,/\.sandbox-brand-copy small\s*\{[^}]*font-size:9\.5px;line-height:1\.1;margin-top:1px/);
assert.match(navigation,/function update\(\)\{button\.hidden=!canShowBack\(current\);button\.disabled=restoring/);
assert.match(navigation,/const back=\(\)=>\{if\(current\?\.previous&&!restoring\)\{snapshot\(\);history\.back\(\)\}\}/);
assert.match(widths,/colgroup\[data-system-widths\]/);
assert.match(widths,/table\.style\.tableLayout='fixed'/);
assert.match(widths,/table\.closest\('#suppliersView'\)&&!isVisible\(table\)\)return;apply\(table,saved\[key\]\|\|\{\}\)/);
assert.match(widths,/saved\[key\]=\{\.\.\.next/);
const widthContext=vm.createContext({WeakMap,Number,Math,Set,Array,document:{createElement(tag){return {style:{},dataset:{},children:[],replaceChildren(...children){this.children=children}}}}});
vm.runInContext("const defaultWidths=new WeakMap();function columnKey(th){return th.dataset.col}",widthContext);
vm.runInContext(section(widths,'function apply(table,widths){','const dialog='),widthContext);
function widthTable(){const heads=['name','code','status'].map(col=>({dataset:{col},style:{},hidden:false,getBoundingClientRect(){return {width:col==='name'?240:80}}}));const row={cells:heads.map(()=>({style:{},hidden:false}))};return {tHead:{rows:[{cells:heads}]},tBodies:[{rows:[row]}],dataset:{},style:{},group:null,closest:()=>({}),querySelector(){return this.group},prepend(group){this.group=group}}}
const widthFixture=widthTable();widthContext.apply(widthFixture,{code:150});
assert.equal(widthFixture.tHead.rows[0].cells[1].style.width,'150px');
assert.equal(widthFixture.tBodies[0].rows[0].cells[1].style.width,'150px');
assert.equal(widthFixture.group.children[1].style.width,'150px');
assert.equal(widthFixture.style.width,'470px');
widthFixture.tBodies[0].rows=[{cells:[{style:{}},{style:{}},{style:{}}]}];widthContext.apply(widthFixture,{code:150});
assert.equal(widthFixture.tBodies[0].rows[0].cells[1].style.width,'150px');
const afterReload=widthTable();widthContext.apply(afterReload,{code:150});
assert.equal(afterReload.group.children[1].style.width,'150px');
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
assert.match(app,/link\.href=`\$\{googleRowPath\}\?open=1`/);
assert.match(app,/actions\.append\(clarity\)/);
assert.match(app,/actions\.append\(link\)/);
assert.match(css,/\.supplier-edr-actions a\{display:inline-flex;align-items:center;justify-content:center;min-height:32px/);
const caseLabels=['genitive','dative','accusative'].map(value=>({dataset:{declensionCase:value},classList:{active:false,toggle(name,state){this.active=state}}}));
const editorNodes=new Map();
for(const id of ['declensionDialogTitle','declensionType','declensionOriginal','declensionGenitive','declensionDative','declensionAccusative','declensionComment','declensionDialogHint','declensionDialog'])editorNodes.set('#'+id,{value:'',textContent:'',showModal(){},focus(){}});
for(const value of ['genitive','dative','accusative'])editorNodes.set(`#declensionDialog [data-declension-case="${value}"] input`,{focus(){}});
const caseContext=vm.createContext({$:selector=>editorNodes.get(selector),$$:()=>caseLabels,editingDeclensionId:null,Set,Array});
vm.runInContext(section(app,'function openDeclensionEditor(','function declensionLookup('),caseContext);
for(const [required,expected] of [[['dative'],[false,true,false]],[['genitive'],[true,false,false]],[['genitive','dative'],[true,true,false]],[[],[false,false,false]]]){
  caseContext.openDeclensionEditor({entity_type:'legal_entity',original:'Тест'},required);
  assert.deepEqual(caseLabels.map(label=>label.classList.active),expected);
}
caseContext.openDeclensionEditor({entity_type:'legal_entity',original:'Тест'},['genitive','accusative'],{subject_label:'Постачальник'});
assert.deepEqual(caseLabels.map(label=>label.hidden),[false,true,false]);
assert.match(modulesCss,/\.declension-form label\[hidden\]\{display:none\}/);
caseContext.openDeclensionEditor({entity_type:'legal_entity',original:'Тест'});
assert.deepEqual(caseLabels.map(label=>label.hidden),[false,false,false]);
const pendingNodes=new Map(),pendingNode=selector=>{if(!pendingNodes.has(selector))pendingNodes.set(selector,{value:'',textContent:'',hidden:false,close(){}});return pendingNodes.get(selector)};
const pendingContext=vm.createContext({$:pendingNode,declensionItems:[{entity_type:'legal_entity',original:'Тест',genitive:'Тесту',dative:''}],declensionReturnContext:null,showModule(){},setReferenceTab(){},loadDeclensionOverrides:async()=>{},declensionLookup:value=>String(value||'').toLowerCase().trim(),openDeclensionEditor(_item,cases){pendingContext.selected=cases}});
vm.runInContext(section(app,'function remainingDeclensionItems(','async function returnToDeclensionReport(')+section(app,'async function openDocumentDeclension(','async function openDeclensionFromValidation('),pendingContext);
const pendingEntries=['genitive','dative'].map(grammatical_case=>({entity_type:'legal_entity',original:'Тест',grammatical_case}));
pendingContext.openDocumentDeclension(pendingEntries[0],{originType:'operational_task',taskId:'t',label:'задачі',entries:pendingEntries}).then(()=>{
  assert.deepEqual(Array.from(pendingContext.selected),['dative']);
}).catch(error=>{console.error(error);process.exitCode=1});
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
assert.match(app,/line\.append\(code,action\);cell\.classList\.add\('supplier-code-action-cell'\);cell\.replaceChildren\(line\)/);
assert.match(css,/\.supplier-code-line\{display:grid;grid-template-columns:minmax\(0,1fr\) auto;align-items:center/);
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
console.log('SANDBOX supplier UX: date/status/note/navigation/card-shell checks passed');
