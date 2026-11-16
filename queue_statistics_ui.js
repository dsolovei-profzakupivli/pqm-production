'use strict';

(() => {
  const statuses = [
    ['active', 'Допущено', 'admitted'],
    ['unsuccessful', 'Відхилено', 'rejected'],
    ['pending', 'Очікує рішення', 'pending'],
  ];
  const controls = $$('[data-statistics-filter]');
  const progress = $('#queueReviewProgress');
  const kpis = $('#queueStatisticsKpis');
  const table = $('#queueStatisticsRows');
  const message = $('#queueStatisticsMessage');
  const from = $('#queueStatisticsFrom');
  const to = $('#queueStatisticsTo');
  const group = $('#queueStatisticsGroup');
  const filterNames = {dk_code:'Код ДК', category:'Категорія', review_officer:'УО розгляду', protocol_officer:'УО протоколу'};
  const unassigned = '__unassigned__';
  let actions = [];
  let statistics = [];
  let period = null, initialPeriod;
  let statisticsRequest = 0, progressRequest = 0;
  let progressPeriod = '', initialized = false;

  const periodParams = (start, end) => ({date_from:start.value, date_to:end.value});
  const summary = (name, dates) => request(`${API}/uo-work-queue?${new URLSearchParams({summary:name,...dates})}`);
  const officerName = name => name ? formatOfficerName(name) : 'Не призначено';
  const number = n => n.toLocaleString('uk-UA');
  const percent = (count,total) => total ? Math.round(count*100/total) : 0;

  function openRegister(filters, status, review) {
    resetApplicationsForExternalKpi();
    $('#dateFromFilter').value=filters.date_from;
    $('#dateToFilter').value=filters.date_to;
    $('#protocolDecisionFilter').value=review?'__empty__':'';
    if (filters.dk_code) filterSelections.dk.add(filters.dk_code);
    categoryFilter=filters.category||'';
    for (const key of ['review_officer','protocol_officer']) {
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
    scope.textContent=officers.map(([key,value])=>`${filterNames[key]} · ${officerName(value===unassigned?'':value)}`).join(' · ');
    scope.hidden=!officers.length;
    saveFilterState();
    updateApplicationFilterStyles();
    showModule('applications');
    return loadApplicationsForExternalKpi();
  }

  async function loadProgress() {
    const dates=periodParams($('#queueProtocolFrom'),$('#queueProtocolTo'));
    if (!dates.date_from && !dates.date_to) return;
    const key=JSON.stringify(dates);
    if (key===progressPeriod) return;
    progressPeriod=key;
    const ticket=++progressRequest;
    progress.textContent='Завантаження…';
    try {
      const data=await summary('review-progress',dates);
      if (ticket!==progressRequest) return;
      progress.innerHTML=data.items.map(row=>{
        const reviewed=percent(row.reviewed,row.total);
        const pending=row.total&&row.reviewed+row.pending===row.total?100-reviewed:percent(row.pending,row.total);
        return `<section class="queue-review-progress"><strong>${esc(officerName(row.review_officer))}</strong><span>Усього ${number(row.total)}</span>
          <div class="queue-review-scale" aria-hidden="true"><span class="admitted" style="width:${reviewed}%"></span><span class="pending" style="width:${pending}%"></span></div>
          <span>Розглянуто ${number(row.reviewed)} · ${reviewed}%</span>
          <button type="button" class="ghost" data-review-progress="${esc(row.review_officer)}">Не розглянуто ${number(row.pending)} · ${pending}%</button></section>`;
      }).join('')||'<p class="muted">Заявок за період немає</p>';
      progress.onclick=event=>{
        const button=event.target.closest('[data-review-progress]');
        if (button) openRegister({...dates,review_officer:button.dataset.reviewProgress||unassigned},'',true);
      };
    } catch (error) {
      if (ticket===progressRequest) {progressPeriod='';progress.textContent=error.message;}
    }
  }

  function countButton(count, filters, status, label='', tone='') {
    const index=actions.push({filters,status})-1;
    return `<button type="button" class="ghost ${tone}" data-statistics-action="${index}">${label?`<span>${label}</span>`:''}<strong>${number(count)}</strong></button>`;
  }

  function emptyCounts() { return {active:0,unsuccessful:0,pending:0,total:0}; }
  function addCounts(counts,row) {
    counts.total+=row.total;
    if (statuses.some(([code])=>code===row.status)) counts[row.status]+=row.total;
  }

  function renderStatistics() {
    if (!period) return;
    const selection=Object.fromEntries(controls.filter(control=>control.value).map(control=>[control.dataset.statisticsFilter,control.value]));
    const filters={...period,...selection}, key=group.value, totals=emptyCounts(), groups=new Map();
    for (const row of statistics) {
      if (!Object.entries(selection).every(([field,value])=>(row[field]||unassigned)===value)) continue;
      const name=row[key];
      if (!groups.has(name)) groups.set(name,emptyCounts());
      addCounts(groups.get(name),row);
      addCounts(totals,row);
    }
    actions=[];
    kpis.innerHTML=statuses.map(([code,label,tone])=>countButton(totals[code],filters,label,label,tone)).join('');
    table.innerHTML=[...groups].sort(([a],[b])=>officerName(a).localeCompare(officerName(b),'uk')).map(([name,counts])=>{
      const scoped={...filters,[key]:name||unassigned};
      return `<tr><th scope="row">${esc(officerName(name))}</th>${statuses.map(([code,label])=>`<td>${countButton(counts[code],scoped,label)}</td>`).join('')}<td>${countButton(counts.total,scoped,'')}</td></tr>`;
    }).join('');
    const other=totals.total-totals.active-totals.unsuccessful-totals.pending;
    message.textContent=!groups.size?'Заявок за цими умовами немає':other?`Заявки без одного з трьох статусів Prozorro · ${number(other)}`:'';
  }

  async function loadStatistics() {
    const dates=periodParams(from,to), ticket=++statisticsRequest;
    if (dates.date_from>dates.date_to) {message.textContent='Дата «До» має бути не раніше дати «Від»';return;}
    period=null;
    kpis.replaceChildren();
    table.replaceChildren();
    message.textContent='Завантаження…';
    try {
      const data=await summary('application-statistics',dates);
      if (ticket!==statisticsRequest) return;
      statistics=data.items;
      period=dates;
      for (const control of controls) {
        const key=control.dataset.statisticsFilter, previous=control.value, isOfficer=key.endsWith('_officer');
        const values=[...new Set(statistics.map(row=>row[key]).filter(value=>value||isOfficer))].sort((a,b)=>a.localeCompare(b,'uk'));
        control.replaceChildren(new Option('Усі',''),...values.map(value=>new Option(isOfficer?officerName(value):value,value||unassigned)));
        control.value=[...control.options].some(option=>option.value===previous)?previous:'';
      }
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
  $('#queueProtocolApply').addEventListener('click',()=>{progressPeriod='';},true);
  $('#queueStatisticsFilters').onsubmit=event=>{event.preventDefault();loadStatistics();};
  $('#queueStatisticsReset').onclick=()=>{
    if (!initialPeriod) return;
    from.value=initialPeriod.date_from;
    to.value=initialPeriod.date_to;
    controls.forEach(control=>control.value='');
    group.value='review_officer';
    loadStatistics();
  };
  [...controls,group].forEach(control=>control.onchange=renderStatistics);
  for (const root of [kpis,table]) root.onclick=event=>{
    const button=event.target.closest('[data-statistics-action]');
    const action=button&&actions[Number(button.dataset.statisticsAction)];
    if (action) openRegister(action.filters,action.status,false);
  };
  $('#clearFiltersBtn').addEventListener('click',()=>{$('#queueRegistryScope').hidden=true;},true);
})();
