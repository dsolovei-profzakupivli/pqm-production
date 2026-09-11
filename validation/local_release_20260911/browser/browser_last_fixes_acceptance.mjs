import {spawn} from 'node:child_process';
import {mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';

const chrome=process.env.PQM_CHROME_EXE;
const appUrl=process.env.PQM_APP_URL||'http://127.0.0.1:8080';
if(!chrome)throw new Error('PQM_CHROME_EXE is required');
const output=path.join(process.cwd(),'output','browser-acceptance');await mkdir(output,{recursive:true});
const port=9233,profile=path.join(output,`last-fixes-profile-${Date.now()}`);
const child=spawn(chrome,['--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--no-first-run','--no-default-browser-check',`--remote-debugging-port=${port}`,`--user-data-dir=${profile}`,appUrl],{stdio:'ignore'});
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));let socket;
try{
  let target;for(let i=0;i<100&&!target;i++){try{target=(await(await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find(x=>x.type==='page')}catch{}await sleep(100)}
  if(!target)throw new Error('Chrome target unavailable');socket=new WebSocket(target.webSocketDebuggerUrl);await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject});
  let sequence=0;const pending=new Map(),exceptions=[];socket.onmessage=event=>{const m=JSON.parse(event.data);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(new Error(m.error.message)):p.resolve(m.result)}else if(m.method==='Runtime.exceptionThrown')exceptions.push(m.params.exceptionDetails.text)};
  const send=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence;pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}))});
  const evaluate=async expression=>(await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true})).result.value;
  await send('Runtime.enable');await send('Page.enable');for(let i=0;i<120;i++){if(await evaluate(`document.readyState==='complete'&&typeof openOperationalTask==='function'`))break;await sleep(100)}

  await evaluate(`openOperationalTask('afd80553bd8748ada1526a54e1f4fbde')`);for(let i=0;i<100;i++){if(await evaluate(`document.querySelector('[data-result="refuted"]')?.textContent==='Спростовано'`))break;await sleep(100)}
  const action=await evaluate(`document.querySelector('[data-result="refuted"]')?.textContent`);
  await evaluate(`document.querySelector('#operationalTaskDialog')?.close();openOperationalTask('9880c9022bca437dac0ffc3162bd05e8')`);for(let i=0;i<100;i++){if(await evaluate(`document.querySelector('#operationalTaskBody .operational-summary-actions strong')?.textContent.includes('Спростовано')`))break;await sleep(100)}
  const factual=await evaluate(`(()=>({summary:document.querySelector('#operationalTaskBody .operational-summary-actions strong')?.textContent,history:[...document.querySelectorAll('#operationalTaskBody .operational-history strong')].map(x=>x.textContent)}))()`);

  await evaluate(`document.querySelector('#operationalTaskDialog')?.close();showModule('frameworks');document.querySelector('#frameworksSearch').value='UA-F-2026-09-10-000001';frameworkPage=1;loadFrameworkAnalytics()`);for(let i=0;i<120;i++){if(await evaluate(`document.querySelector('#frameworksBody tr')?.textContent.includes('UA-F-2026-09-10-000001')`))break;await sleep(100)}
  const framework=await evaluate(`(()=>{const row=document.querySelector('#frameworksBody tr');return{total:document.querySelector('#frameworksTotal').textContent,text:row?.textContent,status:row?.querySelector('.framework-status')?.textContent,pending:row?.classList.contains('framework-agreement-pending')}})()`);
  await send('Page.captureScreenshot',{format:'png',fromSurface:true}).then(result=>writeFile(path.join(output,'framework-ua-f-2026-09-10.png'),Buffer.from(result.data,'base64')));
  const result={action,factual,framework,exceptions};
  if(action!=='Спростовано'||factual.summary!=='НАЗК · Спростовано'||!factual.history.includes('НАЗК · Спростовано')||framework.total!=='1'||framework.status!=='Активний'||!framework.text.includes('39540000-9')||exceptions.length)throw new Error(JSON.stringify(result));
  console.log(JSON.stringify({...result,screenshot:'framework-ua-f-2026-09-10.png'},null,2));
}finally{try{socket?.close()}catch{}child.kill()}
