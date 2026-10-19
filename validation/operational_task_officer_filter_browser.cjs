const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('C:/Users/User/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root=path.resolve(__dirname,'..'),out=path.join(root,'evidence','operational-task-officer-filter');
const browserPath='C:/Users/User/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe';
const read=name=>fs.readFileSync(path.join(root,name),'utf8');
function block(source,startText,endText){const start=source.indexOf(startText),end=source.indexOf(endText,start);assert(start>=0&&end>start,`source block found: ${startText}`);return source.slice(start,end)}
(async()=>{
 fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({headless:true,executablePath:browserPath,args:['--no-sandbox']});
 try{
  const page=await browser.newPage({viewport:{width:1500,height:960},timezoneId:'Europe/Kyiv'}),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/*',route=>route.abort());
  const html=read('index.html').replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,'');
  await page.setContent(html);
  for(const name of ['styles.css','theme.css','modules.css','filters.css'])await page.addStyleTag({content:read(name)});
  await page.evaluate(()=>{
    document.querySelector('#loginGate')?.setAttribute('hidden','');
    document.querySelector('#applicationShell')?.removeAttribute('hidden');
    document.querySelectorAll('main,[id$="View"]').forEach(node=>{if(node.id!=='operationalTasksView')node.hidden=true});
    const view=document.querySelector('#operationalTasksView');view?.removeAttribute('hidden');
    document.documentElement.dataset.theme='light';
    window.$=selector=>document.querySelector(selector);window.$$=selector=>[...document.querySelectorAll(selector)];
    window.API='/api';window.operationalTaskTypeLabels={nazk_check:'НАЗК · перевірка',amcu_exclusion:'АМКУ · виключення',warning_block:'Блокування за попередженнями',termination_exclusion:'Припинення · виключення'};
    window.esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
    window.formatOfficerName=value=>value||'';window.displayDate=value=>value||'';
    window.operationalActionColumnVisible=status=>status!=='completed';
    window.operationalTaskStatusLabel=item=>item.status;
    window.operationalListAction=()=>'';window.operationalTriggerHtml=()=>'';window.operationalBasisHtml=()=>'';window.operationalResultHtml=()=>'';window.operationalDecisionHtml=()=>'';
    window.operationalBasisDirection='';window.operationalListGeneration=0;
    window.__synthetic=[
      {id:'active-42',task_type:'warning_block',status:'in_progress',officer:'42',assigned_officer_name:'Ірина Мельник',supplier_name_snapshot:'Активне призначення',supplier_code:'10000001',created_at:'2026-10-18'},
      {id:'active-43',task_type:'warning_block',status:'new',officer:'43',assigned_officer_name:'Марина Шевченко',supplier_name_snapshot:'Друге активне призначення',supplier_code:'10000007',created_at:'2026-10-18'},
      {id:'done-7',task_type:'warning_block',status:'completed',officer:'7',assigned_officer_name:'Оксана Петренко',supplier_name_snapshot:'Завершене призначення',supplier_code:'10000002',created_at:'2026-10-17'},
      {id:'nazk-9',task_type:'nazk_check',status:'new',officer:'9',assigned_officer_name:'Тетяна Бондар',supplier_name_snapshot:'НАЗК canonical',supplier_code:'10000003',created_at:'2026-10-16'},
      {id:'legacy',task_type:'nazk_check',status:'completed',officer:'__legacy_snapshot__:Олена Коваль',assigned_officer_name:'Олена Коваль',supplier_name_snapshot:'Історичний snapshot',supplier_code:'10000004',created_at:'2026-10-15'},
      {id:'unassigned',task_type:'warning_block',status:'new',officer:'__unassigned__',assigned_officer_name:'',supplier_name_snapshot:'Без призначення',supplier_code:'10000005',created_at:'2026-10-14'}
    ];
    window.request=async url=>{
      const params=new URL(url,'http://local').searchParams,group=params.get('status_group')||'active',officer=params.get('officer')||'',type=params.get('type')||'';
      window.__lastParams={group,officer,type};
      const items=__synthetic.filter(item=>(group==='historical'?['completed','cancelled'].includes(item.status):group==='active'? !['completed','cancelled'].includes(item.status):item.status===group)&&(!officer||item.officer===officer)&&(!type||item.task_type===type));
      window.__lastReturnedIds=items.map(item=>item.id);
      return {items,total:items.length,kpis:{active:4,completed:2},type_counts:{nazk_check:2,warning_block:4},status_group:group,officers:[
        {value:'42',full_name:'Ірина Мельник'},{value:'43',full_name:'Марина Шевченко'},
        {value:'7',full_name:'Оксана Петренко',historical_snapshot:true},
        {value:'9',full_name:'Тетяна Бондар'},
        {value:'__legacy_snapshot__:Олена Коваль',full_name:'Олена Коваль',historical_snapshot:true}
      ]};
    };
  });
  const app=read('app.js');
  const code=[
    block(app,'function operationalTaskParams()','function operationalSummaryLink('),
    block(app,'function operationalTaskTypeMarker(','function operationalTaskEmptyMessage('),
    block(app,'function operationalTaskEmptyMessage()','let operationalListGeneration='),
    block(app,'let operationalListGeneration=','$(\'#operationalTasksNav\').onclick=')
  ].join('\n');
  await page.addScriptTag({content:code});
  await page.evaluate(()=>{window.__refresh=loadOperationalTasks});
  await page.evaluate(()=>__refresh());
  for(const [officer,expected] of [['42','active-42'],['43','active-43'],['9','nazk-9']]){
    await page.locator('#operationalTaskStatus').selectOption('active');
    await page.locator('#operationalTaskOfficer').selectOption(officer);
    await page.evaluate(()=>__refresh());
    assert.deepEqual(await page.locator('#operationalTasksBody tr[data-task-id]').evaluateAll(rows=>rows.map(row=>row.dataset.taskId)),[expected],`officer ${officer} filters its own task`);
  }
  await page.locator('#operationalTaskStatus').selectOption('completed');
  await page.locator('#operationalTaskOfficer').selectOption('7');
  await page.evaluate(()=>__refresh());
  assert.equal(await page.locator('#operationalTaskOfficer').inputValue(),'7');
  assert.deepEqual(await page.locator('#operationalTasksBody tr[data-task-id]').evaluateAll(rows=>rows.map(row=>row.dataset.taskId)),['done-7']);
  await page.locator('#operationalTaskStatus').selectOption('active');
  await page.evaluate(()=>__refresh());
  assert.deepEqual(await page.evaluate(()=>window.__lastParams),{group:'active',officer:'7',type:''});
  assert.equal(await page.locator('#operationalTaskOfficer').inputValue(),'7','selected UO persists when status changes');
  const afterStatusIds=await page.locator('#operationalTasksBody tr[data-task-id]').evaluateAll(rows=>rows.map(row=>row.dataset.taskId));
  assert.deepEqual(afterStatusIds,[],'status update should keep the selected officer and show no matching active tasks: '+JSON.stringify({afterStatusIds,requested:await page.evaluate(()=>window.__lastParams),returned:await page.evaluate(()=>window.__lastReturnedIds),status:await page.locator('#operationalTaskStatus').inputValue()}));
  await page.locator('#operationalTaskOfficer').selectOption('__unassigned__');
  await page.evaluate(()=>__refresh());
  assert.deepEqual(await page.locator('#operationalTasksBody tr[data-task-id]').evaluateAll(rows=>rows.map(row=>row.dataset.taskId)),['unassigned']);
  await page.locator('#operationalTaskOfficer').selectOption('__legacy_snapshot__:Олена Коваль');
  await page.locator('#operationalTaskStatus').selectOption('historical');
  await page.evaluate(()=>__refresh());
  assert.deepEqual(await page.locator('#operationalTasksBody tr[data-task-id]').evaluateAll(rows=>rows.map(row=>row.dataset.taskId)),['legacy']);
  for(const theme of ['light','dark']){
    await page.evaluate(value=>document.documentElement.dataset.theme=value,theme);
    await page.evaluate(()=>__refresh());
    const select=page.locator('#operationalTaskOfficer'),box=await select.boundingBox();
    assert(box&&box.width>100,'officer filter is visible in '+theme+' theme');
    assert.equal(await select.inputValue(),'__legacy_snapshot__:Олена Коваль');
    const labels=await select.locator('option').allTextContents();
    assert.deepEqual(labels,['Усі УО','Ірина Мельник','Марина Шевченко','Оксана Петренко · Історична УО','Тетяна Бондар','Олена Коваль · Історична УО','Не призначено']);
    assert(labels.every(label=>!label.includes('без ID')&&!label.includes('__legacy_snapshot__')),'technical IDs are not shown to the user');
    await page.screenshot({path:path.join(out,`officer-filter-${theme}.png`),fullPage:true});
    const initialSize=await select.getAttribute('size');
    await select.evaluate(el=>{el.size=el.options.length;el.scrollIntoView({block:'center'})});
    const expanded=await select.boundingBox();
    assert(expanded&&expanded.x>=0&&expanded.y>=0&&expanded.x+expanded.width<=1500&&expanded.y+expanded.height<=960,'expanded officer list stays within viewport');
    await page.screenshot({path:path.join(out,`officer-filter-open-${theme}.png`),fullPage:true});
    await select.evaluate((el,size)=>{if(size===null)el.removeAttribute('size');else el.setAttribute('size',size)},initialSize);
  }
  const visualState=await page.evaluate(()=>({selectedLabel:document.querySelector('#operationalTaskOfficer').selectedOptions[0]?.textContent,rowText:[...document.querySelectorAll('#operationalTasksBody tr[data-task-id]')].map(row=>row.innerText),rowBounds:document.querySelector('#operationalTasksBody tr[data-task-id]')?.getBoundingClientRect().toJSON()}));
  console.log('browser visual evidence: '+JSON.stringify(visualState));
  assert.deepEqual(errors,[]);
  console.log('operational task officer browser checks: PASS (light + dark, active IDs, completed, NAZK, legacy snapshot, unassigned; open-list evidence)');
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exit(1)});
