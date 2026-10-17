const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('app.js','utf8');
const names=['resolvedDocumentMetadataHtml','operationalResultHtml','operationalBasisHtml','operationalDecisionHtml','operationalAmcuProtocolMetadataHtml','operationalAmcuDecisionCards','operationalTerminalHtml','operationalTaskHumanState','operationalAmcuHtml'];
const context={esc:x=>String(x??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;'),
 displayDateOnly:x=>String(x??''),operationalSummaryLink:(url,text)=>`<a href="${url}">${text}</a>`,
 documentDeclensionAction:()=>'',resolvedDocumentMetadataHtml:()=>'',operationalActionIcon:()=>'',
 operationalQualificationsHtml:()=>'<div id="unchanged-qualifications"></div>',operationalCurrentReason:()=>''};
vm.createContext(context);
for(const name of names){const start=source.indexOf('function '+name+'(');assert(start>=0);
 const tail=source.slice(start),end=tail.slice(1).search(/\n(?:async )?function /);vm.runInContext(end<0?tail:tail.slice(0,end+1),context);}
const docs=[3,2,1].map(version=>({id:'v'+version,version,document_type:'amcu_exclusion_protocol',
 display_filename:'Протокол фактичний '+version+'.docx',download_url:'/documents/v'+version+'/download',pdf_url:'/documents/v'+version+'/pdf'}));
const item={task_type:'amcu_exclusion',status:'completed',resolution_code:'amcu_excluded',
 result_summary:{label:'Виключення підтверджено Prozorro'},basis_items:[{kind:'amcu_decision',number:'ІНШЕ-42',date:'2026-10-12',reference:'https://example.invalid/basis'}],
 officer_decision:{number:'ІНШЕ-91',date:'2026-10-13',documents:[docs[0]]},document_generation:{documents:docs}};
const original=JSON.stringify(item),terminal=context.operationalTerminalHtml(item);
assert(terminal.includes('Підстава')&&terminal.includes('Рішення УО'));
assert(terminal.includes('ІНШЕ-42')&&terminal.includes('ІНШЕ-91'));
assert(!terminal.includes('Виключення підтверджено Prozorro'));
assert.equal(context.operationalTaskHumanState(item),'');
assert.equal(context.operationalResultHtml(item),'Виключення підтверджено Prozorro'); // table/API presentation retained
assert(terminal.includes(docs[0].download_url)&&terminal.includes(docs[0].pdf_url));
assert(!terminal.includes(docs[1].download_url));
assert.equal(JSON.stringify(item),original);
const active=context.operationalAmcuHtml({...item,status:'ready_for_document'});
assert(active.includes('Попередні версії · 2'));
for(const doc of docs)assert(active.includes(doc.download_url));
assert(active.includes('unchanged-qualifications'));
const missing=context.operationalTerminalHtml({task_type:'amcu_exclusion',status:'completed'});
assert(missing.includes('Не зазначено')&&missing.includes('Не сформовано'));
assert(!missing.includes('706')&&!missing.includes('60/171'));
const multi=context.operationalAmcuDecisionCards({...item,officer_decision:{documents:[docs[0],{...docs[0],download_url:'/other/download',pdf_url:'/other/pdf'}]}});
assert(multi.includes('/other/download')&&multi.includes('/documents/v3/download'));
const escaped=context.operationalAmcuDecisionCards({...item,basis_items:[{number:'<script>bad</script>'}]});
assert(escaped.includes('&lt;script>')&&!escaped.includes('<script>'));
const other=context.operationalTerminalHtml({...item,task_type:'nazk_check'});
assert(other.includes('Виключення підтверджено Prozorro')); // no global result suppression
const currentMetadata=[{metadata_key:'subject',label:'Фактична тема',resolved_text:'ТЕКСТ ВЕРСІЇ 3',version:2},
 {metadata_key:'custom_content',label:'Інше змістове поле',resolved_text:'ІНШИЙ ЗБЕРЕЖЕНИЙ ТЕКСТ',version:7}];
docs[0].resolved_metadata=currentMetadata;docs[1].resolved_metadata=[{metadata_key:'subject',label:'Стара тема',resolved_text:'ТЕКСТ ВЕРСІЇ 2'}];
const withMetadata=context.operationalAmcuDecisionCards(item);
assert(withMetadata.includes('Зміст протоколу')&&withMetadata.includes('ТЕКСТ ВЕРСІЇ 3'));
assert(withMetadata.includes('Інше змістове поле')&&withMetadata.includes('ІНШИЙ ЗБЕРЕЖЕНИЙ ТЕКСТ'));
assert(withMetadata.includes('data-metadata-key="subject"')&&withMetadata.includes('data-protocol-metadata-document="v3"'));
assert(!withMetadata.includes('ТЕКСТ ВЕРСІЇ 2'));
docs[0].resolved_metadata=[];
const absent=context.operationalAmcuDecisionCards(item);
assert(!absent.includes('Зміст протоколу')&&!absent.includes('ТЕКСТ ВЕРСІЇ 2'));
docs[0].resolved_metadata=[{metadata_key:'subject',resolved_text:'   '}];
assert(!context.operationalAmcuDecisionCards(item).includes('Зміст протоколу'));
console.log('AMCU_CARD_LAYOUT_UNIT=PASS; actual fields, empty/multiple/current/history/immutable/non-AMCU');
