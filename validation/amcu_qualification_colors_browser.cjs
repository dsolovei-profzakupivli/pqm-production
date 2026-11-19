/* Offline actual AMCU renderer, existing API projection, and painted contrast. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
let chromium;try{({chromium}=require('playwright'))}catch{({chromium}=require('C:/Users/User/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'))}
const root=path.resolve(__dirname,'..'),read=n=>fs.readFileSync(path.join(root,n),'utf8'),out=path.join(root,'evidence/amcu-toolbar');fs.mkdirSync(out,{recursive:true});
const fixtures=[
 {offender_name:'ОДНА АКТИВНА КВАЛІФІКАЦІЯ',in_supplier_registry:1,active_qualifications:1,has_application:1},
 {offender_name:'КІЛЬКА КВАЛІФІКАЦІЙ: Є АКТИВНА',in_supplier_registry:1,active_qualifications:1,has_application:1},
 {offender_name:'УСІ КВАЛІФІКАЦІЇ НЕАКТИВНІ',in_supplier_registry:1,active_qualifications:0,has_application:1},
 {offender_name:'ЛИШЕ ВІДХИЛЕНІ ЗАЯВКИ',in_supplier_registry:0,active_qualifications:0,has_application:1},
 {offender_name:'НЕМАЄ ЗАЯВОК І КВАЛІФІКАЦІЙ',in_supplier_registry:0,active_qualifications:0,has_application:0}
].map((x,i)=>({...x,offender_code:'0000000'+i,decision_no:'0012-р/к-А',decision_date:'2026-10-01',authority:'Тестовий орган АМКУ',court_case_no:'001/26-А'}));
const src=read('app.js'),start=src.indexOf('async function loadReferenceRegistry(kind){'),end=src.indexOf("\n}",start)+2,loader=src.slice(start,end);
assert(loader.includes('refAmcuBody')&&loader.includes('referencePageCounts[kind]'));
const queueTemplate=src.match(/\$\('#queuePublicationControl'\)\.innerHTML=`([^`]+)`/)[1];
const queueMarkup=new Function('control','return `'+queueTemplate+'`')({admitted:0,rejected:0,awaiting_sync:0});
const stub=`window.API='/api';window.authReady=Promise.resolve();window.calls=[];window.toast=()=>{};window.$=s=>document.querySelector(s);window.esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));window.referencePages={amcu:1};window.referencePageCounts={amcu:1};window.openSupplierProfile=code=>window.openedSupplier=code;
window.request=async(url,options={})=>{calls.push({url,method:options.method||'GET'});if(options.method&&options.method!=='GET')throw Error('No data writes');if(url.endsWith('/account'))return {username:'amcu-color-test'};if(url.endsWith('/table-widths'))return {tables:{}};if(url.includes('/amcu-registry?'))return {items:${JSON.stringify(fixtures)},total:5,pages:1,authorities:[]};throw Error('Unexpected '+url)};
document.querySelector('#loginGate').hidden=true;document.querySelector('#applicationShell').hidden=false;document.querySelectorAll('main').forEach(m=>m.hidden=m.id!=='referencesView');document.body.dataset.authRole='admin';document.querySelectorAll('[data-ref-tab]').forEach(n=>n.classList.toggle('active',n.dataset.refTab==='amcu'));document.querySelectorAll('#referencesView>section').forEach(n=>n.hidden=n.id!=='referenceAmcu');document.querySelector('#referenceAmcu').hidden=false;document.querySelector('#workQueueView').remove();document.querySelector('#referenceAmcu').insertAdjacentHTML('afterbegin','<section id="workQueueView"><h3>Еталон: контроль після синхронізації публікації рішень</h3><div id="queuePublicationControl" class="publication-control-cards">'+${JSON.stringify(queueMarkup)}+'</div></section>');document.querySelector('#referenceAmcu').insertAdjacentHTML('afterbegin','<section aria-label="Порівняння чинної палітри PQM"><button class="check-result-card admit" id="paletteAdmit"><strong>Допущено</strong></button><button class="check-result-card reject" id="paletteReject"><strong>Відхилено</strong></button></section>');document.querySelector('#referenceNazk').hidden=true;document.querySelector('#referenceDeclension').hidden=true;`;
const html=read('index.html').replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,'').replace('</body>',`<script>${stub}${loader};loadReferenceRegistry('amcu');</script><script src='/table_widths_ui.js'></script></body>`);
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.PQM_TEST_BROWSER?{executablePath:process.env.PQM_TEST_BROWSER}:{})});
 const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage(),errors=[],results=[];page.on('pageerror',e=>errors.push(String(e)));
 await context.route('**/*',route=>{const u=new URL(route.request().url());assert.equal(u.hostname,'pqm.test');if(u.pathname==='/fixture')return route.fulfill({contentType:'text/html',body:html});const file=path.resolve(root,'.'+u.pathname);return file.startsWith(root+path.sep)&&fs.existsSync(file)&&fs.statSync(file).isFile()?route.fulfill({path:file}):route.fulfill({status:404,body:''})});
 try{
  await page.goto('http://pqm.test/fixture');await page.locator('#refAmcuBody tr').nth(4).waitFor();
  assert.deepEqual(await page.locator('#refAmcuBody tr').evaluateAll(rows=>rows.map(r=>r.classList.contains('amcu-active-supplier')?'active':r.classList.contains('amcu-our-supplier')?'inactive':'none')),['active','active','inactive','none','none']);
  assert.deepEqual(await page.locator('#refAmcuBody tr').evaluateAll(rows=>rows.map(r=>r.querySelector('.registry-flag')?.textContent||'')),['Активні: 1','Активні: 1','Неактивні','','']);
  assert.equal(await page.locator('.amcu-applicant').count(),0);
  await page.locator('#refAmcuBody tr').first().click();assert.equal(await page.evaluate(()=>openedSupplier),'00000000');
  for(const theme of ['light','dark'])for(const width of [1440,390]){
   await page.setViewportSize({width,height:1000});await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);
   const palette=await page.evaluate(()=>Object.fromEntries(['Admit','Reject'].map(k=>[k,getComputedStyle(document.querySelector('#palette'+k)).backgroundColor])));
   const queuePalette=await page.evaluate(()=>Object.fromEntries([['Admit','active'],['Reject','unsuccessful']].map(([k,v])=>[k,getComputedStyle(document.querySelector('#queuePublicationControl [data-publication-state="'+v+'"]')).backgroundColor])));
   const rowPalette=theme==='dark'?queuePalette:palette;
   assert.equal(queuePalette.Reject,theme==='dark'?'rgb(72, 41, 50)':'rgb(237, 249, 243)');assert.equal(queuePalette.Admit,theme==='dark'?'rgb(23, 62, 56)':'rgb(237, 249, 243)');
   assert.equal(palette.Reject,theme==='dark'?'rgb(73, 41, 54)':'rgb(255, 240, 240)');assert.equal(palette.Admit,theme==='dark'?'rgb(23, 62, 56)':'rgb(232, 246, 240)');
   for(const state of ['normal','hover','active','selected','aria-selected']){
    await page.evaluate(state=>document.querySelectorAll('#refAmcuBody tr').forEach(r=>{r.classList.remove('active','selected');r.removeAttribute('aria-selected');if(state==='active'||state==='selected')r.classList.add(state);if(state==='aria-selected')r.setAttribute('aria-selected','true')}),state);
    for(let i=0;i<5;i++){
     if(state==='hover')await page.locator('#refAmcuBody tr').nth(i).hover();else await page.mouse.move(1,1);
     const painted=await page.locator('#refAmcuBody tr').nth(i).evaluate(row=>{
      const rgb=s=>(s.match(/[\d.]+/g)||[]).map(Number),lum=c=>c.slice(0,3).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4}).reduce((a,v,i)=>a+v*[.2126,.7152,.0722][i],0);
      const surface=n=>{for(;n;n=n.parentElement){const c=rgb(getComputedStyle(n).backgroundColor);if(c.length===3||c[3]===1)return c}return [255,255,255]};
      return {cells:[...row.children].map(n=>({bg:getComputedStyle(n).backgroundColor,color:getComputedStyle(n).color})),texts:[...row.querySelectorAll('td,strong,.registry-flag')].map(n=>{const fg=rgb(getComputedStyle(n).color),bg=surface(n),l=[lum(fg),lum(bg)].sort((a,b)=>b-a);return {contrast:(l[0]+.05)/(l[1]+.05),fg,bg}}),stripe:getComputedStyle(row.firstElementChild).boxShadow,badgeBorder:row.querySelector('.registry-flag')?parseFloat(getComputedStyle(row.querySelector('.registry-flag')).borderTopWidth):0,opacity:getComputedStyle(row).opacity};
     });
     assert.equal(painted.opacity,'1');if(i<3){assert.notEqual(painted.stripe,'none');assert(painted.badgeBorder>=1,'Status badge stays outlined')}assert.equal(painted.cells.length,6);
     for(const t of painted.texts){assert(t.contrast>=4.5,`${theme}/${width}/${state}/${i} contrast ${t.contrast}`);if(i<3&&theme==='light')assert(Math.max(...t.fg.slice(0,3))<150,'Dark text on light colored rows')}
     if(i<3)for(const c of painted.cells)assert.equal(c.bg,i<2?rowPalette.Reject:rowPalette.Admit,'Exact existing status card surface, including hover/selected');
     results.push({theme,width,state,case:i,palette,queuePalette,rowPalette,minimumContrast:Math.min(...painted.texts.map(t=>t.contrast))});
    }
   }
   await page.evaluate(()=>document.querySelectorAll('#refAmcuBody tr').forEach(r=>{r.classList.remove('active','selected');r.removeAttribute('aria-selected')}));await page.mouse.move(1,1);
   await page.screenshot({path:path.join(out,`${theme}-${width}.png`),fullPage:true});
   if(width===390){
    const scroll=await page.locator('#referenceAmcu table').evaluate(t=>{let n=t.parentElement;while(n&&n.scrollWidth<=n.clientWidth)n=n.parentElement;return n?{width:n.clientWidth,total:n.scrollWidth}:null});
    assert(scroll&&scroll.total>scroll.width);
    await page.locator('#referenceAmcu table').evaluate(t=>{let n=t.parentElement;while(n&&n.scrollWidth<=n.clientWidth)n=n.parentElement;n.scrollLeft=n.scrollWidth});
    await page.screenshot({path:path.join(out,`${theme}-${width}-scrolled.png`),fullPage:true});
    await page.locator('#referenceAmcu table').evaluate(t=>{let n=t.parentElement;while(n&&n.scrollWidth<=n.clientWidth)n=n.parentElement;n.scrollLeft=0});
   }
  }
  const toolbarChecks=[];
  for(const theme of ['light','dark'])for(const width of [1920,1440,1366,1280,1279,1024,768,390]){
   await page.setViewportSize({width,height:1000});await page.evaluate(t=>document.documentElement.dataset.theme=t,theme);
   const layout=await page.locator('#referenceAmcu .amcu-toolbar').evaluate(t=>{
    const box=t.getBoundingClientRect(),controls=[...t.children].filter(n=>getComputedStyle(n).display!=='none').map(n=>{const b=n.getBoundingClientRect();return {id:n.id||n.tagName,x:b.x,y:b.y,width:b.width,height:b.height,center:b.y+b.height/2}});
    return {box:{x:box.x,right:box.right,width:box.width},controls,scrollWidth:t.scrollWidth,clientWidth:t.clientWidth,wrap:getComputedStyle(t).flexWrap};
   });
   const centers=layout.controls.map(n=>n.center);
   if(width>=1280){assert.equal(layout.wrap,'nowrap');assert(Math.max(...centers)-Math.min(...centers)<2,'Desktop controls share one row');assert(layout.scrollWidth<=layout.clientWidth+1,'No toolbar overflow');for(const c of layout.controls){assert(c.x>=layout.box.x-1&&c.x+c.width<=layout.box.right+1,'Control fits toolbar');assert(c.width>20)}}
   else{assert.equal(layout.wrap,'wrap');if(width<=1024)assert(Math.max(...centers)-Math.min(...centers)>10,'Narrow controls wrap')}
   toolbarChecks.push({theme,width,...layout});
  }
  fs.writeFileSync(path.join(out,'toolbar-results.json'),JSON.stringify({status:'PASS',checks:toolbarChecks},null,2));
  await page.locator('#referenceAmcu .system-width-button').click();assert.equal(await page.locator('.system-width-dialog[open]').count(),1);await page.locator('.dialog-cancel').click();
  assert((await page.evaluate(()=>calls)).every(c=>c.method==='GET'));assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(out,'browser-results.json'),JSON.stringify({status:'PASS',cases:5,paintedChecks:results.length,results},null,2));console.log('AMCU_COLORS_BROWSER=PASS cases=5 paintedChecks='+results.length);
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
