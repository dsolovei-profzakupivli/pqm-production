/* Chromium regression: adaptive scenario in appeal rows and read-only saved justification viewer. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const vm=require('node:vm');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),read=name=>fs.readFileSync(path.join(root,name),'utf8'),app=read('app.js'),index=read('index.html');
const fragment=(start,end)=>{const a=app.indexOf(start),b=app.indexOf(end,a);assert(a>=0&&b>a,`missing source ${start}`);return app.slice(a,b).trim()};
const helpers=[
  fragment('function requestScenarioCell(', '\nfunction showSavedRequestJustification('),
  fragment('function showSavedRequestJustification(', '\nfunction requestAuthorityShortName('),
  fragment("$('#requestsBody').onclick=", '\n')
].join('\n');
const dialog=index.match(/<dialog id="requestJustificationDialog"[\s\S]*?<\/dialog>/)?.[0];assert(dialog,'read-only justification dialog markup missing');
assert(index.includes('data-column-key="decision_justification">Сценарій</th>'),'scenario header and stable preference key must be preserved');
const requestsTable=index.match(/<table class="supplier-table requests-table">[\s\S]*?<\/table>/)?.[0];assert(requestsTable,'appeals table markup missing');
const reportLoader=fragment('async function loadViolationReports(', '\nconst internalDecisionLabels=');
assert(reportLoader.includes('requestScenarioCell(item,index)')&&!reportLoader.includes('requestJustificationCell(item,index)'),'appeals table loader must render scenario_summary in the legacy preference column');
assert(!app.includes('Контрольний сценарій'),'scenario title must not be shown in appeal cards');
assert(app.includes('item.scenario_summary?'),'scenario_summary must remain available in appeal cards');
const saved=[
  {id:'P-1',report_id:'UA-D-PENDING',status:'pending',scenario_summary:'Строк укладення договору сплив, але договір не укладено.',decision_justification:'Збережене офіційне обґрунтування для очікуваного звернення.'},
  {id:'S-1',report_id:'UA-D-SATISFIED',status:'satisfied',scenario_summary:'Письмову відмову надано після граничної дати.',decision_justification:'Збережене обґрунтування задоволеного звернення.'},
  {id:'D-1',report_id:'UA-D-DECLINED',status:'declined',scenario_summary:'До звернення не додано остаточного рішення суду.',decision_justification:'Збережене обґрунтування відхиленого звернення.'},
  {id:'N-1',report_id:'UA-D-NONE',status:'pending',scenario_summary:'Адаптивний сценарій без збереженого обґрунтування.',decision_justification:''},
  {id:'S-2',report_id:'UA-D-NO-SCENARIO',status:'satisfied',scenario_summary:'',decision_justification:'Збережений текст залишається окремо доступним.'}
];
const widths=read('table_widths_ui.js'),visibilitySource=widths.match(/function effectiveVisibility\(table,widths\)\{[^}]*\}/)?.[0],orderSource=widths.match(/function effectiveOrder\(table,widths\)\{[^}]*\}/)?.[0];
assert(visibilitySource&&orderSource,'existing table preference helpers must remain available');
const prefContext={keysFor:()=>['appeal-id','decision_justification'],simpleOrderRows:()=>true};
vm.createContext(prefContext);vm.runInContext(visibilitySource+'\n'+orderSource,prefContext);
const priorSettings={__visible__:['appeal-id'],__columns__:['appeal-id'],__order__:['appeal-id']};
assert([...vm.runInContext('effectiveVisibility({},'+JSON.stringify(priorSettings)+')',prefContext)].includes('decision_justification'),'scenario column remains visible when older settings omit it');
assert.deepEqual(Array.from(vm.runInContext('effectiveOrder({},'+JSON.stringify(priorSettings)+')',prefContext)),['appeal-id','decision_justification'],'older column order remains and scenario column appends under the stable key');
;(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.PQM_TEST_BROWSER?{executablePath:process.env.PQM_TEST_BROWSER}:{})});
 try{
  const page=await browser.newPage({viewport:{width:390,height:844}});
  await page.setContent(`<!doctype html><html data-theme="light"><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>${read('styles.css')}\n${read('modules.css')}\n${read('theme.css')}</style></head><body><main id="requestsView"><div class="supplier-table-scroll">${requestsTable}</div></main>${dialog}<script>
    const $=selector=>document.querySelector(selector),esc=value=>String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
    let violationReports=${JSON.stringify(saved)};let cardOpens=0,writeCalls=0;
    function openViolationReport(index){cardOpens++;window.lastOpened=index}
  </script><script>${helpers}</script><script>
    document.querySelector('#requestsBody').innerHTML=violationReports.map((item,index)=>'<tr class="request-row" data-request-index="'+index+'">'+Array.from({length:7},()=>'<td>—</td>').join('')+'<td>'+requestScenarioCell(item,index)+'</td><td>'+item.status+'</td><td>—</td></tr>').join('');
    document.querySelector('#requestJustificationBody').addEventListener('input',()=>writeCalls++);
  </script></body></html>`);
  assert(await page.locator('.supplier-table-scroll').evaluate(el=>el.scrollWidth>el.clientWidth),'table remains horizontally scrollable on a narrow screen');
  for(const theme of ['light','dark']){
   await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);
   assert.equal(await page.locator('.requests-table thead th').count(),10,`${theme}: all existing headers remain`);
   assert.equal((await page.locator('.requests-table thead th').nth(7).textContent()).trim(),'Сценарій',`${theme}: header matches cell contents`);
   for(let i=0;i<saved.length;i++){
    const item=saved[i],scenario=await page.locator(`tr[data-request-index="${i}"] .request-scenario-summary`).textContent();
    assert.equal(await page.locator(`tr[data-request-index="${i}"] td`).count(),10,`${theme}/${item.status}: row aligns to all table headers`);
    assert.equal(scenario,item.scenario_summary||'—',`${theme}/${item.status}: cell shows adaptive scenario, not justification`);
    if(item.decision_justification)assert.notEqual(scenario,item.decision_justification,`${theme}/${item.status}: justification is not duplicated into scenario cell`);
    await page.locator(`tr[data-request-index="${i}"] [data-view-justification]`).click();
    assert.equal(await page.locator('#requestJustificationDialog').evaluate(el=>el.open),true,`${theme}/${item.status}: one click opens viewer`);
    const expected=item.decision_justification||'Обґрунтування для цього звернення ще не сформовано.';
    assert.equal(await page.locator('#requestJustificationBody').textContent(),expected);
    assert.equal(await page.locator('#requestJustificationBody textarea, #requestJustificationBody input, #requestJustificationBody button').count(),0,'viewer is read-only');
    await page.keyboard.press('Escape');
   }
   await page.locator('tr[data-request-index="0"] td').nth(0).click();
   assert.equal(await page.evaluate(()=>window.lastOpened),0,`${theme}: one ordinary row click opens the appeal`);
  }
  assert.equal(await page.evaluate(()=>cardOpens),2,'only ordinary row clicks open cards; eye clicks do not bubble into card opening');
  assert.equal(await page.evaluate(()=>writeCalls),0,'viewer does not initiate writes or regeneration');
  console.log('PASS: adaptive scenario rows, separate one-click read-only justification viewer, missing text, all statuses, both themes, saved column key, narrow horizontal scroll, one-click card opening');
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exit(1)});
