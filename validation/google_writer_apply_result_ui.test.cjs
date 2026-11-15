'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const source=fs.readFileSync('google_writer_apply_result.js','utf8');
const index=fs.readFileSync('index.html','utf8');
const styles=fs.readFileSync('modules.css','utf8');
const requestId='c1dc13464f0247c5a727204ebf28f8cc';
const ticket='PRIVATE_TICKET_SENTINEL';
const tick=()=>new Promise(resolve=>setTimeout(resolve,0));
const ids=['googleWriterApplyCompact','googleWriterApplyCompactStatus','googleWriterApplyCompactHttp',
  'googleWriterApplyDetailsOpen','googleWriterApplyDetailsDialog','googleWriterApplyDetailsBody',
  'googleWriterApplyCopy','googleWriterApplyCopyStatus','googleWriterApplyDiagnosticRefresh',
  'googleWriterApplyRequestId','googleWriterApplyDiagnosticCheck','googleWriterApplyLookupStatus',
  'googleWriterSavedContinuationAudit','googleWriterSavedContinuationAuditStatus',
  'googleWriterSavedContinuationAuditResult','googleWriterSavedContinuationAuditCopy',
  'googleWriterSavedContinuationAuditCopyStatus','googleWriterApplyReadOnlyClear'];
function harness(applyResult,storage=new Map(),diagnosticResult=null,auditResult=null){
  const calls=[],nodes={},clipboard={text:''};
  const element=()=>({hidden:true,open:false,textContent:'',value:'',children:[],dataset:{},style:{},listeners:{},
    appendChild(node){this.children.push(node);this.textContent=this.children.map(x=>x.textContent).join('\n')},
    append(...items){this.children.push(...items)},replaceChildren(){this.children=[];this.textContent=''},
    addEventListener(type,handler){this.listeners[type]=handler},setAttribute(){},select(){},remove(){},
    showModal(){this.open=true},click(){return this.listeners.click?.()}});
  ids.forEach(id=>nodes[id]=element());
  const app={document:{getElementById:id=>nodes[id]||null,createElement:()=>element(),body:element(),execCommand:()=>true},
    navigator:{clipboard:{writeText:async text=>{clipboard.text=text}}},
    sessionStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value)},
    request:async(url,options={})=>{
      calls.push({url,method:options.method||'GET',body:options.body||''});
      if(url.endsWith('/append-continuation-preview'))return{status:'PREVIEW_READY',request_id:requestId,ticket};
      if(url.endsWith('/google-writer/apply')){
        if(applyResult instanceof Error)throw applyResult;
        return applyResult;
      }
      if(url.startsWith('/api/google-writer/continuation-status/'))return diagnosticResult||{status:'outcome_unknown',request_id:requestId,confirmed_append:25,
        attempted_chunk:1,checkpoint:{present:true,next_chunk:1},receipts:{verified_count:1},read_only:true,
        digest:'D'.repeat(43),ticket:'SHOULD_NOT_ESCAPE'};
      if(url.startsWith('/api/admin/google-writer/saved-continuation-audit/'))return auditResult||{
        status:'VERIFIED',request_id:requestId,reason_codes:[],source:{planned:276,confirmed:25,missing:251,conflict:0,unverified:0},
        preserved:{planned:25,confirmed:25,missing:0,conflict:0,unverified:0},
        continuation:{planned:251,present:0,missing:251,duplicate:0,conflict:0,unverified:0},
        related:{source_run:'closed_unknown',continuation_runs:[],source_chunks:{count:1,states:{outcome_unknown:1},unresolved:1,receipt_count:0},
          continuation_chunks:{count:0,states:{},unresolved:0,receipt_count:0},source_checkpoint:false,
          continuation_checkpoints:0,continuation_verified_receipts:0,additional_saved_previews:0},
        read_only:true,sqlite_writes:0,sheets_writes:0,properties_writes:0,
        preview_created:false,ticket_created:false,writer_started:false,
        digest:'D'.repeat(43),ticket:'DO_NOT_COPY',supplier_name:'PRIVATE'};
      throw Error('Unexpected mocked API call');
    }};
  vm.createContext(app);vm.runInContext(source,app,{filename:'google_writer_apply_result.js'});
  return {app,calls,nodes,storage,clipboard};
}
async function invokeApply(h,applyPayload={ticket,confirmed:true}){
  await h.app.request('/api/admin/google-writer/append-continuation-preview',{method:'POST'});
  try{await h.app.request('/api/google-writer/apply',{method:'POST',body:JSON.stringify(applyPayload)});}catch{}
  await new Promise(resolve=>setTimeout(resolve,0));
}
function detailText(h){return h.nodes.googleWriterApplyDetailsBody.children.map(item=>
  item.children.map(child=>child.textContent).join(': ')).join('\n');}
function savedAuditText(h){return h.nodes.googleWriterSavedContinuationAuditResult.children.map(item=>
  item.children.map(child=>child.textContent).join(': ')).join('\n');}

test('HTTP 409 with started:false is BLOCKED, preserves the exact code, and never retries Apply',async()=>{
  const error=Object.assign(new Error('raw private error'),{httpStatus:409,code:'CONTINUATION_PREVIEW_STALE',
    status:'CONTINUATION_PREVIEW_STALE',started:false,ticket,digest:'D'.repeat(43)});
  const h=harness(error);await invokeApply(h);
  assert.equal(h.nodes.googleWriterApplyCompact.hidden,false);
  assert.equal(h.nodes.googleWriterApplyCompactStatus.textContent,'BLOCKED');
  assert.equal(h.nodes.googleWriterApplyCompactHttp.textContent,'HTTP 409');
  await h.nodes.googleWriterApplyDetailsOpen.click();
  assert.equal(h.nodes.googleWriterApplyDetailsDialog.open,true);
  const text=detailText(h);
  assert.match(text,/HTTP-статус: 409/);assert.match(text,/Код відповіді: CONTINUATION_PREVIEW_STALE/);
  assert.match(text,/Новий запуск розпочато: ні/);
  await h.nodes.googleWriterApplyCopy.click();
  assert.match(h.clipboard.text,/HTTP-статус: 409/);
  assert.match(h.clipboard.text,/Код відповіді: CONTINUATION_PREVIEW_STALE/);
  assert.match(h.clipboard.text,/Новий запуск розпочато: ні/);
  assert.doesNotMatch(h.clipboard.text,/PRIVATE_TICKET_SENTINEL|D{43}|raw private error/);
  assert.equal(h.calls.filter(call=>call.url.endsWith('/google-writer/apply')).length,1);
  assert.equal(h.calls.filter(call=>call.url.startsWith('/api/google-writer/continuation-status/')).length,1);
  assert.doesNotMatch(text,/PRIVATE_TICKET_SENTINEL|D{43}|raw private error|SHOULD_NOT_ESCAPE/);
});

test('unknown HTTP 409 is STOP and exposes only verified journal fields',async()=>{
  const error=Object.assign(new Error('private backend text'),{httpStatus:409,code:'APPLY_OUTCOME_UNCONFIRMED',ticket});
  const h=harness(error);await invokeApply(h);await h.nodes.googleWriterApplyDetailsOpen.click();
  const text=detailText(h);
  assert.equal(h.nodes.googleWriterApplyCompactStatus.textContent,'STOP');
  assert.match(text,/Стан continuation run: outcome_unknown/);
  assert.match(text,/Підтверджені APPEND: 25/);assert.match(text,/attempted_chunk: 1/);
  assert.match(text,/Checkpoint: є; наступний chunk 1/);assert.match(text,/Receipts: 1/);
  assert.match(text,/Новий запуск розпочато: невідомо/);
  assert.equal(h.calls.filter(call=>call.url.endsWith('/google-writer/apply')).length,1);
  assert.doesNotMatch(text,/PRIVATE_TICKET_SENTINEL|private backend text|SHOULD_NOT_ESCAPE|D{43}/);
});

test('confirmed start shows SUCCESS and copy button copies only safe fields',async()=>{
  const h=harness({started:true,request_id:requestId});await invokeApply(h);await h.nodes.googleWriterApplyDetailsOpen.click();
  assert.equal(h.nodes.googleWriterApplyCompactStatus.textContent,'SUCCESS');
  assert.equal(h.nodes.googleWriterApplyCompactHttp.textContent,'HTTP 202');
  await h.nodes.googleWriterApplyCopy.click();
  assert.match(h.clipboard.text,/HTTP-статус: 202/);
  assert.match(h.clipboard.text,/Новий запуск розпочато: так/);
  assert.match(h.clipboard.text,/Підтверджені APPEND: 25/);
  assert.match(h.clipboard.text,/Receipts: 1/);
  assert.doesNotMatch(h.clipboard.text,/PRIVATE_TICKET_SENTINEL|SHOULD_NOT_ESCAPE|D{43}|requestId/);
  assert.match(h.nodes.googleWriterApplyCopyStatus.textContent,/скопійовано/);
});

test('safe result survives a tab reload and does not persist a ticket or digest',async()=>{
  const h=harness({started:true,request_id:requestId});await invokeApply(h);
  const saved=[...h.storage.values()].join('');
  assert.doesNotMatch(saved,/PRIVATE_TICKET_SENTINEL|SHOULD_NOT_ESCAPE|D{43}/);
  const restored=harness({started:false},h.storage);await new Promise(resolve=>setTimeout(resolve,0));
  assert.equal(restored.nodes.googleWriterApplyCompact.hidden,false);
  assert.equal(restored.nodes.googleWriterApplyCompactStatus.textContent,'SUCCESS');
  assert.equal(restored.calls.filter(call=>call.url.endsWith('/google-writer/apply')).length,0);
  assert.equal(restored.calls.filter(call=>call.url.startsWith('/api/google-writer/continuation-status/')).length,1);
});

test('without session result the permanent panel is neutral and details open without API writes',async()=>{
  const h=harness({started:false});
  assert.equal(h.nodes.googleWriterApplyCompact.hidden,false);
  assert.equal(h.nodes.googleWriterApplyCompactStatus.textContent,'Немає результату Apply');
  assert.match(h.nodes.googleWriterApplyCompactHttp.textContent,/ще не перевірявся/);
  await h.nodes.googleWriterApplyDetailsOpen.click();
  assert.equal(h.nodes.googleWriterApplyDetailsDialog.open,true);
  assert.match(detailText(h),/Результат Apply: Немає результату Apply/);
  assert.match(detailText(h),/Новий запуск розпочато: невідомо/);
  assert.equal(h.calls.filter(call=>call.method==='POST').length,0);
});

test('manual read-only check accepts only a formatted request ID and confirms the echoed binding',async()=>{
  const h=harness({started:false});
  h.nodes.googleWriterApplyRequestId.value=requestId;
  await h.nodes.googleWriterApplyDiagnosticCheck.click();await tick();
  assert.equal(h.calls.filter(call=>call.url===`/api/google-writer/continuation-status/${requestId}`&&call.method==='GET').length,1);
  assert.equal(h.calls.filter(call=>call.method==='POST').length,0);
  assert.match(h.nodes.googleWriterApplyLookupStatus.textContent,/підтверджено/);
  assert.equal(h.nodes.googleWriterApplyCompactStatus.textContent,'Немає результату Apply');
  assert.match(h.nodes.googleWriterApplyCompactHttp.textContent,/Стан: outcome_unknown/);
  await h.nodes.googleWriterApplyCopy.click();
  assert.match(h.clipboard.text,/Стан continuation run: outcome_unknown/);
  assert.doesNotMatch(h.clipboard.text,/PRIVATE_TICKET_SENTINEL|SHOULD_NOT_ESCAPE|D{43}|c1dc13464f0247c5a727204ebf28f8cc/);
});

test('a valid saved Preview request ID can be checked later without storing its ticket',async()=>{
  const h=harness({started:false});
  await h.app.request('/api/admin/google-writer/append-continuation-preview',{method:'POST'});
  const saved=JSON.parse([...h.storage.values()][0]);
  assert.equal(saved.level,'none');
  assert.equal(saved.diagnosticRequestId,requestId);
  assert.doesNotMatch([...h.storage.values()].join(''),/PRIVATE_TICKET_SENTINEL/);
  const restored=harness({started:false},h.storage);await tick();
  assert.equal(restored.nodes.googleWriterApplyRequestId.value,requestId);
  assert.equal(restored.calls.filter(call=>call.url===`/api/google-writer/continuation-status/${requestId}`).length,1);
  assert.equal(restored.calls.filter(call=>call.method==='POST').length,0);
});

test('manual request ID overrides the Apply lookup without replacing its saved Apply identity',async()=>{
  const storage=new Map([['pqm.googleWriter.applyResult.v1',JSON.stringify({version:1,requestId:'a'.repeat(32),
    httpStatus:202,code:'APPLY_STARTED',level:'success',started:true})]]);
  const h=harness({started:false},storage);h.nodes.googleWriterApplyRequestId.value=requestId;
  await h.nodes.googleWriterApplyDiagnosticCheck.click();await tick();
  assert.ok(h.calls.some(call=>call.url===`/api/google-writer/continuation-status/${requestId}`));
  const saved=JSON.parse(storage.get('pqm.googleWriter.applyResult.v1'));
  assert.equal(saved.requestId,'a'.repeat(32));
  assert.equal(saved.diagnosticRequestId,requestId);
});

test('invalid manual request ID is rejected locally without any network call',async()=>{
  const h=harness({started:false});h.nodes.googleWriterApplyRequestId.value='not-a-request-id';
  await h.nodes.googleWriterApplyDiagnosticCheck.click();await tick();
  assert.match(h.nodes.googleWriterApplyLookupStatus.textContent,/32 символів/);
  assert.equal(h.calls.length,0);
  assert.equal(h.nodes.googleWriterApplyCompactStatus.textContent,'Немає результату Apply');
});

test('read-only BLOCKED and unavailable outcomes are distinguished without leaking data',async()=>{
  const blocked=harness({started:false},new Map(),{status:'BLOCKED',reason_codes:['RECEIPT_BINDING_MISMATCH'],read_only:true,
    ticket:'SECRET',digest:'D'.repeat(43)});
  blocked.nodes.googleWriterApplyRequestId.value=requestId;await blocked.nodes.googleWriterApplyDiagnosticCheck.click();await tick();
  assert.match(blocked.nodes.googleWriterApplyLookupStatus.textContent,/BLOCKED.*RECEIPT_BINDING_MISMATCH/);
  assert.match(detailText(blocked),/Результат read-only перевірки: BLOCKED/);
  assert.doesNotMatch(detailText(blocked),/SECRET|D{43}/);
  const restoredBlocked=harness({started:false},blocked.storage);
  assert.equal(restoredBlocked.nodes.googleWriterApplyCompactStatus.textContent,'Немає результату Apply');
  assert.match(detailText(restoredBlocked),/RECEIPT_BINDING_MISMATCH/);
  assert.equal(restoredBlocked.calls.filter(call=>call.url.startsWith('/api/google-writer/continuation-status/')).length,0);
  const unavailable=harness({started:false},new Map(),{status:'UNAVAILABLE',reason_codes:['CONTINUATION_PLAN_UNAVAILABLE'],read_only:true});
  unavailable.nodes.googleWriterApplyRequestId.value=requestId;await unavailable.nodes.googleWriterApplyDiagnosticCheck.click();await tick();
  assert.match(unavailable.nodes.googleWriterApplyLookupStatus.textContent,/Не вдалося перевірити стан/);
  assert.match(detailText(unavailable),/Результат read-only перевірки: неможливо перевірити/);
  assert.equal(unavailable.nodes.googleWriterApplyCompactStatus.textContent,'Немає результату Apply');
});

test('a mismatched echoed request ID is BLOCKED and not persisted as a binding',async()=>{
  const h=harness({started:false},new Map(),{status:'complete',request_id:'0'.repeat(32),confirmed_append:251,
    checkpoint:{present:true,next_chunk:11},receipts:{verified_count:11},read_only:true});
  h.nodes.googleWriterApplyRequestId.value=requestId;await h.nodes.googleWriterApplyDiagnosticCheck.click();await tick();
  assert.match(h.nodes.googleWriterApplyLookupStatus.textContent,/BLOCKED.*не відповідає/);
  assert.match(detailText(h),/REQUEST_BINDING_MISMATCH/);
  assert.equal(JSON.parse([...h.storage.values()][0]).requestId,null);
});

test('response without a read-only assertion cannot be presented as confirmed',async()=>{
  const h=harness({started:false},new Map(),{status:'complete',request_id:requestId,read_only:false,
    confirmed_append:251,checkpoint:{present:true,next_chunk:11},receipts:{verified_count:11}});
  h.nodes.googleWriterApplyRequestId.value=requestId;await h.nodes.googleWriterApplyDiagnosticCheck.click();await tick();
  assert.match(h.nodes.googleWriterApplyLookupStatus.textContent,/BLOCKED.*read-only/);
  assert.match(detailText(h),/READ_ONLY_NOT_CONFIRMED/);
  assert.doesNotMatch(detailText(h),/Підтверджені APPEND: 251/);
});

test('saved continuation audit reads the saved plan and copies only safe verified counts',async()=>{
  const h=harness({started:false});h.nodes.googleWriterApplyRequestId.value=requestId;
  await h.nodes.googleWriterSavedContinuationAudit.click();await tick();
  assert.equal(h.calls.filter(call=>call.url===`/api/admin/google-writer/saved-continuation-audit/${requestId}`&&call.method==='GET').length,1);
  assert.equal(h.calls.filter(call=>call.method==='POST').length,0);
  assert.equal(h.nodes.googleWriterSavedContinuationAuditStatus.textContent,'VERIFIED');
  assert.match(savedAuditText(h),/Продовження · відсутні: 251/);
  assert.match(savedAuditText(h),/Продовження · вже присутні й підтверджені: 0/);
  assert.match(savedAuditText(h),/Раніше підтверджені 25 · підтверджено: 25/);
  assert.match(savedAuditText(h),/Перевірені receipts continuation: 0/);
  await h.nodes.googleWriterSavedContinuationAuditCopy.click();
  assert.match(h.clipboard.text,/Продовження · відсутні: 251/);
  assert.match(h.clipboard.text,/Google Sheets writes: 0/);
  assert.doesNotMatch(h.clipboard.text,/DO_NOT_COPY|PRIVATE|D{43}|ticket|digest|requestId|c1dc134/);
  await tick();
  assert.equal(h.nodes.googleWriterSavedContinuationAuditCopyStatus.textContent,'Безпечний звіт скопійовано.');
});

test('saved continuation audit explains the exact safe BLOCKED checks in the copied report',async()=>{
  const checks={
    plan_matches:{status:'MATCH'},preserved_match:{status:'MATCH'},source_counts:{status:'MATCH'},
    preserved_counts:{status:'MATCH'},source_chunks_unresolved:{status:'MISMATCH',count:1},
    continuation_chunks_unresolved:{status:'MATCH',count:0},additional_saved_previews:{status:'MATCH',count:0},
    continuation_preview:{status:'MATCH',state:'preview_saved'},linked_runs_unresolved:{status:'MATCH',count:0},
    competing_attempts:{status:'MATCH',count:0},continuation_conflicts:{status:'MATCH',count:0},
    continuation_unverified:{status:'MATCH',count:0},private_field:'NEVER_COPY'};
  delete checks.preserved_counts;
  const result={status:'BLOCKED',request_id:requestId,reason_codes:['CONTINUATION_AUDIT_MISMATCH_OR_UNRESOLVED_STATE'],
    source:{planned:276,confirmed:25,missing:251,conflict:0,unverified:0},
    preserved:{planned:25,confirmed:25,missing:0,conflict:0,unverified:0},
    continuation:{planned:251,present:0,missing:251,duplicate:0,conflict:0,unverified:0},checks,
    related:{source_run:'closed_unknown',continuation_runs:[],source_chunks:{count:1,states:{outcome_unknown:1},unresolved:1,receipt_count:0},
      continuation_chunks:{count:0,states:{},unresolved:0,receipt_count:0},source_checkpoint:false,
      continuation_checkpoints:0,continuation_verified_receipts:0,additional_saved_previews:0},
    read_only:true,sqlite_writes:0,sheets_writes:0,properties_writes:0,preview_created:false,ticket_created:false,writer_started:false};
  const h=harness({started:false},new Map(),null,result);h.nodes.googleWriterApplyRequestId.value=requestId;
  await h.nodes.googleWriterSavedContinuationAudit.click();await tick();
  assert.match(savedAuditText(h),/Причини: CONTINUATION_AUDIT_MISMATCH_OR_UNRESOLVED_STATE/);
  assert.match(savedAuditText(h),/Конкретні умови BLOCKED: Невирішені порції початкового запуску/);
  assert.match(savedAuditText(h),/Невирішені порції початкового запуску: MISMATCH · кількість: 1/);
  assert.match(savedAuditText(h),/Додаткові збережені Preview: MATCH · кількість: 0/);
  assert.match(savedAuditText(h),/Лічильники раніше підтверджених рядків: NOT_CHECKED/);
  await h.nodes.googleWriterSavedContinuationAuditCopy.click();
  assert.match(h.clipboard.text,/Конкретні умови BLOCKED: Невирішені порції початкового запуску/);
  assert.match(h.clipboard.text,/Стан збереженого Preview продовження: MATCH · стан: preview_saved/);
  assert.doesNotMatch(h.clipboard.text,/NEVER_COPY|private_field|ticket|digest|c1dc134/);
});

test('saved continuation audit reports duplicate and conflict counts as BLOCKED',async()=>{
  const result={status:'BLOCKED',request_id:requestId,reason_codes:['CONTINUATION_AUDIT_MISMATCH_OR_UNRESOLVED_STATE'],
    source:{planned:276,confirmed:25,missing:250,conflict:1,unverified:0},
    preserved:{planned:25,confirmed:24,missing:0,conflict:1,unverified:0},
    continuation:{planned:251,present:0,missing:250,duplicate:1,conflict:1,unverified:0},
    related:{source_run:'closed_unknown',continuation_runs:[],source_chunks:{count:0,states:{},unresolved:0,receipt_count:0},
      continuation_chunks:{count:0,states:{},unresolved:0,receipt_count:0},source_checkpoint:false,
      continuation_checkpoints:0,continuation_verified_receipts:0,additional_saved_previews:0},
    read_only:true,sqlite_writes:0,sheets_writes:0,properties_writes:0,preview_created:false,ticket_created:false,writer_started:false};
  const h=harness({started:false},new Map(),null,result);h.nodes.googleWriterApplyRequestId.value=requestId;
  await h.nodes.googleWriterSavedContinuationAudit.click();await tick();
  assert.match(h.nodes.googleWriterSavedContinuationAuditStatus.textContent,/BLOCKED/);
  assert.match(savedAuditText(h),/дублікати: 1/);
  assert.match(savedAuditText(h),/конфлікти: 1/);
});

test('saved audit exposes unresolved source chunk evidence without identifiers or digests',async()=>{
  const result={status:'BLOCKED',request_id:requestId,reason_codes:['CONTINUATION_AUDIT_MISMATCH_OR_UNRESOLVED_STATE'],
    source:{planned:276,confirmed:25,missing:251,conflict:0,unverified:0},
    preserved:{planned:25,confirmed:25,missing:0,conflict:0,unverified:0},
    continuation:{planned:251,present:0,missing:251,duplicate:0,conflict:0,unverified:0},
    checks:{source_chunks_unresolved:{status:'MISMATCH',count:1}},
    related:{source_run:'closed_unknown',source_run_evidence:{scope:'APPEND_ONLY',attempted_chunk:0,outcome_unknown:true},
      source_close:{status:'VALIDATED',closed:true,disposition:'OUTCOME_UNKNOWN_NOT_CONFIRMED',receipt_verified:true},
      source_chunks:{count:1,states:{outcome_unknown:1},unresolved:1,receipt_count:0},
      continuation_runs:[],continuation_chunks:{count:0,states:{},unresolved:0,receipt_count:0},
      source_checkpoint:false,continuation_checkpoints:0,continuation_verified_receipts:0,additional_saved_previews:0,
      source_recovery:{status:'BLOCKED',reason_codes:['MANIFEST_BINDING_MISMATCH'],
        manifest_mismatch_fields:['manifest.chunkIndex','PRIVATE_VALUE'],first_chunk_recovery_evidence:false},
      source_unresolved_chunk_details:[{state:'outcome_unknown',chunk_index:0,scope:'APPEND_ONLY',phase:'append',
        expected_operations:25,plan_operations_matched:25,operations_match:'MATCH',manifest_binding:'MISMATCH',
        bindings:{journal_plan_id:'MATCH',journal_run_id:'MATCH',journal_scope:'MATCH',journal_phase:'MATCH',
          manifest_version:'MATCH',manifest_plan_id:'MATCH',manifest_run_id:'MATCH',manifest_scope:'MATCH',
          manifest_chunk_index:'MISMATCH',manifest_plan_digest:'MATCH',manifest_source_digest:'MATCH',
          plan_operations:'MATCH',journal_chunk_digest:'MATCH',journal_chunk_id:'MATCH'},
        sheet_status:'MATCH',sheet_counts:{confirmed:25,missing:0,conflict:0,unverified:0},receipt_state:'MISSING',
        chunk_id:'SECRET_ID',digest:'SECRET_DIGEST',code:'PRIVATE_SUPPLIER'}]},
    read_only:true,sqlite_writes:0,sheets_writes:0,properties_writes:0,preview_created:false,ticket_created:false,writer_started:false};
  const h=harness({started:false},new Map(),null,result);h.nodes.googleWriterApplyRequestId.value=requestId;
  await h.nodes.googleWriterSavedContinuationAudit.click();await tick();
  const text=savedAuditText(h);
  assert.match(text,/Невирішена порція початкового запуску 0: outcome_unknown; APPEND_ONLY\/append; operations=25; plan match=MATCH; manifest=MISMATCH; sheet=MATCH; receipt=MISSING/);
  assert.match(text,/manifest_chunk_index=MISMATCH/);
  assert.match(text,/confirmed=25, missing=0, conflict=0, unverified=0/);
  assert.match(text,/Причини recovery перевірки: MANIFEST_BINDING_MISMATCH/);
  assert.match(text,/Поля manifest із розбіжностями: manifest\.chunkIndex/);
  assert.match(text,/Сфера\/attempted_chunk початкового запуску: APPEND_ONLY \/ 0/);
  assert.match(text,/Адміністративне закриття: VALIDATED; OUTCOME_UNKNOWN_NOT_CONFIRMED; receipt перевірено/);
  await h.nodes.googleWriterSavedContinuationAuditCopy.click();
  assert.match(h.clipboard.text,/Невирішена порція початкового запуску 0/);
  assert.doesNotMatch(h.clipboard.text,/SECRET_ID|SECRET_DIGEST|PRIVATE_SUPPLIER|PRIVATE_VALUE|c1dc134/);
});

test('clear read-only state is local only and preserves the Apply result',async()=>{
  const storage=new Map([['pqm.googleWriter.applyResult.v1',JSON.stringify({version:1,requestId,httpStatus:202,
    code:'APPLY_STARTED',level:'success',started:true,diagnosticRequestId:requestId,
    diagnostic:null,savedContinuationAudit:null})]]);
  const h=harness({started:false},storage);h.nodes.googleWriterApplyRequestId.value=requestId;
  await h.nodes.googleWriterSavedContinuationAudit.click();await tick();
  const callsBefore=h.calls.length;
  await h.nodes.googleWriterApplyReadOnlyClear.click();
  assert.equal(h.calls.length,callsBefore);
  assert.equal(h.nodes.googleWriterApplyRequestId.value,'');
  assert.match(h.nodes.googleWriterApplyLookupStatus.textContent,/локальний read-only стан очищено/i);
  assert.equal(h.nodes.googleWriterSavedContinuationAuditCopy.disabled,true);
  assert.equal(h.nodes.googleWriterApplyCompactStatus.textContent,'SUCCESS');
  assert.equal(h.nodes.googleWriterApplyCompactHttp.textContent,'HTTP 202');
  assert.equal(JSON.parse([...h.storage.values()][0]).savedContinuationAudit,null);
  assert.equal(JSON.parse([...h.storage.values()][0]).diagnosticRequestId,null);
});

test('saved continuation audit incomplete or Apps Script unavailable stays UNAVAILABLE',async()=>{
  const result={status:'UNAVAILABLE',request_id:requestId,reason_codes:['GOOGLE_SHEETS_READ_INCOMPLETE'],
    source:{planned:276,confirmed:25,missing:250,conflict:0,unverified:1},
    preserved:{planned:25,confirmed:25,missing:0,conflict:0,unverified:0},
    continuation:{planned:251,present:0,missing:250,duplicate:0,conflict:0,unverified:1},
    read_only:true,sqlite_writes:0,sheets_writes:0,properties_writes:0,
    preview_created:false,ticket_created:false,writer_started:false};
  const h=harness({started:false},new Map(),null,result);h.nodes.googleWriterApplyRequestId.value=requestId;
  await h.nodes.googleWriterSavedContinuationAudit.click();await tick();
  assert.match(h.nodes.googleWriterSavedContinuationAuditStatus.textContent,/UNAVAILABLE.*GOOGLE_SHEETS_READ_INCOMPLETE/);
  assert.match(savedAuditText(h),/Продовження · неперевірені: 1/);
  assert.doesNotMatch(savedAuditText(h),/VERIFIED/);
});

test('saved continuation audit missing receipt and unresolved run are visibly BLOCKED',async()=>{
  const result={status:'BLOCKED',request_id:requestId,reason_codes:['RECEIPT_BINDING_MISMATCH'],
    source:{planned:276,confirmed:25,missing:251,conflict:0,unverified:0},
    preserved:{planned:25,confirmed:25,missing:0,conflict:0,unverified:0},
    continuation:{planned:251,present:0,missing:251,duplicate:0,conflict:0,unverified:0},
    related:{source_run:'closed_unknown',continuation_runs:[{status:'outcome_unknown',scope:'APPEND_ONLY',attempted_chunk_present:true}],
      source_chunks:{count:1,states:{outcome_unknown:1},unresolved:1,receipt_count:0},
      continuation_chunks:{count:1,states:{verified:1},unresolved:0,receipt_count:0},source_checkpoint:false,
      continuation_checkpoints:0,continuation_verified_receipts:0,additional_saved_previews:0},
    read_only:true,sqlite_writes:0,sheets_writes:0,properties_writes:0,
    preview_created:false,ticket_created:false,writer_started:false};
  const h=harness({started:false},new Map(),null,result);h.nodes.googleWriterApplyRequestId.value=requestId;
  await h.nodes.googleWriterSavedContinuationAudit.click();await tick();
  assert.match(h.nodes.googleWriterSavedContinuationAuditStatus.textContent,/BLOCKED/);
  assert.match(savedAuditText(h),/Пов’язані continuation-запуски: 1/);
  assert.match(savedAuditText(h),/Перевірені receipts continuation: 0/);
});

test('saved continuation audit rejects invalid ID and a response with unsafe side-effect flags',async()=>{
  const invalid=harness({started:false});invalid.nodes.googleWriterApplyRequestId.value='not-an-id';
  await invalid.nodes.googleWriterSavedContinuationAudit.click();
  assert.equal(invalid.calls.length,0);
  assert.match(invalid.nodes.googleWriterSavedContinuationAuditStatus.textContent,/REQUEST_ID_INVALID/);
  const unsafe=harness({started:false},new Map(),null,{status:'VERIFIED',request_id:requestId,
    source:{planned:276,confirmed:25,missing:251,conflict:0,unverified:0},
    preserved:{planned:25,confirmed:25,missing:0,conflict:0,unverified:0},
    continuation:{planned:251,present:0,missing:251,duplicate:0,conflict:0,unverified:0},
    read_only:true,sqlite_writes:1,sheets_writes:0,properties_writes:0,
    preview_created:false,ticket_created:false,writer_started:false});
  unsafe.nodes.googleWriterApplyRequestId.value=requestId;await unsafe.nodes.googleWriterSavedContinuationAudit.click();await tick();
  assert.match(unsafe.nodes.googleWriterSavedContinuationAuditStatus.textContent,/BLOCKED.*READ_ONLY_CONTRACT_UNCONFIRMED/);
});

test('status sits in desktop column four and details dialog wraps responsively',()=>{
  assert.match(index,/id="googleWriterApplyCompact" class="google-writer-apply-compact/);
  assert.doesNotMatch(index,/googleWriterApplyResult"[^>]*position:\s*fixed/);
  assert.match(index,/id="googleWriterApplyDetailsDialog" class="google-writer-apply-dialog/);
  assert.match(styles,/grid-template-columns:repeat\(4,minmax\(0,1fr\)\)/);
  assert.match(styles,/grid-column:4/);
  assert.match(styles,/\.edr-monitoring-heading>\.edr-monitoring-kpis\{grid-column:1\/-1;grid-row:2;grid-template-columns:repeat\(6,minmax\(0,1fr\)\)/);
  assert.match(styles,/@media\(max-width:800px\)[\s\S]*?grid-template-columns:repeat\(3,minmax\(0,1fr\)\)/);
  assert.match(styles,/@media\(max-width:700px\)[\s\S]*?grid-template-columns:repeat\(2,minmax\(0,1fr\)\)/);
  assert.match(styles,/overflow-wrap:anywhere;word-break:break-word/);
  assert.match(styles,/@media\(max-width:700px\)[\s\S]*?\.google-writer-apply-details,\.google-writer-saved-continuation-audit-result\{grid-template-columns:minmax\(0,1fr\)/);
  assert.match(index,/class="google-writer-apply-scroll" data-testid="google-writer-apply-scroll"/);
  assert.match(index,/id="googleWriterApplyReadOnlyClear"[^>]*>Очистити read-only стан/);
  assert.match(styles,/\.google-writer-apply-dialog>form\{display:grid;grid-template-rows:auto minmax\(0,1fr\) auto/);
  assert.match(styles,/\.google-writer-apply-scroll\{[^}]*overflow:auto/);
  assert.match(styles,/\.google-writer-apply-dialog>form>header\{position:sticky/);
  assert.match(styles,/\.google-writer-apply-dialog>form>footer\{position:sticky/);
  assert.match(styles,/max-height:calc\(100dvh - 32px\)/);
  assert.match(index,/Копіювати діагностику/);
  assert.match(index,/id="googleWriterApplyDiagnosticCheck"[^>]*>Перевірити стан/);
  assert.match(index,/id="googleWriterSavedContinuationAudit"[^>]*>Звірити збережене продовження/);
  assert.match(index,/id="googleWriterSavedContinuationAuditCopy"[^>]*>Копіювати звіт/);
  assert.match(index,/googleWriterSavedContinuationAudit/);
  assert.match(index,/id="googleWriterApplyCompact" class="google-writer-apply-compact card" aria-live="polite">/);
  assert.match(index,/Діагностика Google Writer/);
});
