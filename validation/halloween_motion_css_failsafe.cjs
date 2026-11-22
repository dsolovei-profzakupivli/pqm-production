const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {chromium}=require('C:/Users/User/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');

const ROOT=path.resolve(__dirname,'..');
const BROWSER='C:/Users/User/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe';

async function open(browser,{css='available',now='2026-10-30T12:00:00Z',theme='light',reducedMotion='no-preference',forceBlink=true}={}){
 const context=await browser.newContext({viewport:{width:1440,height:900},timezoneId:'Europe/Kyiv',reducedMotion});
 await context.addInitScript(({now,forceBlink})=>{
  const NativeDate=Date;let clock=NativeDate.parse(now);
  window.Date=class extends NativeDate{constructor(...args){super(...(args.length?args:[clock]))}static now(){return clock}};
  window.__setPqmTime=value=>{clock=NativeDate.parse(value);dispatchEvent(new Event('focus'))};
  window.__allowForcedBlink=forceBlink;window.__forcedBlinkUsed=false;window.__pqmLidAnimations=[];
  const nativeSetTimeout=window.setTimeout.bind(window);
  window.setTimeout=(callback,delay,...args)=>{
   if(window.__allowForcedBlink&&!window.__forcedBlinkUsed&&typeof callback==='function'&&callback.toString().includes('animateLids(')&&callback.toString().includes('nextWinkAt')){
    window.__forcedBlinkUsed=true;return nativeSetTimeout(callback,50,...args);
   }
   return nativeSetTimeout(callback,delay,...args);
  };
  const nativeAnimate=Element.prototype.animate;
  Element.prototype.animate=function(keyframes,options){
   const animation=nativeAnimate.call(this,keyframes,options);
   if(this.classList?.contains('pqm-cat-lids'))window.__pqmLidAnimations.push(animation);
   return animation;
  };
  localStorage.setItem('pqm.halloween.cat.enabled.v1','1');
 },{now,forceBlink});
 let cssRequests=0;
 const page=await context.newPage();
 await page.route('**/*',async route=>{
  const url=new URL(route.request().url());
  if(url.origin!=='http://pqm-production.local')return route.abort();
  const rel=decodeURIComponent(url.pathname.replace(/^\//,''));
  if(!rel)return route.fulfill({body:fs.readFileSync(path.join(ROOT,'index.html')),contentType:'text/html'});
  if(rel==='halloween_motion.css'){
   cssRequests++;
   if(css==='blocked'||(css==='recover'&&cssRequests===1))return route.abort('failed');
  }
  if(rel.endsWith('.js')&&!['theme_ui.js','halloween_season.js','halloween.js','halloween_motion.js'].includes(path.basename(rel)))
   return route.fulfill({body:'',contentType:'application/javascript'});
  const file=path.resolve(ROOT,rel);
  if(!file.startsWith(ROOT+path.sep)||!fs.existsSync(file))return route.fulfill({status:404,body:`missing ${rel}`});
  const contentType={'.html':'text/html','.js':'application/javascript','.css':'text/css','.svg':'image/svg+xml','.webp':'image/webp','.png':'image/png'}[path.extname(file)]||'application/octet-stream';
  return route.fulfill({body:fs.readFileSync(file),contentType});
 });
 await page.goto('http://pqm-production.local/',{waitUntil:'load'});
 await page.evaluate(theme=>{
  document.querySelector('#loginGate').hidden=true;
  document.querySelector('#applicationShell').hidden=false;
  for(const main of document.querySelectorAll('main'))main.hidden=main.id!=='workQueueView';
  PqmThemeUI.apply(theme);
 },theme);
 await page.waitForTimeout(80);
 return{context,page,getCssRequests:()=>cssRequests};
}

async function catState(page){
 return page.evaluate(()=>{
  const cat=document.querySelector('.halloween-cat');
  const layer=document.querySelectorAll('#pqmHalloweenCatEyes');
  const lid=document.querySelector('.pqm-cat-lids');
  const native=cat?.getBoundingClientRect();
  const overlay=layer[0]?.getBoundingClientRect();
  return{
   season:document.documentElement.dataset.halloween,cat:document.documentElement.dataset.pqmCat,
   theme:document.documentElement.dataset.theme,source:cat?.getAttribute('src'),
   visible:!!cat&&getComputedStyle(cat).display!=='none',nativeSize:cat?[cat.naturalWidth,cat.naturalHeight]:null,
   layerCount:layer.length,overlayAligned:!!native&&!!overlay&&Math.abs(native.x-overlay.x)<.1&&Math.abs(native.y-overlay.y)<.1&&Math.abs(native.width-overlay.width)<.1&&Math.abs(native.height-overlay.height)<.1,
   lidOpacity:lid?getComputedStyle(lid).opacity:null,lidBaseAttribute:lid?.getAttribute('opacity')||null,
   lidTransform:lid?getComputedStyle(lid).transform:null,eyeArtOpacity:document.querySelector('.pqm-cat-eye-art')?getComputedStyle(document.querySelector('.pqm-cat-eye-art')).opacity:null,
   reduced:matchMedia('(prefers-reduced-motion: reduce)').matches,layerDisplay:layer[0]?getComputedStyle(layer[0]).display:null,
  };
 });
}

async function waitForBlink(page){
 await page.waitForFunction(()=>window.__pqmLidAnimations.length===2,null,{timeout:2500});
 await page.waitForFunction(()=>window.__pqmLidAnimations.length===2&&window.__pqmLidAnimations.every(animation=>animation.playState==='finished'),null,{timeout:2500});
}

(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:BROWSER});
 try{
  const report={candidate:'a4f720c88941b934abe6b3b66986f3aba5776007',cases:[]};

  const healthy=await open(browser,{theme:'light'});
  const healthyInitial=await catState(healthy.page);
  assert.equal(healthyInitial.season,'on');assert.equal(healthyInitial.source,'assets/halloween-witch-cat.webp');
  assert.equal(healthyInitial.layerCount,1);assert.equal(healthyInitial.overlayAligned,true);
  const catBox=await healthy.page.locator('img.halloween-cat').boundingBox();
  await healthy.page.mouse.move(catBox.x+catBox.width*.1,catBox.y+catBox.height*.15);
  await healthy.page.waitForTimeout(100);
  const gazeMoved=await healthy.page.evaluate(()=>({opacity:document.querySelector('.pqm-cat-eye-art').style.opacity,transform:getComputedStyle(document.querySelector('.pqm-cat-gaze')).transform}));
  assert.equal(gazeMoved.opacity,'1');assert.notEqual(gazeMoved.transform,'none');
  assert.notEqual(gazeMoved.transform,'matrix(1, 0, 0, 1, 0, 0)');
  await waitForBlink(healthy.page);const healthyAfter=await catState(healthy.page);
  assert.equal(healthyAfter.lidOpacity,'0');assert.equal(healthyAfter.lidTransform,'none');
  report.cases.push({name:'CSS доступний: жовтень, світла тема, рух очей і підморгування 420 мс',initial:healthyInitial,gazeMoved,afterBlink:healthyAfter});
  await healthy.context.close();

  const healthyPostseason=await open(browser,{now:'2026-11-01T12:00:00Z',theme:'dark'});
  const healthyPostseasonInitial=await catState(healthyPostseason.page);
  assert.equal(healthyPostseasonInitial.season,'off');assert.equal(healthyPostseasonInitial.source,'assets/pqm-cat-no-hat.png');
  assert.equal(healthyPostseasonInitial.layerCount,1);assert.equal(healthyPostseasonInitial.overlayAligned,true);
  await waitForBlink(healthyPostseason.page);const healthyPostseasonAfter=await catState(healthyPostseason.page);
  assert.equal(healthyPostseasonAfter.lidOpacity,'0');assert.equal(healthyPostseasonAfter.lidTransform,'none');
  report.cases.push({name:'CSS доступний: післясезонний режим, темна тема, підморгування продовжується',initial:healthyPostseasonInitial,afterBlink:healthyPostseasonAfter});
  await healthyPostseason.context.close();

  const blockedOctober=await open(browser,{css:'blocked',theme:'light'});
  const blockedOctoberState=await catState(blockedOctober.page);
  assert.equal(blockedOctoberState.season,'on');assert.equal(blockedOctoberState.visible,true);
  assert.equal(blockedOctoberState.nativeSize?.[0],720);assert.equal(blockedOctoberState.layerCount,0);
  await blockedOctober.page.waitForTimeout(500);
  const blockedOctoberAfter=await catState(blockedOctober.page);
  assert.equal(blockedOctoberAfter.layerCount,0);assert.equal(blockedOctoberAfter.visible,true);
  report.cases.push({name:'CSS заблоковано: жовтень, оригінальні відкриті очі',state:blockedOctoberAfter});
  await blockedOctober.context.close();

  const blockedPostseason=await open(browser,{css:'blocked',now:'2026-11-01T12:00:00Z',theme:'dark'});
  const blockedPostseasonState=await catState(blockedPostseason.page);
  assert.equal(blockedPostseasonState.season,'off');assert.equal(blockedPostseasonState.cat,'on');
  assert.equal(blockedPostseasonState.source,'assets/pqm-cat-no-hat.png');assert.equal(blockedPostseasonState.visible,true);
  assert.equal(blockedPostseasonState.layerCount,0);
  await blockedPostseason.page.waitForTimeout(500);
  const blockedPostseasonAfter=await catState(blockedPostseason.page);
  assert.equal(blockedPostseasonAfter.layerCount,0);assert.equal(blockedPostseasonAfter.visible,true);
  report.cases.push({name:'CSS заблоковано: післясезонний режим, темна тема, оригінальні відкриті очі',state:blockedPostseasonAfter});
  await blockedPostseason.context.close();

  const recovered=await open(browser,{css:'recover',theme:'dark',forceBlink:false});
  const beforeRecovery=await catState(recovered.page);
  assert.equal(beforeRecovery.layerCount,0);assert.equal(beforeRecovery.visible,true);
  await recovered.page.evaluate(()=>{window.__allowForcedBlink=true;const link=[...document.querySelectorAll('link[rel~="stylesheet"]')].find(item=>new URL(item.href).pathname.endsWith('/halloween_motion.css'));link.href=new URL(link.href).pathname+'?retry=1'});
  await recovered.page.waitForFunction(()=>document.querySelectorAll('#pqmHalloweenCatEyes').length===1,null,{timeout:2500});
  await recovered.page.evaluate(()=>{const link=[...document.querySelectorAll('link[rel~="stylesheet"]')].find(item=>new URL(item.href).pathname.endsWith('/halloween_motion.css'));link.href=new URL(link.href).pathname+'?retry=2'});
  await recovered.page.waitForFunction(()=>window.__pqmLidAnimations.length===2,null,{timeout:2500});
  const afterRecoveryBeforeBlink=await catState(recovered.page);
  assert.equal(afterRecoveryBeforeBlink.layerCount,1);assert.equal(afterRecoveryBeforeBlink.overlayAligned,true);
  await waitForBlink(recovered.page);const afterRecoveryBlink=await catState(recovered.page);
  assert.equal(afterRecoveryBlink.layerCount,1);assert.equal(afterRecoveryBlink.lidOpacity,'0');
  assert(recovered.getCssRequests()>=3,`expected blocked CSS and two recovery requests; got ${recovered.getCssRequests()}`);
  report.cases.push({name:'CSS відновився: анімація відновлена, SVG-шар один',requests:recovered.getCssRequests(),state:afterRecoveryBlink});
  await recovered.context.close();

  const reduced=await open(browser,{theme:'dark',reducedMotion:'reduce'});
  const reducedState=await catState(reduced.page);
  assert.equal(reducedState.reduced,true);assert.equal(reducedState.layerCount,1);assert.equal(reducedState.layerDisplay,'none');
  await reduced.page.waitForTimeout(500);
  assert.equal((await reduced.page.evaluate(()=>window.__pqmLidAnimations.length)),0);
  report.cases.push({name:'prefers-reduced-motion: оверлей прихований, анімацій немає',state:reducedState});
  await reduced.context.close();

  console.log(JSON.stringify({result:'PASS',...report},null,2));
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
