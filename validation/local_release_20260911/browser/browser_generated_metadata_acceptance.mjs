import {spawn} from 'node:child_process';
import {mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';

const chrome=process.env.PQM_CHROME_EXE;
const appUrl=process.env.PQM_APP_URL||'http://127.0.0.1:8080';
if(!chrome)throw new Error('PQM_CHROME_EXE is required');
const output=path.join(process.cwd(),'output','browser-acceptance');
await mkdir(output,{recursive:true});
const port=9232;
const profile=path.join(output,`generated-metadata-chrome-profile-${Date.now()}`);
const child=spawn(chrome,['--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--no-first-run','--no-default-browser-check',`--remote-debugging-port=${port}`,`--user-data-dir=${profile}`,appUrl],{stdio:'ignore'});
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let socket;
try{
  let target;
  for(let i=0;i<100&&!target;i++){try{const list=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();target=list.find(x=>x.type==='page')}catch{}await sleep(100)}
  if(!target)throw new Error('Chrome page target was not created');
  socket=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject});
  let sequence=0;const pending=new Map(),exceptions=[];
  socket.onmessage=event=>{const message=JSON.parse(event.data);if(message.id){const entry=pending.get(message.id);pending.delete(message.id);message.error?entry.reject(new Error(message.error.message)):entry.resolve(message.result)}else if(message.method==='Runtime.exceptionThrown')exceptions.push(message.params.exceptionDetails.text)};
  const send=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence;pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}))});
  const evaluate=async expression=>(await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true})).result.value;
  await send('Runtime.enable');await send('Page.enable');
  for(let i=0;i<120;i++){if(await evaluate(`document.readyState==='complete'&&typeof openOperationalTask==='function'&&typeof openViolationReportById==='function'`))break;await sleep(100)}

  await evaluate(`openOperationalTask('c15da7e3c8de4bc080ea193342dfef09')`);
  for(let i=0;i<100;i++){if(await evaluate(`document.querySelectorAll('#operationalTaskBody .document-resolved-metadata-row').length>0`))break;await sleep(100)}
  const nazk=await evaluate(`(()=>{const row=document.querySelector('#operationalTaskBody .document-resolved-metadata-row');return row&&{key:row.dataset.metadataKey,label:row.querySelector('strong').textContent,text:row.querySelector('span').textContent,button:row.querySelector('button').textContent}})()`);
  await evaluate(`document.querySelector('#operationalTaskBody .document-resolved-metadata-row')?.scrollIntoView({block:'center'})`);await sleep(150);
  await send('Page.captureScreenshot',{format:'png',fromSurface:true}).then(result=>writeFile(path.join(output,'generated-metadata-nazk.png'),Buffer.from(result.data,'base64')));

  await evaluate(`document.querySelector('#operationalTaskDialog')?.close();openViolationReportById('UA-D-2026-09-07-000001')`);
  for(let i=0;i<100;i++){if(await evaluate(`document.querySelectorAll('#requestDetailsBody .document-resolved-metadata-row').length>0`))break;await sleep(100)}
  const protocol=await evaluate(`(()=>{const row=document.querySelector('#requestDetailsBody .document-resolved-metadata-row');window.__copied='';copyText=async text=>{window.__copied=text};row?.querySelector('button')?.click();return row&&{key:row.dataset.metadataKey,label:row.querySelector('strong').textContent,text:row.querySelector('span').textContent,copied:window.__copied}})()`);

  await send('Emulation.setDeviceMetricsOverride',{width:520,height:900,deviceScaleFactor:1,mobile:false});await sleep(250);
  await evaluate(`document.querySelector('#requestDetailsBody .document-resolved-metadata-row')?.scrollIntoView({block:'center'})`);await sleep(150);
  const narrow=await evaluate(`(()=>{const rows=[...document.querySelectorAll('#requestDetailsBody .document-resolved-metadata-row')];return{viewport:innerWidth,rows:rows.length,overflow:rows.map(row=>row.scrollWidth-row.clientWidth),buttonVisible:rows.every(row=>{const b=row.querySelector('button').getBoundingClientRect();return b.left>=0&&b.right<=innerWidth})}})()`);
  await send('Page.captureScreenshot',{format:'png',fromSurface:true}).then(result=>writeFile(path.join(output,'generated-metadata-protocol-520.png'),Buffer.from(result.data,'base64')));

  await send('Emulation.clearDeviceMetricsOverride');
  await evaluate(`document.querySelector('#requestDetailsDialog')?.close();document.querySelector('#roleSelect').value='admin';showModule('administration');setAdminTab('templates')`);
  for(let i=0;i<100;i++){if(await evaluate(`document.querySelectorAll('.admin-metadata-item').length>=2`))break;await sleep(100)}
  const testKey='acceptance_generic_render_20260911';
  let created=false;
  if(!await evaluate(`[...document.querySelectorAll('.admin-metadata-item')].some(x=>x.dataset.metadataKey==='${testKey}')`)){
    await evaluate(`document.querySelector('#adminMetadataAdd').click()`);await sleep(250);
    await evaluate(`(()=>{document.querySelector('#adminMetadataDocumentType').value='nazk_supplier_request';document.querySelector('#adminMetadataDocumentType').dispatchEvent(new Event('change',{bubbles:true}));document.querySelector('#adminMetadataLabel').value='Тест generic rendering';document.querySelector('#adminMetadataKey').value='${testKey}';document.querySelector('#adminMetadataDescription').value='Browser acceptance generic metadata';document.querySelector('#adminMetadataTemplate').value='Тестове значення {{supplier.short_name}}';document.querySelector('#adminMetadataActive').value='1';document.querySelector('#adminMetadataCreateSave').click();return true})()`);
    for(let i=0;i<100;i++){if(await evaluate(`[...document.querySelectorAll('.admin-metadata-item')].some(x=>x.dataset.metadataKey==='${testKey}')`)){created=true;break}await sleep(100)}
  }
  await evaluate(`(()=>{const card=[...document.querySelectorAll('.admin-metadata-item')].find(x=>x.dataset.metadataKey==='${testKey}');card.open=true;card.querySelector('[data-metadata-active]').value='0';card.querySelector('[data-metadata-save]').click();return true})()`);
  for(let i=0;i<100;i++){if(await evaluate(`(()=>{const card=[...document.querySelectorAll('.admin-metadata-item')].find(x=>x.dataset.metadataKey==='${testKey}');return card?.classList.contains('is-inactive')})()`))break;await sleep(100)}
  const admin=await evaluate(`(()=>{const card=[...document.querySelectorAll('.admin-metadata-item')].find(x=>x.dataset.metadataKey==='${testKey}');return{exists:!!card,inactive:card?.classList.contains('is-inactive'),version:card?.querySelector('.admin-metadata-summary-state')?.textContent}})()`);

  const result={nazk,protocol,narrow,admin:{...admin,created},exceptions,screenshots:['generated-metadata-nazk.png','generated-metadata-protocol-520.png']};
  if(nazk?.key!=='askod_short_summary'||!nazk.text||protocol?.key!=='protocol_subject'||protocol.copied!==protocol.text||narrow.rows<1||narrow.overflow.some(value=>value>4)||!narrow.buttonVisible||!admin.exists||!admin.inactive||exceptions.length)throw new Error(JSON.stringify(result));
  console.log(JSON.stringify(result,null,2));
}finally{try{socket?.close()}catch{}child.kill()}
