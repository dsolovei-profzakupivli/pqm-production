import {spawn} from 'node:child_process';

const chrome=process.env.PQM_CHROME_EXE;
const appUrl=process.env.PQM_APP_URL||'http://127.0.0.1:8080';
if(!chrome)throw new Error('PQM_CHROME_EXE is required');
const port=9246,profile=`${process.env.TEMP||'.'}\\pqm-violation-context-${Date.now()}`;
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
  let sequence=0;const pending=new Map(),exceptions=[],consoleErrors=[],mutations=[];
  socket.onmessage=event=>{
    const message=JSON.parse(event.data);
    if(message.id){const waiter=pending.get(message.id);pending.delete(message.id);message.error?waiter.reject(new Error(message.error.message)):waiter.resolve(message.result);return}
    if(message.method==='Runtime.exceptionThrown')exceptions.push(message.params.exceptionDetails.text);
    if(message.method==='Runtime.consoleAPICalled'&&message.params.type==='error')consoleErrors.push(message.params.args.map(arg=>arg.value||arg.description||'').join(' '));
    if(message.method==='Network.requestWillBeSent'&&!['GET','HEAD','OPTIONS'].includes(message.params.request.method))mutations.push(`${message.params.request.method} ${message.params.request.url}`);
  };
  const send=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence;pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}))});
  const evaluate=async expression=>(await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true})).result.value;
  await send('Runtime.enable');await send('Network.enable');await send('Page.enable');
  for(let i=0;i<150;i++){if(await evaluate(`document.readyState==='complete'&&typeof openViolationReportById==='function'`))break;await sleep(100)}
  const result=await evaluate(`(async()=>{
    document.querySelector('#roleSelect').value='admin';
    await openViolationReportById('UA-D-2026-09-01-000003');
    const item=await request('/api/violation-reports/UA-D-2026-09-01-000003');
    const json=await request('/api/violation-reports/UA-D-2026-09-01-000003/sheets-json');
    const section=document.querySelector('.violation-readonly-review');
    const heading=[...section.querySelectorAll('h4')].find(node=>node.textContent.trim()==='Збережений контекст рішення');
    const values=Object.fromEntries([...heading.nextElementSibling.children].map(node=>[
      node.querySelector('small')?.textContent.trim()||'',node.querySelector('strong')?.textContent.trim()||''
    ]));
    return {source:item.decision_context_source,values,json:{cpv:json.cpv,winner_selected_at:json.winner_selected_at,rejection_at:json.rejection_at,rejection_reason:json.rejection_reason}};
  })()`);
  const expected={
    'Код ДК / CPV':'44110000-4 — Конструкційні матеріали',
    'Дата визначення переможцем':'21.08.2026',
    'Дата відхилення':'01.09.2026',
  };
  const bad=result.source!=='case_scoped_resolver'
    ||Object.entries(expected).some(([key,value])=>result.values[key]!==value)
    ||result.values['Підстава відхилення']!==result.json.rejection_reason
    ||result.values['Код ДК / CPV']!==result.json.cpv
    ||result.values['Дата визначення переможцем']!==result.json.winner_selected_at
    ||result.values['Дата відхилення']!==result.json.rejection_at
    ||exceptions.length||consoleErrors.length||mutations.length;
  const output={...result,exceptions,consoleErrors,mutations};
  if(bad)throw new Error(JSON.stringify(output));
  console.log(JSON.stringify(output,null,2));
}finally{
  try{socket?.close()}catch{}
  child.kill();
}
