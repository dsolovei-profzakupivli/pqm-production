/* Read-only Sandbox preview. Existing task/profile handlers and layouts are untouched. */
(()=>{
  'use strict';
  const root=document.querySelector('#operationalTasksView');
  const panel=document.querySelector('#nazkPreviewPanel');
  const tabs=document.querySelector('#nazkPreviewTabs');
  if(!root||!panel||!tabs)return;
  const q=id=>document.getElementById(id);
  const escape=value=>String(value??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const groups={candidate:'Кандидат',existing:'Уже в роботі',completed:'Завершено',inactive:'Неактивний',blocked:'Недостатньо умов',excluded:'Виключено'};
  const legacy=[...root.children].filter(node=>node.matches('#operationalTaskKpis,.operational-task-toolbar,.supplier-table-card'));
  const typeMarkers=q('operationalTaskTypes');if(typeMarkers)legacy.push(typeMarkers);
  const workStatuses={needs_review:'Потребує перевірки',waiting_response:'Очікується відповідь',request_to_supplier:'Запит постачальнику',request_to_nazk:'Запит до НАЗК',completed:'Завершено',legacy_archived:'Архівний цикл',not_current:'Неактуально',new:'Нова',in_progress:'В роботі',awaiting_response:'Очікується відповідь',waiting_external:'Очікується зовнішня відповідь',ready_for_document:'Готова до документа',awaiting_publication:'Очікується публікація',awaiting_sync:'Очікується синхронізація',active_blocking:'Блокування діє',cancelled:'Скасована'};
  const oldHidden=new Map();let selected=false,page=1,pages=1,generation=0,timer,items=[];
  function allowed(){const me=typeof currentMe!=='undefined'?currentMe:null;return me?.ui_features?.nazk_preview===true&&me?.permissions?.['tasks.read']===true&&me?.permissions?.['suppliers.read']===true;}
  function sync(){tabs.hidden=!allowed();if(tabs.hidden&&selected)select(false);}
  function select(preview){
    if(preview&&!allowed())return;
    selected=preview;panel.hidden=!preview;
    for(const node of legacy){if(preview){if(!oldHidden.has(node))oldHidden.set(node,node.hidden);node.hidden=true;}else if(oldHidden.has(node)){node.hidden=oldHidden.get(node);oldHidden.delete(node);}}
    tabs.querySelectorAll('[data-nazk-view]').forEach(button=>button.setAttribute('aria-pressed',String((button.dataset.nazkView==='preview')===preview)));
    if(preview)load();else generation++;
  }
  function options(){const params=new URLSearchParams({scope:q('nazkPreviewScope').value,page:String(page),size:'100'});for(const [name,id]of[['search','nazkPreviewSearch'],['state','nazkPreviewState'],['reason','nazkPreviewReason'],['group','nazkPreviewGroup']]){const value=q(id).value.trim();if(value)params.set(name,value);}return params;}
  function dictionaries(id,values){const control=q(id),selected=control.value;for(const [key,label]of Object.entries(values)){if(![...control.options].some(option=>option.value===key))control.add(new Option(label,key));}control.value=selected;}
  async function load(){
    if(!selected||!allowed())return;const requestId=++generation;
    q('nazkPreviewMessage').textContent='Завантаження попереднього перегляду…';
    q('nazkPreviewRefresh').disabled=true;
    try{
      const data=await request(`/api/operational-tasks/nazk-preview?${options()}`);
      if(requestId!==generation||!selected||!allowed())return;
      items=data.items||[];pages=data.pages||1;
      dictionaries('nazkPreviewState',data.states||{});dictionaries('nazkPreviewReason',data.reasons||{});
      panel.querySelectorAll('[data-nazk-count]').forEach(node=>node.textContent=String(data.counts?.[node.dataset.nazkCount]??'—'));
      q('nazkPreviewRows').innerHTML=items.map(row=>`<tr><td><button type="button" class="nazk-preview-supplier" data-nazk-supplier="${escape(row.code)}">${escape(row.name)}</button><small>${escape(row.code)}</small></td><td>${escape(row.active_count)} / ${escape(row.stored_active_count)}</td><td>${escape(data.states?.[row.state]||row.state)}${row.source_ids.map(id=>`<small>НАЗК · ${escape(id)}</small>`).join('')}</td><td>${row.checks.map(check=>`<small>Перевірка ${escape(check.id)} · ${escape(workStatuses[check.status]||check.status)}${check.result?' · '+escape(data.states?.[check.result]||check.result):''}</small>`).join('')||'—'}${row.tasks.map(task=>`<button type="button" data-nazk-task="${escape(task.id)}">Задача · ${escape(workStatuses[task.status]||task.status)}</button>`).join('')}</td><td>${escape(row.responsible_officer?.name||'Не призначено')}</td><td>${escape(row.linked_active_applications)}</td><td><span class="nazk-preview-badge">${escape(groups[row.group]||row.group)}</span><small>${escape(data.reasons?.[row.reason]||row.reason)}</small>${row.existing_check_without_task?'<small>Новий цикл не потрібний</small>':''}${row.covering_check_id?`<small>Покриття: перевірка ${escape(row.covering_check_id)}</small>`:''}</td><td><button type="button" data-nazk-supplier="${escape(row.code)}">Картка</button><button type="button" disabled title="Адресний запуск буде окремим погодженим етапом">Запуск неактивний</button></td></tr>`).join('')||'<tr><td colspan="8">За вибраними умовами постачальників немає</td></tr>';
      q('nazkPreviewTotal').textContent=`Постачальників: ${data.total} · сторінка ${data.page} із ${pages}`;
      q('nazkPreviewPrev').disabled=page<=1;q('nazkPreviewNext').disabled=page>=pages;
      q('nazkPreviewMessage').textContent='Оновлено.';
    }catch(error){if(requestId===generation){items=[];q('nazkPreviewRows').innerHTML='';panel.querySelectorAll('[data-nazk-count]').forEach(node=>node.textContent='—');q('nazkPreviewTotal').textContent='';q('nazkPreviewMessage').textContent=error.message||'Попередній перегляд недоступний';}}
    finally{if(requestId===generation)q('nazkPreviewRefresh').disabled=false;}
  }
  tabs.addEventListener('click',event=>{const button=event.target.closest('[data-nazk-view]');if(button)select(button.dataset.nazkView==='preview');});
  panel.addEventListener('click',event=>{
    const supplier=event.target.closest('[data-nazk-supplier]');
    if(supplier&&allowed()&&typeof openSupplierProfile==='function')openSupplierProfile(supplier.dataset.nazkSupplier);
    const task=event.target.closest('[data-nazk-task]');
    if(task&&allowed()&&typeof openOperationalTask==='function')openOperationalTask(task.dataset.nazkTask);
  });
  for(const id of ['nazkPreviewScope','nazkPreviewState','nazkPreviewReason','nazkPreviewGroup'])q(id).addEventListener('change',()=>{page=1;load();});
  q('nazkPreviewSearch').addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(()=>{page=1;load();},200);});
  q('nazkPreviewRefresh').addEventListener('click',()=>load());
  q('nazkPreviewPrev').addEventListener('click',()=>{if(page>1){page--;load();}});
  q('nazkPreviewNext').addEventListener('click',()=>{if(page<pages){page++;load();}});
  new MutationObserver(sync).observe(root,{attributes:true,attributeFilter:['hidden']});
  new MutationObserver(sync).observe(document.body,{attributes:true,attributeFilter:['data-auth-role']});
  if(typeof authReady!=='undefined')Promise.resolve(authReady).then(sync).catch(()=>{});
  sync();
})();
