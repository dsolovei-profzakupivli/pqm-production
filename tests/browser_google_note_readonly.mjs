import {spawn} from 'node:child_process';
import path from 'node:path';
import {rm} from 'node:fs/promises';

const chrome=process.env.PQM_CHROME_EXE;
if(!chrome)throw new Error('PQM_CHROME_EXE is required');
const appUrl=process.env.PQM_APP_URL||'http://127.0.0.1:8080';
const port=9256,profile=path.join(process.cwd(),'tmp',`google-note-browser-${Date.now()}`);
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
 await evaluate(`(()=>{const realRequest=request;request=async(url,options)=>url.includes('/edr-monitoring?')?{items:[{supplier_code:'TEST_NOTE',supplier_name:'Тестовий постачальник',google_note:'Legacy код → РНОКПП\\nДругий рядок <safe>',freshness:'not_checked',prozorro_status:'Ще не в реєстрі'},{supplier_code:'TEST_EMPTY',supplier_name:'Без примітки',google_note:'',freshness:'not_checked',prozorro_status:'Ще не в реєстрі'}],total:2,pages:1,kpis:{not_checked:2},edr_statuses:[]}:realRequest(url,options);showModule('edrMonitoring');return loadEdrMonitoring()})()`);
 const icon=await evaluate(`(()=>{const button=document.querySelector('[data-edr-code="TEST_NOTE"] .edr-supplier-note');return {icons:document.querySelectorAll('#edrMonitoringBody .edr-supplier-note').length,title:button?.title,blankIcon:!!document.querySelector('[data-edr-code="TEST_EMPTY"] .edr-supplier-note')}})()`);
 if(icon.icons!==1||icon.blankIcon||!icon.title.includes('Другий рядок <safe>'))throw new Error('Google note icon/tooltip failed');
 await evaluate(`document.querySelector('[data-edr-code="TEST_NOTE"] .edr-supplier-note').click()`);
 const dialog=await evaluate(`(()=>{const d=document.querySelector('#googleNoteDialog');return{open:d.open,title:d.querySelector('h2').textContent,text:document.querySelector('#googleNoteText').textContent,editable:d.querySelectorAll('textarea,input,[contenteditable="true"]').length,save:d.innerText.includes('Зберегти')}})()`);
 if(!dialog.open||dialog.title!=='Примітка з Google'||!dialog.text.includes('<safe>')||dialog.editable||dialog.save)throw new Error('Read-only Google note dialog failed');
 console.log(JSON.stringify({icon,dialog,exceptions},null,2));
 if(exceptions.length)throw new Error('Browser runtime exception');
}finally{
 try{socket?.close()}catch{}
 const exited=new Promise(resolve=>child.once('exit',resolve));child.kill();await Promise.race([exited,sleep(3000)]);
 await rm(profile,{recursive:true,force:true}).catch(()=>{});
}
