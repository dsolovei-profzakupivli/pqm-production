/* Presentation-only navbar registry. Icons are neutral placeholders pending UI approval. */
(function(){
  const svg=(body)=>`<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">${body}</svg>`;
  const BUILTIN_ICONS={
    history:svg('<path d="M12 7v5l3 2M4.9 5.5A8 8 0 1 1 4 15M4 5v5h5"/>'),
    requests:svg('<path d="M5 4h14v13H9l-4 3V4Zm3 4h8M8 12h5"/>'),
    references:svg('<path d="M5 4h6a3 3 0 0 1 3 3v13a3 3 0 0 0-3-3H5V4Zm14 0h-2a3 3 0 0 0-3 3v13a3 3 0 0 1 3-3h2V4Z"/>'),
    frameworks:svg('<path d="M4 6h16M4 12h16M4 18h16M7 4v4m5 2v4m5 2v4"/>'),
    procurements:svg('<path d="M5 7h14l-1 12H6L5 7Zm3 0V5a4 4 0 0 1 8 0v2"/>'),
    audit:svg('<path d="M6 3h12v18H6V3Zm3 5h6M9 12h6M9 16h4"/>'),
    administration:svg('<path d="M4 6h10M18 6h2M4 12h2m4 0h10M4 18h8m4 0h4M14 4v4M6 10v4m6 2v4"/>'),
  };
  let customIcons={};const icons=()=>({...BUILTIN_ICONS,...customIcons});
  const ITEMS=[
    {id:'workQueueNav',module:'workQueue',route:'workQueue',label:'Робота УО',tooltip:'Робота УО',iconKey:null,displayMode:'text',order:1,permission:'work.read',visible:true},
    {id:'applicationsNav',module:'applications',route:'applications',label:'Реєстр заявок',tooltip:'Реєстр заявок',iconKey:null,displayMode:'text',order:2,permission:'applications.read',visible:true},
    {id:'historyNav',module:'history',route:'history',label:'Історія заявок',tooltip:'Історія заявок',iconKey:'history',displayMode:'icon',order:3,permission:'applications.read',visible:true},
    {id:'suppliersNav',module:'suppliers',route:'suppliers',label:'База постачальників',tooltip:'База постачальників',iconKey:null,displayMode:'text',order:4,permission:'suppliers.read',visible:true},
    {id:'requestsNav',module:'requests',route:'requests',label:'Звернення замовників',tooltip:'Звернення замовників',iconKey:'requests',displayMode:'icon',order:5,permission:'appeals.read',visible:true},
    {id:'referencesNav',module:'references',route:'references',label:'Довідники',tooltip:'Довідники',iconKey:'references',displayMode:'icon',order:6,permission:'references.read',visible:true},
    {id:'operationalTasksNav',module:'operationalTasks',route:'operationalTasks',label:'Операційні задачі',tooltip:'Операційні задачі',iconKey:null,displayMode:'text',order:7,permission:'tasks.read',visible:true},
    {id:'frameworksNav',module:'frameworks',route:'frameworks',label:'Відбори',tooltip:'Відбори',iconKey:'frameworks',displayMode:'icon',order:8,permission:'frameworks.read',visible:true},
    {id:'procurementsNav',module:'procurements',route:'procurements',label:'Закупівлі за відборами',tooltip:'Закупівлі за відборами',iconKey:'procurements',displayMode:'icon',order:9,permission:'suppliers.read',visible:true},
    {id:'auditBtn',module:'audit',route:'audit',label:'Журнал змін',tooltip:'Журнал змін',iconKey:'audit',displayMode:'icon',order:10,permission:'admin.read',visible:true},
    {id:'administrationNav',module:'administration',route:'administration',label:'Адміністрування',tooltip:'Адміністрування',iconKey:'administration',displayMode:'icon',order:11,permission:'role:admin',visible:true},
    {id:'edrMonitoringNav',module:'edrMonitoring',route:'edrMonitoring',label:'Перевірка ЄДР',tooltip:'Перевірка ЄДР',iconKey:null,displayMode:'text',order:12,permission:'suppliers.read',visible:true},
  ];
  const nav=document.getElementById('mainNav');let currentOverrides={};let currentAccess=null;
  const resolvedItems=overrides=>ITEMS.map(base=>({...base,...(overrides[base.id]||{})})).sort((a,b)=>a.order-b.order);
  const permissionAllows=item=>!currentAccess||!item.permission||(item.permission==='role:admin'?currentAccess.role==='admin':Boolean(currentAccess.permissions?.[item.permission]));
  function canonicalActiveModule(){
    const modules=new Set(ITEMS.map(item=>item.module));
    const route=new URL(location.href).searchParams.get('view');
    if(modules.has(route))return route;
    try{const persisted=localStorage.getItem('pqm.activeModule');if(modules.has(persisted))return persisted}catch{}
    return'applications';
  }
  function render(overrides=currentOverrides){currentOverrides=overrides&&typeof overrides==='object'?overrides:{};
   const selectedModule=canonicalActiveModule();
   for(const item of resolvedItems(currentOverrides)){
    let button=document.getElementById(item.id);if(!button){button=document.createElement('button');button.type='button';button.id=item.id}
    button.dataset.navModule=item.module;
    button.dataset.navRoute=item.route;
    if(item.permission)button.dataset.navPermission=item.permission;
    button.classList.toggle('main-nav-icon',item.displayMode==='icon');
    button.classList.toggle('main-nav-text',item.displayMode==='text');
    button.classList.toggle('main-nav-icon-text',item.displayMode==='icon-text');
    button.classList.toggle('nav-active',item.module===selectedModule);
    button.title=item.tooltip;button.setAttribute('aria-label',item.label);
    const icon=icons()[item.iconKey]||'<span class="nav-icon-slot" aria-hidden="true"></span>';
    if(item.displayMode==='icon')button.innerHTML=icon;
    else if(item.displayMode==='icon-text')button.innerHTML=`${icon}<span>${item.label}</span>`;
    else button.textContent=item.label;
    button.dataset.navVisible=String(item.visible!==false);button.hidden=item.visible===false||!permissionAllows(item);nav.append(button);
   }
  }
  function applyAccess(me){currentAccess=me||null;render(currentOverrides)}
  render();
  window.PQM_NAV_ICON_LIBRARY=Object.freeze(icons());
  window.PQM_NAVIGATION_CONFIG=Object.freeze(ITEMS.map(item=>Object.freeze({...item})));
  window.pqmRenderNavigation=render;window.pqmApplyNavigationAccess=applyAccess;window.pqmResolvedNavigation=()=>resolvedItems(currentOverrides);
  window.pqmSetNavigationIcons=items=>{customIcons=Object.fromEntries((items||[]).map(item=>[item.icon_key,item.svg]));window.PQM_NAV_ICON_LIBRARY=Object.freeze(icons());render(currentOverrides)};
})();
