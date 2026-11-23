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
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const origin='http://127.0.0.1:'+server.address().port;
 try{
  for(theme of ['light','dark'])for(const zoom of [1,.9]){
   const context=await chromium.launchPersistentContext(path.join(OUT,'profile-'+theme+'-'+zoom),{headless:true,viewport:{width:1920,height:1080},executablePath:process.env.PQM_CHROMIUM_EXECUTABLE});
   contexts.push(context);await context.route('**/*',r=>!/^https?:/.test(r.request().url())||new URL(r.request().url()).origin===origin?r.continue():r.abort());
   const settings=await context.newPage();await settings.goto('chrome://settings');
   await settings.evaluate(zoom=>new Promise(resolve=>chrome.settingsPrivate.setDefaultZoom(zoom,resolve)),zoom);
   const confirmedZoom=await settings.evaluate(()=>new Promise(resolve=>chrome.settingsPrivate.getDefaultZoom(resolve)));assert(Math.abs(confirmedZoom-zoom)<.001);await settings.close();
   const page=await context.newPage();page.setDefaultTimeout(10000);page.on('pageerror',e=>errors.push({theme,zoom,error:e.message}));
   await page.goto(origin,{waitUntil:'networkidle'});await page.waitForTimeout(400);await page.evaluate(theme=>{document.documentElement.dataset.theme=theme;document.querySelector('#loginGate').hidden=true;document.querySelector('#applicationShell').hidden=false},theme);
   await page.evaluate(()=>{for(const key of Object.keys(localStorage))if(key.startsWith('pqm-document-selection:synthetic-'))localStorage.removeItem(key)});
   for(const [scenario,make] of Object.entries(scenarios)){
    const reviewed=['noMatch','many'].includes(scenario);row={...base,...make(),id:'synthetic-'+theme+'-'+zoom+'-'+scenario,decision:reviewed?'Допущено':'Очікує рішення',status:reviewed?'active':'pending',qualification_status:reviewed?'active':'pending',publication_date:reviewed?'2026-11-21':'',protocol_decision:reviewed?'admit':''};assert.equal(Boolean(row.decision_documents.length),reviewed,'normal workflow fixture must agree with publication state');
    await page.evaluate(async()=>{statsSignature='';await loadRows();await loadStats()});const clip=page.locator('#applicationsTable .paperclip:not(.registry-paperclip)').first();await clip.waitFor();const count=Number((await clip.innerText()).replace(/\D/g,'')),start=verification.length;
    if(scenario==='auto'){await clip.scrollIntoViewIfNeeded();await page.screenshot({path:path.join(OUT,theme+'-'+Math.round(zoom*100)+'-registry-counter.png')});}
    await clip.click();await page.locator('#docsDialog').waitFor();let f=await facts(page);inside(f);
    assert.equal(f.title,'Документи заявки та кваліфікації');assert(f.subtitle.startsWith('03220000-9 · 12345678 · '));assert(!f.subtitle.includes(base.pretty_id));assert.equal(f.checkboxes,0);assert.equal(count,f.supplierCount);for(const group of f.numbers)assert.deepEqual(group.numbers,Array.from({length:group.numbers.length},(_,i)=>i+1));for(const select of Object.values(f.selects))for(const option of select.options)if(option.value!=='')assert(option.text.startsWith((Number(option.value)+1)+'. '),'selector number must match supplier row, not option position');assert.deepEqual(f.footerLabels,['⇩ Завантажити всі','Закрити']);assert.equal(verification.length,start,'automatic selection must not run verification');
    if(f.numberStyle){assert.equal(f.numberStyle.fontSize,'11px');assert(f.numberStyle.right<=f.numberStyle.iconLeft+1);}
    assert.equal(f.theme,theme);assert.equal(f.bodyZoom,'1');assert(Math.abs(f.dpr-zoom)<.01,'actual browser zoom must change DPR');
    assert(f.bar.y>=f.header.bottom-1&&f.bar.bottom<=f.list.y+1);assert(f.footer.y>=f.list.bottom-1);assert(f.bar.right<=f.rect.right+1);
    assert(f.downloadLinks.every(l=>l.title==='Завантажити файл'&&l.download));
    if(theme==='dark')assert(f.downloadLinks.every(l=>l.background!=='rgb(255, 255, 255)'));
    if(scenario==='auto'&&theme==='light'&&zoom===1){const downloaded=page.waitForEvent('download');await page.locator('#docsList .doc-download').first().click();assert.equal((await downloaded).suggestedFilename(),'Архів.zip');const archive=page.waitForEvent('download');await page.click('#archiveDownloadBtn');assert.equal((await archive).suggestedFilename(),'UI001-synthetic.zip');}
    if(scenario==='auto'){
     assert.equal(f.selects.docsSignatureFile.value,'1');assert.equal(f.selects.docsMvsFile.value,'');assert(!f.verifyDisabled);
     await page.selectOption('#docsMvsFile','');assert(!(await facts(page)).verifyDisabled);
     await page.click('#verifyDocumentsBtn');await page.waitForTimeout(100);assert.deepEqual(verification.at(-1).selection,{'1':['signature']});
     assert((await page.locator('#documentCheckSubtitle').innerText()).startsWith('03220000-9 · 12345678 · '));
     await page.locator('#documentCheckDialog').screenshot({path:path.join(OUT,theme+'-'+Math.round(zoom*100)+'-partial-result.png')});
     await page.evaluate(()=>document.querySelector('#documentCheckDialog').close());await clip.click();
     assert.equal((await facts(page)).selects.docsMvsFile.value,'');
     await page.selectOption('#docsSignatureFile','');assert((await facts(page)).verifyDisabled);
     const requestsBefore=verification.length;await page.evaluate(()=>verifyDocuments());assert.equal(verification.length,requestsBefore);
     await page.evaluate(()=>document.querySelector('#docsDialog').close());await clip.click();assert((await facts(page)).verifyDisabled);
     await page.selectOption('#docsMvsFile','2');assert(!(await facts(page)).verifyDisabled);
     await page.locator('#docsDialog').screenshot({path:path.join(OUT,theme+'-'+Math.round(zoom*100)+'-mvs-only.png')});
     await page.click('#verifyDocumentsBtn');await page.waitForTimeout(100);assert.deepEqual(verification.at(-1).selection,{'2':['mvs']});
     await page.evaluate(()=>document.querySelector('#documentCheckDialog').close());await clip.click();await page.selectOption('#docsSignatureFile','1');
     await page.click('#verifyDocumentsBtn');await page.waitForTimeout(100);assert.deepEqual(verification.at(-1).selection,{'1':['signature'],'2':['mvs']});
     await page.evaluate(()=>document.querySelector('#documentCheckDialog').close());await clip.click();f=await facts(page);
    }
    if(scenario==='manual'){
     assert.equal(f.selects.docsSignatureFile.options.length,3);assert.equal(f.selects.docsMvsFile.options.length,3);assert.equal(f.selects.docsSignatureFile.value,'');assert.equal(f.selects.docsMvsFile.value,'');assert(f.verifyDisabled);
     await page.screenshot({path:path.join(OUT,theme+'-'+Math.round(zoom*100)+'-manual-awaiting-selection.png')});
     await page.selectOption('#docsSignatureFile','3');await page.selectOption('#docsMvsFile','4');assert.equal(verification.length,start);
     await page.click('#verifyDocumentsBtn');await page.waitForFunction(()=>document.querySelector('#documentCheckDialog').open);await page.waitForTimeout(100);
     assert.equal(verification.length,start+1);assert.deepEqual(verification.at(-1).selection,{'3':['signature'],'4':['mvs']});await page.evaluate(()=>document.querySelector('#documentCheckDialog').close());
     await clip.click();f=await facts(page);assert.equal(f.selects.docsSignatureFile.value,'3');assert.equal(f.selects.docsMvsFile.value,'4');
    }
    if(scenario==='noMatch'||scenario==='empty'){assert(f.verifyDisabled);for(const select of Object.values(f.selects)){assert(select.disabled);assert.equal(select.options[0].text,'Файл не знайдено');}}
    if(['auto','empty','noMatch'].includes(scenario)){assert(f.listScrollHeight<=f.listClientHeight+1,'short document list must not scroll');assert(f.rect.height<f.viewport.height-50,'short dialog must fit content instead of filling viewport');}
    if(scenario==='many'){
     assert(f.rect.height>=f.viewport.height-40,'long list should use available height');
     assert(f.listScrollHeight>f.listClientHeight);const before=f;
     await page.locator('#docsList').evaluate(e=>e.scrollTop=e.scrollHeight);f=await facts(page);
     for(const key of ['header','bar','footer'])assert(Math.abs(before[key].y-f[key].y)<1,key+' must stay fixed');
     const last=await page.locator('#docsList .doc').last().boundingBox();assert(last.y+last.height<=f.list.bottom+2);await page.locator('#docsList').evaluate(e=>e.scrollTop=0);
    }
    await page.screenshot({path:path.join(OUT,theme+'-'+Math.round(zoom*100)+'-'+scenario+'.png')});report.push({theme,zoom:confirmedZoom,scenario,count,...f});
    if(scenario==='auto'){
     for(const [x,y] of [[9999,9999],[-500,-500]]){const h=await page.locator('#docsDialog header').boundingBox();await page.mouse.move(h.x+Math.min(h.width/3,100),h.y+20);await page.mouse.down();await page.mouse.move(x,y,{steps:6});await page.mouse.up();inside(await facts(page));}
     const h=await page.locator('#docsDialog header').boundingBox();await page.mouse.move(h.x+100,h.y+20);await page.mouse.down();await page.mouse.move(9999,9999,{steps:5});await page.mouse.up();const bounded=await facts(page);inside(bounded);report.push({theme,zoom,scenario:'drag-boundary',...bounded});await page.screenshot({path:path.join(OUT,theme+'-'+Math.round(zoom*100)+'-drag.png')});
    }
    if(scenario==='auto'){
     for(const size of [{width:1366,height:768},{width:900,height:650}]){
      await page.setViewportSize(size);await page.waitForTimeout(100);const resized=await facts(page);inside(resized);
      assert(resized.bar.bottom<=resized.list.y+1);assert(resized.footer.bottom<=resized.viewport.height+1);
      report.push({theme,zoom,scenario:'resize-'+size.width,...resized});
     }
     await page.setViewportSize({width:1920,height:1080});await page.waitForTimeout(100);
    }
    await page.evaluate(()=>document.querySelector('#docsDialog').close());
   }
   // Negative consistency cases intentionally include inconsistent status/document combinations
   // to prove document count never overrides locked. Only coherent pairs are visual examples.
   // Status gating uses the actual registry locked(row, 'managerName') and handler.
   for(const [status,decision] of [['pending','Очікує рішення'],['admitted','Допущено'],['rejected','Відхилено']])for(const withReview of [false,true]){
    row={...base,...scenarios.auto(),id:'status-'+theme+'-'+zoom+'-'+status+'-'+withReview,decision,status:status==='pending'?'pending':status==='admitted'?'active':'unsuccessful',qualification_status:status==='pending'?'pending':status==='admitted'?'active':'unsuccessful',decision_documents:[doc('review-sign','sign.p7s','application/pkcs7-signature'),doc('review-pdf','Протокол.pdf','application/pdf')],document_check_status:'ok'};
    if(!withReview)row.decision_documents=[];
    await page.evaluate(async()=>{statsSignature='';await loadRows();await loadStats()});const clip=page.locator('#applicationsTable .paperclip:not(.registry-paperclip)').first();await clip.click();let f=await facts(page);
    const blocked=status!=='pending',start=verification.length;
    assert.equal(f.verifyDisabled,blocked);for(const select of Object.values(f.selects))assert.equal(select.disabled,blocked);
    assert.equal(f.supplierCount,3);assert.equal(f.decisionCount,withReview?2:0);inside(f);
    if(zoom===1&&((status==='pending'&&!withReview)||(status!=='pending'&&withReview)))await page.screenshot({path:path.join(OUT,theme+'-100-status-'+status+'-'+(withReview?'with-review':'without-review')+'.png')});
    if(blocked){
     await page.evaluate(()=>document.querySelector('#verifyDocumentsBtn').click());await page.evaluate(()=>verifyDocuments());assert.equal(verification.length,start,'locked rows cannot start a job, including direct handler invocation');
     assert(await page.locator('#docsList .doc-download').first().isVisible());const file=page.waitForEvent('download');await page.locator('#docsList .doc-download').first().click();assert.equal((await file).suggestedFilename(),'Архів.zip');
     const archive=page.waitForEvent('download');await page.click('#archiveDownloadBtn');assert.equal((await archive).suggestedFilename(),'UI001-synthetic.zip');
     await page.evaluate(()=>document.querySelector('#docsDialog').close());
    }else{
     await page.click('#verifyDocumentsBtn');await page.waitForFunction(()=>document.querySelector('#documentCheckDialog').open);await page.waitForTimeout(75);assert.equal(verification.length,start+1);assert.deepEqual(verification.at(-1).selection,{'1':['signature']});await page.evaluate(()=>document.querySelector('#documentCheckDialog').close());
    }
    const beforeSaved=verification.length;await page.evaluate(row=>openSavedDocumentCheck(mapRow(row)),row);
    await page.locator('#documentCheckBody').getByText('UI001 saved synthetic result').waitFor();assert.equal(await page.locator('#rerunDocumentCheckBtn').isDisabled(),blocked);assert.equal(verification.length,beforeSaved,'reading saved results must not start a job');
    await page.evaluate(()=>document.querySelector('#documentCheckDialog').close());
    report.push({theme,zoom,scenario:'status-'+status,withReview,blocked,savedResultReadable:true,downloadsAvailable:true,...f});
   }
   // Shared historical/registry flows retain their read-only verification behavior.
   await page.evaluate(base=>{const r=mapRow({...base,documents:[],decision_documents:[]});openDocs(r,[{title:'Рішення.pdf',url:'/synthetic-files/registry'}],'Документи рішення у реєстрі')},base);
   assert(await page.locator('#docsVerificationBar').isHidden());assert.equal(await page.locator('#docsList .doc-number').first().innerText(),'1');await page.evaluate(()=>document.querySelector('#docsDialog').close());
   await page.evaluate(base=>openHistoryDocuments(mapRow(base),{supplier:base.documents,decision:base.decision_documents}),base);assert(await page.locator('#docsVerificationBar').isHidden());for(const group of (await facts(page)).numbers)assert.deepEqual(group.numbers,Array.from({length:group.numbers.length},(_,i)=>i+1));await page.evaluate(()=>document.querySelector('#docsDialog').close());
   await page.evaluate(base=>{const r=mapRow(base);r.historicalReadOnly=true;openDocs(r,r.documents,'Документи заявки та кваліфікації')},base);const readonly=await facts(page);assert(readonly.verifyDisabled);assert(Object.values(readonly.selects).every(s=>s.disabled));await page.evaluate(()=>document.querySelector('#docsDialog').close());
   await context.close();
  }
  assert.deepEqual(writes,[]);assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(OUT,'acceptance-results.json'),JSON.stringify({result:'PASS',report,errors,writes,verification},null,2));console.log('UI001_BROWSER=PASS captures='+report.length+' verificationMocks='+verification.length);
 }finally{for(const context of contexts)await context.close();await new Promise(r=>server.close(r));}
})().catch(e=>{console.error(e);fs.writeFileSync(path.join(OUT,'failure.json'),JSON.stringify({error:e.stack,report,errors,writes,verification},null,2));process.exitCode=1;server.close();});
