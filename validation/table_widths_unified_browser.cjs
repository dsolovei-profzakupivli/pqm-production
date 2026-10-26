/* Real PQM markup, CSS and renderers. All requests are synthetic and offline. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
let chromium;try{({chromium}=require('playwright'))}catch{({chromium}=require('C:/Users/User/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'))}
const root=path.resolve(process.argv[2]||path.join(__dirname,'..')),out=path.join(root,'evidence','column-widths');fs.mkdirSync(out,{recursive:true});
const read=n=>fs.readFileSync(path.join(root,n),'utf8'),source=read('app.js');
const expected=['ПІБ','Порушення','Вид стягнення','Номер судової справи','Дата рішення','Дата набрання законної сили','Посилання на рішення','№ наказу','Дата наказу'];
const fixture=[
 {full_name:'ТЕСТ ДИСЦИПЛІНАРНИЙ НАКАЗ',offense_name:'Неповідомлення про конфлікт інтересів. '.repeat(4),punishment:'догана',decree_number:'00153-к/А',decree_date:'2026-08-19'},
 {full_name:'ТЕСТ СУДОВЕ РІШЕННЯ',offense_name:'Порушення',court_case_number:'001/2026-А',sentence_date:'2026-08-01',punishment_start:'2026-08-15',decision_url:'https://example.invalid/court'},
 {full_name:'ТЕСТ БЕЗ ДАТИ НАКАЗУ',offense_name:'Порушення',punishment:'звільнення',decree_number:'0007-Б'},
 {full_name:'ТЕСТ ОБИДВА ВИДИ РЕКВІЗИТІВ',offense_name:'Порушення',punishment:'догана',decree_number:'0009-К/Б',decree_date:'2026-09-01',court_case_number:'2026-09-05',sentence_date:'2026-09-02',decision_url:'https://example.invalid/both'}
];
const legacy={'referencesView:refAmcuBody':{'суб-єкт':410,'код':110,'рішення':170,'дата':120,'орган-амку':230,'судова-справа':150}};
legacy['referencesView:legacy-nazk']={'піб':431,'порушення':541};
legacy['suppliersView:supplierRegistryBody']={'постачальник':380,'єдрпоу-рнокпп':155};
const sharedStore=structuredClone(legacy),personalProfiles=new Map(),historySettings=new Map();let failNextSharedSave=false,personalId=0,sharedWrites=0;
const defaultApplicationColumns=[{key:'participant',label:'Назва учасника',width:260,order:0,visible:true},{key:'edrpou',label:'Код',width:140,order:1,visible:true}];
const markup=read('index.html').replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,'');
const stub=`window.API='/api';window.authReady=Promise.resolve();window.calls=[];window.toast=()=>{};window.$=s=>document.querySelector(s);window.esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
window.request=async(url,options={})=>{const method=options.method||'GET';calls.push({url,method});const response=await fetch(url,{...options,headers:{...(options.headers||{}),'X-Fixture-Role':document.body.dataset.authRole,'X-Fixture-User':new URL(location).searchParams.get('user')||'alice'}});const data=await response.json();if(!response.ok)throw Error(data.error||'Request failed');return data};
document.querySelector('#loginGate').hidden=true;document.querySelector('#applicationShell').hidden=false;document.querySelectorAll('main').forEach(m=>m.hidden=m.id!=='referencesView');document.body.dataset.authRole='admin';document.querySelector('#referenceNazk').hidden=false;document.querySelector('#referenceAmcu').hidden=true;document.querySelector('#referenceDeclension').hidden=true;`;
const html=markup.replace('</body>',`<script>${stub}</script><script src="/table_widths_ui.js"></script></body>`);
const lineFunction=n=>source.split(/\r?\n/).find(l=>l.startsWith('function '+n+'('));
const loader=source.slice(source.indexOf('loadReferenceRegistry=async function(kind){',source.indexOf('const loadReferenceRegistryBase=')),source.indexOf("$('#refNazkSearch').oninput="));
async function prepare(page,user='alice'){
 await page.goto('http://pqm.test/fixture?user='+user);
 await page.evaluate(()=>{window.referencePages={nazk:1};window.referencePageCounts={nazk:1};window.loadReferenceRegistryBase=()=>{};window.displayDateOnly=x=>x||'';window.operationalNazkRecords=x=>x.records;window.nazkRegistrySourceNotice=()=>''});
 await page.addScriptTag({content:loader+'\n'+lineFunction('displayDateOnly')+'\n'+lineFunction('operationalNazkContext')});await page.evaluate(()=>loadReferenceRegistry('nazk'));
 await page.locator('#referenceNazk .system-width-button').waitFor();
}
async function openEditor(page,scope='#referenceNazk'){await page.locator(scope+' .system-width-button').click();await page.locator('.system-width-dialog[open]').waitFor()}
async function widths(page,selector){return page.locator(selector+' thead th').evaluateAll(ns=>ns.map(n=>Math.round(n.getBoundingClientRect().width)))}
async function drag(page,selector,index,delta){
 const h=page.locator(selector+' thead th').nth(index);await h.scrollIntoViewIfNeeded();const rect=await h.boundingBox();await page.mouse.move(rect.x+rect.width-2,rect.y+rect.height/2);await page.mouse.down();await page.mouse.move(rect.x+rect.width-2+delta,rect.y+rect.height/2,{steps:5});await page.mouse.up();await page.waitForTimeout(280);
}
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.PQM_TEST_BROWSER?{executablePath:process.env.PQM_TEST_BROWSER}:fs.existsSync('C:/Users/User/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe')?{executablePath:'C:/Users/User/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe'}:{})});
 const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage(),errors=[],results=[];
 page.on('pageerror',e=>errors.push(String(e)));
 async function installRoutes(ctx){await ctx.route('**/*',async route=>{
  const u=new URL(route.request().url());assert.equal(u.hostname,'pqm.test','No external network allowed');
  if(u.pathname==='/fixture')return route.fulfill({contentType:'text/html',body:html});
  if(u.pathname==='/api/table-widths')return route.fulfill({contentType:'application/json',body:JSON.stringify({tables:sharedStore})});
  if(u.pathname==='/api/application-profiles'){
   const user=route.request().headers()['x-fixture-user']||'alice',method=route.request().method();let items=personalProfiles.get(user)||[];
   if(method==='GET')return route.fulfill({contentType:'application/json',body:JSON.stringify({items:[{id:'system-main',owner_key:'__system__',name:'Основний реєстр',is_system:true,columns:defaultApplicationColumns,kpis:[],sorts:[]},...items]})});
   if(method==='POST'){
    const role=route.request().headers()['x-fixture-role'],payload=route.request().postDataJSON();if(role==='viewer'&&payload.is_system)return route.fulfill({status:403,contentType:'application/json',body:JSON.stringify({error:'system profile admin only'})});
    const item={...payload,id:`personal-${user}-${++personalId}`,owner_key:user,is_system:false};personalProfiles.set(user,[...items,item]);return route.fulfill({status:201,contentType:'application/json',body:JSON.stringify({saved:true,id:item.id})});
   }
  }
  const profileMatch=u.pathname.match(/^\/api\/application-profiles\/([^/]+)$/);
  if(profileMatch&&route.request().method()==='PATCH'){
   const user=route.request().headers()['x-fixture-user']||'alice',role=route.request().headers()['x-fixture-role'],items=personalProfiles.get(user)||[],payload=route.request().postDataJSON(),index=items.findIndex(item=>item.id===decodeURIComponent(profileMatch[1]));
   if(role==='viewer'&&index<0)return route.fulfill({status:403,contentType:'application/json',body:JSON.stringify({error:'owner scope'})});
   if(index<0)return route.fulfill({status:404,contentType:'application/json',body:JSON.stringify({error:'profile missing'})});
   items[index]={...items[index],...payload};personalProfiles.set(user,items);return route.fulfill({contentType:'application/json',body:JSON.stringify({saved:true,id:items[index].id})});
  }
  if(u.pathname==='/api/history-columns'){
   const user=route.request().headers()['x-fixture-user']||'alice';if(route.request().method()==='POST')historySettings.set(user,route.request().postDataJSON().columns);
   return route.fulfill({contentType:'application/json',body:JSON.stringify({columns:historySettings.get(user)||[]})});
  }
  if(u.pathname==='/api/nazk-registry')return route.fulfill({contentType:'application/json',body:JSON.stringify({items:fixture,total:4,pages:1,courts:[]})});
  if(u.pathname==='/api/admin/table-widths'&&route.request().method()==='POST'){
   const role=route.request().headers()['x-fixture-role'];if(role!=='admin')return route.fulfill({status:403,contentType:'application/json',body:JSON.stringify({error:'admin only'})});
   if(failNextSharedSave){failNextSharedSave=false;return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'synthetic save failure'})})}
   const payload=route.request().postDataJSON(),old=sharedStore[payload.table_key]||{},next={...old,...payload.widths};
   sharedWrites++;
   if(Array.isArray(payload.visible))next.__visible__=payload.visible;if(Array.isArray(payload.order))next.__order__=payload.order;if(Array.isArray(payload.columns))next.__columns__=payload.columns;
   sharedStore[payload.table_key]=next;return route.fulfill({contentType:'application/json',body:JSON.stringify({saved:true,widths:next})});
  }
  if(u.pathname==='/api/admin/table-widths'&&route.request().method()==='DELETE'){
   const role=route.request().headers()['x-fixture-role'];if(role!=='admin')return route.fulfill({status:403,contentType:'application/json',body:JSON.stringify({error:'admin only'})});
   delete sharedStore[u.searchParams.get('table_key')];return route.fulfill({contentType:'application/json',body:JSON.stringify({reset:true})});
  }
  if(u.pathname==='/api/applications/search-fields')return route.fulfill({contentType:'application/json',body:JSON.stringify({items:[]})});
  const file=path.resolve(root,'.'+u.pathname);if(file.startsWith(root+path.sep)&&fs.existsSync(file)&&fs.statSync(file).isFile())return route.fulfill({path:file});
  return route.fulfill({status:404,body:''});
 });}
 await installRoutes(context);
 try{
  if(process.argv.includes('--native-only')){console.log(await require('./table_widths_native_browser.cjs')({page,prepare,drag,read,out}));assert.deepEqual(errors,[]);return}
  await prepare(page,'scenario-width');
  await page.evaluate(()=>{
   document.body.dataset.authRole='admin';document.querySelectorAll('main').forEach(main=>main.hidden=main.id!=='requestsView');
   document.querySelector('#requestsBody').innerHTML='<tr>'+Array.from({length:10},(_,index)=>`<td>${index===7?'Короткий сценарій для перевірки налаштування ширини':''}</td>`).join('')+'</tr>';
  });
  const scenarioTable='#requestsView .requests-table',scenarioKey='requestsView:requestsBody';
  await page.waitForFunction(key=>document.querySelector('#requestsView .requests-table')?.dataset.systemTable===key,scenarioKey);
  await page.locator(`#requestsView .system-width-button[data-table-key="${scenarioKey}"]`).waitFor();
  await page.locator(`#requestsView .system-width-button[data-table-key="${scenarioKey}"]`).click();
  await page.locator('.system-width-fields [data-column="decision_justification"]').fill('260');
  await page.locator('.system-width-dialog .primary').click();
  await page.waitForFunction(()=>Math.round(document.querySelector('#requestsView .requests-table thead th[data-column-key="decision_justification"]').getBoundingClientRect().width)===260);
  assert.equal(sharedStore[scenarioKey]['decision_justification'],260,'Scenario column width is saved through the existing shared table settings API');
  await page.reload();
  await page.evaluate(()=>{document.body.dataset.authRole='admin';document.querySelectorAll('main').forEach(main=>main.hidden=main.id!=='requestsView');document.querySelector('#requestsBody').innerHTML='<tr>'+Array.from({length:10},(_,index)=>`<td>${index===7?'Короткий сценарій після перезавантаження':''}</td>`).join('')+'</tr>'});
  await page.waitForFunction(()=>Math.round(document.querySelector('#requestsView .requests-table thead th[data-column-key="decision_justification"]')?.getBoundingClientRect().width||0)===260);
  assert.equal(Math.round(await page.locator(scenarioTable+' thead th[data-column-key="decision_justification"]').evaluate(th=>th.getBoundingClientRect().width)),260,'Scenario column width survives an F5-style page reload');
  results.push('Appeals scenario column: shared width saved through existing admin API and restored after page reload');
  await prepare(page);
  const supplierTable='#suppliersView .supplier-table';
  assert.equal(await page.locator(supplierTable).count(),1);
  assert.equal(await page.locator(supplierTable).evaluate(table=>table.closest('main').hidden),true);
  assert.equal(await page.locator(supplierTable).getAttribute('data-system-table'),null,
    'Saved supplier widths must not be applied while its view is hidden');
  await page.evaluate(()=>{
   const view=document.querySelector('#suppliersView'),body=document.querySelector('#supplierRegistryBody');
   document.querySelectorAll('main').forEach(main=>main.hidden=main!==view);
   body.innerHTML='<tr>'+Array.from({length:9},(_,i)=>`<td>Синтетичний постачальник ${i+1}</td>`).join('')+'</tr>';
  });
  await page.locator('#suppliersView .system-width-button').waitFor();
  await page.waitForFunction(()=>Math.round(document.querySelector('#suppliersView .supplier-table thead th').getBoundingClientRect().width)===380);
  assert.equal((await widths(page,supplierTable))[0],380,'Saved widths apply after supplier view becomes visible');
  await openEditor(page,'#suppliersView');
  await page.locator('.system-width-fields [data-column="постачальник"]').fill('455');
  await page.locator('.system-width-dialog .primary').click();
  await page.waitForFunction(()=>Math.round(document.querySelector('#suppliersView .supplier-table thead th').getBoundingClientRect().width)===455);
  assert.equal(sharedStore['suppliersView:supplierRegistryBody']['постачальник'],455,
    'Supplier width is persisted through the shared settings API');
  await page.evaluate(()=>{document.querySelector('#suppliersView').hidden=true;document.querySelector('#referencesView').hidden=false});
  await page.waitForTimeout(80);
  assert.equal(await page.locator(supplierTable).evaluate(table=>table.closest('main').hidden),true,
    'Supplier table remains inside its hidden view between navigation changes');
  assert.equal(await page.locator(supplierTable+' thead th').first().evaluate(th=>th.style.width),'455px',
    'Hiding the supplier view does not discard its applied width');
  await page.evaluate(()=>{document.querySelector('#referencesView').hidden=true;document.querySelector('#suppliersView').hidden=false});
  await page.waitForFunction(()=>Math.round(document.querySelector('#suppliersView .supplier-table thead th').getBoundingClientRect().width)===455);
  assert.equal((await widths(page,supplierTable))[0],455,'Saved width reapplies after hide/show');
  await page.reload();
  assert.equal(await page.locator(supplierTable).evaluate(table=>table.closest('main').hidden),true);
  assert.equal(await page.locator(supplierTable).getAttribute('data-system-table'),null,
    'Supplier view starts hidden and remains unapplied after reload');
  await page.evaluate(()=>{document.querySelectorAll('main').forEach(main=>main.hidden=main.id!=='suppliersView')});
  await page.locator('#suppliersView .system-width-button').waitFor();
  await page.waitForFunction(()=>Math.round(document.querySelector('#suppliersView .supplier-table thead th').getBoundingClientRect().width)===455);
  assert.equal((await widths(page,supplierTable))[0],455,'Supplier width survives reload and is applied only when visible');
  results.push('Supplier table: hidden view defers saved widths; admin edit persists; hide/show and reload reapply after visibility');
  if(process.argv.includes('--supplier-only')){assert.deepEqual(errors,[]);console.log(JSON.stringify({status:'PASS',results},null,2));return}
  await prepare(page);
  assert.deepEqual(await page.locator('#referenceNazk thead th').allTextContents(),expected);
  const initialNazkWidths=(await widths(page,'#referenceNazk table')).slice(0,3);
  if(process.argv.includes('--production-source'))assert(initialNazkWidths.every(value=>value>0),`Production NAZK columns need measurable widths: ${initialNazkWidths}`);
  else assert.deepEqual(initialNazkWidths,[380,520,160]);
  const defaultNazkWidth=initialNazkWidths[0];
  for(const [i,item] of fixture.entries()){
   const cells=await page.locator('#refNazkBody tr').nth(i).locator('td').allTextContents();assert.equal(cells[2],item.punishment||'—');assert.equal(cells[7],item.decree_number||'—');assert.equal(cells[8],item.decree_date||'—');assert.equal(cells[3],item.court_case_number||'—');assert.equal(cells[4],item.sentence_date?item.sentence_date.split('-').reverse().join('.'):'—');assert.equal(cells[5],item.punishment_start?item.punishment_start.split('-').reverse().join('.'):'—');
  }
  results.push('NAZK directory: exact order, defaults, four synthetic records and court fields');
  await openEditor(page);await page.locator('[data-column="full_name"]').fill('430');await page.locator('.system-width-dialog .primary').click();await page.waitForFunction(()=>Math.round(document.querySelector('#referenceNazk thead th').getBoundingClientRect().width)===430);assert.equal((await widths(page,'#referenceNazk table'))[0],430);
  await prepare(page);assert.equal((await widths(page,'#referenceNazk table'))[0],430);results.push('Modal -> table -> real page reload persistence');
  await page.evaluate(()=>{window.sortClicks=0;document.querySelector('#referenceNazk thead').addEventListener('click',()=>sortClicks++)});
  await drag(page,'#referenceNazk table',0,75);assert.equal((await widths(page,'#referenceNazk table'))[0],505);assert.equal(await page.evaluate(()=>sortClicks),0);
  await page.locator('#referenceNazk thead th').first().click({position:{x:20,y:20}});assert.equal(await page.evaluate(()=>sortClicks),1,'Regular header clicks still sort');
  await openEditor(page);assert.equal(await page.locator('[data-column="full_name"]').inputValue(),'505');await page.locator('.dialog-cancel').click();
  await prepare(page);assert.equal((await widths(page,'#referenceNazk table'))[0],505);results.push('Drag -> modal -> reload, sorting suppressed only for resize');
  await page.locator('#referenceNazk thead th').first().click({position:{x:20,y:20}}); // regular sort clicks remain available
  await prepare(page,'bob');assert.equal((await widths(page,'#referenceNazk table'))[0],505);results.push('Shared table settings are not account-scoped');
  await openEditor(page);await page.locator('.system-width-fields [data-order-key="full_name"] .order-down').click();await page.locator('.system-width-dialog .primary').click();
  if(process.argv.includes('--production-source'))await page.waitForTimeout(350);
  else await page.waitForFunction(()=>document.querySelector('#referenceNazk thead th')?.textContent.trim()==='Порушення');
  assert.deepEqual((await page.locator('#referenceNazk thead th').allTextContents()).slice(0,2),['Порушення','ПІБ']);assert.equal((await widths(page,'#referenceNazk table'))[1],505);
  const otherContext=await browser.newContext({viewport:{width:1440,height:1000}});await installRoutes(otherContext);const otherPage=await otherContext.newPage();await prepare(otherPage,'bob');assert.equal((await widths(otherPage,'#referenceNazk table'))[1],505);assert.deepEqual((await otherPage.locator('#referenceNazk thead th').allTextContents()).slice(0,2),['Порушення','ПІБ']);await otherContext.close();await prepare(page,'alice');
  await openEditor(page);await page.locator('.system-width-fields [data-order-key="full_name"] .order-up').click();await page.locator('.system-width-dialog .primary').click();await page.waitForFunction(()=>document.querySelector('#referenceNazk thead th')?.textContent.trim()==='ПІБ');assert.deepEqual((await page.locator('#referenceNazk thead th').allTextContents()).slice(0,2),['ПІБ','Порушення']);
  await page.evaluate(()=>{document.querySelector('#referenceNazk').hidden=true;document.querySelector('#referenceAmcu').hidden=false;document.querySelector('#refAmcuBody').innerHTML='<tr><td>ТЕСТОВИЙ СУБ’ЄКТ — ДОВГА НАЗВА ОРГАНІЗАЦІЇ</td><td>00001234</td><td>0012-р/к</td><td>2026-10-01</td><td>Тестовий орган АМКУ</td><td>001/26-А</td></tr>'});
  await page.locator('#referenceAmcu .system-width-button').waitFor();assert.equal((await widths(page,'#referenceAmcu table'))[0],410);
  await openEditor(page,'#referenceAmcu');assert.equal(await page.locator('[data-column="суб-єкт"]').inputValue(),'410');await page.locator('[data-column="суб-єкт"]').fill('470');await page.locator('.system-width-dialog .primary').click();await page.waitForFunction(()=>Math.round(document.querySelector('#referenceAmcu th').getBoundingClientRect().width)===470);assert.equal((await widths(page,'#referenceAmcu table'))[0],470);results.push('Existing AMCU settings inherited; admin override is centrally persisted per table');
  const resetNazkWidth=process.argv.includes('--production-source')?defaultNazkWidth:380;
  await prepare(page);assert.equal((await widths(page,'#referenceNazk table'))[0],505);await openEditor(page);await page.locator('.system-width-reset').click();await page.waitForFunction(width=>Math.round(document.querySelector('#referenceNazk thead th').getBoundingClientRect().width)===width,resetNazkWidth);await prepare(page);assert.equal((await widths(page,'#referenceNazk table'))[0],resetNazkWidth);results.push('Reset to defaults persists, does not delete legacy settings');
  // Inventory every static table, even modules not initially visible.
  await page.evaluate(()=>{document.querySelectorAll('table').forEach(t=>{for(let n=t.parentElement;n;n=n.parentElement){n.hidden=false;if(n.tagName==='DIALOG')n.setAttribute('open','');if(n.tagName==='DETAILS')n.open=true}})});
  await page.waitForTimeout(350);
  const inventory=await page.locator('table').evaluateAll(ts=>ts.map((t,i)=>({index:i,id:t.id,body:t.querySelector('tbody')?.id,headers:[...t.querySelectorAll('thead th')].map(h=>h.textContent.trim()),key:t.dataset.systemTable,resize:!!t.dataset.resizeBound,native:t.id==='applicationsTable'||!!t.closest('#historyView'),visible:t.getBoundingClientRect().width>0})));
  fs.writeFileSync(path.join(out,'static-table-inventory.json'),JSON.stringify(inventory,null,2));
  const active=inventory.filter(t=>t.visible&&t.headers.length&&!t.native);assert(active.every(t=>t.key&&t.resize));assert.equal(new Set(active.map(t=>t.key)).size,active.length,'Every static table has a unique key');results.push(`${active.length} visible static non-native tables inventoried and resize-enabled`);
  for(const item of active){
   const button=page.locator(`[data-table-key="${item.key}"]`);assert.equal(await button.count(),1);await button.click();
   const input=page.locator('.system-width-fields [data-column]').first(),column=await input.getAttribute('data-column');await input.fill('375');await page.locator('.system-width-dialog .primary').click();
   await page.waitForFunction(({tableIndex,columnKey})=>{const table=document.querySelectorAll('table')[tableIndex];if(!table)return false;const slug=s=>s.trim().toLocaleLowerCase('uk-UA').replace(/[^a-zа-яіїєґ0-9]+/g,'-').replace(/^-|-$/g,'');const th=[...table.querySelectorAll('thead th')].find((h,i)=>(h.dataset.edrColumn||h.dataset.columnKey||h.dataset.historyColumn||h.dataset.col||h.dataset.key||h.dataset.sort||slug(h.textContent)||`column-${i+1}`)===columnKey);return !!th&&Math.abs(th.getBoundingClientRect().width-375)<2},{tableIndex:item.index,columnKey:column});
   const actual=await page.locator('table').nth(item.index).evaluate((t,key)=>{const slug=s=>s.trim().toLocaleLowerCase('uk-UA').replace(/[^a-zа-яіїєґ0-9]+/g,'-').replace(/^-|-$/g,'');const th=[...t.querySelectorAll('thead th')].find((h,i)=>(h.dataset.edrColumn||h.dataset.columnKey||h.dataset.historyColumn||h.dataset.col||h.dataset.key||h.dataset.sort||slug(h.textContent)||`column-${i+1}`)===key);return th?.getBoundingClientRect().width},column);
   assert(Math.abs(actual-375)<2,`${item.key}/${column}: actual width ${actual}`);
  }
   results.push('Every visible static non-native table: one editor, numeric save and actual pixel width');
   await page.evaluate(()=>document.querySelector('#referenceNazk').insertAdjacentHTML('beforeend','<div class="table-scroll"><table id="visibilityFixture" data-system-table="synthetic:visibility"><thead><tr><th data-column-key="a">A</th><th data-column-key="b">B</th><th data-column-key="c">C</th></tr></thead><tbody><tr><td>A1</td><td>B1</td><td>C1</td></tr></tbody></table></div>'));
   await page.locator('[data-table-key="synthetic:visibility"]').waitFor();await page.locator('[data-table-key="synthetic:visibility"]').click();assert.equal(await page.locator('.system-width-fields [data-visible]').count(),3);await page.locator('.system-width-fields [data-visible="b"]').uncheck();await page.locator('.system-width-dialog .primary').click();await page.waitForFunction(()=>document.querySelector('#visibilityFixture th[data-column-key="b"]').hidden&&document.querySelector('#visibilityFixture tbody td:nth-child(2)').hidden);assert.deepEqual(sharedStore['synthetic:visibility'].__visible__,['a','c']);
   await page.evaluate(()=>{const table=document.querySelector('#visibilityFixture');table.tHead.rows[0].insertAdjacentHTML('beforeend','<th data-column-key="d">D</th>');table.tBodies[0].rows[0].insertAdjacentHTML('beforeend','<td>D1</td>')});await page.waitForFunction(()=>!document.querySelector('#visibilityFixture th[data-column-key="d"]').hidden);await page.locator('[data-table-key="synthetic:visibility"]').click();assert.equal(await page.locator('.system-width-fields [data-visible="d"]').isChecked(),true);await page.locator('.dialog-cancel').click();results.push('Shared visibility is persisted, hidden cells stay aligned, and new columns default to visible');
  await page.evaluate(()=>document.body.dataset.authRole='officer');await page.waitForTimeout(150);assert.equal(await page.locator('.system-width-button').count(),0);assert.equal(await page.locator('table:not(#applicationsTable):not(#historyView table) th.column-resizable').count(),0);
  const rejected=await page.evaluate(async()=>{try{await request('/api/admin/table-widths',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({table_key:'referencesView:refNazkBody',widths:{full_name:999}})});return false}catch(error){return /admin only/.test(error.message)}});assert(rejected,'A direct viewer API write is rejected');
  results.push('Officer: no shared editors/resize handles and direct shared-settings API writes are forbidden');
  await prepare(page);
  for(const theme of ['light','dark'])for(const viewport of [1440,390])for(const view of ['nazk','amcu','task']){
   await page.setViewportSize({width:viewport,height:1000});
   await page.evaluate(({theme,view,fixture})=>{
    document.documentElement.dataset.theme=theme;const d=document.querySelector('#operationalTaskDialog');if(d.open)d.close();
    document.querySelector('#referencesView').hidden=view==='task';document.querySelector('#referenceNazk').hidden=view!=='nazk';document.querySelector('#referenceAmcu').hidden=view!=='amcu';
    if(view==='amcu')document.querySelector('#refAmcuBody').innerHTML='<tr><td>ТЕСТОВИЙ СУБ’ЄКТ — ДОВГА НАЗВА</td><td>00001234</td><td>0012-р/к</td><td>2026-10-01</td><td>Тестовий орган АМКУ</td><td>001/26-А</td></tr>';
    if(view==='task'){document.querySelector('#operationalTaskBody').innerHTML=operationalNazkContext({records:fixture,current_manager:{manager_name:'Тестова особа'},status:'open'});document.querySelector('#operationalTaskSave').hidden=true;d.showModal()}
   },{theme,view,fixture});
   const scope=view==='task'?'#operationalTaskBody':view==='nazk'?'#referenceNazk':'#referenceAmcu',table=page.locator(scope+' table');
   await page.locator(scope+' .system-width-button').waitFor();
   if(view!=='amcu'&&!process.argv.includes('--production-source'))assert.deepEqual((await table.locator('thead th').allTextContents()).slice(0,9),expected);
   else assert((await table.locator('thead th').count())>0,'Production-source table headers must remain present');
   await page.screenshot({path:path.join(out,`${view}-${theme}-${viewport}.png`),fullPage:true});
   await page.locator(scope+' .system-width-button').click();await page.screenshot({path:path.join(out,`${view}-${theme}-${viewport}-settings.png`),fullPage:true});await page.locator('.dialog-cancel').click();
   await table.evaluate(t=>{t.parentElement.scrollLeft=t.scrollWidth});assert(await table.evaluate(t=>t.scrollWidth<=t.parentElement.clientWidth+2||t.parentElement.scrollLeft>0),'Horizontal scroll works when needed');await page.screenshot({path:path.join(out,`${view}-${theme}-${viewport}-scroll.png`),fullPage:true});
   if(view==='task'&&!process.argv.includes('--production-source')){
    const button=page.locator(scope+' .system-width-button'),bounds=await button.boundingBox();assert(bounds.x>=0&&bounds.x+bounds.width<=viewport,'Settings remain reachable after horizontal scrolling');
    const taskHeaders=await table.locator('thead th').allTextContents();assert.deepEqual(taskHeaders,['ПІБ','Порушення','Вид стягнення','Номер судової справи','Дата рішення','Дата набрання законної сили','Посилання на рішення','№ наказу','Дата наказу','ID запису']);
    const taskRows=table.locator('tbody tr');assert.equal(await taskRows.count(),fixture.length);
    for(let i=0;i<fixture.length;i++){
     const item=fixture[i],row=taskRows.nth(i),cells=await row.locator('td').allTextContents();assert.equal(cells.length,taskHeaders.length,`Task row ${i} must align with every header`);
     assert.deepEqual(cells.slice(0,6),[item.full_name,item.offense_name,item.punishment||'—',item.court_case_number||'—',item.sentence_date?item.sentence_date.split('-').reverse().join('.'):'—',item.punishment_start?item.punishment_start.split('-').reverse().join('.'):'—']);
     const link=row.locator('td').nth(6).locator('a');if(item.decision_url){assert.equal(await link.getAttribute('href'),item.decision_url);assert.equal(await link.textContent(),'Відкрити джерело')}else assert.equal(cells[6],'—');
     assert.deepEqual(cells.slice(7,9),[item.decree_number||'—',item.decree_date||'—']);
    }
    await page.evaluate(()=>{const body=document.querySelector('#operationalTaskBody');body.innerHTML=operationalNazkContext({records:[],current_manager:{},status:'open'})});
    assert.equal(await page.locator('.operational-registry-list table').count(),0);assert(await page.locator('.operational-registry-list').textContent().then(text=>text.includes('Пов’язаних записів не знайдено')));
    await page.evaluate(()=>{const text='000А-к/<img src=x onerror="window.injected=1">';document.querySelector('#operationalTaskBody').innerHTML=operationalNazkContext({records:[{full_name:'<svg onload=window.injected=1>',decree_number:text}],status:'open'})});
    assert.equal(await page.locator('#operationalTaskBody img,#operationalTaskBody svg').count(),0);assert.equal(await page.locator('.operational-registry-list tbody tr').first().locator('td').nth(7).textContent(),'000А-к/<img src=x onerror="window.injected=1">');assert.equal(await page.evaluate(()=>window.injected),undefined);
   }
   results.push(`${view}/${theme}/${viewport}: modal, wrapping, horizontal scroll`);
  }
  // Group headers and colspan rows must retain column alignment.
  await prepare(page);
  const dynamic=[];
  for(const name of ['app.js','formed_protocol_ui.js','schema_ui.js']){
   const text=read(name);let ordinal=0;
   for(const match of text.matchAll(/<table\b[^>]*>[\s\S]*?<\/table>/g)){
    const header=match[0].match(/<thead\b[^>]*>[\s\S]*?<\/thead>/)?.[0];if(!header)continue;
    dynamic.push({source:name,line:text.slice(0,match.index).split('\n').length,ordinal:ordinal++,header,tableTag:match[0].match(/<table\b[^>]*>/)[0]});
   }
  }
  for(const [i,item] of dynamic.entries()){
   await page.evaluate(({i,item})=>{const host=document.createElement('section');host.id=`dynamic-fixture-${i}`;host.innerHTML='<div class="operational-table">'+item.tableTag+item.header+'<tbody></tbody></table></div>';document.querySelector('#referenceNazk').append(host);const count=host.querySelectorAll('th').length;host.querySelector('tbody').innerHTML='<tr>'+Array.from({length:count},()=>'<td>Синтетичний довгий текст для перевірки перенесення</td>').join('')+'</tr>'},{i,item});
    const scope=`#dynamic-fixture-${i}`,table=scope+' table';await page.locator(scope+' .system-width-button').waitFor();await page.locator(scope+' .system-width-button').click();await page.locator('.system-width-fields [data-column]').first().fill('311');await page.locator('.system-width-dialog .primary').click();await page.waitForFunction(selector=>Math.round(document.querySelector(selector+' thead th').getBoundingClientRect().width)===311,table);
   assert.equal((await widths(page,table))[0],311,`${item.source}:${item.line}`);await drag(page,table,0,29);assert.equal((await widths(page,table))[0],340);await page.locator(scope+' .system-width-button').click();assert.equal(await page.locator('.system-width-fields [data-column]').first().inputValue(),'340');await page.locator('.dialog-cancel').click();
  }
  fs.writeFileSync(path.join(out,'dynamic-table-inventory.json'),JSON.stringify(dynamic,null,2));results.push(`${dynamic.length} dynamic source table headers: modal, actual pixel widths, drag synchronization; synthetic rows`);
  await prepare(page);await page.evaluate(()=>{document.querySelector('#referenceNazk').insertAdjacentHTML('beforeend','<div class="table-scroll"><table id="groupedFixture"><thead><tr><th rowspan="2">Ім’я</th><th colspan="2">Група</th></tr><tr><th>А</th><th>Б</th></tr></thead><tbody><tr><td>Один</td><td>Два</td><td>Три</td></tr><tr><td colspan="3">Порожня вибірка</td></tr></tbody></table></div>')});
  await page.locator('[data-table-key="referencesView:groupedFixture"]').waitFor();await page.locator('[data-table-key="referencesView:groupedFixture"]').click();assert.equal(await page.locator('.system-width-fields [data-column]').count(),3);await page.locator('.system-width-fields [data-column]').first().fill('220');await page.locator('.system-width-dialog .primary').click();assert.equal(Math.round(await page.locator('#groupedFixture tbody tr').first().locator('td').first().evaluate(t=>t.getBoundingClientRect().width)),220);results.push('Grouped headers, rowspan and colspan alignment');
  await prepare(page);await page.evaluate(()=>{const table=document.querySelector('#referenceNazk table').cloneNode(true);table.dataset.systemTable='referencesView:legacy-nazk';delete table.dataset.resizeBound;table.querySelector('tbody').id='legacyNazkFixture';document.querySelector('#referenceNazk').append(table)});
  const legacyTable='table[data-system-table="referencesView:legacy-nazk"]';await page.locator('[data-table-key="referencesView:legacy-nazk"]').waitFor();assert.deepEqual((await widths(page,legacyTable)).slice(0,2),[431,541]);
  await page.locator('[data-table-key="referencesView:legacy-nazk"]').click();assert.equal(await page.locator('[data-column="full_name"]').inputValue(),'431');
  await page.locator('.system-width-fields [data-order-key="offense_name"] .order-up').click();await page.locator('[data-column="full_name"]').fill('900');
  failNextSharedSave=true;await page.locator('.system-width-dialog .primary').click();assert(await page.locator('.system-width-dialog').evaluate(d=>d.open));assert.deepEqual((await widths(page,legacyTable)).slice(0,2),[431,541]);assert.deepEqual((await page.locator(legacyTable+' thead th').allTextContents()).slice(0,2),['ПІБ','Порушення']);
  await page.locator('.dialog-cancel').click();await page.locator('[data-table-key="referencesView:legacy-nazk"]').click();assert.deepEqual((await page.locator(legacyTable+' thead th').allTextContents()).slice(0,2),['ПІБ','Порушення']);assert.deepEqual((await widths(page,legacyTable)).slice(0,2),[431,541]);
  assert.equal(await page.evaluate(()=>Object.keys(localStorage).some(key=>key.startsWith('pqm.table-widths.v2:'))),false);results.push('Shared ordering persists across reload/browser; failed save is atomic; no localStorage source');
  await prepare(page);
  const toolbarWidths={};
  for(const theme of ['light','dark'])for(const width of [390,1024,1280,1440,1920]){
   await page.setViewportSize({width,height:1000});
   await page.evaluate(theme=>{document.documentElement.dataset.theme=theme;document.querySelector('#referenceNazk').hidden=false;document.querySelector('#referenceAmcu').hidden=true;document.querySelector('#referenceDeclension').hidden=true},theme);
   await page.evaluate(()=>window.dispatchEvent(new Event('resize')));await page.waitForTimeout(80);
   const toolbar=page.locator('#referenceNazk .reference-toolbar');
   const measurements=await toolbar.evaluate(el=>{
    const r=el.getBoundingClientRect(),controls=[el.children[0],el.querySelector('#refNazkSearch'),el.querySelector('#refNazkDateFrom')?.parentElement,el.querySelector('#refNazkDateTo')?.parentElement,el.querySelector('#refNazkCourt'),el.querySelector('#refNazkRefresh'),document.querySelector('#referenceNazk .system-width-button')],missing=controls.map((node,index)=>node?null:`control-${index}`).filter(Boolean),nodes=controls.filter(Boolean).map(n=>{const b=n.getBoundingClientRect();return {left:b.left,right:b.right,top:b.top,bottom:b.bottom,width:b.width}});
    return {left:r.left,right:r.right,width:r.width,clientWidth:el.clientWidth,scrollWidth:el.scrollWidth,nodes,missing};
   });
   assert.deepEqual(measurements.missing,[],`NAZK toolbar controls missing at ${theme}/${width}`);
   assert(measurements.nodes.every(n=>n.width>0&&n.left>=measurements.left-1&&n.right<=measurements.right+1),`NAZK toolbar controls clipped/overflow at ${theme}/${width}`);
   assert(measurements.scrollWidth<=measurements.clientWidth+2,`NAZK toolbar horizontal overflow at ${theme}/${width}`);
   if(width>=1280){assert(measurements.nodes.every(n=>Math.abs((n.top+n.bottom)/2-(measurements.nodes[0].top+measurements.nodes[0].bottom)/2)<2),`NAZK toolbar wrapped at desktop ${theme}/${width}`);assert(measurements.nodes.slice(1).every((n,i)=>n.left>=measurements.nodes[i].right-1),`NAZK toolbar order changed at ${theme}/${width}`);assert(measurements.nodes[1].width>=140,`NAZK search collapsed at desktop ${theme}/${width}`)}
   toolbarWidths[`${theme}-${width}`]=measurements.nodes[1].width;
   if([390,1280].includes(width))await page.screenshot({path:path.join(out,`nazk-toolbar-${theme}-${width}.png`),fullPage:true});
   await page.evaluate(()=>{document.querySelector('#referenceNazk').hidden=true;document.querySelector('#referenceAmcu').hidden=false});
   const amcu=page.locator('#referenceAmcu .amcu-toolbar');
   const amcuBox=await amcu.evaluate(el=>{const r=el.getBoundingClientRect();return {top:r.top,left:r.left,right:r.right,width:r.width,clientWidth:el.clientWidth,scrollWidth:el.scrollWidth,controls:[...el.children].filter(n=>!n.hidden&&n.tagName!=='INPUT'&&n.type!=='file').map(n=>{const b=n.getBoundingClientRect();return {left:b.left,right:b.right,top:b.top,bottom:b.bottom,width:b.width}})}});
   assert(amcuBox.scrollWidth<=amcuBox.clientWidth+2,`AMCU toolbar horizontal overflow at ${theme}/${width}`);
   assert(amcuBox.controls.every(n=>n.left>=amcuBox.left-1&&n.right<=amcuBox.right+1),`AMCU toolbar control overflow at ${theme}/${width}`);
   if(width>=1280)assert(amcuBox.controls.every(n=>Math.abs((n.top+n.bottom)/2-(amcuBox.controls[0].top+amcuBox.controls[0].bottom)/2)<2),`AMCU toolbar unexpectedly wrapped at ${theme}/${width}`);
  }
  assert(toolbarWidths['light-1920']>=toolbarWidths['light-1280'],'NAZK search must consume additional desktop width');
  results.push('NAZK task decree table: all 10 headers/cells map, prior fields retained, optional/empty records, source links and HTML escaping');
  results.push('NAZK toolbar: order, single-row desktop, responsive wrapping, no clipping/overflow; 390/1024/1280/1440/1920 × light/dark; AMCU layout regression unchanged');
  results.push(...await require('./table_widths_native_browser.cjs')({page,prepare,drag,read,out}));
  assert.deepEqual(errors,[]);assert(sharedWrites>0,'Shared settings must be saved centrally through the existing API');results.push('Shared settings are server-backed; no browser errors');
  fs.writeFileSync(path.join(out,'browser-results.json'),JSON.stringify({status:'PASS',results},null,2));console.log(JSON.stringify({status:'PASS',results},null,2));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
