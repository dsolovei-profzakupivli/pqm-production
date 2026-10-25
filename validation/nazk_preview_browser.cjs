/* Real index/CSS/new module and unchanged width/hotfix script, synthetic API replies only. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
let chromium;try{({chromium}=require('playwright'));}catch{({chromium}=require('C:/Users/User/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));}
const root=path.resolve(__dirname,'..'),read=name=>fs.readFileSync(path.join(root,name),'utf8');
const python=process.env.PQM_TEST_PYTHON||(process.platform==='win32'?'C:/Users/User/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe':'python3');
const generated=require('node:child_process').spawnSync(python,['-B',path.join(__dirname,'nazk_preview_browser_fixture.py')],{cwd:root,encoding:'utf8'});
assert.equal(generated.status,0,generated.stderr);
const payload=JSON.parse(generated.stdout),app=read('app.js');
const line=name=>app.split(/\r?\n/).find(s=>s.startsWith('function '+name+'('));
const legacy=app.slice(app.indexOf('let operationalListGeneration=0;'),app.indexOf('function operationalHistoryHtml('));
const stub=`window.API='/api';window.authReady=Promise.resolve();window.currentMe={role:'ROLE',permissions:{'tasks.read':true,'suppliers.read':true},ui_features:{nazk_preview:true}};
window.$=s=>document.querySelector(s);window.$$=s=>[...document.querySelectorAll(s)];window.esc=x=>String(x??'');window.toast=()=>{};window.calls=[];window.cardCalls=[];window.taskCalls=[];window.operationalBasisDirection='';window.operationalTaskTimer=0;
window.request=async(url,options={})=>{calls.push({url,method:options.method||'GET'});const r=await fetch(url,options);const data=await r.json();if(!r.ok)throw Error(data.error||'Read failed');return data;};
window.openSupplierProfile=code=>{cardCalls.push(code);document.querySelector('#supplierProfileDialog').showModal()};window.openOperationalTask=id=>{taskCalls.push(id);document.querySelector('#operationalTaskDialog').showModal()};window.renderOperationalTaskTypes=()=>{};
document.querySelector('#loginGate').hidden=true;document.querySelector('#applicationShell').hidden=false;document.querySelectorAll('main').forEach(m=>m.hidden=m.id!=='operationalTasksView');document.body.dataset.authRole='ROLE';
${line('operationalTaskParams')}
${line('operationalActionColumnVisible')}
${line('operationalTaskEmptyMessage')}
${legacy}
`;
const markup=read('index.html').replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,'');
function response(url){
 const q=url.searchParams,scope=q.get('scope')||'active';let rows=payload.items.filter(r=>scope==='all'||(scope==='active'?r.active_count>0:r.active_count===0));
 for(const key of ['state','reason','group'])if(q.get(key))rows=rows.filter(r=>r[key]===q.get(key));
 if(q.get('search')){const term=q.get('search').toLocaleLowerCase('uk');rows=rows.filter(r=>(r.name+' '+r.code).toLocaleLowerCase('uk').includes(term));}
 return {...payload,items:rows,total:rows.length,page:1,pages:1};
}
(async()=>{
 const executable='C:/Users/User/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe';
 const browser=await chromium.launch({headless:true,...(fs.existsSync(executable)?{executablePath:executable}:{})});
 const checks=[],errors=[],forbidden=[];
 fs.mkdirSync(path.join(root,'evidence','browser'),{recursive:true});
 for(const role of ['admin','officer','viewer']){
  const page=await browser.newPage({viewport:{width:1440,height:1050}});
  page.on('pageerror',e=>errors.push(String(e)));
  await page.route('**/*',async route=>{
   const url=new URL(route.request().url());
   if(url.hostname!=='pqm.test'){forbidden.push(url.href);return route.abort();}
   if(url.pathname==='/fixture')return route.fulfill({contentType:'text/html',body:markup.replace('</body>',`<script>${stub.replaceAll('ROLE',role)}</script><script src="/table_widths_ui.js"></script><script src="/nazk_preview.js"></script></body>`)});
   if(url.pathname.startsWith('/api/')){
    assert.equal(route.request().method(),'GET');
    const body=url.pathname==='/api/operational-tasks/nazk-preview'?response(url):url.pathname==='/api/operational-tasks'?{items:[],total:0,kpis:{},type_counts:{}}:url.pathname==='/api/table-widths'?{tables:{}}:{};
    return route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
   }
   const file=path.join(root,url.pathname.slice(1));
   if(!file.startsWith(root)||!fs.existsSync(file))return route.fulfill({status:404,body:''});
   return route.fulfill({path:file});
  });
  await page.goto('http://pqm.test/fixture');await page.locator('#nazkPreviewTabs').waitFor();
  assert.equal(await page.locator('#nazkPreviewPanel').isVisible(),false);
  await page.evaluate(()=>loadOperationalTasks());
  await page.selectOption('#operationalTaskType','amcu_exclusion');
  const legacyBody=await page.locator('#operationalTasksBody').innerHTML();
  for(const theme of ['light','dark']){
   await page.evaluate(t=>{document.documentElement.dataset.theme=t;document.body.dataset.theme=t;},theme);
   await page.locator('[data-nazk-view=preview]').click();
   await page.waitForFunction(()=>document.querySelector('#nazkPreviewMessage').textContent.startsWith('Лише перегляд.'));
   assert.equal(await page.locator('#nazkPreviewRows tr').count(),10);
   assert.equal(await page.locator('[data-nazk-count=new_checks]').first().textContent(),'1');
   assert.equal(await page.locator('[data-nazk-count=new_tasks]').textContent(),'1');
   checks.push(`${role}/${theme}: preview population and separate counters`);
   await page.locator('#nazkPreviewRows button[data-nazk-supplier]').first().click();
   assert(await page.locator('#supplierProfileDialog').evaluate(d=>d.open));
   await page.keyboard.press('Escape');
   const callsBefore=await page.evaluate(()=>taskCalls.length);
   await page.locator('#nazkPreviewRows button[data-nazk-task]').first().click();
   assert.equal(await page.evaluate(()=>taskCalls.length),callsBefore+1);await page.keyboard.press('Escape');
   assert.equal(await page.locator('#nazkPreviewRows button:disabled').count(),10);
   checks.push(`${role}/${theme}: one-click card/task dispatch; launch disabled`);
   await page.selectOption('#nazkPreviewState','refuted');await page.waitForFunction(()=>document.querySelectorAll('#nazkPreviewRows tr').length===1);
   assert.match(await page.locator('#nazkPreviewRows').textContent(),/Спростовано/);
   await page.selectOption('#nazkPreviewState','');await page.selectOption('#nazkPreviewReason','no_linked_active_applications');
   await page.waitForFunction(()=>document.querySelectorAll('#nazkPreviewRows tr').length===1);
   assert.match(await page.locator('#nazkPreviewRows').textContent(),/00000007/);
   await page.selectOption('#nazkPreviewReason','');await page.fill('#nazkPreviewSearch','00000001');
   await page.waitForFunction(()=>document.querySelectorAll('#nazkPreviewRows tr').length===1);
   assert.match(await page.locator('#nazkPreviewRows').textContent(),/00000001/);
    await page.fill('#nazkPreviewSearch','');
    await page.waitForFunction(()=>document.querySelectorAll('#nazkPreviewRows tr').length===10);
    await page.selectOption('#nazkPreviewScope','inactive');await page.waitForFunction(()=>document.querySelectorAll('#nazkPreviewRows tr').length===1);
    await page.waitForFunction(()=>/00000008/.test(document.querySelector('#nazkPreviewRows').textContent));
    assert.match(await page.locator('#nazkPreviewRows').textContent(),/00000008/);
   await page.selectOption('#nazkPreviewScope','active');await page.selectOption('#nazkPreviewGroup','completed');
   await page.waitForFunction(()=>document.querySelectorAll('#nazkPreviewRows tr').length===2);
   await page.selectOption('#nazkPreviewGroup','');await page.waitForFunction(()=>document.querySelectorAll('#nazkPreviewRows tr').length===10);
   checks.push(`${role}/${theme}: search/state/reason/completed/inactive filters`);
   await page.locator('#nazkPreviewRefresh').click();await page.waitForFunction(()=>!document.querySelector('#nazkPreviewRefresh').disabled);
   if(role==='admin')await page.screenshot({path:path.join(root,'evidence','browser',`${theme}-1440.png`),fullPage:true});
   await page.setViewportSize({width:390,height:844});
   assert(await page.locator('.nazk-preview-scroll').evaluate(x=>x.scrollWidth>x.clientWidth));
   await page.locator('.nazk-preview-scroll').evaluate(x=>x.scrollLeft=x.scrollWidth);
   assert(await page.locator('.nazk-preview-scroll').evaluate(x=>x.scrollLeft>0));
   if(role==='admin')await page.screenshot({path:path.join(root,'evidence','browser',`${theme}-390.png`),fullPage:true});
   await page.setViewportSize({width:1440,height:1050});
   const settled=await page.evaluate(async()=>{let count=0;const observer=new MutationObserver(m=>count+=m.length);observer.observe(document.querySelector('#nazkPreviewPanel'),{childList:true,subtree:true});await new Promise(r=>setTimeout(r,350));observer.disconnect();return count;});assert(settled<50,`DOM must settle; mutations=${settled}`);
   await page.locator('[data-nazk-view=tasks]').click();
   assert.equal(await page.locator('#operationalTaskType').inputValue(),'amcu_exclusion');
   assert.equal(await page.locator('#operationalTasksBody').innerHTML(),legacyBody);
   checks.push(`${role}/${theme}: horizontal scroll; DOM settles; legacy controls/body preserved`);
  }
  await page.evaluate(()=>{currentMe.permissions['suppliers.read']=false;document.body.dataset.authRole='revoked'});
  await page.waitForFunction(()=>document.querySelector('#nazkPreviewTabs').hidden);
  checks.push(`${role}: revoked read grant hides preview`);
  assert((await page.evaluate(()=>calls)).every(call=>call.method==='GET'));
  await page.close();
 }
 assert.deepEqual(errors,[]);assert.deepEqual(forbidden,[]);
 fs.writeFileSync(path.join(root,'evidence','browser','results.json'),JSON.stringify({checks,errors,forbidden,synthetic_only:true},null,2));
 console.log(JSON.stringify({pass:checks.length,checks}));await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
