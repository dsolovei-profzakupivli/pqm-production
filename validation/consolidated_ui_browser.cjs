/* Actual markup/styles and filter functions. All requests are blocked. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('playwright'),ROOT=path.resolve(__dirname,'..');
const read=n=>fs.readFileSync(path.join(ROOT,n),'utf8'),app=read('app.js');
const chunk=(a,b)=>app.slice(app.indexOf(a),app.indexOf(b,app.indexOf(a)));
const OUT=process.env.PQM_UI_EVIDENCE_DIR||fs.mkdtempSync(path.join(require('node:os').tmpdir(),'pqm-consolidated-ui-'));
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.PQM_TEST_BROWSER?{executablePath:process.env.PQM_TEST_BROWSER}:{})});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(String(e)));
 await page.route('**/*',r=>r.abort());
 try{
  await page.setContent(read('index.html').replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,''));
  for(const f of ['styles.css','filters.css','modules.css','schema_ui.css','sandbox_theme.css'])await page.addStyleTag({content:read(f)});
  await page.evaluate(()=>{
   window.$=s=>document.querySelector(s);window.$$=s=>[...document.querySelectorAll(s)];
   $('#loginGate').hidden=true;$('#applicationShell').hidden=false;document.body.dataset.authRole='admin';
   window.show=id=>document.querySelectorAll('main').forEach(n=>n.hidden=n.id!==id);
   for(const id of ['queueQualificationCards','queueProtocolOfficerCards'])$('#'+id).innerHTML=['Дмитро САВВА','Світлана НАМЯСЕНКО'].map(name=>`<button class="qualification-summary-officer"><span>${name}</span><strong>72</strong><small>Очікує рішення</small></button>`).join('');
   for(const id of ['queueCategoryCards','queueProtocolCategoryCards'])$('#'+id).innerHTML=['Їжа','Інше','Газ/ЕЕ','Пальне'].map(name=>`<button class="qualification-summary-officer"><span>${name}</span><strong>20</strong><small>Очікує рішення</small></button>`).join('');
   $('#queuePublicationControl').innerHTML=['Допущено','Відхилено','Все ще очікує рішення'].map(name=>`<button><span>${name}</span><strong>21</strong></button>`).join('');
   show('workQueueView');
  });
  const heights=await page.evaluate(()=>Object.fromEntries(['#workQueueKpis button','.qualification-summary-officer','#queuePublicationControl button'].map(selector=>[selector,Math.max(...$$(selector).map(e=>e.getBoundingClientRect().height))])));
  await page.addStyleTag({content:read('ui_improvements.css')});
  await page.addScriptTag({content:read('ui_improvements.js')});
  await page.evaluate(()=>{window.currentMe={permissions:{}};window.authReady=new Promise(()=>{});window.request=()=>{throw Error('HTTP forbidden')};window.toast=()=>{};window.loadViolationReports=()=>{}});
  await page.addScriptTag({content:read('ui_improvements_boot.js')});
  for(const key of ['search','code','supplier','cpv','framework','contract','manager','officer','remarks']){
   await page.evaluate(key=>{const input=$(`input[data-history="${key}"]`);input.value='Перевірка';input.dispatchEvent(new Event('input',{bubbles:true}));const clear=input.closest('.pqm-clear-wrap').querySelector('button');if(clear.hidden)throw Error('Clear button absent');clear.click();if(input.value!=='')throw Error('Field not cleared')},key);
  }
  for(const dark of [false,true])for(const width of [1440,1920,768,390]){
   await page.setViewportSize({width,height:1000});
   await page.evaluate(dark=>{if(dark)document.documentElement.dataset.pqmEnvironment='sandbox';else delete document.documentElement.dataset.pqmEnvironment;show('workQueueView')},dark);
   const queue=await page.evaluate(()=>{
    const boxes=selector=>$$(selector).map(e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return{x:r.x,y:r.y,w:r.width,h:r.height,font:s.fontSize,grow:s.flexGrow}});
    return{top:boxes('#workQueueKpis button'),officer:boxes('#queueProtocolOfficerCards button'),publication:boxes('#queuePublicationControl button'),regions:$$('#workQueueKpis,.qualification-summary-cards,.publication-control-cards').map(e=>({client:e.clientHeight,scroll:e.scrollHeight}))};
   });
   assert(queue.top.every(e=>Math.abs(e.h-heights['#workQueueKpis button'])<1));
   assert(queue.officer.every(e=>Math.abs(e.h-heights['.qualification-summary-officer'])<1));
   assert(queue.publication.every(e=>Math.abs(e.h-heights['#queuePublicationControl button'])<1));
   assert.equal(new Set(queue.top.map(e=>e.y)).size,1);assert(queue.top.every(e=>e.grow==='0'));
   assert(queue.officer.every(e=>e.w<190));assert(queue.regions.every(e=>e.scroll<=e.client+1));
   assert(new Set(queue.top.map(e=>Math.round(e.w))).size>2);
   await page.evaluate(()=>show('historyView'));
   const history=await page.evaluate(()=>{
    const box=e=>{const r=e.getBoundingClientRect();return{x:r.x,y:r.y,w:r.width,h:r.height}};
    return{primary:$$('.history-filter-primary input[data-history]').map(box),secondary:$$('.history-filter-secondary>*').map(box),status:box($('#historyFilters select')),reset:box($('#historyReset')),container:box($('#historyFilters')),labels:$$('.history-filter-primary input').map(e=>e.dataset.history)};
   });
   assert.deepEqual(history.labels,['search','code','supplier','cpv','framework','contract','manager','officer']);
   if(width>=1440){assert.equal(new Set(history.primary.map(e=>Math.round(e.y))).size,1);assert.equal(new Set(history.secondary.map(e=>Math.round(e.y))).size,1);assert(history.secondary[0].w>history.status.w*2);assert(history.container.h<100,'History rows stretched vertically '+JSON.stringify({dark,width,height:history.container.h}))}
   assert(history.status.w<180&&history.reset.w<110);assert.equal(await page.locator('#historyReset').textContent(),'Очистити');
   assert(history.primary.every(e=>e.x+e.w<=history.container.x+history.container.w+1),JSON.stringify({width,history}));
   if(width===1440)await page.screenshot({path:path.join(OUT,`history-${dark?'dark':'light'}-1440.png`)});
  }
  // Execute the shared dynamic checkbox mechanism and supplier-specific adapter.
  await page.setViewportSize({width:1440,height:1000});
  await page.evaluate(()=>{
   show('suppliersView');window.esc=s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
   window.page=9;window.supplierRegistryPage=8;window.loads=0;window.loadRows=()=>{throw Error('Applications loader must not run')};window.loadQualifiedSuppliersFiltered=()=>{loads++};
   window.frameworkOptions=[{id:'f1',pretty_id:'UA-F-1',dk_code:'03110000-1',title:'Їжа'},{id:'f2',pretty_id:'UA-F-2',dk_code:'03220000-2',title:'Овочі'},{id:'f3',pretty_id:'UA-F-3',dk_code:'03110000-1',title:'Повторний відбір'}];
   $('#supplierRegistryFramework').innerHTML=frameworkOptions.map(f=>`<option value="${f.id}">${f.pretty_id}</option>`).join('');
  });
  await page.addScriptTag({content:app.split('\n').find(l=>l.startsWith('function updateMultiSummary('))+'\n'+chunk('function renderDynamicFilter(','async function loadFrameworks(')+chunk('function renderSupplierScopeFilters(){',"$('#supplierRegistryFramework').onchange=")});
  await page.evaluate(()=>renderSupplierScopeFilters());
  assert.equal(await page.locator('#supplierRegistryExcel').count(),0);
  await page.locator('#supplierRegistryDkFilter summary').click();
  await page.locator('#supplierRegistryDkFilter input[type=checkbox]').first().check();
  await page.locator('#supplierRegistryDkFilter .multi-search').fill('0322');
  await page.locator('#supplierRegistryDkFilter input[type=checkbox]').check();
  assert.equal(await page.locator('#supplierRegistryDk').inputValue(),'03110000-1,03220000-2');
  assert.equal(await page.locator('#supplierRegistryDkFilter summary').textContent(),'Усі коди ДК: 2');
  await page.locator('#supplierRegistryDkFilter .multi-search').fill('');
  assert.equal(await page.locator('#supplierRegistryDkFilter input:checked').count(),2);
  await page.locator('#supplierRegistryDkFilter [data-clear-scope]').click();
  assert.equal(await page.locator('#supplierRegistryDk').inputValue(),'');
  await page.evaluate(()=>{$('#supplierRegistryDkFilter').open=false;$('#supplierRegistryFrameworkFilter').open=true});
  await page.locator('#supplierRegistryFrameworkFilter .multi-search').fill('Їжа');
  await page.locator('#supplierRegistryFrameworkFilter input[type=checkbox]').check();
  await page.locator('#supplierRegistryFrameworkFilter .multi-search').fill('UA-F-2');
  await page.locator('#supplierRegistryFrameworkFilter input[type=checkbox]').check();
  assert.deepEqual(await page.evaluate(()=>[...$('#supplierRegistryFramework').selectedOptions].map(o=>o.value)),['f1','f2']);
  await page.locator('#supplierRegistryFrameworkFilter .multi-search').fill('');assert.equal(await page.locator('#supplierRegistryFrameworkFilter input:checked').count(),2);
  assert.equal(await page.evaluate(()=>supplierRegistryPage),1);assert.equal(await page.evaluate(()=>page),9);
  await page.screenshot({path:path.join(OUT,'supplier-multiselect-dark-1440.png')});
  // Copy icons align to cell right edge despite different label lengths.
  await page.evaluate(()=>{show('frameworkAnalyticsView');$('#frameworksBody').innerHTML='<tr><td><div class="framework-number"><a>UA-F-1</a><button class="copy-framework-number">⧉</button></div></td></tr><tr><td><div class="framework-number"><a>UA-F-2026-10-16-000000000001</a><button class="copy-framework-number">⧉</button></div></td></tr>'});
  const right=await page.locator('.copy-framework-number').evaluateAll(nodes=>nodes.map(n=>({right:n.getBoundingClientRect().right,gap:n.closest('td').getBoundingClientRect().right-n.getBoundingClientRect().right})));
  assert(Math.abs(right[0].right-right[1].right)<1);assert(right.every(r=>r.gap>=6&&r.gap<=9));
  assert.deepEqual(errors,[]);console.log(JSON.stringify({result:'PASS',work_queue_heights:heights,viewports:8,multiselect:'PASS',history_two_rows:'PASS',copy_alignment:'PASS',network:'BLOCKED',evidence:OUT}));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
