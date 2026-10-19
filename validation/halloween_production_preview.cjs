const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {chromium}=require('C:/Users/User/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');

const ROOT=path.resolve(__dirname,'..');
const OUT=path.join(ROOT,'evidence','halloween-production');
const BROWSER='C:/Users/User/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe';
const views=['workQueueView','applicationsView','historyView','suppliersView','edrMonitoringView','frameworkAnalyticsView','procurementsView','referencesView','requestsView','operationalTasksView','messagesView','administrationView'];

async function pageFor(browser,{theme='light',preference=null,reducedMotion='no-preference',width=1440}={}){
 const context=await browser.newContext({viewport:{width,height:1000},timezoneId:'Europe/Kyiv',reducedMotion});
 await context.addInitScript(({preference})=>{
  const NativeDate=Date;let now=NativeDate.parse('2026-10-19T12:00:00Z');
  window.Date=class extends NativeDate{constructor(...a){super(...(a.length?a:[now]))}static now(){return now}};
  window.__setHalloweenTime=value=>{now=NativeDate.parse(value);dispatchEvent(new Event('focus'))};
  const nativePerf=performance.now.bind(performance);let perfAdvance=0;Object.defineProperty(performance,'now',{configurable:true,value:()=>nativePerf()+perfAdvance});window.__setPerfAdvance=value=>{perfAdvance=value};
  if(preference!==null&&localStorage.getItem('pqm.halloween.cat.enabled.v1')===null)localStorage.setItem('pqm.halloween.cat.enabled.v1',preference);
  const nativeSetTimeout=window.setTimeout.bind(window),nativeClearTimeout=window.clearTimeout.bind(window);
  window.__flightScheduleDelays=[];window.__pendingHalloweenTimers=new Set();
  window.__catTimerDelays=[];window.__catTimerCounts={look:0,blink:0};window.__catTimerFired={look:0,blink:0};
  window.__waapiTargets=[];const nativeAnimate=Element.prototype.animate;Element.prototype.animate=function(keyframes,options){const a=nativeAnimate.call(this,keyframes,options),name=typeof this.className==='string'?this.className:this.className?.baseVal||'';window.__waapiTargets.push({name,duration:options?.duration});return a};
  const nativeRaf=requestAnimationFrame.bind(window),nativeCancelRaf=cancelAnimationFrame.bind(window);window.__trailFrames=new Set();window.__maxTrailFrames=0;
  window.requestAnimationFrame=fn=>{if(fn.name!=='draw')return nativeRaf(fn);let id;id=nativeRaf(t=>{window.__trailFrames.delete(id);fn(t)});window.__trailFrames.add(id);window.__maxTrailFrames=Math.max(window.__maxTrailFrames,window.__trailFrames.size);return id};
  window.cancelAnimationFrame=id=>{window.__trailFrames.delete(id);return nativeCancelRaf(id)};
  window.__sparkDots=0;window.__sparkArcSamples=[];const nativeArc=CanvasRenderingContext2D.prototype.arc;CanvasRenderingContext2D.prototype.arc=function(...args){if(this.canvas.classList.contains('halloween-broom-trail')){window.__sparkDots++;if(window.__sparkArcSamples.length<12){const sprite=this.canvas.parentElement.querySelector('.halloween-flight-sprite'),svg=sprite?.querySelector('svg'),second=sprite?.dataset.witch==='2',point=svg?.createSVGPoint();if(point){point.x=second?1930:1005;point.y=second?630:625;const tip=point.matrixTransform(svg.getScreenCTM()),box=this.canvas.getBoundingClientRect();window.__sparkArcSamples.push({x:args[0],y:args[1],tipX:tip.x-box.left,tipY:tip.y-box.top,color:this.fillStyle})}}}return nativeArc.apply(this,args)};
  window.setTimeout=(fn,delay,...args)=>{
   if(typeof fn==='function'&&fn.toString().includes('launchFlight()')){
    window.__flightScheduleDelays.push(delay);let id;
    id=nativeSetTimeout(()=>{window.__pendingHalloweenTimers.delete(id);fn(...args)},40);
    window.__pendingHalloweenTimers.add(id);return id;
   }
   if(typeof fn==='function'){
    const source=fn.toString(),kind=source.includes('look();')?'look':source.includes('animateLids(')&&source.includes('nextWinkAt')?'blink':'';
    if(kind&&window.__catTimerCounts[kind]===0){window.__catTimerCounts[kind]++;window.__catTimerDelays.push({kind,delay});return nativeSetTimeout((...xs)=>{window.__catTimerFired[kind]++;fn(...xs)},kind==='blink'?120:40,...args)}
   }
   return nativeSetTimeout(fn,delay,...args);
  };
  window.clearTimeout=id=>{window.__pendingHalloweenTimers.delete(id);return nativeClearTimeout(id)};
 },{preference});
 const errors=[];const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',route=>{
  const url=new URL(route.request().url());
  if(url.origin!=='http://pqm-production.local')return route.abort();
  const rel=decodeURIComponent(url.pathname.replace(/^\//,''));
  if(!rel)return route.fulfill({body:fs.readFileSync(path.join(ROOT,'index.html')),contentType:'text/html'});
  const file=path.resolve(ROOT,rel);if(!file.startsWith(ROOT+path.sep))return route.abort();
  if(rel.endsWith('.js')&&!['theme_ui.js','halloween_season.js','halloween.js','halloween_motion.js'].includes(path.basename(rel)))return route.fulfill({body:'',contentType:'application/javascript'});
  if(!fs.existsSync(file))return route.fulfill({status:404,body:`missing ${rel}`});
  const type={'.html':'text/html','.js':'application/javascript','.css':'text/css','.svg':'image/svg+xml','.webp':'image/webp','.png':'image/png'}[path.extname(file)]||'application/octet-stream';
  return route.fulfill({body:fs.readFileSync(file),contentType:type});
 });
 await page.goto('http://pqm-production.local/',{waitUntil:'load'});
 await page.evaluate(({theme})=>{
  document.querySelector('#loginGate').hidden=true;
  document.querySelector('#applicationShell').hidden=false;
  document.querySelector('#mainNav').innerHTML='<button class="main-nav-icon nav-active" type="button" aria-label="Реєстр заявок"><span>📋</span></button><button class="main-nav-icon" type="button" aria-label="База постачальників"><span>📁</span></button><button class="main-nav-icon" type="button" aria-label="Звернення"><span>🗂️</span><span class="action-count-badge">3</span></button>';
  const avatar=document.querySelector('#currentUserAvatar');avatar.src='data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="64" height="64"%3E%3Ccircle cx="32" cy="32" r="30" fill="%235b83a8"/%3E%3C/svg%3E';avatar.hidden=false;
  PqmThemeUI.apply(theme);
  setTimeout(()=>window.__setPerfAdvance(120000),20);
  window.showPqmView=id=>{for(const main of document.querySelectorAll('main'))main.hidden=main.id!==id;dispatchEvent(new Event('resize'))};
 },{theme});
 await page.waitForTimeout(100);
 return{context,page,errors};
}

async function safeSurface(page,id){
 await page.evaluate(id=>showPqmView(id),id);await page.waitForTimeout(80);
 return page.evaluate(id=>{
  const lane=document.querySelector('.halloween-flight-lane'),view=document.getElementById(id);
  const surfaces=[...view.querySelectorAll('table,.card,.table-card,.module-kpis,.kpi-row,.kpi,.kpi-card,.heading-metrics,.operational-type-kpis,.work-queue-kpis')];
  const nonForeground=surfaces.filter(e=>!e.classList.contains('pqm-halloween-foreground')).map(e=>e.id||e.className);
  const directChildren=[...view.children];
  const protectedChild=e=>e.matches('.module-heading,.page-heading,.history-heading')?[...e.children].every(c=>c.classList.contains('pqm-halloween-foreground')):e.classList.contains('pqm-halloween-foreground');
  return{view:id,safe:lane?.dataset.safe,reason:lane?.dataset.reason,pointerEvents:lane&&getComputedStyle(lane).pointerEvents,visible:!view.hidden,scrollWidth:document.documentElement.scrollWidth,viewport:innerWidth,directChildrenProtected:directChildren.every(protectedChild),nonForegroundSurfaces:nonForeground};
 },id);
}

(async()=>{
 fs.mkdirSync(OUT,{recursive:true});
 const browser=await chromium.launch({headless:true,executablePath:BROWSER});const report={baseline:'b2fab2e71bc42b8df3e4b71883dc348ffc4ce89c',cases:[],checks:[],screenshots:OUT};
 try{
  for(const theme of ['light','dark']){
   const run=await pageFor(browser,{theme});
   for(const id of views){const surface=await safeSurface(run.page,id);assert.equal(surface.safe,'true',`${id} has no safe Halloween lane: ${JSON.stringify(surface)}`);assert.equal(surface.pointerEvents,'none');assert(surface.scrollWidth<=surface.viewport,`${id} caused horizontal overflow`);assert(surface.directChildrenProtected,`${id} has unprotected foreground containers: ${JSON.stringify(surface)}`);assert.deepEqual(surface.nonForegroundSurfaces,[],`${id} has unprotected working surfaces`);report.cases.push(surface)}
   await run.page.evaluate(()=>document.querySelector('#accountSettingsDialog').showModal());await run.page.waitForTimeout(80);const modal=await run.page.evaluate(()=>{const lane=document.querySelector('.halloween-flight-lane');return{reason:lane.dataset.reason,safe:lane.dataset.safe,visible:getComputedStyle(lane).visibility,toggle:document.querySelector('#halloweenDecorationEnabled')?.checked,caption:document.querySelector('.halloween-preference small')?.textContent}});assert.deepEqual(modal,{reason:'dialog-open',safe:'false',visible:'hidden',toggle:true,caption:'Декоративне оформлення лише в цьому браузері'});await run.page.screenshot({path:path.join(OUT,`${theme}-account-halloween-toggle.png`),fullPage:true});await run.page.evaluate(()=>document.querySelector('#accountSettingsDialog').close());report.checks.push({theme,modalSuppression:modal});
   await run.page.evaluate(id=>showPqmView(id),'workQueueView');
   await run.page.waitForTimeout(90);
   const catMotion=await run.page.evaluate(()=>({overlay:!!document.querySelector('.halloween-cat-eyes'),pupils:document.querySelectorAll('.pqm-cat-gaze>ellipse').length,gazeAnimations:document.querySelector('.pqm-cat-gaze')?.getAnimations().length||0,eyelidAnimations:[...document.querySelectorAll('.pqm-cat-lids')].reduce((n,e)=>n+e.getAnimations().length,0),avatarHatVisible:!document.querySelector('.halloween-avatar-hat')?.hidden,spiderVisible:!document.querySelector('.halloween-spider')?.hidden,activeWeb:getComputedStyle(document.querySelector('#mainNav .nav-active'),'::before').backgroundImage,pumpkinCounter:getComputedStyle(document.querySelector('#mainNav .action-count-badge'),'::before').backgroundImage,pumpkinCountText:document.querySelector('#mainNav .action-count-badge')?.textContent,timers:__catTimerDelays.map(x=>x.kind),fired:__catTimerFired,waapi:__waapiTargets}));
   assert.equal(catMotion.overlay,true);assert.equal(catMotion.pupils,2);assert(catMotion.gazeAnimations>0);assert.equal(catMotion.waapi.filter(x=>x.name==='pqm-cat-lids'&&x.duration===420).length,1,JSON.stringify(catMotion));assert(catMotion.timers.includes('look')&&catMotion.timers.includes('blink'));report.checks.push({theme,catMotion});
   assert.equal(catMotion.avatarHatVisible,true);assert.equal(catMotion.spiderVisible,true);assert(catMotion.activeWeb.startsWith('url('));assert(catMotion.pumpkinCounter.includes('data:image/svg+xml'));assert.equal(catMotion.pumpkinCountText,'3');
   const landing=await run.page.evaluate(()=>{const rect=e=>{const r=e.getBoundingClientRect();return{x:r.x,y:r.y,right:r.right,bottom:r.bottom}},overlap=(a,b)=>a.x<b.right&&a.right>b.x&&a.y<b.bottom&&a.bottom>b.y,cat=document.querySelector('.halloween-cat'),brand=document.querySelector('.prod-brand-copy strong'),logo=document.querySelector('.prod-brand-initials');return{active:document.documentElement.dataset.halloween,theme:document.documentElement.dataset.theme,toggle:document.querySelector('#halloweenDecorationEnabled')?.checked,caption:document.querySelector('.halloween-preference small')?.textContent,landscape:getComputedStyle(document.querySelector('#workQueueView'),'::before').backgroundImage,cat:!!cat,catOverlapsBrandText:overlap(rect(cat),rect(brand)),catOverlapsLogo:overlap(rect(cat),rect(logo)),navButtons:[...document.querySelectorAll('#mainNav button')].length}});
   assert.equal(landing.active,'on');assert.equal(landing.theme,theme);assert.equal(landing.toggle,true);assert(landing.landscape.includes(theme==='dark'?'halloween-workqueue-dark.webp':'halloween-workqueue-light.webp'));assert(landing.cat);assert.equal(landing.catOverlapsBrandText,true);assert.equal(landing.catOverlapsLogo,false);report.checks.push({theme,landing});
   await run.page.waitForSelector('.halloween-flight-sprite',{timeout:2000});
   const flight=await run.page.evaluate(()=>{const sprite=document.querySelector('.halloween-flight-sprite'),lane=sprite.parentElement,a=sprite.getAnimations().find(x=>x.animationName==='pqm-witch-cross');a.pause();a.currentTime=a.effect.getTiming().duration*.45;const maneuver=sprite.querySelector('.halloween-witch-maneuver'),waveAnimation=maneuver.getAnimations()[0];waveAnimation.pause();const wave=[.22,.24,.26,.54,.56,.58,.82,.84,.86].map(p=>{a.currentTime=a.effect.getTiming().duration*p;waveAnimation.currentTime=waveAnimation.effect.getTiming().duration*p;return getComputedStyle(maneuver).transform});const x=[];for(const p of [.05,.25,.5,.75,.98,1]){a.currentTime=a.effect.getTiming().duration*p;const r=sprite.getBoundingClientRect();x.push({p,left:r.left,right:r.right})}a.currentTime=a.effect.getTiming().duration*.45;waveAnimation.currentTime=waveAnimation.effect.getTiming().duration*.45;return{count:document.querySelectorAll('.halloween-flight-sprite').length,pointerEvents:getComputedStyle(lane).pointerEvents,witch:sprite.dataset.witch,amplitude:getComputedStyle(lane).getPropertyValue('--maneuver-amplitude'),duration:a.effect.getTiming().duration,catWidth:document.querySelector('.halloween-cat').getBoundingClientRect().width,rate:window.__flightScheduleDelays[0],wave,x,clipRects:sprite.querySelectorAll('clipPath rect').length,overflow:getComputedStyle(sprite).overflow}});
   assert.equal(flight.count,1);assert.equal(flight.pointerEvents,'none');assert(flight.rate>=20000&&flight.rate<=30000);
   assert.equal(flight.witch,'1');assert(flight.clipRects>=1);assert(flight.x[0].left>flight.x[1].left&&flight.x[1].left>flight.x[2].left&&flight.x[2].left>flight.x[3].left&&flight.x[3].left>flight.x[4].left);assert(flight.x[5].right<0,`witch did not fully exit left: ${JSON.stringify(flight.x)}`);assert(new Set(flight.wave).size>=4,`wave motion did not vary smoothly: ${JSON.stringify(flight.wave)}`);
   await run.page.waitForTimeout(260);const sparks=await run.page.evaluate(()=>({count:__sparkDots,samples:__sparkArcSamples}));assert(sparks.count>0,'broom trail did not render any gold particle dots');assert(sparks.samples.length>0);assert(sparks.samples.some(s=>Math.hypot(s.x-s.tipX,s.y-s.tipY)<18),`sparks did not originate near broom tail: ${JSON.stringify(sparks.samples)}`);assert(sparks.samples.some(s=>s.x>s.tipX+2),`sparks do not trail behind rightward of the left-moving broom: ${JSON.stringify(sparks.samples)}`);assert(sparks.samples.every(s=>['#ffe4a0','#edc777','#fff7d5'].includes(String(s.color).toLowerCase())),`unexpected spark colors: ${JSON.stringify(sparks.samples)}`);await run.page.screenshot({path:path.join(OUT,`${theme}-work-queue-with-witch.png`),fullPage:true});
   await run.page.evaluate(()=>{const old=document.querySelector('.halloween-flight-sprite');old.dispatchEvent(new AnimationEvent('animationend',{animationName:'pqm-witch-cross'}))});
   await run.page.waitForFunction(()=>document.querySelector('.halloween-flight-sprite')?.dataset.witch==='2',null,{timeout:2000});
   const second=await run.page.evaluate(()=>{const sprite=document.querySelector('.halloween-flight-sprite'),a=sprite.getAnimations().find(x=>x.animationName==='pqm-witch-cross'),maneuver=sprite.querySelector('.halloween-witch-maneuver'),waveAnimation=maneuver.getAnimations()[0];a.pause();waveAnimation.pause();const x=[],wave=[];for(const p of [.05,.25,.5,.75,.98,1]){a.currentTime=a.effect.getTiming().duration*p;const r=sprite.getBoundingClientRect();x.push({p,left:r.left,right:r.right})}for(const p of [.22,.24,.26,.54,.56,.58,.82,.84,.86]){waveAnimation.currentTime=waveAnimation.effect.getTiming().duration*p;wave.push(getComputedStyle(maneuver).transform)}a.currentTime=a.effect.getTiming().duration;return{count:document.querySelectorAll('.halloween-flight-sprite').length,witch:sprite.dataset.witch,trails:document.querySelectorAll('.halloween-broom-trail').length,x,wave,clipRects:sprite.querySelectorAll('clipPath rect').length}});assert.equal(second.count,1);assert.equal(second.witch,'2');assert.equal(second.trails,1);assert(second.clipRects>=1);assert(second.x[0].left>second.x[1].left&&second.x[1].left>second.x[2].left&&second.x[2].left>second.x[3].left&&second.x[3].left>second.x[4].left);assert(second.x[5].right<0,`second witch did not fully exit left: ${JSON.stringify(second.x)}`);assert(new Set(second.wave).size>=4,`second witch maneuver did not wave: ${JSON.stringify(second.wave)}`);
   await run.page.evaluate(theme=>PqmThemeUI.apply(theme==='light'?'dark':'light'),theme);const switched=await run.page.evaluate(()=>({theme:document.documentElement.dataset.theme,halloween:document.documentElement.dataset.halloween}));assert.equal(switched.theme,theme==='light'?'dark':'light');assert.equal(switched.halloween,'on');await run.page.evaluate(theme=>PqmThemeUI.apply(theme),theme);
   await run.page.evaluate(()=>{const toggle=document.querySelector('#halloweenDecorationEnabled');toggle.checked=false;toggle.dispatchEvent(new Event('change'))});
   await run.page.waitForTimeout(120);const off=await run.page.evaluate(()=>({theme:document.documentElement.dataset.theme,state:document.documentElement.dataset.halloween,stored:localStorage.getItem('pqm.halloween.cat.enabled.v1'),sprite:document.querySelectorAll('.halloween-flight-sprite').length,timers:__pendingHalloweenTimers.size,trailFrames:__trailFrames.size,cat:getComputedStyle(document.querySelector('.halloween-cat')).display}));
   assert.equal(off.state,'off');assert.equal(off.stored,'0');assert.equal(off.sprite,0);assert.equal(off.timers,0);assert.equal(off.trailFrames,0);assert.equal(off.cat,'none');
   await run.page.screenshot({path:path.join(OUT,`${theme}-halloween-off.png`),fullPage:true});
   await run.context.close();report.checks.push({theme,flight,sparks,second,themeSwitch:switched,off,errors:run.errors});assert.deepEqual(run.errors,[]);
  }
  const reduced=await pageFor(browser,{theme:'dark',reducedMotion:'reduce'});
  await reduced.page.waitForTimeout(120);const motion=await reduced.page.evaluate(()=>({prefers:matchMedia('(prefers-reduced-motion: reduce)').matches,catEyes:getComputedStyle(document.querySelector('.halloween-cat-eyes')).display,flight:document.querySelectorAll('.halloween-flight-sprite').length,timers:__pendingHalloweenTimers.size,host:document.querySelector('.halloween-flight-lane').hidden}));
  assert.equal(motion.prefers,true);assert.equal(motion.catEyes,'none');assert.equal(motion.flight,0);assert.equal(motion.timers,0);await reduced.context.close();report.checks.push({reducedMotion:motion});
  const offDefault=await pageFor(browser,{preference:'0'});const offMetrics=await offDefault.page.evaluate(()=>({season:PqmHalloweenSeason.state(new Date()),state:document.documentElement.dataset.halloween,stored:localStorage.getItem('pqm.halloween.cat.enabled.v1')}));assert.equal(offMetrics.state,'off');
  const boundaries=await offDefault.page.evaluate(()=>['2026-09-30T20:59:59Z','2026-09-30T21:00:00Z','2026-10-31T21:59:59Z','2026-10-31T22:00:00Z'].map(d=>PqmHalloweenSeason.state(new Date(d)).available));assert.deepEqual(boundaries,[false,true,true,false]);
  await offDefault.page.evaluate(()=>{document.querySelector('#halloweenDecorationEnabled').checked=true;document.querySelector('#halloweenDecorationEnabled').dispatchEvent(new Event('change'))});
  assert.equal(await offDefault.page.evaluate(()=>localStorage.getItem('pqm.halloween.cat.enabled.v1')),'1');
  await offDefault.page.reload({waitUntil:'load'});await offDefault.page.waitForSelector('#halloweenDecorationEnabled',{state:'attached'});assert.equal(await offDefault.page.evaluate(()=>({checked:document.querySelector('#halloweenDecorationEnabled').checked,stored:localStorage.getItem('pqm.halloween.cat.enabled.v1'),active:document.documentElement.dataset.halloween})).then(x=>x.checked),true);
  await offDefault.page.evaluate(()=>window.__setHalloweenTime('2026-11-01T00:00:00Z'));await offDefault.page.waitForTimeout(20);const seasonEnd=await offDefault.page.evaluate(()=>({state:document.documentElement.dataset.halloween,disabled:document.querySelector('#halloweenDecorationEnabled').disabled,stored:localStorage.getItem('pqm.halloween.cat.enabled.v1')}));assert.deepEqual(seasonEnd,{state:'off',disabled:true,stored:'1'});
  await offDefault.context.close();report.checks.push({kyivBoundaries:boundaries,preferencePersistedAcrossReload:true,seasonEnd,defaultDuringOctober:true});
  fs.writeFileSync(path.join(OUT,'RESULTS.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify({result:'PASS',views:report.cases.length,themes:['light','dark'],checks:report.checks,screenshots:OUT},null,2));
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
