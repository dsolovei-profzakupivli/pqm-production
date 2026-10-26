/* Chromium regression: adaptive scenario in appeal rows and read-only saved justification viewer. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const vm=require('node:vm');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),read=name=>fs.readFileSync(path.join(root,name),'utf8'),app=read('app.js'),index=read('index.html'),server=read('server.py');
const scenarioStyle=read('styles.css').match(/\.request-scenario-summary\{([^}]*)\}/)?.[1];
assert(scenarioStyle,'scenario summary style must remain scoped to the appeals scenario cell');
for(const forbidden of ['-webkit-line-clamp','max-height','text-overflow'])assert(!scenarioStyle.includes(forbidden),`scenario summary must not use ${forbidden}`);
assert(scenarioStyle.includes('overflow-wrap:anywhere')&&!scenarioStyle.includes('overflow:hidden'),'scenario style must wrap long words without clipping');
const thresholdsStyle=read('styles.css').match(/\.violation-thresholds\{([^}]*)\}/)?.[1];
assert(thresholdsStyle&&thresholdsStyle.includes('margin-left:14px')&&thresholdsStyle.includes('display:inline-block')&&thresholdsStyle.includes('float:none'),'supplier counter receives the requested inline gap without changing its font or color');
assert(read('styles.css').includes('.violation-platform-heading')&&read('styles.css').includes('.violation-zakupivli-link img'),'platform icon styling remains scoped to the appeal card heading');
const fragment=(start,end)=>{const a=app.indexOf(start),b=app.indexOf(end,a);assert(a>=0&&b>a,`missing source ${start}`);return app.slice(a,b).trim()};
const helpers=[
  fragment('function requestScenarioCell(', '\nfunction showSavedRequestJustification('),
  fragment('function showSavedRequestJustification(', '\nfunction requestAuthorityShortName('),
  fragment("$('#requestsBody').onclick=", '\n')
].join('\n');
const statusLinkHelpers=[
  fragment('const requestStatusLabels=', '\nconst requestReasonLabels='),
  fragment('function requestLabel(', '\nfunction requestDocumentLinks('),
  fragment('function requestViolationUrl(', '\nfunction zakupivliComplaintLink('),
  fragment('function zakupivliComplaintLink(', '\nfunction requestBlockingBadge('),
  fragment('function violationObjectLinks(', '\nfunction violationHasCompleteRejection(')
].join('\n');
const marketplaceHelper=fragment('function zakupivliComplaintLink(', '\nfunction requestBlockingBadge(');
const activeCardRendererStart=app.indexOf('violationDetailHtml=function(item)',app.indexOf('function violationObjectLinks('));
const activeCardRenderer=app.slice(activeCardRendererStart,app.indexOf('\nconst violationDetailHtmlBase',activeCardRendererStart));
assert(activeCardRenderer.includes('class="violation-platform-heading"')&&activeCardRenderer.includes('zakupivliComplaintLink(item)'),'active appeal card renderer puts the supplier-filtered marketplace link beside its heading');
assert(marketplaceHelper.includes('item?.defendant_code')&&!marketplaceHelper.includes('item?.id')&&!marketplaceHelper.includes('item?.author_code'),'marketplace target uses supplier code and never guesses from internal ID or customer code');
assert(marketplaceHelper.includes('/complaints/list')&&marketplaceHelper.includes('?defendant_srn=')&&marketplaceHelper.includes("complaints/list',href"),'valid supplier codes filter the complaints list and invalid codes use the unfiltered list');
assert(app.includes('requestLabel(item.status,requestStatusLabels)'),'appeals table and card use the shared Ukrainian status label helper');
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
  {id:'D-1',report_id:'UA-D-DECLINED',status:'declinedNoViolation',scenario_summary:'До звернення не додано остаточного рішення суду.',decision_justification:'Збережене обґрунтування відхиленого звернення.'},
  {id:'N-1',report_id:'UA-D-NONE',status:'pending',scenario_summary:'Адаптивний сценарій без збереженого обґрунтування.',decision_justification:''},
  {id:'N-2',report_id:'UA-D-WHITESPACE',status:'satisfied',scenario_summary:'Рішення залежить від сценарію, наведеного у матеріалах.',decision_justification:'   \n  '},
  {id:'N-3',report_id:'UA-D-MISSING',status:'declined',scenario_summary:'Сценарій: Підстава не підтвердилася.',decision_justification:undefined},
  {id:'N-4',report_id:'UA-D-PREFIX-ONLY',status:'pending',scenario_summary:'Сценарій:',decision_justification:''},
  {id:'N-5',report_id:'UA-D-MULTILINE',status:'pending',scenario_summary:'Сценарій: Перший рядок.\nДругий рядок із довгим змістом: '+('довгий текст '.repeat(32)),decision_justification:''},
  {id:'N-6',report_id:'UA-D-LONG-WORD',status:'pending',scenario_summary:'Неподільне довге слово: '+('надзвичайно'.repeat(45)),decision_justification:''},
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
 const context=await browser.newContext();
 await context.route('https://my.zakupivli.pro/**',route=>route.fulfill({status:200,contentType:'text/html',body:'<title>Fixture complaint</title>'}));
 try{
  const page=await context.newPage({viewport:{width:390,height:844}});
  await page.setContent(`<!doctype html><html data-theme="light"><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>${read('styles.css')}\n${read('modules.css')}\n${read('theme.css')}</style></head><body><main id="requestsView"><button id="refreshScenarioList">Оновити список</button><div class="supplier-table-scroll">${requestsTable}</div><section id="cardLayoutFixture" class="request-details-dialog-wide"><div class="violation-top-row"><div><div class="violation-party-heading"><h3>Постачальник <span class="violation-thresholds">0/3 · 0/5</span></h3><button class="violation-card-declension">Відмінювання</button></div></div><div></div><div><h3 class="violation-platform-heading">Закупівля · Договір · Звернення</h3></div></div></section></main>${dialog}<script>
    const $=selector=>document.querySelector(selector),esc=value=>String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
    let violationReports=${JSON.stringify(saved)};let cardOpens=0,writeCalls=0,cardContextFetches=0,listRefreshes=0;
    const localScenarioCache=new Map();
    function openViolationReport(index){cardOpens++;window.lastOpened=index;cardContextFetches++;localScenarioCache.set(violationReports[index].id,violationReports[index].scenario_summary)}
  </script><script>${helpers}</script><script>${statusLinkHelpers}</script><script>
    const renderRows=()=>{document.querySelector('#requestsBody').innerHTML=violationReports.map((item,index)=>'<tr class="request-row" data-request-index="'+index+'">'+Array.from({length:7},()=>'<td>—</td>').join('')+'<td>'+requestScenarioCell(item,index)+'</td><td><span class="request-status status-'+esc(requestStatusClass(item.status))+'">'+requestLabel(item.status,requestStatusLabels)+'</span></td><td>—</td></tr>').join('')};
    renderRows();
    document.querySelector('#refreshScenarioList').addEventListener('click',()=>{listRefreshes++;violationReports[0].scenario_summary=localScenarioCache.get(violationReports[0].id)||'';renderRows()});
    document.querySelector('#requestJustificationBody').addEventListener('input',()=>writeCalls++);
  </script></body></html>`);
  assert(await page.locator('.supplier-table-scroll').evaluate(el=>el.scrollWidth>el.clientWidth),'table remains horizontally scrollable on a narrow screen');
  assert.equal(await page.locator('.requests-table thead th').first().evaluate(el=>getComputedStyle(el).position),'sticky','scenario layout preserves sticky table headers');
  for(const theme of ['light','dark']){
   await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);
   for(const width of [390,768,1024,1440,1920]){
    await page.setViewportSize({width,height:844});
    const counterLayout=await page.locator('#cardLayoutFixture .violation-party-heading').evaluate(el=>{const heading=el.querySelector('h3'),counter=el.querySelector('.violation-thresholds'),button=el.querySelector('.violation-card-declension'),badge=counter.getBoundingClientRect(),head=heading.getBoundingClientRect(),buttonRect=button.getBoundingClientRect(),range=document.createRange();range.selectNodeContents(heading.firstChild);const label=range.getBoundingClientRect();return{badge,head,buttonRect,label,margin:getComputedStyle(counter).marginLeft,fontSize:parseFloat(getComputedStyle(counter).fontSize),headingFontSize:parseFloat(getComputedStyle(heading).fontSize),color:getComputedStyle(counter).color,buttonText:button.textContent.trim()}});
    assert.equal(counterLayout.margin,'14px',`${theme}/${width}px: counter gap is 14px`);
    assert(Math.abs(counterLayout.fontSize-counterLayout.headingFontSize*.9)<.1,`${theme}/${width}px: counter font size remains at 0.9em`);
    assert.equal(counterLayout.color,'rgb(8, 104, 216)',`${theme}/${width}px: counter color is unchanged`);
    assert(counterLayout.badge.top>=counterLayout.head.top-1&&counterLayout.badge.bottom<=counterLayout.head.bottom+1,`${theme}/${width}px: heading and counter remain on one level`);
    assert(Math.abs(counterLayout.badge.top-counterLayout.label.top)<=4,`${theme}/${width}px: counter stays on the heading text line`);
    assert(counterLayout.badge.left-counterLayout.label.right>=12&&counterLayout.badge.left-counterLayout.label.right<=22,`${theme}/${width}px: visible gap is about 12–16px beyond normal text spacing`);
    assert(!(counterLayout.badge.right>counterLayout.buttonRect.left&&counterLayout.badge.left<counterLayout.buttonRect.right&&counterLayout.badge.top<counterLayout.buttonRect.bottom&&counterLayout.badge.bottom>counterLayout.buttonRect.top),`${theme}/${width}px: counter does not overlap the declension button`);
    assert.equal(counterLayout.buttonText,'Відмінювання',`${theme}/${width}px: declension action remains in place`);
   }
   await page.setViewportSize({width:390,height:844});
   const marketplace=await page.evaluate(()=>({legal:zakupivliComplaintLink({id:'not-a-platform-id',author_code:'11111111',defendant_code:'43012009'}),fop:zakupivliComplaintLink({id:'6ad0c3cc04a8f063b8c3d028',author_code:'11111111',defendant_code:'1234567890'}),missing:zakupivliComplaintLink({id:'6ad0c3cc04a8f063b8c3d028'}),malformed:zakupivliComplaintLink({id:'6ad0c3cc04a8f063b8c3d028',defendant_code:'43-012009'}),status:requestLabel('declinedNoViolation',requestStatusLabels),statusClass:requestStatusClass('declinedNoViolation'),unknown:requestLabel('futureUnknownStatus',requestStatusLabels),objectHtml:violationObjectLinks({id:'6ad0c3cc04a8f063b8c3d028',status:'declinedNoViolation',procurement_context:{contract_pretty_id:'UA-C-TEST',contract_status:'declinedNoViolation'}})}));
   assert(marketplace.legal.includes('https://my.zakupivli.pro/cabinet/ecatalog/gov/complaints/list?defendant_srn=43012009'),'legal-entity link filters by the supplier EDRPOU');
   assert(marketplace.fop.includes('https://my.zakupivli.pro/cabinet/ecatalog/gov/complaints/list?defendant_srn=1234567890'),'FOP link filters by the supplier RNOKPP');
   assert.equal(marketplace.missing,'<a class="violation-zakupivli-link" href="https://my.zakupivli.pro/cabinet/ecatalog/gov/complaints/list" target="_blank" rel="noopener noreferrer" aria-label="Звернення щодо постачальника на Zakupivli.Pro" title="Звернення щодо постачальника на Zakupivli.Pro"><img src="/assets/zakupivli-pro-mark.svg" alt="Zakupivli.Pro"></a>','missing supplier code safely opens the general complaints list');
   assert(marketplace.malformed.includes('href="https://my.zakupivli.pro/cabinet/ecatalog/gov/complaints/list"'),'malformed supplier code falls back to the general list');
   for(const link of [marketplace.legal,marketplace.fop,marketplace.missing,marketplace.malformed])assert(!link.includes('s=pending')&&!link.includes('status='),'marketplace URL never adds a status filter');
   assert(marketplace.legal.includes('Звернення щодо постачальника на Zakupivli.Pro'),'icon tooltip identifies supplier-filtered marketplace results');
   assert(marketplace.legal.includes('target="_blank"')&&marketplace.legal.includes('rel="noopener noreferrer"'),'platform link opens separately without exposing opener context');
   assert(marketplace.legal.includes('/assets/zakupivli-pro-mark.svg'),'existing Zakupivli.Pro mark is reused');
   await page.locator('#cardLayoutFixture .violation-platform-heading').evaluate((el,html)=>el.insertAdjacentHTML('beforeend',html),marketplace.legal);
   assert.equal(marketplace.status,'Відхилено',`${theme}: declinedNoViolation gets the agreed Ukrainian label`);
   assert.equal(marketplace.statusClass,'declined',`${theme}: technical declined status keeps the existing declined color class`);
   assert.equal(marketplace.unknown,'futureUnknownStatus',`${theme}: unknown status remains visible as received`);
   await page.locator('#cardLayoutFixture').evaluate((el,html)=>el.insertAdjacentHTML('beforeend',html),marketplace.objectHtml);
   assert.equal((await page.locator('#cardLayoutFixture .violation-object-links strong').textContent()).trim(),'Відхилено',`${theme}: card status uses the same Ukrainian label as the table`);
   assert.equal((await page.locator('#cardLayoutFixture .violation-object-links small').textContent()).trim(),'Відхилено',`${theme}: known contract status uses the shared label map`);
   await page.locator('#cardLayoutFixture .violation-object-links').last().evaluate(el=>el.remove());
   assert.equal(await page.locator('.requests-table thead th').count(),10,`${theme}: all existing headers remain`);
   assert.equal((await page.locator('.requests-table thead th').nth(7).textContent()).trim(),'Сценарій',`${theme}: header matches cell contents`);
   for(let i=0;i<saved.length;i++){
    const item=saved[i],scenario=await page.locator(`tr[data-request-index="${i}"] .request-scenario-summary`).textContent();
    assert.equal(await page.locator(`tr[data-request-index="${i}"] td`).count(),10,`${theme}/${item.status}: row aligns to all table headers`);
    if(item.status==='declinedNoViolation'){
      assert.equal((await page.locator(`tr[data-request-index="${i}"] td`).nth(8).textContent()).trim(),'Відхилено',`${theme}: list table renders the technical status with the shared Ukrainian label`);
      assert((await page.locator(`tr[data-request-index="${i}"] td`).nth(8).locator('.request-status').getAttribute('class')).split(/\s+/).includes('status-declined'),`${theme}: declined status keeps the existing red status styling`);
    }
    const expectedScenario=String(item.scenario_summary||'').trim().replace(/^Сценарій:\s*/i,'')||'—';
    assert.equal(scenario,expectedScenario,`${theme}/${item.status}: cell shows adaptive scenario without only its leading service prefix`);
    assert(!/^Сценарій:/i.test(scenario),`${theme}/${item.status}: no leading duplicate service prefix`);
    if(i===4)assert(scenario.includes('сценарію'),'the word сценарій remains when it is part of the meaning');
    if(i===6)assert.equal(scenario,'—','a prefix without scenario content renders as empty');
    if(i===7){
      assert(scenario.startsWith('Перший рядок.\nДругий рядок із довгим змістом:'),`${theme}: line breaks and body text survive prefix removal`);
      const style=await page.locator(`tr[data-request-index="${i}"] .request-scenario-summary`).evaluate(el=>({display:getComputedStyle(el).display,whiteSpace:getComputedStyle(el).whiteSpace,overflowWrap:getComputedStyle(el).overflowWrap,overflow:getComputedStyle(el).overflow,lineClamp:getComputedStyle(el).webkitLineClamp}));
      assert.equal(style.whiteSpace,'normal',`${theme}: text wraps in the cell`);
      assert.equal(style.overflowWrap,'anywhere',`${theme}: long text can wrap without widening the table`);
      assert.equal(style.display,'block',`${theme}: summary uses natural block layout instead of a clamped box`);
      assert.equal(style.overflow,'visible',`${theme}: scenario text is not clipped`);
      assert.equal(style.lineClamp,'none',`${theme}: scenario has no line clamp`);
      const fullText=await page.locator(`tr[data-request-index="${i}"] .request-scenario-summary`).evaluate(el=>({text:el.textContent,scrollHeight:el.scrollHeight,clientHeight:el.clientHeight,rowHeight:el.closest('tr').getBoundingClientRect().height,scrollWidth:el.scrollWidth,clientWidth:el.clientWidth}));
      assert.equal(fullText.text,scenario,`${theme}: complete multiline scenario remains in the cell`);
      assert(fullText.clientHeight>=fullText.scrollHeight-1,`${theme}: the cell expands to the full scenario height`);
      assert(fullText.rowHeight>50,`${theme}: long scenario increases the row height`);
      assert(fullText.scrollWidth<=fullText.clientWidth+1,`${theme}: unbroken long words wrap inside the scenario column`);
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
   for(const columnWidth of [150,620]){
    await page.locator('.requests-table').evaluate((table,width)=>{
      table.style.tableLayout='fixed';
      table.querySelectorAll('tr').forEach(row=>{const cell=row.children[7];if(cell)cell.style.width=`${width}px`});
      const header=table.querySelectorAll('thead th')[7];if(header)header.style.width=`${width}px`;
    },columnWidth);
    for(const index of [7,9]){
      const layout=await page.locator(`tr[data-request-index="${index}"] .request-scenario-summary`).evaluate(el=>({text:el.textContent,clientHeight:el.clientHeight,scrollHeight:el.scrollHeight,clientWidth:el.clientWidth,scrollWidth:el.scrollWidth,rowHeight:el.closest('tr').getBoundingClientRect().height,overflow:getComputedStyle(el).overflow,maxHeight:getComputedStyle(el).maxHeight}));
      assert(layout.clientWidth<=columnWidth,`${theme}/${columnWidth}px: saved column width remains the wrapping boundary`);
      assert(layout.clientHeight>=layout.scrollHeight-1,`${theme}/${columnWidth}px: all scenario lines remain visible`);
      assert(layout.scrollWidth<=layout.clientWidth+1,`${theme}/${columnWidth}px: long tokens wrap inside the column`);
      assert.equal(layout.overflow,'visible',`${theme}/${columnWidth}px: no clipping overflow`);
      assert.equal(layout.maxHeight,'none',`${theme}/${columnWidth}px: no fixed maximum height`);
      assert.equal(layout.text,await page.locator(`tr[data-request-index="${index}"] .request-scenario-summary`).textContent(),`${theme}/${columnWidth}px: text content is intact`);
      assert(layout.rowHeight>50,`${theme}/${columnWidth}px: row grows to fit its full scenario`);
    }
   }
   await page.locator('tr[data-request-index="0"] td').nth(0).click();
   assert.equal(await page.evaluate(()=>window.lastOpened),0,`${theme}: one ordinary row click opens the appeal`);
  }
  const [platformTab]=await Promise.all([page.waitForEvent('popup'),page.locator('#cardLayoutFixture .violation-zakupivli-link').last().click()]);
  await platformTab.waitForLoadState('domcontentloaded');
  assert.equal(platformTab.url(),'https://my.zakupivli.pro/cabinet/ecatalog/gov/complaints/list?defendant_srn=43012009','one click opens supplier-filtered marketplace complaints in a separate tab');
  await platformTab.close();
  assert.equal(await page.evaluate(()=>cardOpens),2,'only ordinary row clicks open cards; eye clicks do not bubble into card opening');
  assert.equal(await page.evaluate(()=>writeCalls),0,'viewer does not initiate writes or regeneration');
  await page.locator('#refreshScenarioList').click();
  assert.equal(await page.evaluate(()=>cardContextFetches),2,'one existing card context resolution per ordinary click');
  assert.equal(await page.evaluate(()=>listRefreshes),1,'list refresh reads saved local scenario context');
  assert.equal(await page.locator('tr[data-request-index="0"] .request-scenario-summary').textContent(),
    String(saved[0].scenario_summary).replace(/^Сценарій:\s*/i,''),'scenario resolved by the card appears after list refresh');
  console.log('PASS: adaptive scenario rows without duplicate leading label, full untruncated multiline text, natural row growth, long-word wrapping, narrow/wide configured column widths, eye only for nonblank saved justification including missing/empty/whitespace cases, one-click read-only viewer, all statuses, both themes, saved column key, narrow horizontal scroll, one-click card opening, card context then refreshed-list scenario reuse');
 }finally{await context.close();await browser.close()}
})().catch(error=>{console.error(error);process.exit(1)});
