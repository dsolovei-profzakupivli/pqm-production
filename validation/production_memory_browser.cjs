'use strict';
// Full shipped HTML and script order; all API replies are synthetic and in memory.
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const {chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..'),OUT=process.env.PQM_LIVE_FIX_EVIDENCE||path.join(ROOT,'evidence/browser');
assert.ok(OUT,'Use an isolated evidence directory');fs.mkdirSync(OUT,{recursive:true});
const codes=['03210000-6','03220000-9','45000000-7'];
const frameworks=codes.map((dk_code,i)=>({id:'f'+i,pretty_id:'F'+i,title:'Synthetic',category:'Овочі',dk_code,applications_count:3}));
const records=Array.from({length:9},(_,i)=>({id:'s'+i,supplier_code:'9900322'+i,supplier_name:'Синтетичний '+i,dk_code:codes[i%3],status:'active',fields:{},documents:[]}));
const reads=[],mutations=[],errors=[],checks=[],assets=[];
let theme='light',assetFault='';
function fixture(url){
 const p=url.pathname;
 if(p==='/api/auth/me')return{username:'synthetic',role:'admin',authenticated:true,permissions:{'applications.read':true,'suppliers.read':true,'work.read':true},ui_features:{}};
 if(p==='/api/account')return{username:'synthetic',color_scheme:theme,start_view:'applications',density:'comfortable'};
 if(p.includes('frameworks'))return{items:frameworks};
 if(p==='/api/application-profiles')return{items:[],profiles:[],system:[]};
 if(p==='/api/runtime-features')return{environment:'test_web',sandbox_mode:true,background_jobs:{disabled:true,environment_locked:true},scheduler_jobs:[],google:{enabled:false}};
 if(p==='/api/uo-work-queue')return url.searchParams.get('summary')==='application-statistics'
  ?{items:[{review_officer:'',protocol_officer:'',status:'pending',total:3}],totals:{active:0,unsuccessful:0,pending:3,total:3},filter_options:{category:['Овочі'],dk_code:codes,review_officer:[''],protocol_officer:['']},diagnostics:{}}
  :{items:[],rows:[],officers:[],total:0,filters:{},period:{date_from:'2026-11-01',date_to:'2026-11-20'},supplier_types:[],categories:['Овочі'],dk_codes:codes};
 if(p==='/api/edr-monitoring'){
  const selected=url.searchParams.getAll('dk_code').flatMap(v=>v.split(',')).filter(Boolean);
  const items=records.filter(r=>!selected.length||selected.includes(r.dk_code)).map(r=>({...r,edr_status:'Зареєстровано',prozorro_status:'Допущено',freshness:'current'}));
  return{items,total:items.length,pages:1,page:1,edr_statuses:['Зареєстровано','Припинено'],kpis:{}};
 }
 if(p==='/api/applications'){
  const selected=url.searchParams.getAll('dk_code').flatMap(v=>v.split(',')).filter(Boolean);
  const scoped=url.searchParams.get('review_officer')==='__unassigned__';
  const items=records.filter(r=>(!selected.length||selected.includes(r.dk_code))&&(!selected.length||!scoped||Number(r.id.slice(1))<4));
  return{items,total:items.length,pages:1,page:1};
 }
 return{items:[],rows:[],columns:[],profiles:[],count:0,total:0,pages:1,page:1,enabled:false,settings:{},permissions:{},kpis:{},officers:[]};
}
const mime={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.svg':'image/svg+xml','.png':'image/png','.webp':'image/webp'};
const server=http.createServer(async(req,res)=>{
 const u=new URL(req.url,'http://localhost');
 if(u.pathname.startsWith('/api/')){
  if(req.method!=='GET'){mutations.push({method:req.method,path:u.pathname});res.writeHead(403,{'Content-Type':'application/json'});return res.end('{"error":"Fixture denies writes"}');}
  reads.push(u.pathname+u.search);res.writeHead(200,{'Content-Type':'application/json','Cache-Control':'no-store'});return res.end(JSON.stringify(fixture(u)));
 }
 const relative=u.pathname==='/'?'index.html':u.pathname.slice(1),file=path.resolve(ROOT,relative);
 if(!file.startsWith(ROOT+path.sep)||!fs.existsSync(file)){res.writeHead(404);return res.end();}
 if((assetFault==='missing-cat-css'&&relative==='pqm_cat.css')||(assetFault==='missing-dark-logo'&&relative==='assets/pqm-brand-mark-prod-dark.svg')){assets.push({path:relative,status:503});res.writeHead(503);return res.end();}
 if(assetFault==='delayed-cat-controller'&&relative==='halloween.js')await new Promise(r=>setTimeout(r,1800));
 await new Promise(r=>setTimeout(r,(relative.length*17+reads.length*11)%65));
 const data=fs.readFileSync(file);
 assets.push({path:relative,status:200,sha256:crypto.createHash('sha256').update(data).digest('hex'),cacheControl:'no-store, no-cache, must-revalidate'});
 res.writeHead(200,{'Content-Type':mime[path.extname(file)]||'application/octet-stream','Cache-Control':'no-store, no-cache, must-revalidate'});res.end(data);
});
async function check(name,fn){if(process.env.PQM_BROWSER_CHECK_FILTER&&!new RegExp(process.env.PQM_BROWSER_CHECK_FILTER).test(name))return;try{const detail=await fn();checks.push({name,result:'PASS',detail});console.log('PASS',name);}catch(e){checks.push({name,result:'FAIL',error:e.stack});console.log('FAIL',name,e.message);}}


const baseFixture=fixture;
const saved={submission_id:'s0',supplier_name:'Synthetic',supplier_code:'00000001',pretty_id:'SYNTHETIC',checked_at:'2026-10-01T10:11:12+03:00',official_verification_url:'https://czo.gov.ua/verify',counts:{ok:16,warning:1,error:0,neutral:0},checks:Array.from({length:17},(_,i)=>({key:'signer'+i,label:'Synthetic '+i,detail:'Stored evidence '+i,status:i<16?'ok':'warning'})),category_results:{signature:{status:'ok'},mvs:{status:'warning'}}};
let starts=0;
fixture=function(url){
 if(url.pathname.endsWith('/document-check-result'))return structuredClone(saved);
 if(url.pathname.endsWith('/verify-documents/start')){starts++;return{status:'complete',job_id:'synthetic-'+starts,result:structuredClone(saved)}}
 if(url.pathname==='/api/uo-work-queue'&&url.searchParams.get('summary')==='application-statistics')return{items:[{review_officer:'Synthetic',protocol_officer:'Synthetic',entity_type:'legal_entity',status:'pending',total:3,date:'2026-11-01'}],totals:{total:3,pending:3},filter_options:{category:['Овочі'],dk_code:codes,review_officer:['Synthetic'],protocol_officer:['Synthetic']},diagnostics:{}};
 return baseFixture(url);
};
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const origin='http://127.0.0.1:'+server.address().port;
 const browser=await chromium.launch({headless:true,executablePath:process.env.PQM_CHROMIUM_EXECUTABLE});
 try{for(theme of ['light','dark']){
 const context=await browser.newContext({viewport:{width:1440,height:1000}});
 await context.route('**/*',route=>new URL(route.request().url()).origin===origin?route.continue():route.abort());
 const page=await context.newPage();page.setDefaultTimeout(7000);page.on('pageerror',e=>errors.push({theme,message:e.message}));
 await page.goto(origin,{waitUntil:'networkidle'});await page.waitForFunction(()=>typeof openDocs==='function');
 const row={id:'s0',participant:'Synthetic',edrpou:'00000001',qualificationId:'SYNTHETIC',decision:'Очікує рішення',documentCheckStatus:'warning',documents:[{id:'one',url:'https://documents.prozorro.gov.ua/synthetic.pdf',title:'Synthetic.pdf',format:'application/pdf'}]};row.supplierDocuments=row.documents;
 const open=async(edit={})=>page.evaluate(row=>{const r={...row,supplierDocuments:row.documents};openDocs(r,r.documents,'Документи заявки та кваліфікації')},{...row,...edit});
 await check(theme+' full application boot',async()=>{assert.equal(await page.locator('#docsDialog').count(),1);assert.equal(await page.locator('#documentCheckDialog').count(),1);assert.equal(errors.filter(x=>x.theme===theme).length,0)});
 await check(theme+' unlocked documents retain selection and verification',async()=>{await open();assert.equal(await page.locator('.doc-analysis-tag:disabled').count(),0);assert.equal(await page.locator('.doc-analysis-tag').count(),3);assert.equal(await page.locator('#verifyDocumentsBtn').isEnabled(),true);await page.locator('#docsDialog button[value=cancel]').last().click()});
 for(const decision of ['Допущено','Відхилено'])await check(theme+' '+decision+' documents readonly with download',async()=>{await open({decision});assert.equal(await page.locator('.doc-analysis-tag:disabled').count(),3);assert.equal(await page.locator('#verifyDocumentsBtn').isDisabled(),true);assert.equal(await page.getByRole('link',{name:'Відкрити',exact:true}).isVisible(),true);assert.equal(await page.locator('#archiveDownloadBtn').getAttribute('href'),'/api/applications/s0/archive');await page.screenshot({path:path.join(OUT,theme+'-documents-'+(decision==='Допущено'?'admitted':'rejected')+'.png')});await page.locator('#docsDialog button[value=cancel]').last().click()});
 for(const role of ['admin','officer','viewer'])await check(theme+' '+role+' saved result remains factual and readonly',async()=>{const before=starts;await page.evaluate(({row,role})=>{document.querySelector('#roleSelect').value=role;return openSavedDocumentCheck({...row,decision:'Допущено'})},{row,role});await page.waitForSelector('#documentCheckBody .check-summary');assert.equal(await page.locator('#documentCheckBody .check-summary b').allTextContents().then(a=>a.join(',')),'16,1,0');assert.equal(await page.locator('#documentCheckBody .check-row').count(),17);assert.equal(await page.locator('#rerunDocumentCheckBtn').isDisabled(),true);assert.equal(await page.locator('#officialSignatureCheck').getAttribute('href'),'https://czo.gov.ua/verify');assert.match(await page.locator('#documentCheckSubtitle').innerText(),/2026/);assert.equal(starts,before);await page.screenshot({path:path.join(OUT,theme+'-saved-'+role+'.png')});await page.locator('#documentCheckDialog button[value=cancel]').last().click()});
 await check(theme+' never checked locked row cannot start',async()=>{const before=starts;await page.evaluate(row=>openSavedDocumentCheck({...row,decision:'Допущено',documentCheckStatus:''}),row);assert.match(await page.locator('#documentCheckBody').innerText(),/Не перевірено/);assert.equal(await page.locator('#rerunDocumentCheckBtn').isDisabled(),true);assert.equal(starts,before);await page.locator('#documentCheckDialog button[value=cancel]').last().click()});
 await check(theme+' never checked unlocked view does not start automatically',async()=>{await page.evaluate(()=>document.querySelector('#roleSelect').value='admin');const before=starts;await page.evaluate(row=>openSavedDocumentCheck({...row,documentCheckStatus:''}),row);assert.equal(starts,before);assert.match(await page.locator('#documentCheckBody').innerText(),/Не перевірено/);assert.equal(await page.locator('#rerunDocumentCheckBtn').isEnabled(),true);await page.locator('#documentCheckDialog button[value=cancel]').last().click()});
 await check(theme+' explicit rerun still works before row locking',async()=>{await page.evaluate(row=>openSavedDocumentCheck(row),row);await page.waitForSelector('#documentCheckBody .check-summary');const before=starts;await page.locator('#rerunDocumentCheckBtn').click();await page.waitForFunction(()=>document.querySelector('#documentCheckBody .check-summary'));assert.equal(starts,before+1);await page.locator('#documentCheckDialog button[value=cancel]').last().click()});
 await context.close();
 }}finally{await browser.close();await new Promise(r=>server.close(r))}
 const report={synthetic_only:true,full_shipped_html_and_script_order:true,checks,errors,mutations,reads,starts,failures:checks.filter(c=>c.result==='FAIL')};fs.writeFileSync(path.join(OUT,'results.json'),JSON.stringify(report,null,2));
 console.log(JSON.stringify({checks:checks.length,failures:report.failures,errors,mutations},null,2));if(report.failures.length||errors.length||mutations.length)process.exitCode=1;
})().catch(e=>{console.error(e);process.exitCode=1;server.close()});
