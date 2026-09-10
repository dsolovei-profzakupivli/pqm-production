/* Stage 1 admin-only document API browser; no runtime renderer changes. */
(() => {
  const q=id=>document.getElementById(id), e=x=>esc(String(x??''));
  let catalog=null,loadVersion=0;
  const cases={nominative:'Називний',genitive:'Родовий',dative:'Давальний',accusative:'Знахідний',instrumental:'Орудний',locative:'Місцевий',vocative:'Кличний'};
  function editor(field=null){
    q('derivedFieldEditor')?.remove();
    const b=field?.source_binding||{};
    const sources=catalog.items.filter(f=>f.key!==field?.key&&f.value_type==='string'&&f.active&&!f.deprecated&&f.binding_status==='VALID');
    q('templateFieldRows').insertAdjacentHTML('beforebegin',`<form id="derivedFieldEditor" class="card"><h3>${field?'Редагувати':'Додати'} похідне поле</h3>
      <label>Базове поле<select name="source_field" required>${sources.map(f=>`<option value="${e(f.key)}" ${f.key===b.source_field?'selected':''}>${e(f.label)} · ${e(f.key)}</option>`).join('')}</select></label>
      <label>Перетворення<select name="transformation_type">${Object.entries(catalog.transformations).map(([key,t])=>`<option value="${e(key)}" ${key===b.transformation_type?'selected':''}>${e(t.label)}</option>`).join('')}</select></label>
      <label data-prefix>Поле умови<select name="condition_field">${catalog.items.filter(f=>f.value_type==='enum'&&f.enum_values?.length&&f.binding_status==='VALID'&&f.active&&!f.deprecated).map(f=>`<option value="${e(f.key)}" ${f.key===b.condition_field?'selected':''}>${e(f.label)} · ${e(f.key)}</option>`).join('')}</select></label>
      <label data-prefix>Дорівнює<select name="equals"></select></label>
      <label data-prefix>Префікс (пробіли зберігаються)<input name="prefix" maxlength="200" value="${e(b.prefix||'')}"></label>
      <label>Відмінок<select name="grammatical_case">${Object.entries(cases).map(([key,label])=>`<option value="${key}" ${key===(b.grammatical_case||'genitive')?'selected':''}>${label}</option>`).join('')}</select></label>
      <label>Що відмінюємо<select name="entity_type">${Object.entries({person:'ПІБ фізичної особи',legal_entity:'Назва юридичної особи',fop:'Назва ФОП',other:'Інше (ручний override)'}).map(([key,label])=>`<option value="${key}" ${key===(b.entity_type||'person')?'selected':''}>${label}</option>`).join('')}</select></label>
      <label>Назва поля<input name="label" required maxlength="200" value="${e(field?.label||'')}"></label>
      <label>Стабільний ключ<input name="key" required ${field?'readonly':''} placeholder="manager.full_name_genitive" value="${e(field?.key||'')}"></label>
      <fieldset><legend>Доступне для документів</legend>${catalog.document_types.map(t=>`<label><input type="checkbox" name="available_for" value="${e(t)}" ${field?.available_for.includes(t)?'checked':''}>${e(t)}</label>`).join('')}</fieldset>
      <p>Називний зберігає вихідне значення. Родовий і знахідний використовують погоджені правила та overrides; давальний — override. Орудний, місцевий і кличний поки повертають помилку: автоматичних правил немає. Невизначена форма блокує генерацію, без fallback.</p>
      <p id="derivedFieldError" role="alert"></p><button type="submit">Зберегти поле</button> <button type="button" data-derived-cancel>Скасувати</button></form>`);
    const form=q('derivedFieldEditor');
    const updateLiterals=()=>{const f=catalog.items.find(f=>f.key===form.elements.condition_field.value);form.elements.equals.innerHTML=(f?.enum_values||[]).map(v=>`<option value="${e(v)}" ${v===b.equals?'selected':''}>${e(v)}</option>`).join('')};
    const updateTransformation=()=>{const prefix=form.elements.transformation_type.value==='conditional_prefix';form.querySelectorAll('[data-prefix]').forEach(el=>{el.hidden=!prefix;el.querySelector('input,select').disabled=!prefix});['grammatical_case','entity_type'].forEach(n=>{form.elements[n].disabled=prefix;form.elements[n].closest('label').hidden=prefix})};
    form.elements.condition_field.onchange=updateLiterals;form.elements.transformation_type.onchange=updateTransformation;updateLiterals();updateTransformation();
    form.querySelector('[data-derived-cancel]').onclick=()=>form.remove();
    form.onsubmit=async event=>{event.preventDefault();const submit=form.querySelector('[type=submit]');submit.disabled=true;
      try{const values=new FormData(form);const payload=Object.fromEntries(values);payload.available_for=values.getAll('available_for');payload.revision=catalog.revision;payload.mode=field?'update':'create';
        await request('/api/admin/template-fields/derived',{method:'POST',body:JSON.stringify(payload)});await load();toast('Похідне поле збережено');
      }catch(error){q('derivedFieldError').textContent=error.message;submit.disabled=false;}};
    form.scrollIntoView({block:'nearest'});
  }
  function draw(){
    if(!catalog)return;
    const term=q('templateFieldSearch').value.trim().toLocaleLowerCase('uk-UA'),type=q('templateFieldType').value;
    const fields=catalog.items.filter(f=>(!type||f.available_for.includes(type))&&(!term||['label','description','group','key'].some(k=>String(f[k]||'').toLocaleLowerCase('uk-UA').includes(term))));
    q('templateFieldCount').textContent=`Знайдено полів: ${fields.length} · Catalog v${catalog.version}.${catalog.revision}`;
    const groups=[...new Set(fields.map(f=>f.group))];
    q('templateFieldRows').innerHTML=groups.map(g=>`<section><h3>${e(g)}</h3>${fields.filter(f=>f.group===g).map(f=>`<article class="template-field"><div><strong>${e(f.label)}</strong><small><code>{{${e(f.key)}}}</code></small><p>${e(f.description)}</p><small>${e(f.value_type)} · ${f.binding_status==='VALID'?'Джерело підтверджено':e(f.binding_status)}${!f.active?' · Неактивне':''}${f.deprecated?' · Застаріле':''}</small><details><summary>Джерело та доступність</summary><p>${e(f.source_binding.source_type==='derived'?'Похідне поле: '+f.source_binding.description:f.source_binding.schema_field||f.source_binding.description)}</p><small>${e((f.source_binding.dependencies||[]).join(', '))}</small><p>${f.available_for.map(e).join(', ')}</p><p>${f.validation_errors.map(e).join('; ')}</p></details></div><button type="button" class="ghost" data-field-copy="${e(f.key)}" ${f.binding_status!=='VALID'||!f.active||f.deprecated?'disabled':''}>Копіювати</button></article>`).join('')}</section>`).join('')||'<p>Полів за цим пошуком не знайдено.</p>';
  }
  async function load(){
    const version=++loadVersion;
    q('templateCatalogPanel')?.remove();
    const me=await request('/api/auth/me');if(me.role!=='admin')return;
    const [data,templates]=await Promise.all([request('/api/admin/template-fields'),request('/api/admin/templates')]);
    if(version!==loadVersion)return;
    q('templateCatalogPanel')?.remove();catalog=data;
    q('adminTemplatesPanel').insertAdjacentHTML('beforeend',`<section id="templateCatalogPanel" class="card"><h2>Каталог полів шаблонів</h2><p>Знайдіть поле за українською назвою, описом, групою або ключем. Нові документи на цьому етапі не генеруються.</p><div class="schema-filters"><label>Тип документа<select id="templateFieldType"><option value="">Усі типи документів</option>${data.document_types.map(t=>`<option value="${e(t)}">${e(t)}</option>`).join('')}</select></label><label class="schema-search">Пошук поля<input id="templateFieldSearch" placeholder="Наприклад: керівник, дата рішення, попередження…"></label></div><p id="templateFieldCount"></p><div id="templateFieldRows"></div><details><summary>Сумісність чинних шаблонів і metadata</summary>${templates.items.map(t=>`<article class="template-field"><div><strong>${e(t.name)}</strong><p>${e(t.document_type)} · ${e(t.template_key)} · ${e(t.format)} · ${e(t.generation_provider)} · ${t.active?'Активний':'Неактивний'}</p><small>Output pattern / destination: ${e(t.output_name_pattern||'Не налаштовано')} / ${e(t.destination_config||'Не налаштовано')}</small><p>Розпізнані canonical: ${e(t.validation?.recognized?.join(', ')||'—')}</p><p>Legacy (чинний runtime збережено): ${e(t.validation?.legacy?.join(', ')||'—')}</p><p>Невідомі: ${e(t.validation?.unknown?.join(', ')||'—')}</p><p>Недоступні: ${e(t.validation?.unavailable?.join(', ')||'—')}</p><p>Broken bindings: ${e(t.validation?.broken_bindings?.join(', ')||'—')}</p></div></article>`).join('')}</details></section>`);
    q('templateCatalogPanel').querySelector('h2').insertAdjacentHTML('afterend','<button type="button" id="addDerivedField">Додати похідне поле</button><div id="derivedFieldActions"></div>');
    q('addDerivedField').onclick=()=>editor();
    q('derivedFieldActions').innerHTML=catalog.items.filter(f=>f.source_binding.transformation_type).map(f=>`<button type="button" class="ghost" data-derived-edit="${e(f.key)}">Редагувати: ${e(f.label)}</button>`).join('');
    q('derivedFieldActions').onclick=event=>{const button=event.target.closest('[data-derived-edit]');if(button)editor(catalog.items.find(f=>f.key===button.dataset.derivedEdit))};
    q('templateFieldSearch').oninput=draw;q('templateFieldType').onchange=draw;
    q('templateFieldRows').onclick=event=>{const b=event.target.closest('[data-field-copy]');if(b&&!b.disabled)copyText('{{'+b.dataset.fieldCopy+'}}')};draw();
  }
  const prior=loadAdminTemplates;loadAdminTemplates=async function(){await prior();try{await load()}catch(error){toast(error.message)}};
  const priorCapabilities=applyRoleCapabilities;applyRoleCapabilities=function(me){priorCapabilities(me);if(me.role!=='admin'){loadVersion++;q('templateCatalogPanel')?.remove();catalog=null}};
})();
