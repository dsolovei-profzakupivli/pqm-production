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

  function actionButton({className, text, label, attribute}) {
    const button=document.createElement('button');
    button.type='button';
    button.className=className;
    button.textContent=text;
    button.title=label;
    button.setAttribute('aria-label',label);
    button.setAttribute(attribute,'');
    button.hidden=true;
    return button;
  }

  function actionSlot(apply,clear) {
    const slot=document.createElement('span');
    slot.className='filter-row-actions';
    slot.append(apply,clear);
    return slot;
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
      const apply=actionButton({className:'filter-row-apply',text:'✓',label:`Застосувати фільтр «${title}»`,attribute:'data-application-filter-apply'});
      apply.dataset.applicationFilterApply=section.dataset.applicationFilterSection;
      const clear=actionButton({className:'filter-row-clear',text:'×',label:`Скинути фільтр «${title}»`,attribute:'data-application-filter-reset'});
      clear.dataset.applicationFilterReset=section.dataset.applicationFilterSection;
      const heading=document.createElement('div');heading.className='filter-section-heading';
      heading.append(button,actionSlot(apply,clear));
      [...section.childNodes].forEach(node=>content.append(node));
      section.replaceChildren(heading,content);
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
      const apply=actionButton({className:'filter-row-apply',text:'✓',label:`Застосувати фільтр «${title}»`,attribute:'data-edr-filter-apply'});
      apply.dataset.edrFilterApply=section.dataset.edrFilterSection;
      const slot=actionSlot(apply,clear||actionButton({className:'filter-row-clear',text:'×',label:`Скинути фільтр «${title}»`,attribute:'data-edr-filter-clear'}));
      const next=document.createDocumentFragment();
      while(section.children.length>1)next.append(section.children[1]);
      const content=document.createElement('div');
      content.className='filter-accordion-content edr-monitoring-filter-content';
      content.hidden=true;
      next.querySelectorAll('.edr-monitoring-filter-control>span').forEach(caption=>{
        if(caption.textContent.trim()==='Виберіть тип')caption.classList.add('filter-field-caption');
      });
      content.append(next);
      heading.classList.add('filter-section-heading');
      heading.replaceChildren(button,slot);
      section.append(content);
      section.dataset.accordionReady='true';
    });
    bind(panel,'.edr-monitoring-filter-section','.filter-accordion-toggle','.filter-accordion-content');
  }

  function bind(panel,itemSelector,toggleSelector,contentSelector) {
    panel.addEventListener('click',event=>{
      if(event.target.closest('.filter-row-actions'))return;
      const heading=event.target.closest('.filter-section-heading,.edr-monitoring-filter-heading,.queue-statistics-filter-section-heading');
      const toggle=event.target.closest(toggleSelector)||(heading&&heading.querySelector(toggleSelector));
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
      collapseSection(toggle.closest('.application-filter-section,.edr-monitoring-filter-section,.queue-statistics-filter-section'));
    });
  }

  function collapseSection(section) {
    if(!section)return false;
    const toggle=section.querySelector('.filter-accordion-toggle,.queue-statistics-section-toggle');
    const content=section.querySelector('.filter-accordion-content,.queue-statistics-filter-section-content');
    toggle?.setAttribute('aria-expanded','false');
    if(content)content.hidden=true;
    return true;
  }

  function collapseControl(control) {
    return collapseSection(control?.closest('.application-filter-section,.edr-monitoring-filter-section,.queue-statistics-filter-section'));
  }

  function prepareQueueStatisticsFilters() {
    const panel=document.querySelector('#queueStatisticsFilterPanel');
    if(!panel)return;
    panel.querySelectorAll('.queue-statistics-filter-section').forEach(section=>{
      const toggle=section.querySelector('.queue-statistics-section-toggle');
      const content=section.querySelector('.queue-statistics-filter-section-content');
      const apply=actionButton({className:'filter-row-apply',text:'✓',label:`Застосувати фільтр «${toggle?.querySelector('span')?.textContent.trim()||''}»`,attribute:'data-statistics-filter-apply'});
      apply.dataset.statisticsFilterApply=section.dataset.statisticsFilterSection;
      const clear=section.querySelector('[data-statistics-filter-reset]');
      const dkSummary=section.querySelector('#queueStatisticsDkSummary');
      if(dkSummary){const count=document.createElement('span');count.className='queue-statistics-section-count';dkSummary.replaceWith(count);const heading=section.querySelector('.queue-statistics-dk-heading');if(heading){dkSummary.classList.add('queue-statistics-dk-draft-summary');heading.append(dkSummary)}}
      let slot=section.querySelector('.filter-row-actions');
      if(!slot){slot=actionSlot(apply,clear||actionButton({className:'filter-row-clear',text:'×',label:'Скинути цей фільтр',attribute:'data-statistics-filter-reset'}));section.querySelector('.queue-statistics-filter-section-heading')?.replaceChildren(toggle,slot);}
      else if(!slot.contains(apply)){slot.prepend(apply);}
      if(toggle)toggle.setAttribute('aria-expanded','false');
      if(content)content.hidden=true;
    });
    bind(panel,'.queue-statistics-filter-section','.queue-statistics-section-toggle','.queue-statistics-filter-section-content');
  }

  prepareApplicationFilters();
  prepareEdrFilters();
  prepareQueueStatisticsFilters();
  window.PqmFilterAccordion={collapseAll,collapseControl};
  [['#applicationFilters','#applicationFilterPanel'],['#edrMonitoringAdvanced','#edrMonitoringFilterPanel']].forEach(([detailsSelector,panelSelector])=>{
    const details=document.querySelector(detailsSelector),panel=document.querySelector(panelSelector);
    details?.addEventListener('toggle',()=>{if(details.open)collapseAll(panel)});
  });
})();
