import {spawn} from 'node:child_process';
import path from 'node:path';
import {rm} from 'node:fs/promises';

const chrome=process.env.PQM_CHROME_EXE;
if(!chrome)throw new Error('PQM_CHROME_EXE is required');
const appUrl=process.env.PQM_APP_URL||'http://127.0.0.1:8080';
const port=9258,profile=path.join(process.cwd(),'tmp',`task-declension-browser-${Date.now()}`);
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

 await send('Emulation.setDeviceMetricsOverride',{width:1440,height:900,deviceScaleFactor:1,mobile:false});
 const result=await evaluate(`(async()=>{
 showModule('operationalTasks');await loadOperationalTasks();
 const filters=['operationalTaskSearch','operationalTaskType','operationalTaskStatus'].map(id=>document.getElementById(id).value);
 const button=document.querySelector('#operationalTaskDeclension');
 if(!button)throw new Error('Toolbar action missing');
 applyRoleCapabilities({role:'viewer',permissions:{'tasks.read':false}});const denied=button.disabled;
 applyRoleCapabilities({role:'admin',permissions:{'tasks.read':true}});const allowed=!button.disabled;
 await button.onclick();const opened=activeModule==='references'&&referenceTab==='declension'&&!document.querySelector('#referenceDeclension').hidden;
 const loaded=!document.querySelector('#declensionBody').textContent.includes('Завантаження');
 await returnToDeclensionReport();await loadOperationalTasks();
 const returned=activeModule==='operationalTasks',preserved=filters.every((v,i)=>v===document.getElementById(['operationalTaskSearch','operationalTaskType','operationalTaskStatus'][i]).value);
 document.querySelector('#operationalTaskTemplates').click();await setAdminTab('templates');
 const templatesOpened=activeModule==='administration'&&adminTab==='templates'&&!document.querySelector('#adminTemplatesPanel').hidden&&document.querySelector('#administrationNav').classList.contains('nav-active');
 const persisted=localStorage.getItem('pqm.adminTab')==='templates';
 showModule('operationalTasks');showModule('administration');await setAdminTab(adminTab);
 const templatesReturned=adminTab==='templates'&&!document.querySelector('#adminTemplatesPanel').hidden;
 showModule('operationalTasks');
 const b=button.getBoundingClientRect(),toolbar=button.closest('section').getBoundingClientRect();
 return {templatesOpened,persisted,templatesReturned,denied,allowed,opened,loaded,returned,preserved,desktopFits:b.right<=innerWidth&&b.top>=toolbar.top,rows:document.querySelectorAll('#operationalTasksBody tr').length};
 })()`);
 if(!result||Object.entries(result).some(([k,v])=>k!=='rows'&&!v))throw new Error('Task declension browser acceptance failed: '+JSON.stringify(result));
 console.log(JSON.stringify({result,exceptions},null,2));if(exceptions.length)throw new Error('Runtime exceptions');

}finally{
 try{socket?.close()}catch{}
 const exited=new Promise(resolve=>child.once('exit',resolve));child.kill();await Promise.race([exited,sleep(3000)]);
 await rm(profile,{recursive:true,force:true}).catch(()=>{});
}
