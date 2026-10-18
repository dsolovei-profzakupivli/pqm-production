const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require('C:/Users/User/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root=path.resolve(__dirname,'..'),out=path.join(root,'evidence','halloween-integration');
const scripts=new Set(['theme_ui.js','nav_icons.js','sandbox_contrast.js','halloween_season.js','halloween.js','halloween_motion.js']);
const browserPath='C:/Users/User/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe';
async function fixture(browser,{candidate=true,theme='light',zoom=1,width=1440,reducedMotion='no-preference',off=false,fast=true,clock=false,dpr=1,motionSource=null}={}){
 const context=await browser.newContext({viewport:{width,height:960},deviceScaleFactor:dpr,reducedMotion,timezoneId:'Europe/Kyiv'});
 await context.addInitScript(({fast,off})=>{
  const NativeDate=Date;let now=NativeDate.parse('2026-10-19T12:00:00Z');
  window.Date=class extends NativeDate{constructor(...a){super(...(a.length?a:[now]))}static now(){return now}};
  window.__setNow=d=>{now=NativeDate.parse(d);dispatchEvent(new Event('focus'))};
  if(off)localStorage.setItem('pqm.halloween.cat.enabled.v1','0');
  const timeout=setTimeout.bind(window);window.__flightDelays=[];window.__pendingFlightTimers=new Set();
  window.setTimeout=(fn,d,...args)=>{
   if(typeof fn==='function'&&fn.toString().includes("lane.className='halloween-flight-lane'")){
    window.__flightDelays.push(d);let id;id=timeout(()=>{window.__pendingFlightTimers.delete(id);fn(...args)},fast?100:d);window.__pendingFlightTimers.add(id);return id;
   }return timeout(fn,d,...args);
  };
  const clear=clearTimeout.bind(window);window.clearTimeout=id=>{window.__pendingFlightTimers.delete(id);return clear(id)};
  const raf=requestAnimationFrame.bind(window),cancel=cancelAnimationFrame.bind(window);window.__trailFrames=new Set();window.__maxTrailFrames=0;
  window.requestAnimationFrame=fn=>{if(fn.name!=='draw')return raf(fn);let id;id=raf(t=>{window.__trailFrames.delete(id);fn(t)});window.__trailFrames.add(id);window.__maxTrailFrames=Math.max(window.__maxTrailFrames,window.__trailFrames.size);return id};
  window.cancelAnimationFrame=id=>{window.__trailFrames.delete(id);return cancel(id)};
  const clearRect=CanvasRenderingContext2D.prototype.clearRect,arc=CanvasRenderingContext2D.prototype.arc;
  window.__particles={active:0,max:0,draws:0};
  CanvasRenderingContext2D.prototype.clearRect=function(...a){window.__particles.active=0;window.__particles.draws++;return clearRect.apply(this,a)};
  CanvasRenderingContext2D.prototype.arc=function(...a){const p=window.__particles;p.active++;p.max=Math.max(p.max,p.active);return arc.apply(this,a)};
 },{fast,off});
 const page=await context.newPage(),errors=[],blocked=[];page.on('pageerror',e=>errors.push(e.message));
 if(clock)await page.clock.install({time:new Date('2026-10-19T12:00:00Z')});
 await page.route('**/*',r=>{
  const u=new URL(r.request().url());if(u.origin!=='http://pqm.halloween.local'){blocked.push(u.href);return r.abort()}
  const rel=decodeURIComponent(u.pathname).replace(/^\//,''),file=path.resolve(root,rel);
  if(u.pathname==='/')return r.fulfill({body:fs.readFileSync(path.join(out,candidate?'candidate.html':'baseline.html')),contentType:'text/html'});
  if(rel==='halloween_motion.js'&&motionSource!==null)return r.fulfill({body:motionSource,contentType:'application/javascript'});
  if(!file.startsWith(root+path.sep))return r.abort();
  if(rel.endsWith('.js')&&!scripts.has(path.basename(rel)))return r.fulfill({body:'',contentType:'application/javascript'});
  if(!fs.existsSync(file))return r.fulfill({status:404,body:'missing fixture file'});
  return r.fulfill({body:fs.readFileSync(file),contentType:({'.css':'text/css','.js':'application/javascript','.svg':'image/svg+xml','.webp':'image/webp','.png':'image/png'})[path.extname(file)]||'application/octet-stream'});
 });
 await page.goto('http://pqm.halloween.local/',{waitUntil:'load'});
 await page.addScriptTag({content:fs.readFileSync(path.join(root,'validation/halloween_integration_fixture.js'),'utf8')});
 await page.evaluate(({theme,zoom})=>{HalloweenIntegrationFixture.install({panel:false});document.body.style.zoom=String(zoom);PqmThemeUI.apply(theme)}, {theme,zoom});
 await page.waitForTimeout(160);
 return {page,context,errors,blocked};
}
async function geometry(page){return page.evaluate(()=>{
 const selectors=['.sandbox-brand','#mainNav','#mainNav button','#workQueueView h1','#workQueueView .card','#workQueueView button','#workQueueView input'];
 const nodes=[...new Set(selectors.flatMap(s=>[...document.querySelectorAll(s)]))].filter(e=>e.getBoundingClientRect().width&&e.getBoundingClientRect().height);
 return {scroll:[document.documentElement.scrollWidth,document.documentElement.scrollHeight],nodes:nodes.map(e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return{tag:e.tagName,id:e.id,rect:[r.x,r.y,r.width,r.height],color:s.color,background:s.backgroundColor,font:s.fontSize}})};
})}
async function noActivity(page){await page.waitForTimeout(120);assert.equal(await page.locator('.halloween-flight-lane').count(),0);assert.equal(await page.evaluate(()=>__trailFrames.size),0);assert.equal(await page.evaluate(()=>__pendingFlightTimers.size),0)}
async function hitState(page){return page.evaluate(()=>[...document.querySelectorAll('#workQueueView button,#workQueueView input')].filter(e=>{const r=e.getBoundingClientRect();return r.width&&r.height&&r.x+r.width/2>=0&&r.x+r.width/2<innerWidth&&r.y+r.height/2>=0&&r.y+r.height/2<innerHeight}).map(e=>{const r=e.getBoundingClientRect();return{id:e.id,text:e.textContent,clickable:e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))}}))}
module.exports={fixture,geometry};
if(require.main===module)(async()=>{const browser=await chromium.launch({headless:true,executablePath:browserPath});const report={cases:[],checks:[]};try{
 for(const theme of ['light','dark'])for(const zoom of [1,1.25]){
  const before=await fixture(browser,{candidate:false,theme,zoom}),after=await fixture(browser,{theme,zoom});
  assert.deepEqual(await geometry(after.page),await geometry(before.page));
  assert.deepEqual(after.errors,[]);assert.deepEqual(after.blocked,[]);
  await after.page.waitForSelector('.halloween-flight-sprite');
  const metrics=await after.page.evaluate(()=>{const sprite=document.querySelector('.halloween-flight-sprite'),lane=sprite.parentElement,a=sprite.getAnimations()[0];a.pause();a.currentTime=a.effect.getTiming().duration*.28;
   return{theme:document.documentElement.dataset.theme,environment:document.documentElement.dataset.pqmEnvironment,delays:__flightDelays,instances:document.querySelectorAll('.halloween-flight-sprite').length,width:sprite.getBoundingClientRect().width,pointer:getComputedStyle(lane).pointerEvents,z:getComputedStyle(lane).zIndex,cat:document.querySelector('img.halloween-cat').getBoundingClientRect().toJSON(),pupils:document.querySelectorAll('.pqm-cat-gaze>ellipse').length,duration:a.effect.getTiming().duration,oldSpeed:(document.querySelector('#workQueueView').clientWidth*.63+125)/13,speed:(lane.clientWidth+125)/(a.effect.getTiming().duration/1000)};
  });
  assert.equal(metrics.instances,1);assert.equal(metrics.environment,'sandbox');assert.equal(metrics.pupils,2);assert.equal(metrics.pointer,'none');assert.equal(metrics.z,'2');assert(metrics.delays.every(d=>d>=20000&&d<=30000));assert(Math.abs(metrics.speed-metrics.oldSpeed)<.001);
  // Real controls stay hit-testable even with an active decorative layer.
  assert.deepEqual(await hitState(after.page),await hitState(before.page));
  await after.page.screenshot({path:path.join(out,`${theme}-${zoom===1?'100':'125'}.png`),fullPage:true});
  if(zoom===1){
   // Sample actual CSS/WAAPI phases without changing delivered timings.
   for(const [label,fraction] of [['entry',.2],['middle',.5],['over-heading',.84],['fade',.96]]){
    await after.page.evaluate(f=>{const a=document.querySelector('.halloween-flight-sprite').getAnimations()[0];a.currentTime=a.effect.getTiming().duration*f;for(const a of document.querySelector('.halloween-cat-eyes').getAnimations({subtree:true})){a.pause();a.currentTime=a.effect.getTiming().duration*f}},fraction);
    await after.page.waitForTimeout(300);await after.page.screenshot({path:path.join(out,`${theme}-${label}.png`),clip:{x:0,y:72,width:1440,height:140}});
   }
   // Eyes move in both directions, stationary original cat geometry and two pupils.
   const eyeStates=[];
   for(const f of [.2,.85])eyeStates.push(await after.page.evaluate(f=>{const g=document.querySelector('.pqm-cat-gaze'),a=g.getAnimations()[0];a.currentTime=a.effect.getTiming().duration*f;return getComputedStyle(g).transform},f));
   assert.equal(eyeStates[0],'matrix(1, 0, 0, 1, 10, 0)');assert.equal(eyeStates[1],'matrix(1, 0, 0, 1, -10, 0)');
   const end=await after.page.evaluate(()=>{const s=document.querySelector('.halloween-flight-sprite'),a=s.getAnimations()[0];a.currentTime=a.effect.getTiming().duration-.01;return s.getBoundingClientRect().right});assert(end<0);
   // Complete cycles repeatedly: exactly one replacement flight/canvas.
   const variants=[];
   for(let i=0;i<4;i++){
    await after.page.waitForSelector('.halloween-flight-sprite');
    variants.push(await after.page.locator('.halloween-flight-sprite svg').getAttribute('viewBox'));
    await after.page.evaluate(()=>document.querySelector('.halloween-flight-sprite').dispatchEvent(new AnimationEvent('animationend',{animationName:'pqm-witch-cross'})));
    await after.page.waitForTimeout(180);assert.equal(await after.page.locator('.halloween-broom-trail').count(),1);
   }assert(variants.every((v,i)=>!i||v!==variants[i-1]));
   await after.page.emulateMedia({reducedMotion:'reduce'});await noActivity(after.page);
   assert.equal(await after.page.locator('.halloween-cat-eyes').evaluate(e=>getComputedStyle(e).display),'none');
   await after.page.emulateMedia({reducedMotion:'no-preference'});await after.page.waitForSelector('.halloween-flight-sprite');
   await after.page.evaluate(()=>{const i=document.querySelector('#halloweenDecorationEnabled');i.checked=false;i.dispatchEvent(new Event('change'))});await noActivity(after.page);
   assert.equal(await after.page.locator('.halloween-cat').first().evaluate(e=>getComputedStyle(e).display),'none');
   await after.page.evaluate(()=>{const i=document.querySelector('#halloweenDecorationEnabled');i.checked=true;i.dispatchEvent(new Event('change'))});await after.page.waitForSelector('.halloween-flight-sprite');
   await after.page.evaluate(()=>{document.querySelector('#workQueueView').hidden=true;document.querySelector('#applicationsView').hidden=false});await noActivity(after.page);
   await after.page.evaluate(()=>{document.querySelector('#applicationsView').hidden=true;document.querySelector('#workQueueView').hidden=false});await after.page.waitForSelector('.halloween-flight-sprite');
   await after.page.evaluate(()=>dispatchEvent(new Event('pagehide')));await noActivity(after.page);
   await after.page.evaluate(()=>dispatchEvent(new Event('pageshow')));await after.page.waitForSelector('.halloween-flight-sprite');
   await after.page.evaluate(()=>__setNow('2026-10-31T22:00:00Z'));await noActivity(after.page);assert.equal(await after.page.evaluate(()=>document.documentElement.dataset.halloween),'off');
   const boundary=await after.page.evaluate(()=>['2026-09-30T20:59:59Z','2026-09-30T21:00:00Z','2026-10-31T21:59:59Z','2026-10-31T22:00:00Z'].map(d=>PqmHalloweenSeason.state(new Date(d)).available));assert.deepEqual(boundary,[false,true,true,false]);
   report.checks.push({theme,eyes:eyeStates,fullExitRight:end,alternation:variants,kyivBoundaries:boundary,particles:await after.page.evaluate(()=>__particles),maxTrailFrames:await after.page.evaluate(()=>__maxTrailFrames)});
  }
  assert.deepEqual(after.errors,[]);report.cases.push({theme,zoom,geometry:'unchanged vs actual Live baseline HTML',...metrics});await before.context.close();await after.context.close();
 }
 for(const options of [{off:true},{reducedMotion:'reduce'},{width:390}]){
  const base=await fixture(browser,{candidate:false,...options}),candidate=await fixture(browser,options);assert.deepEqual(await geometry(candidate.page),await geometry(base.page));
  if(options.off||options.reducedMotion)await noActivity(candidate.page);
  report.checks.push({options,geometry:'unchanged',errors:candidate.errors});assert.deepEqual(candidate.errors,[]);await base.context.close();await candidate.context.close();
 }
 // The nominal pause is also tested without shortening any timer.
 const slow=await fixture(browser,{fast:false});assert.equal(await slow.page.locator('.halloween-flight-sprite').count(),0);
 const delay=await slow.page.evaluate(()=>__flightDelays[0]);assert(delay>=20000&&delay<=30000);await noActivityTimerOnly(slow.page);
 await slow.page.waitForTimeout(Math.max(0,delay-1000));assert.equal(await slow.page.locator('.halloween-flight-sprite').count(),0);
 await slow.page.waitForSelector('.halloween-flight-sprite',{timeout:2500});await slow.context.close();
 report.realPause={milliseconds:delay,noEarlyFlight:true,observedActualTimerExpiry:true};
 const blinking=await fixture(browser,{clock:true,fast:false});await blinking.page.clock.fastForward(16500);
 const lids=await blinking.page.evaluate(()=>[...document.querySelectorAll('.pqm-cat-lids')].map(e=>{const a=e.getAnimations()[0];if(!a)return null;a.pause();a.currentTime=210;return getComputedStyle(e).opacity}));assert.deepEqual(lids,['1','1']);
 await blinking.context.close();report.naturalBlink={scheduledBothLids:true};
 // Consecutive real-time frames, with no jumps between samples: visible births,
 // free particles behind the moving broom, and their natural fading.
 for(const theme of ['light','dark']){
  const capture=await fixture(browser,{theme});await capture.page.waitForSelector('.halloween-flight-sprite');
  await capture.page.evaluate(()=>{for(const a of document.querySelector('.halloween-flight-sprite').getAnimations()){a.currentTime=a.effect.getTiming().duration*.23;a.play()}for(const a of document.querySelector('.halloween-cat-eyes').getAnimations({subtree:true})){a.currentTime=a.effect.getTiming().duration*.23;a.play()}});
  for(let i=0;i<5;i++){await capture.page.waitForTimeout(i?600:80);await capture.page.screenshot({path:path.join(out,`${theme}-trail-${i}.png`),clip:{x:500,y:72,width:940,height:134}})}
  await capture.page.screenshot({path:path.join(out,`${theme}-flight-full.png`),fullPage:true});
  await capture.page.screenshot({path:path.join(out,`${theme}-cat.png`),clip:{x:205,y:38,width:80,height:58}});
  const max=await capture.page.evaluate(()=>__particles.max);assert(max>10&&max<=44);assert.equal(await capture.page.evaluate(()=>__maxTrailFrames),1);
  await capture.context.close();
 }
 fs.writeFileSync(path.join(out,'BROWSER.json'),JSON.stringify(report,null,2));
 const gallery='<!doctype html><meta charset="utf-8"><title>Sandbox Halloween — інтеграція</title><style>body{background:#202631;color:white;font:16px system-ui;margin:24px}img{display:block;max-width:100%;margin-bottom:24px;border:1px solid #63758d}</style><h1>Sandbox 8fa52a6 + Halloween · локальне приймання</h1><p>Актуальні Sandbox HTML/CSS. Демонстраційні дані; API й бізнес-скрипти не виконуються. Кадри вибраних фаз погодженого польоту.</p>'+['light','dark'].map(t=>'<h2>'+t+'</h2>'+['entry','middle','over-heading','fade'].map(f=>'<p>'+f+'</p><img src="'+t+'-'+f+'.png">').join('')).join('');
 const trailGallery=['light','dark'].map(t=>'<h2>'+t+' · послідовні кадри шлейфа (~0,6 с)</h2>'+[0,1,2,3,4].map(i=>'<img src="'+t+'-trail-'+i+'.png">').join('')).join('');
 fs.writeFileSync(path.join(out,'frames.html'),gallery+trailGallery);console.log(JSON.stringify({result:'PASS',cases:report.cases.length,checks:report.checks.length,realPause:report.realPause,naturalBlink:report.naturalBlink},null,2));
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exitCode=1});
async function noActivityTimerOnly(page){assert.equal(await page.locator('.halloween-flight-lane').count(),0);assert.equal(await page.evaluate(()=>__pendingFlightTimers.size),1)}
