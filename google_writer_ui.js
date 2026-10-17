/* Separate fourth-job controls; no credentials, Google API calls or legacy scheduler edits. */
let googleWriterJobState=null,googleWriterSchedulePreview=null,googleWriterBusy=false;
async function loadGoogleWriterJob(){
  try{
    const data=await request(`${API}/google-writer/status`);
    googleWriterJobState=data;
    const run=document.getElementById('pqmGoogleWriterRun');
    if(run){run.disabled=googleWriterBusy||!data.can_execute||!data.channel_ready||data.blocked;
      run.title=!data.can_execute?'Недостатньо прав':!data.channel_ready?'Execution API канал ще не підготовлено':data.blocked?'Активний запуск або невизначений результат; потрібна перевірка':'';}
    const message=document.getElementById('pqmGoogleWriterMessage');
    if(message)message.textContent=data.blocked?'Запуск або результат потребує перевірки':data.channel_ready?'Доступний ручний Preview → Apply':'Execution API ще не підготовлено';
    const root=document.getElementById('schedulerJobs');if(!root)return data;
    let card=document.getElementById('googleWriterJobCard');
    if(!card){card=document.createElement('article');card.id='googleWriterJobCard';card.className='scheduler-job';root.append(card);}
    card.innerHTML=`<header><strong>PQM → Google Sheets</strong><span>${data.configured_enabled?'Розклад увімкнено':'Розклад вимкнено'}</span></header>
      <dl><div><dt>Розклад</dt><dd>${esc(data.schedule)} · Europe/Kyiv</dd></div><div><dt>Останній результат</dt><dd>${esc(data.last_status)} · ${esc(data.last_finished_at?displayDate(data.last_finished_at):'—')}</dd></div><div><dt>Наступний запуск</dt><dd>${esc(data.next_run?displayDate(data.next_run):'—')}</dd></div></dl>
      <p class="muted">${data.channel_ready?'':'Захищений канал ще не підготовлено. '}${data.blocked?'Активний запуск / outcome unknown — новий Apply заблоковано.':''}</p>
      ${data.can_manage?`<label><input id="googleWriterEnabled" type="checkbox" ${data.configured_enabled?'checked':''} ${!data.channel_ready&&!data.configured_enabled?'disabled':''}> Увімкнено</label>
      <label>Година <input id="googleWriterHour" type="number" min="0" max="23" value="${data.hour}"></label>
      <label>Хвилина <input id="googleWriterMinute" type="number" min="0" max="59" value="${data.minute}"></label>
      <footer><button id="googleWriterSchedulePreview" class="ghost" type="button">Переглянути розклад</button><button id="googleWriterScheduleApply" class="ghost" type="button" disabled>Застосувати розклад</button></footer><p id="googleWriterScheduleResult" class="muted"></p>`:''}
      <details><summary>Журнал запусків</summary><ul>${data.runs.map(row=>`<li>${esc(displayDate(row.started_at))} · ${esc(row.trigger)} · ${esc(row.status)} · ${esc(JSON.stringify(row.result?.counts||{}))}</li>`).join('')||'<li>Запусків ще не було</li>'}</ul></details>`;
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
async function manualGoogleWriter(){
  if(googleWriterBusy||!googleWriterJobState?.can_execute||!googleWriterJobState?.channel_ready||googleWriterJobState.blocked)return;
  googleWriterBusy=true;document.getElementById('pqmGoogleWriterRun').disabled=true;
  try{
    const request_id=crypto.randomUUID().replaceAll('-','');
    const preview=await request(`${API}/google-writer/preview`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request_id})});
    if(!confirm(`PQM → Google Sheets: додати ${preview.counts.append||0}, оновити ${preview.counts.update||0}, конфліктів ${preview.counts.conflict||0}. Застосувати цей Preview?`))return;
    await request(`${API}/google-writer/apply`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ticket:preview.ticket,confirmed:true})});
    toast('Запуск прийнято. Перевірте журнал; частковий результат не означає повний PASS.','success');
  }catch(error){toast(error.message,'error');}
  finally{googleWriterBusy=false;await loadGoogleWriterJob();}
}
const googleWriterRunButton=document.getElementById('pqmGoogleWriterRun');
if(googleWriterRunButton)googleWriterRunButton.onclick=manualGoogleWriter;
loadGoogleWriterJob();
