import {spawn} from 'node:child_process';
import path from 'node:path';
import {rm} from 'node:fs/promises';

const chrome=process.env.PQM_CHROME_EXE;
if(!chrome)throw new Error('PQM_CHROME_EXE is required');
const appUrl=process.env.PQM_APP_URL||'http://127.0.0.1:8080';
const port=9260,profile=path.join(process.cwd(),'tmp',`template-actions-browser-${Date.now()}`);
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
 const docs=[{id:'fixture-doc',version:2,filename:'Fixture.docx',download_url:'/fixture.docx',pdf_url:'/fixture.pdf'},{id:'fixture-old',version:1,filename:'Old.docx',download_url:'/old.docx',pdf_url:'/old.pdf'}];
 const item={id:'fixture-task',task_type:'termination_exclusion',status:'ready_for_document',supplier_code:'2884318089',protocol_number:'TEST',protocol_date:'2026-09-16',supplier_snapshot:{type:'individual_entrepreneur'},termination_evidence:{status:'Припинено',details:'Fixture only'},target_qualifications:[],document_generation:{ready:true,can_manage:true,documents:docs,declensions:[],errors:[]}};
 const panel=document.createElement('div');document.body.append(panel);panel.innerHTML=operationalTerminationHtml(item);installOperationalTerminationDocuments(item,panel);
 const ready=!panel.querySelector('.operational-generate-termination').disabled;
 const docx=panel.querySelector('a[title="Завантажити DOCX"]')?.getAttribute('href')==='/fixture.docx';
 const pdf=!!panel.querySelector('[data-amcu-pdf-url="/fixture.pdf"]')?.onclick;
 const history=panel.querySelector('details')?.textContent.includes('Попередні версії');
 const originalRequest=request,originalOpen=openOperationalTask,originalLoad=loadOperationalTasks;
 let posts=0,returned=0;request=async(url,options)=>{if(options?.method==='POST'&&url.endsWith('/documents/termination-exclusion-protocol'))posts++;else throw new Error('Unexpected fixture request');return {document:docs[0]}};
 openOperationalTask=async()=>{returned++};loadOperationalTasks=async()=>{};
 await panel.querySelector('.operational-generate-termination').onclick();
 request=originalRequest;openOperationalTask=originalOpen;loadOperationalTasks=originalLoad;
 const done=operationalTerminationHtml({...item,status:'completed',document_generation:{...item.document_generation,errors:['obsolete']}});
 const completedClean=!done.includes('obsolete')&&!done.includes('шаблон-кандидат');
 const legal=operationalTerminationHtml({...item,supplier_snapshot:{type:'legal_entity'},document_generation:{...item.document_generation,ready:false}});
 panel.innerHTML=legal;const legalBlocked=panel.querySelector('.operational-generate-termination').disabled;
 const nazk=operationalSupplierDocumentHtml({...item,task_type:'nazk_check'});
 const nazkPdf=nazk.includes('data-amcu-pdf-url="/fixture.pdf"'),nazkDocx=nazk.includes('/fixture.docx');
 panel.remove();return{ready,docx,pdf,history,posts:posts===1,returned:returned===1,completedClean,legalBlocked,nazkPdf,nazkDocx};
 })()`);
 if(!result||Object.values(result).some(v=>!v))throw new Error('Document actions failed: '+JSON.stringify(result));
 console.log(JSON.stringify({result,exceptions},null,2));if(exceptions.length)throw new Error('Runtime exceptions');

}finally{
 try{socket?.close()}catch{}
 const exited=new Promise(resolve=>child.once('exit',resolve));child.kill();await Promise.race([exited,sleep(3000)]);
 await rm(profile,{recursive:true,force:true}).catch(()=>{});
}
