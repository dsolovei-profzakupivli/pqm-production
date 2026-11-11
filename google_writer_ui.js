/* Separate fourth-job controls; no credentials, Google API calls or legacy scheduler edits. */
let googleWriterJobState=null,googleWriterSchedulePreview=null,googleWriterBusy=false,googleWriterProgressTimer=null;
function googleWriterProgressLabel(run){
  const progress=run?.progress||{},state=progress.state||run?.status;
  if(run?.status==='closed_unknown')return 'Адміністративно закрито · результат запису невідомий';
  if(run?.status==='outcome_unknown')return 'Невизначений результат · запис заблоковано';
  if(run?.status==='complete')return 'Завершено';
  if(run?.status==='partial')return 'Часткове завершення';
  if(state==='preparing')return 'Підготовка порції';
  if(state==='remote_in_flight')return 'Запит Apps Script триває · запис і read-back ще не підтверджені';
  if(state==='verified')return 'Останню порцію підтверджено';
  if(run?.status==='running')return 'Запуск активний · підтвердженого прогресу ще немає';
  return state||'—';
}
function googleWriterProgressHtml(run){
  if(!run)return '<p class="muted">Немає активного виконання.</p>';
  const p=run.progress||{},planned=p.planned||{},confirmed=p.confirmed||{},remaining=p.remaining||{},error=p.safe_error,recovered=p.last_recovered_error;
  const stage=error?`<p class="google-writer-error">Помилка: ${esc(error.stage||'невідомий етап')} · ${esc(error.category||'невідома категорія')}${error.http_status?` · HTTP ${Number(error.http_status)}`:''} (${esc(error.exception_type||'Other')})</p>`:'';
  const recovery=recovered?`<p class="muted">Порцію відновлено після ${esc(recovered.stage||'невідомого етапу')} · ${esc(recovered.category||'невідомої категорії')}${recovered.http_status?` · HTTP ${Number(recovered.http_status)}`:''} (${esc(recovered.exception_type||'Other')})</p>`:'';
  const last=p.last_confirmed_progress_at?displayDate(p.last_confirmed_progress_at):'ще не було';
  const chunk=p.current_chunk===null||p.current_chunk===undefined?'—':String(Number(p.current_chunk)+1);
  return `<strong>${esc(googleWriterProgressLabel(run))}</strong><dl class="google-writer-progress-metrics">
    <div><dt>Поточна фаза</dt><dd>${esc(p.phase||'—')}</dd></div><div><dt>Порція</dt><dd>${esc(chunk)}</dd></div>
    <div><dt>APPEND: план / підтверджено / залишок</dt><dd>${Number(planned.append||0)} / ${Number(confirmed.append||0)} / ${Number(remaining.append||0)}</dd></div>
    <div><dt>UPDATE: план / підтверджено / залишок</dt><dd>${Number(planned.update||0)} / ${Number(confirmed.update||0)} / ${Number(remaining.update||0)}</dd></div>
    <div><dt>Останній підтверджений прогрес</dt><dd>${esc(last)}</dd></div></dl>${stage}${recovery}`;
}
function startGoogleWriterProgressPolling(requestId){
  if(googleWriterProgressTimer)clearInterval(googleWriterProgressTimer);
  let ticks=0,polling=false;
  googleWriterProgressTimer=setInterval(async()=>{
    if(polling)return;polling=true;ticks++;
    let data=null;try{data=await loadGoogleWriterJob();}finally{polling=false;}
    const run=data?.runs?.find(item=>item.request_id===requestId);
    if((run&&run.status!=='running')||ticks>=600){clearInterval(googleWriterProgressTimer);googleWriterProgressTimer=null;}
  },2000);
}
async function loadGoogleWriterJob(){
  try{
    const data=await request(`${API}/google-writer/status`);
    googleWriterJobState=data;
    const run=document.getElementById('pqmGoogleWriterRun');
    if(run){run.disabled=googleWriterBusy||!data.can_execute||!data.channel_ready||data.blocked;
      run.title=!data.can_execute?'Недостатньо прав':!data.channel_ready?'Execution API канал ще не підготовлено':data.resume_available?'Є підтверджений checkpoint: продовжіть його перед новим Apply':data.blocked?'Активний запуск або невизначений результат; потрібна перевірка':'';}
    const message=document.getElementById('pqmGoogleWriterMessage');
    if(message)message.textContent=data.resume_available?'Є зупинений APPEND_ONLY запуск із підтвердженими порціями · його можна безпечно продовжити':data.blocked?'Запуск або результат потребує перевірки':data.channel_ready?(data.automation_blocked?'Автоматику вимкнено · ручний Preview → Apply доступний':'Доступний ручний Preview → Apply'):'Execution API ще не підготовлено';
    const root=document.getElementById('schedulerJobs');if(!root)return data;
    let card=document.getElementById('googleWriterJobCard');
    if(!card){card=document.createElement('article');card.id='googleWriterJobCard';card.className='scheduler-job';root.append(card);}
    const activeRun=data.runs.find(row=>row.status==='running'||row.status==='outcome_unknown')||data.runs[0];
    const heldRuns=data.runs.filter(row=>row.status==='outcome_unknown'||row.status==='closed_unknown'||
      row.status==='failed_safe'&&row.prewrite_close_eligible||row.status==='closed_prewrite');
    const holdHtml=heldRuns.map(row=>{
      const result=row.result||{},progress=row.progress||{},error=progress.safe_error||{};
      const scope=result.plan_scope||'невідомий',chunk=result.attempted_chunk===null||result.attempted_chunk===undefined?'—':String(Number(result.attempted_chunk)+1);
      const diagnosis=error.stage?`${error.stage} · ${error.category||'unknown'} · ${error.exception_type||'Other'}`:'Діагностику не збережено';
      const closed=row.status==='closed_unknown';
      const prewrite=row.status==='failed_safe'||row.status==='closed_prewrite';
      const prewriteClosed=row.status==='closed_prewrite';
      const closeAction=row.status==='outcome_unknown'&&data.can_close?`<button class="ghost google-writer-close" type="button" data-request-id="${esc(row.request_id)}" ${googleWriterBusy?'disabled':''}>${row.close_state==='prepared'?'Повторити закриття з тим самим ID':'Закрити запуск без повторного запису'}</button>`:'';
      const preflightAction=prewrite&&!prewriteClosed&&row.prewrite_close_eligible&&data.can_preflight_close_prewrite?
        `<button class="ghost google-writer-preflight-close" type="button" data-request-id="${esc(row.request_id)}" ${googleWriterBusy?'disabled':''}>Перевірити можливість закриття</button>`:'';
      const prewriteAction=prewrite&&!prewriteClosed&&row.prewrite_close_eligible&&data.can_close_prewrite?
        `<button class="ghost google-writer-close-prewrite" type="button" data-request-id="${esc(row.request_id)}" ${googleWriterBusy?'disabled':''}>${row.prewrite_close_state==='prepared'?'Повторити перевірку з тим самим ID':'Перевірити й закрити підтверджений збій до запису'}</button>`:'';
      const closeNote=closed?`<p class="muted">Адміністративно закрито ${esc(row.closed_at?displayDate(row.closed_at):'')} · результат запису невідомий${row.close_reason?` · причина: ${esc(row.close_reason)}`:''}</p>`:
        row.close_state==='prepared'?'<p class="google-writer-error">Закриття очікує підтвердження Apps Script; HOLD збережено. Повторюйте лише з тим самим close ID.</p>':
        prewriteClosed?`<p class="muted">Адміністративно закрито як підтверджений збій до запису · ${esc(row.prewrite_closed_at?displayDate(row.prewrite_closed_at):'')} · запис у Google Sheets не виконувався${row.prewrite_close_reason?` · причина: ${esc(row.prewrite_close_reason)}`:''}</p>`:
        row.prewrite_close_state==='prepared'?'<p class="google-writer-error">Перевірку очікує Apps Script; блокування збережено. Повторюйте лише з тим самим close ID.</p>':'';
      return `<article class="google-writer-hold"><strong>${closed?'Адміністративно закритий запуск':prewriteClosed?'Закритий prewrite-збій':'Заблокований запуск'}</strong><dl><div><dt>Request ID</dt><dd>${esc(row.request_id)}</dd></div><div><dt>Статус</dt><dd>${esc(row.status)}</dd></div><div><dt>Scope</dt><dd>${esc(scope)}</dd></div><div><dt>Порція</dt><dd>${esc(chunk)}</dd></div><div><dt>Діагностика</dt><dd>${esc(diagnosis)}</dd></div></dl>${closeNote}${closeAction}${preflightAction}${prewriteAction}</article>`;
    }).join('');
    card.innerHTML=`<header><strong>PQM → Google Sheets</strong><span>${data.automation_blocked?(data.configured_enabled?'Розклад збережено · заблоковано':'Розклад вимкнено'):data.configured_enabled?'Розклад увімкнено':'Розклад вимкнено'}</span></header>
      <dl><div><dt>Розклад</dt><dd>${esc(data.schedule)} · Europe/Kyiv</dd></div><div><dt>Останній результат</dt><dd>${esc(data.last_status)} · ${esc(data.last_finished_at?displayDate(data.last_finished_at):'—')}</dd></div><div><dt>Наступний запуск</dt><dd>${esc(data.next_run?displayDate(data.next_run):'—')}</dd></div></dl>
      <section class="google-writer-progress" aria-live="polite">${googleWriterProgressHtml(activeRun)}</section>
      ${holdHtml?`<section class="google-writer-holds"><h4>Стан запусків із невизначеним результатом</h4>${holdHtml}</section>`:''}
      <p class="muted">${data.channel_ready?'':'Захищений канал ще не підготовлено. '}${data.automation_blocked?'Глобальна автоматика заблокована; ручний запуск не змінює розклад. ':''}${data.blocked?'Активний запуск / outcome unknown — новий Apply заблоковано.':''}</p>
      ${data.can_manage?`<label><input id="googleWriterEnabled" type="checkbox" ${data.configured_enabled?'checked':''} ${!data.channel_ready||(data.automation_blocked&&!data.configured_enabled)?'disabled':''}> Автоматичний розклад</label>
      <label>Година <input id="googleWriterHour" type="number" min="0" max="23" value="${data.hour}" ${data.automation_blocked?'disabled':''}></label>
      <label>Хвилина <input id="googleWriterMinute" type="number" min="0" max="59" value="${data.minute}" ${data.automation_blocked?'disabled':''}></label>
      <footer><button id="googleWriterSchedulePreview" class="ghost" type="button" ${!data.channel_ready||(data.automation_blocked&&!data.configured_enabled)?'disabled':''}>Переглянути розклад</button><button id="googleWriterScheduleApply" class="ghost" type="button" disabled>Застосувати розклад</button></footer><p id="googleWriterScheduleResult" class="muted"></p>`:''}
      <details><summary>Журнал запусків</summary><ul>${data.runs.map(row=>`<li>${esc(displayDate(row.started_at))} · ${esc(row.trigger)} · ${esc(row.actor||'')} · ${esc(row.status)} · ${esc(JSON.stringify(row.result?.counts||{}))}${row.resume_available&&data.can_execute&&data.channel_ready?` <button class="ghost google-writer-resume" type="button" data-request-id="${esc(row.request_id)}" ${googleWriterBusy?'disabled':''}>Продовжити підтверджений APPEND_ONLY checkpoint</button>`:''}</li>`).join('')||'<li>Запусків ще не було</li>'}</ul></details>`;
    card.querySelectorAll('.google-writer-resume').forEach(button=>button.onclick=()=>resumeGoogleWriterAppendOnly(button.dataset.requestId));
    card.querySelectorAll('.google-writer-close').forEach(button=>button.onclick=()=>closeGoogleWriterUnknownRun(button.dataset.requestId));
    card.querySelectorAll('.google-writer-preflight-close').forEach(button=>button.onclick=()=>preflightGoogleWriterPrewriteClose(button.dataset.requestId));
    card.querySelectorAll('.google-writer-close-prewrite').forEach(button=>button.onclick=()=>closeGoogleWriterPrewriteFailure(button.dataset.requestId));
    googleWriterSchedulePreview=null;
    if(data.can_manage){
      for(const id of ['googleWriterEnabled','googleWriterHour','googleWriterMinute'])document.getElementById(id).oninput=()=>{googleWriterSchedulePreview=null;document.getElementById('googleWriterScheduleApply').disabled=true;};
      document.getElementById('googleWriterSchedulePreview').onclick=previewGoogleWriterSchedule;
      document.getElementById('googleWriterScheduleApply').onclick=applyGoogleWriterSchedule;
    }
    return data;
  }catch(error){
    const run=document.getElementById('pqmGoogleWriterRun');if(run)run.disabled=true;
    const message=document.getElementById('pqmGoogleWriterMessage');if(message)message.textContent='Статус Execution API недоступний; запуск заблоковано';
    return null;
  }
}
async function preflightGoogleWriterPrewriteClose(requestId){
  if(googleWriterBusy||!googleWriterJobState?.can_preflight_close_prewrite)return;
  const run=googleWriterJobState.runs.find(item=>item.request_id===requestId&&
    item.status==='failed_safe'&&item.prewrite_close_eligible);
  if(!run)return;
  googleWriterBusy=true;
  try{
    const result=await request(`${API}/admin/google-writer/prewrite-close-preflight`,{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({request_id:requestId})});
    if(result.read_only!==true||result.sqlite_writes!==0||result.sheets_writes!==0||result.properties_writes!==0||
       !['READY','BLOCKED'].includes(result.status))
      throw new Error('Read-only результат не підтверджений; блокування збережено');
    if(result.status==='READY'&&(!result.request_id_matches||result.plan_binding!=='PASS'||
       result.chunk_binding!=='PASS'||result.manifest_binding!=='PASS'||result.target_code_matches!==0||
       result.run_marker_matches!==0))
      throw new Error('Доказові bindings неповні; блокування збережено');
    const labels={LOCAL_EVIDENCE_UNAVAILABLE:'локальні SQLite-докази недоступні',
      CLOSE_ALREADY_EXISTS:'для запуску вже є intent закриття',APPS_SCRIPT_TOMBSTONE_EXISTS:'Apps Script уже має tombstone',
      LEGACY_CLOSE_EXISTS:'існує попередній close marker',UNCERTAINTY_MARKER_MISMATCH:'uncertainty marker не збігається',
      RUN_RECORD_INVALID:'Apps Script run record відсутній або некоректний',RUN_NOT_UNTOUCHED:'run record не доводить стан до запису',
      PREWRITE_STAGE_UNVERIFIED:'prewrite stage не підтверджено',MANIFEST_NOT_OVERSIZED:'manifest не перевищує межу checkpoint',
      SHEET_BOUNDS_UNAVAILABLE:'межі аркушів не підтверджені',SHEET_READ_INCOMPLETE:'читання аркушів неповне',
      TARGET_CODES_PRESENT:'знайдено цільові коди',RUN_MARKER_PRESENT:'знайдено маркер запуску',
      APPS_SCRIPT_CHECK_UNAVAILABLE:'Apps Script read-only перевірка недоступна',
      APPS_SCRIPT_EVIDENCE_REJECTED:'Apps Script не підтвердив доказ',LOCAL_OR_REMOTE_EVIDENCE_UNAVAILABLE:'докази недоступні',
      SANDBOX_ONLY:'доступно лише в Sandbox',PERMISSION_REQUIRED:'бракує адміністративних прав'};
    if(result.status==='READY'){
      toast(`READY · write-ahead ${Number(result.write_ahead_bytes).toLocaleString('uk-UA')} / ${Number(result.checkpoint_max_bytes).toLocaleString('uk-UA')} байт · цільових кодів ${result.target_code_matches} · маркерів ${result.run_marker_matches}. Це лише перевірка; під час закриття все буде перевірено повторно.`, 'success');
    }else{
      const reasons=(result.reason_codes||[]).map(code=>labels[code]||'доказ не підтверджено');
      toast(`BLOCKED · ${reasons.join('; ')||'доказів недостатньо'}. HOLD збережено.`, 'error');
    }
  }catch(error){toast(`BLOCKED · read-only перевірка не завершена: ${error.message}. HOLD збережено.`, 'error');}
  finally{googleWriterBusy=false;}
}
async function closeGoogleWriterUnknownRun(requestId){
  if(googleWriterBusy||!googleWriterJobState?.can_close)return;
  const run=googleWriterJobState.runs.find(item=>item.request_id===requestId&&item.status==='outcome_unknown');
  if(!run)return;
  const existing=run.close_state==='prepared';
  const reason=window.prompt('Причина адміністративного закриття (результат запису залишиться невідомим):',existing?(run.close_reason||''):'');
  if(typeof reason!=='string'||reason.trim().length<8||reason.trim().length>500)return;
  if(!window.confirm(`Закрити ${requestId} без повторного запису? Це НЕ підтверджує успішність Apply. Google Sheets не змінюватиметься.`))return;
  googleWriterBusy=true;
  try{
    const closeId=existing?run.close_id:crypto.randomUUID().replaceAll('-','');
    const result=await request(`${API}/admin/google-writer/close-unknown`,{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({close_id:closeId,request_id:requestId,reason:reason.trim(),confirmed:true})});
    if(result.status!=='ADMIN_CLOSED_UNKNOWN'||result.disposition!=='OUTCOME_UNKNOWN_NOT_CONFIRMED'||result.resume_authorized!==false)
      throw new Error('Закриття не має підтвердженого адміністративного результату; HOLD зберігається');
    toast('Адміністративно закрито. Результат запису невідомий.','success');
  }catch(error){toast(error.message,'error');}
  finally{googleWriterBusy=false;await loadGoogleWriterJob();}
}
async function closeGoogleWriterPrewriteFailure(requestId){
  if(googleWriterBusy||!googleWriterJobState?.can_close_prewrite)return;
  const run=googleWriterJobState.runs.find(item=>item.request_id===requestId&&
    item.status==='failed_safe'&&item.prewrite_close_eligible);
  if(!run)return;
  const existing=run.prewrite_close_state==='prepared';
  const reason=window.prompt('Причина закриття підтвердженого збою до запису (сервер перевірить відсутність цільових рядків і маркера):',
    existing?(run.prewrite_close_reason||''):'');
  if(typeof reason!=='string'||reason.trim().length<8||reason.trim().length>500)return;
  if(!window.confirm(`Перевірити та закрити ${requestId} як підтверджений збій до запису? Буде виконано лише read-only звірку Google Sheets; якщо доказів недостатньо, HOLD залишиться. Записів у Sheets не буде.`))return;
  googleWriterBusy=true;
  try{
    const closeId=existing?run.prewrite_close_id:crypto.randomUUID().replaceAll('-','');
    const result=await request(`${API}/admin/google-writer/close-prewrite`,{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({close_id:closeId,request_id:requestId,reason:reason.trim(),confirmed:true})});
    if(result.status!=='ADMIN_CLOSED_PREWRITE_NO_WRITE'||
       result.disposition!=='PREWRITE_FAILURE_CONFIRMED_NO_SHEET_WRITE'||
       result.resume_authorized!==false||result.sheets_write_performed!==false)
      throw new Error('Підтверджене закриття не отримано; запуск залишається заблокованим');
    toast('Підтверджений збій до запису закрито. Google Sheets не змінювалася.','success');
  }catch(error){toast(error.message,'error');}
  finally{googleWriterBusy=false;await loadGoogleWriterJob();}
}
function googleWriterSpecification(){return{enabled:document.getElementById('googleWriterEnabled').checked,
  hour:Number(document.getElementById('googleWriterHour').value),minute:Number(document.getElementById('googleWriterMinute').value)};}
async function previewGoogleWriterSchedule(){
  try{
    const specification=googleWriterSpecification(),revision=googleWriterJobState.revision;
    const result=await request(`${API}/admin/google-writer/schedule/preview`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({specification})});
    if(JSON.stringify(specification)!==JSON.stringify(googleWriterSpecification())||revision!==googleWriterJobState.revision)return;
    googleWriterSchedulePreview={specification,expected_revision:revision};
    document.getElementById('googleWriterScheduleResult').textContent=`Наступний слот: ${displayDate(result.next_run)}. Apply не запускає синхронізацію.`;
    document.getElementById('googleWriterScheduleApply').disabled=false;
  }catch(error){googleWriterSchedulePreview=null;toast(error.message,'error');}
}
async function applyGoogleWriterSchedule(){
  if(!googleWriterSchedulePreview||JSON.stringify(googleWriterSchedulePreview.specification)!==JSON.stringify(googleWriterSpecification()))return;
  document.getElementById('googleWriterScheduleApply').disabled=true;
  try{
    await request(`${API}/admin/google-writer/schedule/apply`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(googleWriterSchedulePreview)});
    googleWriterSchedulePreview=null;await loadGoogleWriterJob();toast('Збережено лише розклад; sync не запускався','success');
  }catch(error){googleWriterSchedulePreview=null;toast(error.message,'error');}
}
function googleWriterPreviewHasFormula(value){return typeof value==='string'&&/^\s*=/.test(value);}
function googleWriterPreviewValueHtml(value){return esc(value===null||value===undefined||value===''?'—':String(value));}
function googleWriterPreviewCellValueHtml(value){
  if(googleWriterPreviewHasFormula(value))return esc('Формула');
  return googleWriterPreviewValueHtml(value);
}
function renderGoogleWriterPreviewDetails(details){
  const root=document.getElementById('googleWriterPreviewDetails');
  if(!root)return;
  if(!details){root.innerHTML='<p class="preview-empty">Деталі плану недоступні в цьому середовищі.</p>';return;}
  const cellList=cells=>(cells||[]).map(cell=>{
    const formulaText=googleWriterPreviewHasFormula(cell.old_value)||googleWriterPreviewHasFormula(cell.new_value);
    const formulaHint=cell.formula&&!formulaText?' <small>Формула</small>':'';
    return `<div><strong>${esc(cell.column)}</strong>: <span class="preview-old">${googleWriterPreviewCellValueHtml(cell.old_value)}</span> → <span class="preview-new">${googleWriterPreviewCellValueHtml(cell.new_value)}</span>${formulaHint}</div>`;
  }).join('');
  const rows=(items,operation)=>items.map(item=>`<tr><td>${esc(operation)}</td><td>${esc(item.tab||'—')}</td><td><strong>${googleWriterPreviewValueHtml(item.name)}</strong><br><small>${esc(item.code||'')}</small></td><td class="change-values">${cellList(item.cells)}</td><td>—</td></tr>`).join('');
  const conflicts=(details.conflicts||[]).map(item=>`<tr><td>CONFLICT</td><td>${esc(item.tab||'—')}</td><td><strong>${googleWriterPreviewValueHtml(item.name)}</strong><br><small>${esc(item.code||'')}</small></td><td>—</td><td class="preview-conflict">${esc(item.explanation||item.reason||'Причину не визначено')}</td></tr>`).join('');
  const errors=(details.errors||[]).map(item=>`<tr><td>ERROR</td><td>${esc(item.tab||'—')}</td><td><strong>${googleWriterPreviewValueHtml(item.name)}</strong><br><small>${esc(item.code||'')}</small></td><td>—</td><td class="preview-conflict">${esc(item.explanation||item.reason||'Помилка плану')}</td></tr>`).join('');
  const content=rows(details.appends||[],'APPEND')+rows(details.updates||[],'UPDATE')+conflicts+errors;
  root.innerHTML=content?`<table><thead><tr><th>Дія</th><th>Вкладка</th><th>Постачальник</th><th>Стовпці: старе → нове</th><th>Причина</th></tr></thead><tbody>${content}</tbody></table>`:'<p class="preview-empty">У плані немає змін або конфліктів.</p>';
}
function confirmGoogleWriterPreview(preview,details,options={}){
  const dialog=document.getElementById('googleWriterPreviewDialog');
  const applyButton=document.getElementById('googleWriterPreviewApply');
  const appendButton=document.getElementById('googleWriterPreviewAppendOnly');
  if(!dialog||dialog.open)return Promise.resolve(false);
  const counts=preview?.counts||{};
  document.getElementById('googleWriterPreviewAppend').textContent=Number(counts.append||0).toLocaleString('uk-UA');
  document.getElementById('googleWriterPreviewUpdate').textContent=Number(counts.update||0).toLocaleString('uk-UA');
  document.getElementById('googleWriterPreviewConflict').textContent=Number(counts.conflict||0).toLocaleString('uk-UA');
  const notice=document.getElementById('googleWriterPreviewNotice');
  if(notice){notice.textContent=options.notice||'';notice.hidden=!options.notice;}
  const detailed=!!preview?.plan_digest;
  appendButton.hidden=!!options.resume||!detailed||Number(counts.append||0)===0;
  applyButton.textContent=options.resume?'Продовжити порції':detailed?'Застосувати всі зміни':'Застосувати зміни';
  renderGoogleWriterPreviewDetails(details);
  applyButton.disabled=false;appendButton.disabled=false;
  return new Promise(resolve=>{
    let applyRequested=false,settled=false;
    const finish=value=>{if(settled)return;settled=true;resolve(value)};
    const onApply=scope=>{
      if(applyRequested||settled)return;
      applyRequested=true;applyButton.disabled=true;appendButton.disabled=true;dialog.close(scope);
    };
    const onFull=()=>onApply('apply_all');
    const onAppendOnly=()=>onApply('append_only');
    const onClose=()=>finish(applyRequested&&['apply_all','append_only'].includes(dialog.returnValue)?
      {scope:dialog.returnValue==='append_only'?'APPEND_ONLY':'ALL'}:false);
    const onBackdrop=event=>{if(event.target===dialog&&dialog.open)dialog.close('cancel')};
    applyButton.addEventListener('click',onFull);
    appendButton.addEventListener('click',onAppendOnly);
    dialog.addEventListener('close',onClose,{once:true});
    dialog.addEventListener('click',onBackdrop);
    try{dialog.showModal()}catch(error){
      applyButton.removeEventListener('click',onFull);appendButton.removeEventListener('click',onAppendOnly);
      dialog.removeEventListener('close',onClose);
      dialog.removeEventListener('click',onBackdrop);
      finish(false);throw error;
    }
    dialog.addEventListener('close',()=>{
      applyButton.removeEventListener('click',onFull);appendButton.removeEventListener('click',onAppendOnly);
      dialog.removeEventListener('click',onBackdrop);
    },{once:true});
  });
}
async function manualGoogleWriter(){
  if(googleWriterBusy||!googleWriterJobState?.can_execute||!googleWriterJobState?.channel_ready||googleWriterJobState.blocked)return;
  googleWriterBusy=true;document.getElementById('pqmGoogleWriterRun').disabled=true;
  try{
    const request_id=crypto.randomUUID().replaceAll('-','');
    const preview=await request(`${API}/google-writer/preview`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request_id})});
    let details=null;
    if(preview.plan_digest){
      const saved=await request(`${API}/google-writer/preview-details/${request_id}?plan_digest=${encodeURIComponent(preview.plan_digest)}`);
      details=saved.details;
      if(details?.plan_digest!==preview.plan_digest||details?.counts?.append!==preview.counts?.append||
          details?.counts?.update!==preview.counts?.update||details?.counts?.conflict!==preview.counts?.conflict)
        throw new Error('Деталі не збігаються зі збереженим Preview; Apply заблоковано');
    }
    let activePreview=preview,activeDetails=details,notice='';
    while(true){
      const choice=await confirmGoogleWriterPreview(activePreview,activeDetails,{notice});
      notice='';
      if(!choice)return;
      let ticket=activePreview.ticket,plannedCounts=activePreview.counts||{};
      if(choice.scope==='APPEND_ONLY'){
        try{
          const scoped=await request(`${API}/google-writer/preview-scope`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ticket:activePreview.ticket,scope:'APPEND_ONLY',confirmed:true})});
          if(scoped.scope!=='APPEND_ONLY'||scoped.counts?.update!==0||scoped.counts?.append!==activePreview.counts?.append)
            throw new Error('APPEND_ONLY ticket не відповідає переглянутому плану');
          ticket=scoped.ticket;plannedCounts=scoped.counts||plannedCounts;
        }catch(error){
          toast(`Не вдалося підтвердити режим «Лише додати»: ${error.message}. Apply не надсилався; запис не розпочато.`, 'error');
          return;
        }
      }
      let result;
      try{
        result=await request(`${API}/google-writer/apply`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ticket,confirmed:true})});
      }catch(error){
        if(error.httpStatus===409&&error.status==='PREVIEW_STALE_RECONFIRM'&&error.started===false){
          try{
            if(!/^[0-9a-f]{32}$/.test(error.request_id||'')||!error.ticket||!error.plan_digest||!error.details_digest)
              throw new Error('Сервер не повернув пов’язаний актуальний Preview');
            const saved=await request(`${API}/google-writer/preview-details/${error.request_id}?plan_digest=${encodeURIComponent(error.plan_digest)}`);
            if(saved.details_digest!==error.details_digest||saved.details?.plan_digest!==error.plan_digest||
                saved.details?.counts?.append!==error.counts?.append||saved.details?.counts?.update!==error.counts?.update||
                saved.details?.counts?.conflict!==error.counts?.conflict)
              throw new Error('Деталі нового Preview не збігаються з відповіддю сервера');
            activePreview={request_id:error.request_id,ticket:error.ticket,plan_digest:error.plan_digest,
              details_digest:error.details_digest,counts:error.counts};
            activeDetails=saved.details;
            notice='Попередній план застарів. Запис не розпочато. Перегляньте актуальний Preview і підтвердьте його окремо.';
            continue;
          }catch(refreshError){
            toast(`Попередній Preview застарів; запис не розпочато, але актуальні деталі не вдалося відкрити: ${refreshError.message}.`, 'error');
            return;
          }
        }
        if(error.httpStatus){
          toast(error.message,'error');
          toast(`Apply відхилено (HTTP ${error.httpStatus}): ${error.message}. Цей запит не підтвердив створення запуску; перевірте журнал перед будь-яким новим кроком.`, 'error');
        }else{
          toast(error.message,'error');
          toast(`Не отримано HTTP-підтвердження Apply; результат запиту невідомий. Не повторюйте дію. Перевірте журнал запусків для ${activePreview.request_id||request_id}.`, 'error');
        }
        return;
      }
      if(result.started!==true||!result.request_id){
        toast(`API не підтвердив створення Writer run (${result.status||'відповідь без started=true'}). Перевірте журнал; Apply автоматично не повторюється.`, 'error');
        return;
      }
      const counts=result.counts||plannedCounts;
      const status=result.status||'running';
      startGoogleWriterProgressPolling(result.request_id);
      toast(`Запуск прийнято та створено: ${result.request_id} · статус ${status} · APPEND ${Number(counts.append||0)} · UPDATE ${Number(counts.update||0)} · CONFLICT ${Number(counts.conflict||0)}. Частковий результат не означає повний PASS.`, 'success');
      return;
    }
  }catch(error){toast(error.message,'error');}
  finally{googleWriterBusy=false;await loadGoogleWriterJob();}
}
async function resumeGoogleWriterAppendOnly(requestId){
  if(googleWriterBusy||!googleWriterJobState?.can_execute||!googleWriterJobState?.channel_ready)return;
  googleWriterBusy=true;await loadGoogleWriterJob();
  try{
    const preview=await request(`${API}/google-writer/resume-preview`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request_id:requestId})});
    if(preview.status!=='RESUME_READY'||preview.scope!=='APPEND_ONLY'||preview.counts?.append<=0||preview.counts?.update!==0||
       preview.details?.plan_digest!==preview.plan_digest||preview.details_digest===undefined)
      throw new Error('Checkpoint не пройшов read-only звірку; Apply не запускався');
    const choice=await confirmGoogleWriterPreview({plan_digest:preview.plan_digest,counts:preview.counts},preview.details,{resume:true});
    if(!choice)return;
    await request(`${API}/google-writer/resume-append-only`,{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({ticket:preview.ticket,confirmed:true})});
    toast('Продовження прийнято з останньої підтвердженої порції. Невизначені порції не повторюються.','success');
  }catch(error){toast(error.message,'error');}
  finally{googleWriterBusy=false;await loadGoogleWriterJob();}
}
const googleWriterRunButton=document.getElementById('pqmGoogleWriterRun');
if(googleWriterRunButton)googleWriterRunButton.onclick=manualGoogleWriter;
loadGoogleWriterJob();
