const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..'),OUT=process.env.PQM_UNIFIED_EVIDENCE_DIR;
assert.ok(OUT,'PQM_UNIFIED_EVIDENCE_DIR must name an isolated evidence directory');
const read=f=>fs.readFileSync(path.join(ROOT,f),'utf8');
const source=read('validation/uo_work_page_layout_browser.cjs');
const fixtures=new Function('require','__dirname',source.slice(0,source.indexOf('(async()=>{'))+'\nreturn {makePage,makeAuxPage};')(require,__dirname);
const panels=[['registry','applicationsView','applicationFilterPanel'],['officer','workQueueView','queueStatisticsFilterPanel'],['edr','edrMonitoringView','edrMonitoringFilterPanel']];
const records=[],shots=[],failures=[];let checks=0;
function check(ok,label,context){checks++;if(!ok)failures.push({label,...context});}
async function inspect(page,id){return page.locator('#'+id+' .pqm-filter-heading').evaluateAll(nodes=>nodes.map(h=>{
 const box=n=>{const r=n.getBoundingClientRect();return{left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height}};
 const t=h.querySelector('.pqm-filter-toggle'),c=h.querySelector('.pqm-filter-count'),slot=h.querySelector('.filter-row-actions'),s=getComputedStyle(h),ps=getComputedStyle(h,'::after'),hr=box(h);
 const textRange=document.createRange();textRange.selectNodeContents(t.querySelector('.filter-accordion-title'));
 return{heading:hr,background:s.backgroundColor,font:getComputedStyle(t).font,toggleBackground:getComputedStyle(t).backgroundColor,title:[...textRange.getClientRects()].map(r=>({left:r.left,right:r.right,top:r.top,bottom:r.bottom})),count:box(c),countText:c.textContent,countHidden:c.hidden||c.textContent==='',slot:box(slot),buttons:[...slot.children].map(n=>({...box(n),hidden:n.hidden})),arrow:{left:hr.right-parseFloat(ps.right)-parseFloat(ps.width),right:hr.right-parseFloat(ps.right),top:hr.top+hr.height/2-6.5,bottom:hr.top+hr.height/2+6.5},outline:getComputedStyle(h.parentElement).outlineStyle,toggleOutline:getComputedStyle(t).outlineStyle};
}));}
const overlap=(a,b)=>Math.min(a.right,b.right)-Math.max(a.left,b.left)>.5&&Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>.5;
(async()=>{fs.mkdirSync(OUT,{recursive:true});const browser=await chromium.launch({headless:true,ignoreDefaultArgs:['--hide-scrollbars'],executablePath:process.env.PQM_CHROMIUM_EXECUTABLE});try{
for(const theme of ['light','dark'])for(const width of [1920,1280,800,390])for(const [kind,view,id] of panels){
 const page=kind==='officer'?await fixtures.makePage(browser,theme,width,1080):await fixtures.makeAuxPage(browser,theme,view,width,1080);
 await page.addScriptTag({path:path.join(ROOT,'registry_popovers.js')});
 if(kind==='registry'){await page.locator('#applicationFiltersSummary').click();}
 else if(kind==='edr'){await page.locator('#edrMonitoringFilterSummary').click();}
 else {await page.locator('#'+id).evaluate(n=>n.hidden=false);}
 const headActions=await page.locator('#'+id+' .filter-panel-header-actions button').evaluateAll(ns=>ns.map(n=>{const s=getComputedStyle(n),r=n.getBoundingClientRect();return{id:n.id,width:r.width,height:r.height,left:r.left,color:s.color,background:s.backgroundColor,svg:n.querySelector('path')?.getAttribute('d')||'',label:n.getAttribute('aria-label')};}));
 check(headActions.length===3&&headActions.every(b=>b.width===36&&b.height===36),'three identical 36px header actions',{theme,width,kind,headActions});
 check(headActions[0].svg==='M4 5h16M7 5l1 15h8l1-15M9 5V3h6v2'&&headActions[1].svg==='m5 12 4.5 4.5L19 7','trash, check, close ordering',{theme,width,kind});
 let baseline;
 for(const state of ['neutral','applied','pending']){
 await page.locator('#'+id).evaluate((panel,state)=>{panel.querySelectorAll('.pqm-filter-heading').forEach(h=>{const section=h.parentElement;section.classList.toggle('filter-active',state!=='neutral');section.classList.toggle('filter-pending',state==='pending');const c=h.querySelector('.pqm-filter-count');c.textContent=state==='neutral'?'':'2';c.hidden=state==='neutral';h.querySelector('.filter-row-apply').hidden=state!=='pending';h.querySelector('.filter-row-actions>button:last-child').hidden=state==='neutral';});},state);
 const rows=await inspect(page,id);baseline??=rows;
 for(let i=0;i<rows.length;i++){
 const r=rows[i],ctx={theme,width,kind,state,row:i,measurement:r};
 check(r.slot.width===58&&r.heading.height===42,'fixed compact dimensions',ctx);
 check(r.font===rows[0].font,'same font including DK',ctx);
 check(r.background===rows[0].background&&r.toggleBackground==='rgba(0, 0, 0, 0)','uniform full-width heading fill',ctx);
 check(Math.abs(r.count.left-rows[0].count.left)<1&&Math.abs(r.slot.left-rows[0].slot.left)<1&&Math.abs(r.arrow.left-rows[0].arrow.left)<1,'fixed counter, actions and arrow axes',ctx);
 check(Math.abs(r.count.left-baseline[i].count.left)<1&&Math.abs(r.slot.left-baseline[i].slot.left)<1,'no movement across states',ctx);
 check(r.countText===(state==='neutral'?'':'2'),'pending draft does not replace applied count',ctx);
 check(r.outline==='none'&&r.toggleOutline==='none','no nested pending outlines',ctx);
 for(const b of r.buttons.filter(b=>!b.hidden)){check(b.left>=r.slot.left-1&&b.right<=r.slot.right+1,'button inside its slot',ctx);check(!overlap(b,r.arrow),'button clear of arrow',ctx);}
 if(r.buttons.every(b=>!b.hidden))check(!overlap(...r.buttons),'buttons do not overlap',ctx);
 for(const text of r.title)for(const obstacle of [r.count,...r.buttons,r.arrow])check(!overlap(text,obstacle),'title clear of count/actions/arrow',ctx);
 }
 records.push({theme,width,kind,state,headActions,rows});
 if(width===1920){const p=path.join(OUT,`${kind}-${theme}-${state}.png`);await page.locator('#'+id).screenshot({path:p});shots.push(p);}
 }
 // Native accordion and keyboard interactions use the shipped component.
 const toggle=page.locator('#'+id+' .pqm-filter-toggle').first();await toggle.click();check(await toggle.getAttribute('aria-expanded')==='true','accordion opens',{theme,width,kind});if(width===1920)await page.locator('#'+id).screenshot({path:path.join(OUT,`${kind}-${theme}-expanded.png`)});await toggle.click();check(await toggle.getAttribute('aria-expanded')==='false','accordion closes',{theme,width,kind});
 await toggle.focus();await page.keyboard.press('Tab');check(await page.evaluate(()=>getComputedStyle(document.activeElement).outlineWidth==='2px'&&document.activeElement.matches(':focus-visible')),'keyboard focus remains visible',{theme,width,kind});
 // Open multiple options through the real popover handler (the original regression).
 if(kind==='officer'){const dk=page.locator('[data-statistics-filter-section="dk_code"]');await dk.locator('.pqm-filter-toggle').click();const options=dk.locator('input[type="checkbox"]');await options.nth(0).uncheck();await options.nth(1).uncheck();await options.nth(0).check();await options.nth(1).check();check(await dk.locator('.pqm-filter-toggle').getAttribute('aria-expanded')==='true','multiple DK selections keep accordion open',{theme,width,kind});await options.nth(0).uncheck();check(await dk.locator('.pqm-filter-toggle').getAttribute('aria-expanded')==='true','DK deselection keeps accordion open',{theme,width,kind});if(width===1920)await page.locator('#'+id).screenshot({path:path.join(OUT,`${kind}-${theme}-multi.png`)});}
 const target=kind==='registry'?'#supplierCodeFilter':kind==='edr'?'#edrMonitoringEdr':null;
 if(target){const details=page.locator(target);const section=details.locator('xpath=ancestor::*[contains(@class,"filter-section")][1]');await section.locator('.pqm-filter-toggle').click();
 await details.locator('.multi-panel').evaluate(n=>n.innerHTML='<label><input type="checkbox" value="a"><span>Перше синтетичне значення</span></label><label><input type="checkbox" value="b"><span>Друге синтетичне значення</span></label>');await details.locator('summary').click();
 await details.locator('input').nth(0).check();check(await details.evaluate(n=>n.open),'first selection keeps multi open',{theme,width,kind});await details.locator('input').nth(1).check();check(await details.evaluate(n=>n.open),'second selection keeps multi open',{theme,width,kind});await details.locator('input').nth(0).uncheck();check(await details.evaluate(n=>n.open),'deselection keeps multi open',{theme,width,kind});
 const alignment=await details.locator('label').first().evaluate(n=>{const b=n.querySelector('input').getBoundingClientRect(),t=n.querySelector('span').getBoundingClientRect();return{centerDelta:Math.abs((b.top+b.bottom-t.top-t.bottom)/2),gap:t.left-b.right};});check(alignment.centerDelta<=1&&alignment.gap>=6&&alignment.gap<=8,'checkbox vertically centered against text',{theme,width,kind,alignment});if(width===1920)await page.locator('#'+id).screenshot({path:path.join(OUT,`${kind}-${theme}-multi.png`)});
 }
 await page.close();
}
// Real EDR draft/apply/reset logic with synthetic sets and inert data loading.
for(const theme of ['light','dark']){
 const p=await fixtures.makeAuxPage(browser,theme,'edrMonitoringView',1920,1080);await p.addScriptTag({path:path.join(ROOT,'registry_popovers.js')});
 await p.evaluate(()=>{window.$=s=>document.querySelector(s);window.$$=s=>[...document.querySelectorAll(s)];window.edrMonitoringStatusSelections={edr_status:new Set(),prozorro_status:new Set()};window.edrMonitoringStatusDrafts={edr_status:new Set(),prozorro_status:new Set()};window.edrMonitoringSort='freshness';window.edrMonitoringDirection='asc';window.edrMonitoringPage=1;window.syncSharedFilterPresentation=()=>{};window.saveEdrMonitoringFilters=()=>{};window.loadEdrMonitoring=()=>{};document.querySelector('#edrMonitoringEdr .multi-panel').innerHTML='<label><input type="checkbox" value="a"> Чинний</label><label><input type="checkbox" value="b"> Припинено</label>';});
 const names=['edrMonitoringParams','edrMonitoringFilterIsActive','edrMonitoringFilterValueCount','updateEdrMonitoringMultiSummary','bindEdrMonitoringStatusMulti','updateEdrMonitoringFilters','applyEdrMonitoringFilter','clearEdrMonitoringFilter'];const app=read('app.js');await p.addScriptTag({content:names.map(name=>app.split('\n').find(l=>l.startsWith('function '+name+'('))).join('\n')});
 await p.evaluate(()=>{bindEdrMonitoringStatusMulti('edrMonitoringEdr','edr_status');updateEdrMonitoringFilters();});await p.locator('#edrMonitoringFilterSummary').click();const section=p.locator('[data-edr-filter-section="edr_status"]');await section.locator('.pqm-filter-toggle').click();await p.locator('#edrMonitoringEdr summary').click();await p.locator('#edrMonitoringEdr input').nth(0).check();await p.locator('#edrMonitoringEdr input').nth(1).check();
 check(await section.locator('.pqm-filter-count').textContent()==='','no draft count in EDR header',{theme});check(await p.evaluate(()=>edrMonitoringParams().edr_status)==='','draft is absent from API parameters',{theme});await p.evaluate(()=>applyEdrMonitoringFilter('edr_status'));check(await section.locator('.pqm-filter-count').textContent()==='2','applied EDR count is two',{theme});await p.evaluate(()=>clearEdrMonitoringFilter('edr_status'));check(await section.locator('.pqm-filter-count').textContent()==='','reset removes EDR applied count',{theme});await p.close();
}
// Statistics appearance and screenshots, keeping dark hover behavior unchanged.
for(const theme of ['light','dark']){
 const p=await fixtures.makePage(browser,theme,1920,1080);const label=p.locator('#queueStatisticsGroupField');const decoration=await label.evaluate(n=>{const s=getComputedStyle(n);return{background:s.backgroundColor,border:s.borderWidth}});check(decoration.background==='rgba(0, 0, 0, 0)'&&decoration.border==='0px','plain grouping caption',{theme,decoration});await label.screenshot({path:path.join(OUT,`group-${theme}.png`)});
 const row=p.locator('#queueStatisticsRows tr').first(),number=row.locator('button').first();await row.locator('th').hover();await p.waitForTimeout(180);await p.locator('.queue-statistics-table').screenshot({path:path.join(OUT,`table-${theme}-row.png`)});await number.hover();await p.waitForTimeout(180);check(await number.evaluate(n=>getComputedStyle(n).backgroundColor)===(theme==='light'?'rgb(168, 205, 245)':'rgba(255, 255, 255, 0.063)'),'distinct hovered number background',{theme});await p.locator('.queue-statistics-table').screenshot({path:path.join(OUT,`table-${theme}-number.png`)});await number.evaluate(n=>{n.setAttribute('aria-pressed','true');n.classList.add('is-selected');});await p.mouse.move(2,2);await p.waitForTimeout(180);if(theme==='light'){check(await number.evaluate(n=>getComputedStyle(n).backgroundColor)==='rgb(36, 92, 152)','selected number differs from hover',{theme});await number.hover();await p.waitForTimeout(180);check(await number.evaluate(n=>getComputedStyle(n).backgroundColor)==='rgb(36, 92, 152)','selected number stays distinct while hovered',{theme});await p.mouse.move(2,2);await p.waitForTimeout(180);}await p.locator('.queue-statistics-table').screenshot({path:path.join(OUT,`table-${theme}-selected.png`)});await p.close();
}
for(const theme of ['light','dark'])for(const width of [1920,1280,800,390]){const group=records.filter(r=>r.theme===theme&&r.width===width&&r.state==='applied');const ref=group[0];for(const r of group){check(JSON.stringify(r.headActions.map(({id,label,left,...style})=>style))===JSON.stringify(ref.headActions.map(({id,label,left,...style})=>style)),'header icons share colors, dimensions and artwork across panels',{theme,width,kind:r.kind});check(r.rows[0].font===ref.rows[0].font,'heading font identical across all panels',{theme,width,kind:r.kind});for(const state of ['neutral','applied','pending']){const current=records.find(x=>x.theme===theme&&x.width===width&&x.kind===r.kind&&x.state===state),base=records.find(x=>x.theme===theme&&x.width===width&&x.kind===ref.kind&&x.state===state);check(current.rows[0].background===base.rows[0].background,'identical state background across all panels',{theme,width,kind:r.kind,state});}}}
fs.writeFileSync(path.join(OUT,'unified-results.json'),JSON.stringify({checks,failures,records,shots},null,2));console.log(JSON.stringify({checks,failures:failures.length,samples:failures.slice(0,3)},null,2));assert.equal(failures.length,0,'all unified panel checks pass');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1});
