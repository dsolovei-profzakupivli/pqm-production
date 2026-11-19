/* Exercise per-user application/history layout persistence using real PQM adapters. */
const assert=require('node:assert/strict'),path=require('node:path');
module.exports=async({page,prepare,drag,read,out})=>{
 const app=read('app.js');
 const profile=app.split(/\r?\n/).find(line=>line.startsWith('function profile(){'));
 const saveProfiles=app.split(/\r?\n/).find(line=>line.startsWith('function saveProfiles(){'));
 const saveLayout=app.split(/\r?\n/).find(line=>line.startsWith('let profileSaveTimer;function persistProfileLayout(){'));
 const persistColumns=app.split(/\r?\n/).find(line=>line.startsWith('const persistProfileColumns='));
 const profileColumns=app.split(/\r?\n/).find(line=>line.startsWith('function applicationProfileColumns('));
 const getCols=app.split(/\r?\n/).find(line=>line.startsWith('function getCols(){'));
 const adapters=app.slice(app.indexOf('async function ensurePersonalApplicationProfile(){'),app.indexOf('function cardsDialog(){'));
 assert(profile&&saveProfiles&&saveLayout&&persistColumns&&profileColumns&&getCols&&adapters.includes('async function columnsDialog()'));
 async function applications(user='alice'){
  await prepare(page,user);
  await page.evaluate(async user=>{
   document.body.dataset.authRole='viewer';document.querySelector('#referencesView').hidden=true;document.querySelector('#applicationsView').hidden=false;
   window.currentMe={role:'viewer'};window.activeKey='pqm.test.active:'+user;window.columns=[{key:'participant',label:'Назва учасника',width:260,order:0,visible:true},{key:'edrpou',label:'Код',width:140,order:1,visible:true}];
   window.profileLayoutGeneration=0;window.profileSaveTimer=null;window.renderProfiles=()=>{};window.toast=(...args)=>window.__lastToast=args;window.loadProfiles=async()=>{const data=await request('/api/application-profiles');profiles=data.items;const selected=profiles.find(p=>p.id===localStorage.getItem(activeKey)),defaultSystem=profiles.find(p=>p.is_system),personal=defaultSystem&&profiles.find(p=>!p.is_system&&p.source_system_profile_id===defaultSystem.id);activeProfileId=selected?.id||personal?.id||defaultSystem?.id||profiles[0]?.id;return true};await loadProfiles();
   window.render=()=>{const cs=getCols(),table=document.querySelector('#applicationsTable');table.style.width=table.style.minWidth=cs.reduce((sum,c)=>sum+c.width,0)+'px';table.querySelector('thead').innerHTML='<tr>'+cs.map(c=>`<th data-column-key="${c.key}" style="width:${c.width}px;min-width:${c.width}px;max-width:${c.width}px">${c.label}</th>`).join('')+'</tr>';table.querySelector('tbody').innerHTML='<tr>'+cs.map(c=>`<td style="width:${c.width}px">Тест</td>`).join('')+'</tr>'};
   document.querySelector('#columnsBtn').onclick=()=>columnsDialog();
  },user);
  await page.addScriptTag({content:[profile,saveProfiles,saveLayout,persistColumns,profileColumns,getCols,adapters].join('\n')});
  await page.evaluate(()=>render());await page.locator('#applicationsTable th.column-resizable').first().waitFor();
 }
 await page.setViewportSize({width:1440,height:1000});await applications('alice');
 await page.evaluate(async()=>await columnsDialog());assert.notEqual(await page.evaluate(()=>profile().id),'system-main');
 await page.locator('#columnsList [data-key="participant"] .col-width').fill('440');await page.locator('#columnsList [data-key="participant"] .col-width').dispatchEvent('change');await page.waitForTimeout(350);
 assert.equal(await page.locator('#applicationsTable th').first().evaluate(th=>Math.round(th.getBoundingClientRect().width)),440);
 await page.locator('#columnsList [data-key="participant"] .col-down').click();await page.waitForTimeout(350);assert.equal(await page.evaluate(()=>getCols()[0].key),'edrpou');await page.evaluate(()=>document.querySelector('#columnsDialog').close());
 await applications('alice');assert.equal(await page.locator('#applicationsTable th').first().getAttribute('data-column-key'),'edrpou');assert.equal(Math.round(await page.locator('#applicationsTable th[data-column-key="participant"]').evaluate(th=>th.getBoundingClientRect().width)),440);
 await applications('bob');assert.equal(await page.locator('#applicationsTable th').first().getAttribute('data-column-key'),'participant');assert.equal(Math.round(await page.locator('#applicationsTable th').first().evaluate(th=>th.getBoundingClientRect().width)),260);
 await applications('alice');await drag(page,'#applicationsTable',1,65);await page.waitForTimeout(350);assert.equal(Math.round(await page.locator('#applicationsTable th[data-column-key="participant"]').evaluate(th=>th.getBoundingClientRect().width)),505);
 for(const theme of ['light','dark'])for(const width of [1440,390]){await page.setViewportSize({width,height:1000});await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);await page.evaluate(async()=>await columnsDialog());await page.screenshot({path:path.join(out,`applications-viewer-${theme}-${width}-settings.png`),fullPage:true});await page.locator('#columnsDialog').evaluate(dialog=>dialog.close())}
 const directProfileWrite=await page.evaluate(async()=>{const p=profile();try{await request(`/api/application-profiles/${encodeURIComponent(p.id)}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({columns:p.columns})});return true}catch{return false}});assert(directProfileWrite,'Owner may save own personal layout through existing profile API');
 const forbiddenSystemWrite=await page.evaluate(async()=>{try{await request('/api/application-profiles/system-main',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({columns:[]})});return false}catch{return true}});assert(forbiddenSystemWrite,'Viewer cannot save shared system profile');

 async function history(user='alice'){
  await prepare(page,user);
  await page.evaluate(()=>{document.body.dataset.authRole='viewer';document.querySelector('#referencesView').hidden=true;document.querySelector('#historyView').hidden=false;window.installViewportDrag=()=>{};window.drawHistorySort=()=>{};window.historyItems=[]});
  await page.addScriptTag({content:read('history_columns.js')});await page.evaluate(async()=>{await ensureHistoryColumns();renderHistoryTable()});await page.locator('#historyView th.column-resizable').first().waitFor();
 }
 await page.setViewportSize({width:1440,height:1000});await history('alice');assert.equal(await page.locator('#historyColumnsButton').isVisible(),true);
 await page.locator('#historyColumnsButton').click();await page.locator('#historyColumnList [data-key="supplier"] .col-width').fill('420');await page.locator('#historyColumnList [data-key="supplier"] .col-width').dispatchEvent('change');await page.locator('#historyColumnList [data-key="supplier"] .col-down').click();await page.locator('#historyColumnSave').click();await page.waitForFunction(()=>document.querySelector('#historyView thead th')?.dataset.historyColumn==='code');
 assert.equal(await page.locator('#historyView thead th').first().getAttribute('data-history-column'),'code');assert.equal(Math.round(await page.locator('#historyView th[data-history-column="supplier"]').evaluate(th=>th.getBoundingClientRect().width)),420);
 await history('alice');assert.equal(await page.locator('#historyView thead th').first().getAttribute('data-history-column'),'code');assert.equal(await page.locator('#historyColumnMessage').textContent(),'');
 await history('bob');assert.equal(await page.locator('#historyView thead th').first().getAttribute('data-history-column'),'supplier');assert.equal(Math.round(await page.locator('#historyView th[data-history-column="supplier"]').evaluate(th=>th.getBoundingClientRect().width)),180);
 await history('alice');await drag(page,'#historyView table',1,70);await page.waitForTimeout(350);assert.equal(Math.round(await page.locator('#historyView th[data-history-column="supplier"]').evaluate(th=>th.getBoundingClientRect().width)),490);
 for(const theme of ['light','dark'])for(const width of [1440,390]){await page.setViewportSize({width,height:1000});await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);await page.locator('#historyColumnsButton').click();await page.screenshot({path:path.join(out,`history-viewer-${theme}-${width}-settings.png`),fullPage:true});await page.locator('#historyColumnCancel').click()}
 const noLocalColumnSource=await page.evaluate(()=>Object.keys(localStorage).some(key=>key.includes('table-widths')));assert.equal(noLocalColumnSource,false);
 return ['Applications: every role edits own server profile; system profile remains protected; width/order survive F5 and are isolated by account','History: viewer width/order save through existing owner-scoped API; F5 and second account isolation confirmed','Applications/history personal settings do not use localStorage; both themes and narrow/wide viewports rendered'];
};
