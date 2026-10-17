/* Complete offline DOM acceptance. Actual callbacks, no network or write adapter. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('playwright'),root=path.resolve(__dirname,'..'),read=n=>fs.readFileSync(path.join(root,n),'utf8').replaceAll('\r\n','\n');
const out=process.env.PQM_UI_EVIDENCE_DIR||fs.mkdtempSync(path.join(require('node:os').tmpdir(),'pqm-ui-final-'));
const app=read('app.js'),section=(a,b)=>app.slice(app.indexOf(a),app.indexOf(b,app.indexOf(a)));
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.PQM_TEST_BROWSER?{executablePath:process.env.PQM_TEST_BROWSER}:{})});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(String(e)));
 await page.route('**/*',r=>r.request().url()==='https://pqm-ui-fixture.invalid/'?r.fulfill({contentType:'text/html',body:read('index.html').replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,'')}):r.abort());
 try{
  await page.goto('https://pqm-ui-fixture.invalid/');
  for(const f of ['styles.css','filters.css','modules.css','schema_ui.css','ui_improvements.css','sandbox_theme.css','ui_final.css','ui_tz2.css'])await page.addStyleTag({content:read(f)});
  await page.evaluate(()=>{
   window.$=s=>document.querySelector(s);window.$$=s=>[...document.querySelectorAll(s)];
   $('#loginGate').hidden=true;$('#applicationShell').hidden=false;document.body.dataset.authRole='admin';
   window.show=id=>$$('main').forEach(n=>n.hidden=n.id!==id);
   window.API='/api';window.role=()=> 'admin';window.currentMe={permissions:{}};window.authReady=Promise.resolve(currentMe);window.toast=()=>{};
   window.esc=s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');window.displayDate=s=>s;
   window.requestsPage=1;window.loadViolationReports=()=>{};window.filterSelections={status:new Set()};window.page=2;window.statsSignature='old';window.rowLoads=0;window.loadRows=()=>{rowLoads++};
   window.updateMultiSummary=()=>{};window.auditPage=3;window.auditPages=3;
   window.frameworkPage=4;window.loadFrameworkAnalytics=()=>{};
   window.calls=[];window.schedulerScheduleDrafts=new Map();window.schedulerEditorsGeneration=0;
   window.schedulerJobLabels={prozorro:'Заявки / Prozorro',violation_reports:'Звернення замовників',nazk_registry:'Реєстр НАЗК'};
   window.jobs=['prozorro','violation_reports','nazk_registry'].map(job=>({job,spec:{kind:'hourly',minute:50},enabled:false,effective_enabled:false,registered:true,schedule:'щогодини :50',timezone:'Europe/Kyiv',revision:2,history:[],last_status:'ok',last_started_at:'fixture',next_run:'fixture',duration_seconds:2}));
   window.features={scheduler_jobs:jobs,sandbox_mode:true,powerbi:true,google:true,bids_mode:'supported'};
   window.environmentBannerText=()=> 'PQM';window.loadSandboxAutomationControl=async()=>{};window.renderGoogleRuntimeState=()=>{};window.renderManualBidsUpdateState=()=>{};window.updateRequestsRefreshAvailability=()=>{};
   window.request=async(url,options={})=>{if(options.method&&options.method!=='GET')throw Error('Forbidden write '+url);calls.push(url);
    if(url.endsWith('/runtime-features'))return features;
    if(url.endsWith('/admin/scheduler-schedules'))return{items:jobs};
    if(url.endsWith('/google-writer/status'))return{configured_enabled:false,can_manage:true,channel_ready:false,can_execute:false,blocked:false,schedule:'09:00',last_status:'off',hour:9,minute:0,runs:[]};
    if(url.includes('/audit?'))return{items:[{id:1,submission_id:'old-page',changed_at:'fixture',changed_by:'Officer',field_name:'notes',old_value:'a',new_value:'b'}],total:1,page:1,pages:1};
    return{tables:{}};
   };
   $('#mainNav').innerHTML='<button id="applicationsNav">Реєстр заявок</button><button id="historyNav">Історія заявок</button>';
  });
  await page.addScriptTag({content:read('working_modal_drag.js')});
  await page.addScriptTag({content:read('ui_improvements.js')});
  await page.addScriptTag({content:read('audit_search.js')});
  await page.addScriptTag({content:section('let auditRows=','function renderProfileFallback(')});
  await page.addScriptTag({content:section('function schedulerEditorMarkup(','async function loadRuntimeFeatures(')+section('async function loadRuntimeFeatures(){',"\ndocument.addEventListener('click',event=>{\n  const blocked=")});
  await page.addScriptTag({content:read('google_writer_ui.js')});
  await page.addScriptTag({content:read('table_widths_ui.js')});
  await page.addScriptTag({content:read('ui_improvements_boot.js')});
  await page.addScriptTag({content:read('ui_final.js')});
  await page.addScriptTag({content:read('ui_tz2.js')});
  // Text clears include dynamic modal/multiselect fields but never dates/numbers/editing.
  await page.evaluate(()=>{const box=document.createElement('div');box.innerHTML='<input id="dynamicSearch" type="search"><input id="ordinaryEdit"><input id="numberFixture" type="number">';document.body.append(box)});
  await page.waitForFunction(()=>document.querySelector('#dynamicSearch').closest('.pqm-clear-wrap'));
  assert.equal(await page.locator('#ordinaryEdit').evaluate(n=>!!n.closest('.pqm-clear-wrap')),false);
  assert.equal(await page.locator('#numberFixture').evaluate(n=>!!n.closest('.pqm-clear-wrap')),false);
  await page.locator('#dynamicSearch').fill('abc');await page.locator('#dynamicSearch').locator('..').locator('button').click();assert.equal(await page.locator('#dynamicSearch').inputValue(),'');
  await page.evaluate(()=>show('historyView'));
  for(const dark of [false,true])for(const width of [1280,1440,1680,1920])for(const zoom of [1,1.25]){
   await page.setViewportSize({width,height:1000});
   await page.evaluate(({dark,zoom})=>{if(dark)document.documentElement.dataset.pqmEnvironment='sandbox';else delete document.documentElement.dataset.pqmEnvironment;document.body.style.zoom=String(zoom);show('historyView')},{dark,zoom});
   await page.waitForTimeout(35);
   const h=await page.evaluate(()=>{const status=$('#historyFilters select'),r=status.getBoundingClientRect(),footer=$('#historyView>.pagination').getBoundingClientRect();return{width:r.width,client:status.clientHeight,scroll:status.scrollHeight,footer:footer.bottom,primary:$$('.history-filter-primary input').map(n=>n.getBoundingClientRect().y),reset:$('#historyReset').textContent}});
   assert(h.width>=170*zoom-1);assert(h.scroll<=h.client+1,'Status height clipped');assert.equal(h.reset,'×');assert(h.footer<=1000-20,'History footer under banner '+JSON.stringify({width,zoom,h}));
   if(zoom===1)assert.equal(new Set(h.primary.map(Math.round)).size,1);
   await page.evaluate(()=>show('workQueueView'));
   assert.equal(await page.locator('#workQueueKpis').isVisible(),false);assert.equal(await page.locator('.work-queue-details').isVisible(),false);assert.equal(await page.locator('#workQueueView .work-queue-toolbar').isVisible(),false);
   let originalHeight=null;
   for(const count of [1,2,3,4,5,7]){
    await page.evaluate(count=>{for(const id of ['queueQualificationCards','queueProtocolOfficerCards','queueCategoryCards','queueProtocolCategoryCards']){const category=id.includes('Category');$('#'+id).innerHTML=Array.from({length:count},(_,i)=>`<button class="qualification-summary-officer ${category?'qualification-summary-category':''}"><span>${category?['Їжа','Інше','Газ/ЕЕ','Пальне'][i%4]:'Тетяна ФЕДЧЕНКО'}</span><strong>26</strong><small>категорія</small></button>`).join('')}$('#queuePublicationControl').innerHTML='<button><span>Все ще очікує рішення</span><strong>26</strong></button>'},count);
    await page.waitForTimeout(45);
    const cards=await page.evaluate(()=>$$('#workQueueView .qualification-summary-cards').map(group=>({x:group.scrollWidth<=group.clientWidth+1,cards:[...group.children].map(n=>{const span=n.querySelector('span');return{width:n.clientWidth,height:n.getBoundingClientRect().height,text:span.scrollWidth<=span.clientWidth+1}})})));
    assert(cards.every(g=>g.x&&g.cards.every(c=>c.text)),'Work Queue clipping '+JSON.stringify({width,zoom,count,cards}));
    if(originalHeight===null)originalHeight=cards[0].cards[0].height;assert(cards.every(g=>g.cards.every(c=>Math.abs(c.height-originalHeight)<1)),'KPI card height changed');
    if(count===4&&zoom===1){
      const layout=await page.locator('#queueProtocolCategoryCards').evaluate(group=>{const r=group.getBoundingClientRect();return{left:r.left,right:r.right,scroll:group.scrollWidth,client:group.clientWidth,cards:[...group.children].map(n=>{const c=n.getBoundingClientRect();return{x:c.x,y:c.y,width:c.width,right:c.right}})}});
      assert.equal(new Set(layout.cards.map(c=>Math.round(c.y))).size,1,'Protocol categories wrap');
      assert(Math.max(...layout.cards.map(c=>c.width))-Math.min(...layout.cards.map(c=>c.width))<1,'Category widths differ');
      assert(layout.scroll<=layout.client+1);assert(layout.cards[0].x>=layout.left&&layout.cards.at(-1).right<=layout.right+1);
    }
   }
   if(width===1440&&zoom===1)await page.screenshot({path:path.join(out,`work-queue-final-${dark?'dark':'light'}.png`)});
  }
  await page.setViewportSize({width:390,height:900});await page.evaluate(()=>{document.body.style.zoom='1';show('workQueueView');$('#queueProtocolCategoryCards').innerHTML=['Їжа','Інше','Газ/ЕЕ','Пальне'].map(name=>`<button class="qualification-summary-officer qualification-summary-category"><span>${name}</span><strong>20000</strong><small>категорія</small></button>`).join('')});await page.waitForTimeout(50);
  const narrowCategories=await page.locator('#queueProtocolCategoryCards').evaluate(n=>({fits:n.scrollWidth<=n.clientWidth+1,rows:new Set([...n.children].map(c=>Math.round(c.getBoundingClientRect().y))).size,labels:[...n.querySelectorAll('span')].every(s=>s.scrollWidth<=s.clientWidth+1)}));assert(narrowCategories.fits&&narrowCategories.labels&&narrowCategories.rows===2);
  await page.evaluate(()=>{document.body.style.zoom='1';show('administrationView');$('#adminSyncPanel').hidden=false});await page.setViewportSize({width:1920,height:1080});
  await page.evaluate(()=>loadRuntimeFeatures());
  assert.equal(await page.locator('#schedulerJobs>.scheduler-job').count(),4);assert.equal(await page.locator('#schedulerJobs .scheduler-editor').count(),3);
  assert.equal(await page.locator('#googleWriterJobCard details').count(),1);assert.equal(await page.locator('[data-schedule-action=preview]').first().textContent(),'Переглянути розклад');
  const ys=await page.locator('#schedulerJobs>.scheduler-job').evaluateAll(nodes=>nodes.map(n=>Math.round(n.getBoundingClientRect().y)));assert.equal(new Set(ys).size,1);
  assert.equal(await page.locator('[data-schedule-action=apply]').first().isDisabled(),true);await page.screenshot({path:path.join(out,'automation-four-cards.png')});
  const surface=await page.locator('#schedulerJobs>.scheduler-job').first().evaluate(n=>getComputedStyle(n).backgroundColor);assert.equal(surface,'rgb(21, 43, 70)');
  for(const width of [1440,1680,1920]){
   await page.setViewportSize({width,height:1000});await page.evaluate(()=>show('suppliersView'));await page.waitForTimeout(80);
   const toolbar=await page.locator('#suppliersView .supplier-toolbar').evaluate(n=>[...n.children].filter(c=>!c.hidden&&getComputedStyle(c).display!=='none'&&c.tagName!=='DATALIST').map(c=>{const r=c.getBoundingClientRect();return{id:c.id||c.className,bottom:r.bottom,right:r.right}}));
   const bottoms=toolbar.map(e=>Math.round(e.bottom));assert(Math.max(...bottoms)-Math.min(...bottoms)<3,'Supplier toolbar wraps '+JSON.stringify({width,toolbar}));assert(toolbar.every(e=>e.right<=width));
  }
  await page.evaluate(()=>{window.frameworkOptions=[{id:'f1',pretty_id:'UA-F-1',title:'Їжа',dk_code:'03110000-1'},{id:'f2',pretty_id:'UA-F-2',title:'Інше',dk_code:'03220000-2'}];$('#supplierRegistryFramework').innerHTML=frameworkOptions.map(f=>`<option value="${f.id}">${f.pretty_id}</option>`).join('');window.supplierRegistryPage=5;window.loadQualifiedSuppliersFiltered=()=>{};window.updateMultiSummary=(id,label,set)=>{$('#'+id+' summary').textContent=set.size>1?label+': '+set.size:set.size?[...set][0]:label}});
  await page.addScriptTag({content:section('function renderDynamicFilter(','async function loadFrameworks(')+section('function renderSupplierScopeFilters(){',"$('#supplierRegistryFramework').onchange=")});
  await page.evaluate(()=>renderSupplierScopeFilters());
  await page.evaluate(()=>{$('#supplierRegistryFrameworkFilter').open=true});
  const panel=await page.locator('#supplierRegistryFrameworkFilter .multi-panel').boundingBox(),closed=await page.locator('#supplierRegistryFrameworkFilter summary').boundingBox();assert(panel.width>closed.width);assert(panel.x>=0&&panel.x+panel.width<=1920);
  assert(await page.locator('#supplierRegistryFrameworkFilter .multi-panel').evaluate(n=>n.scrollWidth<=n.clientWidth+1));
  await page.evaluate(()=>{$('#supplierRegistryFrameworkFilter').open=false});
  await page.locator('#supplierRegistryDkFilter summary').click();await page.locator('#supplierRegistryDkFilter input[type=checkbox]').first().check();await page.locator('#supplierRegistryDkFilter .multi-search').fill('0322');await page.locator('#supplierRegistryDkFilter input[type=checkbox]').check();assert.equal(await page.locator('#supplierRegistryDk').inputValue(),'03110000-1,03220000-2');
  await page.locator('#supplierRegistryDkFilter .multi-search').fill('');assert.equal(await page.locator('#supplierRegistryDkFilter input:checked').count(),2);await page.locator('#supplierRegistryDkFilter [data-clear-scope]').click();assert.equal(await page.locator('#supplierRegistryDk').inputValue(),'');
  await page.evaluate(()=>{$('#supplierRegistryDkFilter').open=false;$('#supplierRegistryFrameworkFilter').open=true});await page.locator('#supplierRegistryFrameworkFilter .multi-search').fill('Їжа');await page.locator('#supplierRegistryFrameworkFilter input[type=checkbox]').check();await page.locator('#supplierRegistryFrameworkFilter .multi-search').fill('UA-F-2');await page.locator('#supplierRegistryFrameworkFilter input[type=checkbox]').check();assert.deepEqual(await page.evaluate(()=>[...$('#supplierRegistryFramework').selectedOptions].map(o=>o.value)),['f1','f2']);
  assert.equal(await page.locator('#supplierRegistryExcel').count(),0);
  await page.evaluate(()=>{show('applicationsView');window.rowLoads=0});
  await page.locator('[data-kpi-card=applications]').click();await page.locator('[data-kpi-card=suppliers]').click();assert.equal(await page.evaluate(()=>rowLoads),0);
  await page.locator('[data-kpi-card=admitted]').click();assert.deepEqual(await page.evaluate(()=>[...filterSelections.status]),['Допущено']);
  await page.locator('[data-kpi-card=rejected]').click();assert.deepEqual(await page.evaluate(()=>[...filterSelections.status]),['Відхилено']);
  await page.locator('[data-kpi-card=rejected]').click();assert.deepEqual(await page.evaluate(()=>[...filterSelections.status]),[]);
  await page.evaluate(()=>openAudit());assert.equal(await page.locator('#auditDialog').isVisible(),true);
  await page.locator('[data-audit-filter=search]').fill('old-page');await page.waitForTimeout(550);
  assert(await page.evaluate(()=>calls.some(url=>url.includes('search=old-page')&&url.includes('page=1'))));
  const before=await page.locator('#auditDialog').boundingBox(),header=await page.locator('#auditDialog header h2').boundingBox();
  await page.evaluate(()=>{window.clipboardValue='';window.copyText=async text=>{clipboardValue=text};renderAudit({items:[{changed_at:'fixture',old_value:'Було\n'.repeat(100),new_value:'Стало\n'.repeat(100)}],total:1,pages:1})});
  assert((await page.locator('.audit-long-value').first().boundingBox()).height<80);
  await page.locator('.audit-long-value').first().click();assert.equal(await page.locator('#auditValueDialog pre').count(),2);
  await page.locator('#auditValueDialog section button').first().click();assert.equal(await page.evaluate(()=>clipboardValue),'Було\n'.repeat(100));
  await page.locator('#auditValueDialog .dialog-close').click();
  await page.mouse.move(header.x+30,header.y+8);await page.mouse.down();await page.mouse.move(header.x+90,header.y+60,{steps:5});await page.mouse.up();const after=await page.locator('#auditDialog').boundingBox();assert(Math.abs(after.width-before.width)<1);assert(after.y>=0&&after.y<1000-60);
  await page.locator('#historyNav').click();assert.equal(await page.locator('#auditDialog').isVisible(),false);
  for(const height of [720,900])for(const zoom of [1,1.25]){
    await page.setViewportSize({width:1280,height});await page.evaluate(zoom=>{document.body.style.zoom=String(zoom)},zoom);
    await page.evaluate(()=>openAudit());await page.waitForTimeout(50);const r=await page.locator('#auditDialog').boundingBox();
    assert(r.x>=0&&r.y>=0&&r.x+r.width<=1280&&r.y+r.height<=height,'Audit outside viewport '+JSON.stringify({height,zoom,r}));
    const handle=await page.locator('#auditDialog header h2').boundingBox();await page.mouse.move(handle.x+10,handle.y+10);await page.mouse.down();await page.mouse.move(1270,height-10,{steps:5});await page.mouse.up();
    const moved=await page.locator('#auditDialog').boundingBox();assert(moved.x>=0&&moved.y>=0&&moved.x+moved.width<=1280&&moved.y+moved.height<=height,'Zoomed audit dragging outside viewport');
    await page.evaluate(()=>$('#auditDialog').close());
  }
  assert.deepEqual(errors,[]);console.log('UI_FINAL_BROWSER=PASS; themes=2 widths=4 zooms=2; workQueue=1/2/3/4/5/7; audit/drag/clear/status/4-cards=PASS');
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
