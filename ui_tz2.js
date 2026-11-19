/* Existing read-only document/download/copy mechanisms only. */
(()=>{
  const audit=document.getElementById('auditDialog');
  audit.dataset.keepViewport='true';
  function fitAuditSurfaces(){
    const scale=Number(getComputedStyle(document.body).zoom)||1;
    for(const dialog of document.querySelectorAll('#auditDialog[open],#auditValueDialog[open]')){
      dialog.style.width=Math.min(dialog===audit?1090:1000,(innerWidth-40)/scale)+'px';
      let rect=dialog.getBoundingClientRect();
      dialog.style.maxHeight=Math.max(120,(innerHeight-Math.max(8,rect.top)-20)/scale)+'px';
      rect=dialog.getBoundingClientRect();
      if(rect.x<8||rect.right>innerWidth-8){dialog.style.margin='0';dialog.style.left=Math.max(8,Math.min(rect.x,innerWidth-rect.width-8))/scale+'px'}
      if(rect.y<8||rect.bottom>innerHeight-8){dialog.style.margin='0';dialog.style.top=Math.max(8,Math.min(rect.y,innerHeight-rect.height-8))/scale+'px'}
    }
  }
  new MutationObserver(records=>{if(records.some(r=>r.target===document.body||r.attributeName==='open'&&['auditDialog','auditValueDialog'].includes(r.target.id)))fitAuditSurfaces()}).observe(document.body,{subtree:true,attributes:true,attributeFilter:['open','style']});
  window.addEventListener('resize',fitAuditSurfaces);
  document.getElementById('auditBody').addEventListener('click',event=>{
    const button=event.target.closest('[data-audit-row]');if(!button)return;
    const row=auditRows[Number(button.dataset.auditRow)];if(!row)return;
    let viewer=document.getElementById('auditValueDialog');
    if(!viewer){viewer=document.createElement('dialog');viewer.id='auditValueDialog';viewer.className='wide';viewer.innerHTML='<form method="dialog"><header><h2>Повні значення запису</h2><button class="dialog-close" value="cancel" aria-label="Закрити">×</button></header><div class="audit-value-comparison"></div><footer><button value="cancel" class="primary">Закрити</button></footer></form>';document.body.append(viewer);if(typeof installViewportDrag==='function')installViewportDrag(viewer,viewer,viewer.querySelector('header'))}
    const grid=viewer.querySelector('.audit-value-comparison');grid.replaceChildren();
    for(const [label,key] of [['Було','old_value'],['Стало','new_value']]){const section=document.createElement('section'),title=document.createElement('h3'),text=document.createElement('pre'),copy=document.createElement('button');title.textContent=label;text.textContent=row[key]??'';copy.type='button';copy.className='ghost';copy.textContent='Копіювати';copy.onclick=()=>copyText(text.textContent);section.append(title,text,copy);grid.append(section)}
    viewer.dataset.keepViewport='true';viewer.showModal();
  });
  audit.addEventListener('close',()=>document.getElementById('auditValueDialog')?.close());
  document.getElementById('requestsBody').addEventListener('click',event=>{
    const button=event.target.closest('[data-protocol-askod],[data-protocol-json]');if(!button)return;
    event.preventDefault();event.stopImmediatePropagation();
    const item=violationReports[Number(button.dataset.protocolAskod??button.dataset.protocolJson)];if(!item)return;
    if(button.hasAttribute('data-protocol-askod'))copyText(item.protocol_summary.askod);
    else copyViolationReportJson(item,button);
  },true);
})();
