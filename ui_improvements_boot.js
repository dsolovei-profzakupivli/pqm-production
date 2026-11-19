/* UI-only installation. No write/sync endpoints are called here. */
(()=>{
  const selectors=['#supplierRegistrySearch','#frameworksSearch','#refAmcuSearch',
    ...['search','code','supplier','cpv','framework','contract','manager','officer','remarks'].map(k=>`input[data-history="${k}"]`)];
  function installClear(input){
    if(input.closest('.pqm-clear-wrap'))return;
    // A span inherits the legacy search-icon positioning and font rules.
    const wrapper=document.createElement('div');wrapper.className='pqm-clear-wrap';
    // Preserve the input's role when it was a direct flex child. These are
    // layout constraints only; the input keeps its own appearance and events.
    const flexParent=getComputedStyle(input.parentElement).display==='flex';
    const original=getComputedStyle(input),layout={flex:original.flex,minWidth:original.minWidth};
    input.before(wrapper);wrapper.append(input);
    // Existing wrapper-specific responsive rules take precedence over the
    // legacy input rules (e.g. the compact AMCU toolbar).
    if(flexParent&&getComputedStyle(wrapper).flex==='0 1 auto'){
      wrapper.style.flex=layout.flex;wrapper.style.minWidth=layout.minWidth;
    }
    const button=document.createElement('button');button.type='button';button.className='pqm-search-clear';
    button.textContent='×';button.title='Очистити поле';button.setAttribute('aria-label',`Очистити: ${input.getAttribute('aria-label')||input.placeholder}`);
    const update=()=>{
      button.hidden=!input.value;
      // Inputs in column dialogs retain their own margins. Anchor inside the
      // actual input box, rather than the wrapper's margin-inclusive box.
      button.style.left=`${input.offsetLeft+input.offsetWidth-27}px`;
      button.style.top=`${input.offsetTop+input.offsetHeight/2}px`;
    };input.addEventListener('input',update);
    button.onclick=()=>{PqmUi.clearInput(input);update()};wrapper.append(button);update();
    new ResizeObserver(update).observe(input);
  }
  const isSearch=input=>!input.hidden&&['text','search'].includes(input.type)&&
    (input.type==='search'||input.classList.contains('multi-search')||/search/i.test(input.id)||input.matches('[data-history],.registry-toolbar input,.edr-monitoring-toolbar input,.work-queue-toolbar input')||/пошук|знайти|search/i.test(input.placeholder+' '+input.getAttribute('aria-label')));
  function scanSearch(root){root.querySelectorAll('input').forEach(input=>{if(isSearch(input))installClear(input)})}
  selectors.forEach(selector=>document.querySelectorAll(selector).forEach(installClear));
  scanSearch(document);
  const clearState=()=>{
    document.querySelectorAll('.pqm-clear-wrap').forEach(w=>{w.querySelector('button').hidden=!w.querySelector('input').value});
    const bulk=document.getElementById('bulkBtn');if(bulk&&!bulk.title)bulk.title='Масове заповнення вибраних заявок';
    PqmUi.formatActionButtons(document);
  };
  document.addEventListener('change',clearState);document.addEventListener('click',()=>requestAnimationFrame(clearState));
  document.addEventListener('input',clearState,true);
  document.addEventListener('focusin',()=>{scanSearch(document);clearState()});
  // Navigation restoration and autofill can set .value without dispatching input.
  setInterval(()=>{if(!document.hidden)clearState()},500);
  clearState();
  let clearQueued=false;
  new MutationObserver(()=>{if(clearQueued)return;clearQueued=true;requestAnimationFrame(()=>{clearQueued=false;scanSearch(document);clearState()})})
    .observe(document.body,{childList:true,subtree:true});
  document.querySelector('#frameworksBody').addEventListener('click',async event=>{
    const button=event.target.closest('[data-copy-framework-number]');if(!button)return;
    event.preventDefault();event.stopPropagation();
    try{await navigator.clipboard.writeText(button.dataset.copyFrameworkNumber);toast('Номер відбору скопійовано')}
    catch{toast('Не вдалося скопіювати номер відбору','error')}
  });
  const expired=document.createElement('button');expired.type='button';expired.id='requestsExpiredFilter';
  expired.textContent='Строк відповіді сплив';expired.setAttribute('aria-pressed','false');
  expired.onclick=()=>{PqmUi.responseExpired=!PqmUi.responseExpired;expired.classList.toggle('active',PqmUi.responseExpired);expired.setAttribute('aria-pressed',String(PqmUi.responseExpired));requestsPage=1;loadViolationReports()};
  document.querySelector('#requestQuickFilters').append(expired);
  const counts=new Map();let refreshing=false;
  function badge(id,count){
    const target=document.getElementById(id);if(!target)return;
    let node=target.querySelector('.action-count-badge');
    if(!node){node=document.createElement('b');node.className='action-count-badge';target.append(node)}
    const ready=Number.isInteger(count)&&count>0;node.hidden=!ready;
    const label=ready?String(count):'';if(node.textContent!==label)node.textContent=label;
    node.setAttribute('aria-label',ready?`Потребують дії: ${count}`:'');
  }
  function paint(){for(const [id,value] of counts){const permission=id==='operationalTasksNav'?'tasks.read':'appeals.read';badge(id,currentMe?.permissions?.[permission]?value:0)}}
  async function refresh(){
    if(refreshing||document.hidden||!currentMe)return;
    refreshing=true;const me=currentMe;
    try{await Promise.all([
      ['tasks.read','operationalTasksNav','/operational-tasks/summary'],
      ['appeals.read','requestsNav','/violation-reports/summary']
    ].map(async([permission,id,path])=>{
      if(!me.permissions?.[permission]){counts.set(id,0);badge(id,0);return}
      try{const result=await request(`${API}${path}`,{cache:'no-store'});if(currentMe!==me)return;
        const value=Number.isInteger(result.count)&&result.count>=0?result.count:null;counts.set(id,value);badge(id,value)}
      catch{counts.set(id,null);badge(id,null)}
    }))}finally{refreshing=false}
  }
  new MutationObserver(paint).observe(document.getElementById('mainNav'),{childList:true,subtree:true});
  // Keep viewing separate from completion: only server state determines counts.
  authReady.then(()=>{clearState();refresh();setInterval(refresh,60000)});
  window.addEventListener('focus',()=>{clearState();refresh()});
  document.addEventListener('visibilitychange',refresh);
  document.getElementById('mainNav').addEventListener('click',event=>{
    const target=event.target.closest('#operationalTasksNav,#requestsNav');
    const permission=target?.id==='operationalTasksNav'?'tasks.read':'appeals.read';
    if(target&&counts.get(target.id)>0&&currentMe?.permissions?.[permission]){
      if(target.id==='operationalTasksNav'){
        resetOperationalKpiFilters();document.getElementById('operationalTaskStatus').value='needs_action';
      }else{
        clearTimeout(requestsTimer);
        for(const id of ['requestsSearch','requestsStatus','requestsReason','requestsDateFrom','requestsDateTo'])document.getElementById(id).value='';
        selectedRequestAuthority='40996564';requestsPage=1;PqmUi.responseExpired=true;
        expired.classList.add('active');expired.setAttribute('aria-pressed','true');
      }
      clearState();
    }
    // The existing tab callback performs navigation and exactly one list load.
    refresh();
  },true);
})();
