// Read-only history shares submission data and the existing document viewer.
function historyDateCell(value){
  if(!value)return '';
  const date=new Date(value);
  if(Number.isNaN(date.valueOf()))return esc(value);
  const day=date.toLocaleDateString('uk-UA',{day:'2-digit',month:'2-digit',year:'2-digit'});
  const time=/^\d{4}-\d{2}-\d{2}$/.test(String(value).trim())?'':date.toLocaleTimeString('uk-UA',{hour:'2-digit',minute:'2-digit'});
  return `<span class="history-date-line">${esc(day)}</span>${time?`<span class="history-date-line">${esc(time)}</span>`:''}`;
}
let historyPage=1,historyPages=1,historyRequest=0,historyTimer,historyItems=[];
let historySorts=[{key:'date',direction:'desc'}];
function drawHistorySort(){
  document.querySelectorAll('[data-history-sort]').forEach(button=>{const i=historySorts.findIndex(x=>x.key===button.dataset.historySort);button.querySelector('small').textContent=i<0?'':`${historySorts[i].direction==='asc'?'↑':'↓'}${i+1}`;button.setAttribute('aria-label',`${button.dataset.label}${i<0?'':`, ${historySorts[i].direction}, пріоритет ${i+1}`}`)});
}
document.querySelector('#historyView thead').onclick=e=>{const b=e.target.closest('[data-history-sort]');if(!b)return;const key=b.dataset.historySort,i=historySorts.findIndex(x=>x.key===key);
  if(e.shiftKey){if(i<0)historySorts.push({key,direction:'asc'});else if(historySorts[i].direction==='asc')historySorts[i].direction='desc';else historySorts.splice(i,1)}
  else historySorts=[{key,direction:i>=0&&historySorts[i].direction==='asc'?'desc':'asc'}];
  if(!historySorts.length)historySorts=[{key:'date',direction:'desc'}];
  historyPage=1;drawHistorySort();loadApplicationHistory();
};
drawHistorySort();
moduleNames.push('history');
async function loadApplicationHistory(){
  const ticket=++historyRequest,q=new URLSearchParams({page:String(historyPage),size:'50'});
  $('#historyTotal').textContent='…';
  await ensureHistoryColumns();
  q.set('sorts',JSON.stringify(historySorts));
  document.querySelectorAll('[data-history]').forEach(el=>q.set(el.dataset.history,el.value.trim()));
  try{
    const data=await request(`/api/application-history?${q}`);if(ticket!==historyRequest)return;
    historyItems=data.items;historyPages=data.pages;
    $('#historyTotal').textContent=String(data.total);
    renderHistoryTable();
    $('#historyCount').textContent=`${data.total} заявок · сторінка ${data.page} із ${data.pages}`;
    $('#historyPrev').disabled=historyPage<=1;$('#historyNext').disabled=historyPage>=historyPages;
  }catch(error){if(ticket===historyRequest){$('#historyCount').textContent=error.message;$('#historyTotal').textContent='—'}}
}
function openSupplierHistory(code){
  $('#supplierProfileDialog').close();document.querySelectorAll('[data-history]').forEach(el=>el.value='');
  document.querySelector('[data-history="code"]').value=code;historyPage=1;showModule('history');loadApplicationHistory();
}
$('#historyNav').onclick=()=>{showModule('history');loadApplicationHistory()};
$('#historyFilters').oninput=()=>{clearTimeout(historyTimer);historyTimer=setTimeout(()=>{historyPage=1;loadApplicationHistory()},300)};
$('#historyReset').onclick=()=>{document.querySelectorAll('[data-history]').forEach(el=>el.value='');historyPage=1;loadApplicationHistory()};
$('#historyPrev').onclick=()=>{if(historyPage>1){historyPage--;loadApplicationHistory()}};
$('#historyNext').onclick=()=>{if(historyPage<historyPages){historyPage++;loadApplicationHistory()}};
$('#historyRows').onclick=e=>{const b=e.target.closest('[data-history-docs]');if(b){const x=historyItems[Number(b.dataset.historyDocs)];openDocs(mapRow(x),x.documents,'Документи історичної заявки')}};
if(new URLSearchParams(location.search).get('view')==='history'){showModule('history');loadApplicationHistory()}

// Existing remarks catalogue: presentation/revision only, no copy of historical text.
$('#refRemarksList').insertAdjacentHTML('beforebegin',`<div class="card history-filters"><input id="remarkRevisionSearch" placeholder="Пошук за пунктом або текстом…"><select id="remarkRevisionSort"><option value="point">За пунктом</option><option value="text">За текстом</option></select><label><input type="checkbox" id="remarkRevisionDuplicates"> Лише точні дублікати</label><label><input type="checkbox" id="remarkRevisionInactive"> Показати неактивні</label><span id="remarkRevisionCount"></span><div id="remarkSimilar" class="muted"></div></div>`);
const normalizedRemark=value=>String(value||'').normalize('NFC').toLocaleLowerCase('uk').trim().replace(/\s+/g,' ');
function drawReferenceRemarks(){
  const term=normalizedRemark($('#remarkRevisionSearch').value),sort=$('#remarkRevisionSort').value;
  const keys=new Map();remarksItems.forEach(x=>{const k=normalizedRemark(x.point)+'|'+normalizedRemark(x.text);keys.set(k,(keys.get(k)||0)+1)});
  const shown=remarksItems.filter(x=>($('#remarkRevisionInactive').checked||x.active)&&(!term||normalizedRemark(x.point+' '+x.text).includes(term))&&(!$('#remarkRevisionDuplicates').checked||keys.get(normalizedRemark(x.point)+'|'+normalizedRemark(x.text))>1)).sort((a,b)=>String(a[sort]||'').localeCompare(String(b[sort]||''),'uk',{numeric:true}));
  $('#remarkRevisionCount').textContent=`Записів: ${remarksItems.length} · показано: ${shown.length}`;
  $('#refRemarksList').innerHTML=shown.map(x=>`<article class="reference-remark"><div><strong>${esc(x.point)}</strong>${x.active?'':' · Неактивний'}<p>${esc(x.text)}</p></div><div><button type="button" onclick="editReferenceRemark('${x.id}')">Редагувати</button><button type="button" ${x.active?'':'disabled'} onclick="removeReferenceRemark('${x.id}')">Деактивувати</button></div></article>`).join('')||'<p>Записів не знайдено</p>';
}
loadReferenceRemarks=async function(){try{remarksItems=(await request('/api/remarks-catalog?all=1')).items;drawReferenceRemarks()}catch(e){$('#refRemarksList').textContent=e.message}};
['remarkRevisionSearch','remarkRevisionSort','remarkRevisionDuplicates','remarkRevisionInactive'].forEach(id=>$('#'+id).oninput=drawReferenceRemarks);
function showSimilarRemarks(){const point=normalizedRemark($('#refRemarkPoint').value),text=normalizedRemark($('#refRemarkText').value),words=new Set(text.split(' ').filter(x=>x.length>3));const similar=remarksItems.filter(x=>point&&normalizedRemark(x.point)===point||words.size&&[...words].filter(w=>normalizedRemark(x.text).includes(w)).length/words.size>=0.5).slice(0,5);$('#remarkSimilar').textContent=(point||text)&&similar.length?'Схожі записи (не автоматичні дублікати): '+similar.map(x=>x.point+' — '+x.text).join(' | '):''}
$('#refRemarkPoint').addEventListener('input',showSimilarRemarks);$('#refRemarkText').addEventListener('input',showSimilarRemarks);

// Admin-only, schema-backed field inventory. Unmapped semantics stay explicitly unknown.
document.querySelector('#administrationView .reference-tabs').insertAdjacentHTML('beforeend','<button type="button" id="schemaTab" data-admin-tab="schema">Схема PQM</button>');
$('#administrationView').insertAdjacentHTML('beforeend','<section id="adminSchemaPanel" class="admin-panel" hidden><h2>Схема PQM</h2><p>Фактичні поля SQLite та metadata пошуку. Значення даних не відображаються. Template engine не реалізовано.</p><input id="schemaSearch" placeholder="Таблиця / поле…"><div class="history-table"><table><thead><tr><th>Назва</th><th>Key</th><th>Таблиця</th><th>Тип</th><th>Джерело / поле</th><th>Примітки</th><th>У шаблонах</th></tr></thead><tbody id="schemaRows"></tbody></table></div></section>');
let schemaItems=[];function drawSchema(){const q=$('#schemaSearch').value.toLowerCase();$('#schemaRows').innerHTML=schemaItems.filter(x=>(x.table+' '+x.key+' '+x.label).toLowerCase().includes(q)).map(x=>`<tr><td>${esc(x.label)}</td><td>${esc(x.key)}</td><td>${esc(x.table)}</td><td>${esc(x.type)}</td><td>${esc(x.source)}<small>${esc(x.source_field)}</small></td><td>${esc(x.notes)}</td><td>Не позначено</td></tr>`).join('')}
const baseAdminTab=setAdminTab;setAdminTab=function(name){$('#adminSchemaPanel').hidden=name!=='schema';if(name!=='schema')return baseAdminTab(name);document.querySelectorAll('#administrationView .admin-panel').forEach(x=>x.hidden=x.id!=='adminSchemaPanel');document.querySelectorAll('[data-admin-tab]').forEach(x=>x.classList.toggle('active',x.dataset.adminTab==='schema'));request('/api/admin/schema').then(data=>{schemaItems=data.items;drawSchema()}).catch(e=>$('#schemaRows').textContent=e.message)};
$('#schemaTab').onclick=()=>setAdminTab('schema');$('#schemaSearch').oninput=drawSchema;
