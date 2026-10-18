/* Actual decorated Sandbox HTML, local synthetic data and real theme/Halloween modules. */
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict'),cp=require('child_process');
const {chromium}=require('playwright'),root=path.resolve(__dirname,'..');
const out=process.env.PQM_THEME_EVIDENCE||require('os').tmpdir();
const html=process.env.PQM_SERVED_HTML?fs.readFileSync(process.env.PQM_SERVED_HTML,'utf8'):cp.execFileSync(process.env.PQM_PYTHON||'python',['-B','-c',"import os;os.environ['PQM_SANDBOX']='1';from pathlib import Path;import sandbox_runtime;print(sandbox_runtime.decorate_html(Path('index.html').read_bytes()).decode('utf-8'))"],{cwd:root,encoding:'utf8'});
assert(html.includes('data-pqm-environment="sandbox"')&&html.includes('sandbox-brand-copy'));
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.PQM_TEST_BROWSER?{executablePath:process.env.PQM_TEST_BROWSER}:{})}),results=[];
 try{for(const width of [1920,800,390])for(const zoom of [1,1.25]){
  const page=await browser.newPage({viewport:{width,height:1080},reducedMotion:'reduce'}),errors=[],failed=[];
  page.on('pageerror',e=>errors.push(String(e)));page.on('requestfailed',r=>failed.push(r.url()));
  await page.clock.install({time:new Date('2026-10-18T09:00:00Z')});
  await page.route('**/*',r=>{const u=new URL(r.request().url());assert.equal(u.origin,'http://pqm.fixture');assert.equal(r.request().method(),'GET');const file=path.join(root,u.pathname==='/'?'index.html':u.pathname);if(!fs.existsSync(file))return r.abort();if(file.endsWith('.js')&&!['theme_ui.js','nav_icons.js','halloween.js','halloween_season.js','sandbox_contrast.js'].includes(path.basename(file)))return r.fulfill({body:'',contentType:'application/javascript'});return r.fulfill({body:u.pathname==='/'?html:fs.readFileSync(file),contentType:file.endsWith('.html')?'text/html':file.endsWith('.css')?'text/css':file.endsWith('.js')?'application/javascript':file.endsWith('.webp')?'image/webp':'image/svg+xml'});});
  await page.goto('http://pqm.fixture/');
  await page.evaluate(zoom=>{
   document.body.style.zoom=String(zoom);document.getElementById('loginGate').hidden=true;document.getElementById('applicationShell').hidden=false;PqmThemeUI.install();
   document.getElementById('currentUserAvatar').src='/assets/pqm-q-favicon.svg';document.getElementById('currentUserAvatar').hidden=false;
   for(const id of ['queueQualificationCards','queueProtocolOfficerCards','queueCategoryCards','queueProtocolCategoryCards']){const e=document.getElementById(id),category=id.includes('Category');if(e)e.innerHTML=(category?['Їжа','Інше','Газ/ЕЕ','Пальне']:['Тестова УО 1','Тестова УО 2']).map((label,i)=>`<button class="qualification-summary-officer ${category?'qualification-summary-category':''}"><span>${label}</span><strong>${i+3}</strong><small>Ізольована вибірка</small></button>`).join('');}
   for(const tbody of document.querySelectorAll('main tbody'))if(!tbody.children.length){const row=tbody.insertRow();for(const th of tbody.closest('table').querySelectorAll('thead th'))row.insertCell().textContent='Ізольований тест — не робочі дані';}
   const nav=document.getElementById('mainNav');nav.querySelectorAll('button').forEach(n=>n.classList.remove('nav-active'));nav.querySelector('button').classList.add('nav-active');
   for(const selector of ['#requestsNav','#operationalTasksNav']){const button=document.querySelector(selector),b=document.createElement('b');b.className='action-count-badge';b.textContent='14';button.append(b);}
   const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.id='themeCustomSvg';svg.innerHTML='<path fill="#e91e63" stroke="#13ac75" d="M0 0h10v10z"/>';svg.style.display='none';document.body.append(svg);
  },zoom);
  const ids=await page.locator('main').evaluateAll(ns=>ns.map(n=>n.id));
  const toggleHalloween=async value=>{await page.locator('#accountSettingsDialog').evaluate(n=>n.showModal());await page.locator('#halloweenDecorationEnabled').setChecked(value);await page.locator('#accountSettingsDialog').evaluate(n=>n.close());};
  for(const id of ids){
   await page.evaluate(id=>{document.querySelectorAll('main').forEach(n=>n.hidden=n.id!==id);document.querySelectorAll('#mainNav button').forEach(n=>n.classList.toggle('nav-active',n.id===id.replace(/View$/,'Nav')));},id);
   let geometry;
   for(const theme of ['light','dark'])for(const halloween of [false,true]){
    assert.equal(await page.evaluate(theme=>PqmThemeUI.apply(theme),theme),theme);
    await toggleHalloween(halloween);
    await page.clock.runFor(60);
    const state=await page.evaluate(id=>{const node=document.getElementById(id),logo=document.querySelector('.sandbox-brand-initials'),rect=n=>{const r=n.getBoundingClientRect();return[r.x,r.y,r.width,r.height]};return{identity:document.documentElement.dataset.pqmEnvironment,theme:document.documentElement.dataset.theme,halloween:document.documentElement.dataset.halloween,bg:getComputedStyle(document.body).backgroundColor,scene:getComputedStyle(node,'::before').backgroundImage,logo:logo.getAttribute('src'),logoRect:rect(logo),geometry:[...document.querySelectorAll('.topbar'),...node.querySelectorAll('section,article,table,input,select,button')].map(rect),svg:[getComputedStyle(document.querySelector('#themeCustomSvg path')).fill,getComputedStyle(document.querySelector('#themeCustomSvg path')).stroke],legacyMarkers:document.querySelectorAll('[data-pqm-light-ink],[data-pqm-dark-ink]').length,cat:getComputedStyle(document.querySelector('.halloween-cat')).display};},id);
    assert.equal(state.identity,'sandbox');assert.equal(state.theme,theme);assert.equal(state.halloween,halloween?'on':'off');assert.equal(state.legacyMarkers,0);
    assert.equal(state.bg,theme==='dark'?'rgb(11, 23, 42)':'rgb(245, 247, 248)');
    assert.equal(state.logo,`/assets/pqm-brand-mark-prod${theme==='dark'?'-dark':''}.svg`);assert.deepEqual(state.svg,['rgb(233, 30, 99)','rgb(19, 172, 117)']);
    if(geometry)assert.deepEqual(state.geometry,geometry,'Decoration/theme changed geometry '+id);else geometry=state.geometry;
    assert(state.logoRect[0]>=0&&state.logoRect[0]+state.logoRect[2]<=width,'Logo outside viewport');
    if(halloween&&await page.locator('#'+id).evaluate(n=>n.classList.contains('halloween-workspace')))assert(state.scene.includes(`halloween-workqueue-${theme}.webp`));else assert.equal(state.scene,'none');
    assert.equal(state.cat==='none',!halloween);
    results.push({id,width,zoom,theme,halloween,bg:state.bg,scene:state.scene,status:'PASS'});
    if(width===1920&&zoom===1)await page.screenshot({path:path.join(out,`${id}-${theme}-halloween-${halloween?'on':'off'}.png`),fullPage:true});
   }
  }
  for(const id of await page.locator('dialog').evaluateAll(ns=>ns.map(n=>n.id))){let geometry;
   for(const theme of ['light','dark'])for(const halloween of [false,true]){
    await page.evaluate(theme=>PqmThemeUI.apply(theme),theme);await toggleHalloween(halloween);
    const current=await page.locator('#'+id).evaluate(n=>{n.showModal();return [...n.querySelectorAll('form,header,footer,input,select,button')].map(e=>{const r=e.getBoundingClientRect();return[r.x,r.y,r.width,r.height]})});
    if(geometry)assert.deepEqual(current,geometry,'Modal geometry '+id);else geometry=current;
    await page.locator('#'+id).evaluate(n=>n.close());await page.clock.runFor(20);
    results.push({id,width,zoom,theme,halloween,kind:'modal',status:'PASS'});
   }
  }
  // Preference survives theme changes and season closure. Kyiv midnight, not local browser zone.
  await toggleHalloween(true);await page.clock.setSystemTime(new Date('2026-10-31T21:59:59Z'));await page.clock.runFor(60000);
  assert.equal(await page.evaluate(()=>document.documentElement.dataset.halloween),'off');
  assert.equal(await page.locator('#halloweenDecorationEnabled').isDisabled(),true);
  await page.evaluate(()=>PqmThemeUI.apply('dark'));assert.equal(await page.evaluate(()=>document.documentElement.dataset.halloween),'off');
  await page.clock.setSystemTime(new Date('2027-09-30T21:00:00Z'));await page.clock.runFor(60000);
  assert.equal(await page.evaluate(()=>document.documentElement.dataset.halloween),'on');
  assert.deepEqual(errors,[]);assert.deepEqual(failed,[]);await page.close();
 }}finally{await browser.close()}
 fs.writeFileSync(path.join(out,'SANDBOX_THEME_BROWSER.json'),JSON.stringify({status:'PASS',cases:results.length,results},null,2));console.log('SANDBOX_THEME_BROWSER=PASS; cases='+results.length+'; four modes, geometry, SVG, decorated HTML, Kyiv season');
})().catch(e=>{console.error(e);process.exitCode=1});
