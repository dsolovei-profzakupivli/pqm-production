const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require('C:/Users/User/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const {fixture}=require('./halloween_integration_browser.cjs');
const out=path.resolve(__dirname,'../evidence/halloween-maneuvers');fs.mkdirSync(out,{recursive:true});
// Test-only clock and animation capture: invoke the actual eyelid scheduler,
// without adding a preview API or changing runtime timing/eye geometry.
const probe=`(()=>{
 Math.random=()=>.2;window.__eyeJobs=new Map();window.__lidEvents=[];window.__lidCaptures=[];window.__eyeOffset=0;
 const now=performance.now.bind(performance);performance.now=()=>now()+__eyeOffset;
 const timeout=setTimeout.bind(window),clear=clearTimeout.bind(window);
 window.setTimeout=(fn,delay,...args)=>{
  if(typeof fn!=='function'||!fn.toString().includes('now>=nextWinkAt'))return timeout(fn,delay,...args);
  let id;const invoke=()=>{__eyeJobs.delete(id);fn(...args)};id=timeout(invoke,delay);
  __eyeJobs.set(id,{id,due:performance.now()+delay,delay,invoke});return id;
 };
 window.clearTimeout=id=>{__eyeJobs.delete(id);return clear(id)};
 window.__stepLids=()=>{const job=[...__eyeJobs.values()][0];if(!job)throw Error('No eyelid clock');clear(job.id);__eyeOffset+=Math.max(0,job.due-performance.now())+2;job.invoke()};
 const animate=Element.prototype.animate;
 Element.prototype.animate=function(...args){const a=animate.apply(this,args);if(this.classList.contains('pqm-cat-lids')){
  __lidEvents.push({index:[...this.parentElement.querySelectorAll('.pqm-cat-lids')].indexOf(this),time:performance.now(),duration:args[1].duration});
  a.pause();a.currentTime=210;__lidCaptures.push(a);
 }return a};
 window.__finishLids=()=>{for(const a of __lidCaptures.splice(0))a.finish()};
})();`;
async function finish(page){await page.evaluate(()=>__finishLids());await page.waitForTimeout(35)}
async function step(page){return page.evaluate(()=>{const start=__lidEvents.length;__stepLids();return __lidEvents.slice(start)})}
async function capture(page,name){const b=await page.locator('img.halloween-cat').boundingBox();await page.screenshot({path:path.join(out,name+'.png'),clip:{x:Math.max(0,Math.floor(b.x-8)),y:Math.max(0,Math.floor(b.y-8)),width:Math.ceil(b.width+16),height:Math.ceil(b.height+16)}})}
(async()=>{const browser=await chromium.launch({headless:true,executablePath:'C:/Users/User/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe'});const reports=[];try{
 for(const theme of ['light','dark']){
  const source=probe+fs.readFileSync(path.resolve(__dirname,'../halloween_motion.js'),'utf8');
  const f=await fixture(browser,{theme,dpr:3,fast:false,motionSource:source}),page=f.page;
  await page.evaluate(()=>document.querySelectorAll('main').forEach(v=>v.hidden=v.id!=='messagesView'));
  const before=await page.locator('img.halloween-cat').boundingBox();await capture(page,`${theme}-cat-open`);
  const bilateral=await step(page);assert.equal(bilateral.length,2);await capture(page,`${theme}-cat-both-blink`);await finish(page);
  const winks=[];
  for(const index of [0,1]){
   let events=[];
   for(let i=0;i<12;i++){events=await step(page);if(events.length===1)break;assert.equal(events.length,2);await finish(page)}
   assert.equal(events.length,1);assert.equal(events[0].index,index);assert.equal(events[0].duration,420);
   const lidState=await page.locator('.pqm-cat-lids').evaluateAll(es=>es.map(e=>getComputedStyle(e).opacity));assert.equal(lidState[index],'1');assert.equal(lidState[1-index],'0');
   winks.push(events[0]);await capture(page,`${theme}-cat-wink-${index===0?'left':'right'}`);await finish(page);
   await page.evaluate(()=>{Math.random=()=>.8});
  }
  assert(winks[0].time>=40000&&winks[0].time<60500);assert(winks[1].time-winks[0].time>=40000&&winks[1].time-winks[0].time<60500);
  const job=await page.evaluate(()=>[...__eyeJobs.keys()][0]);
  for(const id of await page.locator('main').evaluateAll(es=>es.map(e=>e.id))){await page.evaluate(id=>document.querySelectorAll('main').forEach(v=>v.hidden=v.id!==id),id);await page.waitForTimeout(20);assert.equal(await page.evaluate(()=>[...__eyeJobs.keys()][0]),job);assert.equal(await page.evaluate(()=>__eyeJobs.size),1)}
  // A separate isolated fixture exercises the real flight-end reaction.
  await f.context.close();
  const reaction=await fixture(browser,{theme,dpr:3,motionSource:source}),p=reaction.page;
  await p.waitForSelector('.halloween-flight-sprite');await p.evaluate(()=>{__eyeOffset+=41000;const gaze=document.querySelector('.pqm-cat-gaze').getAnimations()[0];gaze.currentTime=gaze.effect.getTiming().duration*.8});
  await capture(p,`${theme}-cat-tracks-witch`);
  await p.evaluate(()=>{for(const e of document.querySelectorAll('.pqm-cat-gaze,.pqm-cat-eye-art'))for(const a of e.getAnimations())a.finish();document.querySelector('.halloween-flight-sprite').dispatchEvent(new AnimationEvent('animationend',{animationName:'pqm-witch-cross'}))});
  await p.waitForTimeout(30);await capture(p,`${theme}-cat-return-center`);
  let response=await p.evaluate(()=>__lidCaptures.length?__lidEvents.slice(-__lidCaptures.length):[]);
  for(let i=0;!response.length&&i<3;i++){response=await step(p);if(response.length===1)break;await finish(p);response=[]}
  assert.equal(response.length,1);await capture(p,`${theme}-cat-after-flight-wink`);await finish(p);
  // A second flight inside the wink cooldown does not schedule a reaction.
  await p.waitForSelector('.halloween-flight-sprite');
  const cooldownJob=await p.evaluate(()=>[...__eyeJobs.keys()][0]);
  await p.evaluate(()=>document.querySelector('.halloween-flight-sprite').dispatchEvent(new AnimationEvent('animationend',{animationName:'pqm-witch-cross'})));
  assert.equal(await p.evaluate(()=>[...__eyeJobs.keys()][0]),cooldownJob);
  // Even outside cooldown, the random branch may leave the cat unreactive.
  await p.waitForSelector('.halloween-flight-sprite');
  await p.evaluate(()=>{__eyeOffset+=41000;Math.random=()=>.8});
  const quietJob=await p.evaluate(()=>[...__eyeJobs.keys()][0]);
  await p.evaluate(()=>document.querySelector('.halloween-flight-sprite').dispatchEvent(new AnimationEvent('animationend',{animationName:'pqm-witch-cross'})));
  assert.equal(await p.evaluate(()=>[...__eyeJobs.keys()][0]),quietJob);
  assert.deepEqual(await p.locator('img.halloween-cat').boundingBox(),before);
  assert.equal(await p.locator('.halloween-cat-eyes').count(),1);assert.equal(await p.locator('.pqm-cat-gaze>ellipse').count(),2);
  await step(p);assert(await p.locator('.pqm-cat-lids').evaluateAll(es=>es.some(e=>e.getAnimations().length)));
  await p.emulateMedia({reducedMotion:'reduce'});await p.waitForTimeout(40);assert.equal(await p.evaluate(()=>__eyeJobs.size),0);assert.equal(await p.locator('.pqm-cat-lids').evaluateAll(es=>es.flatMap(e=>e.getAnimations()).length),0);
  await p.emulateMedia({reducedMotion:'no-preference'});await p.waitForTimeout(40);assert.equal(await p.evaluate(()=>__eyeJobs.size),1);
  await p.evaluate(()=>document.documentElement.dataset.halloween='off');await p.waitForTimeout(40);assert.equal(await p.evaluate(()=>__eyeJobs.size),1);
  await p.evaluate(()=>document.documentElement.dataset.pqmCat='off');await p.waitForTimeout(40);assert.equal(await p.evaluate(()=>__eyeJobs.size),0);
  assert.deepEqual(f.errors,[]);assert.deepEqual(reaction.errors,[]);
  reports.push({theme,winks,normalBilateralBlink:true,otherEyeStaysOpen:true,duration:420,oneEyelidClockAcross13Tabs:true,reactionAfterCentredGaze:true,reactionCooldown:true,randomReactionMaySkip:true,geometryUnchanged:true,reducedMotionCancelsActiveLids:true,off:true});await reaction.context.close();
 }
 fs.writeFileSync(path.join(out,'cat-eye-checks.json'),JSON.stringify(reports,null,2));console.log('PASS: natural blinks, both one-eye winks, timing, coordinated reaction, singleton clock, gates');
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exitCode=1});
