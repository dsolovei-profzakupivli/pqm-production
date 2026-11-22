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
 if(u.pathname==='/api/runtime-features')return{environment:'test_web',sandbox_mode:true,background_jobs:{disabled:true,environment_locked:true},scheduler_jobs:[],google:{enabled:false}};
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
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const origin='http://127.0.0.1:'+server.address().port;
 try{
  for(theme of ['light','dark'])for(const zoom of [1,.9]){
   const context=await chromium.launchPersistentContext(path.join(OUT,'profile-'+theme+'-'+zoom),{headless:true,viewport:{width:1920,height:1080},executablePath:process.env.PQM_CHROMIUM_EXECUTABLE});
   try{
    await context.route('**/*',r=>!/^https?:/.test(r.request().url())||new URL(r.request().url()).origin===origin?r.continue():r.abort());
    const settings=await context.newPage();await settings.goto('chrome://settings');await settings.evaluate(z=>new Promise(resolve=>chrome.settingsPrivate.setDefaultZoom(z,resolve)),zoom);await settings.close();
    const page=await context.newPage();page.setDefaultTimeout(10000);page.on('pageerror',e=>errors.push({theme,zoom,message:e.message}));
    await page.goto(origin,{waitUntil:'networkidle'});assert.equal(await page.evaluate(()=>document.documentElement.dataset.pqmEnvironment),'sandbox');await page.waitForTimeout(300);await page.evaluate(theme=>{document.documentElement.dataset.theme=theme;document.querySelector('#loginGate').hidden=true;document.querySelector('#applicationShell').hidden=false},theme);
    for(const scenario of ['not-checked','full','legacy-locked','signature-only','partial-legacy','many']){
     row={...baseRow,id:'ui002-'+theme+'-'+zoom+'-'+scenario,supplier_name:legacy.supplier_name,documents:[supplier[0],supplier[1]],decision_documents:[],status:'pending',qualification_status:'pending',decision:'Очікує рішення',document_check_status:'error'};
     fixtureData=JSON.parse(JSON.stringify(modern));
     if(scenario==='legacy-locked'){row.decision='Допущено';row.status=row.qualification_status='active';row.decision_documents=[decision[0]];fixtureData=JSON.parse(JSON.stringify(legacy));}
     if(scenario==='not-checked')row.document_check_status='';
     if(scenario==='signature-only'){fixtureData.checks=modern.checks.filter(c=>!c.key.startsWith('mvs_')&&c.key!=='contract_experience');fixtureData.counts=totals(fixtureData.checks);}
     if(scenario==='partial-legacy'){fixtureData.checks=JSON.parse(JSON.stringify(legacy.checks));fixtureData.counts=totals(modern.checks);}
     if(scenario==='many'){fixtureData.checks=modern.checks.concat(Array.from({length:40},(_,i)=>check('legacy_extra_'+i,'Раніше збережене поле '+i,'warning','Синтетичні історичні дані')));fixtureData.counts=totals(fixtureData.checks);}
     await page.evaluate(async()=>{statsSignature='';await loadRows();await loadStats()});
     const starts=verification.length,savedReads=requests.filter(x=>x.includes('/document-check-result')).length;
     await page.evaluate(row=>openSavedDocumentCheck(mapRow(row)),row);let f=await facts(page);inside(f);assert(Math.abs(f.dpr-zoom)<.01);assert.equal(f.theme,theme);assert.equal(verification.length,starts,'opening must not start a check');
     if(scenario==='not-checked'){
      assert(f.text.includes('Не перевірено'));assert.equal(await page.locator('#rerunDocumentCheckBtn').innerText(),'Перевірити');assert.equal(f.rerunDisabled,false);assert.equal(requests.filter(x=>x.includes('/document-check-result')).length,savedReads);assert(f.rect.height<f.viewport.height/2);
     }else{
      for(const key of ['ok','warning','error'])assert.equal(f.counts[key],fixtureData.counts[key]);
      assert.equal(f.rerunDisabled,scenario==='legacy-locked');
      if(['full','legacy-locked','partial-legacy'].includes(scenario))grid(f);
      if(scenario==='full'){
       assert.equal(await page.locator('[data-check-key="eds_verification"] .document-check-value').innerText(),'Перевірено');
       for(const [key,value] of [['code','12345678'],['signer','ІВАНЕНКО ІВАН ІВАНОВИЧ'],['mvs_person','ІВАНЕНКО ІВАН ІВАНОВИЧ'],['mvs_age','37 к.д.'],['mvs_criminal_liability','ВІДСУТНІ'],['mvs_unspent_conviction','ВІДСУТНІ'],['mvs_wanted_status','ВІДСУТНІ']])assert.equal(await page.locator(`[data-check-key="${key}"] .document-check-value`).innerText(),value);
       for(const status of ['ok','warning','error']){
        const icon=page.locator(`.document-check-field.${status}:not([data-experience-state]) .document-check-indicator`).first();
        assert.equal(await icon.innerText(),status==='ok'?'✓':'!');assert.equal(await icon.evaluate(e=>getComputedStyle(e).color),'rgb(255, 255, 255)');
       }
       const contractParts=await page.locator('.contract-experience-links a').first().evaluate(e=>[...e.children].map(n=>({text:n.textContent,y:n.getBoundingClientRect().y})));
       assert(contractParts.every(p=>Math.abs(p.y-contractParts[0].y)<3),JSON.stringify(contractParts));assert(/^\d{2}\.\d{2}\.\d{4}$/.test(contractParts[1].text));
       assert(!(await page.locator('[data-check-key="contract_experience"] .document-check-value').innerText()).startsWith('+'));
       const originalBody=await page.locator('#documentCheckBody').innerHTML();
       await page.evaluate(()=>{document.querySelector('#documentCheckBody').innerHTML=PqmDocumentCheck.render({checks:[{key:'contract_experience',label:'Досвід',status:'error',search_status:'none',detail:'Договорів не знайдено'}],counts:{ok:0}},{esc,renderBusinessRows})});
       const noExperience=page.locator('[data-experience-state="none"] .document-check-indicator');assert.equal(await noExperience.innerText(),'−');assert.equal(await noExperience.evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(238, 242, 247)');
       await page.locator('#documentCheckBody').evaluate((e,html)=>e.innerHTML=html,originalBody);
       assert(!f.fields.mvs_seal);if(theme==='dark')assert(f.sections.every(s=>s.background==='rgb(25, 52, 81)'&&s.color==='rgb(237, 243, 252)'));}
      if(scenario==='legacy-locked'){assert(f.fields.mvs_seal);await page.evaluate(()=>document.querySelector('#rerunDocumentCheckBtn').click());await page.evaluate(()=>verifyDocuments());assert.equal(verification.length,starts);}
      if(scenario==='partial-legacy'){assert(f.fields.mvs_seal);assert.equal(f.counts.warning,modern.counts.warning);}
      if(theme==='dark'){
       assert.equal(f.links.find(l=>l.text==='Перевірити в ЦЗО').background,'rgb(25, 52, 81)');
       const contract=f.links.find(l=>l.text.startsWith('UA-'));if(contract){assert.equal(contract.background,'rgb(19, 40, 64)');assert.equal(contract.color,'rgb(134, 189, 255)');}
      }
     }
     if(scenario==='full'){
      const evidence=JSON.stringify(fixtureData);
      for(const layout of ['b']){
       await page.locator('.document-check-results').evaluate((e,layout)=>e.dataset.resultLayout=layout,layout);
       const measurements=await page.locator('.document-check-text').evaluateAll(elements=>elements.map(e=>{
        const label=e.querySelector('strong').getBoundingClientRect(),value=e.querySelector('.document-check-value').getBoundingClientRect();
        return {label:e.querySelector('strong').textContent,left:label.x,labelRight:label.right,valueLeft:value.x,valueRight:value.right,sameLine:Math.abs(label.y-value.y)<3,gap:value.x-label.right,font:getComputedStyle(e.querySelector('.document-check-value')).fontSize};
       }));
       assert(measurements.some(m=>m.sameLine));assert(measurements.every(m=>m.font==='14px'));
       if(layout==='b')assert(measurements.filter(m=>m.sameLine).every(m=>Math.abs(m.gap-12)<1));
       const experience=page.locator('[data-experience-state="found"] .document-check-indicator');assert.equal(await experience.textContent(),'+');assert.equal(await experience.evaluate(e=>getComputedStyle(e).color),'rgb(255, 255, 255)');

       report.push({theme,zoom,scenario:'variant-'+layout,measurements});
      }
      assert.equal(JSON.stringify(fixtureData),evidence);await page.locator('.document-check-results').evaluate(e=>e.dataset.resultLayout='b');
     }
     if(zoom===1&&scenario==='full'){
      const filename=scenario==='full'?'full-'+theme+'.png':scenario==='not-checked'?'not-checked.png':'locked-saved.png';await page.screenshot({path:path.join(OUT,filename)});
     }
     if(scenario==='many'){
      assert(f.scrollHeight>f.clientHeight);const before=f;await page.locator('#documentCheckBody').evaluate(e=>e.scrollTop=e.scrollHeight);f=await facts(page);for(const key of ['header','footer'])assert(Math.abs(f[key].y-before[key].y)<1);await page.locator('#documentCheckBody').evaluate(e=>e.scrollTop=0);
     }
     if(scenario==='full'||scenario==='not-checked'){
      for(const [x,y] of [[9999,9999],[-500,-500]]){const h=await page.locator('#documentCheckDialog header').boundingBox();await page.mouse.move(h.x+100,h.y+20);await page.mouse.down();await page.mouse.move(x,y,{steps:5});await page.mouse.up();inside(await facts(page));}
      await page.setViewportSize({width:1366,height:768});await page.waitForTimeout(100);inside(await facts(page));await page.setViewportSize({width:1920,height:1080});
     }
     report.push({theme,zoom,scenario,...f});await page.evaluate(()=>document.querySelector('#documentCheckDialog').close());
    }
    // Existing UI001 selection -> existing worker polling -> saved-result fallback.
    row={...baseRow,id:'ui002-transfer-'+theme+'-'+zoom,documents:[supplier[0],supplier[1]],decision_documents:[],decision:'Очікує рішення',document_check_status:'error'};
    fixtureData={...modern,document_check_job_id:'fixture-job'};jobMode='evicted';
    await page.evaluate(row=>{const r=mapRow(row);openDocs(r,r.documents,'Документи заявки та кваліфікації')},row);const before=verification.length;
    await page.click('#verifyDocumentsBtn');await page.locator('[data-check-key="main_signature"]').waitFor();assert.equal(verification.length,before+1);assert.deepEqual(verification.at(-1).selection,{'0':['signature'],'1':['mvs']});assert.equal((await facts(page)).counts.warning,modern.counts.warning);report.push({theme,zoom,scenario:'UI001-selection-and-evicted-job-recovery',result:'PASS'});
    jobMode='technical-error';const saved=JSON.stringify(fixtureData);await page.click('#rerunDocumentCheckBtn');await page.getByText('Synthetic technical failure; stored result preserved',{exact:true}).waitFor();assert.equal(JSON.stringify(fixtureData),saved);await page.evaluate(()=>document.querySelector('#documentCheckDialog').close());await page.evaluate(row=>openSavedDocumentCheck(mapRow(row)),row);assert.equal((await facts(page)).counts.warning,modern.counts.warning);report.push({theme,zoom,scenario:'technical-failure-saved-result-readable',result:'PASS'});await page.evaluate(()=>document.querySelector('#documentCheckDialog').close());jobMode='normal';
    registryRows=['ok','warning','error','empty'].map((status,i)=>({...baseRow,id:'registry-'+i,supplier_name:['Успішна перевірка','Попередження','Помилка перевірки','Документи не перевірено'][i],document_check_status:status==='empty'?'':status,document_check_categories:status==='empty'?{}:{signature:status,mvs:status,experience:i%2===0?'ok':'neutral'}}));
    await page.evaluate(async()=>{const p=profile();p.columns=p.columns.map(c=>({...c,visible:['participant','edrpou','dkCode','documentCheckStatus','documents','decision'].includes(c.key)}));statsSignature='';await loadRows();await loadStats();render()});
    for(const close of await page.locator('#toast button').all())await close.click();await page.waitForTimeout(300);
    assert.equal(await page.locator('.doc-category-badge.ok').count(),2);assert.equal(await page.locator('.doc-category-badge.warning').count(),2);assert.equal(await page.locator('.doc-category-badge.error').count(),2);assert.equal(await page.locator('.doc-category-badge.empty').count(),2);
    assert.equal(await page.locator('.contract-experience-marker.found').count(),2);assert.equal(await page.locator('.contract-experience-marker.neutral').count(),2);
    assert.equal(await page.locator('.contract-experience-marker.found').first().evaluate(e=>getComputedStyle(e).color),'rgb(255, 255, 255)');
    const badgeStyles=await page.locator('.doc-category-badge').evaluateAll(es=>es.map(e=>({state:['ok','warning','error','empty'].find(s=>e.classList.contains(s)),background:getComputedStyle(e).backgroundColor,color:getComputedStyle(e).color,border:getComputedStyle(e).borderTopWidth})));
    const palette=theme==='dark'?{ok:['rgb(23, 62, 56)','rgb(139, 224, 182)'],warning:['rgb(68, 59, 38)','rgb(255, 220, 138)'],error:['rgb(73, 41, 54)','rgb(255, 177, 184)'],empty:['rgb(21, 43, 70)','rgb(237, 243, 252)']}:{ok:['rgb(225, 245, 234)','rgb(8, 122, 76)'],warning:['rgb(255, 243, 205)','rgb(138, 90, 0)'],error:['rgb(254, 231, 231)','rgb(180, 35, 24)'],empty:['rgb(238, 242, 247)','rgb(100, 116, 139)']};
    for(const badge of badgeStyles){assert.deepEqual([badge.background,badge.color],palette[badge.state]);if(theme==='dark'&&badge.state==='empty')assert(Math.abs(parseFloat(badge.border)*zoom-1)<.11,'one-pixel border after Chromium zoom rounding');}
    const historyButton=page.locator('.supplier-history-open').first();assert.equal(await historyButton.evaluate(e=>getComputedStyle(e).backgroundColor),theme==='dark'?'rgb(25, 52, 81)':'rgb(247, 249, 251)');
    if(theme==='dark'){await historyButton.hover();assert.equal(await historyButton.evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(40, 81, 123)');await page.mouse.move(1800,900);}
    const registry=await page.locator('.doc-category-badge,.contract-experience-marker').evaluateAll(es=>es.map(e=>({text:e.textContent,class:e.className,color:getComputedStyle(e).color,background:getComputedStyle(e).backgroundColor,rect:JSON.parse(JSON.stringify(e.getBoundingClientRect()))})));
    const viewportWidth=await page.evaluate(()=>innerWidth);assert(registry.every(e=>e.rect.x>=0&&e.rect.right<=viewportWidth));
    if(zoom===1)await page.screenshot({path:path.join(OUT,'registry-indicators-'+theme+'.png')});report.push({theme,zoom,scenario:'registry-indicators',registry});registryRows=null;
   }finally{await context.close()}
  }
  assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);
  fs.writeFileSync(path.join(OUT,'UI002-browser-results.json'),JSON.stringify({result:'PASS',report,errors,writes,verification},null,2));console.log('UI002_BROWSER=PASS states='+report.length+' mocked-starts='+verification.length);
 }finally{await new Promise(r=>server.close(r))}
})().catch(e=>{console.error(e);fs.writeFileSync(path.join(OUT,'UI002-browser-failure.json'),JSON.stringify({error:e.stack,report,errors,writes},null,2));process.exitCode=1;server.close()});
