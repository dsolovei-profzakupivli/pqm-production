const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..'),OUT=process.env.PQM_CONTEXT_EVIDENCE_DIR;
assert.ok(OUT,'Use an isolated evidence directory');
const read=f=>fs.readFileSync(path.join(ROOT,f),'utf8');
const base=read('validation/uo_work_page_layout_browser.cjs'),prefix=base.slice(0,base.indexOf('(async()=>{'));
const f=new Function('require','__dirname',prefix+'\nreturn {makePage,makeAuxPage};')(require,__dirname);
const app=read('app.js');
function source(name){const start=app.indexOf('function '+name+'(');assert.ok(start>=0,name);const line=app.slice(start).split('\n')[0];return line.trim().endsWith('}')?line:app.slice(start,app.indexOf('\n}',start)+2);}
const records=[],flowChecks=[];
async function globals(page){await page.evaluate(()=>{
 window.$=s=>document.querySelector(s);window.$$=s=>[...document.querySelectorAll(s)];window.esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 window.filterSelections={dk:new Set(),status:new Set(),supplier:new Set(),registry:new Set(),framework:new Set(),marketplace:new Set()};window.filterDrafts={dk:new Set(),registry:new Set(),supplier:new Set(),framework:new Set()};window.queueRegistryFilters={};window.categoryFilter='';window.officerFilter='';window.page=1;window.statsSignature='';window.syncSharedFilterPresentation=()=>{};window.loadRows=()=>{};
 });}
async function chrome(page,kind){
 await page.addScriptTag({path:path.join(ROOT,'nav_icons.js')});
 const logo=fs.readFileSync(path.join(ROOT,'assets/pqm-brand-mark-prod.svg')).toString('base64');
 await page.evaluate(({kind,logo})=>{
  document.querySelectorAll('#mainNav button').forEach(n=>n.classList.toggle('nav-active',n.dataset.navModule===kind));
  document.querySelector('.brand img').src='data:image/svg+xml;base64,'+logo;
  document.querySelector('#environmentBanner').textContent='PQM Sandbox · тестові дані';
  document.querySelector('#accountDisplayName').textContent='Тестова УО';
  document.querySelector('#roleSelect').value='officer';
 },{kind,logo});
 await page.addScriptTag({path:path.join(ROOT,'registry_popovers.js')});
 const dismiss=app.split('\n').filter(line=>line.startsWith("document.addEventListener('click',event=>{const drawer=$('#applicationFilters')")||line.startsWith("document.addEventListener('click',event=>{const drawer=$('#edrMonitoringAdvanced')"));
 assert.equal(dismiss.length,2);await page.addScriptTag({content:dismiss.join('\n')});
}
async function multiCheck(page,selector,indices){
 const details=page.locator(selector);
 const closedFlow=await details.evaluate(n=>{if(n.tagName!=='DETAILS')return null;const section=n.closest('.application-filter-section,.edr-monitoring-filter-section');return{nextTop:section.nextElementSibling.getBoundingClientRect().top,height:section.getBoundingClientRect().height};});
 if(closedFlow)await details.locator('summary').click();
 const inputs=details.locator('input[type="checkbox"]');
 for(const i of indices){await inputs.nth(i).check();if(await details.evaluate(n=>n.tagName==='DETAILS'))assert.equal(await details.evaluate(n=>n.open),true,'selecting a value keeps dropdown open');}
 await inputs.nth(indices[0]).uncheck();if(await details.evaluate(n=>n.tagName==='DETAILS'))assert.equal(await details.evaluate(n=>n.open),true,'deselection keeps dropdown open');
 await inputs.nth(indices[0]).check();
 const geometry=await details.locator('label').evaluateAll(labels=>labels.map(label=>{
  const input=label.querySelector('input'),box=input.getBoundingClientRect();let text;
  if(label.querySelector('span'))text=label.querySelector('span').getBoundingClientRect();
  else{const range=document.createRange(),node=[...label.childNodes].find(n=>n.nodeType===Node.TEXT_NODE&&n.textContent.trim());range.selectNodeContents(node);text=range.getBoundingClientRect();}
  return{checked:input.checked,centerDelta:Math.abs((box.top+box.bottom-text.top-text.bottom)/2),gap:text.left-box.right,input:{left:box.left,top:box.top,width:box.width,height:box.height},text:{left:text.left,top:text.top,width:text.width,height:text.height}};
 }));
 for(const g of geometry){assert.ok(g.centerDelta<=1,'checkbox centers against corresponding text');assert.ok(g.gap>=6&&g.gap<=8,'consistent checkbox/text gap');}
 assert.equal(await inputs.evaluateAll(ns=>ns.filter(n=>n.checked).length),indices.length);
 if(closedFlow){const openFlow=await details.evaluate(n=>{const panel=n.querySelector('.multi-panel'),section=n.closest('.application-filter-section,.edr-monitoring-filter-section'),r=panel.getBoundingClientRect(),next=section.nextElementSibling.getBoundingClientRect();return{nextTop:next.top,panelTop:r.top,panelBottom:r.bottom,panelHeight:r.height,panelPosition:getComputedStyle(panel).position,topLayer:panel.matches(':popover-open'),fixedClass:n.classList.contains('popover-fixed'),sectionBottom:section.getBoundingClientRect().bottom};});assert.equal(openFlow.panelPosition,'static');assert.equal(openFlow.topLayer,false);assert.equal(openFlow.fixedClass,false);assert.ok(openFlow.nextTop>=openFlow.panelBottom,'following filter does not overlap expanded choices');assert.ok(openFlow.nextTop-closedFlow.nextTop>=openFlow.panelHeight-1,'expanding choices moves following filters down');flowChecks.push({selector,theme:await page.evaluate(()=>document.documentElement.dataset.theme),closedFlow,openFlow});}
 return geometry;
}
async function verifyDrawerDismissAndScroll(page,kind,theme){
 const registry=kind==='registry',owner=registry?'#applicationFilters':'#edrMonitoringAdvanced',id=registry?'#applicationFilterPanel':'#edrMonitoringFilterPanel',summary=registry?'#applicationFiltersSummary':'#edrMonitoringFilterSummary',fields=registry?'.application-filter-fields':'.edr-monitoring-filter-fields';
 const backdrop=await page.locator(owner).evaluate(n=>({content:getComputedStyle(n,'::before').content,background:getComputedStyle(n,'::before').backgroundColor}));assert.equal(backdrop.content,'none','drawer creates no dimming overlay');
 await page.locator('main:not([hidden]) h1').click();await page.waitForFunction(selector=>!document.querySelector(selector).open,owner);assert.equal(await page.locator(owner).evaluate(n=>n.open),false,'real outside click closes drawer');
 await page.locator(summary).click();await page.setViewportSize({width:390,height:420});await page.waitForTimeout(100);
 const panel=page.locator(id),scroller=panel.locator(fields);const before=await panel.evaluate((n,fields)=>{const f=n.querySelector(fields),h=n.querySelector('.filter-panel-header').getBoundingClientRect();return{headerTop:h.top,headerBottom:h.bottom,scrollHeight:f.scrollHeight,clientHeight:f.clientHeight,overflow:getComputedStyle(f).overflowY,pageScrollY:scrollY};},fields);
 assert.equal(before.overflow,'auto');assert.ok(before.scrollHeight>before.clientHeight,'short viewport provides drawer scrolling');await scroller.evaluate(n=>n.scrollTop=n.scrollHeight);
 const after=await panel.evaluate((n,fields)=>{const f=n.querySelector(fields),h=n.querySelector('.filter-panel-header').getBoundingClientRect(),last=f.lastElementChild.getBoundingClientRect(),r=f.getBoundingClientRect();return{headerTop:h.top,headerBottom:h.bottom,scrollTop:f.scrollTop,lastTop:last.top,lastBottom:last.bottom,fieldsBottom:r.bottom,pageScrollY:scrollY};},fields);
 assert.ok(after.scrollTop>0);assert.ok(after.lastBottom<=after.fieldsBottom+1&&after.lastTop>=after.headerBottom,'last filter is reachable inside drawer');assert.ok(Math.abs(after.headerTop-before.headerTop)<1&&Math.abs(after.headerBottom-before.headerBottom)<1,'drawer header stays pinned');assert.equal(after.pageScrollY,before.pageScrollY,'scrolling stays inside drawer');flowChecks.push({kind,theme,backdrop,outsideClickCloses:true,shortViewport:{before,after}});
}
async function capture(page,kind,theme,id){
 await page.mouse.move(5,1050);await page.waitForTimeout(180);
 const states=await page.locator('#'+id+' .pqm-filter-heading').evaluateAll(headings=>headings.map(h=>({title:h.querySelector('.filter-accordion-title').textContent,active:h.parentElement.classList.contains('filter-active'),pending:h.parentElement.classList.contains('filter-pending'),count:h.querySelector('.pqm-filter-count').textContent,expanded:h.querySelector('.pqm-filter-toggle').getAttribute('aria-expanded')})));
 assert.ok(states.some(s=>!s.active&&!s.pending),'neutral filter is present');assert.ok(states.some(s=>s.active&&!s.pending),'applied filter is present');assert.ok(states.some(s=>s.pending&&s.expanded==='true'),'unapplied expanded filter is present');
 const bounds=await page.locator('#'+id).evaluate(n=>{const r=n.getBoundingClientRect();return{left:r.left,right:r.right,width:r.width,viewport:innerWidth,buttons:[...n.querySelectorAll('.filter-panel-header-actions button')].map(b=>{const x=b.getBoundingClientRect();return{left:x.left,right:x.right}})};});assert.ok(bounds.left>=0&&bounds.right<=bounds.viewport+1,'drawer remains inside viewport');assert.ok(bounds.buttons.every(b=>b.left>=bounds.left&&b.right<=bounds.right),'all header actions fit drawer');
 const filename=`${kind}-${theme}-full-page.png`;await page.screenshot({path:path.join(OUT,filename),fullPage:false});return {kind,theme,viewport:page.viewportSize(),states,bounds,screenshot:filename};
}
(async()=>{fs.mkdirSync(OUT,{recursive:true});const b=await chromium.launch({headless:true,ignoreDefaultArgs:['--hide-scrollbars'],executablePath:process.env.PQM_CHROMIUM_EXECUTABLE});try{
for(const theme of ['light','dark']){
 // Registry: real draft rendering and applied-count calculation, synthetic rows.
 const p=await f.makeAuxPage(b,theme,'applicationsView',1920,1080);await globals(p);await chrome(p,'applications');
 await p.evaluate(()=>{
  window.officerFilter='Дмитро САВВА';document.querySelector('#applicationOfficerFilter').innerHTML='<option value="">Усі</option><option selected>Дмитро САВВА</option>';
  document.querySelector('#profileSelect').innerHTML='<option>Мій профіль</option>';document.querySelector('#resultInfo').textContent='12 синтетичних заявок · локальна візуальна перевірка';
  document.querySelector('#applicationsTable thead').innerHTML='<tr>'+['ID заявки','Постачальник','Код','Категорія','Статус Prozorro','УО протоколу','Дата подання'].map(x=>'<th>'+x+'</th>').join('')+'</tr>';
  document.querySelector('#applicationsTable tbody').innerHTML=Array.from({length:12},(_,i)=>'<tr><td>TEST-'+(1200+i)+'</td><td>Тестовий постачальник '+(i+1)+'</td><td>990000'+String(i+1).padStart(2,'0')+'</td><td>'+['Їжа','Пальне','Інше'][i%3]+'</td><td>Допущено</td><td>Дмитро САВВА</td><td>16.11.2026 10:30</td></tr>').join('');
  document.querySelector('#footerInfo').textContent='Показано 12 із 12 · синтетичні дані';
 });
 await p.addScriptTag({content:['updateMultiSummary','renderDynamicFilter','updateApplicationFilterStyles'].map(source).join('\n')});
 await p.evaluate(()=>{renderDynamicFilter('supplierCodeFilter',[{code:'99000001',name:'Тестовий постачальник Альфа'},{code:'99000002',name:'Тестовий постачальник Бета'},{code:'99000003',name:'Тестовий постачальник Гамма'},{code:'99000004',name:'Тестовий постачальник Дельта'}],filterSelections.supplier,x=>x.code,x=>x.code+' · '+x.name,'Усі постачальники');updateApplicationFilterStyles();});
 await p.locator('#applicationFiltersSummary').click();await p.locator('[data-application-filter-section="supplier_codes"] .pqm-filter-toggle').click();
 const registryGeometry=await multiCheck(p,'#supplierCodeFilter',[0,1,2]);assert.equal(await p.locator('[data-application-filter-section="supplier_codes"] .pqm-filter-count').textContent(),'');assert.equal(await p.evaluate(()=>filterSelections.supplier.size),0,'draft supplier choices are not applied');
 records.push({...await capture(p,'registry',theme,'applicationFilterPanel'),checkboxes:registryGeometry});await verifyDrawerDismissAndScroll(p,'registry',theme);await p.close();
 // EDR: shipped multi-select draft and applied-count handlers.
 const e=await f.makeAuxPage(b,theme,'edrMonitoringView',1920,1080);await globals(e);await chrome(e,'edrMonitoring');
 await e.evaluate(()=>{
  window.edrMonitoringStatusSelections={edr_status:new Set(),prozorro_status:new Set()};window.edrMonitoringStatusDrafts={edr_status:new Set(),prozorro_status:new Set()};window.edrMonitoringSort='freshness';window.edrMonitoringDirection='asc';window.edrMonitoringPage=1;window.saveEdrMonitoringFilters=()=>{};window.loadEdrMonitoring=()=>{};
  document.querySelector('#edrMonitoringType').value='individual_entrepreneur';
  document.querySelector('#edrMonitoringEdr .multi-panel').innerHTML=['Зареєстровано','В стані припинення','Порушено справу про банкрутство','Припинено'].map(value=>'<label><input type="checkbox" value="'+value+'"> '+value+'</label>').join('');
  document.querySelectorAll('#edrMonitoringKpis strong').forEach((n,i)=>n.textContent=[12,8,4,3,2,1][i]);
  document.querySelector('#edrMonitoringBody').innerHTML=Array.from({length:8},(_,i)=>'<tr><td><input type="checkbox"></td><td><span class="edr-freshness current">Актуально</span></td><td>990000'+String(i+1).padStart(2,'0')+'</td><td>Тестовий постачальник '+(i+1)+'</td><td>Тестове підприємство '+(i+1)+'</td><td>Тест '+(i+1)+'</td><td>Іван ТЕСТОВИЙ</td><td>Зареєстровано</td><td>Допущено</td><td>—</td><td>16.11.2026</td><td>19.11.2026</td><td>Тестова УО</td><td>—</td></tr>').join('');document.querySelector('#edrMonitoringPageInfo').textContent='8 синтетичних записів · зовнішні системи не використовуються';
 });
 await e.addScriptTag({content:['edrMonitoringParams','edrMonitoringFilterIsActive','edrMonitoringFilterValueCount','updateEdrMonitoringMultiSummary','bindEdrMonitoringStatusMulti','updateEdrMonitoringFilters'].map(source).join('\n')});
 await e.evaluate(()=>{bindEdrMonitoringStatusMulti('edrMonitoringEdr','edr_status');updateEdrMonitoringFilters();});
 await e.locator('#edrMonitoringFilterSummary').click();await e.locator('[data-edr-filter-section="edr_status"] .pqm-filter-toggle').click();
 const edrGeometry=await multiCheck(e,'#edrMonitoringEdr',[0,1,2]);assert.equal(await e.locator('[data-edr-filter-section="edr_status"] .pqm-filter-count').textContent(),'');assert.equal(await e.evaluate(()=>edrMonitoringParams().edr_status),'','draft statuses do not reach query parameters');records.push({...await capture(e,'edr',theme,'edrMonitoringFilterPanel'),checkboxes:edrGeometry});await verifyDrawerDismissAndScroll(e,'edr',theme);await e.close();
 // Officer statistics: shipped statistics UI and synthetic request responses.
 let setup=prefix.slice(prefix.indexOf('async function verifyRealStatisticsSelection'),prefix.indexOf("  const selected=page.locator('#queueStatisticsRows"))+'return page;}';
 setup=setup.replace("await makeAuxPage(browser,theme,'workQueueView',1280,800)","await makePage(browser,theme,1920,1080)").replace('category:[],dk_code:[]',"category:['Їжа','Пальне'],dk_code:['02100000-6','03000000-1','45000000-7']");
 const create=new Function('require','__dirname',prefix+'\n'+setup.replace('verifyRealStatisticsSelection','setupContext')+'\nreturn setupContext;')(require,__dirname);
 const w=await create(b,theme);await chrome(w,'workQueue');
 const captions=await w.locator('#queueStatisticsFromField,#queueStatisticsToField,#queueStatisticsGroupField').evaluateAll(ns=>ns.map(n=>{const s=getComputedStyle(n);return{id:n.id,backgroundColor:s.backgroundColor,backgroundImage:s.backgroundImage,border:s.borderWidth,shadow:s.boxShadow,font:s.font,color:s.color,before:getComputedStyle(n,'::before').content,after:getComputedStyle(n,'::after').content};}));
 for(const c of captions){assert.equal(c.backgroundColor,'rgba(0, 0, 0, 0)');assert.equal(c.backgroundImage,'none');assert.equal(c.border,'0px');assert.equal(c.shadow,'none');assert.equal(c.font,captions[0].font);assert.equal(c.color,captions[0].color);}
 await w.mouse.move(5,1050);await w.screenshot({path:path.join(OUT,`officer-${theme}-caption-full-page.png`),fullPage:false});await w.locator('.queue-statistics-card').screenshot({path:path.join(OUT,`officer-${theme}-statistics-context.png`)});
 await w.locator('#queueStatisticsFilterToggle').click();await w.locator('[data-statistics-filter-section="supplier_type"] .pqm-filter-toggle').click();await w.locator('[data-statistics-filter="supplier_type"]').selectOption('individual_entrepreneur');await w.waitForTimeout(100);
 await w.locator('[data-statistics-filter-section="dk_code"] .pqm-filter-toggle').click();const dkGeometry=await multiCheck(w,'#queueStatisticsDkOptions',[0,1]);assert.equal(await w.locator('[data-statistics-filter-section="dk_code"] .pqm-filter-count').textContent(),'');
 records.push({...await capture(w,'officer',theme,'queueStatisticsFilterPanel'),checkboxes:dkGeometry,captions});await w.close();
}
fs.writeFileSync(path.join(OUT,'context-review-results.json'),JSON.stringify({result:'PASS',records,flowChecks},null,2));console.log(JSON.stringify({result:'PASS',screenshots:records.map(r=>r.screenshot),maxCheckboxCenterDelta:Math.max(...records.flatMap(r=>r.checkboxes.map(c=>c.centerDelta)))},null,2));
}finally{await b.close();}})().catch(e=>{console.error(e);process.exitCode=1});
