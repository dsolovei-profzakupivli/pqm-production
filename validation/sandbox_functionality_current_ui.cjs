const {extractFunction}=require('./function_test_source.cjs');
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
// Reuse the existing synthetic DOM; old tests and assertions remain unchanged.
let source=fs.readFileSync('validation/queue_statistics_ui.test.cjs','utf8');
source=source.replace("document:{body:makeNode(),addEventListener(){}},", "document:{body:makeNode(),listeners:{},addEventListener(type,fn){(this.listeners[type]??=[]).push(fn)},dispatchEvent(event){for(const fn of this.listeners[event.type]||[])fn(event)}},activeModule:'workQueue',");
const {harness,sample}=new Function('require',source+'\nreturn {harness,sample};')(name=>name==='node:test'?(()=>{}):require(name));
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const counts=h=>h.calls.filter(url=>url.includes('application-statistics')).length;
(async()=>{
 let scenarios=0;
 const h=harness(JSON.parse(JSON.stringify(sample)));
 h.context.window.refreshQueueApplicationStatistics();await tick();assert.equal(counts(h),1);
 const dates=[h.nodes.queueStatisticsFrom.value,h.nodes.queueStatisticsTo.value];
 h.controls[0].value='individual_entrepreneur';h.controls[0].onchange();await tick();
 const before=counts(h);h.context.document.dispatchEvent({type:'pqm:applications-synchronized'});await tick();
 assert.equal(counts(h),before+1);assert(h.calls.at(-1).includes('entity_type=individual_entrepreneur'));assert.deepEqual([h.nodes.queueStatisticsFrom.value,h.nodes.queueStatisticsTo.value],dates);scenarios++;
 h.context.activeModule='applications';const hiddenBefore=counts(h);
 h.context.document.dispatchEvent({type:'pqm:applications-synchronized'});await tick();assert.equal(counts(h),hiddenBefore);
 h.context.activeModule='workQueue';h.context.window.refreshQueueApplicationStatistics();await tick();assert.equal(counts(h),hiddenBefore+1);scenarios++;
 h.context.window.refreshQueueApplicationStatistics();await tick();assert.equal(counts(h),hiddenBefore+1);scenarios++;
 const app=fs.readFileSync('app.js','utf8');const observer=app.match(/let queueStatisticsLastSyncRun='';[\s\S]*?\n}\r?\n/)[0];
 const events=[];const context=vm.createContext({Date,Number,CustomEvent:class{constructor(type,options){this.type=type;this.detail=options.detail}},document:{dispatchEvent:e=>events.push(e)}});vm.runInContext(observer,context);
 const state={running:false,last_status:'ok',last_started_at:'2026-11-21T12:00:00Z',last_finished_at:'2026-11-21T12:01:00Z',data_changed:true,data_revision:'one'};
 context.observeQueueStatisticsSync(state);context.observeQueueStatisticsSync(state);assert.equal(events.length,1);scenarios++;
 for(const edit of [{running:true},{last_status:'error'},{last_status:'partial'},{data_changed:false},{last_started_at:'invalid'},{last_finished_at:'2026-11-21T11:00:00Z'}])context.observeQueueStatisticsSync({...state,last_finished_at:'2026-11-21T12:02:00Z',...edit});
 assert.equal(events.length,1);scenarios+=6;
 context.observeQueueStatisticsSync({...state,last_finished_at:'2026-11-21T12:03:00Z'});assert.equal(events.length,2);scenarios++;
 assert(!fs.readFileSync('queue_statistics_ui.js','utf8').includes('setInterval('));assert(!fs.readFileSync('queue_statistics_ui.js','utf8').includes('setTimeout('));scenarios++;
 const lockedDefinition=extractFunction(app,'locked');
 const verifyDefinition=extractFunction(app,'verifyDocuments');
 const savedDefinition=extractFunction(app,'openSavedDocumentCheck');
 const nodes={'#rerunDocumentCheckBtn':{},'#documentCheckBody':{},'#documentCheckSubtitle':{},'#documentCheckDialog':{open:true}};
 let role='admin',reads=0,notices=0,renders=0;
 const lockContext=vm.createContext({API:'/api',role:()=>role,activeDocsRow:null,$:key=>nodes[key],toast(){notices++},Date,
   request:async url=>{assert(url.includes('/document-check-result'));reads++;return {counts:{ok:16,warning:1}}},renderDocumentCheck(){renders++}});
 vm.runInContext(lockedDefinition+'\n'+verifyDefinition+'\n'+savedDefinition,lockContext);
 for(const decision of ['Допущено','Відхилено']){
   lockContext.activeDocsRow={id:'locked',decision,documentCheckStatus:'warning'};
   await lockContext.verifyDocuments();assert.equal(reads,0);scenarios++;
 }
 assert.equal(notices,2);
 for(role of ['admin','officer','viewer']){
   await lockContext.openSavedDocumentCheck({id:'locked',decision:'Допущено',documentCheckStatus:'warning'});
   assert.equal(nodes['#rerunDocumentCheckBtn'].disabled,true);scenarios++;
 }
 assert.equal(reads,3);assert.equal(renders,3);
 nodes['#officialSignatureCheck']={};
 await lockContext.openSavedDocumentCheck({id:'never-checked',decision:'Допущено',participant:'Synthetic',edrpou:'00000001'});
 assert(nodes['#documentCheckBody'].innerHTML.includes('Не перевірено'));assert.equal(reads,3);assert.equal(nodes['#officialSignatureCheck'].href,'https://czo.gov.ua/verify');scenarios++;
 role='admin';await lockContext.openSavedDocumentCheck({id:'never-checked-editable',participant:'Synthetic',edrpou:'00000001'});assert(nodes['#documentCheckBody'].innerHTML.includes('Не перевірено'));assert.equal(reads,3);assert.equal(nodes['#rerunDocumentCheckBtn'].disabled,false);scenarios++;
 const docsDefinition=extractFunction(app,'openDocs'),downloadDefinition=extractFunction(app,'documentDownloadLink');
 const makeSelect=()=>({value:'',disabled:false,innerHTML:'',get options(){return [...this.innerHTML.matchAll(/<option /g)]}});
 const docsNodes={'#docsDialog h2':{},'#docsSubtitle':{},'#archiveDownloadBtn':{},'#verifyDocumentsBtn':{},'#docsVerificationBar':{},'#docsSignatureFile':makeSelect(),'#docsMvsFile':makeSelect(),'#docsList':{},'#docsDialog':{toggleAttribute(){},showModal(){}}};
 let selectionWrites=0;
 const docsContext=vm.createContext({API:'/api',role:()=>role,activeDocsRow:null,$:key=>docsNodes[key],esc:value=>String(value),historicalApplicationBadge:()=>'',displayDate:value=>value,PqmApplicationDocuments:require('../application_documents_ui.js'),getDocumentSelection:()=>({0:['signature']}),saveDocumentSelection(){selectionWrites++;throw Error('No automatic selection write')}});
 vm.runInContext(lockedDefinition+'\n'+downloadDefinition+'\n'+docsDefinition,docsContext);
 for(const decision of ['Допущено','Відхилено','']){
   role='admin';const documents=[{id:'sig',url:'https://example.test/sign.p7s',title:'sign.p7s',format:'application/pkcs7-signature'},{id:'pdf',url:'https://example.test/mvs.pdf',title:'Витяг.pdf',format:'application/pdf'}];
   docsContext.openDocs({id:'s',decision,documents,supplierDocuments:documents,participant:'Synthetic'});
   assert.equal(docsNodes['#verifyDocumentsBtn'].disabled,Boolean(decision));
   for(const id of ['#docsSignatureFile','#docsMvsFile'])assert.equal(docsNodes[id].disabled,Boolean(decision));
   assert.equal(docsNodes['#docsSignatureFile'].value,'0');assert.equal(docsNodes['#docsMvsFile'].value,'1');
   assert.equal((docsNodes['#docsList'].innerHTML.match(/class="doc-download"/g)||[]).length,2);
   assert.equal((docsNodes['#docsList'].innerHTML.match(/title="Завантажити файл"/g)||[]).length,2);
   assert.equal(selectionWrites,0);assert.equal(docsNodes['#archiveDownloadBtn'].href,'/api/applications/s/archive');scenarios++;
 }
 assert(fs.readFileSync('index.html','utf8').includes('https://czo.gov.ua/verify'));scenarios++;
 // Extraction itself must preserve multiline declarations and reject truncation.
 const multiline="function example(value){\n const literal=`text } ${value}`;\n return {value,literal};\n}\nfunction next(){}";
 assert.equal(extractFunction(multiline,'example'),multiline.slice(0,multiline.indexOf('\nfunction next')));
 assert.throws(()=>extractFunction('function unfinished(){','unfinished'),/Incomplete/);
 assert.throws(()=>extractFunction('function repeated(){}\nfunction repeated(){}','repeated'),/exactly one/);
 console.log(`Current Sandbox statistics/documents: ${scenarios} scenarios PASS; extraction guards PASS`);
})().catch(error=>{console.error(error);process.exitCode=1});
