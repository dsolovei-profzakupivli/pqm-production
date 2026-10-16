/* UI-only installation. No write/sync endpoints are called here. */
(()=>{
  const selectors=['#supplierRegistrySearch','#frameworksSearch','#refAmcuSearch',
    ...['search','code','supplier','cpv','framework','contract','manager','officer','remarks'].map(k=>`input[data-history="${k}"]`)];
  function installClear(input){
    if(input.closest('.pqm-clear-wrap'))return;
    const wrapper=document.createElement('span');wrapper.className='pqm-clear-wrap';
    input.before(wrapper);wrapper.append(input);
    const button=document.createElement('button');button.type='button';button.className='pqm-search-clear';
    button.textContent='×';button.title='Очистити поле';button.setAttribute('aria-label',`Очистити: ${input.getAttribute('aria-label')||input.placeholder}`);
    const update=()=>{button.hidden=!input.value};input.addEventListener('input',update);
    button.onclick=()=>{PqmUi.clearInput(input);update()};wrapper.append(button);update();
  }
  selectors.forEach(selector=>document.querySelectorAll(selector).forEach(installClear));
  const clearState=()=>{
    document.querySelectorAll('.pqm-clear-wrap').forEach(w=>{w.querySelector('button').hidden=!w.querySelector('input').value});
    const bulk=document.getElementById('bulkBtn');if(bulk&&!bulk.title)bulk.title='Масове заповнення вибраних заявок';
    PqmUi.formatActionButtons(document);
  };
  document.addEventListener('change',clearState);document.addEventListener('click',()=>requestAnimationFrame(clearState));
  clearState();
  let clearQueued=false;
  new MutationObserver(()=>{if(clearQueued)return;clearQueued=true;requestAnimationFrame(()=>{clearQueued=false;clearState()})})
    .observe(document.getElementById('applicationShell'),{childList:true,subtree:true});
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
    node.textContent=ready?String(count):'';node.setAttribute('aria-label',ready?`Потребують дії: ${count}`:'');
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
  new MutationObserver(paint).observe(document.getElementById('mainNav'),{childList:true});
  // Keep viewing separate from completion: only server state determines counts.
  authReady.then(()=>{clearState();refresh();setInterval(refresh,60000)});
  window.addEventListener('focus',()=>{clearState();refresh()});
  document.addEventListener('visibilitychange',refresh);
  document.getElementById('mainNav').addEventListener('click',event=>{
    if(event.target.closest('#operationalTasksNav'))document.getElementById('operationalTaskStatus').value='needs_action';
    refresh();
  },true);
})();
