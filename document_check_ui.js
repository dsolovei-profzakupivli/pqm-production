/* UI-002 presentation only. Preserve supplied statuses and saved totals; no I/O. */
((root,factory)=>{const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.PqmDocumentCheck=api})(globalThis,()=>{
  const layouts={
    signature:[['main_signature',1,1,1],['eds_verification',1,2,1],['signing_time',1,3,1],
      ['code',2,1,1],['organization',2,2,2],['signer_drfo',3,1,1],['signer',3,2,2],
      ['authority',4,1,1],['certificate_issuer',4,2,2]],
    mvs:[['mvs_extract',1,1,1],['mvs_extract_type',1,2,1],['mvs_age',1,3,1],
      ['mvs_person',2,1,3],['mvs_criminal_liability',3,1,1],
      ['mvs_unspent_conviction',3,2,1],['mvs_wanted_status',3,3,1]],
  };
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const category=item=>item.key==='contract_experience'?'experience':String(item.key||'').startsWith('mvs_')?'mvs':'signature';
  const shortLabels={mvs_criminal_liability:'Притягнення',mvs_unspent_conviction:'Судимість',mvs_wanted_status:'Розшук'};
  function categoryStatuses(data){
    const result=Object.fromEntries(Object.entries(data.category_results||{}).map(([key,value])=>[key,value.status||'warning']));
    if(data.document_check_policy_version===2&&data.category_results?.mvs){
      const checks=(data.category_results.mvs.checks||[]).filter(item=>item.key!=='mvs_seal');
      result.mvs=checks.some(c=>c.status==='error')?'error':checks.some(c=>c.status==='warning')?'warning':checks.some(c=>c.status==='ok')?'ok':'neutral';
    }
    const experience=(data.category_results?.experience?.checks||[]).find(item=>item.key==='contract_experience');
    if(experience)result.experience=experience.search_status==='found'?'ok':'neutral';
    return result;
  }
  function displayValue(item,data){
    const signature=data.signature||{},mvs=data.mvs_extract||{},detail=String(item.detail??'');
    if(item.key==='contract_experience')return detail.replace(/^\s*\+\s*[·:]?\s*/,'');
    if(item.key==='eds_verification'&&item.status==='ok')return 'Перевірено';
    if(item.key==='code'&&item.status==='ok')return signature.code||detail.split(/\s+·\s+/)[0];
    if(item.key==='signer'&&item.status==='ok')return signature.signer||detail.split(/\s+·\s+/)[0];
    if(item.key==='organization'&&signature.organization)return signature.organization;
    if(item.key==='mvs_person')return mvs.person_name||detail.replace(/\s+·\s*керівник:.*$/iu,'');
    if(item.key==='mvs_age'){
      if(Number.isInteger(mvs.age_days))return `${mvs.age_days} к.д.`;
      const days=detail.match(/^(-?\d+)\s*к\.д\./);if(days)return `${days[1]} к.д.`;
    }
    const statement=mvs[{mvs_criminal_liability:'criminal_liability',mvs_unspent_conviction:'unspent_conviction',mvs_wanted_status:'wanted_status'}[item.key]];
    if(statement?.found&&typeof statement.value==='string'&&statement.value)return statement.value;
    return detail;
  }
  function field(item,esc,layout,renderBusinessRows,data){
    const status=['ok','warning','error','neutral'].includes(item.status)?item.status:'neutral';
    const experience=item.key==='contract_experience',found=experience&&item.search_status==='found';
    const icon=experience?(found?'+':'−'):status==='ok'?'✓':status==='error'||status==='warning'?'!':'—';
    const style=layout?` style="--check-row:${layout[1]};--check-column:${layout[2]};--check-span:${layout[3]}"`:'';
    return `<article class="document-check-field ${status}${item.informational?' informational':''}" data-check-key="${esc(item.key)}" data-check-status="${status}"${experience?` data-experience-state="${found?'found':'none'}"`:''}${style}><div class="document-check-line"><i class="document-check-indicator" aria-hidden="true">${icon}</i><div class="document-check-text"><strong>${esc(shortLabels[item.key]||item.label||item.key)}</strong><span class="document-check-value" title="${esc(item.detail)}">${esc(displayValue(item,data))}</span></div></div>${renderBusinessRows(item)}</article>`;
  }
  function render(data,{esc=escape,renderBusinessRows=()=>'',layout='b'}={}){
    const checks=Array.isArray(data.checks)?data.checks:[],counts=data.counts||{};
    const status=counts.error?'error':counts.warning?'warning':counts.ok?'ok':'neutral';
    const headline=status==='error'?'Виявлено помилки':status==='warning'?'Є зауваження':status==='ok'?'Перевірки пройдено':'Довідкова інформація';
    const sections=[];
    for(const [name,title] of [['signature','Перевірка КЕП'],['mvs','Перевірка витягу МВС'],['experience','Досвід у Prozorro']]){
      const items=checks.filter(item=>category(item)===name);if(!items.length){if(name!=='experience')sections.push(`<section class="check-section document-check-section" data-result-category="${name}"><h3>${title}</h3><p class="muted">Не перевірено</p></section>`);continue;}
      if(name==='experience'){
        sections.push(`<section class="check-section document-check-section" data-result-category="experience"><h3>${title}</h3><div class="document-check-experience">${items.map(item=>field(item,esc,null,renderBusinessRows,data)).join('')}</div></section>`);continue;
      }
      const layout=layouts[name],known=new Set(layout.map(row=>row[0]));
      const ordered=layout.flatMap(row=>items.filter(item=>item.key===row[0]).map(item=>field(item,esc,row,renderBusinessRows,data))).join('');
      // Unknown/legacy evidence is displayed, never silently dropped or recounted.
      const extra=items.filter(item=>!known.has(item.key));
      const legacyNote=data.document_check_policy_version===2&&extra.some(item=>item.key==='mvs_seal')
        ?'<p class="document-check-legacy-note">Раніше збережена перевірка печатки МВС не входить до підсумку нової перевірки.</p>':'';
      sections.push(`<section class="check-section document-check-section" data-result-category="${name}"><h3>${title}</h3><div class="document-check-grid">${ordered}</div>${extra.length?`<div class="document-check-extra">${legacyNote}${extra.map(item=>field(item,esc,null,renderBusinessRows,data)).join('')}</div>`:''}</section>`);
    }
    return `<div class="document-check-results" data-result-layout="${layout==='b'?'b':'a'}"><div class="check-summary ${status}"><strong>${headline}</strong><span>Успішно <b data-result-count="ok">${esc(counts.ok||0)}</b></span><span>Попередження <b data-result-count="warning">${esc(counts.warning||0)}</b></span><span>Помилки <b data-result-count="error">${esc(counts.error||0)}</b></span></div><div class="check-sections">${sections.join('')}</div>${data.notice?`<div class="check-notice">${esc(data.notice)}</div>`:''}</div>`;
  }
  return{render,layouts,categoryStatuses,displayValue};
});
