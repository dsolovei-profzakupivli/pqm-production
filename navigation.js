// Session-local screen history. Browser entries contain opaque IDs, never form data.
(()=>{
  const session=crypto.randomUUID(),entries=new Map(),nativeReplace=history.replaceState.bind(history);
  let current=null,restoring=false,serial=0,tab=document.querySelector('[data-admin-tab].active')?.dataset.adminTab||'frameworks';
  const view=()=>document.getElementById(activeModule==='frameworks'?'frameworkAnalyticsView':activeModule+'View');
  const clone=x=>structuredClone(x);
  const button=document.createElement('button');button.type='button';button.textContent='← Назад';button.id='pqmBack';button.hidden=true;
  button.style.cssText='margin:4px 12px;flex:0 0 auto';document.querySelector('header')?.append(button);
  if(!button.isConnected)document.body.prepend(button);
  const dialog=document.getElementById('supplierProfileDialog'),dialogButton=button.cloneNode(true);dialogButton.id='pqmDialogBack';dialog.prepend(dialogButton);
  function update(){for(const b of [button,dialogButton]){b.hidden=!current?.previous;b.disabled=restoring}}
  function values(){const root=view();return [...(root?.querySelectorAll('input[id],select[id],textarea[id]')||[])].filter(e=>!e.closest('tbody,dialog')&&!['password','file','hidden'].includes(e.type)&&(activeModule!=='administration'||e.closest('#adminSchemaPanel'))).map(e=>({id:e.id,value:e.value,checked:e.checked,selected:e.multiple?[...e.selectedOptions].map(o=>o.value):null}))}
  function restoreValues(items){for(const x of items||[]){const e=document.getElementById(x.id);if(!e)continue;e.value=x.value;if('checked'in e)e.checked=x.checked;if(x.selected)for(const o of e.options)o.selected=x.selected.includes(o.value)}}
  const models={
    applications:{get:()=>({page,sortKey,sortDirection,multiSort,officerFilter,categoryFilter,activeProfileId,activeRow,selected:[...selected],layout:profile().columns,kpis:profile().kpis,deepLinkSubmissionId,selections:Object.fromEntries(Object.entries(filterSelections).map(([k,v])=>[k,[...v]]))}),set:s=>{({page,sortKey,sortDirection,multiSort,officerFilter,categoryFilter,activeProfileId,activeRow,deepLinkSubmissionId}=s);selected.clear();(s.selected||[]).forEach(x=>selected.add(x));profile().columns=s.layout;profile().kpis=s.kpis;for(const [k,v]of Object.entries(s.selections)){filterSelections[k].clear();v.forEach(x=>filterSelections[k].add(x))}syncPrimaryFilters();renderProfiles()},load:()=>loadRows()},
    history:{get:()=>({historyPage,historySorts,historyColumns}),set:s=>{({historyPage,historySorts,historyColumns}=s);drawHistorySort()},load:()=>loadApplicationHistory()},
    suppliers:{get:()=>({supplierRegistryPage,supplierRegistryRisk}),set:s=>{({supplierRegistryPage,supplierRegistryRisk}=s)},load:()=>loadQualifiedSuppliersFiltered()},
    frameworks:{get:()=>({frameworkPage,frameworkSort,frameworkDirection}),set:s=>{({frameworkPage,frameworkSort,frameworkDirection}=s)},load:()=>loadFrameworkAnalytics()},
    procurements:{get:()=>({supplierProcurementPage}),set:s=>{({supplierProcurementPage}=s)},load:()=>loadSupplierProcurements()},
    requests:{get:()=>({requestsPage,selectedRequestAuthority}),set:s=>{({requestsPage,selectedRequestAuthority}=s)},load:()=>loadViolationReports()},
    workQueue:{get:()=>({workQueuePage}),set:s=>{({workQueuePage}=s)},load:()=>loadWorkQueue()},
    references:{get:()=>({referenceTab,pages:{...referencePages}}),set:s=>{referenceTab=s.referenceTab;Object.assign(referencePages,s.pages)},load:()=>loadReferenceRegistry(referenceTab)}
  };
  function snapshot(){if(!current||restoring)return;current.controls=values();current.model=clone(models[activeModule]?.get()||{});current.scroll=[...document.querySelectorAll('[id]')].filter(e=>e.scrollTop||e.scrollLeft).map(e=>[e.id,e.scrollLeft,e.scrollTop]);current.window=[scrollX,scrollY];current.url=location.href}
  // Existing filter/module code replaces URLs. Retain the opaque navigation token.
  history.replaceState=function(state,title,url){return nativeReplace({...state,pqmNavigation:history.state?.pqmNavigation},title,url)};
  function enter(route){if(restoring)return;if(current&&JSON.stringify(current.route)===JSON.stringify(route))return;
    if(current?.fresh&&current.route.module===route.module&&!route.supplier&&!current.route.supplier){current.route=route;return}
    snapshot();const previous=current?.id||null;current={id:++serial,previous,route,fresh:true};const added=current;queueMicrotask(()=>added.fresh=false);entries.set(current.id,current);const url=new URL(location.href);url.searchParams.set('view',route.module);history.pushState({pqmNavigation:{session,id:current.id}},'',url);update()}
  const originalModule=showModule,originalTab=setAdminTab,originalSupplier=openSupplierProfile,originalReference=setReferenceTab;
  showModule=function(name){if(!moduleNames.includes(name))name='applications';enter({module:name,tab:name==='administration'?tab:null,...(name==='references'?{reference:referenceTab}:{})});if(dialog.open)dialog.close();return originalModule(name)};
  setAdminTab=function(name){if(activeModule==='administration')enter({module:'administration',tab:name});tab=name;return originalTab(name)};
  setReferenceTab=function(name){if(activeModule==='references')enter({module:'references',tab:null,reference:name});return originalReference(name)};
  openSupplierProfile=async function(code,context={}){enter({module:activeModule,tab:activeModule==='administration'?tab:null,supplier:String(code),context});const result=await originalSupplier(code,context);update();return result};
  async function restore(entry){restoring=true;update();try{
    clearTimeout(searchTimer);clearTimeout(historyTimer);clearTimeout(supplierRegistryTimer);clearTimeout(frameworkTimer);clearTimeout(workQueueTimer);clearTimeout(requestsTimer);clearTimeout(referenceTimer);
    if(dialog.open)dialog.close();current=entry;originalModule(entry.route.module);
    if(entry.route.tab){tab=entry.route.tab;await originalTab(tab)}
    restoreValues(entry.controls);if(entry.model&&models[entry.route.module])models[entry.route.module].set(clone(entry.model));
    if(entry.route.module==='applications'){
      const filters={supplier:['supplierCodeFilter','Коди ЄДРПОУ'],status:['statusFilter','Усі статуси'],marketplace:['marketplaceDecisionFilter','Дія на майданчику'],registry:['registryStatusFilter','Будь-який стан у відборі'],framework:['frameworkFilter','Усі відбори'],dk:['dkFilter','Усі коди ДК']};
      for(const [key,[id,label]]of Object.entries(filters)){const el=document.getElementById(id);if(!el)continue;for(const input of el.querySelectorAll('input[type=checkbox]'))input.checked=filterSelections[key].has(input.value);updateMultiSummary(id,label,filterSelections[key],value=>key==='marketplace'?(marketplaceFilterLabels[value]||value):value)}
    }
    if(entry.route.module==='history')syncHistorySupplierCardButton();
    if(entry.route.reference)originalReference(entry.route.reference);
    if(entry.model)await models[entry.route.module]?.load();
    if(entry.route.module==='applications'&&entry.model){models.applications.set(clone(entry.model));render()}
    if(entry.route.supplier)await originalSupplier(entry.route.supplier,entry.route.context);
    restoreValues(entry.controls);
    if(entry.route.tab==='schema')document.getElementById('schemaSearch').dispatchEvent(new Event('input',{bubbles:true}));
    await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
    for(const e of document.querySelectorAll('[id]')){if(e.scrollTop)e.scrollTop=0;if(e.scrollLeft)e.scrollLeft=0}
    for(const [id,x,y]of entry.scroll||[]){const e=document.getElementById(id);if(e){e.scrollLeft=x;e.scrollTop=y}}
    window.scrollTo(...(entry.window||[0,0]));
  }finally{restoring=false;update()}}
  let restoreQueue=Promise.resolve();
  function enqueue(entry){restoreQueue=restoreQueue.then(()=>restore(entry)).catch(()=>toast('Не вдалося повністю відновити екран.','warning'))}
  window.addEventListener('popstate',event=>{snapshot();const token=event.state?.pqmNavigation,entry=token?.session===session?entries.get(token.id):null;if(entry){enqueue(entry)}else{current={id:++serial,previous:null,route:{module:new URL(location.href).searchParams.get('view')||'applications',tab:null}};entries.set(current.id,current);enqueue(current);nativeReplace({pqmNavigation:{session,id:current.id}},'',location.href)}});
  const back=()=>{if(current?.previous&&!restoring){snapshot();history.back()}};button.onclick=dialogButton.onclick=back;
  // Capture before legacy links close the supplier dialog or alter destination filters.
  document.addEventListener('click',snapshot,true);
  dialog.addEventListener('close',()=>{if(!restoring&&current?.route.supplier&&!dialog.open)back()});
  current={id:++serial,previous:null,route:{module:activeModule,tab:activeModule==='administration'?tab:null}};entries.set(current.id,current);
  nativeReplace({pqmNavigation:{session,id:current.id}},'',location.href);history.scrollRestoration='manual';update();
})();
