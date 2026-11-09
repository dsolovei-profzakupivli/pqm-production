/* Separate fourth-job controls; no credentials, Google API calls or legacy scheduler edits. */
let googleWriterJobState=null,googleWriterSchedulePreview=null,googleWriterBusy=false,googleWriterProgressTimer=null;
function googleWriterProgressLabel(run){
  const progress=run?.progress||{},state=progress.state||run?.status;
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
    card.innerHTML=`<header><strong>PQM → Google Sheets</strong><span>${data.automation_blocked?(data.configured_enabled?'Розклад збережено · заблоковано':'Розклад вимкнено'):data.configured_enabled?'Розклад увімкнено':'Розклад вимкнено'}</span></header>
      <dl><div><dt>Розклад</dt><dd>${esc(data.schedule)} · Europe/Kyiv</dd></div><div><dt>Останній результат</dt><dd>${esc(data.last_status)} · ${esc(data.last_finished_at?displayDate(data.last_finished_at):'—')}</dd></div><div><dt>Наступний запуск</dt><dd>${esc(data.next_run?displayDate(data.next_run):'—')}</dd></div></dl>
      <section class="google-writer-progress" aria-live="polite">${googleWriterProgressHtml(activeRun)}</section>
      <p class="muted">${data.channel_ready?'':'Захищений канал ще не підготовлено. '}${data.automation_blocked?'Глобальна автоматика заблокована; ручний запуск не змінює розклад. ':''}${data.blocked?'Активний запуск / outcome unknown — новий Apply заблоковано.':''}</p>
      ${data.can_manage?`<label><input id="googleWriterEnabled" type="checkbox" ${data.configured_enabled?'checked':''} ${!data.channel_ready||(data.automation_blocked&&!data.configured_enabled)?'disabled':''}> Автоматичний розклад</label>
      <label>Година <input id="googleWriterHour" type="number" min="0" max="23" value="${data.hour}" ${data.automation_blocked?'disabled':''}></label>
      <label>Хвилина <input id="googleWriterMinute" type="number" min="0" max="59" value="${data.minute}" ${data.automation_blocked?'disabled':''}></label>
      <footer><button id="googleWriterSchedulePreview" class="ghost" type="button" ${!data.channel_ready||(data.automation_blocked&&!data.configured_enabled)?'disabled':''}>Переглянути розклад</button><button id="googleWriterScheduleApply" class="ghost" type="button" disabled>Застосувати розклад</button></footer><p id="googleWriterScheduleResult" class="muted"></p>`:''}
      <details><summary>Журнал запусків</summary><ul>${data.runs.map(row=>`<li>${esc(displayDate(row.started_at))} · ${esc(row.trigger)} · ${esc(row.actor||'')} · ${esc(row.status)} · ${esc(JSON.stringify(row.result?.counts||{}))}${row.resume_available&&data.can_execute&&data.channel_ready?` <button class="ghost google-writer-resume" type="button" data-request-id="${esc(row.request_id)}" ${googleWriterBusy?'disabled':''}>Продовжити підтверджений APPEND_ONLY checkpoint</button>`:''}</li>`).join('')||'<li>Запусків ще не було</li>'}</ul></details>`;
    card.querySelectorAll('.google-writer-resume').forEach(button=>button.onclick=()=>resumeGoogleWriterAppendOnly(button.dataset.requestId));
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
function googleWriterPreviewValueHtml(value){return esc(value===null||value===undefined||value===''?'—':String(value));}
function renderGoogleWriterPreviewDetails(details){
  const root=document.getElementById('googleWriterPreviewDetails');
  if(!root)return;
  if(!details){root.innerHTML='<p class="preview-empty">Деталі плану недоступні в цьому середовищі.</p>';return;}
  const cellList=cells=>(cells||[]).map(cell=>`<div><strong>${esc(cell.column)}</strong>: <span class="preview-old">${googleWriterPreviewValueHtml(cell.old_value)}</span> → <span class="preview-new">${googleWriterPreviewValueHtml(cell.new_value)}</span>${cell.formula?' <small>формула</small>':''}</div>`).join('');
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
  const detailed=!!preview?.plan_digest;
  appendButton.hidden=!!options.resume||!detailed||Number(counts.append||0)===0;
  applyButton.textContent=options.resume?'Продовжити порції':detailed?'Застосувати всі зміни':'Застосувати зміни';
  renderGoogleWriterPreviewDetails(details);
  applyButton.disabled=false;
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
    const choice=await confirmGoogleWriterPreview(preview,details);
    if(!choice)return;
    let ticket=preview.ticket;
    if(choice.scope==='APPEND_ONLY'){
      const scoped=await request(`${API}/google-writer/preview-scope`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ticket:preview.ticket,scope:'APPEND_ONLY',confirmed:true})});
      if(scoped.scope!=='APPEND_ONLY'||scoped.counts?.update!==0||scoped.counts?.append!==preview.counts?.append)
        throw new Error('APPEND_ONLY ticket не відповідає підтвердженому плану; Apply заблоковано');
      ticket=scoped.ticket;
    }
    startGoogleWriterProgressPolling(request_id);
    await request(`${API}/google-writer/apply`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ticket,confirmed:true})});
    toast('Запуск прийнято. Перевірте журнал; частковий результат не означає повний PASS.','success');
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
