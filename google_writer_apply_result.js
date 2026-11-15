/* Compact Apply status and safe, copyable continuation details. Never retries Apply. */
(function(root){
  'use strict';
  const STORAGE_KEY='pqm.googleWriter.applyResult.v1';
  const doc=root.document;
  const compact=doc?.getElementById('googleWriterApplyCompact');
  const compactStatus=doc?.getElementById('googleWriterApplyCompactStatus');
  const compactHttp=doc?.getElementById('googleWriterApplyCompactHttp');
  const openDetails=doc?.getElementById('googleWriterApplyDetailsOpen');
  const detailsDialog=doc?.getElementById('googleWriterApplyDetailsDialog');
  const detailsBody=doc?.getElementById('googleWriterApplyDetailsBody');
  const copyButton=doc?.getElementById('googleWriterApplyCopy');
  const copyStatus=doc?.getElementById('googleWriterApplyCopyStatus');
  const refresh=doc?.getElementById('googleWriterApplyDiagnosticRefresh');
  const originalRequest=root.request;
  if(typeof originalRequest!=='function')return;
  let continuation=null;
  let state=null;
  const safeCode=value=>{
    if(typeof value!=='string'||value.length>64||/^[0-9a-f]{32,}$/i.test(value))return 'APPLY_RESULT_UNCLASSIFIED';
    if(/^[A-Z][A-Z0-9_]{0,63}$/.test(value))return value;
    if(/^[a-z][a-z0-9_]{0,63}$/.test(value))return value.toUpperCase();
    return 'APPLY_RESULT_UNCLASSIFIED';
  };
  const safeDiagnostic=value=>{
    const allowed=new Set(['UNAVAILABLE','BLOCKED','preview_saved','running','partial','outcome_unknown',
      'failed_safe','complete','closed_unknown','closed_prewrite']);
    const result={status:allowed.has(value?.status)?value.status:'UNAVAILABLE'};
    if(Array.isArray(value?.reason_codes))result.reason_codes=value.reason_codes.map(safeCode);
    if(Number.isInteger(value?.confirmed_append)&&value.confirmed_append>=0)result.confirmed_append=value.confirmed_append;
    if(Number.isInteger(value?.attempted_chunk)&&value.attempted_chunk>=0)result.attempted_chunk=value.attempted_chunk;
    if(value?.checkpoint&&typeof value.checkpoint.present==='boolean')result.checkpoint={
      present:value.checkpoint.present,...(Number.isInteger(value.checkpoint.next_chunk)?{next_chunk:value.checkpoint.next_chunk}:{})};
    if(value?.receipts&&Number.isInteger(value.receipts.verified_count)&&value.receipts.verified_count>=0)
      result.receipts={verified_count:value.receipts.verified_count};
    return result;
  };
  const descriptionFor=code=>({
    APPLY_REQUEST_PENDING:'Запит надіслано; очікується відповідь сервера. Не натискайте Apply повторно.',
    CONTINUATION_PREVIEW_STALE:'Стан таблиці або плану змінився після Preview. Новий запуск не розпочато.',
    CONTINUATION_BINDING_INVALID:'Прив’язки continuation не пройшли перевірку.',
    PREVIEW_BINDING_INVALID:'Збережений Preview не пройшов перевірку.',
    APPLY_CHANNEL_UNAVAILABLE:'Захищений канал недоступний; потрібна перевірка журналу.',
    APPLY_PRECHECK_UNAVAILABLE:'Передзаписна перевірка не завершилася однозначно.',
    APPLY_REQUEST_REJECTED:'Запит відхилено сервером до підтвердженого запуску.',
    APPLY_OUTCOME_UNCONFIRMED:'Сервер не підтвердив, чи запустився новий worker.'
  })[code]||'Сервер відхилив або не підтвердив запуск. Перевірте read-only журнал перед будь-якою наступною дією.';
  function statusLabel(){return state?.level==='success'?'SUCCESS':state?.level==='blocked'?'BLOCKED':'STOP';}
  function save(){try{root.sessionStorage?.setItem(STORAGE_KEY,JSON.stringify(state));}catch{}}
  function diagnosticRows(){
    const d=state?.diagnostic;
    const started=state?.started===true?'так':state?.started===false?'ні':'невідомо';
    const rows=[['Результат Apply',statusLabel()],['HTTP-статус',state?.httpStatus??'невідомий'],
      ['Код відповіді',safeCode(state?.code)],['Безпечний опис',state?.description||descriptionFor(safeCode(state?.code))],
      ['Новий запуск розпочато',started]];
    if(!d||d.status==='UNAVAILABLE'||d.status==='BLOCKED'){
      rows.push(['Стан continuation run','не підтверджено'],['Підтверджені APPEND','не підтверджено'],
        ['attempted_chunk','не підтверджено'],['Checkpoint','не підтверджено'],['Receipts','не підтверджено']);
      if(d?.reason_codes?.length)rows.push(['Причини недоступності',d.reason_codes.join(', ')]);
      return rows;
    }
    rows.push(['Стан continuation run',d.status],
      ['Підтверджені APPEND',Number.isInteger(d.confirmed_append)?d.confirmed_append:'не підтверджено'],
      ['attempted_chunk',Number.isInteger(d.attempted_chunk)?d.attempted_chunk:'не зафіксовано'],
      ['Checkpoint',d.checkpoint?.present===true?`є; наступний chunk ${d.checkpoint.next_chunk}`:'не підтверджено'],
      ['Receipts',Number.isInteger(d.receipts?.verified_count)?d.receipts.verified_count:'не підтверджено']);
    if(d.reason_codes?.length)rows.push(['Причини діагностики',d.reason_codes.join(', ')]);
    return rows;
  }
  function render(){
    if(!state)return;
    if(compact){
      compact.hidden=false;compact.dataset.state=state.level;
      if(compactStatus)compactStatus.textContent=statusLabel();
      if(compactHttp)compactHttp.textContent=`HTTP ${state.httpStatus??'—'}`;
    }
    if(!detailsBody)return;
    detailsBody.replaceChildren();
    for(const [label,value] of diagnosticRows()){
      const item=doc.createElement('dl');item.className='google-writer-apply-detail';
      const term=doc.createElement('dt');term.textContent=label;
      const description=doc.createElement('dd');description.textContent=String(value);
      item.append(term,description);detailsBody.appendChild(item);
    }
  }
  function diagnosticText(){
    return ['PQM Google Writer — результат Apply',...diagnosticRows().map(([label,value])=>`${label}: ${value}`)].join('\n');
  }
  async function copyDiagnostic(){
    if(!state)return;
    const text=diagnosticText();
    try{
      if(root.navigator?.clipboard?.writeText)await root.navigator.clipboard.writeText(text);
      else {
        const textarea=doc.createElement('textarea');textarea.value=text;textarea.setAttribute('readonly','');
        textarea.style.position='fixed';textarea.style.opacity='0';doc.body.appendChild(textarea);textarea.select();
        if(!doc.execCommand('copy'))throw new Error('clipboard unavailable');textarea.remove();
      }
      if(copyStatus)copyStatus.textContent='Безпечну діагностику скопійовано.';
    }catch{if(copyStatus)copyStatus.textContent='Не вдалося скопіювати. Відкрийте деталі й скопіюйте текст вручну.';}
  }
  async function refreshDiagnostic(){
    if(!state?.requestId)return;
    try{
      const result=await originalRequest(`/api/google-writer/continuation-status/${state.requestId}`);
      state.diagnostic=safeDiagnostic(result);save();render();
    }catch{
      state.diagnostic={status:'UNAVAILABLE',reason_codes:['CONTINUATION_STATUS_UNAVAILABLE']};save();render();
    }
  }
  function setResult(next){
    state={version:1,requestId:next.requestId,httpStatus:next.httpStatus??null,code:safeCode(next.code),
      level:next.level,started:next.started===true?true:next.started===false?false:null,
      description:descriptionFor(safeCode(next.code)),diagnostic:null};
    save();render();void refreshDiagnostic();
  }
  try{
    const saved=JSON.parse(root.sessionStorage?.getItem(STORAGE_KEY)||'null');
    if(saved&&saved.version===1&&/^[0-9a-f]{32}$/.test(saved.requestId||'')){
      state={version:1,requestId:saved.requestId,httpStatus:Number.isInteger(saved.httpStatus)?saved.httpStatus:null,
        code:safeCode(saved.code),level:['success','blocked','stop','not_started'].includes(saved.level)?
          (saved.level==='not_started'?'blocked':saved.level):'stop',
        started:saved.started===true?true:saved.started===false?false:null,
        description:descriptionFor(safeCode(saved.code)),
        diagnostic:saved.diagnostic?safeDiagnostic(saved.diagnostic):null};render();void refreshDiagnostic();
    }
  }catch{}
  if(openDetails)openDetails.addEventListener('click',()=>{
    if(detailsDialog?.showModal)detailsDialog.showModal();else if(detailsDialog)detailsDialog.open=true;
  });
  if(refresh)refresh.addEventListener('click',()=>void refreshDiagnostic());
  if(copyButton)copyButton.addEventListener('click',()=>copyDiagnostic());
  root.request=async function(url,options={}){
    const method=String(options.method||'GET').toUpperCase();
    const isPreview=method==='POST'&&String(url).includes('/admin/google-writer/append-continuation-preview');
    const isApply=method==='POST'&&String(url).endsWith('/google-writer/apply');
    let applyPayload=null;
    if(isApply){try{applyPayload=JSON.parse(options.body||'{}');}catch{}}
    const matchingApply=Boolean(isApply&&continuation&&applyPayload?.ticket===continuation.ticket&&
      applyPayload?.confirmed===true);
    if(matchingApply){
      state={version:1,requestId:continuation.requestId,httpStatus:null,code:'APPLY_REQUEST_PENDING',
        level:'stop',started:null,description:descriptionFor('APPLY_REQUEST_PENDING'),diagnostic:null};
      save();render();
    }
    try{
      const result=await originalRequest(url,options);
      if(isPreview&&result?.status==='PREVIEW_READY'&&/^[0-9a-f]{32}$/.test(result.request_id||'')&&typeof result.ticket==='string')
        continuation={requestId:result.request_id,ticket:result.ticket};
      if(matchingApply){
        if(result?.started===true&&result.request_id===continuation.requestId)
          setResult({requestId:continuation.requestId,httpStatus:202,code:'APPLY_STARTED',level:'success',started:true});
        else if(result?.started===false)
          setResult({requestId:continuation.requestId,httpStatus:200,code:safeCode(result.code||result.status),level:'blocked',started:false});
        else setResult({requestId:continuation.requestId,httpStatus:200,code:'APPLY_OUTCOME_UNCONFIRMED',level:'stop'});
      }
      return result;
    }catch(error){
      if(matchingApply){
        const code=safeCode(error?.code||error?.status||'APPLY_OUTCOME_UNCONFIRMED');
        setResult({requestId:continuation.requestId,httpStatus:Number.isInteger(error?.httpStatus)?error.httpStatus:null,
          code,level:error?.started===false?'blocked':'stop',started:error?.started===false?false:null});
      }
      throw error;
    }
  };
  root.PqmGoogleWriterApplyResult={refreshDiagnostic,render,diagnosticText};
})(globalThis);
