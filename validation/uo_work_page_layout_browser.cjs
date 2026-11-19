const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const {chromium}=require('playwright');

const ROOT=path.resolve(__dirname,'..');
const OUT=process.env.PQM_UO_EVIDENCE_DIR||path.join(os.tmpdir(),'pqm-uo-work-layout-evidence');
const read=name=>fs.readFileSync(path.join(ROOT,name),'utf8');
const html=read('index.html').replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,'').replace(/<link\b[^>]*rel=["']stylesheet["'][^>]*>/gi,'');
const styles=['styles.css','chat_annotations.css','filters.css','modules.css','schema_ui.css','ui_improvements.css','ui_final.css','theme.css','uo_work_page.css','nazk_preview.css','ui_tz2.css','halloween.css'];
const officers=['Дмитро САВВА','Олена ЄРЬОМІНА','Тетяна ФЕДЧЕНКО','Світлана НАМЯСЕНКО','Дуже Довге Ім’я Уповноваженої ОСОБИ'];
const esc=value=>String(value).replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));

function protocolCard(name,index){
  const total=[9,7,5,4,3][index%5],reviewed=[4,7,0,1,2][index%5],pending=total-reviewed,ratio=total?Math.round(reviewed*100/total):0;
  return `<article class="qualification-summary-officer protocol-officer-card" data-protocol-officer="${esc(name)}"><button type="button" class="protocol-officer-main"><span>${esc(name)}</span><strong>${total}</strong></button><div class="protocol-officer-progress"><div class="protocol-progress-track" title="Розглянуто: ${reviewed} із ${total} (${ratio}%)"><span style="width:${ratio}%"></span></div><div class="protocol-progress-meta"><span>${ratio}%</span><button class="protocol-pending-count" type="button" title="Не розглянуто: ${pending}. Відкрити в реєстрі заявок" ${pending===0?'disabled':''}>${pending}</button></div></div></article>`;
}
function categoryCard(name,index){return `<button class="qualification-summary-officer qualification-summary-category"><span>${esc(name)}</span><strong>${[12,9,5,3,1][index%5]}</strong><small>категорія</small></button>`;}
function statisticRows(count){return officers.slice(0,Math.min(count,officers.length)).map((name,i)=>`<tr><th scope="row">${esc(name)}</th><td><button class="ghost publication-kpi">${i}</button></td><td><button class="ghost publication-kpi">${i+1}</button></td><td><button class="ghost publication-kpi">${i+2}</button></td><td><button class="ghost publication-kpi">${i+3}</button></td></tr>`).join('');}

async function makePage(browser,theme='light',width=1920,height=1080){
  const page=await browser.newPage({viewport:{width,height},deviceScaleFactor:1});
  await page.setContent(html);
  for(const name of styles)await page.addStyleTag({content:read(name)});
  await page.evaluate(({theme,officers})=>{
    document.documentElement.dataset.theme=theme;
    document.documentElement.dataset.pqmEnvironment='sandbox';
    document.documentElement.dataset.halloween='off';
    document.querySelector('#loginGate').hidden=true;
    document.querySelector('#applicationShell').hidden=false;
    document.querySelectorAll('main').forEach(main=>{main.hidden=main.id!=='workQueueView';});
    const set=(selector,value)=>{const node=document.querySelector(selector);if(node)node.innerHTML=value;};
    document.querySelector('#queueProtocolFrom').value='2026-10-01';
    document.querySelector('#queueProtocolTo').value='2026-10-31';
    document.querySelector('#queueProtocolTotal').textContent='28';
    document.querySelector('#queueQualificationTotal').textContent='16';
    const categories=['Їжа','Інше','Газ/ЕЕ','Пальне','Вугілля'];
    document.querySelector('#queueProtocolCategoryCards').innerHTML=categories.map((name,i)=>`<button class="qualification-summary-officer qualification-summary-category"><span>${name}</span><strong>${[12,9,7,4,2][i]}</strong><small>категорія</small></button>`).join('');
    document.querySelector('#queueCategoryCards').innerHTML=categories.map((name,i)=>`<button class="qualification-summary-officer qualification-summary-category"><span>${name}</span><strong>${[8,5,3,2,1][i]}</strong><small>категорія</small></button>`).join('');
    document.querySelector('#queueProtocolOfficerCards').innerHTML=officers.slice(0,5).map((name,i)=>`<article class="qualification-summary-officer protocol-officer-card" data-protocol-officer="${name}"><button type="button" class="protocol-officer-main"><span>${name}</span><strong>${[9,7,5,4,3][i]}</strong></button><div class="protocol-officer-progress"><div class="protocol-progress-track" title="Розглянуто: ${[4,7,0,1,2][i]} із ${[9,7,5,4,3][i]} (${Math.round([4,7,0,1,2][i]*100/[9,7,5,4,3][i])}%)"><span style="width:${Math.round([4,7,0,1,2][i]*100/[9,7,5,4,3][i])}%"></span></div><div class="protocol-progress-meta"><span>${Math.round([4,7,0,1,2][i]*100/[9,7,5,4,3][i])}%</span><button class="protocol-pending-count" type="button" title="Не розглянуто: ${[5,0,5,3,1][i]}. Відкрити в реєстрі заявок" ${i===1?'disabled':''}>${[5,0,5,3,1][i]}</button></div></div></article>`).join('');
    document.querySelector('#queueQualificationCards').innerHTML=officers.slice(0,3).map((name,i)=>`<button class="qualification-summary-officer"><span>${name}</span><strong>${[8,5,3][i]}</strong><small>очікує рішення</small></button>`).join('');
    document.querySelector('#queuePublicationControl').innerHTML='<button class="publication-kpi publication-kpi--admitted"><span>Допущено</span><strong>18</strong></button><button class="publication-kpi publication-kpi--rejected"><span>Відхилено</span><strong>4</strong></button><button class="publication-kpi publication-kpi--pending"><span>Все ще очікує рішення</span><strong>6</strong></button>';
    document.querySelector('#queueStatisticsKpis').innerHTML='<button class="ghost publication-kpi submitted"><span>Подано заявок</span><strong>23</strong></button><button class="ghost publication-kpi admitted"><span>Допущено</span><strong>12</strong></button><button class="ghost publication-kpi rejected"><span>Відхилено</span><strong>4</strong></button><button class="ghost publication-kpi pending"><span>Очікує рішення</span><strong>7</strong></button>';
    document.querySelector('#queueStatisticsTrendSvg').innerHTML='<g class="trend-axis"><g class="trend-grid"><line x1="54" y1="25" x2="874" y2="25"/><text x="46" y="29" text-anchor="end">20</text></g><g class="trend-grid"><line x1="54" y1="110" x2="874" y2="110"/><text x="46" y="114" text-anchor="end">10</text></g><g class="trend-grid"><line x1="54" y1="195" x2="874" y2="195"/><text x="46" y="199" text-anchor="end">0</text></g><text class="trend-axis-label" x="54" y="242">01.10.2026</text><text class="trend-axis-label" x="874" y="242" text-anchor="end">31.10.2026</text></g><path class="trend-line trend-submitted" d="M54,170 L300,115 L600,80 L874,38" fill="none" stroke="var(--statistics-submitted)" stroke-width="2.5"/><path class="trend-line trend-active" d="M54,192 L300,155 L600,145 L874,120" fill="none" stroke="var(--statistics-admitted)" stroke-width="2.5"/><path class="trend-line trend-unsuccessful" d="M54,205 L300,185 L600,180 L874,165" fill="none" stroke="var(--statistics-rejected)" stroke-width="2.5"/>';
    document.querySelector('#queueStatisticsRows').innerHTML=Array.from({length:8},(_,i)=>`<tr><th scope="row">${officers[i%officers.length]}</th><td><button class="ghost publication-kpi">${i}</button></td><td><button class="ghost publication-kpi">${i+1}</button></td><td><button class="ghost publication-kpi">${i+2}</button></td><td><button class="ghost publication-kpi">${i+3}</button></td></tr>`).join('');
    const statisticsTable=document.querySelector('.queue-statistics-table');
    statisticsTable.classList.add('queue-statistics-table--scroll');
    const tableHeader=statisticsTable.querySelector('thead'),firstFive=[...document.querySelectorAll('#queueStatisticsRows tr')].slice(0,5);
    statisticsTable.style.maxHeight=`${Math.ceil(tableHeader.getBoundingClientRect().height+firstFive.reduce((sum,row)=>sum+row.getBoundingClientRect().height,0))}px`;
    document.querySelector('#queueStatisticsFrom').value='2026-10-01';
    document.querySelector('#queueStatisticsTo').value='2026-10-31';
    document.querySelector('#queueStatisticsGroup').value='review_officer';
    document.querySelector('[data-statistics-filter="category"]').innerHTML='<option value="">Усі</option><option>Їжа</option>';
    document.querySelector('[data-statistics-filter="supplier_type"]').value='individual_entrepreneur';
    document.querySelector('[data-statistics-filter="category"]').value='Їжа';
    document.querySelector('[data-statistics-filter="review_officer"]').innerHTML='<option value="">Усі</option><option>Дмитро САВВА</option>';
    document.querySelector('[data-statistics-filter="protocol_officer"]').innerHTML='<option value="">Усі</option><option>Олена ЄРЬОМІНА</option>';
    document.querySelector('#queueStatisticsDkOptions').innerHTML=['02100000-6','03000000-1','45000000-7'].map((value,index)=>`<label><input type="checkbox" ${index<2?'checked':''}> ${value}</label>`).join('');
    const filterSections=Object.fromEntries([...document.querySelectorAll('[data-statistics-filter-section]')].map(section=>[section.dataset.statisticsFilterSection,section]));
    for(const key of ['supplier_type','dk_code']){const section=filterSections[key];section.classList.add('filter-active');section.querySelector('.queue-statistics-section-state').textContent='';section.querySelector('.queue-statistics-section-count').textContent=key==='dk_code'?'2':'1';section.querySelector('[data-statistics-filter-reset]').hidden=false;}
    const draftSection=filterSections.category;draftSection.classList.add('filter-pending');draftSection.querySelector('.queue-statistics-section-state').textContent='Не застосовано';draftSection.querySelector('.queue-statistics-section-count').textContent='';
  },{theme,officers});
  await page.addScriptTag({path:path.join(ROOT,'filter_panels_ui.js')});
  return page;
}

async function makeAuxPage(browser,theme,viewId,width,height){
  const page=await browser.newPage({viewport:{width,height},deviceScaleFactor:1});
  await page.setContent(html);
  for(const name of styles)await page.addStyleTag({content:read(name)});
  await page.evaluate(({theme,viewId})=>{
    document.documentElement.dataset.theme=theme;
    document.documentElement.dataset.pqmEnvironment='sandbox';
    document.documentElement.dataset.halloween='off';
    document.querySelector('#loginGate').hidden=true;
    document.querySelector('#applicationShell').hidden=false;
    document.querySelectorAll('main').forEach(main=>{main.hidden=main.id!==viewId;});
    if(viewId==='historyView'){
      document.querySelectorAll('#historyFilters input[data-history]').forEach(input=>{
        const wrapper=document.createElement('div');wrapper.className='pqm-clear-wrap';input.before(wrapper);wrapper.append(input);
        const button=document.createElement('button');button.type='button';button.className='pqm-search-clear';button.textContent='×';button.hidden=true;wrapper.append(button);
      });
    }
    if(viewId==='requestsView'){
      document.querySelector('#requestAuthorityCards').innerHTML=['Профзакупівлі','МЗУ','УСС'].map((name,index)=>`<button class="request-authority-card"><span>${name}</span><strong>${index+2}</strong></button>`).join('');
      document.querySelector('#requestsPending').textContent='12';document.querySelector('#requestsSatisfied').textContent='18';document.querySelector('#requestsDeclined').textContent='3';
      document.querySelectorAll('#requestQuickFilters [data-status]').forEach(button=>button.setAttribute('aria-label',`${button.title}: ${button.querySelector('strong').textContent}`));
    }
  },{theme,viewId});
  await page.addScriptTag({path:path.join(ROOT,'filter_panels_ui.js')});
  return page;
}

(async()=>{
  fs.mkdirSync(OUT,{recursive:true});
  const browser=await chromium.launch({headless:true,ignoreDefaultArgs:['--hide-scrollbars'],executablePath:process.env.PQM_CHROMIUM_EXECUTABLE||undefined});
  try{
    const evidence=[];
    for(const theme of ['light','dark']){
      const page=await makePage(browser,theme);
      const layout=await page.evaluate(()=>{
        const rect=selector=>{const r=document.querySelector(selector).getBoundingClientRect();return{x:r.x,y:r.y,right:r.right,bottom:r.bottom,width:r.width,height:r.height};};
        return{protocol:rect('.queue-protocol-summary'),current:rect('.queue-current-summary'),left:rect('.queue-summary-left'),statistics:rect('.queue-statistics-card'),grid:rect('.work-queue-operational-grid'),statsAlign:getComputedStyle(document.querySelector('.queue-statistics-card')).alignSelf,heading:document.querySelector('#workQueueView .module-heading').innerText.trim(),kpisNext:document.querySelector('#workQueueKpis').nextElementSibling.className};
      });
      assert.match(layout.heading,/^Робота УО$/,'page heading contains only the approved title');
      assert.equal(layout.kpisNext,'work-queue-operational-grid','existing KPI section keeps its current position without being added or moved');
      assert.ok(Math.abs(layout.protocol.x-layout.current.x)<2,'protocol and current summaries share the left column');
      assert.ok(layout.current.y>=layout.protocol.bottom,'current applications are stacked below the protocol summary');
      assert.ok(layout.current.y-layout.protocol.bottom<24,'left summaries keep a compact vertical gap');
      assert.ok(layout.statistics.x>=layout.left.right-2,'statistics occupies the separate right column');
      assert.ok(Math.abs(layout.statistics.y-layout.grid.y)<2,'statistics aligns to the top of the operational grid');
      assert.equal(layout.statsAlign,'start','statistics remains sized to its own content');
      assert.ok(layout.statistics.height<layout.left.height&&layout.statistics.bottom<layout.left.bottom,`statistics stays content-sized instead of being stretched to match both left blocks: ${JSON.stringify(layout)}`);
      assert.ok(layout.left.width/layout.statistics.width>0.74&&layout.left.width/layout.statistics.width<0.9,`wide layout keeps approximately 45/55 columns: ${JSON.stringify(layout)}`);
      const leftMarkers=await page.evaluate(()=>['#queueProtocolCategoryCards>.qualification-summary-category','#queueCategoryCards>.qualification-summary-category','#queueProtocolOfficerCards>.protocol-officer-card:not([data-protocol-officer="Не призначено"])','#queueQualificationCards>.qualification-summary-officer','#queueStatisticsKpis button','#queuePublicationControl button'].map(selector=>{const node=document.querySelector(selector);return{selector,color:getComputedStyle(node).borderLeftColor,width:getComputedStyle(node).borderLeftWidth}}));
      assert.ok(leftMarkers.every(item=>item.width==='4px'&&item.color!=='rgba(0, 0, 0, 0)'),`work dashboard keeps its approved colored left markers: ${JSON.stringify(leftMarkers)}`);
      const protocolHeader=await page.evaluate(()=>{
        const rect=selector=>{const r=document.querySelector(selector).getBoundingClientRect();return{left:r.left,right:r.right};};
        return{title:rect('.queue-protocol-summary h2'),period:rect('.queue-protocol-summary .protocol-period'),total:rect('#queueProtocolTotal'),card:rect('.queue-protocol-summary')};
      });
      assert.ok(protocolHeader.period.left>=protocolHeader.title.right+8,'protocol dates and search sit slightly to the right of the title');
      assert.ok(protocolHeader.card.right-protocolHeader.total.right<20,'protocol total stays close to the card right edge');
      for(const selector of ['#queueProtocolCategoryCards>.qualification-summary-category','#queueCategoryCards>.qualification-summary-category']){
        const positions=await page.locator(selector).evaluateAll(nodes=>nodes.map(node=>({name:node.textContent.trim(),top:node.getBoundingClientRect().top,left:node.getBoundingClientRect().left,width:node.getBoundingClientRect().width,background:getComputedStyle(node).backgroundColor,border:getComputedStyle(node).borderTopColor,borderWidth:getComputedStyle(node).borderLeftWidth,topBorderWidth:getComputedStyle(node).borderTopWidth})));
        assert.equal(positions.length,5,`${selector} renders all five categories`);
        assert.ok(positions.every(item=>Math.abs(item.top-positions[0].top)<2),`${selector} keeps all five categories on one row: ${JSON.stringify(positions)}`);
        assert.ok(positions.every(item=>item.width>0&&item.borderWidth==='4px'&&item.topBorderWidth==='1px'),`${selector} cards have compact widths, a thin colored marker and a thin outline`);
        if(theme==='light')assert.ok(positions.every(item=>item.background==='rgb(238, 243, 255)'&&item.border==='rgb(134, 168, 223)'),`${selector} uses the approved light-blue category palette: ${JSON.stringify(positions)}`);
        else assert.ok(positions.every(item=>item.background==='rgb(28, 53, 81)'&&item.border==='rgb(75, 121, 168)'),`${selector} keeps dark-blue fills with blue outlines: ${JSON.stringify(positions)}`);
      }
      const officerPalette=await page.locator('#queueProtocolOfficerCards>.protocol-officer-card:not([data-protocol-officer="Не призначено"])').first().evaluate(node=>({background:getComputedStyle(node).backgroundColor,border:getComputedStyle(node).borderTopColor,borderWidth:getComputedStyle(node).borderLeftWidth,topBorderWidth:getComputedStyle(node).borderTopWidth}));
      assert.equal(officerPalette.borderWidth,'4px','officer cards have a slim colored marker');
      assert.equal(officerPalette.topBorderWidth,'1px','officer cards keep a thin outline');
      if(theme==='light')assert.deepEqual(officerPalette,{background:'rgb(237, 246, 232)',border:'rgb(141, 182, 122)',borderWidth:'4px',topBorderWidth:'1px'},'light officer cards use the approved green palette');
      else assert.deepEqual(officerPalette,{background:'rgb(23, 62, 56)',border:'rgb(63, 123, 104)',borderWidth:'4px',topBorderWidth:'1px'},'dark officer cards retain green fills with green outlines');
      const officerRows=await page.evaluate(()=>{
        const positions=selector=>[...document.querySelectorAll(selector)].map(node=>({top:node.getBoundingClientRect().top,right:node.getBoundingClientRect().right}));
        const protocol=positions('#queueProtocolOfficerCards>.protocol-officer-card'),current=positions('#queueQualificationCards>.qualification-summary-officer'),container=document.querySelector('#queueQualificationCards').getBoundingClientRect();
        return{protocol,current,currentContainerRight:container.right};
      });
      assert.equal(officerRows.protocol.length,5,'protocol summary renders five officer cards');
      assert.ok(officerRows.protocol.every(card=>Math.abs(card.top-officerRows.protocol[0].top)<2),'five protocol officer cards fit in one wide-screen row');
      assert.equal(officerRows.current.length,3,'current summary renders the available officer cards');
      assert.ok(officerRows.current.every(card=>Math.abs(card.top-officerRows.current[0].top)<2),'current officer cards fit in one wide-screen row');
      assert.ok(officerRows.current.at(-1).right<officerRows.currentContainerRight-20,'three current officer cards do not stretch to fill all five columns');
      for(const selector of ['#queueProtocolOfficerCards>.protocol-officer-card','#queueQualificationCards>.qualification-summary-officer']){
        const names=page.locator(selector);
        const cards=await names.evaluateAll(nodes=>nodes.map(card=>{const name=card.querySelector('span'),main=card.querySelector('.protocol-officer-main'),progress=card.querySelector('.protocol-officer-progress');return{height:card.getBoundingClientRect().height,name:{clientWidth:name.clientWidth,scrollWidth:name.scrollWidth,clientHeight:name.clientHeight,scrollHeight:name.scrollHeight,text:name.textContent},mainBottom:main?.getBoundingClientRect().bottom,progressTop:progress?.getBoundingClientRect().top};}));
        assert.ok(cards.every(card=>card.height===cards[0].height),`${selector} cards keep a consistent height with a long name`);
        assert.ok(cards.every(card=>card.name.scrollWidth<=card.name.clientWidth+1&&card.name.scrollHeight<=card.name.clientHeight+1),`${selector} long names wrap without clipping: ${JSON.stringify(cards)}`);
        assert.ok(cards.filter(card=>card.mainBottom!==undefined).every(card=>card.mainBottom<=card.progressTop+1),'officer name/count never overlap progress');
      }
      const rows=await page.locator('#queueStatisticsRows tr').count();assert.equal(rows,8);
      const table=await page.locator('.queue-statistics-table').evaluate(el=>({client:el.clientHeight,scroll:el.scrollHeight,overflow:getComputedStyle(el).overflowY}));
      assert.ok(table.scroll>table.client,'more than five rows scroll inside the table');
      const toolbar=await page.locator('.queue-statistics-controls').evaluate(el=>[...el.children].map(node=>({id:node.id||node.querySelector('input,select')?.id||node.getAttribute('data-statistics-filter')||node.textContent.trim().slice(0,16),left:node.getBoundingClientRect().left,top:node.getBoundingClientRect().top,right:node.getBoundingClientRect().right})));
      assert.equal(toolbar.length,7,'statistics toolbar contains dates, apply, reset, separator, grouping and filters');
      assert.ok(toolbar.filter(item=>item.id).every(item=>Math.abs(item.top-toolbar[0].top)<2),`all toolbar controls share one row at wide width: ${JSON.stringify(toolbar)}`);
      const visibleToolbar=toolbar.filter(item=>item.right>item.left);
      assert.ok(visibleToolbar.every((item,index)=>index===0||item.left>=visibleToolbar[index-1].right-1),`visible toolbar controls keep the requested order while the separator occupies no space: ${JSON.stringify(toolbar)}`);
      const typeOptions=await page.locator('[data-statistics-filter="supplier_type"] option').evaluateAll(nodes=>nodes.map(option=>[option.value,option.textContent.trim()]));
      assert.deepEqual(typeOptions,[['','Усі'],['individual_entrepreneur','ФОП'],['legal_entity','ЮО та інші'],['foreign_legal_entity','Нерезидент'],['unknown','Потребує перевірки']]);
      const firstFilterLabel=await page.locator('.queue-statistics-filter-section-heading').first().textContent();
      assert.match(firstFilterLabel,/Тип/,'supplier type is the first filter in the side panel');
      const filterStates=await page.locator('[data-statistics-filter-section]').evaluateAll(nodes=>nodes.map(node=>({active:node.classList.contains('filter-active'),pending:node.classList.contains('filter-pending'),resetHidden:node.querySelector('[data-statistics-filter-reset]').hidden,background:getComputedStyle(node.querySelector('.queue-statistics-filter-section-heading')).backgroundColor})).slice(0,3));
      assert.equal(filterStates[0].active,true,'applied filters remain visibly active in their section heading');
      assert.equal(filterStates[0].resetHidden,false,'each applied filter exposes its own reset control');
      assert.equal(filterStates[1].pending,true,'unapplied edits are shown separately from applied filters');
      assert.equal(filterStates[0].background,theme==='dark'?'rgb(36, 62, 90)':'rgb(228, 239, 255)','active filter headings use the approved readable theme highlight');
      const cardPalette=await page.locator('.queue-statistics-card').evaluate(el=>({background:getComputedStyle(el).backgroundColor,border:getComputedStyle(el).borderTopColor}));
      if(theme==='light')assert.deepEqual(cardPalette,{background:'rgb(240, 246, 255)',border:'rgb(141, 180, 229)'},'light statistics card has the approved blue tint');
      else assert.deepEqual(cardPalette,{background:'rgb(32, 54, 80)',border:'rgb(100, 136, 181)'},'dark statistics card has the approved blue tint');
      const controls=await page.locator('.queue-statistics-controls').evaluate(el=>getComputedStyle(el).display);
      assert.equal(controls,'flex');
      const controlHeights=await page.locator('#queueProtocolFrom,#queueProtocolTo,#queueProtocolApply,#queueStatisticsFrom,#queueStatisticsTo,#queueStatisticsFilterToggle,#queueStatisticsGroup,#queueStatisticsSearch,#queueStatisticsReset').evaluateAll(nodes=>nodes.map(node=>({id:node.id,height:node.getBoundingClientRect().height,borderRadius:getComputedStyle(node).borderRadius})));
      assert.ok(controlHeights.every(control=>control.height===34&&control.borderRadius==='7px'),`page controls share a 34px height and matching corners: ${JSON.stringify(controlHeights)}`);
      const statsControlOrder=await page.locator('.queue-statistics-controls>*').evaluateAll(nodes=>nodes.map(node=>node.id||node.className));
      assert.deepEqual(statsControlOrder.slice(0,7),['queueStatisticsFromField','queueStatisticsToField','queueStatisticsSearch','queueStatisticsReset','queue-statistics-control-separator','queueStatisticsGroupField','queueStatisticsFilterToggle'],'statistics controls follow the approved date/apply/reset/group/filter order');
      const kpis=await page.locator('#queueStatisticsKpis button').evaluateAll(nodes=>nodes.map(node=>({bg:getComputedStyle(node).backgroundColor,color:getComputedStyle(node).color,border:getComputedStyle(node).borderTopColor})));
      assert.equal(kpis.length,4);
      const kpiRows=await page.locator('#queueStatisticsKpis button').evaluateAll(nodes=>nodes.map(node=>Math.round(node.getBoundingClientRect().top)));
      assert.equal(new Set(kpiRows).size,1,'all four statistics KPIs stay in one row');
      if(theme==='dark'){
        assert.deepEqual(kpis.map(item=>item.bg),['rgb(32, 54, 80)','rgb(23, 62, 56)','rgb(72, 41, 50)','rgb(68, 59, 38)']);
        assert.deepEqual(kpis.map(item=>item.color),['rgb(237, 243, 252)','rgb(237, 243, 252)','rgb(237, 243, 252)','rgb(237, 243, 252)']);
        const tableText=await page.locator('.queue-statistics-table td button').first().evaluate(el=>getComputedStyle(el).color);
        assert.equal(tableText,'rgb(237, 243, 252)','dark table numbers remain readable');
      }else {
        assert.deepEqual(kpis.map(item=>item.bg),['rgb(228, 239, 255)','rgb(229, 246, 236)','rgb(253, 232, 231)','rgb(255, 244, 212)']);
        assert.equal(kpis[2].color,'rgb(0, 0, 0)','light rejected KPI text and numbers are black');
        assert.equal(kpis[2].border,'rgb(233, 165, 160)','light rejected KPI uses the approved red border');
        const leftRejected=await page.locator('#queuePublicationControl .publication-kpi--rejected').evaluate(el=>({bg:getComputedStyle(el).backgroundColor,color:getComputedStyle(el).color,border:getComputedStyle(el).borderTopColor}));
        assert.deepEqual(leftRejected,{bg:'rgb(253, 232, 231)',color:'rgb(0, 0, 0)',border:'rgb(233, 165, 160)'},'left rejected KPI matches the approved light red style');
      }
      const screenshot=path.join(OUT,`work-uo-${theme}-wide-closed.png`);
      await page.screenshot({path:screenshot,fullPage:true});evidence.push(screenshot);
      const workspace=page.locator('#queueStatisticsWorkspace'),panel=page.locator('#queueStatisticsFilterPanel');
      await panel.evaluate(node=>node.hidden=false);
      assert.equal(await page.locator('.queue-statistics-section-toggle[aria-expanded="false"]').count(),5,'all statistics filter rows start collapsed');
      assert.equal(await page.locator('.queue-statistics-filter-section-content[hidden]').count(),5,'all statistics filter controls start hidden');
      const filterControlHeights=await page.locator('.queue-statistics-filter-header-actions button').evaluateAll(nodes=>nodes.map(node=>({id:node.id,height:node.getBoundingClientRect().height,width:node.getBoundingClientRect().width,borderRadius:getComputedStyle(node).borderRadius})));
      assert.ok(filterControlHeights.every(control=>control.height===36&&control.width===36&&control.borderRadius==='7px'),`filter panel icon actions use the same compact size: ${JSON.stringify(filterControlHeights)}`);
      const expandedHeights=[];
      for(const key of ['supplier_type','category','dk_code','review_officer','protocol_officer']){
        await page.locator(`[data-statistics-filter-section="${key}"] .queue-statistics-section-toggle`).click();
        const heights=await page.locator(`[data-statistics-filter-section="${key}"] .queue-statistics-filter-section-content select,[data-statistics-filter-section="${key}"] .queue-statistics-filter-section-content input:not([type="checkbox"])`).evaluateAll(nodes=>nodes.map(node=>({id:node.id||node.dataset.statisticsFilter,height:node.getBoundingClientRect().height,borderRadius:getComputedStyle(node).borderRadius})));
        expandedHeights.push(...heights);
      }
      assert.ok(expandedHeights.length>=5&&expandedHeights.every(control=>control.height>=32&&control.height<=40&&control.borderRadius==='7px'),`expanded filters keep compact controls: ${JSON.stringify(expandedHeights)}`);
      assert.equal(await page.locator('.queue-statistics-section-toggle[aria-expanded="true"]').count(),1,'opening a row collapses the previously open filter');
      await page.locator('[data-statistics-filter-section="dk_code"] .queue-statistics-section-toggle').click();
      assert.deepEqual(await page.locator('[data-statistics-filter-section="dk_code"] .queue-statistics-section-toggle').evaluate(node=>{const style=getComputedStyle(node,'::after');return{content:style.content,right:style.right}}),{content:'"⌃"',right:'10px'},'expanded statistics filter points upward at the shared right inset');
      const dkSearchLayout=await page.evaluate(()=>{
        const heading=document.querySelector('.queue-statistics-dk-heading'),input=document.querySelector('#queueStatisticsDkSearch'),clear=document.querySelector('#queueStatisticsDkClear');
        const rect=el=>{const r=el.getBoundingClientRect();return{left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width};};
        return{heading:rect(heading),input:rect(input),clear:rect(clear),accessibleName:input.getAttribute('aria-label')};
      });
      assert.ok(dkSearchLayout.input.width>=dkSearchLayout.heading.width-2,`DK search spans the available field width: ${JSON.stringify(dkSearchLayout)}`);
      assert.ok(dkSearchLayout.clear.top>=dkSearchLayout.input.bottom,`DK clear button has its own row below the search field: ${JSON.stringify(dkSearchLayout)}`);
      assert.equal(dkSearchLayout.accessibleName,'Пошук коду ДК');
      const dkCheckbox=await page.locator('#queueStatisticsDkOptions label').first().evaluate(label=>{const input=label.querySelector('input[type="checkbox"]'),textNode=[...label.childNodes].find(node=>node.nodeType===Node.TEXT_NODE&&node.textContent.trim()),range=document.createRange();range.selectNode(textNode);const text=range.getClientRects()[0],box=input.getBoundingClientRect();return{display:getComputedStyle(label).display,input:{left:box.left,right:box.right,top:box.top,width:box.width,height:box.height},text:{left:text.left,top:text.top,height:text.height},gap:text.left-box.right,centerDelta:Math.abs((box.top+box.height/2)-(text.top+text.height/2))}});
      assert.ok(dkCheckbox.display==='flex'&&dkCheckbox.input.width===15&&dkCheckbox.input.height===15&&dkCheckbox.gap>=4&&dkCheckbox.gap<=10&&dkCheckbox.centerDelta<=3,`statistics DK checkbox remains immediately left of its first-line label: ${JSON.stringify(dkCheckbox)}`);
      const dkToggle=page.locator('#queueStatisticsDkOptions label').first(),wasChecked=await dkToggle.locator('input').isChecked(),labelBox=await dkToggle.evaluate(label=>{const textNode=[...label.childNodes].find(node=>node.nodeType===Node.TEXT_NODE&&node.textContent.trim()),range=document.createRange();range.selectNode(textNode);const r=range.getClientRects()[0],outer=label.getBoundingClientRect();return{x:r.left-outer.left+r.width/2,y:r.top-outer.top+r.height/2}});
      await dkToggle.click({position:labelBox});
      assert.equal(await dkToggle.locator('input').isChecked(),!wasChecked,'clicking the DK option text toggles its checkbox');
      await dkToggle.click({position:labelBox});
      await workspace.evaluate(node=>node.classList.add('is-filter-open'));
      const panelLayout=await page.evaluate(()=>{
        const card=document.querySelector('.queue-statistics-card'),work=document.querySelector('#queueStatisticsWorkspace'),results=document.querySelector('.queue-statistics-results'),panel=document.querySelector('#queueStatisticsFilterPanel');
        const rect=el=>{const r=el.getBoundingClientRect();return{left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height};};
        const workspaceStyle=getComputedStyle(work),panelStyle=getComputedStyle(panel);
        return{viewport:document.documentElement.clientWidth,height:document.documentElement.clientHeight,scroll:document.documentElement.scrollWidth,card:rect(card),workspace:rect(work),results:rect(results),panel:rect(panel),columns:workspaceStyle.gridTemplateColumns,areas:workspaceStyle.gridTemplateAreas,panelArea:panelStyle.gridArea,panelPosition:panelStyle.position,panelHeight:panelStyle.height,panelTop:panelStyle.top,panelBottom:panelStyle.bottom,ancestors:[...function*(node){while(node){const style=getComputedStyle(node);yield{tag:node.tagName,id:node.id,position:style.position,transform:style.transform,filter:style.filter,perspective:style.perspective,contain:style.contain};node=node.parentElement}}(panel)]};
      });
      assert.ok(panelLayout.scroll<=panelLayout.viewport+2,`filter panel does not cause page overflow: ${JSON.stringify(panelLayout)}`);
      assert.ok(panelLayout.panel.left>=panelLayout.results.right-1,`filter panel does not cover the table: ${JSON.stringify(panelLayout)}`);
      assert.ok(panelLayout.panel.right<=panelLayout.viewport+1&&panelLayout.panel.left>=0,'drawer remains inside the browser viewport');
      assert.equal(panelLayout.panelPosition,'fixed','filter drawer is fixed to the viewport');
      assert.ok(panelLayout.panel.top<=1&&panelLayout.panel.bottom<=panelLayout.height-39,'filter drawer fills the viewport but stays above the Sandbox footer');
      assert.ok(panelLayout.panel.height>=panelLayout.height-44,`filter drawer keeps nearly all available viewport height: ${JSON.stringify(panelLayout)}`);
      assert.equal(await panel.locator('.queue-statistics-filter-header-actions button').count(),3,'drawer header keeps clear, apply and close actions visible');
      assert.equal(await panel.locator('.queue-statistics-filter-actions').count(),0,'drawer actions are not hidden at the bottom of the scroll area');
      const panelShot=path.join(OUT,`work-uo-${theme}-filter-panel.png`);
      await page.screenshot({path:panelShot,fullPage:true});evidence.push(panelShot);
      await page.close();
    }
    for(const theme of ['light','dark'])for(const width of [1920,1280,1120,800,520,360]){
      const page=await makeAuxPage(browser,theme,'historyView',width,1080);
      const historyRows=await page.evaluate(()=>['.history-filter-primary','.history-filter-secondary'].map(selector=>{
        const row=document.querySelector(selector),children=[...row.children],tops=children.map(node=>Math.round(node.getBoundingClientRect().top));
        return{selector,count:children.length,tops:[...new Set(tops)],width:row.clientWidth,scroll:row.scrollWidth,fields:children.map(node=>({field:node.querySelector('[data-history]')?.dataset.history||node.dataset.history||node.id||node.className,rect:(r=>({x:r.x,y:r.y,width:r.width,right:r.right}))(node.getBoundingClientRect())}))};
      }));
      assert.equal(historyRows[0].count,7,'history search row retains all seven agreed fields');
      assert.equal(historyRows[1].count,7,'history status row retains all seven agreed fields');
      const allowedResponsiveRows=width>1120?1:width>760?3:4;
      assert.ok(historyRows.every(row=>row.tops.length<=allowedResponsiveRows+1&&row.scroll<=row.width+1),`history filters wrap without overlap or horizontal overflow after search-clear wrappers are installed: ${JSON.stringify(historyRows)}`);
      const controls=await page.evaluate(()=>{
        const rect=selector=>{const r=document.querySelector(selector).getBoundingClientRect();return{x:r.x,right:r.right,width:r.width,height:r.height}};
        return{protocol:rect('[data-history="officer"]'),review:rect('#historyReviewOfficerSearch'),remarks:rect('[data-history="remarks"]'),status:rect('[data-history="status"]'),from:rect('[data-history="from"]'),to:rect('[data-history="to"]'),reset:rect('#historyReset'),viewport:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,optionsHidden:document.querySelector('#historyReviewOfficerOptions').hidden};
      });
      if(width>1120){
        assert.ok(controls.protocol.width>=88&&controls.protocol.width<=112&&controls.review.width>=88&&controls.review.width<=112,`officer search fields stay 90–110px wide at ${width}px: ${JSON.stringify(controls)}`);
        assert.ok(controls.status.width<=180&&controls.status.width>=145,`status selector remains compact but fits its longest option: ${JSON.stringify(controls)}`);
        assert.ok(controls.from.x>controls.status.x&&controls.to.x>controls.from.x,`date filters sit to the right of the decision selector: ${JSON.stringify(controls)}`);
      }
      assert.ok(controls.remarks.width>=Math.min(180,controls.viewport*.3),`remarks gets the released width: ${JSON.stringify(controls)}`);
      assert.ok(controls.reset.right<=controls.viewport+1&&controls.reset.width>=34,`clear button remains visible at the right edge: ${JSON.stringify(controls)}`);
      if(width>1120)assert.ok(controls.reset.x>=controls.to.x,`clear button remains after the date fields on wide screens: ${JSON.stringify(controls)}`);
      assert.ok(controls.scroll<=controls.viewport+1&&controls.optionsHidden,'history filters avoid horizontal page overflow and keep the officer list initially closed');
      if(width===1920){const historyShot=path.join(OUT,`application-history-${theme}-wide.png`);await page.screenshot({path:historyShot,fullPage:true});evidence.push(historyShot);}
      await page.close();
    }
    for(const theme of ['light','dark'])for(const width of [1920,1024,700,480,360]){
      const page=await makeAuxPage(browser,theme,'edrMonitoringView',width,1000);
      const edr=await page.evaluate(()=>{
        const code=document.querySelector('#edrMonitoringDk'),panel=document.querySelector('#edrMonitoringAdvanced');
        const kpis=[...document.querySelectorAll('#edrMonitoringKpis button')];
        const colors=kpis.map(node=>({key:node.dataset.freshness,color:getComputedStyle(node).borderLeftColor,width:getComputedStyle(node).borderLeftWidth}));
        return{viewport:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,insidePanel:code.closest('#edrMonitoringFilterPanel')===document.querySelector('#edrMonitoringFilterPanel'),mainRowHasCode:!!document.querySelector('.edr-monitoring-toolbar>#edrMonitoringDk'),chipsVisible:getComputedStyle(document.querySelector('#edrMonitoringChips')).display!=='none',sectionCount:document.querySelectorAll('#edrMonitoringFilterPanel [data-edr-filter-section]').length,colors};
      });
      assert.equal(edr.insidePanel,true,'DK filter stays inside the existing filters panel');
      assert.equal(edr.mainRowHasCode,false,'the DK filter no longer takes space in the main toolbar');
      assert.equal(edr.chipsVisible,false,'no separate active-filter chips row is shown');
      assert.equal(edr.sectionCount,12,'all existing EDR filter dimensions have individual sections');
      assert.equal(edr.colors.length,6,'all six freshness KPIs remain available');
      assert.ok(edr.colors.every(item=>item.width==='4px'&&item.color!=='rgba(0, 0, 0, 0)'),`freshness KPIs have colored left markers in ${theme} theme: ${JSON.stringify(edr.colors)}`);
      assert.ok(edr.scroll<=edr.viewport+2,`EDR screen has no page-level horizontal overflow at ${width}px`);
      if(width===1920){
        await page.locator('#edrMonitoringFilterSummary').click();
        assert.equal(await page.locator('#edrMonitoringAdvanced').evaluate(node=>node.open),true,'the toolbar control opens the native drawer');
        assert.equal(await page.locator('#edrMonitoringFilterPanel .filter-accordion-toggle[aria-expanded="false"]').count(),12,'all EDR filter sections start collapsed');
        const compactRows=await page.locator('#edrMonitoringFilterPanel').evaluate(panel=>({gap:getComputedStyle(panel.querySelector('.edr-monitoring-filter-fields')).rowGap,rows:[...panel.querySelectorAll('.edr-monitoring-filter-section')].map(section=>{const toggle=section.querySelector('.filter-accordion-toggle'),icon=getComputedStyle(toggle,'::after');return{section:section.getBoundingClientRect().height,toggle:toggle.getBoundingClientRect().height,icon:{content:icon.content,right:icon.right}}})}));
        assert.equal(compactRows.gap,'7px','EDR uses the same compact section gap as the application registry drawer');
        assert.ok(compactRows.rows.every(row=>Math.abs(row.toggle-42)<1&&Math.abs(row.section-44)<1&&row.icon.content==='"›"'&&row.icon.right==='10px'),`EDR collapsed rows match registry height and arrow placement: ${JSON.stringify(compactRows.rows)}`);
        assert.deepEqual(await page.locator('#edrMonitoringType').evaluate(node=>({labels:node.labels.length,labelText:node.labels[0]?.querySelector('span')?.textContent.trim(),captionClass:node.labels[0]?.querySelector('span')?.classList.contains('filter-field-caption')})),{labels:1,labelText:'Виберіть тип',captionClass:true},'the redundant EDR prompt remains the control label for assistive technology');
        await page.locator('[data-edr-filter-section="dk_code"] .filter-accordion-toggle').click();
        assert.deepEqual(await page.locator('[data-edr-filter-section="dk_code"] .filter-accordion-toggle').evaluate(node=>{const style=getComputedStyle(node,'::after');return{content:style.content,right:style.right}}),{content:'"⌃"',right:'10px'},'expanded EDR filter points upward at the shared right inset');
        const dkWidth=await page.locator('#edrMonitoringDk').evaluate(node=>node.getBoundingClientRect().width);
        assert.ok(dkWidth>=250,'expanded DK search uses the full panel width');
        await page.locator('[data-edr-filter-section="entity_type"] .filter-accordion-toggle').click();
        await page.locator('#edrMonitoringType').selectOption('individual_entrepreneur');
        await page.locator('[data-edr-filter-section="entity_type"][data-edr-filter-section] [data-edr-filter-count]').evaluate(node=>{node.textContent='1';node.hidden=false;node.closest('[data-edr-filter-section]').classList.add('filter-active')});
        await page.locator('[data-edr-filter-section="entity_type"] [data-edr-filter-clear]').evaluate(node=>node.hidden=false);
        await page.locator('#edrMonitoringFilterSummary').evaluate(node=>node.textContent='Фільтри · 1');
        const edrToggleStyles=await page.locator('#edrMonitoringFilterPanel .filter-accordion-toggle').evaluateAll(nodes=>nodes.map(node=>({width:node.getBoundingClientRect().width,height:node.getBoundingClientRect().height,radius:getComputedStyle(node).borderRadius,border:getComputedStyle(node).borderWidth})));
        assert.ok(edrToggleStyles.every(item=>item.width>=300&&Math.abs(item.height-42)<1&&item.radius==='7px'&&item.border==='0px'),`EDR accordion headings use full-width compact rows rather than inherited circular button styles: ${JSON.stringify(edrToggleStyles)}`);
        const drawer=await page.locator('#edrMonitoringFilterPanel').evaluate(node=>{const r=node.getBoundingClientRect();return{x:r.x,right:r.right,width:r.width,height:r.height,position:getComputedStyle(node).position,header:node.querySelector('.edr-monitoring-filter-header').getBoundingClientRect().height,scroll:node.querySelector('.edr-monitoring-filter-fields').scrollHeight,client:node.querySelector('.edr-monitoring-filter-fields').clientHeight,apply:!!node.querySelector('#edrMonitoringApply'),clear:!!node.querySelector('#edrMonitoringReset'),close:!!node.querySelector('#edrMonitoringClose')}});
        assert.ok(drawer.position==='fixed'&&drawer.x>=0&&drawer.right<=edr.viewport+1&&drawer.height>=999&&drawer.width<=430,`drawer stays at the browser edge and fills the viewport: ${JSON.stringify(drawer)}`);
        assert.ok(dkWidth>=250&&drawer.header>=50&&drawer.apply&&drawer.clear&&drawer.close,'drawer retains a readable DK control and top-level actions');
        const shot=path.join(OUT,`edr-monitoring-${theme}-filters-open.png`);await page.screenshot({path:shot,fullPage:true});evidence.push(shot);
      }
      await page.close();
    }
    for(const theme of ['light','dark']){
      const page=await makeAuxPage(browser,theme,'edrMonitoringView',390,420);
      await page.locator('#edrMonitoringFilterSummary').click();
      const before=await page.evaluate(()=>{const panel=document.querySelector('#edrMonitoringFilterPanel'),fields=panel.querySelector('.edr-monitoring-filter-fields'),header=panel.querySelector('.edr-monitoring-filter-header'),rect=node=>{const r=node.getBoundingClientRect();return{top:r.top,bottom:r.bottom,height:r.height}};return{panel:rect(panel),header:rect(header),fields:{scrollHeight:fields.scrollHeight,clientHeight:fields.clientHeight,overflow:getComputedStyle(fields).overflowY,scrollbarWidth:getComputedStyle(fields).scrollbarWidth,scrollbarColor:getComputedStyle(fields).scrollbarColor},rootOverflow:getComputedStyle(document.documentElement).overflow,lastSection:panel.querySelector('[data-edr-filter-section="application_to"]').getBoundingClientRect().bottom,viewport:innerHeight,scrollY}});
      assert.ok(before.fields.scrollHeight>before.fields.clientHeight&&before.fields.overflow==='auto',`short viewport scrolls the filter content internally in ${theme}: ${JSON.stringify(before)}`);
      assert.equal(before.rootOverflow,'hidden','opening the drawer prevents page scrolling underneath it');
      assert.ok(before.fields.scrollbarWidth==='thin'&&before.fields.scrollbarColor!=='auto',`filter scrollbar has a visible theme-aware track and thumb in ${theme}: ${JSON.stringify(before.fields)}`);
      assert.ok(before.lastSection>before.viewport,'last filters extend below the short viewport before scrolling');
      await page.locator('.edr-monitoring-filter-fields').evaluate(node=>node.scrollTop=node.scrollHeight);
      const after=await page.evaluate(()=>{const panel=document.querySelector('#edrMonitoringFilterPanel'),fields=panel.querySelector('.edr-monitoring-filter-fields'),header=panel.querySelector('.edr-monitoring-filter-header');return{scrollTop:fields.scrollTop,headerTop:header.getBoundingClientRect().top,headerBottom:header.getBoundingClientRect().bottom,lastSectionBottom:panel.querySelector('[data-edr-filter-section="application_to"]').getBoundingClientRect().bottom,scrollY};});
      assert.ok(after.scrollTop>0&&after.lastSectionBottom<=before.viewport,`last filter becomes reachable by scrolling inside the drawer in ${theme}: ${JSON.stringify(after)}`);
      assert.ok(Math.abs(after.headerTop-before.header.top)<1&&Math.abs(after.headerBottom-before.header.bottom)<1,`drawer title and actions stay pinned while filters scroll in ${theme}: ${JSON.stringify({before:before.header,after})}`);
      assert.equal(after.scrollY,before.scrollY,'scrolling the filter drawer does not scroll the page underneath');
      const shot=path.join(OUT,`edr-monitoring-${theme}-filters-short-viewport.png`);await page.screenshot({path:shot,fullPage:false});evidence.push(shot);
      await page.close();
    }
    for(const theme of ['light','dark'])for(const width of [1920,1536,1366,1280,1024,900]){
      const page=await makeAuxPage(browser,theme,'requestsView',width,1000);
      const layout=await page.evaluate(()=>{
        const actions=document.querySelector('.request-heading-actions'),authorities=document.querySelector('#requestAuthorityCards'),statuses=document.querySelector('#requestQuickFilters');
        const rect=node=>{const r=node.getBoundingClientRect();return{left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height};};
        return{viewport:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,actions:rect(actions),authorities:rect(authorities),statuses:rect(statuses),authorityCards:[...authorities.children].map(rect),statusCards:[...statuses.children].map(rect)};
      });
      assert.equal(layout.authorityCards.length,3,'all three organization cards are rendered');
      assert.equal(layout.statusCards.length,3,'only three status counters are rendered');
      assert.ok(layout.scroll<=layout.viewport+2,`requests page has no horizontal overflow at ${width}px`);
      if(width>=1024){
        assert.ok(layout.authorities.height<=60&&layout.statuses.height<=40&&Math.abs((layout.authorities.top+layout.authorities.bottom)/2-(layout.statuses.top+layout.statuses.bottom)/2)<2,`three organization cards and three status counters stay in one row at ${width}px: ${JSON.stringify(layout)}`);
        assert.ok(layout.authorityCards.every(card=>Math.abs(card.top-layout.authorityCards[0].top)<2&&Math.abs(card.height-layout.authorityCards[0].height)<2&&Math.abs(card.width-layout.authorityCards[0].width)<2),'organization cards have equal width and height on one row');
        if(width>1350)assert.ok(layout.statuses.left-layout.authorities.right>=20&&layout.statuses.left-layout.authorities.right<=24,`organization cards sit slightly farther left with the agreed inter-group gap: ${JSON.stringify(layout)}`);
        assert.ok(layout.statusCards.every(card=>Math.abs(card.top-layout.statusCards[0].top)<2&&Math.abs(card.height-layout.statusCards[0].height)<2),'status counters align on one row');
        assert.ok(layout.statusCards.every(card=>card.width<layout.authorityCards[0].width&&card.height<layout.authorityCards[0].height),'status counters are substantially smaller than organization cards');
      }
      const controls=await page.locator('#requestQuickFilters button').evaluateAll(nodes=>nodes.map(node=>({title:node.title,label:node.getAttribute('aria-label'),pressed:node.getAttribute('aria-pressed'),visibleText:node.innerText.trim(),tooltip:getComputedStyle(node,'::after').content})));
      assert.deepEqual(controls.map(item=>item.title),['Очікує розгляду','Задоволено','Відхилено']);
      assert.ok(controls.every(item=>item.label.startsWith(item.title+':')&&/^\d/.test(item.visibleText)&&!item.visibleText.includes(' ')),'status counters show only their number and expose full accessible labels');
      assert.equal(await page.locator('#requestsExpiredFilter,#requestsExpired').count(),0,'the expired-response KPI duplicate is absent');
      if(width===1920){
        const firstStatus=page.locator('#requestQuickFilters button').first();
        await firstStatus.focus();await page.waitForTimeout(160);
        assert.equal(await firstStatus.evaluate(node=>node.matches(':focus')&&getComputedStyle(node,'::after').visibility),'visible','tooltip is available on keyboard focus');
      }
      if(width===1920){const requestShot=path.join(OUT,`requests-${theme}-wide.png`);await page.screenshot({path:requestShot,fullPage:true});evidence.push(requestShot);}
      await page.close();
    }
    for(const count of [3,5,8]){
      const page=await makePage(browser,'light');
      await page.evaluate(count=>{
        const names=['Альфа УО','Бета УО','Гамма УО','Дельта УО','Епсилон УО','Дзета УО','Ета УО','Тета УО'];
        const table=document.querySelector('#queueStatisticsRows');
        table.innerHTML=names.slice(0,count).map((name,i)=>`<tr><th scope="row">${name}</th><td>${i}</td><td>${i}</td><td>${i}</td><td>${i}</td></tr>`).join('');
        const wrap=document.querySelector('.queue-statistics-table');wrap.classList.toggle('queue-statistics-table--scroll',count>5);
        if(count>5){const header=wrap.querySelector('thead'),firstFive=[...table.querySelectorAll('tr')].slice(0,5);wrap.style.maxHeight=`${Math.ceil(header.getBoundingClientRect().height+firstFive.reduce((sum,row)=>sum+row.getBoundingClientRect().height,0))}px`;}else wrap.style.maxHeight='';
      },count);
      const wrap=await page.locator('.queue-statistics-table').evaluate(el=>({client:el.clientHeight,scroll:el.scrollHeight,overflow:getComputedStyle(el).overflowY,visibleRows:[...el.querySelectorAll('tbody tr')].filter(row=>row.getBoundingClientRect().bottom<=el.getBoundingClientRect().bottom+1).length,headerPosition:getComputedStyle(el.querySelector('thead th')).position}));
      if(count<=5)assert.ok(wrap.scroll<=wrap.client+1,`${count} rows fit without vertical scroll`);
      else {assert.ok(wrap.scroll>wrap.client,`${count} rows use internal vertical scroll`);assert.equal(wrap.visibleRows,5,'exactly five rows are visible before scrolling');assert.equal(wrap.headerPosition,'sticky','table header stays visible while scrolling');}
      await page.close();
    }
    for(const zoom of [0.8,1,1.25,1.5]){
      // Browser zoom reduces the effective CSS viewport. Model that viewport directly so
      // responsive media queries behave as they do in a real zoomed browser window.
      const page=await makePage(browser,'dark',Math.round(1536/zoom),Math.round(864/zoom));
      const dimensions=await page.evaluate(()=>({width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,grid:getComputedStyle(document.querySelector('.work-queue-operational-grid')).gridTemplateColumns,overflow:[...document.querySelectorAll('#workQueueView *')].map(el=>({selector:el.id?`#${el.id}`:el.className&&typeof el.className==='string'?`.${el.className.trim().split(/\s+/).join('.')}`:el.tagName.toLowerCase(),left:Math.round(el.getBoundingClientRect().left),right:Math.round(el.getBoundingClientRect().right),width:Math.round(el.getBoundingClientRect().width)})).filter(item=>item.right>document.documentElement.clientWidth+2).slice(0,12)}));
      assert.ok(dimensions.scroll<=dimensions.width+2,`no page-level horizontal overflow at ${zoom*100}%: ${JSON.stringify(dimensions)}`);
      const shot=path.join(OUT,`work-uo-dark-${Math.round(zoom*100)}.png`);
      if(zoom!==1) {await page.locator('#workQueueView .work-queue-operational-grid').screenshot({path:shot});evidence.push(shot);}
      await page.close();
    }
    for(const width of [650,480,360]){
      const page=await makePage(browser,'light',width,900);
      const layout=await page.locator('#queueCategoryCards>.qualification-summary-category').evaluateAll(nodes=>({viewport:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,tops:nodes.map(node=>Math.round(node.getBoundingClientRect().top)),officerTops:[...document.querySelectorAll('#queueProtocolOfficerCards>.protocol-officer-card')].map(node=>Math.round(node.getBoundingClientRect().top)),currentOfficerTops:[...document.querySelectorAll('#queueQualificationCards>.qualification-summary-officer')].map(node=>Math.round(node.getBoundingClientRect().top)),cardRights:nodes.map(node=>Math.round(node.getBoundingClientRect().right)),cardLefts:nodes.map(node=>Math.round(node.getBoundingClientRect().left))}));
      assert.ok(layout.scroll<=layout.viewport+2,`no horizontal overflow at ${width}px: ${JSON.stringify(layout)}`);
      assert.ok(new Set(layout.tops).size>1,`categories wrap at narrow width ${width}px`);
      assert.ok(new Set(layout.officerTops).size>1&&new Set(layout.currentOfficerTops).size>1,`officer cards wrap at narrow width ${width}px`);
      await page.close();
    }
    for(const width of [1280,800,480]){
      const page=await makePage(browser,'dark',width,900);
      await page.locator('#queueStatisticsFilterPanel').evaluate(node=>node.hidden=false);
      await page.locator('#queueStatisticsWorkspace').evaluate(node=>node.classList.add('is-filter-open'));
      const layout=await page.evaluate(()=>{
        const card=document.querySelector('.queue-statistics-card'),results=document.querySelector('.queue-statistics-results'),panel=document.querySelector('#queueStatisticsFilterPanel'),viewport=document.documentElement.clientWidth;
        const rect=el=>{const r=el.getBoundingClientRect();return{left:r.left,right:r.right,top:r.top,bottom:r.bottom};};
        return{viewport,height:document.documentElement.clientHeight,scroll:document.documentElement.scrollWidth,card:rect(card),results:rect(results),panel:rect(panel),panelPosition:getComputedStyle(panel).position,panelVisibility:getComputedStyle(results).visibility};
      });
      assert.ok(layout.scroll<=layout.viewport+2,`responsive filter panel has no page overflow at ${width}px: ${JSON.stringify(layout)}`);
      assert.equal(layout.panelPosition,'fixed',`filter drawer stays attached to the browser window at ${width}px`);
      assert.ok(layout.panel.left>=0&&layout.panel.right<=layout.viewport+1,`filter drawer stays inside the viewport at ${width}px: ${JSON.stringify(layout)}`);
      assert.ok(layout.panel.top<=1&&layout.panel.bottom<=layout.height-39,`filter drawer stays above the Sandbox footer at ${width}px: ${JSON.stringify(layout)}`);
      if(width>=1200)assert.ok(layout.panel.left>=layout.results.right-1,`wide filter drawer does not cover the table at ${width}px: ${JSON.stringify(layout)}`);
      else assert.equal(layout.panelVisibility,'hidden',`table is hidden while the full-screen drawer is open at ${width}px`);
      await page.close();
    }
    console.log(JSON.stringify({result:'PASS',responsiveCases:['five categories in one row: light/dark','five categories wrap: 650px/480px/360px','filter panel no-overlap at 1920/1280/800/480px','history officer fields 90–110px, compact decisions, dates right of status, flexible remarks: 1920/1280/1120/800/520/360px light/dark','EDR full-height right drawer, 12 sections, top actions, no chip row, DK filter and six freshness KPI markers: 1920/1024/700/480/360px light/dark','requests: three organization cards plus three status counters in one row at 1920/1536/1366/1280/1024, adaptive 900px, light/dark','3 rows','5 rows','8 rows','80%','100%','125%','150%'],screenshots:evidence},null,2));
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
