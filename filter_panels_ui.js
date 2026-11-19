'use strict';

(() => {
  function buildToggle(title, countAttribute) {
    const button=document.createElement('button');
    button.type='button';
    button.className='filter-accordion-toggle';
    button.setAttribute('aria-expanded','false');
    const name=document.createElement('span');
    name.className='filter-accordion-title';
    name.textContent=title;
    const count=document.createElement('span');
    count.className='filter-accordion-count';
    count.setAttribute(countAttribute,'');
    count.hidden=true;
    button.append(name,count);
    return button;
  }

  function prepareApplicationFilters() {
    const panel=document.querySelector('#applicationFilterPanel');
    if(!panel)return;
    panel.querySelectorAll('.application-filter-section').forEach((section,index)=>{
      if(section.dataset.accordionReady)return;
      const source=section.querySelector(':scope > label,:scope > .application-filter-label');
      const title=source?.textContent.trim()||`Фільтр ${index+1}`;
      if(source)source.classList.add('filter-field-caption');
      const button=buildToggle(title,'data-application-filter-count');
      section.dataset.applicationFilterSection=({
        applicationOfficerFilter:'protocol_officer',applicationEntityTypeFilter:'entity_type',supplierCodeFilter:'supplier_codes',
        registryStatusFilter:'registry_status',protocolNumberFilter:'protocol_number',protocolDecisionFilter:'protocol_decision',
        complianceStatusFilter:'compliance_status',frameworkFilter:'framework_id',dkFilter:'dk_code',dateFromFilter:'application_date',dateToFilter:'application_date'
      })[section.querySelector('input,select,details')?.id]||'other';
      const content=document.createElement('div');
      content.className='filter-accordion-content application-filter-content';
      content.hidden=true;
      [...section.childNodes].forEach(node=>content.append(node));
      section.replaceChildren(button,content);
      section.dataset.accordionReady='true';
    });
    bind(panel,'.application-filter-section','.filter-accordion-toggle','.filter-accordion-content');
  }

  function prepareEdrFilters() {
    const panel=document.querySelector('#edrMonitoringFilterPanel');
    if(!panel)return;
    panel.querySelectorAll('.edr-monitoring-filter-section').forEach(section=>{
      if(section.dataset.accordionReady)return;
      const heading=section.querySelector(':scope > .edr-monitoring-filter-heading');
      if(!heading)return;
      const title=heading.querySelector('strong')?.textContent.trim()||'';
      const button=buildToggle(title,'data-edr-filter-count');
      const clear=heading.querySelector('[data-edr-filter-clear]');
      const next=document.createDocumentFragment();
      while(section.children.length>1)next.append(section.children[1]);
      const content=document.createElement('div');
      content.className='filter-accordion-content edr-monitoring-filter-content';
      content.hidden=true;
      next.querySelectorAll('.edr-monitoring-filter-control>span').forEach(caption=>{
        if(caption.textContent.trim()==='Виберіть тип')caption.classList.add('filter-field-caption');
      });
      content.append(next);
      heading.replaceChildren(button,...(clear?[clear]:[]));
      section.append(content);
      section.dataset.accordionReady='true';
    });
    bind(panel,'.edr-monitoring-filter-section','.filter-accordion-toggle','.filter-accordion-content');
  }

  function bind(panel,itemSelector,toggleSelector,contentSelector) {
    panel.addEventListener('click',event=>{
      const toggle=event.target.closest(toggleSelector);
      if(!toggle||!panel.contains(toggle))return;
      const current=toggle.closest(itemSelector),open=toggle.getAttribute('aria-expanded')!=='true';
      panel.querySelectorAll(itemSelector).forEach(item=>{
        const button=item.querySelector(toggleSelector),content=item.querySelector(contentSelector),active=item===current&&open;
        button?.setAttribute('aria-expanded',String(active));
        if(content)content.hidden=!active;
      });
    });
  }

  function collapseAll(panel) {
    panel?.querySelectorAll('.filter-accordion-toggle,.queue-statistics-section-toggle').forEach(toggle=>{
      toggle.setAttribute('aria-expanded','false');
      const item=toggle.closest('.application-filter-section,.edr-monitoring-filter-section,.queue-statistics-filter-section');
      const content=item?.querySelector('.filter-accordion-content,.queue-statistics-filter-section-content');
      if(content)content.hidden=true;
    });
  }

  function prepareQueueStatisticsFilters() {
    const panel=document.querySelector('#queueStatisticsFilterPanel');
    if(!panel)return;
    panel.querySelectorAll('.queue-statistics-filter-section').forEach(section=>{
      const toggle=section.querySelector('.queue-statistics-section-toggle');
      const content=section.querySelector('.queue-statistics-filter-section-content');
      if(toggle)toggle.setAttribute('aria-expanded','false');
      if(content)content.hidden=true;
    });
    bind(panel,'.queue-statistics-filter-section','.queue-statistics-section-toggle','.queue-statistics-filter-section-content');
  }

  prepareApplicationFilters();
  prepareEdrFilters();
  prepareQueueStatisticsFilters();
  window.PqmFilterAccordion={collapseAll};
  [['#applicationFilters','#applicationFilterPanel'],['#edrMonitoringAdvanced','#edrMonitoringFilterPanel']].forEach(([detailsSelector,panelSelector])=>{
    const details=document.querySelector(detailsSelector),panel=document.querySelector(panelSelector);
    details?.addEventListener('toggle',()=>{if(details.open)collapseAll(panel)});
  });
})();
