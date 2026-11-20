'use strict';
// Full shipped HTML and script order; all API replies are synthetic and in memory.
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const {chromium}=require('playwright');
const ROOT=process.env.PQM_UI_FIX_SOURCE_ROOT||path.resolve(__dirname,'..'),OUT=process.env.PQM_LIVE_FIX_EVIDENCE;
assert.ok(OUT,'Use an isolated evidence directory');fs.mkdirSync(OUT,{recursive:true});
const codes=['03210000-6','03220000-9','45000000-7'];
const frameworks=codes.map((dk_code,i)=>({id:'f'+i,pretty_id:'F'+i,title:'Synthetic',category:'Овочі',dk_code,applications_count:3}));
const records=Array.from({length:9},(_,i)=>({id:'s'+i,supplier_code:'9900322'+i,supplier_name:'Синтетичний '+i,dk_code:codes[i%3],status:'active',fields:{},documents:[]}));
const reads=[],mutations=[],errors=[],checks=[],assets=[];
let theme='light',assetFault='';
function fixture(url){
 const p=url.pathname;
 if(p==='/api/auth/me')return{username:'synthetic',role:'admin',authenticated:true,permissions:{'applications.read':true,'suppliers.read':true,'work.read':true},ui_features:{}};
 if(p==='/api/account')return{username:'synthetic',color_scheme:theme,start_view:'applications',density:'comfortable'};
 if(p.includes('frameworks'))return{items:frameworks};
 if(p==='/api/application-profiles')return{items:[],profiles:[],system:[]};
 if(p==='/api/runtime-features')return{environment:'test_web',sandbox_mode:true,background_jobs:{disabled:true,environment_locked:true},scheduler_jobs:[],google:{enabled:false}};
 if(p==='/api/uo-work-queue')return url.searchParams.get('summary')==='application-statistics'
  ?{items:[{review_officer:'',protocol_officer:'',status:'pending',total:3}],totals:{active:0,unsuccessful:0,pending:3,total:3},filter_options:{category:['Овочі'],dk_code:codes,review_officer:[''],protocol_officer:['']},diagnostics:{}}
  :{items:[],rows:[],officers:[],total:0,filters:{},period:{date_from:'2026-11-01',date_to:'2026-11-20'},supplier_types:[],categories:['Овочі'],dk_codes:codes};
 if(p==='/api/edr-monitoring'){
  const selected=url.searchParams.getAll('dk_code').flatMap(v=>v.split(',')).filter(Boolean);
  const items=records.filter(r=>!selected.length||selected.includes(r.dk_code)).map(r=>({...r,edr_status:'Зареєстровано',prozorro_status:'Допущено',freshness:'current'}));
  return{items,total:items.length,pages:1,page:1,edr_statuses:['Зареєстровано','Припинено'],kpis:{}};
 }
 if(p==='/api/applications'){
  const selected=url.searchParams.getAll('dk_code').flatMap(v=>v.split(',')).filter(Boolean);
  const scoped=url.searchParams.get('review_officer')==='__unassigned__';
  const items=records.filter(r=>(!selected.length||selected.includes(r.dk_code))&&(!selected.length||!scoped||Number(r.id.slice(1))<4));
  return{items,total:items.length,pages:1,page:1};
 }
 return{items:[],rows:[],columns:[],profiles:[],count:0,total:0,pages:1,page:1,enabled:false,settings:{},permissions:{},kpis:{},officers:[]};
}
const mime={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.svg':'image/svg+xml','.png':'image/png','.webp':'image/webp'};
const server=http.createServer(async(req,res)=>{
 const u=new URL(req.url,'http://localhost');
 if(u.pathname.startsWith('/api/')){
  if(req.method!=='GET'){mutations.push({method:req.method,path:u.pathname});res.writeHead(403,{'Content-Type':'application/json'});return res.end('{"error":"Fixture denies writes"}');}
  reads.push(u.pathname+u.search);res.writeHead(200,{'Content-Type':'application/json','Cache-Control':'no-store'});return res.end(JSON.stringify(fixture(u)));
 }
 const relative=u.pathname==='/'?'index.html':u.pathname.slice(1),file=path.resolve(ROOT,relative);
 if(!file.startsWith(ROOT+path.sep)||!fs.existsSync(file)){res.writeHead(404);return res.end();}
 if((assetFault==='missing-cat-css'&&relative==='pqm_cat.css')||(assetFault==='missing-dark-logo'&&relative==='assets/pqm-brand-mark-prod-dark.svg')){assets.push({path:relative,status:503});res.writeHead(503);return res.end();}
 if(assetFault==='delayed-cat-controller'&&relative==='halloween.js')await new Promise(r=>setTimeout(r,1800));
 await new Promise(r=>setTimeout(r,(relative.length*17+reads.length*11)%65));
 const data=relative==='index.html'?fs.readFileSync(path.join(OUT,'sandbox-index.html')):fs.readFileSync(file);
 assets.push({path:relative,status:200,sha256:crypto.createHash('sha256').update(data).digest('hex'),cacheControl:'no-store, no-cache, must-revalidate'});
 res.writeHead(200,{'Content-Type':mime[path.extname(file)]||'application/octet-stream','Cache-Control':'no-store, no-cache, must-revalidate'});res.end(data);
});
async function check(name,fn){if(process.env.PQM_BROWSER_CHECK_FILTER&&!new RegExp(process.env.PQM_BROWSER_CHECK_FILTER).test(name))return;try{const detail=await fn();checks.push({name,result:'PASS',detail});console.log('PASS',name);}catch(e){checks.push({name,result:'FAIL',error:e.stack});console.log('FAIL',name,e.message);}}
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const origin='http://127.0.0.1:'+server.address().port;
 const browser=await chromium.launch({headless:true,executablePath:process.env.PQM_CHROMIUM_EXECUTABLE});
 try{
 for(theme of ['light','dark']){
  const context=await browser.newContext({viewport:{width:1920,height:1080}});
  await context.route('**/*',route=>new URL(route.request().url()).origin===origin?route.continue():route.abort());
  const page=await context.newPage();page.setDefaultTimeout(10000);page.on('pageerror',e=>errors.push({theme,message:e.message}));
  await page.goto(origin,{waitUntil:'networkidle'});
  await page.waitForTimeout(600);
  await check(theme+' full application boot',async()=>{assert.equal(await page.evaluate(()=>typeof window.PqmFilterAccordion),'object');assert.equal(await page.evaluate(()=>typeof loadRows),'function');return{errors:errors.filter(e=>e.theme===theme)};});
  await check(theme+' trash survives real boot and repaint',async()=>{
   await page.locator('#edrMonitoringNav').click();await page.locator('#edrMonitoringFilterSummary').click();
   await page.waitForTimeout(650);assert.equal(await page.locator('#edrMonitoringReset svg').count(),1);return await page.locator('#edrMonitoringReset').evaluate(e=>e.outerHTML);
  });
  await check(theme+' external search is not a panel section',async()=>{
   await page.evaluate(()=>{document.querySelector('#edrMonitoringSearch').value='0322';updateEdrMonitoringFilters()});
   assert.equal(await page.locator('#edrMonitoringFilterSummary').innerText(),'Фільтри');
  });
  await check(theme+' transferred DK applied/draft/checkbox state is idempotent',async()=>{
   await page.locator('#workQueueNav').click();
   await page.waitForFunction(()=>document.querySelector('#queueStatisticsRows [data-statistics-action]'));
   await page.locator('#queueStatisticsFilterToggle').click();
   await page.locator('[data-statistics-filter-section="supplier_type"] .queue-statistics-section-toggle').click();
   await page.locator('[data-statistics-filter="supplier_type"]').selectOption('legal_entity');
   await page.locator('[data-statistics-filter-section="category"] .queue-statistics-section-toggle').click();
   await page.locator('[data-statistics-filter="category"]').selectOption('Овочі');
   await page.locator('[data-statistics-filter-section="dk_code"] .queue-statistics-section-toggle').click();
   await page.locator('#queueStatisticsDkOptions input[value="03210000-6"]').check();
   await page.locator('#queueStatisticsDkOptions input[value="03220000-9"]').check();
   await page.locator('#queueStatisticsFilterApply').click();
   await page.waitForTimeout(100);
   await page.screenshot({path:path.join(OUT,'officer-applied-'+theme+'.png'),fullPage:false});
   await page.locator('#queueStatisticsRows tr td').nth(2).locator('button').click();
   await page.waitForFunction(()=>filterSelections.dk.size===2);
   const before=await page.evaluate(()=>({params:currentFilterParams(),applied:[...filterSelections.dk],draft:[...filterDrafts.dk],checked:[...document.querySelectorAll('#dkFilter .multi-options input:checked')].map(n=>n.value)}));
   assert.deepEqual(before.draft.sort(),before.applied.sort());assert.deepEqual(before.checked.sort(),before.applied.sort());
   const presentation=await page.evaluate(()=>{
    const section=document.querySelector('[data-application-filter-section="dk_code"]');
    return{badge:section.querySelector('[data-application-filter-count]').textContent,active:section.classList.contains('filter-active'),pending:section.classList.contains('filter-pending'),applyHidden:section.querySelector('[data-application-filter-apply]').hidden,type:document.querySelector('#applicationEntityTypeFilter').value,category:document.querySelector('#applicationCategoryFilter').value,status:[...document.querySelectorAll('#statusFilter input:checked')].map(n=>n.value),scope:document.querySelector('#queueRegistryScope').textContent,summary:document.querySelector('#applicationFiltersSummary').textContent,activePanelSections:document.querySelectorAll('#applicationFilterPanel .application-filter-section.filter-active').length};
   });
   assert.equal(presentation.badge,'2');assert.equal(presentation.active,true);assert.equal(presentation.pending,false);assert.equal(presentation.applyHidden,true,'no apply check when draft equals applied');
   assert.equal(presentation.type,'legal_entity');assert.equal(presentation.category,'Овочі');assert.deepEqual(presentation.status,['Очікує рішення']);assert.match(presentation.scope,/УО розгляду.*Не призначено/);
   assert.equal(presentation.summary,'Фільтри · 3');assert.equal(presentation.activePanelSections,3,'type, DK and one date section only');
   await page.locator('#applicationFiltersSummary').click();
   await page.locator('[data-application-filter-section="dk_code"] .filter-accordion-toggle').click();
   if(await page.locator('#dkFilter').getAttribute('open')===null)await page.locator('#dkFilter > summary').click();
   await page.screenshot({path:path.join(OUT,'registry-transfer-immediate-'+theme+'.png'),fullPage:false});
   await page.evaluate(()=>document.querySelector('#applicationFilters').open=false);
   await page.evaluate(()=>applyApplicationFilterDimension('dk_code'));
   const after=await page.evaluate(()=>currentFilterParams());assert.deepEqual(after,before.params);
   await page.evaluate(()=>loadRows());
   assert.equal(await page.evaluate(()=>total),3);
   await page.screenshot({path:path.join(OUT,'registry-transfer-'+theme+'.png'),fullPage:false});return{before,presentation,after,total:3};
  });
  await check(theme+' EDR DK substring multi-select and apply',async()=>{
   await page.evaluate(()=>showModule('edrMonitoring'));
   await page.evaluate(()=>{document.querySelector('#edrMonitoringAdvanced').open=true});
   await page.locator('[data-edr-filter-section="dk_code"] .filter-accordion-toggle').click();
   if(await page.locator('#edrMonitoringDkFilter').getAttribute('open')===null)await page.locator('#edrMonitoringDkFilter > summary').click();
   const search=page.locator('#edrMonitoringDkFilter .multi-search');assert.equal(await search.count(),1);
   await search.fill('0322');const option=page.locator('#edrMonitoringDkFilter input[type=checkbox][value="03220000-9"]');assert.equal(await option.count(),1);await option.check();
   assert.equal(await page.locator('#edrMonitoringDkFilter').getAttribute('open')!==null,true);
   assert.equal(await page.evaluate(()=>edrMonitoringParams().dk_code),'');
   await search.fill('0321');await page.locator('#edrMonitoringDkFilter input[type=checkbox][value="03210000-6"]').check();
   await page.locator('[data-edr-filter-section="dk_code"] [data-edr-filter-apply]').click();
   assert.deepEqual((await page.evaluate(()=>edrMonitoringParams().dk_code)).split(',').sort(),codes.slice(0,2));
   await page.waitForFunction(()=>edrMonitoringTotal===6);
   await page.locator('[data-edr-filter-section="dk_code"] .filter-accordion-toggle').click();
   if(await page.locator('#edrMonitoringDkFilter').getAttribute('open')===null)await page.locator('#edrMonitoringDkFilter > summary').click();
   await search.fill('032');await page.screenshot({path:path.join(OUT,'edr-multi-'+theme+'.png'),fullPage:false});
   const data={params:await page.evaluate(()=>edrMonitoringParams()),total:await page.evaluate(()=>edrMonitoringTotal)};
   await page.reload({waitUntil:'networkidle'});
   assert.deepEqual((await page.evaluate(()=>edrMonitoringParams().dk_code)).split(',').sort(),codes.slice(0,2),'applied EDR codes survive reload');
   assert.equal(await page.locator('#edrMonitoringDkFilter input:checked').count(),2,'restored applied codes also restore checkboxes');
   await page.evaluate(()=>{showModule('edrMonitoring');document.querySelector('#edrMonitoringAdvanced').open=true});
   await page.locator('[data-edr-filter-section="dk_code"] [data-edr-filter-clear]').click();
   await page.waitForFunction(()=>edrMonitoringTotal===9);
   assert.equal(await page.locator('#edrMonitoringDkFilter input:checked').count(),0);return data;
  });
  await page.screenshot({path:path.join(OUT,'full-page-'+theme+'.png'),fullPage:false});
  await check(theme+' repeated reloads retain resources and trash',async()=>{
   const records=[];
   for(let i=0;i<3;i++){
    await page.reload({waitUntil:'networkidle'});await page.waitForTimeout(550);
    const record=await page.evaluate(()=>{const cat=document.querySelector('img.halloween-cat'),logo=document.querySelector('.sandbox-brand-initials');return{trash:!!document.querySelector('#edrMonitoringReset svg'),catWidth:cat?.getBoundingClientRect().width,catVisible:!!cat&&getComputedStyle(cat).display!=='none',logoLoaded:!!logo?.naturalWidth,theme:document.documentElement.dataset.theme,dkOptions:document.querySelectorAll('#dkFilter .multi-options input').length};});records.push(record);
    assert.equal(record.trash,true);assert(record.catWidth>0&&record.catWidth<=180);assert.equal(record.logoLoaded,true);assert.equal(record.theme,theme);assert.equal(record.dkOptions,codes.length);
   }return records;
  });
  await check(theme+' missing permanent cat CSS cannot enlarge cat',async()=>{
   assetFault='missing-cat-css';try{await page.reload({waitUntil:'networkidle'});const width=await page.locator('img.halloween-cat').evaluate(e=>e.getBoundingClientRect().width);assert(width<=180,'cat width '+width);return{width};}finally{assetFault='';}
  });
  await check(theme+' failed dark logo keeps a loaded mark',async()=>{
   assetFault='missing-dark-logo';try{await page.reload({waitUntil:'networkidle'});const mark=await page.locator('.sandbox-brand-initials').evaluate(e=>({loaded:e.complete&&e.naturalWidth>0,width:e.getBoundingClientRect().width,height:e.getBoundingClientRect().height,src:e.getAttribute('src')}));assert(mark.loaded);assert.equal(mark.width,82);assert.equal(mark.height,40);return mark;}finally{assetFault='';}
  });
  await check(theme+' cold EDR entry loads the common CPV source',async()=>{
   await page.evaluate(()=>localStorage.clear());
   await page.goto(origin+'/?view=edrMonitoring',{waitUntil:'networkidle'});
   await page.waitForFunction(()=>document.querySelectorAll('#edrMonitoringDkFilter .multi-options input').length===3);
   assert.equal(await page.locator('#dkFilter .multi-options input').count(),3,'registry and EDR use the same framework CPV source');
   return{edrCodes:await page.locator('#edrMonitoringDkFilter .multi-options input').evaluateAll(nodes=>nodes.map(n=>n.value))};
  });
  await check(theme+' first cat frame is stable before the late controller',async()=>{
   assetFault='delayed-cat-controller';
   try{
    await page.goto(origin,{waitUntil:'commit'});
    await page.waitForSelector('img.halloween-cat',{state:'visible'});
    const early=await page.locator('img.halloween-cat').evaluate(e=>({width:e.getBoundingClientRect().width,display:getComputedStyle(e).display,src:e.getAttribute('src'),bridgeStarted:document.documentElement.dataset.pqmCatController==='on'}));
    // Static ordinary markup must be correct even before its controller starts.
    assert.equal(early.display,'block');assert.equal(early.width,180);assert.equal(early.src,'assets/pqm-cat-no-hat.png');
    await page.waitForLoadState('networkidle');assert.equal(await page.evaluate(()=>document.documentElement.dataset.pqmCatController),'on','ordinary controller finishes initialization');assert.equal(assets.filter(a=>a.path==='halloween.js'&&a.status===200).length,0,'November never requests the seasonal controller');return early;
   }finally{assetFault='';}
  });
  await context.close();
 }
 }finally{await browser.close();await new Promise(r=>server.close(r));}
 const report={checks,errors,mutations,reads,assets,failures:checks.filter(c=>c.result==='FAIL')};fs.writeFileSync(path.join(OUT,'browser-results.json'),JSON.stringify(report,null,2));
 console.log(JSON.stringify({checks:checks.map(c=>({name:c.name,result:c.result,error:c.error?.split('\n')[0]})),errors,mutations},null,2));if(report.failures.length)process.exitCode=1;
})().catch(e=>{console.error(e);process.exitCode=1;server.close();});
