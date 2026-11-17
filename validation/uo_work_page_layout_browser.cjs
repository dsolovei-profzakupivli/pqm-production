const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const {chromium}=require(require.resolve('playwright',{paths:['C:/Users/User/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules']}));

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
    document.querySelector('#queueProtocolCategoryCards').innerHTML=['Ліки','Інше','Обладнання'].map((name,i)=>`<button class="qualification-summary-officer qualification-summary-category"><span>${name}</span><strong>${[12,9,7][i]}</strong><small>категорія</small></button>`).join('');
    document.querySelector('#queueCategoryCards').innerHTML=['Ліки','Інше','Обладнання'].map((name,i)=>`<button class="qualification-summary-officer qualification-summary-category"><span>${name}</span><strong>${[8,5,3][i]}</strong><small>категорія</small></button>`).join('');
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
  },{theme,officers});
  return page;
}

(async()=>{
  fs.mkdirSync(OUT,{recursive:true});
  const browser=await chromium.launch({headless:true,executablePath:'C:/Users/User/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe'});
  try{
    const evidence=[];
    for(const theme of ['light','dark']){
      const page=await makePage(browser,theme);
      const left=await page.locator('.queue-protocol-summary').boundingBox();
      const right=await page.locator('.queue-current-summary').boundingBox();
      assert.ok(Math.abs(left.y-right.y)<2,'top summary blocks align');
      const leftCategories=await page.locator('#queueProtocolCategoryCards').boundingBox();
      const rightCategories=await page.locator('#queueCategoryCards').boundingBox();
      assert.ok(Math.abs(leftCategories.y-rightCategories.y)<2,'category cards begin on the same line');
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
      const actions=await page.locator('.queue-statistics-actions').boundingBox();
      const title=await page.locator('.queue-statistics-heading h2').boundingBox();
      assert.ok(actions.x>title.x+title.width,'statistics actions stay on the title row at right');
      const controls=await page.locator('.queue-statistics-controls').evaluate(el=>getComputedStyle(el).display);
      assert.equal(controls,'flex');
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
    console.log(JSON.stringify({result:'PASS',responsiveCases:['wide light','wide dark','3 rows','5 rows','8 rows','100%','125%','150%'],screenshots:evidence},null,2));
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
