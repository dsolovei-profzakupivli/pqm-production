'use strict';
// Real decorated HTML/resources. API data is synthetic; all outbound writes denied.
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..'),OUT=process.env.PQM_CALENDAR_EVIDENCE;
assert(OUT,'Use an isolated evidence directory');fs.mkdirSync(OUT,{recursive:true});
const html=fs.readFileSync(process.env.PQM_SERVED_HTML||path.join(OUT,'sandbox-index.html'));
const seasonal=p=>/(?:^|\/)(?:halloween(?:_motion)?\.(?:css|js)|halloween_cat_season\.(?:css|js))$/.test(p)||p.startsWith('/assets/halloween-');
let fault='';const writes=[];
const server=http.createServer((req,res)=>{
 const u=new URL(req.url,'http://localhost');
 if(req.method!=='GET'){writes.push(req.method+' '+u.pathname);res.writeHead(403);return res.end();}
 if(u.pathname.startsWith('/api/')){
  let data={items:[],profiles:[],columns:[],rows:[],count:0,total:0,pages:1,page:1,settings:{},scheduler_jobs:[],google:{enabled:false}};
  if(u.pathname==='/api/auth/me')data={username:'synthetic',role:'viewer',permissions:{'applications.read':true},ui_features:{}};
  if(u.pathname==='/api/account')data={username:'synthetic',color_scheme:'light',start_view:'applications'};
  res.writeHead(200,{'Content-Type':'application/json'});return res.end(JSON.stringify(data));
 }
 if(u.pathname==='/halloween_season.js'&&fault==='policy-shape'){res.writeHead(200,{'Content-Type':'text/javascript'});return res.end("globalThis.PqmHalloweenSeason={state:()=>({available:true,timeZone:'UTC'})}");}
 if(u.pathname==='/halloween_season.js'&&fault==='policy-throw'){res.writeHead(200,{'Content-Type':'text/javascript'});return res.end("globalThis.PqmHalloweenSeason={state:()=>{throw Error('synthetic calendar failure')}}");}
 if((fault==='policy'&&u.pathname==='/halloween_season.js')||(fault==='css'&&u.pathname==='/halloween.css')||(fault==='motion'&&u.pathname==='/halloween_motion.js')||(fault==='hat'&&u.pathname==='/assets/halloween-witch-cat.webp')||(fault==='core'&&u.pathname==='/pqm_cat.js')||(fault==='neutral-css'&&u.pathname==='/pqm_cat.css')){res.writeHead(503);return res.end();}
 const file=path.resolve(ROOT,u.pathname.slice(1)||'index.html');
 if(!file.startsWith(ROOT+path.sep)||!fs.existsSync(file)){res.writeHead(404);return res.end();}
 res.writeHead(200,{'Content-Type':({'.js':'text/javascript','.css':'text/css','.html':'text/html','.svg':'image/svg+xml','.webp':'image/webp','.png':'image/png'})[path.extname(file)]||'application/octet-stream','Cache-Control':'no-store'});
 res.end(u.pathname==='/'||u.pathname==='/index.html'?html:fs.readFileSync(file));
});
const cases=[
 ['September last millisecond','2026-09-30T20:59:59.999Z',false],
 ['October first millisecond','2026-09-30T21:00:00.000Z',true],
 ['DST before fold','2026-10-25T00:59:59.999Z',true],
 ['DST after fold','2026-10-25T01:00:00.000Z',true],
 ['October last millisecond','2026-10-31T21:59:59.999Z',true],
 ['November first millisecond','2026-10-31T22:00:00.000Z',false],
 ['Next year before October','2027-09-30T20:59:59.999Z',false],
 ['Next year October','2027-09-30T21:00:00.000Z',true],
 ['Next year November','2027-10-31T22:00:00.000Z',false],
 ['January','2027-01-01T00:00:00.000Z',false],
];
const report=[];
async function settled(page){
 await page.waitForLoadState('networkidle');
 // Node-side delay: the page clock intentionally remains paused at the boundary.
 await new Promise(r=>setTimeout(r,50));
 return page.evaluate(()=>({cat:document.querySelector('img.halloween-cat')?.getAttribute('src'),count:document.querySelectorAll('img.halloween-cat').length,mode:document.documentElement.dataset.halloween,visible:document.querySelector('img.halloween-cat')?getComputedStyle(document.querySelector('img.halloween-cat')).display:null,seasonalScripts:[...document.scripts].map(n=>n.getAttribute('src')).filter(s=>s==='halloween.js'||s==='halloween_motion.js')}));
}
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const origin='http://127.0.0.1:'+server.address().port;
 const browser=await chromium.launch({headless:true,executablePath:process.env.PQM_CHROMIUM_EXECUTABLE});
 try{
  for(const theme of ['light','dark']){
   const samples=[...cases.map(([name,date,enabled])=>({name,date,enabled})),...['policy','css','motion','hat','intl','policy-shape','policy-throw','core','neutral-css'].map(f=>({name:'fail closed '+f,date:'2026-10-18T12:00:00Z',enabled:false,fault:f}))];
   for(const c of samples){
    fault=c.fault||'';const context=await browser.newContext({viewport:{width:1920,height:1080},timezoneId:theme==='dark'?'America/Los_Angeles':'Asia/Tokyo'});
    await context.route('**/*',r=>new URL(r.request().url()).origin===origin?r.continue():r.abort());
    const page=await context.newPage(),requests=[];page.on('request',r=>requests.push(new URL(r.url()).pathname));
    const moment=new Date(c.date);await page.clock.install({time:new Date(moment.getTime()-1000)});await page.clock.pauseAt(moment);
    if(c.fault==='intl')await page.addInitScript(()=>{const Original=Intl.DateTimeFormat;Intl.DateTimeFormat=function(locale,options){if(options?.timeZone==='Europe/Kyiv')throw Error('synthetic calendar failure');return new Original(locale,options)};});
    await page.goto(origin,{waitUntil:'load'});const result=await settled(page);
    assert.equal(result.count,1,c.name);assert.equal(result.cat,c.enabled?'assets/halloween-witch-cat.webp':'assets/pqm-cat-no-hat.png',c.name+' cat');
    assert.equal(result.mode,c.enabled?'on':'off',c.name+' mode');
    const media=requests.filter(seasonal);
    if(!c.enabled&&!c.fault)assert.deepEqual(media,[],c.name+' must request zero seasonal resources');
    if(['policy','intl','policy-shape','policy-throw','core','neutral-css'].includes(c.fault))assert.deepEqual(media,[],c.name+' calendar errors must request zero seasonal resources');
    if(c.enabled){assert(media.includes('/halloween.js'));assert(media.includes('/halloween_motion.js'));assert(media.includes('/assets/halloween-witch-cat.webp'));}
    if(['October first millisecond','November first millisecond','fail closed css'].includes(c.name)){
     await page.evaluate(theme=>{document.documentElement.dataset.theme=theme;document.querySelector('#loginGate').hidden=true;document.querySelector('#applicationShell').hidden=false},theme);
     await page.screenshot({path:path.join(OUT,theme+'-'+c.name.replaceAll(' ','-')+'.png')});
    }
    report.push({theme,...c,result,seasonalRequests:media});await context.close();
   }
   // Exact midnight transitions in an already open page.
   for(const opening of [true,false]){
    fault='';const context=await browser.newContext({viewport:{width:1920,height:1080},timezoneId:'UTC'});
    await context.route('**/*',r=>new URL(r.request().url()).origin===origin?r.continue():r.abort());
    const page=await context.newPage(),requests=[];page.on('request',r=>requests.push(new URL(r.url()).pathname));
    const start=new Date(opening?'2026-09-30T20:59:59.500Z':'2026-10-31T21:59:59.500Z');await page.clock.install({time:new Date(start.getTime()-1000)});await page.clock.pauseAt(start);
    await page.goto(origin,{waitUntil:'load'});const before=await settled(page);const mark=requests.length;
    await page.clock.runFor(1000);const after=await settled(page);
    assert.equal(after.cat,opening?'assets/halloween-witch-cat.webp':'assets/pqm-cat-no-hat.png');assert.equal(after.mode,opening?'on':'off');
    if(!opening)assert.deepEqual(requests.slice(mark).filter(seasonal),[],'no seasonal requests after November boundary');
    report.push({theme,name:opening?'open October at midnight':'close October at midnight',before,after,newRequests:requests.slice(mark)});await context.close();
   }
  }
  assert.deepEqual(writes,[],'no write requests');
  fs.writeFileSync(path.join(OUT,'calendar-network-results.json'),JSON.stringify({result:'PASS',cases:report,writes},null,2));console.log('CALENDAR_NETWORK=PASS cases='+report.length);
 }finally{await browser.close();await new Promise(r=>server.close(r));}
})().catch(e=>{console.error(e);fs.writeFileSync(path.join(OUT,'calendar-network-failure.json'),JSON.stringify({error:e.stack,completed:report},null,2));process.exitCode=1;server.close();});
