/* Existing protocol-number cell is the entry point; no parallel requisites editor. */
function formedSnapshotTable(items){return `<div class="formed-protocol-items"><table><thead><tr><th>Заявка</th><th>Постачальник</th><th>ЄДРПОУ / РНОКПП</th><th>Відбір</th><th>Рішення УО</th></tr></thead><tbody>${items.map(x=>`<tr><td>${esc(x.id)}</td><td>${esc(x.supplier_name)}</td><td>${esc(x.supplier_code)}</td><td>${esc(x.pretty_id)}</td><td>${x.protocol_decision==='admit'?'Допустити':x.protocol_decision==='reject'?'Відхилити':'—'}</td></tr>`).join('')}</tbody></table></div>`}
function formedHistoryEntry(x){return `<details data-history-protocol="${esc(x.id)}"><summary>№${esc(x.protocol_number)} · ${esc(x.officer)} · ${x.count_all} заявок · <strong>${x.status==='active'?'Чинний':x.status==='superseded'?'Замінено':'Скасовано'}</strong></summary><p>Сформовано: ${esc(displayDate(x.created_at))} · ${esc(x.created_by)}</p>${x.cancelled_at?`<p>Скасовано: ${esc(displayDate(x.cancelled_at))} · ${esc(x.cancelled_by)} · ${esc(x.reason)}</p>`:''}${formedSnapshotTable(x.items)}${x.download_url?`<a href="${esc(x.download_url)}" download>Завантажити DOCX цього формування</a>`:'<p class="muted">Файл DOCX недоступний</p>'}</details>`}
async function openFormedProtocol(id){
  try{
    const data=await request(`${API}/protocol/formed/${encodeURIComponent(id)}`);
    let dialog=document.getElementById('formedProtocolDialog');
    if(!dialog){dialog=document.createElement('dialog');dialog.id='formedProtocolDialog';dialog.className='formed-protocol-dialog';document.body.append(dialog)}
    dialog.innerHTML=`<header><h2>Протокол № ${esc(data.protocol_number)}</h2><button type="button" data-close-protocol aria-label="Закрити">×</button></header>
      <p>${esc(data.protocol_date)} · ${esc(data.officer)} · <strong>${data.status==='active'?'Чинний':'Скасовано'}</strong></p>
      <p>Сформовано: ${esc(displayDate(data.created_at))} · ${esc(data.created_by)}</p>
      <p>Усього: ${data.count_all} · Допущено: ${data.count_admitted} · Відхилено: ${data.count_rejected}</p>
      <div class="formed-protocol-items"><table><thead><tr><th>Заявка</th><th>Постачальник</th><th>ЄДРПОУ / РНОКПП</th><th>Відбір</th><th>Рішення УО</th></tr></thead><tbody>${data.items.map(x=>`<tr><td>${esc(x.id)}</td><td>${esc(x.supplier_name)}</td><td>${esc(x.supplier_code)}</td><td>${esc(x.pretty_id)}</td><td>${x.protocol_decision==='admit'?'Допустити':'Відхилити'}</td></tr>`).join('')}</tbody></table></div>
      <details class="formed-history"><summary>Історія формувань · ${data.history.length}</summary><p class="muted">Пов’язані формування за збереженим складом заявок. Старі позначки без snapshot не реконструюються.</p>${data.history.map(formedHistoryEntry).join('')}</details>
      <footer>${data.download_url?`<a class="primary" href="${esc(data.download_url)}" download>Завантажити актуальний DOCX</a>`:''}<button type="button" data-cancel-protocol ${data.status!=='active'||role()==='viewer'?'disabled':''}>Скасувати формування</button><button type="button" data-close-protocol>Закрити</button></footer>`;
    dialog.querySelectorAll('[data-close-protocol]').forEach(x=>x.onclick=()=>dialog.close());
    dialog.querySelector('[data-cancel-protocol]').onclick=async e=>{
      const reason=prompt('Причина скасування формування (реквізити, рішення та зауваження заявок залишаться):');
      if(!reason?.trim()||!confirm(`Скасувати формування протоколу № ${data.protocol_number} для ${data.count_all} заявок?`))return;
      e.target.disabled=true;
      try{await request(`${API}/protocol/formed/${encodeURIComponent(id)}/cancel`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirmed:true,reason})});dialog.close();await loadRows();toast('Формування скасовано. Реквізити заявок збережено.')}
      catch(error){toast(error.message);e.target.disabled=false}
    };
    if(!dialog.open)dialog.showModal();
  }catch(error){toast(error.message)}
}

document.addEventListener('click',async e=>{
  const formed=e.target.closest('[data-formed-protocol]'),legacy=e.target.closest('[data-release-legacy]');
  if(!formed&&!legacy)return;
  e.preventDefault();e.stopPropagation();
  if(formed){await openFormedProtocol(formed.dataset.formedProtocol);return}
  const reason=prompt('Причина скасування старої generated-позначки. Склад старого протоколу невідомий; зміниться лише ця заявка:');
  if(!reason?.trim()||!confirm('Скасувати legacy-позначку лише цієї заявки? №, дата, УО, рішення та зауваження залишаться.'))return;
  legacy.disabled=true;
  try{await request(`${API}/protocol/legacy/${encodeURIComponent(legacy.dataset.releaseLegacy)}/cancel`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirmed:true,reason})});await loadRows();toast('Legacy-позначку скасовано. Дані заявки збережено.')}
  catch(error){toast(error.message);legacy.disabled=false}
},true);
