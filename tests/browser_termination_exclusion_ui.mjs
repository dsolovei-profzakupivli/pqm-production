import {spawn} from 'node:child_process';
import path from 'node:path';
import {rm} from 'node:fs/promises';

const chrome=process.env.PQM_CHROME_EXE;
if(!chrome)throw new Error('PQM_CHROME_EXE is required');
const appUrl=process.env.PQM_APP_URL||'http://127.0.0.1:8098';
const port=9254,profile=path.join(process.cwd(),'tmp',`termination-browser-${Date.now()}`);
const child=spawn(chrome,['--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--no-first-run',
  `--remote-debugging-port=${port}`,`--user-data-dir=${profile}`,appUrl],{stdio:'ignore'});
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));let socket;
try{
 let target;for(let i=0;i<100&&!target;i++){try{target=(await(await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find(x=>x.type==='page')}catch{}await sleep(100)}
 if(!target)throw new Error('Chrome target unavailable');
 socket=new WebSocket(target.webSocketDebuggerUrl);await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject});
 let sequence=0;const pending=new Map(),exceptions=[],consoleErrors=[];
 socket.onmessage=event=>{const message=JSON.parse(event.data);if(message.id){const waiter=pending.get(message.id);pending.delete(message.id);message.error?waiter.reject(new Error(message.error.message)):waiter.resolve(message.result);return}if(message.method==='Runtime.exceptionThrown')exceptions.push(message.params.exceptionDetails.text);if(message.method==='Runtime.consoleAPICalled'&&message.params.type==='error')consoleErrors.push(message.params.args.map(x=>x.value||x.description||'').join(' '))};
 const send=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence;pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}))});
 const evaluate=async expression=>(await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true})).result.value;
 await send('Runtime.enable');await send('Page.enable');
 for(let i=0;i<120;i++){if(await evaluate(`document.readyState==='complete'&&typeof showModule==='function'`))break;await sleep(100)}
 await evaluate(`localStorage.setItem('pqm.local.role.v1','admin');document.querySelector('#roleSelect').value='admin';showModule('edrMonitoring');loadEdrMonitoring()`);await sleep(800);
 const candidate=await evaluate(`(()=>{const row=document.querySelector('[data-edr-code="1234567890"]');return{exists:!!row,status:row?.querySelector('[data-edr-column="edr_status"]')?.textContent.trim(),prozorro:row?.querySelector('[data-edr-column="prozorro_status"]')?.textContent.trim()}})()`);
 if(!candidate.exists||candidate.status!=='Припинено'||candidate.prozorro!=='Активний')throw new Error('Eligible fixture is not projected canonically');
 await evaluate(`(()=>{const input=document.querySelector('[data-edr-code="1234567890"] .edr-monitoring-check');input.click();document.querySelector('#edrMonitoringCreateTermination').click()})()`);await sleep(500);
 const preview=await evaluate(`document.querySelector('#terminationExclusionPreview').innerText`);
 if(!preview.includes('Буде створено задач')||!preview.includes('Відповідають умовам')||!preview.toLocaleLowerCase('uk-UA').includes('тестова'))throw new Error('Confirmation preview is incomplete: '+JSON.stringify(preview));
 await evaluate(`document.querySelector('#terminationExclusionConfirm').click()`);await sleep(700);
 const tasks=await(await fetch(`${appUrl}/api/operational-tasks?type=termination_exclusion&status_group=active`)).json();
 if(tasks.total!==1)throw new Error(`Expected one task, got ${tasks.total}`);
 const taskId=tasks.items[0].id;
 await evaluate(`(async()=>{showModule('operationalTasks');await openOperationalTask(${JSON.stringify(taskId)})})()`);await sleep(500);
 const card=await evaluate(`(()=>{const body=document.querySelector('#operationalTaskBody');return{title:document.querySelector('#operationalTaskTitle').textContent.trim(),text:body.innerText,decisions:body.querySelectorAll('[data-termination-decision]').length,protocol:!!body.querySelector('[data-termination-protocol-number]'),disabledGeneration:body.querySelector('.protocol-decision-section button')?.disabled,payloadBoundary:body.innerText.includes('Canonical шаблон termination_exclusion_protocol ще не зареєстрований')}})()`);
 if(card.title!=='Припинення · виключення'||!card.text.includes('Відомості про припинення')||!card.text.includes('Запис про припинення № 10')||card.decisions!==1||!card.protocol||!card.disabledGeneration||!card.payloadBoundary)throw new Error('Termination task card acceptance failed');
 const terminal=await evaluate(`(()=>{const clone=structuredClone(activeOperationalTask);clone.status='completed';const host=document.createElement('div');host.innerHTML=operationalTerminationHtml(clone);return{disabled:[...host.querySelectorAll('input,select,button')].every(x=>x.disabled),obsolete:host.innerText.includes('задачу можна готувати до документа')}})()`);
 if(!terminal.disabled||terminal.obsolete)throw new Error('Completed-state presentation failed');
 const duplicate=await(await fetch(`${appUrl}/api/edr-monitoring/termination-exclusions/preview`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({supplier_codes:['1234567890']})})).json();
 if(duplicate.to_create!==0||duplicate.items[0].reason!=='active_duplicate')throw new Error('Duplicate protection browser/API acceptance failed');
 console.log(JSON.stringify({candidate,preview,taskId,card,terminal,duplicate:{to_create:duplicate.to_create,reason:duplicate.items[0].reason},consoleErrors,exceptions},null,2));
 if(consoleErrors.length||exceptions.length)throw new Error('Browser acceptance produced console errors');
}finally{
 try{socket?.close()}catch{}
 const exited=new Promise(resolve=>child.once('exit',resolve));child.kill();await Promise.race([exited,sleep(3000)]);
 await rm(profile,{recursive:true,force:true}).catch(()=>{});
}
