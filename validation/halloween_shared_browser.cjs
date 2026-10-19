const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require('C:/Users/User/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const {fixture}=require('./halloween_integration_browser.cjs');
const root=path.resolve(__dirname,'..'),out=path.join(root,'evidence','halloween-shared');fs.mkdirSync(out,{recursive:true});
const working='table,.card,.table-card,.module-kpis,.module-kpis>article,.kpi,.kpi-row>article,.kpi-card,.heading-metrics,.history-total,.operational-type-kpis,.work-queue-kpis';
async function data(page){await page.addScriptTag({content:fs.readFileSync(path.join(root,'validation/halloween_shared_fixture.js'),'utf8')});await page.waitForTimeout(40)}
async function switchView(page,id){await page.evaluate(id=>document.querySelectorAll('main').forEach(e=>e.hidden=e.id!==id),id);await page.waitForTimeout(90)}
async function geometry(page){return page.evaluate(()=>{
 const v=[...document.querySelectorAll('main')].find(e=>!e.hidden),selectors='h1,h2,button,input,select,table,.card,.module-kpis,.kpi,.history-total';
 return{scroll:[document.documentElement.scrollWidth,document.documentElement.scrollHeight],elements:[...v.querySelectorAll(selectors)].filter(e=>e.getBoundingClientRect().width&&e.getBoundingClientRect().height).map(e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return{tag:e.tagName,id:e.id,rect:[r.x,r.y,r.width,r.height],color:s.color,background:s.backgroundColor}})};
})}
async function state(page){return page.evaluate(working=>{
 const host=document.querySelector('#pqmHalloweenHost'),view=document.getElementById(host.dataset.view),r=host.getBoundingClientRect(),s=host.querySelector('.halloween-flight-sprite');
 const overlaps=host.dataset.safe==='true'?[...view.querySelectorAll(working)].filter(e=>{const b=e.getBoundingClientRect();return b.width&&b.height&&b.left<r.right&&b.right>r.left&&b.top<r.bottom&&b.bottom>r.top}).map(e=>e.id||e.className||e.tagName):[];
 return{view:host.dataset.view,landscape:view.classList.contains('halloween-workspace'),safe:host.dataset.safe==='true',reason:host.dataset.reason,hostCount:document.querySelectorAll('#pqmHalloweenHost').length,parent:host.parentElement.id,visibility:getComputedStyle(host).visibility,host:[r.x,r.y,r.width,r.height],instances:host.querySelectorAll('.halloween-flight-sprite').length,canvases:host.querySelectorAll('canvas').length,frames:__trailFrames.size,maxFrames:__maxTrailFrames,pending:__pendingFlightTimers.size,delays:[...__flightDelays],overlaps,pointer:getComputedStyle(host).pointerEvents,extraClouds:getComputedStyle(view,'::after').backgroundImage,originalNode:!window.__sharedSprite||s===window.__sharedSprite,originalCanvas:!window.__sharedCanvas||host.querySelector('canvas')===window.__sharedCanvas};
},working)}
(async()=>{const browser=await chromium.launch({headless:true,executablePath:'C:/Users/User/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe'});const report={matrix:[],checks:[]};try{
if(!process.env.PQM_SHARED_FUNCTIONAL_ONLY)for(const width of [1440,390])for(const zoom of (width===1440?[1,1.25]:[1]))for(const theme of ['light','dark']){
 const baseline=await fixture(browser,{candidate:false,width,zoom,theme}),f=await fixture(browser,{width,zoom,theme});
 await data(baseline.page);await data(f.page);
 const ids=await f.page.locator('main').evaluateAll(es=>es.map(e=>e.id));
 if(width===1440&&zoom===1){await f.page.waitForSelector('.halloween-flight-sprite');await f.page.evaluate(()=>{window.__sharedSprite=document.querySelector('.halloween-flight-sprite');window.__sharedCanvas=document.querySelector('.halloween-broom-trail');const a=__sharedSprite.getAnimations()[0];a.pause();a.currentTime=a.effect.getTiming().duration*.45})}
 const delayCount=await f.page.evaluate(()=>__flightDelays.length);
 for(const id of ids){
  await switchView(baseline.page,id);await switchView(f.page,id);
  assert.deepEqual(await geometry(f.page),await geometry(baseline.page),`${id} geometry ${theme}/${zoom}/${width}`);
  const s=await state(f.page);assert.equal(s.hostCount,1);assert.equal(s.parent,'applicationShell');assert.equal(s.pointer,'none');assert.equal(s.safe,s.landscape);assert(s.frames<=1&&s.maxFrames<=1&&s.instances<=1&&s.canvases<=1&&s.pending<=1);if(theme==='dark'&&s.landscape)assert(s.extraClouds.includes('halloween-workqueue-dark.webp'));else assert.equal(s.extraClouds,'none');
  if(!s.safe){assert.equal(s.visibility,'hidden');assert.equal(s.frames,0)}
  if(width===1440&&zoom===1){assert(s.originalNode&&s.originalCanvas);assert.equal(s.delays.length,delayCount);await f.page.screenshot({path:path.join(out,`${theme}-${id}.png`),fullPage:false})}
  report.matrix.push({theme,zoom,width,...s});
 }
 assert.deepEqual(f.errors,[]);await baseline.context.close();await f.context.close();
}
// Pending real delay persists across every tab, without replacing browser timers.
const waiting=await fixture(browser,{fast:false});const p=waiting.page;
const ids=await p.locator('main').evaluateAll(es=>es.map(e=>e.id)),timer=await p.evaluate(()=>[...__pendingFlightTimers][0]);
assert(timer!==undefined);
for(const id of ids){await switchView(p,id);assert.equal(await p.evaluate(()=>[...__pendingFlightTimers][0]),timer);assert.equal(await p.evaluate(()=>__flightDelays.length),1)}
await switchView(p,'workQueueView');const delay=await p.evaluate(()=>__flightDelays[0]);assert(delay>=20000&&delay<=30000);
assert.equal(await p.locator('.halloween-flight-sprite').count(),0);
report.checks.push({waitingTimerPreservedAcross13Views:true,delay});await waiting.context.close();
// Natural mid-flight tab switches preserve the same animation and progress.
const f=await fixture(browser),page=f.page;await page.waitForSelector('.halloween-flight-sprite');
await page.addScriptTag({content:fs.readFileSync(path.join(root,'halloween_motion.js'),'utf8')});assert.equal(await page.locator('#pqmHalloweenHost').count(),1);assert.equal(await page.locator('.halloween-cat-eyes').count(),1);
await page.evaluate(()=>{window.__sharedSprite=document.querySelector('.halloween-flight-sprite');window.__sharedCanvas=document.querySelector('.halloween-broom-trail');window.__flightAnimation=__sharedSprite.getAnimations()[0];__flightAnimation.currentTime=__flightAnimation.effect.getTiming().duration*.3});
let previous=0;
for(const id of ['referencesView','applicationsView','edrMonitoringView','messagesView','procurementsView','workQueueView']){
 await switchView(page,id);const t=await page.evaluate(()=>__flightAnimation.currentTime);assert(t>=previous);previous=t;const s=await state(page);assert(s.originalNode&&s.originalCanvas);assert.equal(s.delays.length,1);assert.equal(s.safe,s.landscape);
}
report.checks.push({sameFlightAndCanvasAcrossSafeAndPausedViews:true,progressContinues:true});
// Layout changes make safety reactive without allocating a new cycle.
await page.evaluate(()=>{const b=document.createElement('div');b.className='card';b.id='safetyFixture';b.textContent='Fixture control';b.style.cssText='position:fixed;top:75px;left:400px;width:400px;height:140px';document.querySelector('#workQueueView .module-heading').append(b)});
await page.waitForTimeout(120);assert.equal((await state(page)).safe,true);assert((await state(page)).frames<=1);
await page.evaluate(()=>document.querySelector('#safetyFixture').remove());await page.waitForTimeout(120);assert((await state(page)).safe);assert((await state(page)).originalNode);
// Finishing a cycle schedules one pause. Next sprite alternates and is bounded.
const first=await page.locator('.halloween-flight-sprite svg').getAttribute('viewBox');
await page.evaluate(()=>document.querySelector('.halloween-flight-sprite').dispatchEvent(new AnimationEvent('animationend',{animationName:'pqm-witch-cross'})));await page.waitForTimeout(180);
assert.notEqual(await page.locator('.halloween-flight-sprite svg').getAttribute('viewBox'),first);assert.equal(await page.locator('#pqmHalloweenHost').count(),1);assert.equal(await page.locator('canvas.halloween-broom-trail').count(),1);
await page.emulateMedia({reducedMotion:'reduce'});await page.waitForTimeout(180);assert.equal(await page.locator('.halloween-flight-sprite').count(),0);assert.equal(await page.evaluate(()=>__trailFrames.size+__pendingFlightTimers.size),0);
await page.emulateMedia({reducedMotion:'no-preference'});await page.waitForTimeout(180);
await page.evaluate(()=>{const i=document.querySelector('#halloweenDecorationEnabled');i.checked=false;i.dispatchEvent(new Event('change'))});await page.waitForTimeout(120);assert.equal(await page.locator('.halloween-flight-sprite').count(),0);assert.equal(await page.evaluate(()=>__trailFrames.size+__pendingFlightTimers.size),0);
await page.evaluate(()=>{const i=document.querySelector('#halloweenDecorationEnabled');i.checked=true;i.dispatchEvent(new Event('change'))});await page.waitForTimeout(180);
await page.evaluate(()=>__setNow('2026-10-31T22:00:00Z'));await page.waitForTimeout(120);assert.equal(await page.locator('.halloween-flight-sprite').count(),0);assert.equal(await page.evaluate(()=>__trailFrames.size+__pendingFlightTimers.size),0);
const boundaries=await page.evaluate(()=>['2026-09-30T20:59:59Z','2026-09-30T21:00:00Z','2026-10-31T21:59:59Z','2026-10-31T22:00:00Z'].map(d=>PqmHalloweenSeason.state(new Date(d)).available));assert.deepEqual(boundaries,[false,true,true,false]);
assert.deepEqual(f.errors,[]);report.checks.push({workingSurfacesDoNotPauseFlight:true,oneController:true,alternation:true,reducedMotion:true,manualOff:true,kyivBoundaries:boundaries});await f.context.close();
if(!process.env.PQM_SHARED_FUNCTIONAL_ONLY){const real=await fixture(browser,{fast:false});await real.page.waitForTimeout(19000);assert.equal(await real.page.locator('.halloween-flight-sprite').count(),0);await real.page.waitForSelector('.halloween-flight-sprite',{timeout:13000});report.checks.push({realFirstFlightDelay:await real.page.evaluate(()=>__flightDelays[0]),noEarlyFlight:true});await real.context.close()}
fs.writeFileSync(path.join(out,'MATRIX.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({result:'PASS',cases:report.matrix.length,checks:report.checks},null,2));
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exitCode=1});
