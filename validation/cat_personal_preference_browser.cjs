'use strict';
// Shipped decorated page/resources; synthetic GET replies and no external writes.
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..'),OUT=process.env.PQM_CAT_PREFERENCE_EVIDENCE;
assert(OUT,'Use an isolated evidence directory');fs.mkdirSync(OUT,{recursive:true});
const html=fs.readFileSync(process.env.PQM_SERVED_HTML),key='pqm.halloween.cat.enabled.v1';
const seasonal=p=>/(?:^|\/)(?:halloween(?:_motion)?\.(?:css|js)|halloween_cat_season\.(?:css|js))$/.test(p)||p.startsWith('/assets/halloween-');
const writes=[],cases=[];
const server=http.createServer((req,res)=>{
 const u=new URL(req.url,'http://localhost');
 if(req.method!=='GET'){writes.push(req.method+' '+u.pathname);res.writeHead(403);return res.end();}
 if(u.pathname.startsWith('/api/')){
  let data={items:[],profiles:[],rows:[],count:0,total:0,pages:1,page:1,settings:{},scheduler_jobs:[],google:{enabled:false}};
  if(u.pathname==='/api/auth/me')data={username:'synthetic',role:'viewer',permissions:{'applications.read':true},ui_features:{}};
  if(u.pathname==='/api/account')data={username:'synthetic',color_scheme:'light',start_view:'applications'};
  res.writeHead(200,{'Content-Type':'application/json'});return res.end(JSON.stringify(data));
 }
 const file=path.resolve(ROOT,u.pathname.slice(1)||'index.html');
 if(!file.startsWith(ROOT+path.sep)||!fs.existsSync(file)){res.writeHead(404);return res.end();}
 res.writeHead(200,{'Content-Type':({'.js':'text/javascript','.css':'text/css','.html':'text/html','.svg':'image/svg+xml','.webp':'image/webp','.png':'image/png'})[path.extname(file)]||'application/octet-stream','Cache-Control':'no-store'});
 res.end(u.pathname==='/'||u.pathname==='/index.html'?html:fs.readFileSync(file));
});
async function state(page){
 await page.waitForLoadState('networkidle');
 return page.evaluate(key=>({theme:document.documentElement.dataset.theme,stored:localStorage.getItem(key),checked:document.querySelector('#halloweenDecorationEnabled').checked,disabled:document.querySelector('#halloweenDecorationEnabled').disabled,cat:document.querySelector('img.halloween-cat').getAttribute('src'),display:getComputedStyle(document.querySelector('img.halloween-cat')).display,mode:document.documentElement.dataset.halloween,seasonal:document.documentElement.dataset.pqmSeasonalState,count:document.querySelectorAll('img.halloween-cat').length}),key);
}
async function enabledState(page,october){
 const expected=october?'assets/halloween-witch-cat.webp':'assets/pqm-cat-no-hat.png';
 for(let attempt=0;attempt<100;attempt++){
  const current=await state(page);
  if(current.cat===expected&&current.mode===(october?'on':'off'))return current;
  await new Promise(resolve=>setTimeout(resolve,50));
 }
 throw Error('Cat opt-in did not finish loading: '+JSON.stringify(await state(page)));
}
async function toggle(page,on){
 await page.evaluate(()=>{const d=document.querySelector('#accountSettingsDialog');if(!d.open)d.showModal()});
 await page.locator('#halloweenDecorationEnabled').setChecked(on);
 await page.evaluate(()=>document.querySelector('#accountSettingsDialog').close());
}
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const origin='http://127.0.0.1:'+server.address().port;
 const browser=await chromium.launch({headless:true,executablePath:process.env.PQM_CHROMIUM_EXECUTABLE});
 try{
  for(const theme of ['light','dark'])for(const october of [false,true]){
   const context=await browser.newContext({viewport:{width:1920,height:1080},timezoneId:'Asia/Tokyo'});
   await context.route('**/*',r=>new URL(r.request().url()).origin===origin?r.continue():r.abort());
   // Seed once per origin; subsequent reloads must use what the UI actually saved.
   await context.addInitScript(key=>{if(!sessionStorage.getItem('cat-test-seeded')){localStorage.setItem(key,'0');sessionStorage.setItem('cat-test-seeded','1')}},key);
   const page=await context.newPage(),requests=[];page.on('request',r=>requests.push(new URL(r.url()).pathname));
   const instant=new Date(october?'2026-10-18T12:00:00Z':'2026-11-18T12:00:00Z');await page.clock.install({time:new Date(instant.getTime()-1000)});await page.clock.pauseAt(instant);
   await page.goto(origin,{waitUntil:'load'});await page.waitForLoadState('networkidle');await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);
   const initial=await state(page);assert.equal(initial.theme,theme);assert.equal(initial.disabled,false);assert.equal(initial.checked,false);assert.equal(initial.display,'none');assert.equal(initial.count,1);assert.deepEqual(requests.filter(seasonal),[],'saved OFF never loads seasonal resources');
   await toggle(page,true);const enabled=await enabledState(page,october);assert.equal(enabled.stored,'1');assert.equal(enabled.checked,true);assert.equal(enabled.display,'block');assert.equal(enabled.cat,october?'assets/halloween-witch-cat.webp':'assets/pqm-cat-no-hat.png',JSON.stringify({enabled,requests}));assert.equal(enabled.mode,october?'on':'off');
   await toggle(page,false);const disabled=await state(page);assert.equal(disabled.stored,'0');assert.equal(disabled.checked,false);assert.equal(disabled.display,'none');assert.equal(disabled.mode,'off');
   const mark=requests.length;await page.reload({waitUntil:'load'});await page.waitForLoadState('networkidle');await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);const reloaded=await state(page);assert.equal(reloaded.theme,theme);assert.equal(reloaded.checked,false);assert.equal(reloaded.display,'none');assert.equal(reloaded.count,1);assert.deepEqual(requests.slice(mark).filter(seasonal),[],'saved OFF persists across reload');
   await toggle(page,true);const restored=await enabledState(page,october);assert.equal(restored.display,'block');assert.equal(restored.checked,true);assert.equal(restored.cat,october?'assets/halloween-witch-cat.webp':'assets/pqm-cat-no-hat.png');
   if(!october)assert.deepEqual(requests.filter(seasonal),[],'November opt-in must not bypass calendar');
   cases.push({theme,october,initial,enabled,disabled,reloaded,restored});await context.close();
  }
  for(const theme of ['light','dark'])for(const opening of [true,false]){
   const context=await browser.newContext({viewport:{width:1920,height:1080},timezoneId:'UTC'});
   await context.route('**/*',r=>new URL(r.request().url()).origin===origin?r.continue():r.abort());
   await context.addInitScript(key=>localStorage.setItem(key,'0'),key);
   const page=await context.newPage(),requests=[];page.on('request',r=>requests.push(new URL(r.url()).pathname));
   const instant=new Date(opening?'2026-09-30T20:59:59.500Z':'2026-10-31T21:59:59.500Z');await page.clock.install({time:new Date(instant.getTime()-1000)});await page.clock.pauseAt(instant);
   await page.goto(origin,{waitUntil:'load'});await page.waitForLoadState('networkidle');await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);
   const before=await state(page);await page.clock.runFor(1000);const after=await state(page);
   for(const value of [before,after]){assert.equal(value.checked,false);assert.equal(value.disabled,false);assert.equal(value.display,'none');assert.equal(value.mode,'off');assert.equal(value.stored,'0');assert.equal(value.theme,theme);}
   assert.deepEqual(requests.filter(seasonal),[],'calendar transition must not override personal OFF');
   cases.push({theme,transition:opening?'October opens':'October closes',before,after});await context.close();
  }
  assert.deepEqual(writes,[]);
  fs.writeFileSync(path.join(OUT,'cat-preference-results.json'),JSON.stringify({result:'PASS',cases,writes},null,2));console.log('CAT_PREFERENCE=PASS cases='+cases.length+' (toggle/reload in both seasons; OFF survives October boundaries)');
 }finally{await browser.close();await new Promise(r=>server.close(r));}
})().catch(e=>{console.error(e);process.exitCode=1;server.close()});
