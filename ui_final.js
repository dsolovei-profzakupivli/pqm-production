/* Presentation installation and existing read-only filter entry points only. */
(()=>{
  const $=selector=>document.querySelector(selector);
  let auditTimer;
  document.querySelectorAll('[data-audit-filter]').forEach(input=>input.addEventListener('input',()=>{
    clearTimeout(auditTimer);auditPage=1;auditTimer=setTimeout(()=>loadAudit().catch(error=>{$('#auditPageInfo').textContent=error.message;toast(error.message,'error')}),250);
  }));
  $('#mainNav').addEventListener('click',event=>{const button=event.target.closest('button');if(button?.id.endsWith('Nav')&&$('#auditDialog').open)$('#auditDialog').close()},true);
  const frameworkToolbar=$('#frameworkAnalyticsView .frameworks-toolbar');
  if(frameworkToolbar&&!$('#frameworksReset')){
    const reset=document.createElement('button');reset.id='frameworksReset';reset.type='button';reset.textContent='×';reset.className='ghost pqm-filter-reset';reset.title='Скинути всі фільтри';reset.setAttribute('aria-label',reset.title);
    reset.onclick=()=>{for(const id of ['frameworksSearch','frameworksStatus','frameworksDk','frameworksDateFrom','frameworksDateTo'])$('#'+id).value='';frameworkPage=1;loadFrameworkAnalytics()};
    frameworkToolbar.insertBefore(reset,frameworkToolbar.querySelector('.system-width-button'));
  }
  // Information cards remain non-interactive. Status cards are separate from protocol decisions.
  const statusCards={pending:'Очікує рішення',admitted:'Допущено',rejected:'Відхилено'};
  function paintStatusCards(){for(const [key,status] of Object.entries(statusCards)){const card=document.querySelector(`[data-kpi-card="${key}"]`);if(card){const active=filterSelections.status.size===1&&filterSelections.status.has(status);card.classList.toggle('active',active);card.setAttribute('aria-pressed',String(active))}}}
  for(const [key,status] of Object.entries(statusCards)){
    const card=document.querySelector(`[data-kpi-card="${key}"]`);if(!card)continue;
    card.setAttribute('role','button');card.tabIndex=0;
    const activate=()=>{const same=filterSelections.status.size===1&&filterSelections.status.has(status);filterSelections.status.clear();if(!same)filterSelections.status.add(status);document.querySelectorAll('#statusFilter input[type="checkbox"]').forEach(input=>input.checked=filterSelections.status.has(input.value));paintStatusCards();page=1;statsSignature='';updateMultiSummary('statusFilter','Статус',filterSelections.status);loadRows()};
    card.onclick=activate;card.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();activate()}};
  }
  const watched=new WeakSet();
  function layoutCards(group){
    const cards=[...group.children].filter(node=>node.matches('button')),count=cards.length;if(!count||!group.clientWidth)return;
    const canvas=document.createElement('canvas'),context=canvas.getContext('2d');
    let minimum=150;
    for(const card of cards){const span=card.querySelector('span');if(span){context.font=getComputedStyle(span).font;minimum=Math.max(minimum,Math.ceil(context.measureText(span.textContent).width)+28)}}
    const available=(group.clientWidth-12*(count-1))/count;
    const basis=count<=5&&available>=minimum?Math.min(184,available):Math.max(184,minimum);
    const next=basis+'px';if(group.style.getPropertyValue('--card-basis')!==next)group.style.setProperty('--card-basis',next);
  }
  const resize=new ResizeObserver(entries=>entries.forEach(({target})=>layoutCards(target)));
  function install(){
    paintStatusCards();
    const history=$('#historyView');if(history&&!history.hidden){const scale=Number(getComputedStyle(document.body).zoom)||1;const height=Math.max(240,(innerHeight-history.getBoundingClientRect().top-36)/scale)+'px';if(history.style.height!==height)history.style.height=height}
    document.querySelectorAll('#workQueueView .qualification-summary-cards,#workQueueView .publication-control-cards').forEach(group=>{if(!watched.has(group)){watched.add(group);resize.observe(group)}layoutCards(group)});
    document.querySelectorAll('dialog').forEach(dialog=>{
      const header=dialog.querySelector('header');if(header&&typeof installViewportDrag==='function')installViewportDrag(dialog,dialog,header);
    });
  }
  install();let queued=false;
  new MutationObserver(()=>{if(queued)return;queued=true;requestAnimationFrame(()=>{queued=false;install()})}).observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['hidden','open']});
  window.addEventListener('resize',install);
  document.fonts?.ready.then(install);
})();
