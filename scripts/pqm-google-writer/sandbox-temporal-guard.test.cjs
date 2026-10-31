const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),test=require('node:test');
const path=require('node:path');
const source=['PqmSandboxPreviewDependencies.gs','PqmGoogleBusinessMatrix.gs','PqmVerificationDatetime.gs']
  .map(name=>fs.readFileSync(path.join(__dirname,name),'utf8').replace(/\r\n/g,'\n')).join('\n');
function fixture(code,status,googleDate,pqmDate='2026-07-22'){
  const c={Date,Map,Set,Utilities:{formatDate(value,timezone,pattern){
    assert.equal(timezone,'Europe/Kyiv');assert.equal(pattern,"yyyy-MM-dd'T'HH:mm:ss.SSS");
    const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/Kyiv',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).formatToParts(value);
    const v=Object.fromEntries(parts.map(x=>[x.type,x.value]));return `${v.year}-${v.month}-${v.day}T${v.hour}:${v.minute}:${v.second}.${String(value.getUTCMilliseconds()).padStart(3,'0')}`;
  }}};vm.createContext(c);vm.runInContext(source,c);
  const values=Array(15).fill('');values[1]=code;values[2]='old name';values[4]=status;
  values[5]='Неактивний';values[7]=46000;values[8]=googleDate;values[11]='Google officer';
  const row={values,formulas:Array(15).fill(''),codeDisplay:code};
  const tabs=Object.fromEntries(['ФОП','ЮО'].map((name,i)=>[name,{id:i+1,headers:Array.from(c.PQM_GOOGLE_HEADERS),rows:name==='ЮО'?[row]:[],merges:[],templateRowHeight:25}]));
  const body={count:1,items:[{supplier_code:code,entity_type:'legal_entity',supplier_name:'new name',
    monitoring_eligible:true,google_sync_eligible:true,google_writer_eligible:true,
    google_sync_has_active_qualification:true,google_sync_has_admission_history:true,
    google_sync_last_decided_application_decision:'admit',google_sync_last_decided_protocol_at:'',
    google_sync_last_decided_protocol_officer:'',google_sync_last_decided_submission_id:'s1',
    google_sync_latest_rejection_officer:'',freshness_marker:'fresh',edr_status_current:'Зареєстровано',
    verification_date:pqmDate,verification_officer:'PQM officer',verification_event_type:'google_clarity',
    prozorro_status_google:'Активний',last_application_date:'2026-09-22',
    google_sync_last_decided_application_date:'2026-09-22'}]};
  Object.assign(body.items[0],{classification_version:'subject-nature-20261030-v2',
    classification_status:'resolved',classification_reason:'established_subject_nature',
    classification_reason_label:'Тип підтверджено у fixture',target_sheet:'ЮО',append_allowed:true});
  return {c,tabs,body,plan:()=>c.pqmGoogleBusinessPlan_(body,tabs)};
}
for(const [code,status] of [['01756131','Припинено'],['45431261','В стані припинення']]){
  for(const date of [46300.375,'2026-10-05','05.10.2026']){
    test(`${code}: later Google verification preserves D/E/I/L; independent C/F/H remain planned`,()=>{
      const f=fixture(code,status,date),before=JSON.stringify(f.tabs),p=f.plan(),cells=p.changes[0].cells;
      for(const column of ['4','8','11'])assert.equal(Object.hasOwn(cells,column),false);
      for(const column of ['2','5','7'])assert.equal(Object.hasOwn(cells,column),true);
      assert.equal(Object.hasOwn(cells,'3'),false);assert.equal(p.counts.conflicts,0);
      assert.equal(p.counts.google_newer_preserved,1);
      assert.equal(JSON.stringify(f.tabs),before);
    });
  }
}
test('older date-only Google does not authorize D/E/I/L changes',()=>{
  const f=fixture('01756131','Припинено','2026-07-21'),p=f.plan(),cells=p.changes[0].cells;
  for(const column of ['3','4','8','11'])assert.equal(Object.hasOwn(cells,column),false);
  assert.equal(p.counts.conflicts,1);
});
test('equal date-only values with different identity remain a conflict',()=>{
  const f=fixture('45431261','В стані припинення','2026-07-22'),p=f.plan(),cells=p.changes[0].cells;
  for(const column of ['3','4','8','11'])assert.equal(Object.hasOwn(cells,column),false);
  assert.equal(p.counts.conflicts,1);
});
test('date-only provenance guard blocks only D/E/I/L and retains independent updates',()=>{
  const f=fixture('01756131','Припинено','2026-07-21'),p=f.plan(),cells=p.changes[0].cells;
  for(const column of ['3','4','8','11'])assert.equal(Object.hasOwn(cells,column),false);
  assert.ok(['2','5','7'].some(column=>Object.hasOwn(cells,column)));
  assert.equal(p.issues[0].reason,'date_only_cannot_prove_verification_order');
});
test('historical blank PQM officer never creates synthetic attribution or mutates API',()=>{
  for(const googleDate of ['', '2026-07-21','2026-07-22']){
    const f=fixture('01756131','Зареєстровано',googleDate);
    f.body.items[0].verification_officer='';f.tabs['ЮО'].rows[0].values[11]='';
    const before=JSON.stringify(f.body),p=f.plan(),cells=p.changes[0].cells;
    assert.equal(cells[11],undefined);
    assert.equal(JSON.stringify(f.body),before);
    assert.equal(Object.hasOwn(cells,'8'),false);
  }
});
test('blank PQM verification leaves D/E/I/L untouched even when Google has a date',()=>{
  for(const googleDate of ['2026-10-05','2026-07-22']){
    const f=fixture('01756131','Припинено',googleDate);f.body.items[0].verification_officer='';
    const p=f.plan(),cells=p.changes[0].cells;
    assert.equal(Object.hasOwn(cells,'11'),false);
    assert.equal(Object.hasOwn(cells,'8'),false);
    assert.equal(Object.hasOwn(cells,'3'),false);
  }
});
test('blank/invalid PQM dates never create canonical attribution or verification writes',()=>{
  for(const pqmDate of ['', 'invalid']){
    const f=fixture('01756131','Припинено','2026-10-05',pqmDate);f.body.items[0].verification_officer='';
    const p=f.plan();assert.ok(!JSON.stringify(p.changes).includes('Тестова УО SANDBOX'));
  }
  const f=fixture('01756131','Зареєстровано','2026-07-21');
  assert.equal(f.plan().changes[0].cells[11],undefined);
  const prod=fs.readFileSync(path.join(__dirname,'PqmProdPreviewDependencies.gs'),'utf8');
  assert.ok(!prod.includes('Тестова УО SANDBOX'));
});
test('4420 historical rows normalize, nine newer Google rows remain protected',()=>{
  const f=fixture('10000000','Зареєстровано','2026-07-22');
  const template=JSON.parse(JSON.stringify(f.body.items[0]));template.verification_officer='';
  const row=f.tabs['ЮО'].rows[0];row.values[11]='';
  f.body.items=[];f.tabs['ЮО'].rows=[];
  const nine=['45054758','45088216','45101776','32800996','33860155','23098585','01756131','38229721','45431261'];
  for(let i=0;i<4429;i++){
    const code=i<4420?String(10000000+i):nine[i-4420],item={...template,supplier_code:code};
    const r=JSON.parse(JSON.stringify(row));r.values[1]=code;r.codeDisplay=code;
    if(i>=4420){r.values[8]=46300.375;r.values[11]='Світлана НАМЯСЕНКО';r.values[4]='Припинено';}
    f.body.items.push(item);f.tabs['ЮО'].rows.push(r);
  }
  f.body.count=4429;const p=f.plan();
  assert.equal(p.counts.conflicts,0);assert.equal(p.counts.errors,0);
  assert.equal(p.counts.google_newer_preserved,9);
  assert.equal(p.changes.filter(x=>x.cells[11]==='Тестова УО SANDBOX').length,0);
});
