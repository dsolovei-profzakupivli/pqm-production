/* Chromium regression: adaptive scenario in appeal rows and read-only saved justification viewer. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const vm=require('node:vm');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),read=name=>fs.readFileSync(path.join(root,name),'utf8'),app=read('app.js'),index=read('index.html'),server=read('server.py');
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
const listApiStart=server.indexOf('def list_violation_reports('),listApiEnd=server.indexOf('\ndef ',listApiStart+4),listApi=server.slice(listApiStart,listApiEnd);
assert(listApi.includes('item["scenario_summary"]=(violation_scenario_summary(scenario_report,scenario_context)'),'list API must project the canonical adaptive scenario consumed by this browser view');
assert(listApi.includes('violation_scenario_context_snapshots')&&listApi.includes('_validated_scenario_context_snapshot(')&&
  !listApi.includes('resolve_violation_procurement_context(')&&!listApi.includes('api_get('),
  'list API must batch-read locally cached scenario facts and make no external requests');
const cardDetailStart=server.indexOf('def violation_report_detail(');
const cardDetail=server.slice(cardDetailStart,server.indexOf('\nVIOLATION_SHEETS_DECISION_LABELS=',cardDetailStart));
assert(cardDetail.includes('_save_violation_scenario_context_snapshot(')&&cardDetail.includes('factual_procurement_context'),
  'card detail must save already-resolved factual context for later list projection');
assert(server.includes('CREATE TABLE IF NOT EXISTS violation_scenario_context_snapshots')&&
  server.includes('BEGIN IMMEDIATE')&&server.includes('source_updated_at_ns'),
  'scenario context cache must be separate, additive, and monotonic under concurrent writers');
assert(!app.includes('Контрольний сценарій'),'scenario title must not be shown in appeal cards');
assert(app.includes('item.scenario_summary?'),'scenario_summary must remain available in appeal cards');
const saved=[
  {id:'P-1',report_id:'UA-D-PENDING',status:'pending',scenario_summary:'Строк укладення договору сплив, але договір не укладено.',decision_justification:'Збережене офіційне обґрунтування для очікуваного звернення.'},
  {id:'S-1',report_id:'UA-D-SATISFIED',status:'satisfied',scenario_summary:'Сценарій: Письмову відмову надано після граничної дати.',decision_justification:'Збережене обґрунтування задоволеного звернення.'},
  {id:'D-1',report_id:'UA-D-DECLINED',status:'declined',scenario_summary:'До звернення не додано остаточного рішення суду.',decision_justification:'Збережене обґрунтування відхиленого звернення.'},
  {id:'N-1',report_id:'UA-D-NONE',status:'pending',scenario_summary:'Адаптивний сценарій без збереженого обґрунтування.',decision_justification:''},
  {id:'N-2',report_id:'UA-D-WHITESPACE',status:'satisfied',scenario_summary:'Рішення залежить від сценарію, наведеного у матеріалах.',decision_justification:'   \n  '},
  {id:'N-3',report_id:'UA-D-MISSING',status:'declined',scenario_summary:'Сценарій: Підстава не підтвердилася.',decision_justification:undefined},
  {id:'N-4',report_id:'UA-D-PREFIX-ONLY',status:'pending',scenario_summary:'Сценарій:',decision_justification:''},
  {id:'N-5',report_id:'UA-D-MULTILINE',status:'pending',scenario_summary:'Сценарій: Перший рядок.\nДругий рядок із довгим змістом: '+('довгий текст '.repeat(32)),decision_justification:''},
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
  await page.setContent(`<!doctype html><html data-theme="light"><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>${read('styles.css')}\n${read('modules.css')}\n${read('theme.css')}</style></head><body><main id="requestsView"><button id="refreshScenarioList">Оновити список</button><div class="supplier-table-scroll">${requestsTable}</div></main>${dialog}<script>
    const $=selector=>document.querySelector(selector),esc=value=>String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
    let violationReports=${JSON.stringify(saved)};let cardOpens=0,writeCalls=0,cardContextFetches=0,listRefreshes=0;
    const localScenarioCache=new Map();
    function openViolationReport(index){cardOpens++;window.lastOpened=index;cardContextFetches++;localScenarioCache.set(violationReports[index].id,violationReports[index].scenario_summary)}
  </script><script>${helpers}</script><script>
    const renderRows=()=>{document.querySelector('#requestsBody').innerHTML=violationReports.map((item,index)=>'<tr class="request-row" data-request-index="'+index+'">'+Array.from({length:7},()=>'<td>—</td>').join('')+'<td>'+requestScenarioCell(item,index)+'</td><td>'+item.status+'</td><td>—</td></tr>').join('')};
    renderRows();
    document.querySelector('#refreshScenarioList').addEventListener('click',()=>{listRefreshes++;violationReports[0].scenario_summary=localScenarioCache.get(violationReports[0].id)||'';renderRows()});
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
    const expectedScenario=String(item.scenario_summary||'').trim().replace(/^Сценарій:\s*/i,'')||'—';
    assert.equal(scenario,expectedScenario,`${theme}/${item.status}: cell shows adaptive scenario without only its leading service prefix`);
    assert(!/^Сценарій:/i.test(scenario),`${theme}/${item.status}: no leading duplicate service prefix`);
    if(i===4)assert(scenario.includes('сценарію'),'the word сценарій remains when it is part of the meaning');
    if(i===6)assert.equal(scenario,'—','a prefix without scenario content renders as empty');
    if(i===7){
      assert(scenario.startsWith('Перший рядок.\nДругий рядок із довгим змістом:'),`${theme}: line breaks and body text survive prefix removal`);
      const style=await page.locator(`tr[data-request-index="${i}"] .request-scenario-summary`).evaluate(el=>({whiteSpace:getComputedStyle(el).whiteSpace,overflowWrap:getComputedStyle(el).overflowWrap,overflow:getComputedStyle(el).overflow,lineClamp:getComputedStyle(el).webkitLineClamp}));
      assert.equal(style.whiteSpace,'normal',`${theme}: text wraps in the cell`);
      assert.equal(style.overflowWrap,'anywhere',`${theme}: long text can wrap without widening the table`);
      assert.equal(style.overflow,'hidden',`${theme}: long summary is visually truncated`);
      assert.equal(style.lineClamp,'3',`${theme}: long summary remains limited to three lines`);
    }
    if(item.decision_justification)assert.notEqual(scenario,item.decision_justification,`${theme}/${item.status}: justification is not duplicated into scenario cell`);
    const savedJustification=String(item.decision_justification||'').trim(),eye=page.locator(`tr[data-request-index="${i}"] [data-view-justification]`);
    if(savedJustification){
      assert.equal(await eye.count(),1,`${theme}/${item.status}: saved nonblank justification shows eye`);
      await eye.click();
      assert.equal(await page.locator('#requestJustificationDialog').evaluate(el=>el.open),true,`${theme}/${item.status}: one click opens viewer`);
      assert.equal(await page.locator('#requestJustificationBody').textContent(),savedJustification,'viewer shows the saved justification');
      assert.equal(await page.locator('#requestJustificationBody textarea, #requestJustificationBody input, #requestJustificationBody button').count(),0,'viewer is read-only');
      await page.keyboard.press('Escape');
    }else{
      assert.equal(await eye.count(),0,`${theme}/${item.status}: missing, empty, or whitespace-only justification has no eye`);
      assert.equal(await page.locator('#requestJustificationDialog').evaluate(el=>el.open),false,`${theme}/${item.status}: no viewer opens without saved text`);
    }
   }
   await page.locator('tr[data-request-index="0"] td').nth(0).click();
   assert.equal(await page.evaluate(()=>window.lastOpened),0,`${theme}: one ordinary row click opens the appeal`);
  }
  assert.equal(await page.evaluate(()=>cardOpens),2,'only ordinary row clicks open cards; eye clicks do not bubble into card opening');
  assert.equal(await page.evaluate(()=>writeCalls),0,'viewer does not initiate writes or regeneration');
  await page.locator('#refreshScenarioList').click();
  assert.equal(await page.evaluate(()=>cardContextFetches),2,'one existing card context resolution per ordinary click');
  assert.equal(await page.evaluate(()=>listRefreshes),1,'list refresh reads saved local scenario context');
  assert.equal(await page.locator('tr[data-request-index="0"] .request-scenario-summary').textContent(),
    String(saved[0].scenario_summary).replace(/^Сценарій:\s*/i,''),'scenario resolved by the card appears after list refresh');
  console.log('PASS: adaptive scenario rows without duplicate leading label, scenario wording and line breaks preserved, prefix-only/empty values, long-text wrapping and three-line clamp, eye only for nonblank saved justification including missing/empty/whitespace cases, one-click read-only viewer, all statuses, both themes, saved column key, narrow horizontal scroll, one-click card opening, card context then refreshed-list scenario reuse');
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exit(1)});
