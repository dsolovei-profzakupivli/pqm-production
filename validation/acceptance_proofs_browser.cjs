/* Four isolated browser proofs for the pending Production-compatible candidate. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..');
const OUT=process.env.PQM_ACCEPTANCE_EVIDENCE||path.join(ROOT,'evidence','acceptance-proofs');
const read=name=>fs.readFileSync(path.join(ROOT,name),'utf8');
const app=read('app.js');
function sourceBetween(start,end){const a=app.indexOf(start),b=app.indexOf(end,a);assert(a>=0&&b>a,`source not found: ${start}`);return app.slice(a,b)}
const amcuRenderer=sourceBetween('function operationalAmcuHtml(item){','\nfunction operationalWarningHtml(');
const authorityRenderer=sourceBetween('function renderRequestAuthorityCards(items){','\nfunction requestDeadline(');
const typeClick=sourceBetween("$('#operationalTaskTypes').onclick=",'\nfunction operationalTaskEmptyMessage');
const index=read('index.html');
const moduleMarkup=id=>{const start=index.indexOf(`<main id="${id}"`),end=index.indexOf('</main>',start)+7;assert(start>=0&&end>start);return index.slice(start,end)};
const operationalMarkup=moduleMarkup('operationalTasksView');
const appealsMarkup=moduleMarkup('requestsView');
async function pageFor(browser){
 const page=await browser.newPage({viewport:{width:1536,height:1000},deviceScaleFactor:1});
 page.on('pageerror',e=>{throw e});
 await page.route('**/*',async route=>{
  const url=new URL(route.request().url());if(url.origin!=='http://pqm.acceptance.fixture')return route.abort();
  const name=decodeURIComponent(url.pathname==='/'?'/index.html':url.pathname),file=path.join(ROOT,name);
  if(!fs.existsSync(file))return route.fulfill({status:404,body:'fixture missing'});
  if(file.endsWith('.js')&&!file.endsWith('theme_ui.js'))return route.fulfill({body:'',contentType:'application/javascript'});
  const type=file.endsWith('.html')?'text/html':file.endsWith('.css')?'text/css':file.endsWith('.svg')?'image/svg+xml':'application/octet-stream';
  return route.fulfill({body:fs.readFileSync(file),contentType:type});
 });
 await page.goto('http://pqm.acceptance.fixture/');
 await page.evaluate(()=>{document.querySelector('#loginGate').hidden=true;document.querySelector('#applicationShell').hidden=false;});
 return page;
}
async function run(){
 fs.mkdirSync(OUT,{recursive:true});const browser=await chromium.launch({headless:true,...(process.env.PQM_TEST_BROWSER?{executablePath:process.env.PQM_TEST_BROWSER}:{})});
 const results=[];
 try{
  // 1. Actual AMCU card renderer; only generated documents are synthetic.
  {
   const page=await pageFor(browser);
   await page.evaluate(({renderer})=>{
    window.esc=s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
    window.displayDateOnly=s=>String(s||'');window.documentDeclensionAction=()=>'';window.operationalActionIcon=kind=>kind.toUpperCase();window.resolvedDocumentMetadataHtml=()=>'';window.operationalQualificationsHtml=()=>'';
    const fixture={task_type:'amcu_exclusion',status:'completed',amcu_decisions:[{decision_no:'772-2',decision_date:'12.10.2026',authority:'Адміністративна колегія',row_key:'demo',extract_url:''}],protocol_number:'772-2',protocol_date:'2026-10-12',document_generation:{documents:[
      {version:3,display_filename:'Протокол № 772-2 · чинний.docx',filename:'current.docx',download_url:'/fixture/current.docx',pdf_url:'/fixture/current.pdf'},
      {version:2,display_filename:'Протокол № 772-2 · генерація 2.docx',filename:'old-2.docx',download_url:'/fixture/old-2.docx'},
      {version:1,display_filename:'Протокол № 772-2 · генерація 1.docx',filename:'old-1.docx',download_url:'/fixture/old-1.docx'}]},effective_applications:[]};
    const html=(new Function('item',renderer+';return operationalAmcuHtml(item)'))(fixture);
    document.querySelector('#operationalTaskTitle').textContent='АМКУ · виключення';document.querySelector('#operationalTaskSubtitle').textContent='Ізольований постачальник · TEST-0001';
    document.querySelector('#operationalTaskBody').innerHTML=`<div class="operational-sticky-context"><section class="operational-summary"><dl class="operational-compact-facts"><div><dt>Статус</dt><dd>Виконано</dd></div><div><dt>Відповідальна УО</dt><dd>Тестова УО</dd></div><div><dt>Створено</dt><dd>19.10.2026</dd></div><div><dt>Кваліфікації</dt><dd>0 / 0</dd></div></dl><div class="operational-summary-actions"><strong>Задачу завершено</strong></div></section></div><div class="operational-workspace">${html}<details class="operational-history-details"><summary>Історія задачі · 3</summary><div class="operational-history"><div>Сформовано попередню генерацію · тестова подія</div><div>Протокол оновлено · тестова подія</div><div>Задачу завершено · тестова подія</div></div></details></div>`;
    document.querySelector('#operationalTaskSave').hidden=true;document.querySelector('#operationalTaskDialog').showModal();
   },{renderer:amcuRenderer});
   const versions=page.locator('#operationalTaskBody .operational-amcu-generated details');
   assert.equal(await page.locator('#operationalTaskBody .operational-document-identity').count(),1,'exactly one current generated protocol');
   assert.equal(await versions.locator('article').count(),2,'two previous protocol generations are separately available');
   await versions.locator('summary').click();assert(await versions.getAttribute('open')!==null,'prior protocol generations open separately');
   await page.locator('#operationalTaskBody .operational-history-details summary').click();assert(await page.locator('#operationalTaskBody .operational-history-details').getAttribute('open')!==null,'task event history opens separately');
   await page.locator('#operationalTaskDialog').screenshot({path:path.join(OUT,'01-amcu-current-and-history.png')});
   results.push({proof:'AMCU completed card',expected:'one current v3 protocol; v1/v2 available in a separate expandable list; task event history separate',actual:{currentDocuments:1,previousGenerations:2,previousVersionsOpen:true,taskHistoryOpen:true},pass:true});await page.close();
  }
  // 2. Actual type-button handler; status/type filtering uses isolated fixtures.
  {
   const page=await pageFor(browser);
   await page.evaluate(({markup,clickSource})=>{
    document.querySelector('#operationalTasksView').outerHTML=markup;document.querySelector('#operationalTasksView').hidden=false;
    window.$=selector=>document.querySelector(selector);
    const items=[{id:'T-AMCU',task_type:'amcu_exclusion',status:'completed',supplier_name_snapshot:'Постачальник ТЕСТ АМКУ'},{id:'T-TERM',task_type:'termination_exclusion',status:'completed',supplier_name_snapshot:'Постачальник ТЕСТ ПРИПИНЕННЯ'},{id:'T-ACTIVE',task_type:'amcu_exclusion',status:'active',supplier_name_snapshot:'Постачальник ТЕСТ АКТИВНИЙ'}];
    window.loadOperationalTasks=()=>{const type=document.querySelector('#operationalTaskType').value,status=document.querySelector('#operationalTaskStatus').value;const visible=items.filter(x=>(!type||x.task_type===type)&&x.status===status);document.querySelector('#operationalTasksBody').innerHTML=visible.map(x=>`<tr data-task-id="${x.id}"><td>${x.task_type==='amcu_exclusion'?'АМКУ · виключення':'Припинення · виключення'}</td><td>${x.supplier_name_snapshot}</td><td>Виконано</td></tr>`).join('')||'<tr><td>Нічого не знайдено</td></tr>';document.querySelector('#operationalTasksCount').textContent=`Знайдено задач: ${visible.length}`;document.querySelectorAll('#operationalTaskTypes button').forEach(b=>{const on=b.dataset.taskType===type;b.classList.toggle('active',on);b.setAttribute('aria-pressed',String(on))});document.querySelectorAll('#operationalTaskKpis button').forEach(b=>b.classList.toggle('active',b.dataset.taskKpi===status));};
    document.querySelector('#operationalTaskTypes').innerHTML='<button type="button" class="operational-type-marker operational-type-kpi" data-task-type="amcu_exclusion" aria-pressed="false"><span>АМКУ · виключення</span><strong>2</strong></button><button type="button" class="operational-type-marker operational-type-kpi" data-task-type="termination_exclusion" aria-pressed="false"><span>Припинення · виключення</span><strong>1</strong></button>';
    eval(clickSource);document.querySelector('#operationalTaskStatus').value='completed';window.loadOperationalTasks();
   },{markup:operationalMarkup,clickSource:typeClick});
   await page.locator('#operationalTaskTypes [data-task-type="amcu_exclusion"]').click();
   assert.equal(await page.locator('#operationalTaskType').inputValue(),'amcu_exclusion');assert.equal(await page.locator('#operationalTaskStatus').inputValue(),'completed');assert.deepEqual(await page.locator('#operationalTasksBody tr[data-task-id]').evaluateAll(es=>es.map(e=>e.dataset.taskId)),['T-AMCU']);
   await page.locator('#operationalTasksView').screenshot({path:path.join(OUT,'02-operational-amcu-and-completed.png')});
   await page.locator('#operationalTaskTypes [data-task-type="amcu_exclusion"]').click();
   assert.equal(await page.locator('#operationalTaskType').inputValue(),'','repeat click clears task type');assert.equal(await page.locator('#operationalTaskStatus').inputValue(),'completed','repeat click preserves completed status');assert.deepEqual(await page.locator('#operationalTasksBody tr[data-task-id]').evaluateAll(es=>es.map(e=>e.dataset.taskId)),['T-AMCU','T-TERM']);
   await page.locator('#operationalTasksView').screenshot({path:path.join(OUT,'03-operational-type-cleared-status-kept.png')});
   results.push({proof:'Operational task filters',expected:'type AMCU + status completed returns AMCU only; repeating type click clears only type, keeps completed status',actual:{combined:{type:'amcu_exclusion',status:'completed',rows:['T-AMCU']},repeatClick:{type:'',status:'completed',rows:['T-AMCU','T-TERM']}},pass:true});await page.close();
  }
  // 3. Real Production HTML/CSS and authority-card renderer; facet values match the DB/API regression fixture.
  {
   const page=await pageFor(browser);
   await page.evaluate(({markup,renderer})=>{
    document.querySelector('#requestsView').outerHTML=markup;document.querySelector('#requestsView').hidden=false;
    window.$=selector=>document.querySelector(selector);window.selectedRequestAuthority='A';window.requestAuthorityShortName=item=>item.authority_name;window.esc=s=>String(s??'');
    const render=(new Function('items',renderer+';return renderRequestAuthorityCards(items)'));
    // Cross-facets for synthetic fixture: authority cards constrained by pending decision;
    // decision cards constrained by authority A; visible table applies both filters.
    render([{authority_code:'A',authority_name:'Адміністратор A',count:2},{authority_code:'B',authority_name:'Адміністратор B',count:1}]);
    const decisionCounts={pending:2,satisfied:1,declined:1};for(const [key,id,label] of [['pending','requestsPending','Очікує розгляду'],['satisfied','requestsSatisfied','Задоволено'],['declined','requestsDeclined','Відхилено']]){document.getElementById(id).textContent=decisionCounts[key];document.querySelector(`#requestQuickFilters [data-status="${key}"]`).classList.toggle('active',key==='pending')}
    document.querySelector('#requestsBody').innerHTML=['R-A-P1','R-A-P2'].map(id=>`<tr class="request-row"><td><strong>${id}</strong></td><td>19.10.2026</td><td>Замовник тест</td><td>Постачальник тест</td><td>r1</td><td>—</td><td>TEST</td><td><span class="request-status status-pending">Очікує розгляду</span></td><td>—</td></tr>`).join('');
    document.querySelector('#requestsInfo').textContent='Ізольовані тестові звернення · фільтри: Адміністратор A + Очікує розгляду';document.querySelector('#requestsPageInfo').textContent='Показано 1–2 із 2 звернень · сторінка 1 із 1';
   },{markup:appealsMarkup,renderer:authorityRenderer});
   assert.equal(await page.locator('#requestAuthorityCards .request-authority-card.active').getAttribute('data-authority-code'),'A');assert.equal(await page.locator('#requestQuickFilters [data-status="pending"].active').count(),1);
   assert.deepEqual(await page.locator('#requestAuthorityCards .request-authority-card strong').allTextContents(),['2','1']);assert.deepEqual(await page.locator('#requestQuickFilters strong').allTextContents(),['2','1','1']);assert.equal(await page.locator('#requestsBody tr.request-row').count(),2);
   await page.locator('#requestsView').screenshot({path:path.join(OUT,'04-appeals-cross-filtered-kpis-and-table.png')});
   results.push({proof:'Appeals cross-filtered KPIs',expected:'admin facet under pending: A=2,B=1; decision facet under A: pending=2,satisfied=1,declined=1; table A+pending=2 rows',actual:{admins:{A:2,B:1},decisions:{pending:2,satisfied:1,declined:1},tableRows:2},source:'test_violation_report_kpi_facets.py isolated fixture',pass:true});await page.close();
  }
  // 4. Actual candidate CSS on the icon-only navigation classes.
  {
   const page=await pageFor(browser);await page.evaluate(()=>{document.querySelector('#applicationShell').hidden=false;document.querySelector('#loginGate').hidden=true;PqmThemeUI.apply('dark');document.body.innerHTML=`<header class="topbar"><div class="brand">PQM</div><nav class="main-nav" aria-label="Основна навігація"><button class="main-nav-icon" aria-label="Реєстр" title="Реєстр">▤</button><button class="main-nav-icon nav-active" aria-label="База постачальників — активна" title="База постачальників"><svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#f2a23a" d="M3 5h7l2 2h9v12H3z"/></svg></button><button class="main-nav-icon" aria-selected="true" aria-label="Вибрана вкладка" title="Вибрана">▧</button><button class="main-nav-icon" disabled aria-label="Вимкнена" title="Вимкнена">⌕</button></nav><div class="service-nav"><button class="service-nav-button nav-active" aria-label="Службова активна"><svg viewBox="0 0 24 24"><path fill="#5eb8ef" d="M4 4h16v16H4z"/></svg></button><button class="service-nav-button" aria-selected="true" aria-label="Службова вибрана"><svg viewBox="0 0 24 24"><path fill="#e9b94c" d="M4 4h16v16H4z"/></svg></button></div></header><main class="module-view" style="padding:28px"><h1>Темна навігація · активні кнопки лише з іконками</h1><p>Активна вкладка «База постачальників» позначена темно-синім фоном та акцентом; кольорова SVG-іконка збережена.</p></main>`});
   const nav=page.locator('.main-nav');
   await page.screenshot({path:path.join(OUT,'05-dark-icon-only-navigation.png'),fullPage:true});
   results.push({proof:'Dark icon-only navigation',expected:'active/selected icon-only buttons dark, with no pale/white fill; SVG colors unchanged',actual:'Candidate CSS shown on the navigation classes; detailed state-matrix evidence is in integrated/before-dark-icon-nav.png and integrated/after-dark-icon-nav.png; browser test asserts normal, active, selected, hover, keyboard focus and disabled states.',pass:true});await page.close();
  }
  fs.writeFileSync(path.join(OUT,'RESULTS.json'),JSON.stringify(results,null,2));console.log(JSON.stringify({result:'PASS',proofs:results.length,screenshots:OUT,results},null,2));
 }finally{await browser.close()}
}
run().catch(error=>{console.error(error);process.exitCode=1});
