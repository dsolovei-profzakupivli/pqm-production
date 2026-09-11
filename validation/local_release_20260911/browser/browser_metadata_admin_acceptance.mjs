import {spawn} from 'node:child_process';
import {mkdir} from 'node:fs/promises';
import path from 'node:path';

const chrome=process.env.PQM_CHROME_EXE;
const appUrl=process.env.PQM_APP_URL||'http://127.0.0.1:8080';
if(!chrome)throw new Error('PQM_CHROME_EXE is required');
const output=path.join(process.cwd(),'output','browser-acceptance');
await mkdir(output,{recursive:true});
const port=9231;
const child=spawn(chrome,['--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check',`--remote-debugging-port=${port}`,`--user-data-dir=${path.join(output,'metadata-chrome-profile')}`,appUrl],{stdio:'ignore'});
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let socket;
try{
  let target;
  for(let i=0;i<80&&!target;i++){try{const list=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();target=list.find(x=>x.type==='page')}catch{}await sleep(100)}
  if(!target)throw new Error('Chrome page target was not created');
  socket=new WebSocket(target.webSocketDebuggerUrl);await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject});
  let sequence=0;const pending=new Map(),exceptions=[];
  socket.onmessage=event=>{const message=JSON.parse(event.data);if(message.id){const entry=pending.get(message.id);pending.delete(message.id);message.error?entry.reject(new Error(message.error.message)):entry.resolve(message.result)}else if(message.method==='Runtime.exceptionThrown')exceptions.push(message.params.exceptionDetails.text)};
  const send=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence;pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}))});
  await send('Runtime.enable');await send('Page.enable');
  for(let i=0;i<100;i++){const ready=await send('Runtime.evaluate',{expression:`document.readyState==='complete'&&typeof setAdminTab==='function'`,returnByValue:true});if(ready.result.value)break;await sleep(100)}
  await send('Runtime.evaluate',{expression:`(async()=>{document.querySelector('#roleSelect').value='admin';showModule('administration');await setAdminTab('templates');return true})()`,awaitPromise:true,returnByValue:true});
  for(let i=0;i<80;i++){const ready=await send('Runtime.evaluate',{expression:`document.querySelectorAll('.admin-metadata-item').length>=2`,returnByValue:true});if(ready.result.value)break;await sleep(100)}
  await send('Runtime.evaluate',{expression:`document.querySelector('#adminMetadataAdd').click()`,returnByValue:true});await sleep(500);
  await send('Runtime.evaluate',{expression:`(()=>{const s=document.querySelector('#adminMetadataFieldSearch');s.value='Скорочена назва';s.dispatchEvent(new Event('input',{bubbles:true}));const t=document.querySelector('#adminMetadataTemplate');t.value='Тест ';document.querySelector('#adminMetadataInsert').click();return true})()`,returnByValue:true});
  const desktop=(await send('Runtime.evaluate',{expression:`(()=>({items:document.querySelectorAll('.admin-metadata-item').length,dialog:document.querySelector('#adminMetadataDialog').open,types:document.querySelector('#adminMetadataDocumentType').options.length,inserted:document.querySelector('#adminMetadataTemplate').value,existing:[...document.querySelectorAll('.admin-metadata-item')].some(x=>x.dataset.metadataKey==='askod_short_summary')&&[...document.querySelectorAll('.admin-metadata-item')].some(x=>x.dataset.metadataKey==='protocol_subject')}))()`,returnByValue:true})).result.value;
  await send('Page.captureScreenshot',{format:'png',fromSurface:true}).then(result=>import('node:fs/promises').then(fs=>fs.writeFile(path.join(output,'metadata-admin-desktop.png'),Buffer.from(result.data,'base64'))));
  await send('Emulation.setDeviceMetricsOverride',{width:520,height:900,deviceScaleFactor:1,mobile:false});await sleep(250);
  const narrow=(await send('Runtime.evaluate',{expression:`(()=>{const el=document.querySelector('#adminMetadataDialog'),d=el.getBoundingClientRect(),right=d.right;return{viewport:innerWidth,dialogWidth:Math.round(d.width),overflowPixels:el.scrollWidth-el.clientWidth,offenders:[...el.querySelectorAll('*')].map(x=>({tag:x.tagName,id:x.id,cls:x.className||'',right:Math.round(x.getBoundingClientRect().right-right),sw:x.scrollWidth-x.clientWidth})).filter(x=>x.right>2||x.sw>4).slice(0,8)}})()`,returnByValue:true})).result.value;
  await send('Page.captureScreenshot',{format:'png',fromSurface:true}).then(result=>import('node:fs/promises').then(fs=>fs.writeFile(path.join(output,'metadata-admin-narrow.png'),Buffer.from(result.data,'base64'))));
  if(!desktop.dialog||desktop.types!==2||!desktop.existing||!desktop.inserted.includes('{{supplier.short_name}}')||narrow.overflowPixels>4||exceptions.length)throw new Error(JSON.stringify({desktop,narrow,exceptions}));
  console.log(JSON.stringify({desktop,narrow,exceptions,screenshots:['metadata-admin-desktop.png','metadata-admin-narrow.png']},null,2));
}finally{try{socket?.close()}catch{}child.kill()}
