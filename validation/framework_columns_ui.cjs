/* Real browser, synthetic settings endpoint. No PQM server or network. */
const fs=require('fs'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.PQM_TEST_BROWSER?{executablePath:process.env.PQM_TEST_BROWSER}:{})});
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 let tables={},writes=[];
 await page.exposeFunction('settingsRequest',async(url,options={})=>{
   if(options.method==='POST'){const p=JSON.parse(options.body);tables[p.table_key]=p.widths;writes.push(p.table_key);return p.widths}
   if(options.method==='DELETE'){delete tables[new URL(url,'https://fixture.invalid').searchParams.get('table_key')];return{}}
   return{tables:JSON.parse(JSON.stringify(tables))};
 });
 const html=fs.readFileSync('index.html','utf8').replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,'');
 async function load(){
   await page.setContent(html);
   await page.addStyleTag({content:fs.readFileSync('styles.css','utf8')});
   await page.addStyleTag({content:fs.readFileSync('modules.css','utf8')});
   await page.addStyleTag({content:fs.readFileSync('sandbox_theme.css','utf8')});
   await page.evaluate(()=>{
     document.querySelector('#loginGate').hidden=true;document.querySelector('#applicationShell').hidden=false;
     document.documentElement.dataset.pqmEnvironment='production';
     document.querySelectorAll('.module-view').forEach(el=>el.hidden=el.id!=='frameworkAnalyticsView');
     document.body.dataset.authRole='admin';
     window.API='/api';window.authReady=Promise.resolve();window.request=window.settingsRequest;
     window.esc=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');window.toast=()=>{};
     document.querySelector('#frameworksBody').innerHTML='<tr>'+Array.from({length:10},(_,i)=>`<td>${i===9?'<a class="ghost">Завантажити реєстр</a>':'Тест'}</td>`).join('')+'</tr>';
   });
   await page.addScriptTag({content:fs.readFileSync('table_widths_ui.js','utf8')});
   await page.locator('.frameworks-toolbar .system-width-button').waitFor();
 }
 try{
   await load();
   const key=await page.locator('.frameworks-toolbar .system-width-button').getAttribute('data-table-key');
   assert.equal(key,'frameworkAnalyticsView:frameworksBody');
   const controls=page.locator('.frameworks-toolbar>input,.frameworks-toolbar>select,.frameworks-toolbar>label,.frameworks-toolbar>button');
   assert.equal(await controls.count(),7);
   const rects=await controls.evaluateAll(nodes=>nodes.map(n=>{const r=n.getBoundingClientRect();return{x:r.x,y:r.y,w:r.width,h:r.height}}));
   assert(rects.every(r=>Math.abs(r.y-rects[0].y)<2),'wide toolbar must have one row');
   assert(rects[0].w>rects[1].w&&rects[0].w>rects[2].w);
   const heights=await page.locator('.frameworks-toolbar input,.frameworks-toolbar select,.frameworks-toolbar button').evaluateAll(nodes=>nodes.map(n=>n.getBoundingClientRect().height));
   assert(heights.every(h=>h===38));
   if(process.env.PQM_UI_EVIDENCE_DIR)await page.locator('#frameworkAnalyticsView').screenshot({path:process.env.PQM_UI_EVIDENCE_DIR+'/frameworks-wide.png'});
   await page.setViewportSize({width:390,height:900});
   assert(await controls.evaluateAll(nodes=>nodes.every(n=>{const r=n.getBoundingClientRect();return r.x>=0&&r.right<=window.innerWidth})));
   await page.setViewportSize({width:1440,height:1000});
   // Execute the actual link helper without loading startup/sync handlers.
   const source=fs.readFileSync('app.js','utf8');
   const linkHelper=source.slice(source.indexOf('function frameworkProzorroLink('),source.indexOf('\n',source.indexOf('function frameworkProzorroLink(')));
   await page.addScriptTag({content:linkHelper});
   const link=await page.evaluate(()=>frameworkProzorroLink({id:'abc',pretty_id:'UA-F-2026-10-01-000001'}));
   assert(link.includes('https://prozorro.gov.ua/uk/framework/UA-F-2026-10-01-000001'));
   assert(link.includes('noopener noreferrer'));assert(link.includes('target="_blank"'));
   assert.equal(await page.evaluate(()=>frameworkProzorroLink({id:'',pretty_id:'Pending'})),'Pending');
   await page.locator('.frameworks-toolbar .system-width-button').click();
   const inputs=page.locator('.system-width-dialog [data-column]');assert.equal(await inputs.count(),10);
   if(process.env.PQM_UI_EVIDENCE_DIR)await page.screenshot({path:process.env.PQM_UI_EVIDENCE_DIR+'/columns-dialog.png'});
   const defaults=await inputs.evaluateAll(nodes=>nodes.map(n=>Number(n.value)));assert(defaults.every(n=>n>=40&&n<=1200));
   await inputs.nth(0).fill('200');await page.locator('.system-width-dialog .dialog-cancel').click();assert.equal(writes.length,0);
   await page.locator('.frameworks-toolbar .system-width-button').click();assert.equal(Number(await inputs.nth(0).inputValue()),defaults[0]);
   for(let i=0;i<10;i++)await inputs.nth(i).fill(String(i===9?300:200));
   await page.locator('.system-width-dialog button.primary').click();
   assert.equal(writes.length,1);assert.equal(Object.keys(tables[key]).length,10);
   const width=await page.locator('.frameworks-table').evaluate(t=>t.getBoundingClientRect().width);assert(width>=2100);
   assert(await page.locator('#frameworkAnalyticsView .table-scroll').evaluate(el=>el.scrollWidth>el.clientWidth));
   await load();assert.equal(await page.locator('.frameworks-table th').first().evaluate(t=>t.getBoundingClientRect().width),200);
   // Existing requests table uses its own key and remains unchanged.
   await page.evaluate(()=>{document.querySelector('#frameworkAnalyticsView').hidden=true;document.querySelector('#requestsView').hidden=false});
   const requests=page.locator('#requestsView .system-width-button');await requests.waitFor();assert.notEqual(await requests.getAttribute('data-table-key'),key);
   await page.evaluate(()=>{document.querySelector('#requestsView').hidden=true;document.querySelector('#frameworkAnalyticsView').hidden=false});
   await page.locator('.frameworks-toolbar .system-width-button').click();await page.locator('.system-width-reset').click();
   assert.equal(tables[key],undefined);assert.equal(await page.locator('.frameworks-table').evaluate(t=>t.style.width),'');
   console.log('FRAMEWORK_COLUMNS_UI=PASS: modal/10 columns/save/cancel/reload/reset/independence/scroll');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
