const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('C:/Users/User/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const {fixture}=require('./halloween_integration_browser.cjs');
const root=path.resolve(__dirname,'..'),out=path.join(root,'evidence','permanent-cat');fs.mkdirSync(out,{recursive:true});
const assetSha='a073d1a06748ef8b52e5b13b72e2abc79a75379e4576b387c53c12ded3fc70a9';
async function state(page){return page.evaluate(()=>({season:document.documentElement.dataset.halloween,cat:document.documentElement.dataset.pqmCat,src:document.querySelector('img.halloween-cat').getAttribute('src'),visible:getComputedStyle(document.querySelector('img.halloween-cat')).display!=='none',eyes:getComputedStyle(document.querySelector('.halloween-cat-eyes')).display!=='none',disabled:document.querySelector('#halloweenDecorationEnabled').disabled,checked:document.querySelector('#halloweenDecorationEnabled').checked,label:document.querySelector('#halloweenDecorationEnabled').nextElementSibling.firstChild.textContent.trim(),flightSprites:document.querySelectorAll('.halloween-flight-sprite').length,cats:document.querySelectorAll('img.halloween-cat').length,eyeOverlays:document.querySelectorAll('.halloween-cat-eyes').length,motionScripts:document.querySelectorAll('script[src="halloween_motion.js"]').length,catScripts:document.querySelectorAll('script[src="halloween_cat_season.js?v=1"]').length}))}
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Users/User/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe'}),report={assetSha256:assetSha,cases:[],checks:[]};
 try{
  for(const theme of ['light','dark'])for(const zoom of [1,1.25]){
   const f=await fixture(browser,{theme,zoom,width:zoom===1?1440:1024,startDate:'2026-11-01T00:10:00Z',fast:false});
   const page=f.page,initial=await state(page);
   assert.equal(initial.season,'off');assert.equal(initial.cat,'on');assert.equal(initial.src,'assets/pqm-cat-no-hat.png');assert(initial.visible);assert(initial.eyes);assert.equal(initial.disabled,false);assert.equal(initial.checked,true);assert.equal(initial.label,'Котик PQM');assert.equal(initial.flightSprites,0);assert.equal(initial.cats,1);assert.equal(initial.eyeOverlays,1);assert.equal(initial.motionScripts,1);assert.equal(initial.catScripts,1);
   await page.waitForFunction(()=>document.querySelector('img.halloween-cat').complete&&document.querySelector('img.halloween-cat').naturalWidth===720);
   const geometry=await page.evaluate(()=>{const c=document.querySelector('img.halloween-cat').getBoundingClientRect(),e=document.querySelector('.halloween-cat-eyes').getBoundingClientRect();return{x:c.x,y:c.y,width:c.width,height:c.height,eyeOverlay:[e.x,e.y,e.width,e.height],pointer:getComputedStyle(document.querySelector('.halloween-cat-eyes')).pointerEvents}});
   assert.deepEqual(geometry.eyeOverlay,[geometry.x,geometry.y,geometry.width,geometry.height]);assert.equal(geometry.pointer,'none');
   await page.screenshot({path:path.join(out,`post-season-${theme}-${zoom===1?'100':'125'}.png`),fullPage:true});
   if(zoom===1){await page.evaluate(()=>document.querySelector('#accountSettingsDialog').showModal());await page.screenshot({path:path.join(out,`post-season-toggle-${theme}.png`),fullPage:true});await page.locator('#halloweenDecorationEnabled').click();await page.waitForFunction(()=>document.documentElement.dataset.pqmCat==='off');assert.equal((await state(page)).checked,false);await page.locator('#halloweenDecorationEnabled').click();await page.waitForFunction(()=>document.documentElement.dataset.pqmCat==='on');assert.equal((await state(page)).checked,true);await page.evaluate(()=>document.querySelector('#accountSettingsDialog').close())}
   await page.mouse.move(1200,700);await page.evaluate(()=>document.dispatchEvent(new PointerEvent('pointermove',{bubbles:true,pointerType:'mouse',clientX:innerWidth-20,clientY:innerHeight-20})));await page.waitForTimeout(100);
   const gaze=await page.evaluate(()=>({animations:document.querySelector('.pqm-cat-gaze').getAnimations().length,transform:getComputedStyle(document.querySelector('.pqm-cat-gaze')).transform,environment:document.documentElement.dataset.pqmEnvironment,season:document.documentElement.dataset.halloween,cat:document.documentElement.dataset.pqmCat,overlay:document.querySelector('.halloween-cat-eyes').getBoundingClientRect().toJSON(),shellHidden:document.querySelector('#applicationShell').hidden}));assert(gaze.animations>0,JSON.stringify({gaze,errors:f.errors}));assert.notEqual(gaze.transform,'none');
   await page.evaluate(()=>{const input=document.querySelector('#halloweenDecorationEnabled');input.checked=false;input.dispatchEvent(new Event('change',{bubbles:true}))});await page.waitForTimeout(60);
   let after=await state(page);assert.equal(after.cat,'off');assert.equal(after.checked,false);assert.equal(after.disabled,false);assert.equal(after.label,'Котик PQM');assert.equal(after.visible,false);
   await page.evaluate(()=>{const input=document.querySelector('#halloweenDecorationEnabled');input.checked=true;input.dispatchEvent(new Event('change',{bubbles:true}))});await page.waitForTimeout(60);
   after=await state(page);assert.equal(after.cat,'on');assert(after.visible);assert.equal(await page.evaluate(()=>localStorage.getItem('pqm.halloween.cat.enabled.v1')),'1');
   report.cases.push({theme,zoom,initial,gaze,geometry,preferenceOffOn:true,localStoragePersisted:true,errors:f.errors,blocked:f.blocked});assert.deepEqual(f.errors,[]);assert.deepEqual(f.blocked,[]);await f.context.close();
  }
  for(const theme of ['light','dark']){
   const seasonal=await fixture(browser,{theme,startDate:'2026-10-19T12:00:00Z',fast:false}),before=await state(seasonal.page);
   assert.equal(before.season,'on');assert.equal(before.cat,'on');assert.equal(before.src,'assets/halloween-witch-cat.webp');assert(before.visible);assert.equal(before.label,'Halloween · святкове оформлення');assert.equal(before.disabled,false);
   await seasonal.page.screenshot({path:path.join(out,`halloween-season-${theme}.png`),fullPage:true});report.checks.push({theme,halloweenSeasonImagePreserved:true,oldHalloweenLabel:true});assert.deepEqual(seasonal.errors,[]);await seasonal.context.close();
  }
  const boundary=await fixture(browser,{startDate:'2026-10-31T21:59:59Z',fast:false});
  const p=boundary.page;
  assert.equal((await state(p)).season,'on');
  await p.evaluate(()=>__setNow('2026-10-31T21:59:59Z'));assert.equal((await state(p)).season,'on');
  await p.evaluate(()=>__setNow('2026-10-31T22:00:00Z'));await p.waitForFunction(()=>document.documentElement.dataset.halloween==='off'&&document.documentElement.dataset.pqmCat==='on'&&document.querySelector('img.halloween-cat').getAttribute('src')==='assets/pqm-cat-no-hat.png');
  const afterBoundary=await state(p);assert.equal(afterBoundary.label,'Котик PQM');assert.equal(afterBoundary.disabled,false);assert(afterBoundary.visible);assert.equal(afterBoundary.flightSprites,0);
  const policy=await p.evaluate(()=>['2026-10-31T21:59:59Z','2026-10-31T22:00:00Z'].map(d=>PqmHalloweenSeason.state(new Date(d)).available));assert.deepEqual(policy,[true,false]);
  await p.evaluate(()=>{const input=document.querySelector('#halloweenDecorationEnabled');input.checked=false;input.dispatchEvent(new Event('change',{bubbles:true}))});await p.waitForTimeout(60);assert.equal((await state(p)).cat,'off');
  await p.reload({waitUntil:'load'});await p.addScriptTag({content:fs.readFileSync(path.join(root,'validation/halloween_integration_fixture.js'),'utf8')});await p.evaluate(()=>HalloweenIntegrationFixture.install({panel:false}));await p.waitForTimeout(100);
  const reloaded=await state(p);assert.equal(reloaded.season,'off');assert.equal(reloaded.cat,'off');assert.equal(reloaded.checked,false);assert.equal(reloaded.disabled,false);assert.equal(reloaded.src,'assets/pqm-cat-no-hat.png');
  report.checks.push({kyivUtcBoundary:['2026-10-31T21:59:59Z','2026-10-31T22:00:00Z'],policy,openTabSwitch:true,disabledPreferenceSurvivesReload:true});assert.deepEqual(boundary.errors,[]);assert.deepEqual(boundary.blocked,[]);await boundary.context.close();
  const storage=await fixture(browser,{startDate:'2026-11-01T00:10:00Z',storageDisabled:true,fast:false});
  let unavailable=await state(storage.page);assert.equal(unavailable.cat,'on');assert.equal(unavailable.disabled,false);
  await storage.page.evaluate(()=>{const i=document.querySelector('#halloweenDecorationEnabled');i.checked=false;i.dispatchEvent(new Event('change',{bubbles:true}))});await storage.page.waitForTimeout(60);
  unavailable=await state(storage.page);assert.equal(unavailable.cat,'off');assert.equal(unavailable.visible,false);assert.deepEqual(storage.errors,[],JSON.stringify(storage.errors));assert.deepEqual(storage.blocked,[]);
  report.checks.push({localStorageUnavailable:true,memoryPreferenceWorksForCurrentTab:true});await storage.context.close();
  const reduced=await fixture(browser,{startDate:'2026-11-01T00:10:00Z',reducedMotion:'reduce',fast:false});
  const reducedState=await state(reduced.page),reducedMedia=await reduced.page.evaluate(()=>({matches:matchMedia('(prefers-reduced-motion: reduce)').matches,css:[...document.styleSheets].map(s=>s.href),rules:[...document.styleSheets].filter(s=>s.href?.includes('halloween_cat_season.css')).flatMap(s=>{try{return[...s.cssRules].map(r=>r.cssText)}catch{return[]}})}));assert(reducedState.visible);assert.equal(reducedState.eyes,false,JSON.stringify({reducedState,reducedMedia,errors:reduced.errors}));assert.equal(reducedState.flightSprites,0);
  report.checks.push({reducedMotion:{catVisible:reducedState.visible,eyeOverlayHidden:!reducedState.eyes,noFlights:reducedState.flightSprites===0}});assert.deepEqual(reduced.errors,[]);await reduced.context.close();
  const halloween=await fixture(browser,{startDate:'2026-10-31T21:59:59Z',fast:false,off:true});
  const offState=await state(halloween.page);assert.equal(offState.season,'off');assert.equal(offState.cat,'off');assert.equal(offState.checked,false);assert.equal(offState.disabled,false);
  await halloween.page.evaluate(()=>__setNow('2026-10-31T22:00:00Z'));await halloween.page.waitForTimeout(100);const after=await state(halloween.page);assert.equal(after.season,'off');assert.equal(after.cat,'off');assert.equal(after.visible,false);assert.equal(after.checked,false);
  report.checks.push({previouslyDisabledSelectionDoesNotSelfEnable:true});assert.deepEqual(halloween.errors,[]);await halloween.context.close();
  fs.writeFileSync(path.join(out,'BROWSER.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({result:'PASS',cases:report.cases.length,checks:report.checks.length,assetSha256:assetSha},null,2));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
