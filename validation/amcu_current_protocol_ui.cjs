// Executes real table/card renderers offline. No HTTP, imports, sync or writes.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('app.js','utf8');
const item=JSON.parse(fs.readFileSync(0,'utf8'));
const context={esc:x=>String(x??''),displayDateOnly:x=>String(x??''),
 operationalSummaryLink:(url,text)=>`<a href="${url}">${text}</a>`,
 resolvedDocumentMetadataHtml:()=>'',documentDeclensionAction:()=>'',
 operationalActionIcon:()=>'',operationalQualificationsHtml:()=>'',operationalTerminationHtml:()=>''};
vm.createContext(context);
for(const name of ['operationalDecisionHtml','operationalAmcuHtml']){
 const start=source.indexOf('function '+name+'(');assert(start>=0);
 const tail=source.slice(start),end=tail.slice(1).search(/\n(?:async )?function /);
 vm.runInContext(end<0?tail:tail.slice(0,end+1),context);
}
const table=context.operationalDecisionHtml(item),card=context.operationalAmcuHtml(item);
const main=card.split('<details>')[0],history=card.slice(main.length);
const current=item.officer_decision.documents,all=item.document_generation.documents;
for(const doc of current){assert(table.includes(doc.download_url));assert(table.includes(doc.pdf_url));}
for(const doc of all){
 assert.equal(table.includes(doc.download_url),current.some(d=>d.id===doc.id));
 assert.equal(table.includes(doc.pdf_url),current.some(d=>d.id===doc.id));
 assert.equal(main.includes(doc.download_url),doc.id===all[0]?.id);
 assert.equal(history.includes(doc.download_url),doc.id!==all[0]?.id);
}
assert.equal((table.match(/<a href=/g)||[]).length,current.length*2);
if(all.length>1)assert(card.includes('Попередні версії · '+(all.length-1)));
console.log('Current table DOCX/PDF and card history: PASS');
