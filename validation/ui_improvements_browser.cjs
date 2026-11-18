/* Real Chromium, full markup and styles, synthetic read-only request adapter. */
const fs=require('node:fs'),assert=require('node:assert/strict'),path=require('node:path');
const {chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..'),OUT=process.env.PQM_UI_EVIDENCE_DIR||fs.mkdtempSync(path.join(require('node:os').tmpdir(),'pqm-ui-evidence-'));
const read=name=>fs.readFileSync(path.join(ROOT,name),'utf8');
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.PQM_TEST_BROWSER?{executablePath:process.env.PQM_TEST_BROWSER}:{})});const page=await browser.newPage({viewport:{width:1440,height:1000}});
 const errors=[];page.on('pageerror',e=>errors.push(String(e)));await page.route('**/*',route=>route.abort());
 try{
  await page.setContent(read('index.html').replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,''));
  for(const name of ['styles.css','filters.css','modules.css','schema_ui.css','ui_improvements.css','sandbox_theme.css','ui_final.css','ui_tz2.css','theme.css'])await page.addStyleTag({content:read(name)});
  await page.evaluate(()=>{
   document.querySelector('#loginGate').hidden=true;document.querySelector('#applicationShell').hidden=false;
   document.body.dataset.authRole='admin';
   document.querySelector('#mainNav').innerHTML='<button id="requestsNav">Звернення замовників</button><button id="operationalTasksNav">Операційні задачі</button>';
   window.API='/api';window.currentMe={permissions:{'tasks.read':true,'appeals.read':true}};
   window.$=s=>document.querySelector(s);window.operationalTaskTimer=undefined;
   window.authReady=Promise.resolve(currentMe);window.requestsPage=3;window.requestsTimer=undefined;window.selectedRequestAuthority='';window.reloads=0;window.toastLog=[];
   window.toast=s=>toastLog.push(s);window.loadViolationReports=()=>{reloads++};
   window.esc=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
   window.fixtureCounts={tasks:27,appeals:4};window.fixtureCalls=[];
   window.request=async(url,options={})=>{fixtureCalls.push(url);if(options.method&&options.method!=='GET')throw Error('Unexpected write');
    if(url.endsWith('/summary'))return{count:url.includes('operational')?fixtureCounts.tasks:fixtureCounts.appeals};return{tables:{}}};
   window.clipboardValue='';Object.defineProperty(navigator,'clipboard',{value:{writeText:async value=>{clipboardValue=value}},configurable:true});
   document.querySelector('#officerCards').innerHTML=['Т. Федченко','Д. Савва','О. Єрьоміна'].map(n=>`<button class="officer-card"><span>${n}</span><strong>72</strong></button>`).join('');
   window.showFixture=name=>{document.querySelectorAll('main').forEach(n=>n.hidden=n.id!==name)};
   showFixture('frameworkAnalyticsView');
   document.getElementById('refAmcuStatus').textContent='12 345 записів · 17.10.2026 11:05';
  });
  await page.addScriptTag({content:read('ui_improvements.js')});
  const app=read('app.js'),a=app.indexOf('function frameworkProzorroLink('),b=app.indexOf('function registryExportUrl(',a);
  await page.addScriptTag({content:app.slice(a,b)});
  await page.addScriptTag({content:app.split(/\r?\n/).find(line=>line.startsWith('function resetOperationalKpiFilters('))});
  await page.evaluate(()=>{document.querySelector('#frameworksBody').innerHTML='<tr><td>☑</td><td>44530000-4</td><td>'+frameworkProzorroLink({id:'technical-id',pretty_id:'UA-F-2020-12-15-000001-a'})+'</td><td>Довга назва категорії</td>'+Array.from({length:6},()=>'<td>12</td>').join('')+'</tr>'});
  await page.addScriptTag({content:read('table_widths_ui.js')});
  await page.addScriptTag({content:read('ui_improvements_boot.js')});
  await page.locator('#requestsNav .action-count-badge').waitFor();
  assert.equal(await page.locator('#operationalTasksNav .action-count-badge').textContent(),'27');
  assert.equal(await page.locator('#requestsNav .action-count-badge').textContent(),'4');
  for(const dark of [false,true])for(const mode of ['icon','icon-text'])for(const count of [1,9,27,137]){
    await page.evaluate(({dark,mode,count})=>{document.documentElement.dataset.pqmEnvironment=dark?'sandbox':'';const button=document.getElementById('requestsNav');button.className=mode==='icon'?'main-nav-icon':'main-nav-icon-text';button.innerHTML='<svg width="19" height="19"></svg>'+(mode==='icon-text'?'<span>Звернення замовників</span>':'');fixtureCounts.appeals=count;window.dispatchEvent(new Event('focus'))},{dark,mode,count});
    await page.waitForFunction(count=>document.querySelector('#requestsNav .action-count-badge')?.textContent===String(count),count);
    const boxes=await page.locator('#requestsNav').evaluate(n=>({width:n.clientWidth,scroll:n.scrollWidth,items:[...n.children].map(c=>{const r=c.getBoundingClientRect();return{x:r.x,right:r.right,y:r.y,height:r.height}})}));
    assert(boxes.width>=boxes.scroll);assert(boxes.items.at(-1).x>=boxes.items[0].right);assert(Math.abs((boxes.items.at(-1).y+10)-(boxes.items[0].y+boxes.items[0].height/2))<3);
  }
  for(const id of ['requestsNav','operationalTasksNav'])for(const mode of ['icon','icon-text'])for(const count of [3,0,null,27]){
   await page.evaluate(({id,mode,count})=>{const n=document.getElementById(id);n.innerHTML='<svg width="19" height="19"></svg>'+(mode==='icon-text'?'<span>Назва вкладки</span>':'');fixtureCounts[id==='requestsNav'?'appeals':'tasks']=count;window.dispatchEvent(new Event('focus'))},{id,mode,count});
   await page.waitForFunction(({id,count})=>{const b=document.querySelector('#'+id+' .action-count-badge');return b&&(count>0?b.textContent===String(count):b.hidden)},{id,count});
   for(const part of ['svg','span','.action-count-badge']){
    if(part==='span'&&mode==='icon'||part==='.action-count-badge'&&!(count>0))continue;
    const state=await page.evaluate(({id,part})=>{
     const ids=id==='requestsNav'?['requestsSearch','requestsReason','requestsDateFrom','requestsDateTo']:['operationalTaskSearch','operationalTaskType','operationalTaskOfficer','operationalTaskDateFrom'];
     for(const key of ids){const n=document.getElementById(key);if(n.tagName==='SELECT'&&!n.querySelector('[value="old"]'))n.add(new Option('old','old'));n.value=n.type==='date'?'2026-10-01':'old'}
     document.getElementById('operationalTaskStatus').value='completed';requestsPage=8;selectedRequestAuthority='old';PqmUi.responseExpired=false;
     let callbacks=0;document.getElementById(id).onclick=()=>callbacks++;
     document.querySelector('#'+id+' '+part).dispatchEvent(new MouseEvent('click',{bubbles:true}));
     return {callbacks,values:ids.map(key=>document.getElementById(key).value),status:document.getElementById('operationalTaskStatus').value,page:requestsPage,authority:selectedRequestAuthority,expired:PqmUi.responseExpired};
    },{id,part});
    assert.equal(state.callbacks,1);
    if(count>0){assert(state.values.every(x=>x===''));if(id==='requestsNav'){assert.equal(state.page,1);assert.equal(state.authority,'40996564');assert.equal(state.expired,true)}else assert.equal(state.status,'needs_action')}
    else{assert(state.values.every(Boolean));assert.equal(state.page,8);assert.equal(state.status,'completed');assert.equal(state.expired,false)}
   }
  }
  await page.evaluate(()=>{document.getElementById('requestsSearch').value='старий фільтр';PqmUi.responseExpired=false});
  await page.locator('#requestsNav .action-count-badge').click();assert.equal(await page.locator('#requestsSearch').inputValue(),'');assert.equal(await page.evaluate(()=>PqmUi.responseExpired),true);assert.equal(await page.evaluate(()=>selectedRequestAuthority),'40996564');assert.equal(await page.evaluate(()=>requestsPage),1);
  await page.locator('[data-copy-framework-number]').click();
  assert.equal(await page.evaluate(()=>clipboardValue),'UA-F-2020-12-15-000001-a');
  assert.equal(await page.evaluate(()=>toastLog.at(-1)),'Номер відбору скопійовано');
  assert.equal(new URL(await page.locator('.framework-number a').getAttribute('href')).pathname,'/uk/framework/UA-F-2020-12-15-000001-a');
  await page.evaluate(()=>{const row=document.querySelector('#frameworksBody tr').cloneNode(true);row.querySelector('.framework-number a').textContent='UA-F-1';document.querySelector('#frameworksBody').append(row)});
  const aligned=await page.locator('.copy-framework-number').evaluateAll(nodes=>nodes.map(n=>({right:n.getBoundingClientRect().right,gap:n.closest('td').getBoundingClientRect().right-n.getBoundingClientRect().right})));
  assert(Math.abs(aligned[0].right-aligned[1].right)<1);assert(aligned.every(n=>n.gap>=6&&n.gap<=9));
  const count=await page.locator('.pqm-clear-wrap').count();assert(count>=12);
  for(let i=0;i<count;i++)await page.evaluate(i=>{const w=document.querySelectorAll('.pqm-clear-wrap')[i],input=w.querySelector('input'),other=document.querySelector('#frameworksDk');
   other.value='4453';input.value='Текст';input.dispatchEvent(new Event('input',{bubbles:true}));
   if(w.querySelector('button').hidden)throw Error('Clear absent');w.querySelector('button').click();
   if(input.value||!w.querySelector('button').hidden||other.value!=='4453')throw Error('Clear changed other filter');},i);
  await page.evaluate(()=>showFixture('requestsView'));
  assert.equal(await page.locator('#requestsExpiredFilter,#requestsExpired').count(),0,'the duplicate expired-response KPI is absent');
  await page.evaluate(()=>{PqmUi.responseExpired=false;requestsPage=8;selectedRequestAuthority='old';fixtureCounts.appeals=4;window.dispatchEvent(new Event('focus'))});
  await page.waitForFunction(()=>document.querySelector('#requestsNav .action-count-badge')?.textContent==='4');
  await page.locator('#requestsNav .action-count-badge').click();
  assert.equal(await page.evaluate(()=>PqmUi.responseExpired),true);assert.equal(await page.evaluate(()=>requestsPage),1);assert.equal(await page.evaluate(()=>selectedRequestAuthority),'40996564');
  const appSource=read('app.js'),loaderStart=appSource.indexOf('async function loadViolationReports(){'),loaderEnd=appSource.indexOf('\nconst internalDecisionLabels',loaderStart);
  assert(loaderStart>=0&&loaderEnd>loaderStart,'real complaints list loader is available for the UI fixture');
  const quickFilterHandler=appSource.match(/\$\('#requestQuickFilters'\)\.onclick=e=>\{[^}]+\}/)?.[0];assert(quickFilterHandler,'real complaints status-counter handler is available');
  await page.evaluate(()=>{
   window.requestsPage=1;window.requestsPages=1;window.violationReports=[];window.requestsPolling=null;window.requestsRefreshState={running:false,starting:false};window.selectedRequestAuthority='';window.requestFilterCalls=[];window.$$=selector=>[...document.querySelectorAll(selector)];
   window.esc=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('\"','&quot;');
   window.displayDate=value=>String(value||'—');window.requestLabel=value=>String(value||'—');window.requestStatusClass=()=> 'pending';window.requestDeadline=()=>({html:'—'});window.requestTenderLinks=()=>'';window.requestScenarioCell=()=>'';window.requestBlockingBadge=()=>'';window.violationProtocolCell=()=>'';
   window.requestStatusLabels={pending:'Очікує розгляду',satisfied:'Задоволено',declined:'Відхилено'};window.requestReasonLabels={contractBreach:'Порушення'};document.querySelector('#requestsStatus').innerHTML='<option value="">Усі статуси</option><option value="pending">Очікує розгляду</option><option value="satisfied">Задоволено</option><option value="declined">Відхилено</option>';window.populateRequestSelect=(selector,values,labels,empty)=>{const select=$(selector),current=select.value;select.innerHTML=`<option value="">${empty}</option>`+(values||[]).map(value=>`<option value="${value}">${requestLabel(value,labels)}</option>`).join('');select.value=current};window.renderRequestAuthorityCards=()=>{};window.updateRequestsRefreshAvailability=()=>{};window.reloadOpenViolationReportDetail=async()=>{};
   window.request=async url=>{if(url.endsWith('/summary'))return{count:url.includes('operational')?fixtureCounts.tasks:fixtureCounts.appeals};if(!url.startsWith('/api/violation-reports?'))return{};requestFilterCalls.push(url);const status=new URL(url,'http://localhost').searchParams.get('status');const items=!status||status==='pending'?[{id:'fixture-1',report_id:'UA-D-FIXTURE',date_published:'2026-11-10',author_name:'Тестовий замовник',author_code:'00000000',defendant_name:'Тестовий постачальник',defendant_code:'11111111',reason:'contractBreach',status:'pending',defendant_statements:[]}]:[];return{items,pages:1,pending:1,satisfied:0,declined:0,statuses:[],reasons:[],authorities:[],sync:{running:false},total:items.length}};
  });
  await page.addScriptTag({content:appSource.slice(loaderStart,loaderEnd)});
  await page.addScriptTag({content:quickFilterHandler+';'});
  await page.locator('#requestQuickFilters [data-status="pending"]').click();
  await page.waitForFunction(()=>!document.querySelector('#requestsBody').textContent.includes('Завантаження'));
  const filteredTable=await page.locator('#requestsBody').innerText();assert.match(filteredTable,/UA-D-FIXTURE/,`filtered response row appears in the table after loading: ${filteredTable}`);
  assert.equal(await page.evaluate(()=>new URL(requestFilterCalls.at(-1),'http://localhost').searchParams.get('status')),'pending');
  assert.equal(await page.locator('#requestQuickFilters [data-status="pending"]').getAttribute('aria-pressed'),'true');
  for(const theme of ['light','dark']){await page.evaluate(theme=>{document.documentElement.dataset.theme=theme;if(theme==='dark')document.documentElement.dataset.pqmEnvironment='sandbox';else delete document.documentElement.dataset.pqmEnvironment},theme);if(theme==='light'){const colors=await page.locator('#requestQuickFilters button').evaluateAll(nodes=>nodes.map(node=>({background:getComputedStyle(node).backgroundColor,border:getComputedStyle(node).borderTopColor,color:getComputedStyle(node).color})));assert.deepEqual(colors,[{background:'rgb(255, 231, 168)',border:'rgb(189, 139, 22)',color:'rgb(31, 41, 51)'},{background:'rgb(229, 246, 236)',border:'rgb(119, 173, 141)',color:'rgb(31, 41, 51)'},{background:'rgb(253, 232, 231)',border:'rgb(233, 165, 160)',color:'rgb(0, 0, 0)'}],'light status counters match the Work UO KPI palette with black text on light red');}await page.screenshot({path:path.join(OUT,`requests-${theme}-filtered-table.png`),fullPage:true})}
  await page.locator('#requestQuickFilters [data-status="pending"]').click();
  await page.waitForFunction(()=>document.querySelector('#requestsBody tr')?.textContent.includes('UA-D-FIXTURE'));
  assert.equal(await page.evaluate(()=>new URL(requestFilterCalls.at(-1),'http://localhost').searchParams.get('status')),'');
  assert.equal(await page.locator('#requestQuickFilters [data-status="pending"]').getAttribute('aria-pressed'),'false');
  if(process.env.PQM_REQUESTS_UI_ONLY==='1'){assert.deepEqual(errors,[]);console.log('REQUESTS_FILTERED_TABLE=PASS');return}
  await page.evaluate(()=>showFixture('historyView'));
  const historyFields=await page.locator('#historyFilters input:not([type=date])').count();assert.equal(historyFields,10);
  const visibleHistoryFields=page.locator('#historyFilters input:not([type=date]):visible');assert.equal(await visibleHistoryFields.count(),9);
  for(let i=0;i<9;i++)await visibleHistoryFields.nth(i).fill('значення '+i);
  for(let i=0;i<9;i++){
    const field=page.locator('#historyFilters input:not([type=date])').nth(i);
    await field.locator('..').locator('.pqm-search-clear').click();assert.equal(await field.inputValue(),'');
    for(let j=i+1;j<9;j++)assert.equal(await visibleHistoryFields.nth(j).inputValue(),'значення '+j);
  }
  await page.evaluate(()=>{fixtureCounts.appeals=0;window.dispatchEvent(new Event('focus'))});
  await page.waitForFunction(()=>document.querySelector('#requestsNav .action-count-badge').hidden);
  await page.evaluate(()=>{currentMe.permissions['tasks.read']=false;window.dispatchEvent(new Event('focus'))});
  await page.waitForFunction(()=>document.querySelector('#operationalTasksNav .action-count-badge').hidden);
  await page.evaluate(()=>{currentMe.permissions['tasks.read']=true;window.dispatchEvent(new Event('focus'))});
  await page.waitForFunction(()=>!document.querySelector('#operationalTasksNav .action-count-badge').hidden);
  for(const dark of [false,true]){
   await page.evaluate(dark=>{if(dark)document.documentElement.dataset.pqmEnvironment='sandbox';else delete document.documentElement.dataset.pqmEnvironment},dark);
   for(const width of [1920,1440,768,390]){
    await page.setViewportSize({width,height:1000});
    await page.evaluate(()=>showFixture('applicationsView'));await page.waitForTimeout(80);
    const metrics=await page.locator('#applicationsView .heading-metrics').boundingBox(),actions=await page.locator('#applicationsView .heading-actions').boundingBox();
    assert(metrics&&actions);assert(actions.y>=metrics.y+metrics.height-1||metrics.y>=actions.y+actions.height-1||actions.x>=metrics.x+metrics.width-1||metrics.x>=actions.x+actions.width-1,'KPI/actions overlap');
    if(width===1440||width===390)await page.screenshot({path:path.join(OUT,`applications-${dark?'dark':'light'}-${width}.png`)});
    await page.evaluate(()=>showFixture('frameworkAnalyticsView'));await page.waitForTimeout(80);
    assert.equal(await page.locator('#frameworksBody td').first().evaluate(n=>getComputedStyle(n).fontSize),'13px');
    await page.locator('.frameworks-toolbar .system-width-button').waitFor();
    assert(await page.locator('.frameworks-toolbar').evaluate(n=>[...n.children].filter(c=>!c.hidden&&getComputedStyle(c).display!=='none').every(c=>{const r=c.getBoundingClientRect();return r.x>=0&&r.right<=window.innerWidth})), 'Framework control clipped');
    if(width>=1440){const ys=await page.locator('.frameworks-toolbar').evaluate(n=>[...n.children].filter(c=>!c.hidden&&getComputedStyle(c).display!=='none').map(c=>c.getBoundingClientRect().y));assert(Math.max(...ys)-Math.min(...ys)<3,'Framework toolbar wraps');}
    await page.screenshot({path:path.join(OUT,`frameworks-${dark?'dark':'light'}-${width}.png`)});
    await page.evaluate(()=>{showFixture('referencesView');document.querySelectorAll('.reference-panel').forEach(n=>n.hidden=n.id!=='referenceAmcu')});await page.waitForTimeout(80);
    await page.locator('.amcu-toolbar .system-width-button').waitFor();
    if(width>=1440)assert(await page.locator('.amcu-toolbar').evaluate(toolbar=>{
      const info=toolbar.firstElementChild.getBoundingClientRect(),search=toolbar.querySelector('.pqm-clear-wrap').getBoundingClientRect();
      const readable=[...toolbar.querySelectorAll('select')].every(n=>{const s=getComputedStyle(n),c=document.createElement('canvas').getContext('2d');c.font=s.font;return n.clientWidth-parseFloat(s.paddingLeft)-parseFloat(s.paddingRight)>=c.measureText(n.selectedOptions[0].textContent).width&&n.clientHeight-parseFloat(s.paddingTop)-parseFloat(s.paddingBottom)>=parseFloat(s.fontSize)*1.2});
      return info.width>=220&&search.left-info.right<=9&&readable;
    }),'AMCU info/search gap or default option readability');
    assert(await page.locator('.amcu-toolbar').evaluate(n=>[...n.children].filter(c=>!c.hidden&&getComputedStyle(c).display!=='none').every(c=>{const r=c.getBoundingClientRect();return r.x>=0&&r.right<=window.innerWidth})), 'AMCU control clipped');
    assert(await page.locator('.amcu-toolbar .pqm-clear-wrap').evaluate(n=>{const a=n.getBoundingClientRect(),b=n.querySelector('input').getBoundingClientRect();return b.x>=a.x-1&&b.right<=a.right+1}), 'Search input overlaps adjacent filters');
    if(width>=1440){const rects=await page.locator('.amcu-toolbar').evaluate(n=>[...n.children].filter(c=>!c.hidden&&getComputedStyle(c).display!=='none').map(c=>({id:c.id||c.className,y:c.getBoundingClientRect().y+c.getBoundingClientRect().height/2,w:c.getBoundingClientRect().width})));const ys=rects.map(r=>r.y);assert(Math.max(...ys)-Math.min(...ys)<3,'AMCU toolbar wraps '+JSON.stringify({width,dark,rects}));}
    if(width===1440||width===390)await page.screenshot({path:path.join(OUT,`amcu-${dark?'dark':'light'}-${width}.png`)});
   }
  }
  assert.deepEqual(errors,[]);console.log('BROWSER_UI=PASS; themes=2 widths=4 clear_fields=12 copy/badges/filter/column-button/no-F5=PASS');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
