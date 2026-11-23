'use strict';
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..'),OUT=process.env.PQM_UI002_EVIDENCE;assert(OUT);fs.mkdirSync(OUT,{recursive:true});
const html=fs.readFileSync(path.join(OUT,'sandbox-index.html')),errors=[],requests=[],writes=[],report=[];
const doc=(id,title,format)=>({id,title,format,documentType:'eligibilityDocuments',url:'/synthetic-files/'+id,datePublished:'2026-11-21T08:10:00Z',dateModified:'2026-11-21T09:25:00Z'});
const supplier=[doc('sig','sign.p7s','application/pkcs7-signature'),doc('mvs','Витяг МВС.pdf','application/pdf'),doc('pdf2','Довідка з довгою назвою про відповідність постачальника кваліфікаційним вимогам та чинним правилам.pdf','application/pdf'),doc('zip','Архів.zip','application/zip')];
const decision=[doc('decision','Протокол розгляду.pdf','application/pdf'),supplier[0]];
let row={id:'synthetic-ui001',supplier_name:'ТОВ «СИНТЕТИЧНИЙ ПОСТАЧАЛЬНИК UI-001»',supplier_code:'12345678',pretty_id:'UA-F-2026-11-21-000001',dk_code:'03220000-9',category:'Овочі',status:'active',qualification_status:'active',decision:'Допущено',documents:supplier,decision_documents:decision,fields:{},date_published:'2026-11-21T08:00:00Z'};
let theme='light';let fixtureData;let registryRows=null;let jobMode='normal';const verification=[];
function api(u){
 if(u.pathname==='/api/auth/me')return{username:'synthetic',authenticated:true,role:'admin',permissions:{'applications.read':true,'applications.write':true,'work.read':true},ui_features:{}};
 if(u.pathname==='/api/account')return{username:'synthetic',color_scheme:theme,start_view:'applications'};
 if(u.pathname.endsWith('/document-check-result'))return fixtureData;
 if(u.pathname==='/api/stats')return{applications:registryRows?.length||1,suppliers:1,pending:row.decision==='Очікує рішення'?1:0,admitted:row.decision==='Допущено'?1:0,rejected:row.decision==='Відхилено'?1:0,decision_yes:row.decision==='Допущено'?1:0,decision_no:row.decision==='Відхилено'?1:0,decision_undefined:row.decision==='Очікує рішення'?1:0,officers:[]};
 if(u.pathname==='/api/applications')return{items:registryRows||[row],total:registryRows?.length||1,pages:1,page:1};
 if(u.pathname==='/api/frameworks')return{items:[{id:'f1',pretty_id:row.pretty_id,dk_code:row.dk_code,title:'Синтетичний відбір'}]};
 if(u.pathname==='/api/runtime-features')return{environment:'test_web',sandbox_mode:false,background_jobs:{disabled:true,environment_locked:true},scheduler_jobs:[],google:{enabled:false}};
 return{items:[],rows:[],columns:[],profiles:[],count:0,total:0,pages:1,page:1,settings:{},permissions:{},kpis:{},officers:[],enabled:false};
}
const server=http.createServer((req,res)=>{
 const u=new URL(req.url,'http://localhost');requests.push(req.method+' '+u.pathname);
 if(u.pathname.endsWith('/verify-documents/start')){verification.push({path:u.pathname,selection:JSON.parse(u.searchParams.get('selection')||'{}')});res.writeHead(200,{'Content-Type':'application/json'});return res.end(JSON.stringify(jobMode==='technical-error'?{status:'error',error:'Synthetic technical failure; stored result preserved'}:jobMode==='evicted'?{status:'running',job_id:'fixture-job'}:{status:'complete',result:fixtureData}));}
 if(u.pathname.startsWith('/api/document-check-jobs/')&&jobMode==='evicted'){res.writeHead(404,{'Content-Type':'application/json'});return res.end(JSON.stringify({error:'Synthetic RAM job evicted'}));}
 if(req.method==='GET'&&u.pathname.startsWith('/synthetic-files/')){const file=[...row.documents,...row.decision_documents].find(d=>d.url===u.pathname);res.writeHead(200,{'Content-Type':'application/octet-stream','Content-Disposition':"attachment; filename*=UTF-8''"+encodeURIComponent(file?.title||'synthetic.txt')});return res.end('Synthetic UI-001 fixture file');}
 if(req.method==='GET'&&u.pathname.endsWith('/archive')){res.writeHead(200,{'Content-Type':'application/zip','Content-Disposition':'attachment; filename=UI001-synthetic.zip'});return res.end(Buffer.from('504b0506000000000000000000000000000000000000','hex'));}
 if(req.method!=='GET'||/verify-documents|\/archive|\/sync|\/apply/.test(u.pathname)){writes.push(req.method+' '+u.pathname);res.writeHead(403);return res.end();}
 if(u.pathname.startsWith('/api/')){res.writeHead(200,{'Content-Type':'application/json'});return res.end(JSON.stringify(api(u)));}
 const file=path.resolve(ROOT,u.pathname.slice(1)||'index.html');
 if(!file.startsWith(path.resolve(ROOT)+path.sep)||!fs.existsSync(file)){res.writeHead(404);return res.end();}
 res.writeHead(200,{'Content-Type':({'.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.html':'text/html; charset=utf-8','.svg':'image/svg+xml','.png':'image/png','.webp':'image/webp'})[path.extname(file)]||'application/octet-stream','Cache-Control':'no-store'});
 res.end(u.pathname==='/'||u.pathname==='/index.html'?html:fs.readFileSync(file));
});
const check=(key,label,status,detail,extra={})=>({key,label,status,detail,...extra});
const checks=[
 check('main_signature','Основний файл sign.p7s','ok','sign.p7s'),
 check('eds_verification','Автоматичне читання КЕП','ok','КЕП прочитано; криптографічна перевірка успішна'),
 check('certificate_issuer','Видавець сертифіката','ok','Кваліфікований надавач ЕДП — синтетичний приклад'),
 check('code','Код ЄДРПОУ / РНОКПП','ok','12345678 · код відповідає постачальнику'),
 check('organization','Назва організації','ok','ТОВ «СИНТЕТИЧНИЙ ПОСТАЧАЛЬНИК UI-002»',{informational:true}),
 check('signer','Підписант','ok','ІВАНЕНКО ІВАН ІВАНОВИЧ · відповідає керівнику'),
 check('signer_drfo','РНОКПП підписанта','ok','1234567890'),
 check('signing_time','Дата/час підписання','ok','21.11.2026, 10:15'),
 check('authority','Повноваження підписанта','warning','Потрібна ручна перевірка'),
 check('mvs_extract','Витяг МВС','ok','Витяг МВС.pdf'),
 check('mvs_extract_type','Тип витягу МВС','ok','ПОВНИЙ'),
 check('mvs_person','ПІБ у витягу МВС','ok','ІВАНЕНКО ІВАН ІВАНОВИЧ · керівник: ІВАНЕНКО ІВАН ІВАНОВИЧ'),
 check('mvs_age','Строк дії витягу — 30 к.д.','error','37 к.д. · 2026-10-15 → 2026-11-21'),
 check('mvs_seal','Електронна печатка МВС','warning','Печатку МВС не перевірено'),
 check('mvs_criminal_liability','МВС: притягнення до кримінальної відповідальності','ok','До кримінальної відповідальності НЕ ПРИТЯГУЄТЬСЯ'),
 check('mvs_unspent_conviction','МВС: незнята чи непогашена судимість','ok','НЕ МАЄ незнятої чи непогашеної судимості'),
 check('mvs_wanted_status','МВС: розшук','warning','Не вдалося прочитати відповідний рядок у витягу'),
 check('contract_experience','Досвід у Prozorro','neutral','Знайдено договір-кандидат; оцінювання досвіду виконується окремо',{search_status:'found',rows:[{contract_id:'UA-2025-01-01-000001-a',date_modified:'2025-05-01T12:00:00Z',buyer:'Синтетичний замовник',url:'https://example.test/contract'}]}),
];
fixtureData={supplier_name:'ТОВ «СИНТЕТИЧНИЙ ПОСТАЧАЛЬНИК UI-002»',supplier_code:'12345678',pretty_id:'UA-F-2026-11-21-000001',checked_at:'2026-11-21T10:30:00Z',checks,counts:Object.fromEntries(['ok','warning','error','neutral'].map(s=>[s,checks.filter(c=>c.status===s).length])),official_verification_url:'https://czo.gov.ua/verify',notice:''};
const legacy=JSON.parse(JSON.stringify(fixtureData)),baseRow={...row};
const totals=checks=>Object.fromEntries(['ok','warning','error','neutral'].map(s=>[s,checks.filter(c=>c.key!=='contract_experience'&&c.key!=='mvs_seal'&&c.status===s).length]));
const modern={...legacy,document_check_policy_version:2,checks:checks.filter(c=>c.key!=='mvs_seal')};modern.counts=totals(modern.checks);
modern.signature={technical_status:'success',code:'12345678',signer:'ІВАНЕНКО ІВАН ІВАНОВИЧ',organization:'ТОВ «СИНТЕТИЧНИЙ ПОСТАЧАЛЬНИК UI-002»'};
modern.mvs_extract={type:'full',person_name:'ІВАНЕНКО ІВАН ІВАНОВИЧ',age_days:37,issue_date:'2026-10-15',submitted_date:'2026-11-21',criminal_liability:{found:true,value:'ВІДСУТНІ',absent:true},unspent_conviction:{found:true,value:'ВІДСУТНІ',absent:true},wanted_status:{found:true,value:'ВІДСУТНІ',absent:true}};
for(const key of ['mvs_criminal_liability','mvs_unspent_conviction','mvs_wanted_status'])Object.assign(modern.checks.find(c=>c.key===key),{status:'ok',detail:'ВІДСУТНІ'});
modern.checks.find(c=>c.key==='contract_experience').detail='+ · Знайдено договорів-кандидатів: 1';modern.counts=totals(modern.checks);
async function facts(page){return page.evaluate(()=>{
 const d=document.querySelector('#documentCheckDialog'),b=document.querySelector('#documentCheckBody'),rect=e=>{const r=e.getBoundingClientRect();return{x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom}};
 return{rect:rect(d),header:rect(d.querySelector('header')),footer:rect(d.querySelector('footer')),body:rect(b),scrollHeight:b.scrollHeight,clientHeight:b.clientHeight,rerunDisabled:document.querySelector('#rerunDocumentCheckBtn').disabled,text:b.innerText,counts:Object.fromEntries([...b.querySelectorAll('[data-result-count]')].map(e=>[e.dataset.resultCount,Number(e.textContent)])),sections:[...b.querySelectorAll('[data-result-category]')].map(e=>({key:e.dataset.resultCategory,rect:rect(e),background:getComputedStyle(e.querySelector('h3')).backgroundColor,color:getComputedStyle(e.querySelector('h3')).color})),fields:Object.fromEntries([...b.querySelectorAll('[data-check-key]')].map(e=>[e.dataset.checkKey,{...rect(e),status:e.dataset.checkStatus,color:getComputedStyle(e.querySelector('.document-check-value')).color}])),links:[...d.querySelectorAll('a')].map(e=>({text:e.innerText,background:getComputedStyle(e).backgroundColor,color:getComputedStyle(e).color})),viewport:{width:innerWidth,height:innerHeight},dpr:devicePixelRatio,theme:document.documentElement.dataset.theme};
})}
function inside(f){assert(f.rect.x>=-1&&f.rect.y>=-1&&f.rect.right<=f.viewport.width+1&&f.rect.bottom<=f.viewport.height+1,JSON.stringify(f.rect));}
function grid(f){
 const fields=f.fields;
 for(const keys of [['main_signature','eds_verification','signing_time'],['mvs_extract','mvs_extract_type','mvs_age'],['mvs_criminal_liability','mvs_unspent_conviction','mvs_wanted_status']]){
  const cells=keys.map(k=>fields[k]);assert(cells.every(Boolean));assert(cells.every(c=>Math.abs(c.y-cells[0].y)<1));assert(cells.every(c=>Math.abs(c.width-cells[0].width)<1));assert(cells[0].x<cells[1].x&&cells[1].x<cells[2].x);
 }
 const first=fields.main_signature;
 for(const [left,right] of [['code','organization'],['signer_drfo','signer'],['authority','certificate_issuer']]){
  assert(Math.abs(fields[left].y-fields[right].y)<1);assert(Math.abs(fields[left].width-first.width)<1);assert(Math.abs(fields[right].width-(2*first.width+8))<2);
 }
 assert(Math.abs(fields.mvs_person.width-(3*fields.mvs_extract.width+16))<2);
 assert.deepEqual(f.sections.map(s=>s.key),['signature','mvs','experience']);
}
(async()=>{
 const fixtures=JSON.parse(fs.readFileSync(process.env.PQM_MVS_STATUS_EVIDENCE,'utf8')),report=[];
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const origin='http://127.0.0.1:'+server.address().port;
 let browser;
 try{
 for(theme of ['light','dark'])for(const zoom of [1,.9]){
  browser=await chromium.launchPersistentContext(path.join(OUT,'mvs-profile-'+theme+'-'+zoom),{headless:true,viewport:{width:1920,height:1080},executablePath:process.env.PQM_CHROMIUM_EXECUTABLE});
  await browser.route('**/*',route=>!/^https?:/.test(route.request().url())||new URL(route.request().url()).origin===origin?route.continue():route.abort());
  const settings=await browser.newPage();await settings.goto('chrome://settings');await settings.evaluate(zoom=>new Promise(resolve=>chrome.settingsPrivate.setDefaultZoom(zoom,resolve)),zoom);await settings.close();
  const page=await browser.newPage();page.on('pageerror',error=>errors.push(error.message));await page.goto(origin,{waitUntil:'networkidle'});await page.evaluate(theme=>{document.documentElement.dataset.theme=theme;document.querySelector('#loginGate').hidden=true;document.querySelector('#applicationShell').hidden=false},theme);
  for(const [name,data] of Object.entries(fixtures)){
   await page.evaluate(data=>{activeDocsRow=mapRow({id:'synthetic-mvs',supplier_name:data.supplier_name,supplier_code:data.supplier_code,dk_code:'03220000-9',decision:'Очікує рішення'});renderDocumentCheck(data)},data);
   const measurements=await page.locator('#documentCheckDialog .document-check-field').evaluateAll(fields=>fields.map(field=>{const icon=field.querySelector('.document-check-indicator'),value=field.querySelector('.document-check-value');return{key:field.dataset.checkKey,status:field.dataset.checkStatus,text:value.textContent,icon:icon.textContent,iconText:getComputedStyle(icon).color,iconBackground:getComputedStyle(icon).backgroundColor,valueColor:getComputedStyle(value).color,border:getComputedStyle(field).borderLeftColor}}));
   for(const item of measurements){const source=data.checks.find(c=>c.key===item.key);assert.equal(item.status,source.status);assert.equal(item.icon,source.status==='ok'?'✓':'!');assert.equal(item.iconText,'rgb(255, 255, 255)');assert.equal(item.valueColor,item.border);if(['mvs_criminal_liability','mvs_unspent_conviction','mvs_wanted_status'].includes(item.key)&&source.status!=='warning')assert.equal(item.text,source.detail);}
   for(const status of ['ok','warning','error'])assert.equal(Number(await page.locator('[data-result-count="'+status+'"]').innerText()),data.counts[status]);
   report.push({theme,zoom,name,measurements});if(zoom===1)await page.locator('#documentCheckDialog').screenshot({path:path.join(OUT,theme+'-'+name+'.png')});
  }
  await browser.close();browser=null;
 }
 assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);fs.writeFileSync(path.join(OUT,'browser-results.json'),JSON.stringify({result:'PASS',report,errors,writes},null,2));console.log('MVS_BROWSER=PASS states='+report.length);
 }finally{if(browser)await browser.close();await new Promise(r=>server.close(r))}
})().catch(error=>{console.error(error);process.exitCode=1});
