const {test}=require('node:test'),assert=require('node:assert/strict');
const ui=require('../application_documents_ui.js');
const doc=(id,title,format='')=>({id,url:'/files/'+id,title,format});
test('groups use server URL/ID priority, supplier precedence and unique supplier count',()=>{
 const a=doc('a','sign.p7s'),b=doc('b','a.pdf','application/pdf');
 const g=ui.groups({supplierDocuments:[a,a,{},b],decisionDocuments:[a,doc('c','decision.pdf')]});
 assert.deepEqual(g.supplier.map(e=>[e.document.id,e.sourceIndex,e.index]),[['a',0,0],['b',3,1]]);
 assert.deepEqual(g.decision.map(e=>e.document.id),['c']);assert.equal(g.decision[0].index,2);
});
test('candidate indexes are server source indexes, never filtered option positions',()=>{
 const g=ui.groups({supplierDocuments:[doc('z','archive.zip','application/zip'),{},doc('s','sign.p7s'),doc('p','mvs.pdf','application/pdf')]});
 assert.deepEqual(ui.candidates(g,'signature').map(e=>[e.sourceIndex,e.index]),[[2,1]]);
 assert.deepEqual(ui.candidates(g,'mvs').map(e=>[e.sourceIndex,e.index]),[[3,2]]);
 assert.deepEqual(ui.selection(g,{signature:'1',mvs:'2'}),{'1':['signature'],'2':['mvs']});
});
test('only supplier sign.p7s is eligible; unrelated signatures and decision files excluded',()=>{
 const g=ui.groups({supplierDocuments:[doc('x','other.p7s'),doc('s',' SIGN.P7S '),doc('z','sign.p7s','application/zip')],decisionDocuments:[doc('d','sign.p7s')]});
 assert.deepEqual(ui.candidates(g,'signature').map(e=>e.document.id),['s']);
});
test('PDF detection rejects archives and explicit conflicting formats',()=>{
 const g=ui.groups({supplierDocuments:[doc('a','a.PDF'),doc('b','b','application/pdf'),doc('c','c.pdf','application/zip'),doc('d','d.zip','application/pdf'),doc('e','e.pdf','application/msword'),doc('f','f.pdf','application/octet-stream')]});
 assert.deepEqual(ui.candidates(g,'mvs').map(e=>e.document.id),['a','b','f']);
});
test('one file auto-selects, multiple files require manual selection, empty stays empty',()=>{
 const entries=[{index:3},{index:7}];
 assert.equal(ui.initialValue(entries.slice(0,1),{},'signature'),'3');
 assert.equal(ui.initialValue(entries,{},'signature'),'');assert.equal(ui.initialValue([],{},'mvs'),'');
});
test('valid saved manual selection restores; stale or ambiguous storage cannot select a file',()=>{
 const entries=[{index:3},{index:7}];
 assert.equal(ui.initialValue(entries,{'7':['mvs']},'mvs'),'7');
 assert.equal(ui.initialValue(entries,{'8':['mvs']},'mvs'),'');
 assert.equal(ui.initialValue(entries,{'3':['mvs'],'7':['mvs']},'mvs'),'');
 assert.equal(ui.initialValue(entries,{'7':'mvs'},'mvs'),'');
});
test('selection cannot include a decision, archive, stale index or removed MVS seal category',()=>{
 const g=ui.groups({supplierDocuments:[doc('z','z.zip'),doc('p','p.pdf')],decisionDocuments:[doc('d','sign.p7s')]});
 assert.deepEqual(ui.selection(g,{signature:'2',mvs:'0',mvs_signature:'2'}),{});
 assert.deepEqual(ui.selection(g,{signature:'',mvs:'1'}),{'1':['mvs']});
});
test('grouping and automatic selection do not mutate sources or issue requests',()=>{
 const row={supplierDocuments:[doc('s','sign.p7s')]},before=JSON.stringify(row);
 const g=ui.groups(row);ui.initialValue(ui.candidates(g,'signature'),{},'signature');assert.equal(JSON.stringify(row),before);
});
test('document review presence does not change the existing registry row lock',()=>{
 const fs=require('node:fs'),vm=require('node:vm');
 const source=fs.readFileSync(require('node:path').join(__dirname,'../app.js'),'utf8');
 const locked=source.split(/\r?\n/).find(line=>line.startsWith('function locked(row,key)'));
 const context={role:()=> 'admin'};vm.createContext(context);vm.runInContext(locked,context);
 for(const decision of ['Очікує рішення','Очікує розгляду','Допущено','Відхилено'])for(const review of [[],[doc('review','Рішення.pdf')]]){
  const row={decision,decisionDocuments:review};
  assert.equal(context.locked(row,'managerName'),['Допущено','Відхилено'].includes(decision));
 }
});
test('real verification handler rejects locked rows before selection, DOM access or request',async()=>{
 const fs=require('node:fs'),vm=require('node:vm');
 const source=fs.readFileSync(require('node:path').join(__dirname,'../app.js'),'utf8');
 const lines=source.split(/\r?\n/),locked=lines.find(l=>l.startsWith('function locked(row,key)')),verify=lines.find(l=>l.startsWith('async function verifyDocuments(){'));
 for(const decision of ['Допущено','Відхилено'])for(const decisionDocuments of [[],[doc('review','Рішення.pdf')]]){
  let requests=0,notices=0;
  const context={role:()=> 'admin',activeDocsRow:{decision,decisionDocuments},toast:()=>notices++,request:async()=>requests++,$:()=>{throw Error('Locked handler must not reach document selection/DOM')}};
  vm.createContext(context);vm.runInContext(locked+'\n'+verify,context);await context.verifyDocuments();
  assert.equal(requests,0);assert.equal(notices,1);
 }
});
