/* Offline Chromium: actual final modal renderer, full styles, no real requests. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('playwright'),root=path.resolve(__dirname,'..'),read=n=>fs.readFileSync(path.join(root,n),'utf8');
const out=process.env.PQM_UI_EVIDENCE_DIR;
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.PQM_TEST_BROWSER});
 const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(String(e)));
 const cdp=await page.context().newCDPSession(page);
 await page.route('**/*',r=>r.abort());
 try{
  await page.setContent(read('index.html').replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,''));
  for(const name of ['styles.css','filters.css','modules.css','schema_ui.css','ui_improvements.css','sandbox_theme.css','ui_final.css','ui_tz2.css'])await page.addStyleTag({content:read(name)});
  await page.evaluate(()=>{
   document.querySelector('#loginGate').hidden=true;document.querySelector('#applicationShell').hidden=false;
   window.$=s=>document.querySelector(s);window.API='/api';window.activeOperationalTask=null;
   window.esc=x=>String(x??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
   window.displayDateOnly=x=>String(x??'');window.displayDate=displayDateOnly;window.formatOfficerName=displayDateOnly;
   window.operationalSummaryLink=(url,text)=>`<a href="${esc(url)}">${esc(text)}</a>`;
   window.operationalTaskTypeLabels={amcu_exclusion:'АМКУ · виключення'};window.operationalTaskStatusLabels={completed:'Виконано',ready_for_document:'Готова до виключення'};
   window.operationalAssignmentAction=()=>'';window.documentDeclensionAction=()=>'';
   window.operationalActionIcon=()=>'';window.copyText=text=>{window.copiedMetadata=text};window.installViewportDrag=()=>{};
   window.operationalQualificationsHtml=()=>'<section id="source-qualifications">Незмінена таблиця кваліфікацій</section>';
   window.operationalQualificationHtml=()=>'<section id="qualification-summary">Незмінений підсумок кваліфікацій</section>';
   window.operationalCollapsedHistory=events=>`<details id="source-history"><summary>Історія задачі</summary>${events.map(e=>e.event_type).join(' ')}</details>`;
   for(const name of ['installOperationalSupplierDocument','installOperationalWarningActions','installOperationalAssignment','installOperationalAmcuActions','installOperationalTerminationDocuments'])window[name]=()=>{};
   window.saveOperationalTask=()=>{throw Error('Unexpected write')};window.openSupplierProfile=()=>{};
   window.request=async(url,options={})=>{if(options.method&&options.method!=='GET')throw Error('Unexpected write');return structuredClone(window.fixture)};
  });
  const source=read('app.js');
  for(const name of ['resolvedDocumentMetadataHtml','bindResolvedDocumentMetadata','installOperationalAmcuActions','installSharedDetailWindow','operationalResultHtml','operationalBasisHtml','operationalDecisionHtml','operationalAmcuProtocolMetadataHtml','operationalAmcuDecisionCards','operationalTerminalHtml','operationalTaskHumanState','operationalAmcuHtml']){
   const start=source.indexOf('function '+name+'('),tail=source.slice(start),end=tail.slice(1).search(/\n(?:async )?function /);
   assert(start>=0);await page.addScriptTag({content:end<0?tail:tail.slice(0,end+1)});
  }
  const open=source.split(/\r?\n/).find(line=>line.startsWith("openOperationalTask=async function(taskId){const dialog=$('#operationalTaskDialog'),body="));
  assert(open&&open.endsWith('}}'));
  await page.addScriptTag({content:open});
  const layoutStart=source.indexOf('function operationalV2Layout('),wrapperStart=source.indexOf('const openOperationalTaskPolished=');
  assert(layoutStart>=0&&wrapperStart>layoutStart);
  await page.addScriptTag({content:source.slice(layoutStart,wrapperStart)});
  const wrapperEnd=source.indexOf("\n$('#operationalTaskType')",wrapperStart);
  assert(wrapperEnd>wrapperStart);
  await page.addScriptTag({content:source.slice(wrapperStart,wrapperEnd)});
  await page.evaluate(()=>installSharedDetailWindow($('#operationalTaskDialog')));
  let checks=0;
  for(const dark of [false,true])for(const zoom of [1,1.25])for(const width of [390,768,1440])for(const mode of ['modal','floating'])for(const variant of ['long','missing','multiple','active','old-only','single']){
   // Browser zoom shrinks the CSS viewport and scales pixels; body.zoom does not
   // reproduce viewport units in fixed floating windows.
   await page.setViewportSize({width:Math.round(width/zoom),height:Math.round(1000/zoom)});
   await cdp.send('Emulation.setDeviceMetricsOverride',{width:Math.round(width/zoom),height:Math.round(1000/zoom),deviceScaleFactor:zoom,mobile:false});
   await page.evaluate(async({dark,zoom,variant,mode})=>{
    document.documentElement.toggleAttribute('data-pqm-environment',dark);
    if(dark)document.documentElement.dataset.pqmEnvironment='sandbox';
    document.body.style.zoom=1;
    const docs=[3,2,1].map(v=>({id:'v'+v,version:v,display_filename:'Протокол фактичний '+v+' '+('Довга назва документа з переносом за словами '.repeat(8))+'.docx',download_url:'/documents/v'+v+'/download',pdf_url:'/documents/v'+v+'/pdf'}));
    docs[0].resolved_metadata=[{metadata_key:'subject',label:'Фактична тема',resolved_text:'ТЕКСТ АКТУАЛЬНОЇ ВЕРСІЇ '+('Довгий зміст протоколу з фактичних збережених метаданих. '.repeat(8)),version:7},
     {metadata_key:'additional',label:'Додаткове змістове поле',resolved_text:'ІНШЕ ЗБЕРЕЖЕНЕ ЗНАЧЕННЯ',version:3}];
    docs[1].resolved_metadata=[{metadata_key:'subject',label:'Стара тема',resolved_text:'СТАРИЙ ТЕКСТ ВЕРСІЇ 2'}];
    if(variant==='old-only')docs[0].resolved_metadata=[];
    if(variant==='single')docs.splice(1);
    window.fixture={id:'a'.repeat(32),task_type:'amcu_exclusion',status:variant==='active'?'ready_for_document':'completed',resolution_code:'amcu_excluded',
     result_summary:{label:'Виключення підтверджено Prozorro'},supplier_name_snapshot:'Синтетичний постачальник',supplier_code:'00000001',assigned_officer_name:'Історична УО',created_at:'2026-10-01',
     protocol_number:'ІНШЕ-91',protocol_date:'2026-10-13',basis_items:[{kind:'amcu_decision',number:'ІНШЕ-42',date:'2026-10-12',reference:'https://example.invalid/basis'}],
     officer_decision:{number:'ІНШЕ-91',date:'2026-10-13',documents:[docs[0]]},document_generation:{documents:docs},events:[{event_type:'generation1'},{event_type:'generation2'},{event_type:'generation3'}]};
    if(variant==='missing'){fixture.basis_items=[];fixture.officer_decision={};fixture.document_generation={documents:[]};}
    if(variant==='multiple')fixture.officer_decision.documents.push({...docs[0],id:'other',download_url:'/other/download',pdf_url:'/other/pdf',resolved_metadata:[{metadata_key:'other',label:'Інший документ',resolved_text:'ТЕКСТ ІНШОГО ДОКУМЕНТА'}]});
    await openOperationalTask(fixture.id);
    const dialog=$('#operationalTaskDialog');if(dialog.dataset.detailWindow!==mode)dialog.querySelector('.detail-window-toggle').click();
   },{dark,zoom,variant,mode});
   await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
   const result=await page.evaluate(()=>{
    const dialog=$('#operationalTaskDialog'),cards=[...dialog.querySelectorAll('.operational-amcu-decision-cards>article')],b=cards.map(c=>c.getBoundingClientRect());
    const metadata=dialog.querySelector('.operational-amcu-protocol-metadata'),details=dialog.querySelector('.operational-amcu-decision-inner>.operational-amcu-decision-content');
    const code=dialog.querySelector('.operational-amcu-supplier-code'),identity=code.parentElement;
    const range=document.createRange();range.selectNodeContents(code);const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);const copiedCode=selection.toString();selection.removeAllRanges();
    return{cards:cards.length,widths:b.map(r=>r.width),tops:b.map(r=>r.top),headings:cards.map(c=>c.querySelector('h3').textContent),
     headingTops:cards.map(c=>c.querySelector('h3').getBoundingClientRect().top),padding:cards.map(c=>getComputedStyle(c).padding),
     available:dialog.clientWidth,overflow:dialog.scrollWidth>dialog.clientWidth||cards.some(c=>c.scrollWidth>c.clientWidth),formRight:dialog.querySelector(':scope>form').getBoundingClientRect().right,viewport:innerWidth,
     label:dialog.textContent.includes('Виключення підтверджено Prozorro'),text:cards.map(c=>c.textContent).join(' '),
     links:cards.flatMap(c=>[...c.querySelectorAll('a')].map(a=>a.getAttribute('href'))),
     color:getComputedStyle(cards[0]).color,bg:getComputedStyle(cards[0]).backgroundColor,
     metadataText:metadata?.textContent||'',metadataTop:metadata?.getBoundingClientRect().top,metadataLeft:metadata?.getBoundingClientRect().left,
     detailsTop:details.getBoundingClientRect().top,detailsLeft:details.getBoundingClientRect().left,
     codeWeight:getComputedStyle(code).fontWeight,labelWeight:getComputedStyle(identity).fontWeight,
     sameFontSize:getComputedStyle(code).fontSize===getComputedStyle(identity).fontSize,copiedCode,
     history:$('#source-history').textContent,qual:!!$('#qualification-summary')};
   });
   assert.equal(result.cards,2);assert.deepEqual(result.headings,['Підстава','Рішення УО']);
   assert(Math.abs(result.widths[0]-result.widths[1])<1);assert.equal(result.padding[0],result.padding[1]);
   assert(!result.overflow&&!result.label&&result.qual);
   assert.equal(result.viewport,Math.round(width/zoom));
   assert(result.formRight<=result.viewport+1);
   assert.equal(result.codeWeight,'700');assert.equal(result.labelWeight,'400');assert(result.sameFontSize);assert.equal(result.copiedCode,'00000001');
   const sideBySide=Math.abs(result.tops[0]-result.tops[1])<1;
   if(width===1440)assert(sideBySide&&Math.abs(result.headingTops[0]-result.headingTops[1])<1);
   if(width===390)assert(!sideBySide,JSON.stringify({dark,zoom,width,mode,variant,result}));
   if(variant==='missing')assert(result.text.includes('Не зазначено')&&result.text.includes('Не сформовано'));
   else{assert(result.links.includes('/documents/v3/download'));assert(!result.links.includes('/documents/v2/download'));}
   if(variant==='multiple')assert(result.links.includes('/other/download'));
   if(['missing','old-only'].includes(variant))assert.equal(result.metadataText,'');
   else{
    assert(result.metadataText.includes('Зміст протоколу')&&result.metadataText.includes('ТЕКСТ АКТУАЛЬНОЇ ВЕРСІЇ')&&result.metadataText.includes('ІНШЕ ЗБЕРЕЖЕНЕ ЗНАЧЕННЯ'));
    assert(!result.metadataText.includes('СТАРИЙ ТЕКСТ'));
    if(width===1440)assert(Math.abs(result.metadataTop-result.detailsTop)<1&&result.metadataLeft>result.detailsLeft);
    try{await page.locator('.operational-amcu-protocol-metadata [data-copy-resolved-metadata]').first().click({timeout:3000});}
    catch(error){console.error(JSON.stringify({dark,zoom,width,mode,variant,geometry:await page.evaluate(()=>[document.querySelector('#operationalTaskDialog'),document.querySelector('#operationalTaskDialog>form'),document.querySelector('.operational-workspace'),document.querySelector('.operational-amcu-protocol-metadata button')].map(n=>({tag:n.tagName,classes:n.className,box:n.getBoundingClientRect().toJSON(),scroll:n.scrollHeight,client:n.clientHeight,top:n.scrollTop,overflow:getComputedStyle(n).overflowY})))}));throw error;}
    assert((await page.evaluate(()=>window.copiedMetadata)).startsWith('ТЕКСТ АКТУАЛЬНОЇ ВЕРСІЇ'));
   }
   assert(result.history.includes('generation1')&&result.history.includes('generation3'));
   if(out&&zoom===1&&variant==='long'&&width!==768&&mode==='modal'){fs.mkdirSync(out,{recursive:true});await page.screenshot({path:path.join(out,`amcu-${dark?'dark':'light'}-${width}.png`)});}
   checks++;
  }
  assert.deepEqual(errors,[]);console.log('AMCU_CARD_LAYOUT_BROWSER=PASS; '+checks+' combinations, themes/100-125%/390-1440/long/missing/multiple/history');
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
