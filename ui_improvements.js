/* Presentation helpers shared by the UI and offline regression probes. */
(function(root){
  function compactOfficer(value){
    const parts=String(value||'').trim().split(/\s+/).filter(Boolean);
    if(/^(Не визначено|Не призначено)$/i.test(parts.join(' ')))return parts.join(' ');
    if(parts.length<2)return parts.join(' ');
    const surname=parts.at(-1).split('-').map(word=>word[0].toLocaleUpperCase('uk-UA')+word.slice(1).toLocaleLowerCase('uk-UA')).join('-');
    return `${parts.slice(0,-1).map(word=>word[0]+'.').join(' ')} ${surname}`;
  }
  function fullOfficerName(value,officers=[]){
    const source=String(value||'').trim(),parts=source.split(/\s+/).filter(Boolean);
    if(!source||/^(Не визначено|Не призначено)$/i.test(source)||parts.length<2)return source;
    const normalize=word=>String(word||'').replace(/\.$/,'').normalize('NFC').toLocaleUpperCase('uk-UA');
    const surname=normalize(parts.at(-1));
    const matches=(officers||[]).filter(item=>{
      const full=String(item?.full_name||'').trim().split(/\s+/).filter(Boolean);
      if(full.length<2||normalize(full.at(-1))!==surname)return false;
      const given=parts.slice(0,-1),candidate=full.slice(0,-1);
      return given.length<=candidate.length&&given.every((part,index)=>{
        const token=normalize(part),name=normalize(candidate[index]);
        return /\.$/.test(part)?name.startsWith(token):token===name;
      });
    });
    return matches.length===1?matches[0].full_name:source;
  }
  function displayOfficerFullName(value){
    const parts=String(value||'').trim().split(/\s+/).filter(Boolean);
    if(parts.length<2)return parts.join(' ');
    return `${parts.slice(0,-1).map(word=>word[0].toLocaleUpperCase('uk-UA')+word.slice(1).toLocaleLowerCase('uk-UA')).join(' ')} ${parts.at(-1).toLocaleUpperCase('uk-UA')}`;
  }
  const api={compactOfficer,clearInput:null,formatActionButtons:null,resetIds:[],prozorroIds:[],officerRoster:[],responseExpired:false};
  function refreshProtocolOfficerNames(){
    const cards=root.document?.querySelectorAll('#queueProtocolOfficerCards [data-protocol-officer]')||[];
    cards.forEach(card=>{
      const span=card.querySelector('span');if(!span)return;
      const full=fullOfficerName(card.dataset.protocolOfficer,api.officerRoster);
      const label=displayOfficerFullName(full);
      if(label&&span.textContent!==label)span.textContent=label;
      if(label&&span.title!==label)span.title=label;
    });
  }
  api.setOfficerRoster=items=>{api.officerRoster=Array.isArray(items)?items:[];refreshProtocolOfficerNames()};
  if(root.document){
    const observe=()=>{const host=root.document.querySelector('#queueProtocolOfficerCards');if(host)new MutationObserver(refreshProtocolOfficerNames).observe(host,{childList:true,subtree:true})};
    if(root.document.readyState==='loading')root.document.addEventListener('DOMContentLoaded',observe,{once:true});else observe();
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
  api.clearInput=clearInput;api.formatActionButtons=formatActionButtons;api.resetIds=resetIds;api.prozorroIds=prozorroIds;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  root.PqmUi=api;
})(typeof globalThis!=='undefined'?globalThis:this);
