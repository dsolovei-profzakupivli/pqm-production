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
  for(const name of ['styles.css','filters.css','modules.css','schema_ui.css','ui_improvements.css','sandbox_theme.css','ui_final.css','ui_tz2.css'])await page.addStyleTag({content:read(name)});
  await page.evaluate(()=>{
   document.querySelector('#loginGate').hidden=true;document.querySelector('#applicationShell').hidden=false;
   document.body.dataset.authRole='admin';
   document.querySelector('#mainNav').innerHTML='<button id="requestsNav">Звернення замовників</button><button id="operationalTasksNav">Операційні задачі</button>';
   window.API='/api';window.currentMe={permissions:{'tasks.read':true,'appeals.read':true}};
   window.authReady=Promise.resolve(currentMe);window.requestsPage=3;window.reloads=0;window.toastLog=[];
   window.toast=s=>toastLog.push(s);window.loadViolationReports=()=>{reloads++};
   window.esc=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
   window.fixtureCounts={tasks:27,appeals:4};window.fixtureCalls=[];
   window.request=async(url,options={})=>{fixtureCalls.push(url);if(options.method&&options.method!=='GET')throw Error('Unexpected write');
    if(url.endsWith('/summary'))return{count:url.includes('operational')?fixtureCounts.tasks:fixtureCounts.appeals};return{tables:{}}};
   window.clipboardValue='';Object.defineProperty(navigator,'clipboard',{value:{writeText:async value=>{clipboardValue=value}},configurable:true});
   document.querySelector('#officerCards').innerHTML=['Т. Федченко','Д. Савва','О. Єрьоміна'].map(n=>`<button class="officer-card"><span>${n}</span><strong>72</strong></button>`).join('');
   window.showFixture=name=>{document.querySelectorAll('main').forEach(n=>n.hidden=n.id!==name)};
   showFixture('frameworkAnalyticsView');
  });
  await page.addScriptTag({content:read('ui_improvements.js')});
  const app=read('app.js'),a=app.indexOf('function frameworkProzorroLink('),b=app.indexOf('function registryExportUrl(',a);
  await page.addScriptTag({content:app.slice(a,b)});
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
  await page.evaluate(()=>{document.getElementById('requestsSearch').value='старий фільтр';PqmUi.responseExpired=false});
  await page.locator('#requestsNav .action-count-badge').click();assert.equal(await page.locator('#requestsSearch').inputValue(),'старий фільтр');assert.equal(await page.evaluate(()=>PqmUi.responseExpired),false);
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
  await page.evaluate(()=>{showFixture('requestsView');document.querySelector('#requestsExpiredFilter').click()});
  assert.equal(await page.evaluate(()=>PqmUi.responseExpired),true);assert.equal(await page.evaluate(()=>requestsPage),1);
  assert.equal(await page.evaluate(()=>reloads),1);
  await page.evaluate(()=>showFixture('historyView'));
  const historyFields=await page.locator('#historyFilters input:not([type=date])').count();assert.equal(historyFields,9);
  for(let i=0;i<9;i++)await page.locator('#historyFilters input:not([type=date])').nth(i).fill('значення '+i);
  for(let i=0;i<9;i++){
    const field=page.locator('#historyFilters input:not([type=date])').nth(i);
    await field.locator('..').locator('.pqm-search-clear').click();assert.equal(await field.inputValue(),'');
    for(let j=i+1;j<9;j++)assert.equal(await page.locator('#historyFilters input:not([type=date])').nth(j).inputValue(),'значення '+j);
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
    assert(await page.locator('.amcu-toolbar').evaluate(n=>[...n.children].filter(c=>!c.hidden&&getComputedStyle(c).display!=='none').every(c=>{const r=c.getBoundingClientRect();return r.x>=0&&r.right<=window.innerWidth})), 'AMCU control clipped');
    assert(await page.locator('.amcu-toolbar .pqm-clear-wrap').evaluate(n=>{const a=n.getBoundingClientRect(),b=n.querySelector('input').getBoundingClientRect();return b.x>=a.x-1&&b.right<=a.right+1}), 'Search input overlaps adjacent filters');
    if(width>=1440){const rects=await page.locator('.amcu-toolbar').evaluate(n=>[...n.children].filter(c=>!c.hidden&&getComputedStyle(c).display!=='none').map(c=>({id:c.id||c.className,y:c.getBoundingClientRect().y+c.getBoundingClientRect().height/2,w:c.getBoundingClientRect().width})));const ys=rects.map(r=>r.y);assert(Math.max(...ys)-Math.min(...ys)<3,'AMCU toolbar wraps '+JSON.stringify({width,dark,rects}));}
    if(width===1440||width===390)await page.screenshot({path:path.join(OUT,`amcu-${dark?'dark':'light'}-${width}.png`)});
   }
  }
  assert.deepEqual(errors,[]);console.log('BROWSER_UI=PASS; themes=2 widths=4 clear_fields=12 copy/badges/filter/column-button/no-F5=PASS');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
