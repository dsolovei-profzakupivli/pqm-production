/* One admin-only system-width editor shared by PQM tables. */
(()=>{
let saved={};
const slug=value=>String(value||'').trim().toLocaleLowerCase('uk-UA').replace(/[^a-zа-яіїєґ0-9]+/g,'-').replace(/^-|-$/g,'');
function tableKey(table,index){return table.dataset.systemTable||`${table.closest('.module-view')?.id||'pqm'}:${table.id||table.querySelector('tbody')?.id||table.classList[1]||index}`}
function columnKey(th,index){return th.dataset.col||th.dataset.key||th.dataset.sort||slug(th.textContent)||`column-${index+1}`}
function apply(table,widths){const heads=[...table.tHead?.rows?.[0]?.cells||[]];heads.forEach((th,i)=>{const value=Number(widths[columnKey(th,i)]);if(!value)return;th.style.width=th.style.minWidth=`${value}px`;for(const row of table.tBodies[0]?.rows||[]){const cell=row.cells[i];if(cell)cell.style.width=cell.style.minWidth=`${value}px`}})}
const dialog=document.createElement('dialog');dialog.className='system-width-dialog';dialog.innerHTML='<form><header><h2>Налаштування колонок</h2><button type="button" class="dialog-close">×</button></header><div class="system-width-fields"></div><footer><button type="button" class="ghost system-width-reset">Відновити стандартні</button><span></span><button type="button" class="ghost dialog-cancel">Скасувати</button><button class="primary">Зберегти</button></footer></form>';document.body.append(dialog);dialog.querySelectorAll('.dialog-close,.dialog-cancel').forEach(b=>b.onclick=()=>dialog.close());
function isVisible(element){return !element.closest('[hidden]')&&getComputedStyle(element).display!=='none'&&getComputedStyle(element).visibility!=='hidden'}
function toolbarFor(table){
  const panel=table.closest('.admin-panel,.reference-panel');
  if(panel){
    const local=[...panel.querySelectorAll('.admin-framework-actions,.admin-officer-add,.reference-toolbar,.admin-template-heading')].find(isVisible);
    if(local)return local;
  }
  const card=table.closest('.card'),header=card?.querySelector(':scope>header');
  if(header&&isVisible(header))return header;
  const view=table.closest('.module-view');
  return [...(view?.querySelectorAll('.supplier-toolbar,.reference-toolbar,.requests-toolbar,.heading-actions')||[])].find(isVisible)||null;
}
function install(){
  document.querySelectorAll('table[data-width-control]').forEach(table=>delete table.dataset.widthControl);
  const occupied=new Set(),desired=[];
  document.querySelectorAll('table').forEach((table,i)=>{
    if(table.closest('#applicationsView,#historyView'))return;
    const key=tableKey(table,i);table.dataset.systemTable=key;apply(table,saved[key]||{});
    if(document.body.dataset.authRole!=='admin'||!isVisible(table))return;
    const toolbar=toolbarFor(table);if(!toolbar||occupied.has(toolbar))return;
    occupied.add(toolbar);table.dataset.widthControl='1';desired.push({table,key,toolbar})
  });
  document.querySelectorAll('.system-width-button').forEach(button=>{const item=desired.find(x=>x.key===button.dataset.tableKey&&x.toolbar===button.parentElement);if(!item)button.remove()});
  desired.forEach(({table,key,toolbar})=>{if(toolbar.querySelector(`.system-width-button[data-table-key="${CSS.escape(key)}"]`))return;const button=document.createElement('button');button.type='button';button.className='ghost icon-button system-width-button';button.textContent='▥';button.title='Налаштувати колонки';button.setAttribute('aria-label','Налаштувати колонки');button.dataset.tableKey=key;button.onclick=()=>edit(table,key);toolbar.append(button)})
}
function clearApplied(table){[...table.tHead.rows[0].cells].forEach((th,i)=>{th.style.width=th.style.minWidth='';for(const row of table.tBodies[0]?.rows||[]){if(row.cells[i])row.cells[i].style.width=row.cells[i].style.minWidth=''}})}
async function edit(table,key){const widths={...(saved[key]||{})},heads=[...table.tHead.rows[0].cells],fields=dialog.querySelector('.system-width-fields');fields.innerHTML=heads.map((th,i)=>{const k=columnKey(th,i),current=widths[k]||Math.round(th.getBoundingClientRect().width);return `<label><span>${esc(th.textContent.trim()||k)}</span><input type="number" min="40" max="1200" value="${current}" data-column="${esc(k)}"><small>px</small></label>`}).join('');dialog.querySelector('form').onsubmit=async event=>{event.preventDefault();const next={};fields.querySelectorAll('input').forEach(input=>next[input.dataset.column]=Number(input.value));await request(`${API}/admin/table-widths`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({table_key:key,widths:next})});saved[key]=next;apply(table,next);dialog.close();toast('Системні ширини збережено')};dialog.querySelector('.system-width-reset').onclick=async()=>{await request(`${API}/admin/table-widths?table_key=${encodeURIComponent(key)}`,{method:'DELETE'});delete saved[key];clearApplied(table);dialog.close();toast('Стандартні ширини відновлено')};dialog.showModal()}
authReady.then(async()=>{try{saved=(await request(`${API}/table-widths`)).tables||{};let queued=false;const schedule=()=>{if(queued)return;queued=true;requestAnimationFrame(()=>{queued=false;install()})};install();new MutationObserver(schedule).observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['hidden','class','data-auth-role']})}catch(e){console.warn('System table widths unavailable',e)}});
})();
