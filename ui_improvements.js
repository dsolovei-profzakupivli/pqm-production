/* Presentation helpers shared by the UI and offline regression probes. */
(function(root){
  function compactOfficer(value){
    const parts=String(value||'').trim().split(/\s+/).filter(Boolean);
    if(/^(Не визначено|Не призначено)$/i.test(parts.join(' ')))return parts.join(' ');
    if(parts.length<2)return parts.join(' ');
    const given=parts.slice(0,-1).map(word=>word.toLocaleLowerCase('uk-UA').replace(/^./u,char=>char.toLocaleUpperCase('uk-UA'))).join(' ');
    return `${given} ${parts.at(-1).toLocaleUpperCase('uk-UA')}`;
  }
  function clearInput(input){
    input.value='';
    input.dispatchEvent(new Event('input',{bubbles:true}));
    input.focus();
  }
  const resetIds=['queueReset','clearFiltersBtn','historyReset','supplierRegistryReset','edrMonitoringReset','adminFrameworkReset'];
  const prozorroIds=['resetBtn','supplierRegistryRefresh','frameworksRefresh','requestsRefresh'];
  function formatActionButtons(documentRoot){
    for(const id of resetIds){
      const button=documentRoot.querySelector('#'+id);if(!button)continue;
      if(button.textContent!=='×')button.textContent='×';
      button.title='Скинути всі фільтри';button.setAttribute('aria-label',button.title);
      button.classList.add('pqm-filter-reset');
    }
    for(const id of prozorroIds){
      const button=documentRoot.querySelector('#'+id);if(!button)continue;
      button.classList.add('pqm-prozorro-refresh');
      const idle=['Оновити з Prozorro','Оновити дані з Prozorro','Prozorro','↻ Prozorro'].includes(button.textContent.trim());
      if(idle&&button.textContent!=='↻ Prozorro')button.textContent='↻ Prozorro';
      if(idle&&(!button.title||['Оновити з Prozorro','Оновити дані з Prozorro'].includes(button.title)))button.title='Оновити дані з Prozorro';
      button.setAttribute('aria-label','Оновити дані з Prozorro');
    }
  }
  const api={compactOfficer,clearInput,formatActionButtons,resetIds,prozorroIds,responseExpired:false};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  root.PqmUi=api;
})(typeof globalThis!=='undefined'?globalThis:this);
