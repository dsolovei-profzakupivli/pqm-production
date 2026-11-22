const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),src=fs.readFileSync(path.join(root,'app.js'),'utf8');
const code=src.slice(src.indexOf('const declensionTypeLabels='),src.indexOf('async function deleteDeclension('));
const html=fs.readFileSync(path.join(root,'index.html'),'utf8');
const dialog=html.match(/<dialog id="declensionDialog"[\s\S]*?<\/dialog>/)[0];
const {execFileSync}=require('node:child_process');
const fixtures=JSON.parse(execFileSync(process.env.PQM_PYTHON||(process.platform==='win32'?'python':'python3'),['-X','utf8','-B','-c',`import json,tempfile;from pathlib import Path;from declension import decline_name,OverrideStore
with tempfile.TemporaryDirectory() as t:
 store=OverrideStore(Path(t)/'missing.csv');names=['КОМУНАЛЬНЕ ПІДПРИЄМСТВО «СИНТЕТИЧНЕ»','ПРАТ «СИНТЕТИЧНА ЮРІЯ»','ТОВ «ЗАМОВНИК СИНТЕТИЧНИЙ»'];print(json.dumps({name:{case:decline_name(name,'legal_entity',case,store).as_dict() for case in ('genitive','dative','accusative')} for name in names},ensure_ascii=False))`],{cwd:root,encoding:'utf8'}));
fs.mkdirSync(path.join(root,'evidence'),{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.PQM_TEST_BROWSER});const results=[];
 try{
 for(const theme of ['light','dark']){
  const page=await browser.newPage({viewport:{width:1280,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.route('**/*',route=>route.abort());
  await page.setContent(`<html data-theme="${theme}"><head><style>${['styles.css','filters.css','modules.css','schema_ui.css','ui_improvements.css','ui_final.css','ui_tz2.css','theme.css','halloween.css','halloween_motion.css'].map(f=>fs.readFileSync(path.join(root,f),'utf8')).join('\n')}</style></head><body><input id="declensionSearch"><table><tbody id="declensionBody"></tbody></table><div id="declensionInfo"></div><button id="declensionAdd"></button><dialog id="requestDetailsDialog" open></dialog><section id="requestDetailsBody"><textarea id="unsavedDraft">Незбережена чернетка УО</textarea><div class="violation-party-heading"><button data-card-declension-side="customer" class="ghost violation-card-declension">Відмінювання</button><button data-card-declension-side="supplier" class="ghost violation-card-declension">Відмінювання</button></div><select id="violationProtocolType"><option value="warning">Застереження</option><option value="decline_individual_review">Відмова</option></select><p id="violationProtocolReasons">Потрібний давальний відмінок</p></section>${dialog}</body></html>`);
  await page.evaluate(({fixtures})=>{
   window.$=s=>document.querySelector(s);window.$$=s=>[...document.querySelectorAll(s)];window.API='/api';window.esc=s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');window.toast=()=>{};
   window.currentMe={role:'admin',permissions:{'declension.read':true,'declension.manage':true}};window.stored={};window.writes=[];window.reloads=0;window.fullReopens=0;window.unresolvedDeclensionsByReport=new Map();window.fixtures=fixtures;window.failPreview=false;window.latePreview=null;
   window.reportId='synthetic-report';window.delayList=false;window.name='КОМУНАЛЬНЕ ПІДПРИЄМСТВО «СИНТЕТИЧНЕ»';window.customer='ТОВ «ЗАМОВНИК СИНТЕТИЧНИЙ»';
   window.preview=original=>{const row=stored[original];return{item:row||null,preview:Object.fromEntries(Object.entries(fixtures[original]).map(([k,v])=>[k,row?.[k]?{...v,value:row[k],source:'override',status:'resolved'}:v]))}};
   window.item=()=>({id:reportId,author_code:'00000001',defendant_code:'00447853',author_name:customer,defendant_name:name,protocol_readiness:{reasons:stored[name]?.dative?[]:['Потрібна перевірена форма'],declensions:[{subject_label:'Постачальник',entity_type:'legal_entity',original:name,grammatical_case:'dative',status:stored[name]?.dative?'resolved':'unresolved'}]},protocol_readiness_individual:{declensions:[]}});
   window.request=async(url,opts={})=>{
    if(opts.method){const value=JSON.parse(opts.body);writes.push({method:opts.method,payload:value});stored[value.original]={...value,id:'saved'};return{saved:true,item:stored[value.original]}}
    if(url.includes('/violation-reports/')){reloads++;return item()}const u=new URL(url,'http://synthetic.invalid');if(u.searchParams.get('preview')==='1'){
     if(failPreview)throw new Error('synthetic preview failure');const original=u.searchParams.get('original');if(latePreview&&original===name)return new Promise(resolve=>window.resolveLate=()=>resolve(preview(original)));return preview(original);
    }if(delayList)return new Promise(resolve=>window.resolveDelayedList=()=>resolve({items:Object.values(stored)}));return{items:Object.values(stored)};
   };
   window.reloadOpenViolationReportDetail=async()=>{reloads++;const fresh=item();bindViolationCardDeclensionActions(fresh);$('#violationProtocolReasons').hidden=Boolean(stored[name]?.dative);$('#violationProtocolType').onchange=()=>updateViolationCardDeclensionStatus(fresh);return fresh};
   window.openViolationReportById=()=>{fullReopens++};window.showModule=()=>{};
  },{fixtures});
  await page.addScriptTag({content:code});await page.evaluate(()=>{$('#declensionSave').onclick=saveDeclensionEditor;activeDeclensionRequest=item();bindViolationCardDeclensionActions(activeDeclensionRequest)});
  const supplier=page.locator('[data-card-declension-side="supplier"]');assert(await supplier.evaluate(e=>e.classList.contains('needs-declension-review')));assert(!await page.locator('[data-card-declension-side="customer"]').evaluate(e=>e.classList.contains('needs-declension-review')));
  await page.selectOption('#violationProtocolType','decline_individual_review');await page.evaluate(()=>updateViolationCardDeclensionStatus(item()));assert(!await supplier.evaluate(e=>e.classList.contains('needs-declension-review')));await page.selectOption('#violationProtocolType','warning');await page.evaluate(()=>updateViolationCardDeclensionStatus(item()));
  const colours=await supplier.evaluate(e=>({fg:getComputedStyle(e).color,bg:getComputedStyle(e).backgroundColor}));const lum=c=>{const v=c.match(/[\d.]+/g).slice(0,3).map(x=>{const n=Number(x)/255;return n<=0.04045?n/12.92:((n+0.055)/1.055)**2.4});return v[0]*0.2126+v[1]*0.7152+v[2]*0.0722};assert((Math.max(lum(colours.fg),lum(colours.bg))+0.05)/(Math.min(lum(colours.fg),lum(colours.bg))+0.05)>=4.5);
  await supplier.click();await page.waitForFunction(()=>declensionPreviewState&&!declensionPreviewState.loading);
  assert.equal(await page.locator('#declensionGenitive').inputValue(),fixtures['КОМУНАЛЬНЕ ПІДПРИЄМСТВО «СИНТЕТИЧНЕ»'].genitive.value);assert.equal(await page.locator('#declensionDative').inputValue(),'');assert.equal(await page.locator('[data-confirm-declension="genitive"]').isChecked(),false);assert.equal(await page.locator('[data-declension-origin="genitive"]').getAttribute('data-source'),'automatic');assert.equal(await page.evaluate(()=>writes.length),0);
  await page.screenshot({path:path.join(root,`evidence/declension-${theme}.png`)});
  await page.locator('#declensionDative').fill('СИНТЕТИЧНОМУ ПОСТАЧАЛЬНИКУ');await page.locator('#declensionSave').click();await page.waitForFunction(()=>reloads===1);
  const saved=await page.evaluate(()=>writes[0]);assert.equal(saved.payload.dative,'СИНТЕТИЧНОМУ ПОСТАЧАЛЬНИКУ');assert.equal(saved.payload.genitive,'');assert.equal(saved.payload.accusative,'');assert.equal(await page.evaluate(()=>fullReopens),0);assert(!await supplier.evaluate(e=>e.classList.contains('needs-declension-review')));assert(await page.locator('#violationProtocolReasons').isHidden());assert.equal(await page.locator('#unsavedDraft').inputValue(),'Незбережена чернетка УО');
  await supplier.click();await page.waitForFunction(()=>declensionPreviewState&&!declensionPreviewState.loading);assert.equal(await page.locator('#declensionDative').inputValue(),'СИНТЕТИЧНОМУ ПОСТАЧАЛЬНИКУ');assert.equal(await page.locator('[data-declension-origin="dative"]').getAttribute('data-source'),'override');await page.evaluate(()=>$('#declensionDialog').close());
  // Explicitly confirming an unchanged automatic form persists that case only.
  await supplier.click();await page.waitForFunction(()=>declensionPreviewState&&!declensionPreviewState.loading);await page.locator('[data-confirm-declension="genitive"]').check();await page.locator('#declensionSave').click();await page.waitForFunction(()=>reloads===2);assert.equal((await page.evaluate(()=>writes[1])).payload.genitive,fixtures['КОМУНАЛЬНЕ ПІДПРИЄМСТВО «СИНТЕТИЧНЕ»'].genitive.value);
  // Read-only role retains preview, but cannot save even through a direct handler call.
  await page.evaluate(()=>currentMe={role:'viewer',permissions:{'declension.read':true,'declension.manage':false}});await supplier.click();await page.waitForFunction(()=>declensionPreviewState&&!declensionPreviewState.loading);assert(await page.locator('#declensionSave').isHidden());assert(await page.locator('#declensionDative').isDisabled());assert(await page.locator('[data-confirm-declension]').evaluateAll(nodes=>nodes.every(node=>node.disabled)));await page.evaluate(()=>saveDeclensionEditor());assert.equal(await page.evaluate(()=>writes.length),2);await page.evaluate(()=>$('#declensionDialog').close());
  // Officer save path uses exactly the same existing permission flag/API.
  await page.evaluate(()=>currentMe={role:'officer',permissions:{'declension.read':true,'declension.manage':true}});await supplier.click();await page.waitForFunction(()=>declensionPreviewState&&!declensionPreviewState.loading);assert(!await page.locator('#declensionSave').isHidden());await page.evaluate(()=>$('#declensionDialog').close());
  await page.evaluate(()=>failPreview=true);await supplier.click();await page.waitForFunction(()=>declensionPreviewState?.failed);assert(await page.locator('#declensionSave').isDisabled());await page.evaluate(()=>saveDeclensionEditor());assert.equal(await page.evaluate(()=>writes.length),2);await page.evaluate(()=>{$('#declensionDialog').close();failPreview=false});
  // Late response for supplier cannot replace the customer's independently opened editor.
  await page.evaluate(()=>latePreview=true);await supplier.click();await page.waitForFunction(()=>Boolean(window.resolveLate));await page.evaluate(()=>$('#declensionDialog').close());await page.locator('[data-card-declension-side="customer"]').click();await page.waitForFunction(()=>declensionPreviewState&&!declensionPreviewState.loading);await page.evaluate(()=>resolveLate());assert.equal(await page.locator('#declensionOriginal').inputValue(),'ТОВ «ЗАМОВНИК СИНТЕТИЧНИЙ»');assert.equal(await page.evaluate(()=>writes.length),2);
  await page.locator('#declensionGenitive').fill('ПЕРЕВІРЕНА ФОРМА ЗАМОВНИКА');await page.locator('#declensionSave').click();await page.waitForFunction(()=>writes.length===3);assert.equal((await page.evaluate(()=>writes[2])).payload.original,'ТОВ «ЗАМОВНИК СИНТЕТИЧНИЙ»');assert.equal(await page.evaluate(()=>stored[name].dative),'СИНТЕТИЧНОМУ ПОСТАЧАЛЬНИКУ');
  await page.evaluate(()=>openDeclensionEditor({entity_type:'legal_entity',original:customer,dative:'ЧИННА ФОРМА'},'dative',{context_type:'supplier_nazk'}));assert.equal(await page.evaluate(()=>declensionPreviewState),null);assert.equal(await page.locator('[data-declension-preview-control]').count(),0);assert.equal(await page.locator('#declensionDative').inputValue(),'ЧИННА ФОРМА');await page.evaluate(()=>$('#declensionDialog').close());
  // Saved forms keep verified provenance; empty dative cannot become verified.
  await page.evaluate(()=>{latePreview=false;resolveLate=null});
  let writeCount=await page.evaluate(()=>writes.length);
  await supplier.focus();await supplier.press('Enter');await page.waitForFunction(()=>declensionPreviewState&&!declensionPreviewState.loading);
  assert.equal(await page.locator('[data-declension-origin="dative"]').getAttribute('data-source'),'override');
  assert(await page.locator('[data-confirm-declension="dative"]').isChecked());
  assert.equal(await page.locator('[data-declension-origin="genitive"]').getAttribute('data-source'),'override');
  assert(await page.locator('[data-confirm-declension="genitive"]').isChecked());
  await page.locator('#declensionDative').fill('   ');
  assert(await page.locator('[data-confirm-declension="dative"]').isDisabled());
  assert(!await page.locator('[data-confirm-declension="dative"]').isChecked());
  assert.match(await page.locator('[data-confirm-declension="dative"]').getAttribute('aria-label'),/Давальний відмінок/);
  // Even a forced DOM checkbox cannot send a verified whitespace form.
  await page.evaluate(()=>document.querySelector('[data-confirm-declension="dative"]').checked=true);
  await page.locator('#declensionSave').click();await page.waitForFunction(n=>writes.length===n,++writeCount);
  assert.equal((await page.evaluate(()=>writes.at(-1))).payload.dative,'');
  assert(await supplier.evaluate(e=>e.classList.contains('needs-declension-review')));
  assert.match(await supplier.getAttribute('aria-label'),/потрібна перевірка/);
  assert(!await page.locator('#violationProtocolReasons').isHidden());
  assert.equal(await page.locator('#violationProtocolReasons').getAttribute('role'),'status');
  assert.equal(await page.locator('#violationProtocolReasons').getAttribute('aria-live'),'polite');
  await supplier.click();await page.waitForFunction(()=>declensionPreviewState&&!declensionPreviewState.loading);
  assert.equal(await page.locator('[data-declension-origin="dative"]').getAttribute('data-source'),'unresolved');
  assert(await page.locator('[data-confirm-declension="dative"]').isDisabled());
  await page.locator('#declensionDative').fill('ВІДНОВЛЕНА ПЕРЕВІРЕНА ФОРМА');
  const confirmation=page.locator('[data-confirm-declension="dative"]');await confirmation.focus();
  assert(await confirmation.evaluate(e=>document.activeElement===e));
  await confirmation.press('Space');assert(!await confirmation.isChecked());
  await confirmation.press('Space');assert(await confirmation.isChecked());
  await page.locator('#declensionSave').click();await page.waitForFunction(n=>writes.length===n,++writeCount);
  assert(!await supplier.evaluate(e=>e.classList.contains('needs-declension-review')));
  // Different reports/suppliers cannot inherit confirmed values or pending editor state.
  await page.evaluate(()=>{name='ПРАТ «СИНТЕТИЧНА ЮРІЯ»';reportId='synthetic-report-B';activeDeclensionRequest=item();bindViolationCardDeclensionActions(activeDeclensionRequest)});
  await supplier.click();await page.waitForFunction(()=>declensionPreviewState&&!declensionPreviewState.loading);
  assert.equal(await page.locator('#declensionOriginal').inputValue(),'ПРАТ «СИНТЕТИЧНА ЮРІЯ»');assert.equal(await page.locator('#declensionDative').inputValue(),'');
  assert.equal(await page.locator('[data-declension-origin="dative"]').getAttribute('data-source'),'unresolved');await page.evaluate(()=>$('#declensionDialog').close());
  await page.evaluate(()=>{name='КОМУНАЛЬНЕ ПІДПРИЄМСТВО «СИНТЕТИЧНЕ»';reportId='synthetic-report';activeDeclensionRequest=item();bindViolationCardDeclensionActions(activeDeclensionRequest)});
  await supplier.click();await page.waitForFunction(()=>declensionPreviewState&&!declensionPreviewState.loading);
  assert.equal(await page.locator('#declensionDative').inputValue(),'ВІДНОВЛЕНА ПЕРЕВІРЕНА ФОРМА');assert.equal(await page.locator('[data-declension-origin="dative"]').getAttribute('data-source'),'override');await page.evaluate(()=>$('#declensionDialog').close());
  // A late initial dictionary load for A must not reopen its editor over B.
  await page.evaluate(()=>{delayList=true;resolveDelayedList=null});await supplier.click();await page.waitForFunction(()=>Boolean(window.resolveDelayedList));
  await page.evaluate(()=>{delayList=false;name='ПРАТ «СИНТЕТИЧНА ЮРІЯ»';reportId='synthetic-report-B';activeDeclensionRequest=item();bindViolationCardDeclensionActions(activeDeclensionRequest)});
  await supplier.click();await page.waitForFunction(()=>declensionPreviewState&&!declensionPreviewState.loading);
  await page.evaluate(async()=>{resolveDelayedList();await new Promise(resolve=>setTimeout(resolve,0))});
  assert.equal(await page.locator('#declensionOriginal').inputValue(),'ПРАТ «СИНТЕТИЧНА ЮРІЯ»');await page.evaluate(()=>$('#declensionDialog').close());
  // Saving an already-open A editor after switching the owning report is rejected.
  await page.evaluate(()=>{name='КОМУНАЛЬНЕ ПІДПРИЄМСТВО «СИНТЕТИЧНЕ»';reportId='synthetic-report';activeDeclensionRequest=item();bindViolationCardDeclensionActions(activeDeclensionRequest)});
  await supplier.click();await page.waitForFunction(()=>declensionPreviewState&&!declensionPreviewState.loading);
  await page.evaluate(()=>{name='ПРАТ «СИНТЕТИЧНА ЮРІЯ»';reportId='synthetic-report-B';activeDeclensionRequest=item();bindViolationCardDeclensionActions(activeDeclensionRequest)});
  await page.locator('#declensionSave').click();assert.equal(await page.evaluate(()=>writes.length),writeCount);assert(!await page.locator('#declensionDialog').evaluate(e=>e.open));
  assert.deepEqual(errors,[]);results.push({theme,checks:18,status:'PASS'});await page.close();
 }
 fs.writeFileSync(path.join(root,'evidence/browser-results.json'),JSON.stringify({results,total_checks:36,live_requests:0},null,2));console.log('PASS: 36 browser scenarios across both themes, selected protocol, roles, save/reopen, automatic confirmation, errors and stale responses');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
