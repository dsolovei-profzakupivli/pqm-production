import {spawn} from 'node:child_process';

const chrome=process.env.PQM_CHROME_EXE;
if(!chrome)throw new Error('PQM_CHROME_EXE is required');
const url=process.env.PQM_APP_URL||'http://127.0.0.1:8080';
const port=9241;
const child=spawn(chrome,['--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--no-first-run','--no-default-browser-check','--window-size=1440,1000',`--remote-debugging-port=${port}`,`--user-data-dir=${process.env.TEMP}\\pqm-bids-observability-${Date.now()}`,url],{stdio:'ignore'});
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
    if(message.method==='Runtime.exceptionThrown')exceptions.push(message.params.exceptionDetails.text);
    if(message.method==='Runtime.consoleAPICalled'&&message.params.type==='error')consoleErrors.push(message.params.args.map(arg=>arg.value||arg.description||'').join(' '));
    if(message.method==='Network.requestWillBeSent'&&!['GET','HEAD','OPTIONS'].includes(message.params.request.method))mutations.push(`${message.params.request.method} ${message.params.request.url}`);
  };
  const send=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence;pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}))});
  const evaluate=async expression=>(await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true})).result.value;
  await send('Runtime.enable');await send('Network.enable');await send('Page.enable');
  for(let i=0;i<120;i++){if(await evaluate(`document.readyState==='complete'&&typeof setAdminTab==='function'`))break;await sleep(100)}
  await evaluate(`localStorage.setItem('pqm.local.role.v1','admin');showModule('administration');setAdminTab('sync')`);
  for(let i=0;i<120;i++){if((await evaluate(`document.querySelector('#bidsErrors')?.textContent||''`)).includes('Поточні проблеми'))break;await sleep(250)}
  const inspect=()=>evaluate(`(()=>({
    width:innerWidth,
    overflow:document.documentElement.scrollWidth>innerWidth+1,
    issues:document.querySelector('#bidsErrors')?.textContent,
    history:document.querySelector('#bidsSyncHistory')?.textContent,
    warning:document.querySelector('#bidsSyncWarning')?.textContent,
    warningHidden:document.querySelector('#bidsSyncWarning')?.hidden,
    activeText:document.querySelector('#bidsLiveRun')?.textContent
  }))()`);
  const desktop=await inspect();
  await send('Emulation.setDeviceMetricsOverride',{width:520,height:900,deviceScaleFactor:1,mobile:false});
  const narrow=await inspect();
  if(!desktop.issues.includes('96')||!desktop.history.includes('Історія запусків')||!desktop.warning.includes('не є поточним активним процесом')||desktop.warningHidden||desktop.overflow||narrow.overflow||exceptions.length||consoleErrors.length||mutations.length){
    throw new Error(JSON.stringify({desktop,narrow,exceptions,consoleErrors,mutations}));
  }
  console.log(JSON.stringify({desktop,narrow,exceptions,consoleErrors,mutations},null,2));
}finally{try{socket?.close()}catch{}child.kill()}
