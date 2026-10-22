/* Actual baseline markup/styles and table renderers; synthetic API adapter, no server. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require(require.resolve('playwright',{paths:['C:/Users/User/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules']}));
const root=path.resolve(__dirname,'..'),out=path.join(root,'evidence'),read=n=>fs.readFileSync(path.join(root,n),'utf8');
const fixtures=JSON.parse(read('evidence/synthetic-api.json')),source=read('app.js'),original=read('evidence/original/app.js');
const referenceLoader=s=>s.slice(s.indexOf('loadReferenceRegistry=async function(kind){',s.indexOf('const loadReferenceRegistryBase=')),s.indexOf('const loadReferenceRegistryBeforeDatePresentation='));
const lineFunction=(s,n)=>s.split(/\r?\n/).find(l=>l.startsWith('function '+n+'('));
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Users/User/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe'});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],network=[];
 page.on('pageerror',e=>errors.push(String(e)));await page.route('**/*',r=>{network.push(r.request().url());return r.abort()});
 const results=[];
 try{
  await page.setContent(read('index.html').replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,'').replace(/<link\b[^>]*>/gi,''));
  for(const name of ['styles.css','filters.css','modules.css','schema_ui.css','ui_improvements.css','ui_final.css','theme.css'])await page.addStyleTag({content:read(name)});
  await page.evaluate(data=>{
   window.fixture=data;window.API='/api';window.$=s=>document.querySelector(s);
   window.esc=x=>String(x??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
   window.referencePages={nazk:1};window.referencePageCounts={nazk:1};
   window.loadReferenceRegistryBase=()=>{throw Error('Unexpected other registry')};
   window.request=async(url,options={})=>{if(options.method&&options.method!=='GET')throw Error('Unexpected write');if(!url.startsWith('/api/nazk-registry?'))throw Error('Unexpected URL');return structuredClone(fixture.directory)};
   document.querySelector('#loginGate').hidden=true;document.querySelector('#applicationShell').hidden=false;
   document.querySelectorAll('main').forEach(n=>n.hidden=n.id!=='referencesView');
   const section=document.querySelector('#referenceNazk');for(const panel of document.querySelectorAll('.reference-panel'))panel.hidden=panel!==section;
   window.nazkRegistrySourceNotice=()=>'';
   document.querySelector('#accountDisplayName').textContent='Локальна перевірка';
  },fixtures);
  await page.addScriptTag({content:lineFunction(source,'displayDateOnly')});
  await page.addScriptTag({content:lineFunction(source,'operationalNazkRecords')});
  await page.addScriptTag({content:lineFunction(original,'operationalNazkContext').replace('function operationalNazkContext(','function operationalNazkContextBaseline(')});
  await page.addScriptTag({content:lineFunction(source,'operationalNazkContext')});
  // Compare existing cells against the unmodified Live baseline, including links/dates.
  await page.addScriptTag({content:referenceLoader(original)});
  await page.evaluate(async()=>{await loadReferenceRegistry('nazk');window.oldReferenceRows=[...$('#refNazkBody').rows].map(r=>[...r.cells].map(c=>c.innerHTML));window.oldContext=operationalNazkContextBaseline(fixture.task)});
  await page.addScriptTag({content:referenceLoader(source)});
  await page.evaluate(async()=>{await loadReferenceRegistry('nazk');const old=document.createElement('div');old.innerHTML=oldContext;window.oldTaskRows=[...old.querySelectorAll('tbody tr')].map(r=>[...r.cells].map(c=>c.innerHTML))});
  const expected=[
   {name:'ТЕСТ ДИСЦИПЛІНАРНИЙ НАКАЗ',values:['догана','00153-к/А','2026-08-19']},
   {name:'ТЕСТ СУДОВЕ РІШЕННЯ',values:['—','—','—']},
   {name:'ТЕСТ БЕЗ ДАТИ НАКАЗУ',values:['звільнення','0007-Б','—']},
   {name:'ТЕСТ ОБИДВА ВИДИ РЕКВІЗИТІВ',values:['догана','0009-К/Б','2026-09-01']}
  ];
  for(const theme of ['light','dark'])for(const width of [1440,390])for(const view of ['directory','task']){
   await page.setViewportSize({width,height:1000});
   await page.evaluate(({theme,view})=>{
    document.documentElement.dataset.theme=theme;
    const dialog=$('#operationalTaskDialog');if(dialog.open)dialog.close();
    $('#referencesView').hidden=view!=='directory';
    if(view==='task'){
     $('#operationalTaskTitle').textContent='НАЗК · локальна синтетична перевірка';$('#operationalTaskSubtitle').textContent='Чотири тестові записи';
     $('#operationalTaskBody').innerHTML='<div class="operational-workspace">'+operationalNazkContext(fixture.task)+'</div>';
     $('#operationalTaskSave').hidden=true;dialog.showModal();
    }
   },{theme,view});
   const table=page.locator(view==='directory'?'#referenceNazk table':'.operational-registry-list table'),rows=table.locator('tbody tr'),n=view==='directory'?6:7;
   assert.equal(await table.locator('thead th').count(),n+3);
   assert.deepEqual((await table.locator('thead th').allTextContents()).slice(-3),['Вид стягнення','№ наказу','Дата наказу']);
   for(const row of expected){const r=rows.filter({hasText:row.name});assert.equal(await r.count(),1);assert.deepEqual((await r.locator('td').allTextContents()).slice(-3),row.values)}
   assert.equal(await rows.count(),4);
   const newCells=await rows.first().locator('td').evaluateAll((cs,n)=>cs.slice(n).map(c=>({width:c.getBoundingClientRect().width,whiteSpace:getComputedStyle(c).whiteSpace})),n);
   assert(newCells.every(c=>c.width>=80&&c.whiteSpace==='nowrap'),'New values must remain legible without letter-by-letter wrapping');
   const retained=await rows.evaluateAll((rs,n)=>rs.map(r=>[...r.cells].slice(0,n).map(c=>c.innerHTML)),n);
   assert.deepEqual(retained,await page.evaluate(view=>view==='directory'?oldReferenceRows:oldTaskRows,view));
   const wrapper=page.locator(view==='directory'?'#referenceNazk .reference-table-wrap':'.operational-registry-list .operational-table');
   const metrics=await wrapper.evaluate(el=>({clientWidth:el.clientWidth,scrollWidth:el.scrollWidth,overflow:getComputedStyle(el).overflowX}));
   if(width===390){assert(metrics.scrollWidth>metrics.clientWidth,'Narrow table must permit horizontal scrolling');assert(['auto','scroll'].includes(metrics.overflow),'Scrolling container must be active')}
   await wrapper.evaluate(el=>el.scrollLeft=0);
   const target=view==='directory'?page.locator('#referenceNazk'):page.locator('#operationalTaskDialog');
   const prefix=`${view}-${theme}-${width}`;
   await target.screenshot({path:path.join(out,prefix+'-left.png')});
   await wrapper.evaluate(el=>el.scrollLeft=el.scrollWidth);
   const scroll=await wrapper.evaluate(el=>({left:el.scrollLeft,right:el.getBoundingClientRect().right,last:el.querySelector('tr').lastElementChild.getBoundingClientRect().right}));
   if(width===390){assert(scroll.left>0);assert(scroll.last<=scroll.right+2,'Last decree date column must be reachable')}
   await target.screenshot({path:path.join(out,prefix+'-right.png')});
   const vertical=page.locator(view==='directory'?'#referenceNazk .reference-table-wrap':'.operational-context-card');
   await vertical.evaluate(el=>el.scrollTop=el.scrollHeight);
   const bottom=await vertical.evaluate(el=>({top:el.scrollTop,edge:el.getBoundingClientRect().bottom,last:el.querySelector('tbody tr:last-child').getBoundingClientRect().bottom}));
   assert(bottom.last<=bottom.edge+2,'Last synthetic record must remain reachable by vertical scrolling');
   await target.screenshot({path:path.join(out,prefix+'-bottom.png')});
   const contrast=await rows.first().locator('td').last().evaluate(cell=>{
    const rgb=s=>(s.match(/[\d.]+/g)||[]).map(Number);
    let el=cell,bg;while(el){const c=rgb(getComputedStyle(el).backgroundColor);if(c.length===3||c[3]===1){bg=c.slice(0,3);break}el=el.parentElement}bg=bg||[255,255,255];
    const fg=rgb(getComputedStyle(cell).color).slice(0,3),lum=c=>c.map(x=>{x/=255;return x<=.04045?x/12.92:((x+.055)/1.055)**2.4}).reduce((s,x,i)=>s+x*[.2126,.7152,.0722][i],0);
    return {fg,bg,ratio:(Math.max(lum(fg),lum(bg))+.05)/(Math.min(lum(fg),lum(bg))+.05)};
   });
   assert(contrast.ratio>=4.5,JSON.stringify(contrast));
   results.push({view,theme,width,records:4,originalCellsUnchanged:true,metrics,scroll,bottom,contrast});
  }
  // Loading / empty / failure rows span all nine directory columns.
  await page.evaluate(()=>{request=async()=>({items:[],total:0,pages:1,courts:[]})});
  await page.evaluate(()=>loadReferenceRegistry('nazk'));assert.equal(await page.locator('#refNazkBody td').getAttribute('colspan'),'9');
  await page.evaluate(()=>{request=async()=>{throw Error('Synthetic failure')}});await page.evaluate(()=>loadReferenceRegistry('nazk'));assert.equal(await page.locator('#refNazkBody td').getAttribute('colspan'),'9');
  await page.evaluate(()=>{request=()=>new Promise(()=>{});void loadReferenceRegistry('nazk')});assert.equal(await page.locator('#refNazkBody td').getAttribute('colspan'),'9');
  // A source number is rendered as text in both tables.
  await page.evaluate(async()=>{
   const text='000А-к/<img src=x onerror="window.injected=1">';fixture.directory.items[0].decree_number=text;fixture.task.nazk_records[0].decree_number=text;
   request=async()=>structuredClone(fixture.directory);await loadReferenceRegistry('nazk');$('#operationalTaskBody').innerHTML=operationalNazkContext(fixture.task);
  });
  assert.equal(await page.locator('#refNazkBody img,.operational-registry-list img').count(),0);
  assert.equal(await page.evaluate(()=>window.injected),undefined);
  assert.equal(await page.locator('#refNazkBody tr').first().locator('td').nth(7).textContent(),'000А-к/<img src=x onerror="window.injected=1">');
  assert.equal(await page.locator('.operational-registry-list tbody tr').first().locator('td').nth(8).textContent(),'000А-к/<img src=x onerror="window.injected=1">');
  assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(out,'browser-results.json'),JSON.stringify({status:'PASS',matrix:results,emptyErrorLoadingColspan:9,htmlEscaping:'PASS',pageErrors:errors,externalRequests:network},null,2));
  console.log(JSON.stringify({status:'PASS',matrix:results.length,syntheticScenariosPerTable:4,screenshots:results.length*3}));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
