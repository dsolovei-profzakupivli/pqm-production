/* Actual header/profile functions, Chromium, isolated in-memory profile adapter. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('playwright'),ROOT=path.resolve(__dirname,'..');
const OUT=process.env.PQM_UI_EVIDENCE_DIR||fs.mkdtempSync(path.join(require('node:os').tmpdir(),'pqm-header-'));
const read=name=>fs.readFileSync(path.join(ROOT,name),'utf8');
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.PQM_TEST_BROWSER?{executablePath:process.env.PQM_TEST_BROWSER}:{})});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
 page.on('pageerror',error=>errors.push(String(error)));
 await page.route('**/*',route=>route.request().url()==='https://pqm-fixture.invalid/'?route.fulfill({contentType:'text/html',body:read('index.html').replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,'')}):route.abort());
 try{
  await page.goto('https://pqm-fixture.invalid/');
  for(const file of ['styles.css','filters.css','modules.css','schema_ui.css','ui_improvements.css','sandbox_theme.css','ui_final.css','ui_tz2.css'])await page.addStyleTag({content:read(file)});
  await page.addScriptTag({content:read('ui_improvements.js')});
  await page.evaluate(()=>PqmUi.formatActionButtons(document));
  assert.equal(await page.locator('#historyReset').textContent(),'×');
  for(const id of ['queueReset','clearFiltersBtn','supplierRegistryReset','edrMonitoringReset','adminFrameworkReset']){
   assert.equal(await page.locator('#'+id).textContent(),'×');assert.equal(await page.locator('#'+id).getAttribute('title'),'Скинути всі фільтри');
  }
  for(const id of ['resetBtn','supplierRegistryRefresh','frameworksRefresh','requestsRefresh']){
   assert.equal(await page.locator('#'+id).textContent(),'↻ Prozorro');assert.equal(await page.locator('#'+id).getAttribute('title'),'Оновити дані з Prozorro');
  }
  await page.evaluate(()=>{
   const button=document.querySelector('#requestsRefresh'),handler=()=>{throw Error('Sync must not run')};button.onclick=handler;button.disabled=true;button.textContent='Оновлення…';button.title='Оновлення вже триває';
   PqmUi.formatActionButtons(document);
   if(button.onclick!==handler||!button.disabled||button.textContent!=='Оновлення…'||button.title!=='Оновлення вже триває')throw Error('Running state changed');
   button.textContent='Оновити з Prozorro';button.title='';PqmUi.formatActionButtons(document);
   if(button.textContent!=='↻ Prozorro'||!button.disabled)throw Error('Restored idle label changed disabled');
  });
  await page.evaluate(()=>{
   window.$=s=>document.querySelector(s);window.$$=s=>[...document.querySelectorAll(s)];
   $('#loginGate').hidden=true;$('#applicationShell').hidden=false;document.body.dataset.authRole='officer';
   document.querySelectorAll('main').forEach(n=>n.hidden=n.id!=='applicationsView');
   window.API='/api';window.currentMe={role:'officer'};window.activeKey='fixture-active-profile';
   window.activeProfileId='personal';window.columns=[];window.profiles=[];
   window.profilesGeneration=0;window.profileLayoutGeneration=0;window.applicationsRegistryInitialized=false;window.profilesMetadataReady=false;
   window.multiSort=[];window.statsSignature='';window.statsGeneration=0;window.officerFilter='';window.page=1;
   window.defaultKpis=()=>['applications'];window.applyProfileSort=()=>{};
   window.formatOfficerName=s=>s;window.toast=()=>{};
   window.esc=s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
   window.currentFilterParams=()=>({search:''});window.loadRows=()=>{};
   window.people=['Тетяна ФЕДЧЕНКО','Дмитро САВВА','Олена ЄРЬОМІНА'];
   window.selected=['officers','applications','decision_yes','decision_no','decision_undefined'];
   window.saved={personal:{id:'personal',name:'Мій профіль',is_system:false,columns:[],kpis:[...selected],sorts:[]},other:{id:'other',name:'Інший профіль',is_system:false,columns:[],kpis:['suppliers'],sorts:[]}};
   window.apiOfficers=people.map((officer,index)=>({officer,applications:index?72:123456789}));window.writes=[];
   window.request=async(url,options={})=>{
    if(url==='/api/application-profiles')return{items:structuredClone(Object.values(saved))};
    if(url.startsWith('/api/application-profiles/')&&options.method==='PATCH'){const id=decodeURIComponent(url.split('/').at(-1)),payload=JSON.parse(options.body);Object.assign(saved[id],structuredClone(payload));writes.push({id,payload});return{saved:true}}
    if(url.startsWith('/api/stats?'))return{applications:72,suppliers:50,decision_yes:27,decision_no:1,decision_undefined:44,officers:structuredClone(apiOfficers)};
    throw Error('Unexpected endpoint '+url);
   };
  });
  const app=read('app.js'),line=name=>app.split('\n').find(s=>s.startsWith(name));
  const visibility=app.slice(app.indexOf('function applyKpiVisibility()'),app.indexOf('async function loadSearchFields()',app.indexOf('function applyKpiVisibility()')));
  await page.addScriptTag({content:[line('const kpiDefinitions='),line('function profile()'),line('function saveProfiles()'),line('function normalizeProfiles()'),visibility,line('function renderProfiles()'),line('async function loadProfiles()'),line('let profileSaveTimer;'),line('function cardsDialog()'),line('async function loadStatsData()')].join('\n')});
  await page.addScriptTag({content:app.slice(app.indexOf('const decisionKpiValues='),app.indexOf("$('#applicationCategoryFilter').onchange=",app.indexOf('const decisionKpiValues=')))});
  await page.evaluate(async()=>{await loadProfiles();await loadStatsData();applyKpiVisibility()});
  assert.equal(await page.locator('[data-officer="Дмитро САВВА"] span').textContent(),'Дмитро САВВА');
  assert.equal(await page.locator('[data-officer="Дмитро САВВА"]').getAttribute('title'),'Дмитро САВВА');
  for(const dark of [false,true])for(const width of [1920,1440,1280,1024,390]){
   await page.setViewportSize({width,height:1000});
   await page.evaluate(dark=>{if(dark)document.documentElement.dataset.pqmEnvironment='sandbox';else delete document.documentElement.dataset.pqmEnvironment;applyKpiVisibility()},dark);
   await page.waitForTimeout(60);
   const result=await page.evaluate(()=>{
    const region=$('.heading-metrics'),visible=[...region.querySelectorAll('.kpi-card,.officer-card')].filter(n=>!n.hidden&&!n.closest('[hidden]'));
    const rect=n=>{const r=n.getBoundingClientRect();return{x:r.x,y:r.y,w:r.width,h:r.height,right:r.right,bottom:r.bottom}};
    return {cards:visible.map(n=>({key:n.dataset.kpiCard||(n.classList.contains('officer-card')?'officers':''),...rect(n),strong:rect(n.querySelector('strong')),bg:getComputedStyle(n).backgroundColor,before:getComputedStyle(n,':before').backgroundColor})),region:rect(region),actions:rect($('.heading-actions')),rows:[...$$('.heading-action-row')].map(n=>[...n.children].map(rect)),scrollHeight:region.scrollHeight,clientHeight:region.clientHeight};
   });
   assert.equal(result.cards.length,7);assert(result.cards.every(c=>c.h===54),'KPI height changed');
   assert(Math.max(...result.cards.map(c=>c.y))-Math.min(...result.cards.map(c=>c.y))<1,'KPI wrapped');
   assert(result.cards.every(c=>c.strong.right<=c.right+1),'Number clipped');
   assert(result.scrollHeight<=result.clientHeight+1,'Vertical KPI overflow');
   assert.equal(result.actions.h,54);assert(result.rows.every(row=>row.length===3&&row.every(r=>r.h===25)));
   assert(result.rows.every(row=>Math.max(...row.map(r=>r.y))-Math.min(...row.map(r=>r.y))<1),'Button row wrapped');
   assert(new Set(result.rows.flat().map(r=>r.w)).size>1,'Buttons forced equal width');
   for(const c of result.cards.filter(c=>c.key==='officers')){const rgb=c.bg.match(/\d+/g).map(Number);assert(rgb[1]>rgb[0]&&rgb[1]>rgb[2],'Officer background not green');}
   const officerWidth=Math.min(...result.cards.filter(c=>c.key==='officers').map(c=>c.w));
   assert(result.cards.filter(c=>['decision_yes','decision_no','decision_undefined'].includes(c.key)).every(c=>c.w<officerWidth),'Decision KPI not compact');
   if(width>=1366){assert(result.region.right<=result.actions.x+1,'KPI overlaps actions');assert(Math.abs(result.region.y+result.region.h/2-result.actions.y-result.actions.h/2)<2,'Header not centered');}
   if(width===1440||width===390)await page.locator('#applicationsView .page-heading').screenshot({path:path.join(OUT,`header-${dark?'dark':'light'}-${width}.png`)});
  }
  // Existing profile group persists; concrete officers remain dynamic filters.
  await page.evaluate(()=>{profile().kpis=['decision_no','officers','applications','suppliers'];normalizeProfiles();applyKpiVisibility();persistProfileLayout()});
  await page.waitForTimeout(320);
  assert.deepEqual(await page.evaluate(()=>saved.personal.kpis),['decision_no','officers','applications','suppliers']);
  assert.deepEqual(await page.evaluate(()=>saved.other.kpis),['suppliers']);
  for(let i=0;i<2;i++){
   await page.evaluate(async()=>{profiles=[];applicationsRegistryInitialized=false;await loadProfiles();statsSignature='';await loadStatsData();applyKpiVisibility()});
   assert.deepEqual(await page.evaluate(()=>profile().kpis),['decision_no','officers','applications','suppliers']);
  }
  await page.setViewportSize({width:1440,height:1000});
  const order=await page.evaluate(()=>[...document.querySelectorAll('.heading-metrics .kpi-card,.heading-metrics .officer-card')].filter(n=>!n.hidden&&!n.closest('[hidden]')).sort((a,b)=>a.getBoundingClientRect().x-b.getBoundingClientRect().x).map(n=>n.dataset.kpiCard||(n.classList.contains('officer-card')?'officers':'')));
  assert.deepEqual(order,['decision_no','officers','officers','officers','applications','suppliers']);
  for(const [key,value]of [['decision_yes','admit'],['decision_no','reject'],['decision_undefined','__empty__']]){
   await page.evaluate(key=>{profile().kpis=[key];applyKpiVisibility()},key);
   await page.locator(`[data-kpi-card="${key}"]`).click();
   assert.equal(await page.locator('#protocolDecisionFilter').inputValue(),value);
   await page.locator(`[data-kpi-card="${key}"]`).press('Enter');
   assert.equal(await page.locator('#protocolDecisionFilter').inputValue(),'');
  }
  await page.evaluate(()=>{profile().kpis=['decision_no','officers','applications','suppliers'];applyKpiVisibility()});
  await page.locator('[data-officer="Дмитро САВВА"]').click();
  assert.equal(await page.evaluate(()=>officerFilter),'Дмитро САВВА');
  await page.locator('[data-officer="Дмитро САВВА"]').click();
  assert.equal(await page.evaluate(()=>officerFilter),'');
  await page.evaluate(async()=>{apiOfficers=[{officer:'Інша УО',applications:8}];statsSignature='';await loadStatsData()});
  assert.equal(await page.locator('#officerCards .officer-card').count(),1);
  assert.equal(await page.locator('#officerCards .officer-card').getAttribute('data-officer'),'Інша УО');
  assert.equal(await page.locator('#officerCards strong').textContent(),'8');
  await page.evaluate(()=>{cardsDialog()});
  assert.equal(await page.locator('#cardsList [data-key^="officer:"]').count(),0);
  assert(await page.locator('#cardsList [data-key="officers"] input').isChecked());
  await page.locator('#cardsList [data-key="officers"] input').uncheck();await page.waitForTimeout(320);
  assert(!(await page.evaluate(()=>saved.personal.kpis)).includes('officers'));
  assert(await page.locator('#officerCards').evaluate(n=>n.hidden));
  await page.evaluate(()=>{$('#cardsDialog').close();profile().kpis=[];normalizeProfiles();applyKpiVisibility()});
  assert.deepEqual(await page.evaluate(()=>profile().kpis),[],'Deselected cards forced back');
  // Overflow only scrolls KPI, never the two action rows.
  for(const width of [1920,1440,1280,1024,390]){
   await page.setViewportSize({width,height:1000});
   await page.evaluate(async()=>{apiOfficers=Array.from({length:24},(_,i)=>({officer:`Тестова УО ${i}`,applications:123456789}));profile().kpis=kpiDefinitions.map(([k])=>k);applyKpiVisibility();statsSignature='';await loadStatsData()});
   const scroll=await page.evaluate(()=>{const n=$('.heading-metrics'),actions=$('.heading-actions'),before=actions.getBoundingClientRect().x;n.scrollLeft=n.scrollWidth;n.scrollTop=10;return{x:n.scrollLeft,y:n.scrollTop,before,after:actions.getBoundingClientRect().x,sh:n.scrollHeight,ch:n.clientHeight}});
   assert(scroll.x>0&&scroll.y===0&&scroll.sh<=scroll.ch+1,JSON.stringify({width,scroll}));assert.equal(scroll.before,scroll.after);
   await page.evaluate(()=>{profile().kpis=['applications','decision_yes'];applyKpiVisibility()});
   if(width>=1366)assert(await page.locator('.heading-metrics').evaluate(n=>n.scrollWidth<=n.clientWidth),'Unnecessary scroll');
  }
  assert.deepEqual(errors,[]);console.log('HEADER_BROWSER=PASS; themes=2 widths=5 (390/1024/1280/1440/1920); single-row/scroll/settings/relogin/order/actions=PASS');
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
