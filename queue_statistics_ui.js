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
  const trendSvg = $('#queueStatisticsTrendSvg');
  const trendChart = $('#queueStatisticsTrendChart');
  const trendTooltip = $('#queueStatisticsTrendTooltip');
  const trendGranularityControls = $$('[data-trend-granularity]');
  const unassigned = '__unassigned__';
  let actions = [];
  let statistics = [];
  let period = null, initialPeriod;
  let statisticsRequest = 0, progressRequest = 0;
  let progressPeriod = '', progressItems = [], initialized = false;
  let dkSelection = new Set();
  let dkValues = [];
  let appliedSelection = {};
  let appliedDkSelection = new Set();
  let statisticsPayload = null;
  let trendGranularity = 'day';
  let renderedTrend = [];
  let activeTrendIndex = -1;

  group.value = 'review_officer';
  const periodParams = (start, end) => ({date_from:start.value, date_to:end.value});
  const summary = (name, dates, extras={}) => {
    const query=new URLSearchParams({summary:name,...dates});
    for(const [key,value] of Object.entries(extras)){
      if(Array.isArray(value))value.forEach(item=>query.append(key,item));
      else if(value!==undefined&&value!==null&&value!=='')query.set(key,value);
    }
    return request(`${API}/uo-work-queue?${query}`);
  };
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
    const entityType=filters.entity_type||filters.supplier_type||'';
    if(entityType)queueRegistryFilters.entity_type=entityType;
    for (const key of ['review_officer','protocol_officer','protocol_card_officer']) {
      if (filters[key]) queueRegistryFilters[key]=filters[key];
    }
    if (status) {
      const statusLabels={active:'Допущено',unsuccessful:'Відхилено',pending:'Очікує рішення'};
      filterSelections.status.add(statusLabels[status]||status);
    }
    page=1;
    syncPrimaryFilters();
    updateMultiSummary('dkFilter','Усі коди ДК',filterSelections.dk);
    updateMultiSummary('statusFilter','Статус',filterSelections.status);
    $$('#statusFilter input[type="checkbox"]').forEach(input=>input.checked=filterSelections.status.has(input.value));
    const officers=Object.entries(queueRegistryFilters);
    const scope=$('#queueRegistryScope');
    const labels={review_officer:'УО розгляду',protocol_officer:'УО протоколу',protocol_card_officer:'УО протоколу',entity_type:'Тип постачальника'};
    const typeLabels={individual_entrepreneur:'ФОП',legal_entity:'ЮО та інші',foreign_legal_entity:'Нерезидент',unknown:'Потребує перевірки'};
    scope.textContent=officers.map(([key,value])=>`${labels[key]||key} · ${key==='entity_type'?typeLabels[value]||value:officerName(value===unassigned?'':value)}`).join(' · ');
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

  function countButton(count, filters, status, label='', tone='', showLabel=true) {
    const index=actions.push({filters,status})-1;
    return `<button type="button" class="ghost publication-kpi ${tone}${showLabel?'':' queue-statistics-number-only'}" data-statistics-action="${index}"${label?` aria-label="${esc(label)}: ${number(count)}"`:''}>${label&&showLabel?`<span>${esc(label)}</span>`:''}<strong>${number(count)}</strong></button>`;
  }

  function emptyCounts() { return {active:0,unsuccessful:0,pending:0,total:0}; }
  function addCounts(counts,row) {
    const count=Number(row.total||0);
    counts.total+=count;
    if (statuses.some(([code])=>code===row.status)) counts[row.status]+=count;
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

  function renderSelectOptions(options) {
    for(const control of controls){
      const key=control.dataset.statisticsFilter;
      if(key==='supplier_type')continue;
      const previous=control.value;
      const source=Array.isArray(options[key])?options[key]:[];
      const values=[...new Set(source.map(value=>String(value??'')))].filter(value=>value||key.endsWith('_officer'));
      const optionValues=values.map(value=>({value:value||unassigned,label:key.endsWith('_officer')?officerName(value):value}));
      if(previous&&!optionValues.some(item=>item.value===previous))optionValues.push({value:previous,label:previous===unassigned?'Не призначено':key.endsWith('_officer')?officerName(previous):previous});
      optionValues.sort((a,b)=>a.label.localeCompare(b.label,'uk'));
      control.replaceChildren(new Option('Усі',''),...optionValues.map(item=>new Option(item.label,item.value)));
      control.value=optionValues.some(item=>item.value===previous)?previous:'';
    }
  }

  function renderDkOptions() {
    const values=[...new Set([...dkValues,...dkSelection])].sort((a,b)=>a.localeCompare(b,'uk'));
    const query=dkSearch.value.trim().toLocaleLowerCase('uk');
    const matches=values.filter(value=>String(value).toLocaleLowerCase('uk').includes(query));
    const visible=[...new Set([...matches.slice(0,100),...values.filter(value=>dkSelection.has(value))])];
    const clipped=matches.length>100?`<span class="muted queue-statistics-dk-limit">Показано 100 із ${number(matches.length)}. Уточніть пошук.</span>`:'';
    dkOptions.innerHTML=(visible.map(value=>`<label><input type="checkbox" data-statistics-dk-option value="${esc(value)}" ${dkSelection.has(value)?'checked':''}> ${esc(value)}</label>`).join('')||'<span class="muted">Кодів ДК за цим пошуком немає</span>')+clipped;
    dkSummary.textContent=dkSelection.size?`Чернетка: ${dkSelection.size}`:'Усі коди';
  }

  function renderFilterPresentation() {
    const activeCount=Object.values(appliedSelection).filter(Boolean).length+(appliedDkSelection.size?1:0);
    filterSummary.textContent=activeCount?`Фільтри · ${activeCount}`:'Фільтри';
    filterToggle.classList.toggle('filter-active',activeCount>0);
    const drafts={};
    controls.forEach(control=>{drafts[control.dataset.statisticsFilter]=control.value||'';});
    const keys=new Set([...Object.keys(drafts),...Object.keys(appliedSelection),'dk_code']);
    let filtersPending=false;
    filterPanel.querySelectorAll('[data-statistics-filter-section]').forEach(section=>{
      const key=section.dataset.statisticsFilterSection;
      const active=key==='dk_code'?appliedDkSelection.size>0:Boolean(appliedSelection[key]);
      const draftChanged=key==='dk_code'
        ?[...dkSelection].sort().join('\0')!==[...appliedDkSelection].sort().join('\0')
        :(drafts[key]||'')!==(appliedSelection[key]||'');
      section.classList.toggle('filter-active',active);
      section.classList.toggle('filter-pending',draftChanged);
      const state=section.querySelector('.queue-statistics-section-state');
      if(state)state.textContent=draftChanged?'Зміни не застосовано':active?'Застосовано':'';
      const count=section.querySelector('.queue-statistics-section-count');
      if(count)count.textContent=active?(key==='dk_code'?`${appliedDkSelection.size} вибрано`:'1 вибрано')
        :key==='dk_code'?(dkSelection.size?`Чернетка: ${dkSelection.size}`:'Усі коди')
        :drafts[key]?`Чернетка`:'Усі';
      const clear=section.querySelector('[data-statistics-filter-reset]');
      if(clear)clear.hidden=!active;
      filtersPending=filtersPending||draftChanged;
    });
    fromField.classList.toggle('filter-active',Boolean(period?.date_from)&&from.value===period.date_from);
    toField.classList.toggle('filter-active',Boolean(period?.date_to)&&to.value===period.date_to);
    groupField.classList.toggle('filter-active',group.value!=='review_officer');
    const datesPending=Boolean(period)&&(from.value!==period.date_from||to.value!==period.date_to);
    pending.hidden=!datesPending&&!filtersPending;
    pending.textContent=[datesPending?'Зміни періоду ще не застосовано. Натисніть пошук, щоб оновити статистику.':'',filtersPending?'Зміни фільтрів ще не застосовано. Натисніть «Застосувати» в панелі.':''].filter(Boolean).join(' ');
  }

  function buildTrendBuckets(rows,startValue,endValue,granularity) {
    const parse=value=>{const [y,m,d]=String(value||'').slice(0,10).split('-').map(Number);return y&&m&&d?new Date(Date.UTC(y,m-1,d)):null;};
    const keyFor=date=>{
      const value=new Date(date);
      if(granularity==='week'){const day=(value.getUTCDay()+6)%7;value.setUTCDate(value.getUTCDate()-day);}
      if(granularity==='month')value.setUTCDate(1);
      return value.toISOString().slice(0,10);
    };
    const start=parse(startValue),end=parse(endValue);
    if(!start||!end||start>end)return [];
    const startKey=keyFor(start),endKey=keyFor(end),map=new Map();
    for(const row of rows){
      const date=parse(row.date);if(!date)continue;
      const key=keyFor(date),bucket=map.get(key)||{date:key,submitted:0,active:0,unsuccessful:0,pending:0,empty_status:0,unknown_status:0};
      for(const field of ['submitted','active','unsuccessful','pending','empty_status','unknown_status'])bucket[field]+=Number(row[field]||0);
      map.set(key,bucket);
    }
    const output=[];let cursor=parse(startKey),last=parse(endKey),guard=0;
    while(cursor&&cursor<=last&&guard<4001){
      const key=cursor.toISOString().slice(0,10),bucket=map.get(key)||{date:key,submitted:0,active:0,unsuccessful:0,pending:0,empty_status:0,unknown_status:0};
      const formatOptions=granularity==='month'?{month:'short',year:'numeric',timeZone:'UTC'}:{day:'2-digit',month:'2-digit',year:'numeric',timeZone:'UTC'};
      output.push({...bucket,label:new Intl.DateTimeFormat('uk-UA',formatOptions).format(cursor)});
      if(granularity==='month')cursor.setUTCMonth(cursor.getUTCMonth()+1);
      else cursor.setUTCDate(cursor.getUTCDate()+(granularity==='week'?7:1));
      guard++;
    }
    return guard>=4001?[]:output;
  }

  function showTrendTooltip(index) {
    if(index<0||index>=renderedTrend.length){trendTooltip.hidden=true;return;}
    const row=renderedTrend[index],x=54+(index/Math.max(1,renderedTrend.length-1))*820;
    trendTooltip.innerHTML=`<strong>${esc(row.label)}</strong><span>Надійшло: ${number(row.submitted)}</span><span>Допущено: ${number(row.active)}</span><span>Відхилено: ${number(row.unsuccessful)}</span><span>Очікує рішення: ${number(row.pending)}</span>`;
    trendTooltip.style.left=`${Math.max(1,Math.min(76,x/900*100))}%`;
    trendTooltip.hidden=false;
  }

  function renderTrend() {
    const rows=statisticsPayload?.trend||[];
    renderedTrend=buildTrendBuckets(rows,period?.date_from,period?.date_to,trendGranularity);
    const width=900,height=250,left=54,right=26,top=14,bottom=34,plotWidth=width-left-right,plotHeight=height-top-bottom;
    if(!renderedTrend.length){
      trendSvg.innerHTML='<text class="trend-empty" x="450" y="125" text-anchor="middle">Для цього періоду немає даних або обрано надто довгий денний період</text>';
      trendTooltip.hidden=true;
      return;
    }
    const max=Math.max(1,...renderedTrend.flatMap(row=>[row.submitted,row.active,row.unsuccessful]));
    const scale=max<=5?1:Math.pow(10,Math.floor(Math.log10(max)));
    const ceiling=Math.ceil(max/scale)*scale;
    const xAt=index=>left+(renderedTrend.length===1?plotWidth/2:index/(renderedTrend.length-1)*plotWidth);
    const yAt=value=>top+plotHeight-(value/ceiling)*plotHeight;
    const colors={submitted:'var(--statistics-submitted)',active:'var(--statistics-admitted)',unsuccessful:'var(--statistics-rejected)'};
    const paths=Object.entries(colors).map(([field,color])=>`<path class="trend-line trend-${field}" d="${renderedTrend.map((row,index)=>`${index?'L':'M'}${xAt(index).toFixed(2)},${yAt(row[field]).toFixed(2)}`).join(' ')}" fill="none" stroke="${color}" stroke-width="2.5" vector-effect="non-scaling-stroke"/>`).join('');
    const grid=[0,0.5,1].map(ratio=>{const y=top+plotHeight*(1-ratio),value=Math.round(ceiling*ratio);return `<g class="trend-grid"><line x1="${left}" y1="${y}" x2="${width-right}" y2="${y}"/><text x="${left-8}" y="${y+4}" text-anchor="end">${number(value)}</text></g>`;}).join('');
    const tickCount=Math.min(6,renderedTrend.length),ticks=Array.from({length:tickCount},(_,index)=>Math.round(index*(renderedTrend.length-1)/Math.max(1,tickCount-1)));
    const labels=ticks.map(index=>`<text class="trend-axis-label" x="${xAt(index)}" y="${height-8}" text-anchor="middle">${esc(renderedTrend[index].label)}</text>`).join('');
    const marker=activeTrendIndex>=0&&activeTrendIndex<renderedTrend.length?Object.keys(colors).map(field=>`<circle class="trend-marker trend-${field}" cx="${xAt(activeTrendIndex)}" cy="${yAt(renderedTrend[activeTrendIndex][field])}" r="4" fill="${colors[field]}"/>`).join(''):'';
    trendSvg.innerHTML=`<g class="trend-axis">${grid}${labels}</g>${paths}${marker}<rect class="trend-hit-area" x="${left}" y="${top}" width="${plotWidth}" height="${plotHeight}" fill="transparent"/>`;
  }

  function setFilterPanelOpen(open) {
    filterPanel.hidden=!open;
    filterToggle.setAttribute('aria-expanded',String(open));
    filterToggle.title=open?'Закрити фільтри':'Відкрити фільтри';
    workspace.classList.toggle('is-filter-open',open);
    if(typeof document!=='undefined')document.body.classList.toggle('queue-statistics-filter-open',open);
  }

  function applyDraftFilters(closePanel=true) {
    appliedSelection=Object.fromEntries(controls.filter(control=>control.value).map(control=>[control.dataset.statisticsFilter,control.value]));
    appliedDkSelection=new Set(dkSelection);
    renderFilterPresentation();
    loadStatistics();
    if(closePanel)setFilterPanelOpen(false);
  }

  async function loadStatistics() {
    const dates=periodParams(from,to), ticket=++statisticsRequest;
    if(!dates.date_from||!dates.date_to){message.textContent='Оберіть обидві дати для статистики';return;}
    if(dates.date_from>dates.date_to){message.textContent='Дата «До» має бути не раніше дати «Від»';return;}
    period=null;kpis.replaceChildren();table.replaceChildren();message.textContent='Завантаження…';
    try{
      const filters={};
      const entityType=appliedSelection.supplier_type||'';
      if(entityType)filters.entity_type=entityType;
      for(const key of ['category','review_officer','protocol_officer'])if(appliedSelection[key])filters[key]=appliedSelection[key];
      if(appliedDkSelection.size)filters.dk_code=[...appliedDkSelection];
      const data=await summary('application-statistics',dates,filters);
      if(ticket!==statisticsRequest)return;
      statisticsPayload=data||{};
      statistics=Array.isArray(data.items)?data.items:[];
      period=dates;
      activeTrendIndex=-1;
      const options=data.filter_options||{};
      dkValues=(options.dk_code||[]).filter(Boolean).map(String);
      renderSelectOptions(options);
      renderDkOptions();
      renderStatistics();
      renderTrend();
    }catch(error){if(ticket===statisticsRequest){message.textContent=error.message;trendSvg.replaceChildren();}}
  }

  function renderStatistics() {
    if(!period)return;
    const key=group.value,totals=statisticsPayload?.totals||emptyCounts(),groups=new Map();
    for(const row of statistics){
      const name=String(row[key]||'');
      if(!groups.has(name))groups.set(name,emptyCounts());
      addCounts(groups.get(name),row);
    }
    actions=[];
    const filters={...period,...appliedSelection};
    if(appliedDkSelection.size)filters.dk_code=[...appliedDkSelection];
    kpis.innerHTML=[
      countButton(totals.total||0,filters,'','Подано заявок','submitted'),
      ...statuses.map(([code,label,tone])=>countButton(totals[code]||0,filters,code,label,tone)),
    ].join('');
    const sorted=[...groups].sort(([a],[b])=>officerName(a).localeCompare(officerName(b),'uk'));
    table.innerHTML=sorted.map(([name,counts])=>{
      const scoped={...filters,[key]:name||unassigned};
      return `<tr><th scope="row">${esc(officerName(name))}</th>${statuses.map(([code,label])=>`<td>${countButton(counts[code],scoped,code,`${officerName(name)} · ${label}`,'',false)}</td>`).join('')}<td>${countButton(counts.total,scoped,'',`${officerName(name)} · Усього`,'',false)}</td></tr>`;
    }).join('');
    tableWrap.classList.toggle('queue-statistics-table--scroll',sorted.length>5);
    tableWrap.dataset.rowCount=String(sorted.length);
    fitTableViewport();
    const diagnostic=statisticsPayload?.diagnostics||{};
    const statusSum=Number(totals.active||0)+Number(totals.unsuccessful||0)+Number(totals.pending||0);
    const difference=Number(totals.total||0)-statusSum;
    const warnings=[];
    if(Number(diagnostic.empty_status||0))warnings.push(`порожній статус: ${number(diagnostic.empty_status)}`);
    if(Number(diagnostic.unknown_status||0))warnings.push(`невідомий статус: ${number(diagnostic.unknown_status)}`);
    if(difference)warnings.push(`усього ${number(totals.total)}, за трьома статусами ${number(statusSum)} (різниця ${number(difference)})`);
    if(Number(diagnostic.unknown_status||0)&&Array.isArray(diagnostic.unknown_values)){
      warnings.push(`значення: ${diagnostic.unknown_values.map(item=>`${String(item.status)} (${number(item.total)})`).join(', ')}`);
    }
    message.textContent=!Number(totals.total||0)?'Заявок за цими умовами немає':warnings.length?`Перевірка статусів Prozorro: ${warnings.join('; ')}.`:'';
    message.classList.toggle('queue-statistics-message--warning',warnings.length>0);
    renderFilterPresentation();
  }

  window.refreshQueueApplicationStatistics=()=>{
    loadProgress();
    if (initialized) return;
    const now=new Date(),today=`${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`;
    if(!from.value)from.value=`${now.getFullYear()}-01-01`;
    if(!to.value)to.value=today;
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
    appliedDkSelection.clear();
    appliedSelection={};
    dkSearch.value='';
    renderDkOptions();
    loadStatistics();
    renderFilterPresentation();
  };
  $('#queueStatisticsDkClear').onclick=()=>{dkSelection.clear();renderDkOptions();renderFilterPresentation();};
  $('#queueStatisticsFilterClose').onclick=()=>setFilterPanelOpen(false);
  filterPanel.onclick=event=>{
    const reset=event.target.closest('[data-statistics-filter-reset]');
    if(reset){
      const key=reset.dataset.statisticsFilterReset;
      if(key==='dk_code'){appliedDkSelection.clear();dkSelection.clear();dkSearch.value='';}
      else{delete appliedSelection[key];const control=controls.find(item=>item.dataset.statisticsFilter===key);if(control)control.value='';}
      loadStatistics();renderFilterPresentation();return;
    }
    const toggle=event.target.closest('.queue-statistics-section-toggle');
    if(toggle){
      const section=toggle.closest('.queue-statistics-filter-section');
      const content=section?.querySelector('.queue-statistics-filter-section-content');
      const open=toggle.getAttribute('aria-expanded')!=='true';
      toggle.setAttribute('aria-expanded',String(open));
      if(content)content.hidden=!open;
    }
  };
  dkSearch.addEventListener('input',()=>renderDkOptions());
  dkOptions.onchange=event=>{
    const input=event.target.closest('[data-statistics-dk-option]');
    if(!input)return;
    input.checked?dkSelection.add(input.value):dkSelection.delete(input.value);
    renderDkOptions();
    renderFilterPresentation();
  };
  trendGranularityControls.forEach(button=>button.onclick=()=>{
    trendGranularity=button.dataset.trendGranularity||'day';
    trendGranularityControls.forEach(item=>{const active=item===button;item.classList.toggle('is-active',active);item.setAttribute('aria-pressed',String(active));});
    activeTrendIndex=-1;trendTooltip.hidden=true;renderTrend();
  });
  trendSvg.onpointermove=event=>{
    const rect=trendSvg.getBoundingClientRect();
    const x=(event.clientX-rect.left)/Math.max(1,rect.width)*900;
    const fraction=Math.max(0,Math.min(1,(x-54)/820));
    activeTrendIndex=Math.round(fraction*Math.max(0,renderedTrend.length-1));
    renderTrend();showTrendTooltip(activeTrendIndex);
  };
  trendSvg.onpointerleave=()=>{activeTrendIndex=-1;trendTooltip.hidden=true;renderTrend();};
  trendSvg.onkeydown=event=>{
    if(!renderedTrend.length)return;
    if(event.key!=='ArrowLeft'&&event.key!=='ArrowRight')return;
    event.preventDefault();
    activeTrendIndex=Math.max(0,Math.min(renderedTrend.length-1,(activeTrendIndex<0?0:activeTrendIndex)+(event.key==='ArrowRight'?1:-1)));
    renderTrend();showTrendTooltip(activeTrendIndex);
  };
  if(typeof document!=='undefined')document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!filterPanel.hidden)setFilterPanelOpen(false);});
  for (const root of [kpis,table]) root.onclick=event=>{
    const button=event.target.closest('[data-statistics-action]');
    const action=button&&actions[Number(button.dataset.statisticsAction)];
    if (action) openRegister(action.filters,action.status,false);
  };
  $('#clearFiltersBtn').addEventListener('click',()=>{$('#queueRegistryScope').hidden=true;},true);
})();
