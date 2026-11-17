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
    document.querySelector('#queueStatisticsKpis').innerHTML='<button class="ghost publication-kpi admitted"><span>Допущено</span><strong>12</strong></button><button class="ghost publication-kpi rejected"><span>Відхилено</span><strong>4</strong></button><button class="ghost publication-kpi pending"><span>Очікує рішення</span><strong>7</strong></button>';
    document.querySelector('#queueStatisticsRows').innerHTML=Array.from({length:8},(_,i)=>`<tr><th scope="row">${officers[i%officers.length]}</th><td><button class="ghost publication-kpi">${i}</button></td><td><button class="ghost publication-kpi">${i+1}</button></td><td><button class="ghost publication-kpi">${i+2}</button></td><td><button class="ghost publication-kpi">${i+3}</button></td></tr>`).join('');
    const statisticsTable=document.querySelector('.queue-statistics-table');
    statisticsTable.classList.add('queue-statistics-table--scroll');
    const tableHeader=statisticsTable.querySelector('thead'),firstFive=[...document.querySelectorAll('#queueStatisticsRows tr')].slice(0,5);
    statisticsTable.style.maxHeight=`${Math.ceil(tableHeader.getBoundingClientRect().height+firstFive.reduce((sum,row)=>sum+row.getBoundingClientRect().height,0))}px`;
    document.querySelector('#queueStatisticsFrom').value='2026-10-01';
    document.querySelector('#queueStatisticsTo').value='2026-10-31';
    document.querySelector('#queueStatisticsGroup').value='review_officer';
    document.querySelector('[data-statistics-filter="category"]').innerHTML='<option value="">Усі</option><option>Їжа</option>';
    document.querySelector('[data-statistics-filter="review_officer"]').innerHTML='<option value="">Усі</option><option>Дмитро САВВА</option>';
    document.querySelector('[data-statistics-filter="protocol_officer"]').innerHTML='<option value="">Усі</option><option>Олена ЄРЬОМІНА</option>';
    document.querySelector('#queueStatisticsDkOptions').innerHTML=['02100000-6','03000000-1','45000000-7'].map(value=>`<label><input type="checkbox"> ${value}</label>`).join('');
  },{theme,officers});
  return page;
}

(async()=>{
  fs.mkdirSync(OUT,{recursive:true});
  const browser=await chromium.launch({headless:true,executablePath:process.env.PQM_CHROMIUM_EXECUTABLE||undefined});
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
      assert.equal(layout.statsAlign,'start','statistics retains its natural compact height instead of stretching');
      assert.ok(layout.statistics.height<layout.left.height,'statistics stays compact while the left column continues below it');
      assert.ok(layout.left.width/layout.statistics.width>0.62&&layout.left.width/layout.statistics.width<0.72,`wide layout keeps approximately 40/60 columns: ${JSON.stringify(layout)}`);
      const protocolHeader=await page.evaluate(()=>{
        const rect=selector=>{const r=document.querySelector(selector).getBoundingClientRect();return{left:r.left,right:r.right};};
        return{title:rect('.queue-protocol-summary h2'),period:rect('.queue-protocol-summary .protocol-period'),total:rect('#queueProtocolTotal'),card:rect('.queue-protocol-summary')};
      });
      assert.ok(protocolHeader.period.left>=protocolHeader.title.right+8,'protocol dates and search sit slightly to the right of the title');
      assert.ok(protocolHeader.card.right-protocolHeader.total.right<20,'protocol total stays close to the card right edge');
      for(const selector of ['#queueProtocolCategoryCards>.qualification-summary-category','#queueCategoryCards>.qualification-summary-category']){
        const positions=await page.locator(selector).evaluateAll(nodes=>nodes.map(node=>({name:node.textContent.trim(),top:node.getBoundingClientRect().top,left:node.getBoundingClientRect().left,width:node.getBoundingClientRect().width,background:getComputedStyle(node).backgroundColor,border:getComputedStyle(node).borderTopColor,borderWidth:getComputedStyle(node).borderLeftWidth})));
        assert.equal(positions.length,5,`${selector} renders all five categories`);
        assert.ok(positions.every(item=>Math.abs(item.top-positions[0].top)<2),`${selector} keeps all five categories on one row: ${JSON.stringify(positions)}`);
        assert.ok(positions.every(item=>item.width>0&&item.borderWidth==='1px'),`${selector} cards have compact widths and thin outlines`);
        if(theme==='light')assert.ok(positions.every(item=>item.background==='rgb(238, 243, 255)'&&item.border==='rgb(134, 168, 223)'),`${selector} uses the approved light-blue category palette: ${JSON.stringify(positions)}`);
        else assert.ok(positions.every(item=>item.background==='rgb(28, 53, 81)'&&item.border==='rgb(75, 121, 168)'),`${selector} keeps dark-blue fills with blue outlines: ${JSON.stringify(positions)}`);
      }
      const officerPalette=await page.locator('#queueProtocolOfficerCards>.protocol-officer-card:not([data-protocol-officer="Не призначено"])').first().evaluate(node=>({background:getComputedStyle(node).backgroundColor,border:getComputedStyle(node).borderTopColor,borderWidth:getComputedStyle(node).borderLeftWidth}));
      assert.equal(officerPalette.borderWidth,'1px','officer cards use a thin outline');
      if(theme==='light')assert.deepEqual(officerPalette,{background:'rgb(237, 246, 232)',border:'rgb(141, 182, 122)',borderWidth:'1px'},'light officer cards use the approved green palette');
      else assert.deepEqual(officerPalette,{background:'rgb(23, 62, 56)',border:'rgb(63, 123, 104)',borderWidth:'1px'},'dark officer cards retain green fills with green outlines');
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
      assert.equal(toolbar.length,6,'statistics toolbar contains dates, filters, grouping, search and reset');
      assert.ok(toolbar.every(item=>Math.abs(item.top-toolbar[0].top)<2),`all toolbar controls share one row at wide width: ${JSON.stringify(toolbar)}`);
      assert.ok(toolbar.every((item,index)=>index===0||item.left>=toolbar[index-1].right-1),`toolbar controls keep the requested order: ${JSON.stringify(toolbar)}`);
      const typeOptions=await page.locator('[data-statistics-filter="supplier_type"] option').evaluateAll(nodes=>nodes.map(option=>[option.value,option.textContent.trim()]));
      assert.deepEqual(typeOptions,[['','Усі'],['individual_entrepreneur','ФОП'],['legal_entity','ЮО та інші'],['foreign_legal_entity','Нерезидент'],['unknown','Потребує перевірки']]);
      const firstFilterLabel=await page.locator('.queue-statistics-filter-fields label').first().textContent();
      assert.match(firstFilterLabel,/Тип/,'supplier type is the first filter in the side panel');
      const cardPalette=await page.locator('.queue-statistics-card').evaluate(el=>({background:getComputedStyle(el).backgroundColor,border:getComputedStyle(el).borderTopColor}));
      if(theme==='light')assert.deepEqual(cardPalette,{background:'rgb(240, 246, 255)',border:'rgb(141, 180, 229)'},'light statistics card has the approved blue tint');
      else assert.deepEqual(cardPalette,{background:'rgb(32, 54, 80)',border:'rgb(100, 136, 181)'},'dark statistics card has the approved blue tint');
      const controls=await page.locator('.queue-statistics-controls').evaluate(el=>getComputedStyle(el).display);
      assert.equal(controls,'flex');
      const controlHeights=await page.locator('#queueProtocolFrom,#queueProtocolTo,#queueProtocolApply,#queueStatisticsFrom,#queueStatisticsTo,#queueStatisticsFilterToggle,#queueStatisticsGroup,#queueStatisticsSearch,#queueStatisticsReset').evaluateAll(nodes=>nodes.map(node=>({id:node.id,height:node.getBoundingClientRect().height,borderRadius:getComputedStyle(node).borderRadius})));
      assert.ok(controlHeights.every(control=>control.height===34&&control.borderRadius==='7px'),`page controls share a 34px height and matching corners: ${JSON.stringify(controlHeights)}`);
      const kpis=await page.locator('#queueStatisticsKpis button').evaluateAll(nodes=>nodes.map(node=>({bg:getComputedStyle(node).backgroundColor,color:getComputedStyle(node).color,border:getComputedStyle(node).borderTopColor})));
      assert.equal(kpis.length,3);
      if(theme==='dark'){
        assert.deepEqual(kpis.map(item=>item.bg),['rgb(23, 62, 56)','rgb(72, 41, 50)','rgb(68, 59, 38)']);
        assert.deepEqual(kpis.map(item=>item.color),['rgb(237, 243, 252)','rgb(237, 243, 252)','rgb(237, 243, 252)']);
        const tableText=await page.locator('.queue-statistics-table td button').first().evaluate(el=>getComputedStyle(el).color);
        assert.equal(tableText,'rgb(237, 243, 252)','dark table numbers remain readable');
      }else {
        assert.deepEqual(kpis.map(item=>item.bg),['rgb(229, 246, 236)','rgb(253, 232, 231)','rgb(255, 244, 212)']);
        assert.equal(kpis[1].color,'rgb(0, 0, 0)','light rejected KPI text and numbers are black');
        assert.equal(kpis[1].border,'rgb(233, 165, 160)','light rejected KPI uses the approved red border');
        const leftRejected=await page.locator('#queuePublicationControl .publication-kpi--rejected').evaluate(el=>({bg:getComputedStyle(el).backgroundColor,color:getComputedStyle(el).color,border:getComputedStyle(el).borderTopColor}));
        assert.deepEqual(leftRejected,{bg:'rgb(253, 232, 231)',color:'rgb(0, 0, 0)',border:'rgb(233, 165, 160)'},'left rejected KPI matches the approved light red style');
      }
      const screenshot=path.join(OUT,`work-uo-${theme}-wide.png`);
      await page.locator('#workQueueView .work-queue-operational-grid').screenshot({path:screenshot});evidence.push(screenshot);
      const workspace=page.locator('#queueStatisticsWorkspace'),panel=page.locator('#queueStatisticsFilterPanel');
      await panel.evaluate(node=>node.hidden=false);
      const filterControlHeights=await page.locator('.queue-statistics-filter-fields select,#queueStatisticsDkSearch,#queueStatisticsFilterApply,#queueStatisticsFilterClear').evaluateAll(nodes=>nodes.map(node=>({id:node.id||node.dataset.statisticsFilter||node.textContent.trim(),height:node.getBoundingClientRect().height,borderRadius:getComputedStyle(node).borderRadius})));
      assert.ok(filterControlHeights.every(control=>control.height===34&&control.borderRadius==='7px'),`filter panel controls use the same size: ${JSON.stringify(filterControlHeights)}`);
      await workspace.evaluate(node=>node.classList.add('is-filter-open'));
      const panelLayout=await page.evaluate(()=>{
        const card=document.querySelector('.queue-statistics-card'),work=document.querySelector('#queueStatisticsWorkspace'),results=document.querySelector('.queue-statistics-results'),panel=document.querySelector('#queueStatisticsFilterPanel');
        const rect=el=>{const r=el.getBoundingClientRect();return{left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height};};
        const workspaceStyle=getComputedStyle(work),panelStyle=getComputedStyle(panel);
        return{viewport:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,card:rect(card),workspace:rect(work),results:rect(results),panel:rect(panel),columns:workspaceStyle.gridTemplateColumns,areas:workspaceStyle.gridTemplateAreas,panelArea:panelStyle.gridArea,panelPosition:panelStyle.position};
      });
      assert.ok(panelLayout.panel.right<=panelLayout.card.right+1,`filter panel stays within the card's right edge: ${JSON.stringify(panelLayout)}`);
      assert.ok(panelLayout.scroll<=panelLayout.viewport+2,`filter panel does not cause page overflow: ${JSON.stringify(panelLayout)}`);
      assert.ok(panelLayout.panel.left>=panelLayout.results.right-1,`filter panel does not cover the table: ${JSON.stringify(panelLayout)}`);
      assert.equal(await panel.evaluate(node=>getComputedStyle(node).position),'static','filter panel participates in layout instead of overlaying the table');
      const panelShot=path.join(OUT,`work-uo-${theme}-filter-panel.png`);
      await page.locator('#workQueueView .work-queue-operational-grid').screenshot({path:panelShot});evidence.push(panelShot);
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
    for(const zoom of [1,1.25,1.5]){
      // Browser zoom reduces the effective CSS viewport. Model that viewport directly so
      // responsive media queries behave as they do in a real zoomed browser window.
      const page=await makePage(browser,'dark',Math.round(1536/zoom),Math.round(864/zoom));
      const dimensions=await page.evaluate(()=>({width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,grid:getComputedStyle(document.querySelector('.work-queue-operational-grid')).gridTemplateColumns,overflow:[...document.querySelectorAll('#workQueueView *')].map(el=>({selector:el.id?`#${el.id}`:el.className&&typeof el.className==='string'?`.${el.className.trim().split(/\s+/).join('.')}`:el.tagName.toLowerCase(),left:Math.round(el.getBoundingClientRect().left),right:Math.round(el.getBoundingClientRect().right),width:Math.round(el.getBoundingClientRect().width)})).filter(item=>item.right>document.documentElement.clientWidth+2).slice(0,12)}));
      assert.ok(dimensions.scroll<=dimensions.width+2,`no page-level horizontal overflow at ${zoom*100}%: ${JSON.stringify(dimensions)}`);
      const shot=path.join(OUT,`work-uo-dark-${Math.round(zoom*100)}.png`);
      if(zoom>1) {await page.locator('#workQueueView .work-queue-operational-grid').screenshot({path:shot});evidence.push(shot);}
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
        return{viewport,scroll:document.documentElement.scrollWidth,card:rect(card),results:rect(results),panel:rect(panel)};
      });
      const sideBySide=layout.panel.left>=layout.results.right-1||layout.panel.right<=layout.results.left+1;
      const stacked=layout.panel.bottom<=layout.results.top+1||layout.panel.top>=layout.results.bottom-1;
      assert.ok(layout.scroll<=layout.viewport+2,`responsive filter panel has no page overflow at ${width}px: ${JSON.stringify(layout)}`);
      assert.ok(layout.panel.left>=layout.card.left&&layout.panel.right<=layout.card.right+1,`responsive filter panel stays inside the statistics card at ${width}px: ${JSON.stringify(layout)}`);
      assert.ok(sideBySide||stacked,`responsive filter panel does not cover results at ${width}px: ${JSON.stringify(layout)}`);
      await page.close();
    }
    console.log(JSON.stringify({result:'PASS',responsiveCases:['five categories in one row: light/dark','five categories wrap: 650px/480px/360px','filter panel no-overlap at 1920/1280/800/480px','3 rows','5 rows','8 rows','100%','125%','150%'],screenshots:evidence},null,2));
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
