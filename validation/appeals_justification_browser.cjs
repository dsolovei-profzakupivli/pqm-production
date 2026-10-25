/* Chromium regression: stored appeal justification summary and read-only eye viewer. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const vm=require('node:vm');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),read=name=>fs.readFileSync(path.join(root,name),'utf8'),app=read('app.js'),index=read('index.html');
const fragment=(start,end)=>{const a=app.indexOf(start),b=app.indexOf(end,a);assert(a>=0&&b>a,`missing source ${start}`);return app.slice(a,b).trim()};
const helpers=[
  fragment('function savedJustificationSummary(', '\nfunction requestJustificationCell('),
  fragment('function requestJustificationCell(', '\nfunction showSavedRequestJustification('),
  fragment('function showSavedRequestJustification(', '\nfunction requestAuthorityShortName('),
  fragment("$('#requestsBody').onclick=", '\n')
].join('\n');
const dialog=index.match(/<dialog id="requestJustificationDialog"[\s\S]*?<\/dialog>/)?.[0];assert(dialog,'read-only justification dialog markup missing');
assert(index.includes('data-column-key="decision_justification">Обґрунтування</th>'),'appeals table justification column missing');
const requestsTable=index.match(/<table class="supplier-table requests-table">[\s\S]*?<\/table>/)?.[0];assert(requestsTable,'appeals table markup missing');
assert(!app.includes('Контрольний сценарій'),'scenario title must not be shown in appeal cards');
const saved=[
  {id:'P-1',report_id:'UA-D-PENDING',status:'pending',decision_justification:'За результатами розгляду звернення Замовника та аналізу матеріалів закупівлі Адміністратором встановлено наступне.\n\nСтаном на 12.10.2026 строк укладення договору сплив, але договір не укладено.'},
  {id:'S-1',report_id:'UA-D-SATISFIED',status:'satisfied',decision_justification:'У цій закупівлі письмову відмову надано 18.10.2026 після граничної дати 15.10.2026.'},
  {id:'D-1',report_id:'UA-D-DECLINED',status:'declined',decision_justification:'До звернення не додано рішення суду, що набрало законної сили.'},
  {id:'N-1',report_id:'UA-D-NONE',status:'pending',decision_justification:''}
];
const widths=read('table_widths_ui.js'),visibilitySource=widths.match(/function effectiveVisibility\(table,widths\)\{[^}]*\}/)?.[0],orderSource=widths.match(/function effectiveOrder\(table,widths\)\{[^}]*\}/)?.[0];
assert(visibilitySource&&orderSource,'existing table preference helpers must remain available');
const prefContext={keysFor:()=>['appeal-id','decision_justification'],simpleOrderRows:()=>true};
vm.createContext(prefContext);vm.runInContext(visibilitySource+'\n'+orderSource,prefContext);
const priorSettings={__visible__:['appeal-id'],__columns__:['appeal-id'],__order__:['appeal-id']};
assert([...vm.runInContext('effectiveVisibility({},'+JSON.stringify(priorSettings)+')',prefContext)].includes('decision_justification'),'new justification column is visible when older settings omit it');
assert.deepEqual(Array.from(vm.runInContext('effectiveOrder({},'+JSON.stringify(priorSettings)+')',prefContext)),['appeal-id','decision_justification'],'older column order is retained and new column appended');
;(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.PQM_TEST_BROWSER?{executablePath:process.env.PQM_TEST_BROWSER}:{})});
 try{
  const page=await browser.newPage();
  await page.setContent(`<!doctype html><html data-theme="light"><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>${read('styles.css')}\n${read('theme.css')}</style></head><body>${requestsTable}${dialog}<script>
    const $=selector=>document.querySelector(selector),esc=value=>String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
    let violationReports=${JSON.stringify(saved)};let cardOpens=0,writeCalls=0;
  </script><script>${helpers}</script><script>
    document.querySelector('#requestsBody').innerHTML=violationReports.map((item,index)=>'<tr class="request-row" data-request-index="'+index+'">'+Array.from({length:7},()=>'<td>—</td>').join('')+'<td>'+requestJustificationCell(item,index)+'</td><td>'+item.status+'</td><td>—</td></tr>').join('');
    document.querySelector('#requestsBody').onclick=e=>{const view=e.target.closest('[data-view-justification]');if(view){e.preventDefault();e.stopPropagation();showSavedRequestJustification(view.dataset.viewJustification);return}const row=e.target.closest('.request-row');if(row&&!e.target.closest('a,button'))cardOpens++};
    document.querySelector('#requestJustificationBody').addEventListener('input',()=>writeCalls++);
  </script></body></html>`);
  for(const theme of ['light','dark']){
   await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);
   assert.equal(await page.locator('.requests-table thead th').count(),10,`${theme}: all existing and new table headers remain present`);
   for(let i=0;i<saved.length;i++){
    const item=saved[i],summary=await page.locator(`tr[data-request-index="${i}"] .request-justification-summary`).textContent();
    assert.equal(await page.locator(`tr[data-request-index="${i}"] td`).count(),10,`${theme}/${item.status}: row aligns to all table headers`);
    if(item.decision_justification){assert(!summary.startsWith('За результатами розгляду звернення Замовника та аналізу матеріалів закупівлі'),`${theme}/${item.status}: generic intro must not be shown`);assert(summary.trim().length>0)}
    else assert.equal(summary,'Обґрунтування ще не сформовано');
    await page.locator(`tr[data-request-index="${i}"] [data-view-justification]`).click();
    assert.equal(await page.locator('#requestJustificationDialog').evaluate(el=>el.open),true,`${theme}/${item.status}: one click opens viewer`);
    const expected=item.decision_justification||'Обґрунтування для цього звернення ще не сформовано.';
    assert.equal(await page.locator('#requestJustificationBody').textContent(),expected);
    assert.equal(await page.locator('#requestJustificationBody textarea, #requestJustificationBody input, #requestJustificationBody button').count(),0,'viewer is read-only');
    await page.locator('#requestJustificationDialog button[value="cancel"]').last().click();
   }
  }
  assert.equal(await page.evaluate(()=>({cardOpens,writeCalls})).then(x=>x.cardOpens),0,'eye clicks must not open or mutate the appeal card');
  assert.equal(await page.evaluate(()=>writeCalls),0,'viewer must not initiate a write');
  console.log('PASS: saved justification summaries, one-click read-only viewer, missing text, pending/satisfied/declined, both themes');
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exit(1)});
