const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),test=require('node:test');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'PqmSandboxPreviewDependencies.gs'),'utf8').replace(/\r\n/g,'\n');
function fixture(code,status,googleDate,pqmDate='2026-07-22'){
  const c={Date,Map,Set};vm.createContext(c);vm.runInContext(source,c);
  const values=Array(15).fill('');values[1]=code;values[2]='old name';values[4]=status;
  values[5]='old prozorro';values[7]=46000;values[8]=googleDate;values[11]='Google officer';
  const row={values,formulas:Array(15).fill(''),codeDisplay:code};
  const tabs=Object.fromEntries(['ФОП','ЮО'].map((name,i)=>[name,{id:i+1,headers:Array.from(c.PQM_GOOGLE_HEADERS),rows:name==='ЮО'?[row]:[],merges:[],templateRowHeight:25}]));
  const body={count:1,items:[{supplier_code:code,entity_type:'legal_entity',supplier_name:'new name',
    monitoring_eligible:true,google_sync_eligible:true,freshness_marker:'fresh',edr_status_current:'Зареєстровано',
    verification_date:pqmDate,verification_officer:'PQM officer',prozorro_status_google:'Активний',
    last_application_date:'2026-09-22',google_sync_last_decided_application_date:'2026-09-22'}]};
  return {c,tabs,body,plan:()=>c.pqmGooglePlan_(body,tabs)};
}
for(const [code,status] of [['01756131','Припинено'],['45431261','В стані припинення']]){
  for(const date of [46300.375,'2026-10-05','05.10.2026']){
    test(`${code}: newer Google ${date} preserves E/I/L, independent C/F/H still planned`,()=>{
      const f=fixture(code,status,date),before=JSON.stringify(f.tabs),p=f.plan(),cells=p.changes[0].cells;
      for(const column of ['4','8','11'])assert.equal(Object.hasOwn(cells,column),false);
      for(const column of ['2','5','7'])assert.equal(Object.hasOwn(cells,column),true);
      assert.equal(p.counts.google_newer_preserved,1);assert.equal(JSON.stringify(f.tabs),before);
    });
  }
}
test('older Google preserves existing behavior: E/I/L updated',()=>{
  const f=fixture('01756131','Припинено','2026-07-21'),p=f.plan(),cells=p.changes[0].cells;
  assert.equal(cells[4],'Зареєстровано');assert.equal(cells[8],f.c.pqmGoogleDate_('2026-07-22'));
  assert.equal(cells[11],'PQM officer');assert.equal(p.counts.pqm_newer_written,1);
});
test('equal dates retain status update and preserve different Google officer',()=>{
  const f=fixture('45431261','В стані припинення','2026-07-22'),p=f.plan(),cells=p.changes[0].cells;
  assert.equal(cells[4],'Зареєстровано');assert.equal(Object.hasOwn(cells,'8'),false);
  assert.equal(Object.hasOwn(cells,'11'),false);assert.equal(p.counts.same_date_google_officer_preserved,1);
});
test('regression guard is the only planner change; older/equal plans match baseline',()=>{
  const baseline=source.replace(/        \/\/ E belongs[^]*?        delete incoming\[4\];\n/,'');
  assert.notEqual(baseline,source);
  for(const date of ['2026-07-21','2026-07-22']){
    const f=fixture('01756131','Припинено',date),old={Date,Map,Set};vm.createContext(old);vm.runInContext(baseline,old);
    assert.equal(JSON.stringify(f.plan()),JSON.stringify(old.pqmGooglePlan_(f.body,f.tabs)));
  }
});
test('historical blank PQM officer writes only canonical sandbox attribution without mutating API',()=>{
  for(const googleDate of ['', '2026-07-21','2026-07-22']){
    const f=fixture('01756131','Зареєстровано',googleDate);
    f.body.items[0].verification_officer='';f.tabs['ЮО'].rows[0].values[11]='';
    const before=JSON.stringify(f.body),p=f.plan(),cells=p.changes[0].cells;
    assert.equal(p.counts.conflicts,0);assert.equal(cells[11],'Тестова УО SANDBOX');
    assert.equal(JSON.stringify(f.body),before);
    if(googleDate==='2026-07-22')assert.equal(Object.hasOwn(cells,'8'),false);
    else assert.equal(cells[8],f.c.pqmGoogleDate_('2026-07-22'));
  }
});
test('newer Google preserved even with blank PQM officer; same date real Google officer preserved',()=>{
  for(const googleDate of ['2026-10-05','2026-07-22']){
    const f=fixture('01756131','Припинено',googleDate);f.body.items[0].verification_officer='';
    const p=f.plan(),cells=p.changes[0].cells;
    assert.equal(p.counts.conflicts,0);assert.equal(Object.hasOwn(cells,'11'),false);
    assert.equal(Object.hasOwn(cells,'8'),false);
    if(googleDate==='2026-10-05')assert.equal(Object.hasOwn(cells,'4'),false);
  }
});
test('blank/invalid PQM dates never create canonical sandbox officer; real officer retained',()=>{
  for(const pqmDate of ['', 'invalid']){
    const f=fixture('01756131','Припинено','2026-10-05',pqmDate);f.body.items[0].verification_officer='';
    const p=f.plan();assert.ok(!JSON.stringify(p.changes).includes('Тестова УО SANDBOX'));
  }
  const f=fixture('01756131','Зареєстровано','2026-07-21');
  assert.equal(f.plan().changes[0].cells[11],'PQM officer');
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
  assert.equal(p.changes.filter(x=>x.cells[11]==='Тестова УО SANDBOX').length,4420);
});
