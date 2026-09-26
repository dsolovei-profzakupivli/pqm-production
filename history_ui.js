// Read-only history shares submission data and the existing document viewer.
function historyDateCell(value){
  if(!value)return '';
  const formatted=displayDate(value),parts=formatted.split(', ');
  return `<span class="history-date-line">${esc(parts[0])}</span>${parts[1]?`<span class="history-date-line">${esc(parts[1])}</span>`:''}`;
}
let historyPage=1,historyPages=1,historyRequest=0,historyTimer,historyItems=[];
let historySorts=[{key:'date',direction:'desc'}];
function historySupplierCode(){return document.querySelector('[data-history="code"]').value.trim()}
function syncHistorySupplierCardButton(){const button=document.querySelector('#historySupplierCard'),code=historySupplierCode();button.disabled=!code;button.dataset.supplierCode=code;button.title=code?`Відкрити картку постачальника ${code}`:'Встановіть точний фільтр ЄДРПОУ / РНОКПП'}
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
    $('#historyTotal').textContent=String(data.total);syncHistorySupplierCardButton();
    renderHistoryTable();
    $('#historyCount').textContent=`${data.total} заявок · сторінка ${data.page} із ${data.pages}`;
    $('#historyPrev').disabled=historyPage<=1;$('#historyNext').disabled=historyPage>=historyPages;
  }catch(error){if(ticket===historyRequest){$('#historyCount').textContent=error.message;$('#historyTotal').textContent='—'}}
}
function openSupplierHistory(code){
  $('#supplierProfileDialog').close();document.querySelectorAll('[data-history]').forEach(el=>el.value='');
  document.querySelector('[data-history="code"]').value=String(code||'').trim();historyPage=1;syncHistorySupplierCardButton();showModule('history');loadApplicationHistory();
}
document.querySelector('#historyHeadingActions').insertAdjacentHTML('afterbegin','<button type="button" id="historySupplierCard" disabled>Картка постачальника</button>');
document.querySelector('#historySupplierCard').onclick=()=>{const code=historySupplierCode();if(code)openSupplierProfile(code)};
$('#historyNav').onclick=()=>{showModule('history');loadApplicationHistory()};
$('#historyFilters').oninput=()=>{syncHistorySupplierCardButton();clearTimeout(historyTimer);historyTimer=setTimeout(()=>{historyPage=1;loadApplicationHistory()},300)};
$('#historyReset').onclick=()=>{document.querySelectorAll('[data-history]').forEach(el=>el.value='');historyPage=1;syncHistorySupplierCardButton();loadApplicationHistory()};
$('#historyPrev').onclick=()=>{if(historyPage>1){historyPage--;loadApplicationHistory()}};
$('#historyNext').onclick=()=>{if(historyPage<historyPages){historyPage++;loadApplicationHistory()}};
$('#historyRows').onclick=e=>{const b=e.target.closest('[data-history-docs]');if(b){const x=historyItems[Number(b.dataset.historyDocs)];openHistoryDocuments(mapRow(x),x.document_groups||{supplier:x.documents||[],decision:x.decision_documents||[],registry:x.registry_documents||[]})}};
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
function showSimilarRemarks(){const point=normalizedRemark($('#referenceRemarkPoint').value),text=normalizedRemark($('#referenceRemarkText').value),words=new Set(text.split(' ').filter(x=>x.length>3));const similar=remarksItems.filter(x=>point&&normalizedRemark(x.point)===point||words.size&&[...words].filter(w=>normalizedRemark(x.text).includes(w)).length/words.size>=0.5).slice(0,5);$('#remarkSimilar').textContent=(point||text)&&similar.length?'Схожі записи (не автоматичні дублікати): '+similar.map(x=>x.point+' — '+x.text).join(' | '):''}
$('#referenceRemarkPoint').addEventListener('input',showSimilarRemarks);$('#referenceRemarkText').addEventListener('input',showSimilarRemarks);
$('#referenceRemarkText').after($('#remarkSimilar'));
$('#referenceRemarkDialog').addEventListener('close',()=>{$('#remarkSimilar').textContent=''});

// The read-only data dictionary tab is implemented in schema_ui.js.
