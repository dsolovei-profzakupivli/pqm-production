import {spawn} from 'node:child_process';

const chrome=process.env.PQM_CHROME_EXE;
const appUrl=process.env.PQM_APP_URL||'http://127.0.0.1:8080';
if(!chrome)throw new Error('PQM_CHROME_EXE is required');
const port=9241;
const profile=`${process.env.TEMP||'.'}\\pqm-historical-${Date.now()}`;
const child=spawn(chrome,['--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--no-first-run','--no-default-browser-check',`--remote-debugging-port=${port}`,`--user-data-dir=${profile}`,appUrl],{stdio:'ignore'});
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let socket;
try{
  let target;
  for(let i=0;i<100&&!target;i++){
    try{target=(await(await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find(item=>item.type==='page')}catch{}
    await sleep(100);
  }
  if(!target)throw new Error('Chrome target unavailable');
  socket=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject});
  let sequence=0;
  const pending=new Map(),exceptions=[],consoleErrors=[],mutations=[];
  socket.onmessage=event=>{
    const message=JSON.parse(event.data);
    if(message.id){const waiter=pending.get(message.id);pending.delete(message.id);message.error?waiter.reject(new Error(message.error.message)):waiter.resolve(message.result);return}
    if(message.method==='Runtime.exceptionThrown')exceptions.push({text:message.params.exceptionDetails.text,description:message.params.exceptionDetails.exception?.description||'',url:message.params.exceptionDetails.url||'',line:message.params.exceptionDetails.lineNumber});
    if(message.method==='Runtime.consoleAPICalled'&&message.params.type==='error')consoleErrors.push(message.params.args.map(arg=>arg.value||arg.description||'').join(' '));
    if(message.method==='Network.requestWillBeSent'&&!['GET','HEAD','OPTIONS'].includes(message.params.request.method))mutations.push(`${message.params.request.method} ${message.params.request.url}`);
  };
  const send=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence;pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}))});
  const evaluate=async expression=>(await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true})).result.value;
  await send('Runtime.enable');await send('Network.enable');await send('Page.enable');
  for(let i=0;i<150;i++){if(await evaluate(`document.readyState==='complete'&&typeof loadRows==='function'`))break;await sleep(100)}
  const inspect=async(id,role)=>evaluate(`(async()=>{
    for(const dialog of document.querySelectorAll('dialog[open]'))dialog.close();
    document.querySelector('#roleSelect').value=${JSON.stringify(role)};
    for(const id of ['searchInput','protocolNumberFilter','protocolDecisionFilter','complianceStatusFilter','dateFromFilter','dateToFilter']){
      const control=document.getElementById(id);if(control)control.value='';
    }
    for(const selection of Object.values(filterSelections))selection?.clear?.();
    officerFilter='';categoryFilter='';deepLinkSubmissionId=${JSON.stringify(id)};page=1;await loadRows();
    const contractColumn=profile().columns.find(column=>column.key==='contractDetails');
    if(contractColumn){contractColumn.visible=true;render()}
    const row=document.querySelector('#applicationsTable tbody tr[data-id=${JSON.stringify(id)}]');
    const sourceMarkers=row?.querySelectorAll('.historical-application-marker')||[];
    const sourceMarkerCount=sourceMarkers.length;
    const sourceTooltip=sourceMarkers[0]?.title||'';
    const perFieldMarkers=row?.querySelectorAll('.historical-field-marker')?.length||0;
    const checkbox=row?.querySelector('.row-check');
    if(checkbox){checkbox.checked=true;checkbox.dispatchEvent(new Event('change',{bubbles:true}))}
    const selectionAllowed=selected.has(${JSON.stringify(id)});
    const bulkBlocked=document.querySelector('#bulkBtn')?.disabled===true;
    selected.delete(${JSON.stringify(id)});render();
    const currentRowAfterSelection=document.querySelector('#applicationsTable tbody tr[data-id=${JSON.stringify(id)}]');
    const cell=currentRowAfterSelection?.querySelector('td[data-key="contractDetails"]');
    cell?.click();
    const editor=cell?.querySelector('input,select,textarea'),hasEditor=Boolean(editor);
    if(editor)editor.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
    const currentRow=document.querySelector('#applicationsTable tbody tr[data-id=${JSON.stringify(id)}]');
    currentRow?.querySelector('.paperclip:not(.registry-paperclip)')?.click();
    const cardBadgeCount=document.querySelectorAll('#docsDialog[open] .historical-application-badge').length;
    const cardBadge=document.querySelector('#docsDialog[open] .historical-application-badge')?.textContent.trim()||'';
    document.querySelector('#docsDialog[open]')?.close();
    return {role:${JSON.stringify(role)},id:${JSON.stringify(id)},supplierCode:rows.find(item=>item.id===${JSON.stringify(id)})?.edrpou||'',row:Boolean(row),rowIds:[...document.querySelectorAll('#applicationsTable tbody tr[data-id]')].map(item=>item.dataset.id),historical:row?.classList.contains('historical-read-only')===true,marker:row?.querySelector('.registry-flag.nazk')?.textContent.trim()||'',editor:hasEditor,title:row?.title||'',sourceMarkerCount,sourceTooltip,perFieldMarkers,cardBadgeCount,cardBadge,selectionAllowed,bulkBlocked};
  })()`);
  const pqm=await inspect('bc016ccc192a42d9b221fc33cd7322e5','officer');
  await sleep(500);
  const rejectedOfficer=await inspect('4ddbe43aa4754028a30c486af9885407','officer');
  await sleep(500);
  const rejectedAdmin=await inspect('4ddbe43aa4754028a30c486af9885407','admin');
  await sleep(500);
  const admitted=await inspect('8f7a2cd51cc74830a89d05e3fabe610e','officer');
  await sleep(500);
  const history=await evaluate(`(async()=>{
    for(const dialog of document.querySelectorAll('dialog[open]'))dialog.close();
    document.querySelectorAll('[data-history]').forEach(control=>control.value='');
    document.querySelector('[data-history="code"]').value=${JSON.stringify(rejectedOfficer.supplierCode)};
    historyPage=1;await loadApplicationHistory();
    const tableRows=[...document.querySelectorAll('#historyRows tr')];
    const expected=historyItems.filter(item=>item.historical_read_only).length;
    const rowMarkerCounts=tableRows.map(row=>row.querySelectorAll('.historical-application-marker').length);
    const exact=[...document.querySelectorAll('#historyRows .historical-application-marker')].every(marker=>marker.title==='Історичні дані з MedData');
    const historicalIndex=historyItems.findIndex(item=>item.historical_read_only);
    document.querySelector('[data-history-docs="'+historicalIndex+'"]')?.click();
    const cardBadgeCount=document.querySelectorAll('#docsDialog[open] .historical-application-badge').length;
    const cardBadge=document.querySelector('#docsDialog[open] .historical-application-badge')?.textContent.trim()||'';
    document.querySelector('#docsDialog[open]')?.close();
    return {items:historyItems.length,expected,markers:rowMarkerCounts.reduce((sum,count)=>sum+count,0),maxPerRow:Math.max(0,...rowMarkerCounts),exact,perFieldMarkers:document.querySelectorAll('#historyRows .historical-field-marker').length,cardBadgeCount,cardBadge};
  })()`);
  await send('Emulation.setDeviceMetricsOverride',{width:520,height:900,deviceScaleFactor:1,mobile:false});
  const narrow=await inspect('4ddbe43aa4754028a30c486af9885407','officer');
  const result={rejectedOfficer,rejectedAdmin,admitted,pqm,history,narrow,exceptions,consoleErrors,mutations};
  const historicalPresentation=item=>item.sourceMarkerCount===1&&item.sourceTooltip==='Історичні дані з MedData'&&item.perFieldMarkers===0&&item.cardBadgeCount===1&&item.cardBadge==='Історичні дані з MedData'&&item.selectionAllowed&&item.bulkBlocked;
  const bad=!rejectedOfficer.historical||rejectedOfficer.editor||rejectedOfficer.marker!=='НАЗК · Не актуально'||!historicalPresentation(rejectedOfficer)
    ||!rejectedAdmin.historical||rejectedAdmin.editor||rejectedAdmin.marker!=='НАЗК · Не актуально'||!historicalPresentation(rejectedAdmin)
    ||!admitted.historical||admitted.editor||admitted.marker!=='НАЗК · Спростовано'||!historicalPresentation(admitted)
    ||history.markers!==history.expected||history.maxPerRow>1||!history.exact||history.perFieldMarkers||history.cardBadgeCount!==1||history.cardBadge!=='Історичні дані з MedData'
    ||pqm.historical||!pqm.editor||pqm.sourceMarkerCount||pqm.cardBadgeCount||!narrow.historical||narrow.editor||!historicalPresentation(narrow)
    ||exceptions.length||consoleErrors.length||mutations.length;
  if(bad)throw new Error(JSON.stringify(result));
  console.log(JSON.stringify(result,null,2));
}finally{
  try{socket?.close()}catch{}
  child.kill();
}
