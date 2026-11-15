/* Compact Apply status and safe, copyable continuation details. Never retries Apply. */
(function(root){
  'use strict';
  const STORAGE_KEY='pqm.googleWriter.applyResult.v1';
  const doc=root.document;
  const compact=doc?.getElementById('googleWriterApplyCompact');
  const compactStatus=doc?.getElementById('googleWriterApplyCompactStatus');
  const compactHttp=doc?.getElementById('googleWriterApplyCompactHttp');
  const openDetails=doc?.getElementById('googleWriterApplyDetailsOpen');
  const detailsDialog=doc?.getElementById('googleWriterApplyDetailsDialog');
  const detailsBody=doc?.getElementById('googleWriterApplyDetailsBody');
  const copyButton=doc?.getElementById('googleWriterApplyCopy');
  const copyStatus=doc?.getElementById('googleWriterApplyCopyStatus');
  const refresh=doc?.getElementById('googleWriterApplyDiagnosticRefresh');
  const clearReadOnly=doc?.getElementById('googleWriterApplyReadOnlyClear');
  const requestIdInput=doc?.getElementById('googleWriterApplyRequestId');
  const checkButton=doc?.getElementById('googleWriterApplyDiagnosticCheck');
  const lookupStatus=doc?.getElementById('googleWriterApplyLookupStatus');
  const savedAuditButton=doc?.getElementById('googleWriterSavedContinuationAudit');
  const savedAuditStatus=doc?.getElementById('googleWriterSavedContinuationAuditStatus');
  const savedAuditResult=doc?.getElementById('googleWriterSavedContinuationAuditResult');
  const savedAuditCopy=doc?.getElementById('googleWriterSavedContinuationAuditCopy');
  const savedAuditCopyStatus=doc?.getElementById('googleWriterSavedContinuationAuditCopyStatus');
  const originalRequest=root.request;
  if(typeof originalRequest!=='function')return;
  let continuation=null,applyLockMode=null,applyRequestInFlight=false,diagnosticBusy=false,savedAuditBusy=false;
  let state={version:1,requestId:null,httpStatus:null,code:null,level:'none',started:null,
    description:'Збереженого результату Apply немає.',diagnostic:null,savedContinuationAudit:null,
    diagnosticCheckedAt:null,savedAuditCheckedAt:null,applyLockMode:null};
  const REQUEST_ID_RE=/^[0-9a-f]{32}$/;
  const safeCode=value=>{
    if(typeof value!=='string'||value.length>64||/^[0-9a-f]{32,}$/i.test(value))return 'APPLY_RESULT_UNCLASSIFIED';
    if(/^[A-Z][A-Z0-9_]{0,63}$/.test(value))return value;
    if(/^[a-z][a-z0-9_]{0,63}$/.test(value))return value.toUpperCase();
    return 'APPLY_RESULT_UNCLASSIFIED';
  };
  const safeDiagnostic=value=>{
    const allowed=new Set(['UNAVAILABLE','BLOCKED','preview_saved','running','partial','outcome_unknown',
      'failed_safe','complete','closed_unknown','closed_prewrite']);
    const result={status:allowed.has(value?.status)?value.status:'UNAVAILABLE'};
    if(Array.isArray(value?.reason_codes))result.reason_codes=value.reason_codes.map(safeCode);
    if(Number.isInteger(value?.confirmed_append)&&value.confirmed_append>=0)result.confirmed_append=value.confirmed_append;
    if(Number.isInteger(value?.attempted_chunk)&&value.attempted_chunk>=0)result.attempted_chunk=value.attempted_chunk;
    if(value?.checkpoint&&typeof value.checkpoint.present==='boolean')result.checkpoint={
      present:value.checkpoint.present,...(Number.isInteger(value.checkpoint.next_chunk)?{next_chunk:value.checkpoint.next_chunk}:{})};
    if(value?.receipts&&Number.isInteger(value.receipts.verified_count)&&value.receipts.verified_count>=0)
      result.receipts={verified_count:value.receipts.verified_count};
    return result;
  };
  const safeCount=value=>Number.isInteger(value)&&value>=0?value:null;
  const checkedAtText=value=>{
    if(typeof value!=='string'||Number.isNaN(Date.parse(value)))return '';
    return new Intl.DateTimeFormat('uk-UA',{timeZone:'Europe/Kyiv',day:'2-digit',month:'2-digit',
      year:'numeric',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(value));
  };
  const lastCheckSuffix=value=>{const text=checkedAtText(value);return text?` · Остання успішна перевірка: ${text}`:'';};
  function readOnlyButtonsBusy(busy){
    for(const [button,label] of [[refresh,'Оновити read-only стан'],[checkButton,'Перевірити стан']])if(button){
      button.disabled=!!busy;button.textContent=busy?'Виконується запит…':label;
      if(busy)button.setAttribute?.('aria-busy','true');else button.removeAttribute?.('aria-busy');
    }
  }
  const safeRunState=value=>typeof value==='string'&&/^[a-z_]{1,32}$/.test(value)?value:'UNAVAILABLE';
  const safeChunkSummary=value=>{
    const states={};
    if(value?.states&&typeof value.states==='object'&&!Array.isArray(value.states))
      for(const [key,count] of Object.entries(value.states))
        if(['prepared','inflight','verified','outcome_unknown','reconciled'].includes(key)&&Number.isInteger(count)&&count>=0)
          states[key]=count;
    return {count:safeCount(value?.count),states,unresolved:safeCount(value?.unresolved),
      receipt_count:safeCount(value?.receipt_count)};
  };
  const safeUnresolvedChunks=value=>Array.isArray(value)?value.slice(0,50).map(item=>{
    const bindings={};
    const allowed=['journal_plan_id','journal_run_id','journal_scope','journal_phase','manifest_version',
      'manifest_plan_id','manifest_run_id','manifest_scope','manifest_chunk_index','manifest_plan_digest',
      'manifest_source_digest','plan_operations','journal_chunk_digest','journal_chunk_id'];
    for(const key of allowed)bindings[key]=['MATCH','MISMATCH','NOT_CHECKED'].includes(item?.bindings?.[key])?
      item.bindings[key]:'NOT_CHECKED';
    const counts=item?.sheet_counts||{};
    return {state:safeRunState(item?.state),chunk_index:safeCount(item?.chunk_index),
      scope:['APPEND_ONLY','ALL'].includes(item?.scope)?item.scope:'UNKNOWN',
      phase:['append','update'].includes(item?.phase)?item.phase:'unknown',
      expected_operations:safeCount(item?.expected_operations),
      plan_operations_matched:safeCount(item?.plan_operations_matched),
      verified_at_present:item?.verified_at_present===true,
      operations_match:['MATCH','MISMATCH','NOT_CHECKED'].includes(item?.operations_match)?item.operations_match:'NOT_CHECKED',
      manifest_binding:['MATCH','MISMATCH','UNAVAILABLE'].includes(item?.manifest_binding)?item.manifest_binding:'UNAVAILABLE',
      bindings,sheet_status:['MATCH','MISMATCH','UNAVAILABLE'].includes(item?.sheet_status)?item.sheet_status:'UNAVAILABLE',
      sheet_counts:{confirmed:safeCount(counts.confirmed),missing:safeCount(counts.missing),
        conflict:safeCount(counts.conflict),unverified:safeCount(counts.unverified)},
      receipt_state:['MISSING','PRESENT_UNVERIFIED','INVALID'].includes(item?.receipt_state)?item.receipt_state:'INVALID'};
  }):[];
  const safeSourceRecovery=value=>({
    status:['READY','BLOCKED','UNAVAILABLE'].includes(value?.status)?value.status:'UNAVAILABLE',
    reason_codes:Array.isArray(value?.reason_codes)?value.reason_codes.slice(0,20).map(safeCode):[],
    manifest_mismatch_fields:Array.isArray(value?.manifest_mismatch_fields)?value.manifest_mismatch_fields.slice(0,250).filter(field=>
      typeof field==='string'&&/^manifest(?:\.chunkIndex|\.chunkId|\.chunkDigest|\.planId|\.runId|\.rows|\.rows\.length|\.rows\[\d{1,2}\]\.(?:target|preview|tab|row|code|cellsDigest|formulaA|serviceMetadata(?:\.(?:addedAt|planId|runId))?))?$/.test(field)):[],
    first_chunk_recovery_evidence:typeof value?.first_chunk_recovery_evidence==='boolean'?
      value.first_chunk_recovery_evidence:null});
  const safeSourceRunEvidence=value=>({
    scope:['APPEND_ONLY','ALL'].includes(value?.scope)?value.scope:'UNKNOWN',
    attempted_chunk:safeCount(value?.attempted_chunk),
    outcome_unknown:typeof value?.outcome_unknown==='boolean'?value.outcome_unknown:null});
  const safeSourceClose=value=>({
    status:value?.status==='VALIDATED'?'VALIDATED':'UNAVAILABLE',
    closed:value?.closed===true,
    disposition:value?.disposition==='OUTCOME_UNKNOWN_NOT_CONFIRMED'?'OUTCOME_UNKNOWN_NOT_CONFIRMED':'UNAVAILABLE',
    receipt_verified:value?.receipt_verified===true});
  const AUDIT_CHECKS={
    plan_matches:'План збігається з відсутніми операціями',
    preserved_match:'Збережені 25 рядків відповідають контрольним даним',
    source_counts:'Лічильники початкового плану',
    preserved_counts:'Лічильники раніше підтверджених рядків',
    source_chunks_unresolved:'Невирішені порції початкового запуску',
    continuation_chunks_unresolved:'Невирішені порції продовження',
    additional_saved_previews:'Додаткові збережені Preview',
    continuation_preview:'Стан збереженого Preview продовження',
    linked_runs_unresolved:'Невирішені пов’язані запуски',
    competing_attempts:'Інші спроби продовження',
    continuation_conflicts:'Конфлікти продовження',
    continuation_unverified:'Неперевірені операції продовження'};
  const safeAuditChecks=value=>{
    if(!value||typeof value!=='object'||Array.isArray(value))return null;
    const result={};
    for(const key of Object.keys(AUDIT_CHECKS)){
      const check=value[key];if(!check||typeof check!=='object'||Array.isArray(check)){
        result[key]={status:'NOT_CHECKED'};continue;
      }
      const status=['MATCH','MISMATCH','NOT_CHECKED'].includes(check.status)?check.status:'NOT_CHECKED';
      const safe={status};
      if(Object.prototype.hasOwnProperty.call(check,'count'))safe.count=safeCount(check.count);
      if(Object.prototype.hasOwnProperty.call(check,'state'))safe.state=
        ['preview_saved','running','partial','outcome_unknown','failed_safe','complete','closed_unknown',
          'closed_prewrite','BLOCKED','UNAVAILABLE'].includes(check.state)?check.state:'UNAVAILABLE';
      result[key]=safe;
    }
    return result;
  };
  const safeSavedContinuationAudit=value=>{
    if(!value||!['VERIFIED','BLOCKED','UNAVAILABLE'].includes(value.status))return null;
    const source=value.source||{},continuation=value.continuation||{},related=value.related||{};
    return {status:value.status,reason_codes:Array.isArray(value.reason_codes)?value.reason_codes.map(safeCode):[],
      source:{planned:safeCount(source.planned),confirmed:safeCount(source.confirmed),missing:safeCount(source.missing),
        conflict:safeCount(source.conflict),unverified:safeCount(source.unverified)},
      preserved:{planned:safeCount(value.preserved?.planned),confirmed:safeCount(value.preserved?.confirmed),
        missing:safeCount(value.preserved?.missing),conflict:safeCount(value.preserved?.conflict),
        unverified:safeCount(value.preserved?.unverified)},
      continuation:{planned:safeCount(continuation.planned),present:safeCount(continuation.present),
        missing:safeCount(continuation.missing),duplicate:safeCount(continuation.duplicate),
        conflict:safeCount(continuation.conflict),unverified:safeCount(continuation.unverified)},
      related:{source_run:safeRunState(related.source_run),
        source_run_evidence:safeSourceRunEvidence(related.source_run_evidence),
        source_close:safeSourceClose(related.source_close),
        continuation_runs:Array.isArray(related.continuation_runs)?related.continuation_runs.slice(0,20).map(item=>({
          status:safeRunState(item?.status),scope:item?.scope==='APPEND_ONLY'?'APPEND_ONLY':'UNKNOWN',
          attempted_chunk_present:item?.attempted_chunk_present===true})):[],
        source_chunks:safeChunkSummary(related.source_chunks),
        continuation_chunks:safeChunkSummary(related.continuation_chunks),
        source_checkpoint:related.source_checkpoint===true,
        continuation_checkpoints:safeCount(related.continuation_checkpoints),
        continuation_verified_receipts:safeCount(related.continuation_verified_receipts),
        additional_saved_previews:safeCount(related.additional_saved_previews),
        source_unresolved_chunk_details:safeUnresolvedChunks(related.source_unresolved_chunk_details),
        source_recovery:safeSourceRecovery(related.source_recovery)},
      checks:safeAuditChecks(value.checks)};
  };
  const descriptionFor=code=>({
    APPLY_REQUEST_PENDING:'Запит надіслано; очікується відповідь сервера. Не натискайте Apply повторно.',
    CONTINUATION_PREVIEW_STALE:'Стан таблиці або плану змінився після Preview. Новий запуск не розпочато.',
    CONTINUATION_BINDING_INVALID:'Прив’язки continuation не пройшли перевірку.',
    PREVIEW_BINDING_INVALID:'Збережений Preview не пройшов перевірку.',
    APPLY_NOT_STARTED_CONFIRMED:'Read-only перевірка підтвердила, що запуск не створений; можна отримати новий Preview.',
    APPLY_CHANNEL_UNAVAILABLE:'Захищений канал недоступний; потрібна перевірка журналу.',
    APPLY_PRECHECK_UNAVAILABLE:'Передзаписна перевірка не завершилася однозначно.',
    APPLY_REQUEST_REJECTED:'Запит відхилено сервером до підтвердженого запуску.',
    APPLY_OUTCOME_UNCONFIRMED:'Сервер не підтвердив, чи запустився новий worker.'
  })[code]||'Сервер відхилив або не підтвердив запуск. Перевірте read-only журнал перед будь-якою наступною дією.';
  function statusLabel(){return state?.level==='success'?'SUCCESS':state?.level==='blocked'?'BLOCKED':
    state?.level==='none'?'Немає результату Apply':'STOP';}
  function save(){try{root.sessionStorage?.setItem(STORAGE_KEY,JSON.stringify(state));}catch{}}
  function diagnosticRows(){
    const d=state?.diagnostic;
    const started=state?.started===true?'так':state?.started===false?'ні':'невідомо';
    const applyExists=state?.level!=='none';
    const rows=[['Результат Apply',statusLabel()],['HTTP-статус',applyExists?(state?.httpStatus??'невідомий'):'не застосовується'],
      ['Код відповіді',applyExists?safeCode(state?.code):'немає результату Apply'],
      ['Безпечний опис',state?.description||'Збереженого результату Apply немає.'],
      ['Новий запуск розпочато',applyExists?started:'невідомо']];
    if(state?.diagnosticCheckedAt)rows.push(['Остання успішна read-only перевірка',checkedAtText(state.diagnosticCheckedAt)]);
    if(!d||d.status==='UNAVAILABLE'||d.status==='BLOCKED'){
      rows.push(['Результат read-only перевірки',!d?'ще не перевірявся':d.status==='BLOCKED'?'BLOCKED':'неможливо перевірити'],
        ['Стан continuation run','не підтверджено'],['Підтверджені APPEND','не підтверджено'],
        ['attempted_chunk','не підтверджено'],['Checkpoint','не підтверджено'],['Receipts','не підтверджено']);
      if(d?.reason_codes?.length)rows.push(['Причини недоступності',d.reason_codes.join(', ')]);
      return rows;
    }
    rows.push(['Результат read-only перевірки','стан підтверджено'],['Стан continuation run',d.status],
      ['Підтверджені APPEND',Number.isInteger(d.confirmed_append)?d.confirmed_append:'не підтверджено'],
      ['attempted_chunk',Number.isInteger(d.attempted_chunk)?d.attempted_chunk:'не зафіксовано'],
      ['Checkpoint',d.checkpoint?.present===true?`є; наступний chunk ${d.checkpoint.next_chunk}`:'не підтверджено'],
      ['Receipts',Number.isInteger(d.receipts?.verified_count)?d.receipts.verified_count:'не підтверджено']);
    if(d.reason_codes?.length)rows.push(['Причини діагностики',d.reason_codes.join(', ')]);
    return rows;
  }
  function savedAuditRows(){
    const audit=state?.savedContinuationAudit;
    if(!audit)return [['Звірка збереженого продовження','ще не запускалася']];
    const rows=[['Звірка збереженого продовження',audit.status]];
    if(state?.savedAuditCheckedAt)rows.push(['Остання успішна read-only звірка',checkedAtText(state.savedAuditCheckedAt)]);
    if(audit.reason_codes.length)rows.push(['Причини',audit.reason_codes.join(', ')]);
    rows.push(['Початковий план · підтверджено',audit.source.confirmed??'не перевірено'],
      ['Початковий план · відсутні',audit.source.missing??'не перевірено'],
      ['Початковий план · конфлікти',audit.source.conflict??'не перевірено'],
      ['Раніше підтверджені 25 · підтверджено',audit.preserved.confirmed??'не перевірено'],
      ['Раніше підтверджені 25 · відсутні',audit.preserved.missing??'не перевірено'],
      ['Раніше підтверджені 25 · конфлікти',audit.preserved.conflict??'не перевірено'],
      ['Продовження · вже присутні й підтверджені',audit.continuation.present??'не перевірено'],
      ['Продовження · відсутні',audit.continuation.missing??'не перевірено'],
      ['Продовження · дублікати',audit.continuation.duplicate??'не перевірено'],
      ['Продовження · конфлікти',audit.continuation.conflict??'не перевірено'],
      ['Продовження · неперевірені',audit.continuation.unverified??'не перевірено'],
      ['Стан початкового запуску',audit.related.source_run],
      ['Сфера/attempted_chunk початкового запуску',`${audit.related.source_run_evidence.scope} / ${audit.related.source_run_evidence.attempted_chunk??'не зафіксовано'}`],
      ['Прапорець outcome_unknown',audit.related.source_run_evidence.outcome_unknown===true?'так':
        audit.related.source_run_evidence.outcome_unknown===false?'ні':'не підтверджено'],
      ['Адміністративне закриття',`${audit.related.source_close.status}; ${audit.related.source_close.disposition}; receipt ${audit.related.source_close.receipt_verified?'перевірено':'не підтверджено'}`],
      ['Пов’язані continuation-запуски',audit.related.continuation_runs.length],
      ['Порції початкового запуску',audit.related.source_chunks.count??'не перевірено'],
      ['Порції continuation',audit.related.continuation_chunks.count??'не перевірено'],
      ['Checkpoint continuation',audit.related.continuation_checkpoints??'не перевірено'],
      ['Перевірені receipts continuation',audit.related.continuation_verified_receipts??'не перевірено'],
      ['Інші збережені Preview',audit.related.additional_saved_previews??'не перевірено']);
    rows.push(['Перевірка recovery початкового запуску',audit.related.source_recovery.status],
      ['Причини recovery перевірки',audit.related.source_recovery.reason_codes.join(', ')||'немає підтверджених кодів'],
      ['Поля manifest із розбіжностями',audit.related.source_recovery.manifest_mismatch_fields.join(', ')||'не повідомлені'],
      ['Доказ першої порції для recovery',audit.related.source_recovery.first_chunk_recovery_evidence===true?'MATCH':
        audit.related.source_recovery.first_chunk_recovery_evidence===false?'MISMATCH':'NOT_CHECKED']);
    for(const [index,chunk] of audit.related.source_unresolved_chunk_details.entries()){
      const label=`Невирішена порція початкового запуску ${chunk.chunk_index??index}`;
      rows.push([label,`${chunk.state}; ${chunk.scope}/${chunk.phase}; operations=${chunk.expected_operations??'UNAVAILABLE'}; plan match=${chunk.operations_match}; manifest=${chunk.manifest_binding}; sheet=${chunk.sheet_status}; receipt=${chunk.receipt_state}`]);
      rows.push([`${label} verified_at`,chunk.verified_at_present?'є':'відсутній']);
      const badBindings=Object.entries(chunk.bindings).filter(([,status])=>status!=='MATCH');
      if(badBindings.length)rows.push([`${label} · поля прив’язки`,badBindings.map(([field,status])=>`${field}=${status}`).join(', ')]);
      if(chunk.sheet_status==='MATCH')rows.push([`${label} sheet counts`,
        `confirmed=${chunk.sheet_counts.confirmed??'UNAVAILABLE'}, missing=${chunk.sheet_counts.missing??'UNAVAILABLE'}, conflict=${chunk.sheet_counts.conflict??'UNAVAILABLE'}, unverified=${chunk.sheet_counts.unverified??'UNAVAILABLE'}`]);
    }
    if(audit.checks){
      const checkRows=Object.entries(AUDIT_CHECKS).map(([key,label])=>{
        const check=audit.checks[key];if(!check)return null;
        const parts=[check.status];
        if(check.count!==undefined)parts.push(`кількість: ${check.count??'не перевірено'}`);
        if(check.state)parts.push(`стан: ${check.state}`);
        return [label,parts.join(' · ')];
      }).filter(Boolean);
      if(audit.status==='BLOCKED'){
        const failed=checkRows.filter(([,value])=>value.startsWith('MISMATCH'))
          .map(([label])=>label);
        rows.push(['Конкретні умови BLOCKED',failed.length?failed.join('; '):'Підстава не деталізована сервером']);
      }
      rows.push(...checkRows);
    }else if(audit.status==='BLOCKED'){
      rows.push(['Конкретні умови BLOCKED','Ця версія відповіді не містить деталізації перевірок']);
    }
    return rows;
  }
  function savedAuditText(){
    return ['PQM Google Writer — read-only звірка продовження',...savedAuditRows().map(([label,value])=>`${label}: ${value}`),
      'SQLite writes: 0','Google Sheets writes: 0','Script Properties writes: 0',
      'Новий Preview, ключ підтвердження, запуск, порція або checkpoint: не створювалися'].join('\n');
  }
  function render(){
    if(compact){
      compact.hidden=false;compact.dataset.state=state.level==='none'?
        (state.diagnostic?.status==='BLOCKED'?'blocked':state.diagnostic?.status==='UNAVAILABLE'?'stop':'none'):state.level;
      if(compactStatus)compactStatus.textContent=statusLabel();
      if(compactHttp)compactHttp.textContent=state.level==='none'?
        (state.diagnostic?.status==='BLOCKED'?'Read-only: BLOCKED':state.diagnostic?.status==='UNAVAILABLE'?'Стан не вдалося перевірити':
          state.diagnostic?`Стан: ${state.diagnostic.status}`:'Стан ще не перевірявся'):
        `HTTP ${state.httpStatus??'—'}`;
    }
    if(!detailsBody)return;
    detailsBody.replaceChildren();
    for(const [label,value] of diagnosticRows()){
      const item=doc.createElement('dl');item.className='google-writer-apply-detail';
      const term=doc.createElement('dt');term.textContent=label;
      const description=doc.createElement('dd');description.textContent=String(value);
      item.append(term,description);detailsBody.appendChild(item);
    }
    if(savedAuditResult){
      savedAuditResult.replaceChildren();
      for(const [label,value] of savedAuditRows()){
        const item=doc.createElement('dl');item.className='google-writer-apply-detail';
        const term=doc.createElement('dt');term.textContent=label;
        const description=doc.createElement('dd');description.textContent=String(value);
        item.append(term,description);savedAuditResult.appendChild(item);
      }
    }
    if(savedAuditCopy)savedAuditCopy.disabled=!state?.savedContinuationAudit;
  }
  function diagnosticText(){
    return ['PQM Google Writer — безпечна діагностика',...diagnosticRows().map(([label,value])=>`${label}: ${value}`)].join('\n');
  }
  async function copyDiagnostic(){
    if(!state)return;
    const text=diagnosticText();
    try{
      if(root.navigator?.clipboard?.writeText)await root.navigator.clipboard.writeText(text);
      else {
        const textarea=doc.createElement('textarea');textarea.value=text;textarea.setAttribute('readonly','');
        textarea.style.position='fixed';textarea.style.opacity='0';doc.body.appendChild(textarea);textarea.select();
        if(!doc.execCommand('copy'))throw new Error('clipboard unavailable');textarea.remove();
      }
      if(copyStatus)copyStatus.textContent='Безпечну діагностику скопійовано.';
    }catch{if(copyStatus)copyStatus.textContent='Не вдалося скопіювати. Відкрийте деталі й скопіюйте текст вручну.';}
  }
  async function copySavedAudit(){
    if(!state?.savedContinuationAudit)return;
    try{
      if(root.navigator?.clipboard?.writeText)await root.navigator.clipboard.writeText(savedAuditText());
      else {
        const textarea=doc.createElement('textarea');textarea.value=savedAuditText();textarea.setAttribute('readonly','');
        textarea.style.position='fixed';textarea.style.opacity='0';doc.body.appendChild(textarea);textarea.select();
        if(!doc.execCommand('copy'))throw new Error('clipboard unavailable');textarea.remove();
      }
      if(savedAuditCopyStatus)savedAuditCopyStatus.textContent='Безпечний звіт скопійовано.';
    }catch{if(savedAuditCopyStatus)savedAuditCopyStatus.textContent='Не вдалося скопіювати звіт.';}
  }
  async function auditSavedContinuation(){
    if(savedAuditBusy)return false;
    const requestId=requestIdInput?.value?.trim()||'';
    if(!REQUEST_ID_RE.test(requestId)){
      state.savedContinuationAudit=safeSavedContinuationAudit({status:'UNAVAILABLE',reason_codes:['REQUEST_ID_INVALID']});
      if(savedAuditStatus)savedAuditStatus.textContent='UNAVAILABLE · REQUEST_ID_INVALID';
      save();render();return false;
    }
    savedAuditBusy=true;
    if(savedAuditButton){savedAuditButton.disabled=true;savedAuditButton.textContent='Виконується запит…';savedAuditButton.setAttribute?.('aria-busy','true');}
    if(savedAuditStatus)savedAuditStatus.textContent='Читаються збережений план і поточний стан Google Sheets…';
    if(savedAuditCopyStatus)savedAuditCopyStatus.textContent='';
    try{
      const response=await originalRequest(`/api/admin/google-writer/saved-continuation-audit/${requestId}`);
      let audit=safeSavedContinuationAudit(response);
      if(response?.request_id!==requestId)audit=safeSavedContinuationAudit({status:'BLOCKED',reason_codes:['REQUEST_BINDING_MISMATCH']});
      else if(response?.read_only!==true||response?.sqlite_writes!==0||response?.sheets_writes!==0||
          response?.properties_writes!==0||response?.preview_created!==false||response?.ticket_created!==false||
          response?.writer_started!==false)
        audit=safeSavedContinuationAudit({status:'BLOCKED',reason_codes:['READ_ONLY_CONTRACT_UNCONFIRMED']});
      else state.savedAuditCheckedAt=new Date().toISOString();
      if(!audit)audit=safeSavedContinuationAudit({status:'UNAVAILABLE',reason_codes:['AUDIT_RESPONSE_INVALID']});
      state.savedContinuationAudit=audit;
      if(response?.request_id===requestId)state.diagnosticRequestId=requestId;
      if(savedAuditStatus)savedAuditStatus.textContent=`${audit.status}${audit.reason_codes.length?' · '+audit.reason_codes.join(', '):''}${lastCheckSuffix(state.savedAuditCheckedAt)}`;
      save();render();return audit.status==='VERIFIED';
    }catch(error){
      state.savedContinuationAudit=safeSavedContinuationAudit({status:'UNAVAILABLE',
        reason_codes:[safeCode(error?.code||'SAVED_CONTINUATION_AUDIT_UNAVAILABLE')]});
      if(savedAuditStatus)savedAuditStatus.textContent=`Не вдалося виконати звірку · ${state.savedContinuationAudit.reason_codes.join(', ')}${lastCheckSuffix(state.savedAuditCheckedAt)}`;
      save();render();return false;
    }finally{
      savedAuditBusy=false;
      if(savedAuditButton){savedAuditButton.disabled=false;savedAuditButton.textContent='Звірити збережене продовження';savedAuditButton.removeAttribute?.('aria-busy');}
    }
  }
  async function refreshDiagnostic(requestIdOverride=null,explicitUserCheck=false){
    if(diagnosticBusy)return false;
    const requestId=(requestIdOverride!==null?requestIdOverride:state?.diagnosticRequestId||state?.requestId||requestIdInput?.value)?.trim();
    if(!REQUEST_ID_RE.test(requestId||'')){
      if(lookupStatus)lookupStatus.textContent='Введіть request ID із 32 символів a–f та 0–9.';
      return false;
    }
    diagnosticBusy=true;readOnlyButtonsBusy(true);
    if(lookupStatus)lookupStatus.textContent='Виконується запит до read-only стану…';
    try{
      const result=await originalRequest(`/api/google-writer/continuation-status/${requestId}`);
      const diagnostic=safeDiagnostic(result);
      if(result?.read_only!==true){
        state.diagnostic={status:'BLOCKED',reason_codes:['READ_ONLY_NOT_CONFIRMED']};
        if(lookupStatus)lookupStatus.textContent='BLOCKED · відповідь не підтвердила read-only режим.';
      }else if(result?.request_id!==undefined&&result.request_id!==requestId){
        state.diagnostic={status:'BLOCKED',reason_codes:['REQUEST_BINDING_MISMATCH']};
        if(lookupStatus)lookupStatus.textContent='BLOCKED · відповідь не відповідає запитаному запуску.';
      }else{
        state.diagnostic=diagnostic;
        if(lookupStatus)lookupStatus.textContent=diagnostic.status==='UNAVAILABLE'?
          `Не вдалося перевірити стан · ${(diagnostic.reason_codes||[]).join(', ')||'CONTINUATION_STATUS_UNAVAILABLE'}`:
          diagnostic.status==='BLOCKED'?`BLOCKED · ${(diagnostic.reason_codes||[]).join(', ')||'CONTINUATION_DATA_MISMATCH'}`:
          `Стан continuation підтверджено: ${diagnostic.status}.`;
        // Persist an identifier only after the endpoint echoes the exact, validated binding.
        if(result?.request_id===requestId){
          state.diagnosticRequestId=requestId;
          if(result?.read_only===true)state.diagnosticCheckedAt=new Date().toISOString();
          const noRunConfirmed=diagnostic.status==='preview_saved'&&diagnostic.confirmed_append===0&&
            diagnostic.attempted_chunk===undefined&&diagnostic.checkpoint?.present===false&&
            diagnostic.receipts?.verified_count===0;
          if(explicitUserCheck&&applyLockMode==='unknown'&&!applyRequestInFlight&&requestId===state.requestId&&noRunConfirmed){
            applyLockMode=null;state.applyLockMode=null;state.started=false;state.level='blocked';
            state.code='APPLY_NOT_STARTED_CONFIRMED';state.description=descriptionFor(state.code);
            if(lookupStatus)lookupStatus.textContent='Read-only перевірка підтвердила: запуск не створено.';
          }
        }
      }
      if(lookupStatus&&state.diagnosticCheckedAt)lookupStatus.textContent+=lastCheckSuffix(state.diagnosticCheckedAt);
      save();render();return true;
    }catch{
      state.diagnostic={status:'UNAVAILABLE',reason_codes:['CONTINUATION_STATUS_UNAVAILABLE']};
      if(lookupStatus)lookupStatus.textContent=`Не вдалося перевірити стан · CONTINUATION_STATUS_UNAVAILABLE${lastCheckSuffix(state.diagnosticCheckedAt)}`;
      save();render();return false;
    }finally{diagnosticBusy=false;readOnlyButtonsBusy(false);}
  }
  function clearReadOnlyState(){
    state.diagnostic=null;state.diagnosticRequestId=null;state.savedContinuationAudit=null;
    state.diagnosticCheckedAt=null;state.savedAuditCheckedAt=null;
    if(requestIdInput)requestIdInput.value='';
    if(lookupStatus)lookupStatus.textContent='Локальний read-only стан очищено; серверні дані не змінювалися.';
    if(savedAuditStatus)savedAuditStatus.textContent='Звірку ще не запускали.';
    if(savedAuditCopyStatus)savedAuditCopyStatus.textContent='';
    save();render();return true;
  }
  function setResult(next){
    applyLockMode=next.started===true?'started':next.started!==false&&next.level==='stop'?'unknown':null;
    applyRequestInFlight=false;
    state={version:1,requestId:next.requestId,httpStatus:next.httpStatus??null,code:safeCode(next.code),
      level:next.level,started:next.started===true?true:next.started===false?false:null,
      description:descriptionFor(safeCode(next.code)),diagnosticRequestId:next.requestId,diagnostic:null,
      diagnosticCheckedAt:null,savedAuditCheckedAt:state.savedAuditCheckedAt,
      savedContinuationAudit:state.savedContinuationAudit,applyLockMode};
    save();render();void refreshDiagnostic();
  }
  try{
    const saved=JSON.parse(root.sessionStorage?.getItem(STORAGE_KEY)||'null');
    if(saved&&saved.version===1&&(REQUEST_ID_RE.test(saved.requestId||'')||REQUEST_ID_RE.test(saved.diagnosticRequestId||'')||saved.level==='none')){
      state={version:1,requestId:REQUEST_ID_RE.test(saved.requestId||'')?saved.requestId:null,httpStatus:Number.isInteger(saved.httpStatus)?saved.httpStatus:null,
        code:safeCode(saved.code),level:['success','blocked','stop','none','not_started'].includes(saved.level)?
          (saved.level==='not_started'?'blocked':saved.level):'stop',
        started:saved.started===true?true:saved.started===false?false:null,
        description:descriptionFor(safeCode(saved.code)),diagnosticRequestId:REQUEST_ID_RE.test(saved.diagnosticRequestId||'')?saved.diagnosticRequestId:null,
          diagnostic:saved.diagnostic?safeDiagnostic(saved.diagnostic):null,
          savedContinuationAudit:safeSavedContinuationAudit(saved.savedContinuationAudit),
          diagnosticCheckedAt:typeof saved.diagnosticCheckedAt==='string'&&Number.isFinite(Date.parse(saved.diagnosticCheckedAt))?saved.diagnosticCheckedAt:null,
          savedAuditCheckedAt:typeof saved.savedAuditCheckedAt==='string'&&Number.isFinite(Date.parse(saved.savedAuditCheckedAt))?saved.savedAuditCheckedAt:null,
          applyLockMode:['unknown','started'].includes(saved.applyLockMode)?saved.applyLockMode:
            saved.started===true?'started':saved.applyLocked===true||saved.level==='stop'&&saved.started===null?'unknown':null};
      applyLockMode=state.applyLockMode;render();
      if(requestIdInput&&state.diagnosticRequestId)requestIdInput.value=state.diagnosticRequestId;
      if(state.diagnosticRequestId||state.requestId)void refreshDiagnostic();
    }
  }catch{}
  render();
  if(openDetails)openDetails.addEventListener('click',()=>{
    if(detailsDialog?.showModal)detailsDialog.showModal();else if(detailsDialog)detailsDialog.open=true;
  });
  if(refresh)refresh.addEventListener('click',()=>void refreshDiagnostic(null,true));
  if(clearReadOnly)clearReadOnly.addEventListener('click',clearReadOnlyState);
  if(checkButton)checkButton.addEventListener('click',()=>void refreshDiagnostic(requestIdInput?.value||'',true));
  if(copyButton)copyButton.addEventListener('click',()=>copyDiagnostic());
  if(savedAuditButton)savedAuditButton.addEventListener('click',()=>void auditSavedContinuation());
  if(savedAuditCopy)savedAuditCopy.addEventListener('click',()=>void copySavedAudit());
  root.request=async function(url,options={}){
    const method=String(options.method||'GET').toUpperCase();
    const isPreview=method==='POST'&&String(url).includes('/admin/google-writer/append-continuation-preview');
    const isOrdinaryPreview=method==='POST'&&String(url).endsWith('/google-writer/preview');
    const isApply=method==='POST'&&String(url).endsWith('/google-writer/apply');
    let applyPayload=null;
    if(isApply){try{applyPayload=JSON.parse(options.body||'{}');}catch{}}
    if(isApply&&(applyLockMode==='unknown'||applyLockMode==='started'&&continuation)){
      throw Object.assign(new Error('Повторний Apply заблоковано до read-only перевірки стану.'),
        {blockedLocally:true,code:'APPLY_READ_ONLY_CHECK_REQUIRED'});
    }
    const matchingApply=Boolean(isApply&&continuation&&applyPayload?.ticket===continuation.ticket&&
      applyPayload?.confirmed===true);
    if(matchingApply){
      applyRequestInFlight=true;applyLockMode='unknown';
      state={version:1,requestId:continuation.requestId,httpStatus:null,code:'APPLY_REQUEST_PENDING',
        level:'stop',started:null,description:descriptionFor('APPLY_REQUEST_PENDING'),diagnostic:null,
        diagnosticCheckedAt:null,savedAuditCheckedAt:state.savedAuditCheckedAt,
        savedContinuationAudit:state.savedContinuationAudit,applyLockMode:'unknown'};
      save();render();
    }
    try{
      const result=await originalRequest(url,options);
      if(matchingApply)applyRequestInFlight=false;
      if(isPreview&&result?.status==='PREVIEW_READY'&&REQUEST_ID_RE.test(result.request_id||'')&&typeof result.ticket==='string'){
        continuation={requestId:result.request_id,ticket:result.ticket};
        if(state.level==='none'){
          state.diagnosticRequestId=result.request_id;
          if(requestIdInput&&!requestIdInput.value)requestIdInput.value=result.request_id;
          save();
        }
      }
      if(isOrdinaryPreview&&result?.status==='PREVIEW')continuation=null;
      if(matchingApply){
        if(result?.started===true&&result.request_id===continuation.requestId)
          setResult({requestId:continuation.requestId,httpStatus:202,code:'APPLY_STARTED',level:'success',started:true});
        else if(result?.started===false)
          setResult({requestId:continuation.requestId,httpStatus:200,code:safeCode(result.code||result.status),level:'blocked',started:false});
        else setResult({requestId:continuation.requestId,httpStatus:200,code:'APPLY_OUTCOME_UNCONFIRMED',level:'stop'});
      }
      return result;
    }catch(error){
      if(error?.blockedLocally)throw error;
      if(matchingApply){
        applyRequestInFlight=false;
        const code=safeCode(error?.code||error?.status||'APPLY_OUTCOME_UNCONFIRMED');
        setResult({requestId:continuation.requestId,httpStatus:Number.isInteger(error?.httpStatus)?error.httpStatus:null,
          code,level:error?.started===false?'blocked':'stop',started:error?.started===false?false:null});
      }
      throw error;
    }
  };
  root.PqmGoogleWriterApplyResult={refreshDiagnostic,clearReadOnlyState,render,diagnosticText,auditSavedContinuation,savedAuditText,
    canApplyContinuation:requestId=>applyLockMode===null&&!applyRequestInFlight};
})(globalThis);
