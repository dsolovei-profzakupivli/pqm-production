'use strict';

(() => {
  const statuses = [
    ['active', 'Допущено', 'admitted'],
    ['unsuccessful', 'Відхилено', 'rejected'],
    ['pending', 'Очікує рішення', 'pending'],
  ];
  const controls = $$('[data-statistics-filter]');
  const progress = $('#queueProtocolOfficerCards');
  const dkSearch = $('#queueStatisticsDkSearch');
  const dkSummary = $('#queueStatisticsDkSummary');
  const dkOptions = $('#queueStatisticsDkOptions');
  const filterPanel = $('#queueStatisticsFilterPanel');
  const filterToggle = $('#queueStatisticsFilterToggle');
  const workspace = $('#queueStatisticsWorkspace');
  const kpis = $('#queueStatisticsKpis');
  const table = $('#queueStatisticsRows');
  const tableWrap = $('.queue-statistics-table');
  const message = $('#queueStatisticsMessage');
  const filterSummary = $('#queueStatisticsFilterSummary');
  const pending = $('#queueStatisticsPending');
  const fromField = $('#queueStatisticsFromField');
  const toField = $('#queueStatisticsToField');
  const groupField = $('#queueStatisticsGroupField');
  const from = $('#queueStatisticsFrom');
  const to = $('#queueStatisticsTo');
  const group = $('#queueStatisticsGroup');
  const unassigned = '__unassigned__';
  let actions = [];
  let statistics = [];
  let period = null, initialPeriod;
  let statisticsRequest = 0, progressRequest = 0;
  let progressPeriod = '', progressItems = [], initialized = false;
  let dkSelection = new Set();
  let appliedSelection = {};
  let appliedDkSelection = new Set();

  group.value = 'review_officer';
  const periodParams = (start, end) => ({date_from:start.value, date_to:end.value});
  const summary = (name, dates, extras={}) => request(`${API}/uo-work-queue?${new URLSearchParams({summary:name,...dates,...extras})}`);
  const officerName = name => name ? formatOfficerName(name) : 'Не призначено';
  const number = n => Number(n || 0).toLocaleString('uk-UA');
  const percent = (count,total) => total ? Math.round(count*100/total) : 0;

  function openRegister(filters, status, review) {
    resetApplicationsForExternalKpi();
    $('#dateFromFilter').value=filters.date_from||'';
    $('#dateToFilter').value=filters.date_to||'';
    $('#protocolDecisionFilter').value=review?'__empty__':'';
    const dkCodes=Array.isArray(filters.dk_code)?filters.dk_code:filters.dk_code?[filters.dk_code]:[];
    dkCodes.forEach(value=>filterSelections.dk.add(value));
    categoryFilter=filters.category||'';
    for (const key of ['review_officer','protocol_officer','protocol_card_officer']) {
      if (filters[key]) queueRegistryFilters[key]=filters[key];
    }
    if (status) {
      filterSelections.status.add(status);
      queueRegistryFilters.actual_status='1';
    }
    page=1;
    syncPrimaryFilters();
    updateMultiSummary('dkFilter','Усі коди ДК',filterSelections.dk);
    updateMultiSummary('statusFilter','Статус',filterSelections.status);
    $$('#statusFilter input[type="checkbox"]').forEach(input=>input.checked=filterSelections.status.has(input.value));
    const officers=Object.entries(queueRegistryFilters).filter(([key])=>key!=='actual_status');
    const scope=$('#queueRegistryScope');
    scope.textContent=officers.map(([key,value])=>`${key==='review_officer'?'УО розгляду':'УО протоколу'} · ${officerName(value===unassigned?'':value)}`).join(' · ');
    scope.hidden=!officers.length;
    saveFilterState();
    updateApplicationFilterStyles();
    showModule('applications');
    return loadApplicationsForExternalKpi();
  }

  function renderProtocolProgress(items, dates) {
    const byOfficer=new Map(items.map(row=>[String(row.protocol_officer||''),row]));
    progress.querySelectorAll('[data-protocol-officer]').forEach(card=>{
      const name=card.dataset.protocolOfficer||'';
      const row=byOfficer.get(name);
      const slot=card.querySelector('[data-protocol-progress]');
      if(!row||!slot)return;
      const total=Number(row.total||0), reviewed=Number(row.reviewed||0), notReviewed=Number(row.pending||0);
      const ratio=percent(reviewed,total);
      const track=slot.querySelector('.protocol-progress-track');
      const value=slot.querySelector('[data-progress-percent]');
      const pendingButton=slot.querySelector('[data-protocol-pending]');
      if(track){track.querySelector('span').style.width=`${ratio}%`;track.title=`Розглянуто: ${number(reviewed)} із ${number(total)} (${ratio}%)`;track.setAttribute('aria-label',track.title);}
      if(value)value.textContent=`${ratio}%`;
      if(pendingButton){pendingButton.textContent=number(notReviewed);pendingButton.disabled=notReviewed===0;pendingButton.title=`Не розглянуто: ${number(notReviewed)}. Відкрити в реєстрі заявок`;pendingButton.setAttribute('aria-label',pendingButton.title);}
      slot.setAttribute('aria-label',`Розглянуто ${number(reviewed)} із ${number(total)}, ${ratio} відсотків; не розглянуто ${number(notReviewed)}`);
      card.dataset.progressReady='true';
    });
  }

  async function loadProgress() {
    const dates=periodParams($('#queueProtocolFrom'),$('#queueProtocolTo'));
    if (!dates.date_from && !dates.date_to) return;
    const key=JSON.stringify(dates);
    if (key===progressPeriod) {renderProtocolProgress(progressItems,dates);return;}
    progressPeriod=key;
    const ticket=++progressRequest;
    progressItems=[];
    progress.querySelectorAll('[data-protocol-progress]').forEach(slot=>{slot.setAttribute('aria-label','Прогрес розгляду недоступний');});
    try {
      const data=await summary('review-progress',dates,{group_by:'protocol_officer'});
      if (ticket!==progressRequest) return;
      progressItems=Array.isArray(data.items)?data.items:[];
      renderProtocolProgress(progressItems,dates);
    } catch (error) {
      if (ticket===progressRequest) {
        progressPeriod='';
        progress.querySelectorAll('[data-protocol-progress]').forEach(slot=>{slot.setAttribute('aria-label',`Прогрес розгляду недоступний: ${error.message}`);});
      }
    }
  }

  function countButton(count, filters, status, label='', tone='') {
    const index=actions.push({filters,status})-1;
    return `<button type="button" class="ghost publication-kpi ${tone}" data-statistics-action="${index}">${label?`<span>${label}</span>`:''}<strong>${number(count)}</strong></button>`;
  }

  function emptyCounts() { return {active:0,unsuccessful:0,pending:0,total:0}; }
  function addCounts(counts,row) {
    counts.total+=Number(row.total||0);
    if (statuses.some(([code])=>code===row.status)) counts[row.status]+=Number(row.total||0);
  }
  function currentSelection() {
    const selection={...appliedSelection};
    if(appliedDkSelection.size)selection.dk_code=[...appliedDkSelection];
    return selection;
  }
  function matchesSelection(row,selection) {
    return Object.entries(selection).every(([field,value])=>{
      if(field==='supplier_type')return true;
      if(field==='dk_code')return value.includes(row.dk_code||'');
      return (row[field]||unassigned)===value;
    });
  }
  function fitTableViewport() {
    if (!tableWrap.classList.contains('queue-statistics-table--scroll')) {
      tableWrap.style.maxHeight='';
      return;
    }
    const header=tableWrap.querySelector('thead');
    const firstFive=[...table.querySelectorAll('tr')].slice(0,5);
    const height=(header?.getBoundingClientRect().height||0)+firstFive.reduce((sum,row)=>sum+row.getBoundingClientRect().height,0);
    if(height>0)tableWrap.style.maxHeight=`${Math.ceil(height)}px`;
  }

  function renderStatistics() {
    if (!period) return;
    const selection=currentSelection(), filters={...period,...selection}, key=group.value, totals=emptyCounts(), groups=new Map();
    for (const row of statistics) {
      if (!matchesSelection(row,selection)) continue;
      const name=row[key]||'';
      if (!groups.has(name)) groups.set(name,emptyCounts());
      addCounts(groups.get(name),row);
      addCounts(totals,row);
    }
    actions=[];
    kpis.innerHTML=statuses.map(([code,label,tone])=>countButton(totals[code],filters,label,label,tone)).join('');
    const sorted=[...groups].sort(([a],[b])=>officerName(a).localeCompare(officerName(b),'uk'));
    table.innerHTML=sorted.map(([name,counts])=>{
      const scoped={...filters,[key]:name||unassigned};
      return `<tr><th scope="row">${esc(officerName(name))}</th>${statuses.map(([code,label])=>`<td>${countButton(counts[code],scoped,label)}</td>`).join('')}<td>${countButton(counts.total,scoped,'')}</td></tr>`;
    }).join('');
    tableWrap.classList.toggle('queue-statistics-table--scroll',sorted.length>5);
    tableWrap.dataset.rowCount=String(sorted.length);
    fitTableViewport();
    const other=totals.total-totals.active-totals.unsuccessful-totals.pending;
    message.textContent=!groups.size?'Заявок за цими умовами немає':other?`Заявки без одного з трьох статусів Prozorro · ${number(other)}`:'';
    renderFilterPresentation();
  }

  function renderDkFilter(rows,preserveSelection=false) {
    const values=[...new Set([...rows.map(row=>row.dk_code).filter(Boolean),...(preserveSelection?[...appliedDkSelection]:[])])].sort((a,b)=>a.localeCompare(b,'uk'));
    if(!preserveSelection){
      const available=new Set(values);
      appliedDkSelection=new Set([...appliedDkSelection].filter(value=>available.has(value)));
    }
    dkSelection=new Set(appliedDkSelection);
    renderDkOptions(values);
  }

  function renderDkOptions(values=[...new Set(statistics.map(row=>row.dk_code).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'uk'))) {
    const query=dkSearch.value.trim().toLocaleLowerCase('uk');
    const visible=values.filter(value=>String(value).toLocaleLowerCase('uk').includes(query)||dkSelection.has(value));
    dkOptions.innerHTML=visible.map(value=>`<label><input type="checkbox" data-statistics-dk-option value="${esc(value)}" ${dkSelection.has(value)?'checked':''}> ${esc(value)}</label>`).join('')||'<span class="muted">Кодів ДК за цим пошуком немає</span>';
    dkSummary.textContent=dkSelection.size?`Вибрано: ${dkSelection.size}`:'Усі коди';
  }

  function renderFilterPresentation() {
    const activeCount=Object.values(appliedSelection).filter(Boolean).length+(appliedDkSelection.size?1:0);
    filterSummary.textContent=activeCount?`Фільтри · ${activeCount}`:'Фільтри';
    filterToggle.classList.toggle('filter-active',activeCount>0);
    controls.forEach(control=>{
      const applied=appliedSelection[control.dataset.statisticsFilter]||'';
      control.closest('label')?.classList.toggle('filter-active',Boolean(applied&&control.value===applied));
      control.closest('label')?.classList.toggle('filter-pending',control.value!==applied);
    });
    const dkField=dkOptions.closest('.queue-statistics-dk-field');
    const draftDk=[...dkSelection].sort().join('\0'), appliedDk=[...appliedDkSelection].sort().join('\0');
    dkField?.classList.toggle('filter-active',appliedDkSelection.size>0&&draftDk===appliedDk);
    dkField?.classList.toggle('filter-pending',draftDk!==appliedDk);
    fromField.classList.toggle('filter-active',Boolean(period?.date_from)&&from.value===period.date_from);
    toField.classList.toggle('filter-active',Boolean(period?.date_to)&&to.value===period.date_to);
    groupField.classList.toggle('filter-active',group.value!=='review_officer');
    const datesPending=Boolean(period)&&(from.value!==period.date_from||to.value!==period.date_to);
    const filtersPending=controls.some(control=>control.value!==(appliedSelection[control.dataset.statisticsFilter]||''))||draftDk!==appliedDk;
    pending.hidden=!datesPending&&!filtersPending;
    pending.textContent=[datesPending?'Зміни періоду ще не застосовано. Натисніть пошук, щоб оновити статистику.':'',filtersPending?'Зміни фільтрів ще не застосовано. Натисніть «Застосувати» в панелі.':''].filter(Boolean).join(' ');
  }

  function setFilterPanelOpen(open) {
    filterPanel.hidden=!open;
    filterToggle.setAttribute('aria-expanded',String(open));
    filterToggle.title=open?'Закрити фільтри':'Відкрити фільтри';
    workspace.classList.toggle('is-filter-open',open);
  }

  function applyDraftFilters(closePanel=true) {
    const previousType=appliedSelection.supplier_type||'';
    appliedSelection=Object.fromEntries(controls.filter(control=>control.value).map(control=>[control.dataset.statisticsFilter,control.value]));
    appliedDkSelection=new Set(dkSelection);
    if(previousType!==(appliedSelection.supplier_type||''))loadStatistics(true);
    else renderStatistics();
    if(closePanel)setFilterPanelOpen(false);
  }

  async function loadStatistics(preserveSelection=false) {
    const dates=periodParams(from,to), ticket=++statisticsRequest;
    if (dates.date_from>dates.date_to) {message.textContent='Дата «До» має бути не раніше дати «Від»';return;}
    period=null;
    kpis.replaceChildren();
    table.replaceChildren();
    message.textContent='Завантаження…';
    try {
      const entityType=appliedSelection.supplier_type||'';
      const data=await summary('application-statistics',dates,entityType?{entity_type:entityType}:{});
      if (ticket!==statisticsRequest) return;
      statistics=Array.isArray(data.items)?data.items:[];
      period=dates;
      renderDkFilter(statistics,preserveSelection);
      for (const control of controls) {
        const key=control.dataset.statisticsFilter, previous=appliedSelection[key]||'', isOfficer=key.endsWith('_officer');
        if(key==='supplier_type')continue;
        const values=[...new Set(statistics.map(row=>row[key]).filter(value=>value||isOfficer))].sort((a,b)=>a.localeCompare(b,'uk'));
        if(preserveSelection&&previous&&!values.includes(previous))values.push(previous);
        values.sort((a,b)=>a.localeCompare(b,'uk'));
        control.replaceChildren(new Option('Усі',''),...values.map(value=>new Option(isOfficer?officerName(value):value,value||unassigned)));
        control.value=[...control.options].some(option=>option.value===previous)?previous:'';
      }
      appliedSelection=Object.fromEntries(controls.filter(control=>control.value).map(control=>[control.dataset.statisticsFilter,control.value]));
      dkSelection=new Set(appliedDkSelection);
      renderDkOptions();
      renderStatistics();
    } catch(error) {
      if (ticket===statisticsRequest) message.textContent=error.message;
    }
  }

  window.refreshQueueApplicationStatistics=()=>{
    loadProgress();
    if (initialized) return;
    from.value=$('#queueProtocolFrom').value;
    to.value=$('#queueProtocolTo').value;
    if (!from.value||!to.value) return;
    initialPeriod=periodParams(from,to);
    initialized=true;
    loadStatistics();
  };
  window.openQueueProtocolApplications=(officer,pendingOnly)=>{
    const dates=periodParams($('#queueProtocolFrom'),$('#queueProtocolTo'));
    return openRegister({...dates,protocol_card_officer:officer||'Не призначено'},'',Boolean(pendingOnly));
  };
  $('#queueProtocolApply').addEventListener('click',()=>{progressPeriod='';},true);
  $('#queueStatisticsFilters').onsubmit=event=>{event.preventDefault();loadStatistics();};
  [from,to].forEach(control=>control.addEventListener('input',renderFilterPresentation));
  $('#queueStatisticsReset').onclick=()=>{
    if (!initialPeriod) return;
    from.value=initialPeriod.date_from;
    to.value=initialPeriod.date_to;
    controls.forEach(control=>control.value='');
    dkSelection.clear();
    appliedDkSelection.clear();
    appliedSelection={};
    dkSearch.value='';
    group.value='review_officer';
    setFilterPanelOpen(false);
    loadStatistics();
    renderFilterPresentation();
  };
  controls.forEach(control=>control.onchange=renderFilterPresentation);
  group.onchange=renderStatistics;
  filterToggle.onclick=()=>setFilterPanelOpen(filterPanel.hidden);
  $('#queueStatisticsFilterApply').onclick=()=>applyDraftFilters(true);
  $('#queueStatisticsFilterClear').onclick=()=>{
    controls.forEach(control=>control.value='');
    dkSelection.clear();
    dkSearch.value='';
    renderDkOptions();
    applyDraftFilters(false);
  };
  $('#queueStatisticsDkClear').onclick=()=>{
    dkSelection.clear();
    renderDkOptions();
    renderFilterPresentation();
  };
  dkSearch.addEventListener('input',()=>renderDkOptions());
  dkOptions.onchange=event=>{
    const input=event.target.closest('[data-statistics-dk-option]');
    if(!input)return;
    input.checked?dkSelection.add(input.value):dkSelection.delete(input.value);
    renderDkOptions();
    renderFilterPresentation();
  };
  for (const root of [kpis,table]) root.onclick=event=>{
    const button=event.target.closest('[data-statistics-action]');
    const action=button&&actions[Number(button.dataset.statisticsAction)];
    if (action) openRegister(action.filters,action.status,false);
  };
  $('#clearFiltersBtn').addEventListener('click',()=>{$('#queueRegistryScope').hidden=true;},true);
})();
