import {spawn} from 'node:child_process';
import {mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';

const chrome=process.env.PQM_CHROME_EXE;
const appUrl=process.env.PQM_APP_URL||'http://127.0.0.1:8080';
if(!chrome)throw new Error('PQM_CHROME_EXE is required');
const output=path.join(process.cwd(),'output','browser-acceptance');
await mkdir(output,{recursive:true});
const port=9234,profile=path.join(output,`navigation-refresh-profile-${Date.now()}`);
const child=spawn(chrome,['--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--no-first-run','--no-default-browser-check',`--remote-debugging-port=${port}`,`--user-data-dir=${profile}`,appUrl],{stdio:'ignore'});
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));let socket;
try{
  let target;for(let i=0;i<100&&!target;i++){try{target=(await(await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find(x=>x.type==='page')}catch{}await sleep(100)}
  if(!target)throw new Error('Chrome target unavailable');
  socket=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject});
  let sequence=0;const pending=new Map(),exceptions=[];
  socket.onmessage=event=>{const message=JSON.parse(event.data);if(message.id){const waiter=pending.get(message.id);pending.delete(message.id);message.error?waiter.reject(new Error(message.error.message)):waiter.resolve(message.result)}else if(message.method==='Runtime.exceptionThrown')exceptions.push(message.params.exceptionDetails.text)};
  const send=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence;pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}))});
  const evaluate=async expression=>(await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true})).result.value;
  const ready=async()=>{for(let i=0;i<150;i++){if(await evaluate(`document.readyState==='complete'&&typeof showModule==='function'&&document.querySelectorAll('#mainNav button').length>0`))return;await sleep(100)}throw new Error('Application did not become ready')};
  await send('Runtime.enable');await send('Page.enable');await ready();

  const modules=[
    ['workQueue','workQueueView','workQueueNav','Робота УО'],
    ['applications','applicationsView','applicationsNav','Реєстр заявок'],
    ['history','historyView','historyNav','Історія заявок'],
    ['suppliers','suppliersView','suppliersNav','База постачальників'],
    ['requests','requestsView','requestsNav','Звернення замовників'],
    ['operationalTasks','operationalTasksView','operationalTasksNav','Операційні задачі'],
    ['frameworks','frameworkAnalyticsView','frameworksNav','Відбори'],
  ];
  const results=[];
  for(const [module,viewId,navId,label] of modules){
    await evaluate(`showModule(${JSON.stringify(module)})`);
    await send('Page.reload',{ignoreCache:true});await ready();
    // Auth and global navigation settings both re-render the navbar asynchronously.
    await sleep(900);
    const state=await evaluate(`(()=>({
      module:${JSON.stringify(module)},
      route:new URL(location.href).searchParams.get('view'),
      contentVisible:document.getElementById(${JSON.stringify(viewId)})?.hidden===false,
      requestedActive:document.getElementById(${JSON.stringify(navId)})?.classList.contains('nav-active')===true,
      active:[...document.querySelectorAll('#mainNav .nav-active')].map(item=>item.id),
      label:document.getElementById(${JSON.stringify(navId)})?.getAttribute('aria-label'),
      title:document.title
    }))()`);
    results.push(state);
    if(state.route!==module||!state.contentVisible||!state.requestedActive||state.active.length!==1||state.active[0]!==navId||state.label!==label)throw new Error(JSON.stringify({failed:state,results,exceptions}));
  }
  await send('Page.captureScreenshot',{format:'png',fromSurface:true}).then(result=>writeFile(path.join(output,'navigation-frameworks-after-refresh.png'),Buffer.from(result.data,'base64')));
  if(exceptions.length)throw new Error(JSON.stringify({results,exceptions}));
  console.log(JSON.stringify({results,exceptions,screenshot:'navigation-frameworks-after-refresh.png'},null,2));
}finally{try{socket?.close()}catch{}child.kill()}
