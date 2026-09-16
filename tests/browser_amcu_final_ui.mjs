import {spawn} from 'node:child_process';
import path from 'node:path';
import {rm} from 'node:fs/promises';

const chrome=process.env.PQM_CHROME_EXE;
if(!chrome)throw new Error('PQM_CHROME_EXE is required');
const appUrl=process.env.PQM_APP_URL||'http://127.0.0.1:8080';
const taskId='8d1939e99e094aea92c1a84d75a245e5';
const port=9241,profile=path.join(process.cwd(),'.tmp',`amcu-final-${Date.now()}`);
const child=spawn(chrome,['--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage',
  '--no-first-run','--no-default-browser-check',`--remote-debugging-port=${port}`,
  `--user-data-dir=${profile}`,appUrl],{stdio:'ignore'});
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));let socket;
try{
  let target;for(let i=0;i<100&&!target;i++){try{target=(await(await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find(x=>x.type==='page')}catch{}await sleep(100)}
  if(!target)throw new Error('Chrome target unavailable');
  socket=new WebSocket(target.webSocketDebuggerUrl);await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject});
  let sequence=0;const pending=new Map(),exceptions=[],consoleErrors=[],mutations=[];
  socket.onmessage=event=>{const message=JSON.parse(event.data);if(message.id){const waiter=pending.get(message.id);pending.delete(message.id);message.error?waiter.reject(new Error(message.error.message)):waiter.resolve(message.result);return}if(message.method==='Runtime.exceptionThrown')exceptions.push(message.params.exceptionDetails.text);if(message.method==='Runtime.consoleAPICalled'&&message.params.type==='error')consoleErrors.push(message.params.args.map(x=>x.value||x.description||'').join(' '));if(message.method==='Network.requestWillBeSent'&&!['GET','HEAD','OPTIONS'].includes(message.params.request.method))mutations.push(`${message.params.request.method} ${message.params.request.url}`)};
  const send=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence;pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}))});
  const evaluate=async expression=>(await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true})).result.value;
  await send('Runtime.enable');await send('Network.enable');await send('Page.enable');
  for(let i=0;i<120;i++){if(await evaluate(`document.readyState==='complete'&&typeof openOperationalTask==='function'`))break;await sleep(100)}
  await evaluate(`localStorage.setItem('pqm.local.role.v1','admin');document.querySelector('#roleSelect').value='admin'`);
  await send('Page.reload',{ignoreCache:true});await sleep(1200);
  await evaluate(`(async()=>{showModule('operationalTasks');await openOperationalTask(${JSON.stringify(taskId)})})()`);await sleep(500);
  const inspect=()=>evaluate(`(()=>{const body=document.querySelector('#operationalTaskBody'),save=body.querySelector('.operational-amcu-save'),reviewed=body.querySelector('.operational-amcu-reviewed'),market=body.querySelector('.operational-qualifications .external-link'),row=[...body.querySelectorAll('.operational-qualifications tbody tr')][0],action=body.querySelector('.operational-amcu-action-row'),docx=action?.querySelector('[aria-label="Завантажити DOCX"]'),pdf=action?.querySelector('[aria-label="Завантажити PDF"]'),box=element=>element?{width:element.getBoundingClientRect().width,height:element.getBoundingClientRect().height}:null;return{filename:body.querySelector('.operational-document-identity span')?.textContent.trim(),metadata:body.querySelector('.document-resolved-metadata')?.textContent.trim(),reviewedAction:reviewed?.textContent.trim(),saveTitle:save?.title,saveAria:save?.getAttribute('aria-label'),saveText:save?.textContent.trim(),saveBox:box(save),saveIconBox:box(save?.querySelector('svg')),docxAria:docx?.getAttribute('aria-label'),pdfAria:pdf?.getAttribute('aria-label'),docxBox:box(docx),pdfBox:box(pdf),docxIcon:docx?.querySelector('.operational-file-type')?.textContent,pdfIcon:pdf?.querySelector('.operational-file-type')?.textContent,docxColor:getComputedStyle(docx?.querySelector('svg')).color,pdfColor:getComputedStyle(pdf?.querySelector('svg')).color,qualification:row?.innerText,marketplace:market?.href,marketplaceBox:box(market),marketplaceColor:getComputedStyle(market).color,marketplaceFontSize:getComputedStyle(market).fontSize,actionVisible:Boolean(action),pageOverflow:document.documentElement.scrollWidth>document.documentElement.clientWidth,dialogOverflow:body.scrollWidth>body.clientWidth}})()`);
  const desktop=await inspect();
  const jsonFailureGuard=await evaluate(`(async()=>{const button=document.querySelector('[data-amcu-pdf-url]'),oldFetch=window.fetch,oldCreate=URL.createObjectURL;let objectUrls=0;window.fetch=async()=>new Response(JSON.stringify({error:'Контрольована помилка PDF'}),{status:503,headers:{'Content-Type':'application/json'}});URL.createObjectURL=()=>{objectUrls++;return'blob:test'};try{await downloadAmcuProtocolPdf(button);return{objectUrls,disabled:button.disabled,busy:button.hasAttribute('aria-busy'),message:[...document.querySelectorAll('#toast .toast span')].at(-1)?.textContent}}finally{window.fetch=oldFetch;URL.createObjectURL=oldCreate}})()`);
  const pdfSuccessGuard=await evaluate(`(async()=>{const button=document.querySelector('[data-amcu-pdf-url]'),oldCreate=URL.createObjectURL,oldClick=HTMLAnchorElement.prototype.click;let objectUrls=0,filename='';URL.createObjectURL=blob=>{objectUrls++;return oldCreate.call(URL,blob)};HTMLAnchorElement.prototype.click=function(){filename=this.download};try{await downloadAmcuProtocolPdf(button);return{objectUrls,filename,disabled:button.disabled,busy:button.hasAttribute('aria-busy')}}finally{URL.createObjectURL=oldCreate;HTMLAnchorElement.prototype.click=oldClick}})()`);
  await send('Emulation.setDeviceMetricsOverride',{width:520,height:900,deviceScaleFactor:1,mobile:false});await sleep(300);
  const narrow=await inspect();
  const result={desktop,narrow,jsonFailureGuard,pdfSuccessGuard,consoleErrors,exceptions,mutations};
  console.log(JSON.stringify(result,null,2));
  if(desktop.filename!=='Протокол № 701 від 15.09.2026 (пп. 7 п. 40).docx')throw new Error('Business filename is not shown');
  if(!desktop.metadata)throw new Error('Persisted document metadata is not shown');
  if(desktop.reviewedAction!=='Позначити як розглянуто')throw new Error('Manual AMKU reviewed transition is unavailable');
  if(desktop.saveTitle!=='Зберегти посилання на витяг'||desktop.saveAria!==desktop.saveTitle||desktop.saveText)throw new Error('Row save icon contract failed');
  if(desktop.docxAria!=='Завантажити DOCX'||desktop.pdfAria!=='Завантажити PDF')throw new Error('Download icon accessibility failed');
  if(desktop.saveBox?.width!==40||desktop.saveBox?.height!==40||desktop.saveIconBox?.width<22)throw new Error('Save icon sizing failed');
  if(desktop.docxBox?.width!==40||desktop.pdfBox?.width!==40||desktop.docxIcon!=='DOCX'||desktop.pdfIcon!=='PDF'||desktop.docxColor===desktop.pdfColor)throw new Error('File type icon contract failed');
  if(!desktop.qualification?.includes('31430000-9')||!desktop.qualification?.includes('Електричні акумулятори')||!desktop.qualification?.includes('UA-F-2020-12-15-000044-a'))throw new Error('Qualification table projection failed');
  const marketplace=new URL(desktop.marketplace);if(!marketplace.pathname.includes('5fd7ec0d0be3b38799cdd43f')||marketplace.searchParams.get('page')!=='1'||marketplace.searchParams.get('contributor_name_or_srn')!=='2884318089')throw new Error('Marketplace destination failed');
  if(desktop.marketplaceBox?.width!==40||desktop.marketplaceBox?.height!==40||Number.parseFloat(desktop.marketplaceFontSize)<22||desktop.marketplaceColor!=='rgb(22, 131, 79)')throw new Error('Marketplace icon visibility failed');
  if(jsonFailureGuard.objectUrls!==0||jsonFailureGuard.disabled||jsonFailureGuard.busy||jsonFailureGuard.message!=='Контрольована помилка PDF')throw new Error('JSON PDF error started or disguised a file download');
  if(pdfSuccessGuard.objectUrls!==1||pdfSuccessGuard.filename!=='Протокол № 701 від 15.09.2026 (пп. 7 п. 40).pdf'||pdfSuccessGuard.disabled||pdfSuccessGuard.busy)throw new Error('Successful PDF response did not produce the business download');
  if(narrow.pageOverflow||narrow.dialogOverflow)throw new Error('Narrow layout overflows');
  if(consoleErrors.length||exceptions.length||mutations.length)throw new Error('Browser smoke produced errors or mutations');
}finally{
  try{socket?.close()}catch{}
  const exited=new Promise(resolve=>child.once('exit',resolve));child.kill();
  await Promise.race([exited,sleep(3000)]);
  for(let attempt=0;attempt<5;attempt++){try{await rm(profile,{recursive:true,force:true});break}catch(error){if(error.code!=='EBUSY'||attempt===4)throw error;await sleep(400)}}
}
