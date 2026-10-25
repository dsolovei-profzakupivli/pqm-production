/* Browser regression for the permanent declension actions in appeal cards. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),read=name=>fs.readFileSync(path.join(root,name),'utf8'),app=read('app.js'),index=read('index.html');
const line=(start,end)=>{const from=app.indexOf(start),to=app.indexOf(end,from);assert(from>=0&&to>from,`missing source fragment ${start}`);return app.slice(from,to).trim()};
const editor=line('function openDeclensionEditor(','\nlet declensionEditorReadOnly=');
const lookup=line('function declensionLookup(','\nfunction remainingDeclensionItems');
const actions=line('function canReadDeclensions(){','\nfunction violationDeclensionActions');
const button=line('function violationCardDeclensionButton(','\nfunction violationDeclensionActions');
const bind=line('function bindViolationCardDeclensionActions(','\nfunction violationDeclensionActions');
const render=line('const violationDetailDeclensionBase=violationDetailHtml;','\n$(\'#requestDetailsBody\').addEventListener');
const draft=line('function collectViolationReview(){','async function saveViolationReview(');
const restoreDraft=line('function restoreViolationReviewDraft(','\nfunction ');
const save=line('async function saveDeclensionEditor(){','\nasync function deleteDeclension');
const dialog=index.match(/<dialog id="declensionDialog"[\s\S]*?<\/dialog>/)?.[0];assert(dialog,'declension editor markup missing');
const prelude=`
let currentMe={role:'admin',permissions:{'declension.read':true,'declension.manage':true}};
let declensionItems=[],editingDeclensionId=null,declensionReturnContext=null;
let __overrides=[],__item=null;
const API='/api',declensionTypeLabels={legal_entity:'Юридична особа',fop:'ФОП',person:'Фізична особа / ПІБ',other:'Інше'};
const $=selector=>document.querySelector(selector),$$=selector=>Array.from(document.querySelectorAll(selector));
const toast=()=>{};
async function loadDeclensionOverrides(){declensionItems=__overrides.map(row=>({...row}));return true}
async function request(url,options){const row={...JSON.parse(options.body),id:editingDeclensionId||'override-'+(__overrides.length+1)};if(editingDeclensionId)__overrides=__overrides.map(old=>old.id===editingDeclensionId?row:old);else __overrides.push(row);return row}
function violationDetailHtml(item){return '<section class="violation-top-row"><div><h3>Замовник</h3><p>Замовник</p></div><div><h3>Постачальник <span class="violation-thresholds">0/3 · 0/5</span></h3><p>Постачальник</p></div><textarea data-review="review_notes">unsaved draft</textarea></section>'}
async function openViolationReportById(){renderCard(__item);return __item}
`;
const code=[prelude,lookup,editor,'let declensionEditorReadOnly=false;',actions,button,bind,render,restoreDraft,draft,save].join('\n');
;(async()=>{
const browser=await chromium.launch({headless:true,...(process.env.PQM_TEST_BROWSER?{executablePath:process.env.PQM_TEST_BROWSER}:{})});
try{
  const page=await browser.newPage();
  await page.setContent(`<!doctype html><html data-theme="light"><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>${read('styles.css')}\n${read('theme.css')}</style></head><body><main id="requestDetailsBody"></main>${dialog}<script>${code}</script><script>
    function renderCard(item){__item=item;document.querySelector('#requestDetailsBody').innerHTML=violationDetailHtml(item);bindViolationCardDeclensionActions(item)}
    document.querySelector('#declensionSave').onclick=saveDeclensionEditor;
  </script></body></html>`);
  const makeItem=()=>({id:'R-1',author_name:'ТОВАРИСТВО «ПРИКЛАД»',author_code:'12345678',defendant_name:'ФОП Петренко Олена Іванівна',defendant_code:'1234567890',review:{customer_verified_full_name:'ТОВАРИСТВО «ПРИКЛАД»'},protocol_supplier_names:{full_name:{value:'ФОП Петренко Олена Іванівна'}},protocol_readiness:{declensions:[]},protocol_readiness_individual:{declensions:[]}});
  async function setRole(role){await page.evaluate(role=>{currentMe={role,permissions:{'declension.read':true,'declension.manage':role!=='viewer'}}},role)}
  async function openByClick(side){await page.locator(`[data-card-declension-side="${side}"]`).click();await page.waitForFunction(()=>document.querySelector('#declensionDialog').open);}
  for(const theme of ['light','dark']){
    await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);
    for(const role of ['admin','officer','viewer']){
      await setRole(role);await page.evaluate(item=>renderCard(item),makeItem());
      assert.equal(await page.locator('[data-card-declension-side]').count(),2,`${theme}/${role}: permanent buttons must not depend on unresolved warnings`);
      for(const side of ['customer','supplier']){
        if(role!=='viewer'&&side==='customer'){
          await page.locator('[data-review="review_notes"]').fill('збережений чернетковий текст');
          assert.equal(await page.locator('[data-review="review_notes"]').inputValue(),'збережений чернетковий текст');
        }
        await openByClick(side);
        const expected=side==='customer'?'legal_entity':'fop';
        assert.equal(await page.locator('#declensionType').inputValue(),expected,`${theme}/${role}/${side}: entity type`);
        assert.equal(await page.locator('#declensionOriginal').inputValue(),side==='customer'?'ТОВАРИСТВО «ПРИКЛАД»':'ФОП Петренко Олена Іванівна');
        assert.equal(await page.locator('#declensionDialog [data-declension-case="genitive"]').isVisible(),true);
        assert.equal(await page.locator('#declensionDialog [data-declension-case="dative"]').isVisible(),true);
        assert.equal(await page.locator('#declensionDialog [data-declension-case="accusative"]').isVisible(),true);
        assert.equal(await page.locator('#declensionSave').isVisible(),role!=='viewer',`${theme}/${role}: edit permission`);
        if(role==='viewer'){
          assert.equal(await page.locator('#declensionGenitive').getAttribute('readonly'), '');
          await page.locator('#declensionDialog button.dialog-close').click();
          continue;
        }
        const value=`${side==='customer'?'Замовника':'Петренко'}-${theme}-${role}`;
        await page.locator('#declensionGenitive').fill(value);
        await page.locator('#declensionSave').click();
        await page.waitForFunction(()=>!document.querySelector('#declensionDialog').open);
        if(side==='customer')await page.waitForTimeout(120);
        assert.equal(await page.evaluate(()=>__overrides.length),side==='customer'?1:2,`${theme}/${role}/${side}: save through existing API path`);
        if(side==='customer')assert.equal(await page.locator('[data-review="review_notes"]').inputValue(),'збережений чернетковий текст',`${theme}/${role}: review draft survives editor save; state=${JSON.stringify(await page.evaluate(()=>({context:declensionReturnContext,draft:collectViolationReview(),items:__overrides.length})))}`);
        await openByClick(side);
        assert.equal(await page.locator('#declensionGenitive').inputValue(),value,`${theme}/${role}/${side}: saved form reopens`);
        await page.locator('#declensionDialog button.dialog-close').click();
      }
      await page.evaluate(()=>{__overrides=[];declensionItems=[]});
    }
    await setRole('viewer');
    await page.evaluate(item=>{__overrides=[{id:'saved-view-only',entity_type:'fop',original:'ФОП Петренко Олена Іванівна',genitive:'ЗБЕРЕЖЕНА ВІДМІНЕНА ФОРМА',dative:'',accusative:'',comment:''}];renderCard(item)},makeItem());
    await openByClick('supplier');
    assert.equal(await page.locator('#declensionGenitive').inputValue(),'ЗБЕРЕЖЕНА ВІДМІНЕНА ФОРМА',`${theme}: viewer sees saved correction`);
    assert.equal(await page.locator('#declensionSave').isVisible(),false,`${theme}: viewer cannot edit saved correction`);
    await page.locator('#declensionDialog button.dialog-close').click();
    await page.evaluate(()=>{__overrides=[];declensionItems=[]});
    // An unresolved warning can coexist with, but does not control, the permanent actions.
    await setRole('officer');const warningItem=makeItem();warningItem.protocol_readiness.declensions=[{subject_label:'Замовник',original:warningItem.author_name,status:'unresolved',entity_type:'legal_entity',grammatical_case:'genitive'}];
    await page.evaluate(item=>renderCard(item),warningItem);
    assert.equal(await page.locator('[data-card-declension-side]').count(),2,`${theme}: unresolved warning remains independent`);
    const buttonStyle=await page.locator('[data-card-declension-side="customer"]').evaluate(node=>({display:getComputedStyle(node).display,width:node.getBoundingClientRect().width}));
    assert.notEqual(buttonStyle.display,'none');assert.ok(buttonStyle.width>0);
  }
  console.log('PASS: Chromium one-click customer/supplier editor, legal entity/FOP, admin/officer/viewer, save/reopen, light/dark, warning-independent rendering');
}finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
