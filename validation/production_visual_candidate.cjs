/* Production-theme visual regression on real candidate HTML with synthetic, isolated rows. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {execFileSync}=require('node:child_process');
const {chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..'),OUT=process.env.PQM_VISUAL_EVIDENCE||path.join(ROOT,'evidence','production-visual-theme');
const BASE='6d5a31386f47dc5194b14c4d19cf99320691b631';
const read=name=>fs.readFileSync(path.join(ROOT,name),'utf8');
const baseFile=name=>execFileSync('git',['show',`${BASE}:${name}`],{cwd:ROOT,encoding:'utf8'});
const colors={
 lightOfficer:'rgb(237, 246, 232)',lightActiveBorder:'rgb(39, 118, 70)',darkOfficer:'rgb(23, 62, 56)',
 darkCategory:'rgb(28, 53, 81)',darkAdmit:'rgb(23, 62, 56)',darkReject:'rgb(72, 41, 50)',darkPending:'rgb(68, 59, 38)',
 edr:['rgb(48, 38, 63)','rgb(24, 58, 49)','rgb(68, 59, 38)','rgb(73, 48, 34)','rgb(71, 38, 48)','rgb(39, 56, 75)'],
 darkAuthority:'rgb(19, 40, 64)',darkExport:'rgb(25, 52, 81)',lightEdr:'rgb(246, 249, 253)',lightClarity:'rgb(247, 249, 252)'
};
const expectedEdr=['not_current','lt30','gt30','gt60','gt90','not_checked'];
async function makePage(browser,variant){
 const page=await browser.newPage({viewport:{width:1680,height:1050},deviceScaleFactor:1});
 page.on('pageerror',error=>{throw error});
 const theme=variant==='before'?baseFile('theme.css'):read('theme.css');
 const helper=variant==='before'?baseFile('ui_improvements.js'):read('ui_improvements.js');
 await page.route('**/*',route=>{
  const url=new URL(route.request().url());if(url.origin!=='http://pqm.visual.fixture')return route.abort();
  const file=path.join(ROOT,decodeURIComponent(url.pathname==='/'?'/index.html':url.pathname));
  if(!fs.existsSync(file))return route.fulfill({status:404,body:'fixture missing'});
  if(file.endsWith('theme.css'))return route.fulfill({body:theme,contentType:'text/css'});
  if(file.endsWith('ui_improvements.js'))return route.fulfill({body:helper,contentType:'application/javascript'});
  if(file.endsWith('.js')&&!file.endsWith('theme_ui.js'))return route.fulfill({body:'',contentType:'application/javascript'});
  const contentType=file.endsWith('.html')?'text/html':file.endsWith('.css')?'text/css':file.endsWith('.svg')?'image/svg+xml':'application/octet-stream';
  return route.fulfill({body:fs.readFileSync(file),contentType});
 });
 await page.goto('http://pqm.visual.fixture/');
 await page.evaluate(()=>{
  document.querySelector('#loginGate').hidden=true;document.querySelector('#applicationShell').hidden=false;
  window.visualShow=id=>document.querySelectorAll('main').forEach(main=>main.hidden=main.id!==id);
  const officers=['Дмитро САВВА','Тетяна ФЕДЧЕНКО','Олена ЄРЬОМІНА'];
  document.querySelector('#officerCards').innerHTML=officers.map((name,i)=>`<button class="officer-card${i===0?' active':''}" data-officer="${name}" type="button"><span>${PqmUi.compactOfficer(name)}</span><strong>${[162,93,67][i]}</strong></button>`).join('')+'<button class="officer-card unassigned" data-officer="Не визначено" type="button"><span>Не визначено</span><strong>8</strong></button>';
  document.querySelector('#applicationsTable thead').innerHTML='<tr><th class="sticky">Заявка</th><th>Статус</th></tr>';
  document.querySelector('#applicationsTable tbody').innerHTML='<tr class="application-review-completed"><td class="sticky">Завершена заявка</td><td>Перевірена</td></tr><tr><td class="sticky auto-filled">Автозаповнена</td><td>Очікує перевірки</td></tr>';
  const workNames=['Дмитро САВВА','Тетяна ФЕДЧЕНКО','Олена ЄРЬОМІНА'];
  document.querySelector('#queueProtocolOfficerCards').innerHTML=workNames.map(name=>`<button class="qualification-summary-officer"><span>${name}</span><strong>16</strong><small>у протоколі</small></button>`).join('');
  const cats=document.querySelector('#queueProtocolCategoryCards');cats.innerHTML='<button class="qualification-summary-officer qualification-summary-category"><span>Категорія тесту</span><strong>8</strong><small>категорія</small></button>';
  document.querySelector('#queuePublicationControl').innerHTML='<button data-publication-state="active"><span>Допущено</span><strong>48</strong></button><button data-publication-state="unsuccessful"><span>Відхилено</span><strong>7</strong></button><button data-publication-state="pending"><span>Очікує рішення</span><strong>17</strong></button>';
  const freshness=document.querySelectorAll('#edrMonitoringKpis button');freshness.forEach((button,i)=>{button.querySelector('strong').textContent=String([15,20,10,6,4,2][i]);if(i===2)button.classList.add('active')});
  document.querySelector('#requestAuthorityCards').innerHTML=['Професійні закупівлі','УСС','МЗУ'].map((name,i)=>`<button class="request-authority-card${i===0?' active':''}"><span>${name}</span><strong>${[21,14,9][i]}</strong></button>`).join('');
  document.querySelector('#frameworksBody').innerHTML='<tr><td>Відбір</td><td><a href="#" class="ghost">Завантажити реєстр</a></td></tr>';
  const selected=document.querySelector('#frameworksExportSelected');selected.hidden=false;selected.textContent='Експорт вибраних';
  document.querySelector('#supplierProfileBody').innerHTML='<section class="supplier-profile-section"><h3>Керівник та відомості з ЄДР</h3><div class="supplier-edr-actions"><a href="#">↗ Clarity Project</a></div><dl class="supplier-edr-metadata"><div><dt>Актуальність ЄДР</dt><dd>До 30 днів</dd></div><div><dt>Статус у реєстрі</dt><dd>Зареєстровано</dd></div><div><dt>Перевірка</dt><dd>Не перевірено</dd></div><div><dt>Статус Prozorro</dt><dd>Є у реєстрі</dd></div></dl></section>';
 });
 return page;
}
async function metrics(page,theme,view){
 return page.evaluate(({theme,view})=>{
  PqmThemeUI.apply(theme);const ids={registry:'applicationsView',work:'workQueueView',edr:'edrMonitoringView',appeals:'requestsView',frameworks:'frameworkAnalyticsView',supplier:'suppliersView'};visualShow(ids[view]);
  const supplierDialog=document.querySelector('#supplierProfileDialog');if(view==='supplier'&&!supplierDialog.open)supplierDialog.showModal();else if(view!=='supplier'&&supplierDialog.open)supplierDialog.close();
  const color=e=>getComputedStyle(e).backgroundColor,fg=e=>getComputedStyle(e).color,rect=e=>{const r=e.getBoundingClientRect();return [Math.round(r.width),Math.round(r.height)]};
  if(view==='registry')return {cards:[...document.querySelectorAll('#officerCards>.officer-card')].map(e=>({key:e.dataset.officer,label:e.querySelector('span').textContent,bg:color(e),fg:fg(e),labelFg:fg(e.querySelector('span')),strong:fg(e.querySelector('strong')),border:getComputedStyle(e).borderColor,left:getComputedStyle(e).borderLeftColor,shadow:getComputedStyle(e).boxShadow,rect:rect(e),labelStyle:{whiteSpace:getComputedStyle(e.querySelector('span')).whiteSpace,overflow:getComputedStyle(e.querySelector('span')).overflow,textOverflow:getComputedStyle(e.querySelector('span')).textOverflow}})),table:[...document.querySelectorAll('#applicationsTable th,#applicationsTable td')].map(e=>({tag:e.tagName,text:e.textContent,bg:color(e),fg:fg(e)}))};
  if(view==='work')return {officers:[...document.querySelectorAll('#queueProtocolOfficerCards button')].map(e=>({label:e.querySelector('span').textContent,bg:color(e),fg:fg(e.querySelector('span'))})),category:color(document.querySelector('#queueProtocolCategoryCards button')),states:[...document.querySelectorAll('#queuePublicationControl button')].map(e=>color(e))};
  if(view==='edr')return [...document.querySelectorAll('#edrMonitoringKpis button')].map(e=>({key:e.dataset.freshness,bg:color(e),fg:fg(e.querySelector('span')),active:e.classList.contains('active')}));
  if(view==='appeals')return [...document.querySelectorAll('#requestAuthorityCards button')].map(e=>({label:e.querySelector('span').textContent,bg:color(e),fg:fg(e.querySelector('span')),value:fg(e.querySelector('strong'))}));
  if(view==='frameworks')return [...document.querySelectorAll('#frameworksBody a.ghost,#frameworksExportSelected')].map(e=>({label:e.textContent.trim(),bg:color(e),fg:fg(e)}));
  return {cards:[...document.querySelectorAll('#supplierProfileBody .supplier-edr-metadata>div')].map(e=>color(e)),clarity:color(document.querySelector('#supplierProfileBody .supplier-edr-actions a')),clarityText:fg(document.querySelector('#supplierProfileBody .supplier-edr-actions a'))};
 },{theme,view});
}
(async()=>{
 fs.mkdirSync(OUT,{recursive:true});const browser=await chromium.launch({headless:true,...(process.env.PQM_TEST_BROWSER?{executablePath:process.env.PQM_TEST_BROWSER}:{})});const results=[];
 try{
  for(const variant of ['before','after']){
   const page=await makePage(browser,variant);
   for(const [view,theme] of [['registry','light'],['registry','dark'],['work','dark'],['edr','dark'],['appeals','dark'],['frameworks','dark'],['supplier','light'],['supplier','dark']]){
    const result=await metrics(page,theme,view);assert.equal(await page.locator('.prod-brand-initials').getAttribute('src'),`/assets/pqm-brand-mark-prod${theme==='dark'?'-dark':''}.svg`);results.push({variant,view,theme,result});
    if(view==='registry'){
     if(variant==='after'){
      assert.deepEqual(result.cards.map(x=>x.label),['Дмитро САВВА','Тетяна ФЕДЧЕНКО','Олена ЄРЬОМІНА','Не визначено']);
      assert(result.cards.every(x=>x.labelStyle.whiteSpace==='normal'&&x.labelStyle.overflow==='visible'&&x.labelStyle.textOverflow==='clip'));
      if(theme==='light')assert(result.cards.every(x=>x.bg===colors.lightOfficer&&x.fg==='rgb(23, 43, 65)'&&x.labelFg==='rgb(82, 97, 115)'&&x.strong==='rgb(23, 43, 65)'));
      else assert(result.cards.every(x=>x.bg===colors.darkOfficer));
      if(theme==='dark')assert(result.table.every(x=>{const c=x.bg.match(/\d+/g).map(Number);return Math.max(...c)<100}),`dark registry contains light cell/header: ${JSON.stringify(result.table)}`);
     }
    }
    if(view==='work'&&variant==='after'){
     assert(result.officers.every(x=>x.bg===colors.darkOfficer));assert.equal(result.category,colors.darkCategory);
     assert.deepEqual(result.states,[colors.darkAdmit,colors.darkReject,colors.darkPending]);
    }
    if(view==='edr'&&variant==='after'){assert.deepEqual(result.map(x=>x.key),expectedEdr);assert.deepEqual(result.map(x=>x.bg),colors.edr);}
    if(view==='appeals'&&variant==='after')assert(result.every(x=>x.fg!=='rgb(255, 255, 255)'&&x.value!=='rgb(255, 255, 255)'||x.bg==='rgb(33, 84, 135)'));
    if(view==='frameworks'&&variant==='after')assert(result.every(x=>x.bg===colors.darkExport));
    if(view==='supplier'){
     if(theme==='light')assert(result.cards.every(x=>x===colors.lightEdr)&&result.clarity===colors.lightClarity);
     else assert(result.cards.every(x=>x===colors.darkAuthority)&&result.clarity==='rgb(25, 52, 81)');
    }
    if(view==='registry'&&theme==='light')await page.screenshot({path:path.join(OUT,`${variant}-registry-light.png`),fullPage:true});
    if(view==='registry'&&theme==='dark')await page.screenshot({path:path.join(OUT,`${variant}-registry-dark.png`),fullPage:true});
    if(variant==='after'&&view!=='registry')await page.screenshot({path:path.join(OUT,`after-${view}-${theme}.png`),fullPage:true});
   }
   await page.close();
  }
  fs.writeFileSync(path.join(OUT,'RESULTS.json'),JSON.stringify(results,null,2));
  console.log(JSON.stringify({result:'PASS',variants:2,cases:results.length,baseline:BASE,screenshots:OUT,edrStates:expectedEdr,productionSupplierLightStylesUnchanged:true},null,2));
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
