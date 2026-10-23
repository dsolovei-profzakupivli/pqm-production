/* One admin-only system-width editor shared by PQM tables. */
(()=>{
let saved={};
const headingDefaults=new WeakMap();
function isPersonalTable(table){return table?.id==='applicationsTable'||!!table?.closest('#historyView')}
function canResize(table){return document.body.dataset.authRole==='admin'||(isPersonalTable(table)&&['admin','officer','viewer'].includes(document.body.dataset.authRole))}
function heads(table){
  const grid=[],positions=new Map();
  [...table.tHead.rows].forEach((row,y)=>{grid[y]||=[];let x=0;
    [...row.cells].forEach(cell=>{while(grid[y][x])x++;positions.set(cell,x);
      for(let dy=0;dy<cell.rowSpan;dy++){grid[y+dy]||=[];for(let dx=0;dx<cell.colSpan;dx++)grid[y+dy][x+dx]=cell}x+=cell.colSpan;
    });
  });
  return (grid.at(-1)||[]).map((cell,i)=>{if(cell.colSpan===1)cell.dataset.resizeIndex=String(i);return cell});
}
function defaultsFor(table){
  const hs=heads(table);let result=headingDefaults.get(table);
  if(!result||result.length!==hs.length){result=hs.map(th=>Number(th.dataset.defaultWidth)||Math.max(40,Math.round(th.getBoundingClientRect().width/th.colSpan)||120));headingDefaults.set(table,result)}
  return result;
}
function uniqueKeys(table){const counts=new Map(),raw=heads(table).map((th,i)=>columnKey(th,i));return raw.map((key,index)=>{const count=counts.get(key)||0;counts.set(key,count+1);return raw.filter(value=>value===key).length>1?`${key}#${index+1}`:key})}
function keysFor(table){const current=uniqueKeys(table),cached=baseOrder.get(table);if(!cached){baseOrder.set(table,current);return current}if(cached.length!==current.length||current.some(key=>!cached.includes(key))){const next=[...cached.filter(key=>current.includes(key)),...current.filter(key=>!cached.includes(key))];baseOrder.set(table,next);return next}return cached}
function currentOrder(table){const canonical=keysFor(table),stored=table.tHead?.rows[0]?.dataset.systemOrder?JSON.parse(table.tHead.rows[0].dataset.systemOrder):canonical;return [...stored.filter(key=>canonical.includes(key)),...canonical.filter(key=>!stored.includes(key))]}
function sizesFor(table,widths){return heads(table).map((th,i)=>Number(widths[currentOrder(table)[i]])||Number(widths[th.dataset.widthLegacyKey||slug(th.textContent)])||defaultsFor(table)[i])}
function effectiveOrder(table,widths){const keys=simpleOrderRows(table)?keysFor(table):[...new Set(keysFor(table))],requested=Array.isArray(widths.__order__)?widths.__order__:[];return [...requested.filter((key,i)=>keys.includes(key)&&requested.indexOf(key)===i),...keys.filter(key=>!requested.includes(key))]}
function effectiveVisibility(table,widths){const keys=keysFor(table);if(!Array.isArray(widths.__visible__))return new Set(keys);const known=new Set(Array.isArray(widths.__columns__)?widths.__columns__:Object.keys(widths).filter(key=>!key.startsWith('__')));return new Set([...widths.__visible__,...keys.filter(key=>!known.has(key))])}
const baseOrder=new WeakMap();
function simpleOrderRows(table){return table.tHead?.rows.length===1&&[...table.tHead.rows[0].cells].every(cell=>cell.colSpan===1&&cell.rowSpan===1)}
function reorderTable(table,widths){
  if(!simpleOrderRows(table))return false;
  const head=table.tHead.rows[0],canonical=keysFor(table);
  if(canonical.length!==head.cells.length)return false;baseOrder.set(table,canonical);
  const desired=effectiveOrder(table,widths);if(desired.length!==canonical.length)return false;
  for(const row of [head,...[...table.tBodies].flatMap(body=>[...body.rows])]){
    if(row.cells.length===1&&row.cells[0].colSpan>1)continue;
    if([...row.cells].some(cell=>cell.colSpan!==1||cell.rowSpan!==1)||row.cells.length!==canonical.length)continue;
    const stored=row.dataset.systemOrder?JSON.parse(row.dataset.systemOrder):canonical,current=[...stored.filter(key=>canonical.includes(key)),...canonical.filter(key=>!stored.includes(key))];
    const cells=[...row.cells],byKey=new Map(current.map((key,index)=>[key,cells[index]]));
    if(desired.some(key=>!byKey.has(key)))continue;
    desired.forEach(key=>row.append(byKey.get(key)));row.dataset.systemOrder=JSON.stringify(desired);
  }
  return true;
}
function applyLogical(table,widths){
  if(!isPersonalTable(table))reorderTable(table,widths);
  const hs=heads(table),sizes=sizesFor(table,widths),visible=effectiveVisibility(table,widths),visibility=!isPersonalTable(table);
  const visualKeys=currentOrder(table);let total=0;hs.forEach((th,i)=>{if(!visibility||th.dataset.columnFixed==='1'||visible.has(visualKeys[i]))total+=sizes[i]});
  for(const section of [table.tHead,...table.tBodies]){const occupied=[];
    [...section.rows].forEach((row,y)=>{occupied[y]||=[];let x=0;
      [...row.cells].forEach(cell=>{while(occupied[y][x])x++;const start=x;
        for(let dy=0;dy<cell.rowSpan;dy++){occupied[y+dy]||=[];for(let dx=0;dx<cell.colSpan;dx++)occupied[y+dy][x+dx]=true}x+=cell.colSpan;
        const size=sizes.slice(start,x).reduce((a,b)=>a+b,0);
        const shown=hs.slice(start,x).some((th,i)=>!visibility||th.dataset.columnFixed==='1'||visible.has(visualKeys[start+i]));
        if(cell.hidden===shown)cell.hidden=!shown;
        if(size){const value=`${size}px`;if(cell.style.width!==value)cell.style.width=cell.style.minWidth=cell.style.maxWidth=value}
      });
    });
  }
  const value=`${total}px`;if(table.style.width!==value){table.style.setProperty('width',value,'important');table.style.setProperty('min-width',value,'important')}
  table.style.tableLayout='fixed';table.dataset.personalWidthApplied='1';
}
let suppressClickUntil=0;
document.addEventListener('click',e=>{if(Date.now()<suppressClickUntil&&e.target.closest('th')){e.preventDefault();e.stopImmediatePropagation()}},true);
function bindResize(table){
  heads(table).forEach(th=>{
    const allowed=canResize(table)&&th.colSpan===1&&th.dataset.columnKey!=='marketplaceLink'&&!th.querySelector('input[type="checkbox"]');
    if(th.classList.contains('column-resizable')!==allowed)th.classList.toggle('column-resizable',allowed);
    const handle=th.querySelector(':scope>.column-resize-handle');
    if(!allowed){handle?.remove();return}
    if(getComputedStyle(th).position==='static')th.style.position='relative';
    if(!handle){const grip=document.createElement('span');grip.className='column-resize-handle';grip.setAttribute('aria-hidden','true');th.append(grip)}
  });
  if(table.dataset.resizeBound)return;table.dataset.resizeBound='1';
  table.addEventListener('pointerdown',e=>{
    if(!canResize(table)||e.button!==0||e.target.closest('input,button,select,a'))return;
    const th=e.target.closest('th.column-resizable');if(!th)return;
    const rect=th.getBoundingClientRect();if(e.clientX<rect.right-9)return;
    e.preventDefault();e.stopImmediatePropagation();
    const native=table.id==='applicationsTable'||!!table.closest('#historyView');
    const index=Number(th.dataset.resizeIndex),key=table.dataset.systemTable,widths={...(saved[key]||{})},sizes=native?heads(table).map(h=>Math.round(h.getBoundingClientRect().width)):sizesFor(table,widths),start=e.clientX,visualKeys=currentOrder(table);
    sizes[index]=Math.round(rect.width);let width=sizes[index];const original=width;
    const minimum=table.closest('#historyView')?60:40;
    const move=event=>{width=Math.max(minimum,Math.min(1200,Math.round(original+event.clientX-start)));const next={...widths};visualKeys.forEach((column,i)=>next[column]=i===index?width:sizes[i]);applyLogical(table,next)};
    const finish=event=>{document.removeEventListener('pointermove',move,true);document.removeEventListener('pointerup',finish,true);document.removeEventListener('pointercancel',finish,true);document.body.classList.remove('column-resizing');suppressClickUntil=Date.now()+250;
      if(event.type==='pointercancel'||!canResize(table)){const originalWidths={};heads(table).forEach((h,i)=>originalWidths[columnKey(h,i)]=sizes[i]);applyLogical(table,originalWidths);return}
      const column=visualKeys[index];
      if(isPersonalTable(table))table.dispatchEvent(new CustomEvent('pqm:table-column-resize',{bubbles:true,detail:{key:column,width}}));
      else saveShared(key,{...widths,[column]:width},table).catch(()=>{applyLogical(table,widths);toast('Не вдалося зберегти ширину','error')});
    };
    document.body.classList.add('column-resizing');document.addEventListener('pointermove',move,true);document.addEventListener('pointerup',finish,true);document.addEventListener('pointercancel',finish,true);
  },true);
}
const defaultWidths=new WeakMap();
const slug=value=>String(value||'').trim().toLocaleLowerCase('uk-UA').replace(/[^a-zа-яіїєґ0-9]+/g,'-').replace(/^-|-$/g,'');
function tableKey(table,index){
  if(table.dataset.systemTable)return table.dataset.systemTable;
  const scope=table.closest('.module-view')?.id||table.closest('dialog[id]')?.id||'pqm';
  const identity=table.id||table.querySelector('tbody[id]')?.id;
  if(identity)return `${scope}:${identity}`;
  // Anonymous dynamic tables use their semantic headings, not row data or task IDs.
  const signature=`${table.parentElement.closest('[id]')?.id||''}:${heads(table).map(th=>th.textContent.trim()).join('|')}`;
  let hash=2166136261;for(const ch of signature)hash=Math.imul(hash^ch.charCodeAt(0),16777619)>>>0;
  return `${scope}:${table.classList[1]||'table'}:${slug(signature).slice(0,70)}:${hash.toString(16)}`.slice(0,120);
}
function columnKey(th,index){return th.dataset.edrColumn||th.dataset.columnKey||th.dataset.historyColumn||th.dataset.col||th.dataset.key||th.dataset.sort||slug(th.textContent)||`column-${index+1}`}
function apply(table,widths){if(Object.keys(widths).length||table.dataset.personalWidthApplied||table.querySelector('th[data-default-width]'))applyLogical(table,widths)}
async function saveShared(key,settings,table){
  if(document.body.dataset.authRole!=='admin')throw new Error('Спільні налаштування може змінювати лише адміністратор');
  const columns=[...new Set(keysFor(table))],body={table_key:key,widths:Object.fromEntries(Object.entries(settings).filter(([name])=>!name.startsWith('__'))),columns};
  if(simpleOrderRows(table))body.order=effectiveOrder(table,settings);
  const order=body.order||settings.__order__;
  if(!isPersonalTable(table)){const visible=[...effectiveVisibility(table,settings)];body.visible=visible;settings.__visible__=visible}
  if(order)settings.__order__=order;settings.__columns__=columns;
  const result=await request(`${API}/admin/table-widths`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  saved[key]=result.widths||settings;apply(table,saved[key]);return saved[key];
}
const dialog=document.createElement('dialog');dialog.className='system-width-dialog';dialog.innerHTML='<form><header><h2>Налаштування колонок</h2><button type="button" class="dialog-close">×</button></header><div class="system-width-fields"></div><footer><button type="button" class="ghost system-width-reset">Відновити стандартні</button><span></span><button type="button" class="ghost dialog-cancel">Скасувати</button><button class="primary">Зберегти</button></footer></form>';document.body.append(dialog);dialog.querySelectorAll('.dialog-close,.dialog-cancel').forEach(b=>b.onclick=()=>dialog.close());
function isVisible(element){return !element.closest('[hidden]')&&getComputedStyle(element).display!=='none'&&getComputedStyle(element).visibility!=='hidden'&&element.getBoundingClientRect().width>0}
function toolbarFor(table){
  const panel=table.closest('.admin-panel,.reference-panel');
  if(panel){
    const local=[...panel.querySelectorAll('.admin-framework-actions,.admin-officer-add,.reference-toolbar,.admin-template-heading')].find(isVisible);
    if(local)return local;
  }
  const card=table.closest('.card'),header=card?.querySelector(':scope>header');
  if(header&&isVisible(header))return header;
  const view=table.closest('.module-view');
  return [...(view?.querySelectorAll('.edr-monitoring-toolbar,.supplier-toolbar,.reference-toolbar,.requests-toolbar,.frameworks-toolbar,.heading-actions')||[])].find(isVisible)||null;
}
function install(){
  if(!['admin','officer','viewer'].includes(document.body.dataset.authRole)&&dialog.open)dialog.close();
  document.querySelectorAll('table[data-width-control]').forEach(table=>delete table.dataset.widthControl);
  const occupied=new Set(),desired=[];
  document.querySelectorAll('table').forEach((table,i)=>{
    if(!table.tHead?.rows.length)return;
    if(!isVisible(table))return;
    defaultsFor(table);bindResize(table);
    if(table.id==='applicationsTable'||table.closest('#historyView'))return;
    const key=tableKey(table,i);table.dataset.systemTable=key;
    apply(table,saved[key]||{});
    if(document.body.dataset.authRole!=='admin'||!isVisible(table))return;
    const toolbar=toolbarFor(table)||toolbarForFallback(table);if(!toolbar){toolbarForFallback(table);return}if(occupied.has(toolbar)){const fallback=toolbarForFallback(table);desired.push({table,key,toolbar:fallback});return;}
    occupied.add(toolbar);table.dataset.widthControl='1';desired.push({table,key,toolbar})
  });
  document.querySelectorAll('.system-width-button').forEach(button=>{const item=desired.find(x=>x.key===button.dataset.tableKey&&x.toolbar===button.parentElement);if(!item)button.remove()});
  desired.forEach(({table,key,toolbar})=>{if(toolbar.querySelector(`.system-width-button[data-table-key="${CSS.escape(key)}"]`))return;const button=document.createElement('button');button.type='button';button.className='ghost icon-button system-width-button';button.textContent='▥';button.title='Налаштувати колонки';button.setAttribute('aria-label','Налаштувати колонки');button.dataset.tableKey=key;button.onclick=()=>edit(table,key);toolbar.append(button)})
}
function toolbarForFallback(table){
 let toolbar=table.previousElementSibling;
 if(!toolbar?.classList.contains('system-width-toolbar')){toolbar=document.createElement('div');toolbar.className='system-width-toolbar';table.before(toolbar)}
 return toolbar;
}
function clearApplied(table){table.querySelector(':scope>colgroup[data-system-widths]')?.remove();defaultWidths.delete(table);[...table.tHead.rows[0].cells].forEach((th,i)=>{th.hidden=false;th.style.width=th.style.minWidth=th.style.maxWidth='';for(const row of table.tBodies[0]?.rows||[]){if(row.cells[i]){row.cells[i].hidden=false;row.cells[i].style.width=row.cells[i].style.minWidth=row.cells[i].style.maxWidth=''}}});table.style.width=table.style.minWidth=table.style.tableLayout=''}
async function edit(table,key){if(document.body.dataset.authRole!=='admin')return;const widths={...(saved[key]||{})},fields=dialog.querySelector('.system-width-fields'),visibility=!isPersonalTable(table),orderAllowed=simpleOrderRows(table);let order=effectiveOrder(table,widths),visibleDraft=effectiveVisibility(table,widths);const draw=()=>{const visual=currentOrder(table),byKey=new Map(heads(table).map((th,i)=>[visual[i],th])),sizes=sizesFor(table,widths);fields.classList.toggle('with-visibility',visibility);fields.innerHTML=order.map((k,i)=>{const th=byKey.get(k);if(!th||th.dataset.columnFixed==='1')return'';const visualIndex=visual.indexOf(k),current=Number(widths[k])||sizes[visualIndex]||Number(th.dataset.defaultWidth)||defaultsFor(table)[visualIndex]||120;return `<label data-order-key="${esc(k)}">${orderAllowed?`<span class="column-order-controls"><button type="button" class="icon-btn order-up" ${i===0?'disabled':''} aria-label="Перемістити вище">↑</button><button type="button" class="icon-btn order-down" ${i===order.length-1?'disabled':''} aria-label="Перемістити нижче">↓</button></span>`:'<span class="column-order-controls" aria-hidden="true"></span>'}${visibility?`<input type="checkbox" data-visible="${esc(k)}" ${visibleDraft.has(k)?'checked':''}>`:''}<span>${esc(th.textContent.trim()||k)}</span><input type="number" min="40" max="1200" required value="${current}" data-column="${esc(k)}"><small>px</small></label>`}).join('')};draw();fields.onclick=e=>{const button=e.target.closest('.order-up,.order-down'),label=button?.closest('[data-order-key]');if(!button||!label)return;const from=order.indexOf(label.dataset.orderKey),to=from+(button.matches('.order-up')?-1:1);if(to<0||to>=order.length)return;[order[from],order[to]]=[order[to],order[from]];draw()};fields.onchange=e=>{const input=e.target.closest('[data-visible]');if(!input)return;input.checked?visibleDraft.add(input.dataset.visible):visibleDraft.delete(input.dataset.visible)};dialog.querySelector('form').onsubmit=async event=>{event.preventDefault();if(document.body.dataset.authRole!=='admin'||!event.currentTarget.reportValidity())return;const next={...widths};fields.querySelectorAll('[data-column]').forEach(input=>next[input.dataset.column]=Math.max(40,Math.min(1200,Number(input.value))));if(visibility)next.__visible__=[...visibleDraft];if(orderAllowed)next.__order__=[...order];next.__columns__=[...new Set(keysFor(table))];try{await saveShared(key,next,table);dialog.close();toast('Спільні налаштування колонок збережено')}catch(error){toast(error.message||'Не вдалося зберегти колонки','error')}};dialog.querySelector('.system-width-reset').onclick=async()=>{if(document.body.dataset.authRole!=='admin')return;try{await request(`${API}/admin/table-widths?table_key=${encodeURIComponent(key)}`,{method:'DELETE'});delete saved[key];clearApplied(table);applyLogical(table,{});dialog.close();toast('Стандартні налаштування відновлено')}catch(error){toast(error.message||'Не вдалося відновити колонки','error')}};dialog.showModal()}
let initialized=false,initializing=null;
function initialize(){
  if(initialized)return Promise.resolve();
  if(initializing)return initializing;
  initializing=(async()=>{
    for(let attempt=0;attempt<3;attempt++){
      try{
        const data=await request(`${API}/table-widths`);
        saved=data.tables||{};
        window.dispatchEvent(new Event('pqm:table-widths-ready'));
        let queued=false;
        const schedule=()=>{if(queued)return;queued=true;requestAnimationFrame(()=>{queued=false;install()})};
        install();
        new MutationObserver(schedule).observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['hidden','open','class','data-auth-role']});
        // Hidden tables measure zero. Reapply saved widths after their real
        // container is laid out, not only after DOM mutations or a manual F5.
        if(typeof ResizeObserver!=='undefined'){
          const observer=new ResizeObserver(schedule);
          document.querySelectorAll('main').forEach(view=>observer.observe(view));
        }
        window.addEventListener('resize',schedule);
        document.fonts?.ready.then(schedule);
        initialized=true;
        return;
      }catch(e){
        if(attempt===2){console.warn('System table widths unavailable',e);return}
        await new Promise(resolve=>setTimeout(resolve,350*(attempt+1)));
      }
    }
  })().finally(()=>{initializing=null});
  return initializing;
}
window.PQMTableWidths={width:(_key,_column,fallback)=>fallback};
authReady.then(initialize);
window.addEventListener('online',()=>{if(!initialized)initialize()});
window.addEventListener('focus',()=>{if(!initialized)initialize()});
})();
