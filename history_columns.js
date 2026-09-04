// Uses the existing server profile store; never stores filters or application data.
const historyColumnDefaults=[['supplier','Постачальник',180],['code','Код ЄДРПОУ / РНОКПП',90],['manager','Керівник',110],['date','Дата заявки',72],['cpv','Код ДК',90],['framework','Назва відбору',140],['decision','Рішення',90],['officer','УО протоколу',95],['contract','Реквізити договору',100],['remarks','Зауваження',360],['documents','Заявка / документи',99]].map(([key,label,width],order)=>({key,label,width,order,visible:true}));
let historyColumns=structuredClone(historyColumnDefaults),historySettingsPromise=null,historySettingsAvailable=false;
async function ensureHistoryColumns(){
  if(!historySettingsPromise)historySettingsPromise=request('/api/history-columns').then(data=>{
    const stored=data.columns||[];
    if(stored.length===historyColumnDefaults.length&&new Set(stored.map(c=>c.key)).size===stored.length&&stored.every(c=>historyColumnDefaults.some(d=>d.key===c.key)))historyColumns=stored.map((c,order)=>({...historyColumnDefaults.find(d=>d.key===c.key),...c,order}));
    historySettingsAvailable=true;
  }).catch(()=>{historySettingsAvailable=false});
  return historySettingsPromise;
}
function renderHistoryTable(){
  const columns=historyColumns.filter(c=>c.visible),table=document.querySelector('#historyView .history-table table');
  const total=columns.reduce((sum,c)=>sum+c.width,0),stretch=columns.some(c=>c.key==='remarks'&&c.width===360);
  table.style.minWidth=total+'px';table.style.width=stretch?'100%':total+'px';
  table.querySelector('thead tr').innerHTML=columns.map(c=>`<th data-history-column="${c.key}" style="width:${c.key==='remarks'&&stretch?'auto':c.width+'px'}">${c.key==='documents'?esc(c.label):`<button type="button" data-history-sort="${c.key}" data-label="${esc(c.label)}" title="Сортувати; Shift + click — додати рівень">${esc(c.label)} <small></small></button>`}</th>`).join('');
  const cells=(x,i)=>({supplier:esc(x.supplier_name),code:esc(x.supplier_code),manager:esc(x.manager_name||'—'),date:historyDateCell(x.date_published),cpv:esc(x.dk_code),framework:esc(x.framework_title),decision:esc(x.decision),officer:esc(x.protocol_officer||'—'),contract:esc(x.contract_details||'—'),remarks:esc(x.protocol_remarks||x.compliance_comments||'—'),documents:`<a href="/?view=applications&submission_id=${encodeURIComponent(x.id)}" target="_blank" rel="noopener">Заявка →</a><button type="button" class="paperclip" data-history-docs="${i}" title="Переглянути документи" aria-label="Переглянути документи: ${x.documents.length}">📎 <span>${x.documents.length}</span></button>`});
  document.querySelector('#historyRows').innerHTML=historyItems.map((x,i)=>{const values=cells(x,i);return '<tr>'+columns.map(c=>`<td data-history-column="${c.key}">${values[c.key]}</td>`).join('')+'</tr>'}).join('')||`<tr><td colspan="${Math.max(1,columns.length)}">Заявок не знайдено</td></tr>`;
  drawHistorySort();
}
document.querySelector('#historyHeadingActions').insertAdjacentHTML('beforeend','<div class="history-column-toolbar"><button type="button" id="historyColumnsButton">Налаштування колонок</button></div>');
document.body.insertAdjacentHTML('beforeend',`<dialog id="historyColumnsDialog"><h2>Колонки історії заявок</h2><input id="historyColumnSearch" placeholder="Знайти колонку за назвою…"><div id="historyColumnList"></div><p id="historyColumnMessage" role="status"></p><footer><button id="historyColumnReset" type="button">Скинути налаштування</button><button id="historyColumnSave" type="button">Зберегти</button><button id="historyColumnCancel" type="button">Скасувати</button></footer></dialog>`);
let historyDraft=[];
function drawHistoryColumnSettings(){
  const term=document.querySelector('#historyColumnSearch').value.trim().toLocaleLowerCase('uk');
  document.querySelector('#historyColumnList').innerHTML=historyDraft.map((c,index)=>({c,index})).filter(({c})=>c.label.toLocaleLowerCase('uk').includes(term)).map(({c,index})=>`<div class="column-item" data-key="${c.key}"><span class="col-drag" draggable="${!term}" title="Перетягнути">⠿</span><input type="checkbox" class="col-visible" aria-label="Показувати ${esc(c.label)}" ${c.visible?'checked':''}><strong>${esc(c.label)}</strong><input type="number" class="col-width" min="60" max="1200" value="${c.width}" aria-label="Ширина ${esc(c.label)}"><button class="col-up" type="button" ${index===0?'disabled':''} aria-label="Вище">↑</button><button class="col-down" type="button" ${index===historyDraft.length-1?'disabled':''} aria-label="Нижче">↓</button></div>`).join('');
}
document.querySelector('#historyColumnsButton').onclick=async()=>{await ensureHistoryColumns();historyDraft=structuredClone(historyColumns);document.querySelector('#historyColumnSearch').value='';drawHistoryColumnSettings();document.querySelector('#historyColumnMessage').textContent=historySettingsAvailable?'Зберігається персонально для вашого акаунта на сервері.':'Збереження недоступне: потрібен оновлений LOCAL backend.';document.querySelector('#historyColumnSave').disabled=!historySettingsAvailable;document.querySelector('#historyColumnReset').disabled=!historySettingsAvailable;document.querySelector('#historyColumnsDialog').showModal()};
document.querySelector('#historyColumnSearch').oninput=drawHistoryColumnSettings;
const historyColumnList=document.querySelector('#historyColumnList');
historyColumnList.onchange=e=>{const c=historyDraft.find(c=>c.key===e.target.closest('[data-key]')?.dataset.key);if(!c)return;if(e.target.matches('.col-visible'))c.visible=e.target.checked;if(e.target.matches('.col-width'))c.width=Math.max(60,Math.min(1200,Math.round(Number(e.target.value)||120)))};
function moveHistoryColumn(from,to){if(from<0||to<0||to>=historyDraft.length)return;historyDraft.splice(to,0,historyDraft.splice(from,1)[0]);drawHistoryColumnSettings()}
historyColumnList.onclick=e=>{const b=e.target.closest('.col-up,.col-down');if(!b)return;const i=historyDraft.findIndex(c=>c.key===b.closest('[data-key]').dataset.key);moveHistoryColumn(i,i+(b.matches('.col-up')?-1:1))};
historyColumnList.ondragstart=e=>{if(document.querySelector('#historyColumnSearch').value.trim()||!e.target.matches('.col-drag'))return e.preventDefault();e.dataTransfer.setData('text/plain',e.target.closest('[data-key]').dataset.key)};
historyColumnList.ondragover=e=>e.preventDefault();
historyColumnList.ondrop=e=>{e.preventDefault();const target=e.target.closest('[data-key]');if(!target||document.querySelector('#historyColumnSearch').value.trim())return;moveHistoryColumn(historyDraft.findIndex(c=>c.key===e.dataTransfer.getData('text/plain')),historyDraft.findIndex(c=>c.key===target.dataset.key))};
async function saveHistoryColumns(columns){
  try{await request('/api/history-columns',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({columns:columns.map((c,order)=>({key:c.key,visible:c.visible,width:c.width,order}))})});historyColumns=columns.map((c,order)=>({...c,order}));renderHistoryTable();return true}catch(e){document.querySelector('#historyColumnMessage').textContent=e.message;return false}
}
document.querySelector('#historyColumnSave').onclick=async()=>{if(await saveHistoryColumns(historyDraft))document.querySelector('#historyColumnsDialog').close()};
document.querySelector('#historyColumnReset').onclick=async()=>{if(await saveHistoryColumns(historyColumnDefaults)){historyDraft=structuredClone(historyColumnDefaults);drawHistoryColumnSettings();document.querySelector('#historyColumnMessage').textContent='Стандартні налаштування відновлено'}};
document.querySelector('#historyColumnCancel').onclick=()=>document.querySelector('#historyColumnsDialog').close();
