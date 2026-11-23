'use strict';
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..'),OUT=process.env.PQM_UI001_EVIDENCE;assert(OUT);fs.mkdirSync(OUT,{recursive:true});
const html=fs.readFileSync(path.join(OUT,'sandbox-index.html')),errors=[],requests=[],writes=[],report=[];
const doc=(id,title,format)=>({id,title,format,documentType:'eligibilityDocuments',url:'/synthetic-files/'+id,datePublished:'2026-11-21T08:10:00Z',dateModified:'2026-11-21T09:25:00Z'});
const supplier=[doc('sig','sign.p7s','application/pkcs7-signature'),doc('mvs','Витяг МВС.pdf','application/pdf'),doc('pdf2','Довідка з довгою назвою про відповідність постачальника кваліфікаційним вимогам та чинним правилам.pdf','application/pdf'),doc('zip','Архів.zip','application/zip')];
const decision=[doc('decision','Протокол розгляду.pdf','application/pdf'),supplier[0]];
let row={id:'synthetic-ui001',supplier_name:'ТОВ «СИНТЕТИЧНИЙ ПОСТАЧАЛЬНИК UI-001»',supplier_code:'12345678',pretty_id:'UA-F-2026-11-21-000001',dk_code:'03220000-9',category:'Овочі',status:'active',qualification_status:'active',decision:'Допущено',documents:supplier,decision_documents:decision,fields:{},date_published:'2026-11-21T08:00:00Z'};
let theme='light';const verification=[],contexts=[];
function api(u){
 if(u.pathname==='/api/auth/me')return{username:'synthetic',authenticated:true,role:'admin',permissions:{'applications.read':true,'applications.write':true,'work.read':true},ui_features:{}};
 if(u.pathname==='/api/account')return{username:'synthetic',color_scheme:theme,start_view:'applications'};
 if(u.pathname.endsWith('/document-check-result'))return{supplier_name:row.supplier_name,supplier_code:row.supplier_code,pretty_id:row.pretty_id,counts:{ok:1,warning:0,error:0},checks:[{key:'signature',status:'ok',label:'Збережений результат',detail:'UI001 saved synthetic result'}],category_results:{},official_verification_url:'/synthetic-official'};
 if(u.pathname==='/api/stats')return{applications:1,suppliers:1,pending:row.decision==='Очікує рішення'?1:0,admitted:row.decision==='Допущено'?1:0,rejected:row.decision==='Відхилено'?1:0,decision_yes:row.decision==='Допущено'?1:0,decision_no:row.decision==='Відхилено'?1:0,decision_undefined:row.decision==='Очікує рішення'?1:0,officers:[]};
 if(u.pathname==='/api/applications')return{items:[row],total:1,pages:1,page:1};
 if(u.pathname==='/api/frameworks')return{items:[{id:'f1',pretty_id:row.pretty_id,dk_code:row.dk_code,title:'Синтетичний відбір'}]};
 if(u.pathname==='/api/runtime-features')return{environment:'test_web',sandbox_mode:false,background_jobs:{disabled:true,environment_locked:true},scheduler_jobs:[],google:{enabled:false}};
 return{items:[],rows:[],columns:[],profiles:[],count:0,total:0,pages:1,page:1,settings:{},permissions:{},kpis:{},officers:[],enabled:false};
}
const server=http.createServer((req,res)=>{
 const u=new URL(req.url,'http://localhost');requests.push(req.method+' '+u.pathname);
 if(u.pathname.endsWith('/verify-documents/start')){verification.push({path:u.pathname,selection:JSON.parse(u.searchParams.get('selection')||'{}')});res.writeHead(200,{'Content-Type':'application/json'});return res.end(JSON.stringify({status:'complete',result:{supplier_name:row.supplier_name,supplier_code:row.supplier_code,pretty_id:row.pretty_id,checked_at:'2026-11-23T10:15:00Z',dk_code:row.dk_code,counts:{ok:1,warning:0,error:0},checks:[{key:'eds_verification',label:'Автоматичне читання КЕП',status:'ok',detail:'Перевірено'}],category_results:{signature:{status:'ok'}},official_verification_url:'/synthetic-official'}}));}
 if(req.method==='GET'&&u.pathname.startsWith('/synthetic-files/')){const file=[...row.documents,...row.decision_documents].find(d=>d.url===u.pathname);res.writeHead(200,{'Content-Type':'application/octet-stream','Content-Disposition':"attachment; filename*=UTF-8''"+encodeURIComponent(file?.title||'synthetic.txt')});return res.end('Synthetic UI-001 fixture file');}
 if(req.method==='GET'&&u.pathname.endsWith('/archive')){res.writeHead(200,{'Content-Type':'application/zip','Content-Disposition':'attachment; filename=UI001-synthetic.zip'});return res.end(Buffer.from('504b0506000000000000000000000000000000000000','hex'));}
 if(req.method!=='GET'||/verify-documents|\/archive|\/sync|\/apply/.test(u.pathname)){writes.push(req.method+' '+u.pathname);res.writeHead(403);return res.end();}
 if(u.pathname.startsWith('/api/')){res.writeHead(200,{'Content-Type':'application/json'});return res.end(JSON.stringify(api(u)));}
 const file=path.resolve(ROOT,u.pathname.slice(1)||'index.html');
 if(!file.startsWith(path.resolve(ROOT)+path.sep)||!fs.existsSync(file)){res.writeHead(404);return res.end();}
 res.writeHead(200,{'Content-Type':({'.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.html':'text/html; charset=utf-8','.svg':'image/svg+xml','.png':'image/png','.webp':'image/webp'})[path.extname(file)]||'application/octet-stream','Cache-Control':'no-store'});
 res.end(u.pathname==='/'||u.pathname==='/index.html'?html:fs.readFileSync(file));
});
async function facts(page){return page.evaluate(()=>{
 const d=document.querySelector('#docsDialog'),list=d.querySelector('#docsList'),rect=e=>{const r=e.getBoundingClientRect();return{x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom}};
 const selects=Object.fromEntries(['docsSignatureFile','docsMvsFile'].map(id=>{const e=document.getElementById(id);return[id,{value:e.value,disabled:e.disabled,options:[...e.options].map(o=>({value:o.value,text:o.textContent}))}]}));
 const number=list.querySelector('.doc-number'),icon=list.querySelector('.doc-icon');return{numberStyle:number?{fontSize:getComputedStyle(number).fontSize,color:getComputedStyle(number).color,right:rect(number).right,iconLeft:rect(icon).x}:null,title:d.querySelector('h2').textContent,subtitle:d.querySelector('#docsSubtitle').textContent,rect:rect(d),header:rect(d.querySelector('header')),bar:rect(d.querySelector('#docsVerificationBar')),footer:rect(d.querySelector('footer')),list:rect(list),listScrollHeight:list.scrollHeight,listClientHeight:list.clientHeight,checkboxes:list.querySelectorAll('input[type=checkbox]').length,numbers:[...list.querySelectorAll('[data-document-group]')].map(g=>({group:g.dataset.documentGroup,numbers:[...g.querySelectorAll('.doc-number')].map(e=>Number(e.textContent))})),supplierCount:list.querySelectorAll('[data-document-group=supplier] .doc').length,decisionCount:list.querySelectorAll('[data-document-group=decision] .doc').length,selects,verifyDisabled:d.querySelector('#verifyDocumentsBtn').disabled,footerLabels:[...d.querySelectorAll('footer button,footer a')].map(e=>e.textContent),downloadLinks:[...list.querySelectorAll('.doc-download')].map(e=>({title:e.title,download:e.getAttribute('download'),background:getComputedStyle(e).backgroundColor})),viewport:{width:innerWidth,height:innerHeight},dpr:devicePixelRatio,bodyZoom:getComputedStyle(document.body).zoom,theme:document.documentElement.dataset.theme};
})}
function inside(f){assert(f.rect.x>=-1&&f.rect.y>=-1&&f.rect.right<=f.viewport.width+1&&f.rect.bottom<=f.viewport.height+1,JSON.stringify({rect:f.rect,viewport:f.viewport}));}
const base={...row};
const scenarios={
 auto:()=>({documents:[doc('zip','Архів.zip','application/zip'),{},doc('sig','sign.p7s','application/pkcs7-signature'),doc('mvs','Витяг МВС.pdf','application/pdf')],decision_documents:[]}),
 manual:()=>{const z=doc('zip','Архів.zip','application/zip');return{documents:[z,z,{},doc('s1','sign.p7s','application/pkcs7-signature'),doc('p1','Витяг перший.pdf','application/pdf'),doc('s2','sign.p7s','application/pkcs7-signature'),doc('p2','Витяг другий.pdf','application/pdf')],decision_documents:[]};},
 noMatch:()=>({documents:[doc('z','Документи.zip','application/zip'),doc('x','other.p7s','application/pkcs7-signature')],decision_documents:[doc('ds','sign.p7s','application/pkcs7-signature'),doc('dp','Витяг.pdf','application/pdf')]}),
 empty:()=>({documents:[],decision_documents:[]}),
 many:()=>({documents:Array.from({length:35},(_,i)=>doc('many'+i,'Документ_'+i+'_'+('НадзвичайноДовгаНазваБезПробілів'.repeat(8))+'.pdf','application/pdf')),decision_documents:[doc('last','Протокол останній.pdf','application/pdf')]}),
};
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const origin='http://127.0.0.1:'+server.address().port,report=[];
 let context;
 try{for(theme of ['light','dark'])for(const zoom of [1,.9]){
  context=await chromium.launchPersistentContext(path.join(OUT,'csv-profile-'+theme+'-'+zoom),{headless:true,viewport:{width:1920,height:1080},executablePath:process.env.PQM_CHROMIUM_EXECUTABLE});
  await context.route('**/*',r=>!/^https?:/.test(r.request().url())||new URL(r.request().url()).origin===origin?r.continue():r.abort());
  const settings=await context.newPage();await settings.goto('chrome://settings');await settings.evaluate(zoom=>new Promise(resolve=>chrome.settingsPrivate.setDefaultZoom(zoom,resolve)),zoom);await settings.close();
  const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));await page.goto(origin,{waitUntil:'networkidle'});
  await page.evaluate(theme=>{document.documentElement.dataset.theme=theme;document.querySelector('#loginGate').hidden=true;document.querySelector('#applicationShell').hidden=false;showModule('edrMonitoring');updateEdrMonitoringSelection()},theme);
  assert.equal(await page.locator('#edrMonitoringCsvVersion').inputValue(),'1');assert(!(await page.locator('#edrMonitoringExport').getAttribute('href')).includes('csv_version='));
  await page.selectOption('#edrMonitoringCsvVersion','2');assert((await page.locator('#edrMonitoringExport').getAttribute('href')).includes('csv_version=2'));
  const box=await page.locator('#edrMonitoringCsvVersion').boundingBox();assert(box.x>=0&&box.x+box.width<=1920);
  if(zoom===1)await page.screenshot({path:path.join(OUT,theme+'-csv-v2.png')});
  await page.selectOption('#edrMonitoringCsvVersion','1');assert(!(await page.locator('#edrMonitoringExport').getAttribute('href')).includes('csv_version='));
  report.push({theme,zoom,default:'1',explicit:'2',reset:'1'});await context.close();context=null;
 }}finally{if(context)await context.close();await new Promise(r=>server.close(r))}
 assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);fs.writeFileSync(path.join(OUT,'csv-browser-results.json'),JSON.stringify({result:'PASS',report,errors,writes},null,2));console.log('CSV_BROWSER=PASS states='+report.length);
})().catch(e=>{console.error(e);process.exitCode=1});
