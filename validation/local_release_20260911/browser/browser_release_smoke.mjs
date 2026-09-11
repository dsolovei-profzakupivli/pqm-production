import {spawn} from 'node:child_process';
import {mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';

const chrome=process.env.PQM_CHROME_EXE;
const appUrl=process.env.PQM_APP_URL||'http://127.0.0.1:8080';
if(!chrome)throw new Error('PQM_CHROME_EXE is required');
const output=path.join(process.cwd(),'output','release-smoke');await mkdir(output,{recursive:true});
const port=9235,profile=path.join(output,`chrome-${Date.now()}`);
const child=spawn(chrome,['--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--no-first-run','--no-default-browser-check',`--remote-debugging-port=${port}`,`--user-data-dir=${profile}`,appUrl],{stdio:'ignore'});
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));let socket;
try{
  let target;for(let i=0;i<100&&!target;i++){try{target=(await(await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find(item=>item.type==='page')}catch{}await sleep(100)}
  if(!target)throw new Error('Chrome target unavailable');socket=new WebSocket(target.webSocketDebuggerUrl);await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject});
  let sequence=0;const pending=new Map(),exceptions=[],consoleErrors=[],mutations=[];
  socket.onmessage=event=>{const message=JSON.parse(event.data);if(message.id){const waiter=pending.get(message.id);pending.delete(message.id);message.error?waiter.reject(new Error(message.error.message)):waiter.resolve(message.result);return}if(message.method==='Runtime.exceptionThrown')exceptions.push(message.params.exceptionDetails.text);if(message.method==='Runtime.consoleAPICalled'&&message.params.type==='error')consoleErrors.push(message.params.args.map(arg=>arg.value||arg.description||'').join(' '));if(message.method==='Network.requestWillBeSent'&&!['GET','HEAD','OPTIONS'].includes(message.params.request.method))mutations.push(`${message.params.request.method} ${message.params.request.url}`)};
  const send=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence;pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}))});
  const evaluate=async expression=>(await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true})).result.value;
  const ready=async()=>{for(let i=0;i<150;i++){if(await evaluate(`document.readyState==='complete'&&typeof showModule==='function'&&document.querySelectorAll('#mainNav button').length>0`))return;await sleep(100)}throw new Error('Application did not become ready')};
  await send('Runtime.enable');await send('Network.enable');await send('Page.enable');await ready();await sleep(800);
  await evaluate(`localStorage.setItem('pqm.local.role.v1','admin');document.querySelector('#roleSelect').value='admin'`);
  await send('Page.reload',{ignoreCache:true});await ready();await sleep(800);
  const cases=[
    ['workQueue','workQueueView','Робота УО','loadWorkQueue()'],
    ['applications','applicationsView','Реєстр заявок','loadRows()'],
    ['history','historyView','Історія заявок','loadApplicationHistory()'],
    ['suppliers','suppliersView','База постачальників','loadQualifiedSuppliersFiltered()'],
    ['requests','requestsView','Звернення замовників','loadViolationReports()'],
    ['operationalTasks','operationalTasksView','Операційні задачі','loadOperationalTasks()'],
    ['frameworks','frameworkAnalyticsView','Відбори',`(()=>{document.querySelector('#frameworksSearch').value='UA-F-2026-09-10-000001';frameworkPage=1;return loadFrameworkAnalytics()})()`],
  ];
  const desktop=[];
  for(const [module,viewId,label,load] of cases){
    await evaluate(`showModule(${JSON.stringify(module)})`);
    await evaluate(`(async()=>{await (${load})})()`);await sleep(150);
    await evaluate(`showModule(${JSON.stringify(module)})`);
    desktop.push(await evaluate(`(()=>{const view=document.getElementById(${JSON.stringify(viewId)}),nav=document.getElementById(${JSON.stringify(module+'Nav')});return{module,contentVisible:view?.hidden===false,heading:view?.querySelector('h1')?.textContent.trim(),active:nav?.classList.contains('nav-active')===true}})()`.replace('{module,','{module:'+JSON.stringify(module)+',')));
  }
  await evaluate(`(async()=>{showModule('administration');await setAdminTab('templates');await loadAdminTemplates()})()`);await sleep(200);
  const admin=await evaluate(`(()=>({visible:document.querySelector('#administrationView')?.hidden===false,templates:Boolean(document.querySelector('#adminTemplatesContent table')),metadata:Boolean(document.querySelector('#adminDocumentMetadata'))}))()`);
  await send('Page.captureScreenshot',{format:'png',fromSurface:true}).then(result=>writeFile(path.join(output,'desktop-admin-templates.png'),Buffer.from(result.data,'base64')));

  await send('Emulation.setDeviceMetricsOverride',{width:520,height:900,deviceScaleFactor:1,mobile:false});
  const narrow=[];
  for(const [module,viewId,label,load] of cases){
    await evaluate(`showModule(${JSON.stringify(module)})`);
    await evaluate(`(async()=>{await (${load})})()`);await sleep(100);
    await evaluate(`showModule(${JSON.stringify(module)})`);
    narrow.push(await evaluate(`(()=>{const view=document.getElementById(${JSON.stringify(viewId)});return{module:${JSON.stringify(module)},contentVisible:view?.hidden===false,viewport:innerWidth,rootWidth:document.documentElement.scrollWidth,overflow:document.documentElement.scrollWidth>innerWidth+1}})()`));
  }
  await evaluate(`showModule('frameworks')`);await send('Page.captureScreenshot',{format:'png',fromSurface:true}).then(result=>writeFile(path.join(output,'narrow-frameworks.png'),Buffer.from(result.data,'base64')));
  const badDesktop=desktop.filter(item=>!item.contentVisible||!item.active||item.heading!==cases.find(row=>row[0]===item.module)[2]);
  const badNarrow=narrow.filter(item=>!item.contentVisible||item.overflow);
  const result={desktop,admin,narrow,exceptions,consoleErrors,mutations,screenshots:['desktop-admin-templates.png','narrow-frameworks.png']};
  if(badDesktop.length||badNarrow.length||!admin.visible||!admin.templates||!admin.metadata||exceptions.length||consoleErrors.length||mutations.length)throw new Error(JSON.stringify({...result,badDesktop,badNarrow}));
  console.log(JSON.stringify(result,null,2));
}finally{try{socket?.close()}catch{}child.kill()}
