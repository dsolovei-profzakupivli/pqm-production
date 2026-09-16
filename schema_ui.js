/* Descriptive metadata only. Navigation never chooses a business record or mutates data. */
(() => {
  const q=id=>document.getElementById(id), e=value=>esc(String(value??''));
  const statuses={draft:'Попередній опис',unapproved:'Опис не погоджено',approved:'Погоджено'};
  const editing={manual:'Ручне редагування',system:'Системне / обчислюване',unknown:'Потребує уточнення'};
  const kinds={physical:'Колонка SQLite',json:'Поле JSON',derived:'Похідне поле'};
  const modes={automatic:'Автоматичний процес',officer:'Дія УО',manual:'Ручне перенесення',unconfirmed:'Потребує підтвердження',planned:'Заплановано'};
  const navigation=new Set(['applicationsNav','historyNav','suppliersNav','edrMonitoringNav','frameworksNav','requestsNav','referencesNav','procurementsNav']);
  let data=null, mode='fields', requestId=0;
  document.querySelector('#administrationView .reference-tabs').insertAdjacentHTML('beforeend','<button type="button" id="schemaTab" data-admin-tab="schema">Схема даних PQM</button>');
  q('administrationView').insertAdjacentHTML('beforeend',`<section id="adminSchemaPanel" class="admin-panel" hidden>
    <header class="schema-heading"><div><p class="schema-eyebrow">ДОВІДНИК ДАНИХ · ЛИШЕ ПЕРЕГЛЯД</p><h2>Схема даних PQM</h2><p>Зміст, походження та використання даних. Без значень записів і без зміни правил PQM.</p></div><span id="schemaVersion"></span></header>
    <div class="schema-mode" role="group" aria-label="Режим схеми"><button type="button" data-schema-mode="fields" aria-pressed="true">Довідник полів</button><button type="button" data-schema-mode="flows" aria-pressed="false">Потоки даних</button></div>
    <p id="schemaNotice" role="status">Завантаження структури…</p>
    <div id="schemaFields"><div class="schema-filters">
    <label class="schema-search">Пошук<input id="schemaSearch" placeholder="Назва, опис, ключ або таблиця…"></label>
    <label>Предметна група<select id="schemaGroup"></select></label><label>Джерело<select id="schemaSource"></select></label>
    <label>Модуль<select id="schemaModule"></select></label><label>Редагування<select id="schemaEditing"></select></label><label>Статус опису<select id="schemaStatus"></select></label>
    <label>Використовується в шаблонах<select id="schemaTemplates"><option value="">Усі</option><option value="yes">Так</option><option value="no">Ні</option></select></label>
    <label class="schema-technical"><input type="checkbox" id="schemaTechnical"> Показати технічні поля</label><button type="button" id="schemaReset">Скинути</button></div>
    <div class="schema-count" id="schemaCount"></div><div class="schema-table-wrap"><table class="schema-table"><thead><tr><th>Назва</th><th>Опис</th><th>Джерело</th><th>Де використовується</th><th>Редагування</th></tr></thead><tbody id="schemaRows"></tbody></table></div></div>
    <div id="schemaFlows" hidden></div></section>`);
  function options(id,items){const node=q(id),saved=node.value;node.innerHTML='<option value="">Усі</option>'+items.map(([value,label])=>`<option value="${e(value)}">${e(label)}</option>`).join('');if(items.some(x=>x[0]===saved))node.value=saved}
  function moduleChips(item){return (item.modules||[]).map(key=>{const m=data.modules[key];if(!m)return '';return navigation.has(m.navigation)&&q(m.navigation)?`<button type="button" class="schema-chip" data-schema-nav="${e(m.navigation)}" title="Відкрити модуль без вибору довільного запису">${e(m.label)} ↗</button>`:`<span class="schema-chip passive" title="${e(m.note||'Navigation binding не підтверджено')}">${e(m.label)}</span>`}).join('')||'<span class="muted">Потребує опису</span>'}
  function technical(item){return `<details><summary>SQLite / JSON / evidence</summary><dl class="schema-detail">
    <dt>Використовується в шаблонах</dt><dd>${item.used_in_templates?'Так':'Ні'}</dd>
    ${(item.template_fields||[]).map(f=>`<dt>${e(f.label)}</dt><dd><code>${e(f.key)}</code> · ${e(f.group)} · ${e(f.value_type)}<br>${f.available_for.map(e).join(', ')}${f.source_binding.source_type==='derived'?`<br>Похідне поле: ${e(f.source_binding.description)}<br>${f.source_binding.dependencies.map(e).join(', ')}`:''}</dd>`).join('')}
    <dt>Ідентифікатор</dt><dd>${e(item.id)}</dd><dt>Тип запису</dt><dd>${e(kinds[item.kind])}</dd><dt>Сховище / таблиця / поле</dt><dd>${e(item.database)} / ${e(item.table||'—')} / ${e(item.key)}</dd>
    <dt>Тип структури</dt><dd>${e(item.type||'—')}</dd><dt>Introspection</dt><dd>${e(item.structure_source)}</dd>
    ${item.transformation?`<dt>Базове поле / перетворення / відмінок</dt><dd>${e(item.source_field||item.source)} / ${e(item.transformation.transformation_type||item.transformation.resolver||'—')} / ${e(item.transformation.grammatical_case||'—')}</dd>`:''}
    ${item.kind==='physical'?`<dt>Declared NOT NULL / PK</dt><dd>${item.required?'так':'ні'} / ${item.primary_key?'так':'ні'} (фізичні атрибути, не бізнес-обов’язковість)</dd>`:''}
    ${item.kind==='physical'?`<dt>Declared FK</dt><dd>${(item.foreign_keys||[]).map(f=>e(f.target_table)+'.'+e(f.target_key)+' · ON DELETE '+e(f.on_delete)).join('<br>')||'Не оголошено'}</dd>`:''}
    ${item.json_path?`<dt>JSON path / умова</dt><dd>${e(item.json_path)}</dd>`:''}
    <dt>Групи</dt><dd>${(item.groups||[]).map(e).join(' · ')}</dd><dt>Пошук</dt><dd>${e(item.search_note||'Потребує уточнення')}</dd><dt>Фільтрація / сортування</dt><dd>${e(item.filter_sort_note||'Потребує уточнення')}</dd>
    <dt>Evidence</dt><dd>${(item.evidence||[]).map(x=>e(x.file)+' · '+e(x.symbol)+(x.note?' · '+e(x.note):'')).join('<br>')||'Не описано'}</dd>
    ${item.regulatory?'<dt>Нормативний контекст</dt><dd>'+Object.entries({document:'Документ',clause:'Пункт / підпункт',revision:'Редакція',effective_from:'Чинний з',effective_to:'Чинний до',criterion:'Критерій',source:'Джерело перевірки',result:'Результат'}).map(([key,label])=>e(label)+': '+e(item.regulatory[key]||'потребує погодження')).join('<br>')+'</dd>':''}
    </dl></details>`}
  function draw(){if(!data)return;const search=q('schemaSearch').value.trim().toLocaleLowerCase('uk-UA');const selected=data.items.filter(x=>
    (!q('schemaTemplates').value||Boolean(x.used_in_templates)===(q('schemaTemplates').value==='yes'))&&
    (q('schemaTechnical').checked||!x.technical||x.status==='unapproved')&&(!q('schemaGroup').value||(x.groups||[]).includes(q('schemaGroup').value))&&
    (!q('schemaSource').value||x.source===q('schemaSource').value)&&(!q('schemaModule').value||(x.modules||[]).includes(q('schemaModule').value))&&
    (!q('schemaEditing').value||x.editing===q('schemaEditing').value)&&(!q('schemaStatus').value||x.status===q('schemaStatus').value)&&
    (!search||[x.label,x.description,x.id,x.source,...x.groups].join(' ').toLocaleLowerCase('uk-UA').includes(search)));
    q('schemaCount').textContent=`Показано ${selected.length} із ${data.items.length} описів · SQLite, JSON та обчислювані поля`;
    selected.sort((a,b)=>data.groups.indexOf(a.groups[0])-data.groups.indexOf(b.groups[0]));
    q('schemaRows').innerHTML=selected.map(x=>`<tr><td><strong>${e(x.label)}</strong><small>${e(kinds[x.kind])}</small><span class="schema-state">${e(statuses[x.status]||statuses.unapproved)}</span></td><td>${e(x.description)}${technical(x)}</td><td>${e(x.source)}</td><td>${moduleChips(x)}<small>${e(x.usage_note||'')}</small></td><td><strong>${e(editing[x.editing]||editing.unknown)}</strong><small>${e(x.editing_note||'Не встановлено')}</small></td></tr>`).join('')||'<tr><td colspan="5">За цими умовами полів не знайдено.</td></tr>';
  }
  function drawFlows(){q('schemaFlows').innerHTML=`<div class="schema-legend">${Object.entries(modes).map(([key,label])=>`<span class="schema-flow-badge ${key}">${e(label)}</span>`).join('')}</div><p class="muted">Це карта процесів, а не їхній поточний runtime status. Натискання не запускає sync або перевірку.</p><div class="schema-flow-list">${data.flows.map(f=>`<article class="schema-flow ${e(f.mode)}"><div class="schema-flow-title"><span class="schema-flow-badge ${e(f.mode)}">${e(modes[f.mode])}</span><small>${e(f.evidence)}</small></div><div class="schema-flow-nodes"><strong>${e(f.from)}</strong><span aria-hidden="true">→</span><div>${e(f.via)}</div><span aria-hidden="true">→</span><strong>${e(f.to)}</strong></div><p>${e(f.note)}</p></article>`).join('')}</div>
    <details class="schema-relations"><summary>Зв’язки таблиць · ${data.relationships.length}</summary><p>Суцільна лінія — declared FK. Пунктир — підтверджений логічний зв’язок; не гарантія FK або 1:1.</p>${data.relationships.map(link=>`<div class="schema-relation"><code>${e(link.from)}</code><span class="schema-edge ${link.kind==='logical'?'logical':''}" aria-label="${link.kind==='logical'?'Логічний зв’язок':'Declared FK'}"></span><code>${e(link.to)}</code><small>${e(link.note)}${link.available===false?' · структура endpoint не доступна у поточному сховищі':''}</small></div>`).join('')}</details>`}
  async function load(){const ticket=++requestId;q('schemaNotice').textContent='Завантаження структури…';try{const response=await request('/api/admin/schema');if(ticket!==requestId)return;data=response;
    q('schemaVersion').textContent='Metadata v'+data.version+' · read-only';
    q('schemaNotice').textContent=data.stores.map(s=>`${s.id.toUpperCase()}: ${s.available?s.tables+' таблиць / '+s.fields+' колонок':'недоступно'}`).join(' · ')+' · Попередні описи не є погодженими. '+data.warnings.join(' ')+(data.missing_metadata_fields.length?' У metadata є '+data.missing_metadata_fields.length+' полів, не знайдених у поточній структурі.':'');
    options('schemaGroup',data.groups.map(x=>[x,x]));options('schemaSource',[...new Set(data.items.map(x=>x.source))].sort().map(x=>[x,x]));options('schemaModule',Object.entries(data.modules).map(([k,v])=>[k,v.label]));options('schemaEditing',Object.entries(editing));options('schemaStatus',Object.entries(statuses));draw();drawFlows();
  }catch(error){if(ticket!==requestId)return;data=null;q('schemaRows').innerHTML='';q('schemaFlows').textContent='';q('schemaCount').textContent='';q('schemaNotice').textContent='Не вдалося завантажити схему даних. Перевірте доступ до адміністративного API та повторно відкрийте вкладку.'}}
  q('adminSchemaPanel').addEventListener('click',event=>{const target=event.target.closest('[data-schema-nav]');if(target&&navigation.has(target.dataset.schemaNav))q(target.dataset.schemaNav)?.click();const button=event.target.closest('[data-schema-mode]');if(button){mode=button.dataset.schemaMode;q('schemaFields').hidden=mode!=='fields';q('schemaFlows').hidden=mode!=='flows';q('adminSchemaPanel').querySelectorAll('[data-schema-mode]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.schemaMode===mode)))}});
  ['schemaTemplates','schemaSearch','schemaGroup','schemaSource','schemaModule','schemaEditing','schemaStatus','schemaTechnical'].forEach(id=>q(id).addEventListener('input',draw));
  q('schemaReset').onclick=()=>{['schemaTemplates','schemaSearch','schemaGroup','schemaSource','schemaModule','schemaEditing','schemaStatus'].forEach(id=>q(id).value='');q('schemaTechnical').checked=false;draw()};
  const prior=setAdminTab;setAdminTab=function(name){q('adminSchemaPanel').hidden=name!=='schema';if(name!=='schema')return prior(name);document.querySelectorAll('#administrationView .admin-panel').forEach(p=>p.hidden=p.id!=='adminSchemaPanel');document.querySelectorAll('[data-admin-tab]').forEach(p=>p.classList.toggle('active',p.dataset.adminTab==='schema'));return load()};
  q('schemaTab').onclick=()=>setAdminTab('schema');
})();
