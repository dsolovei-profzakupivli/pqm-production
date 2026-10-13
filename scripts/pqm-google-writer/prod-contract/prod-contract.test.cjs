const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
test('all seven install files parse together without runtime calls',()=>{
  const c={Date,Map,Set,console:{log(){}}};vm.createContext(c);
  const files=fs.readdirSync(__dirname).filter(n=>/^PqmProd.*\.gs$/.test(n));
  assert.equal(files.length,7);
  for(const n of files)vm.runInContext(fs.readFileSync(path.join(__dirname,n),'utf8'),c);
});
function fixture(pqmDate='2026-10-11', googleDate='2026-10-10') {
  const c={Date,Map,Set,console:{log(){}}}; vm.createContext(c);
  for(const n of ['Dependencies','Preview','ControlledApply','AppendApply','FullApply']) {
    const name=n==='Dependencies'?'PqmProdPreviewDependencies.gs':'PqmProd'+n+'.gs';
    vm.runInContext(fs.readFileSync(path.join(__dirname,name),'utf8'),c);
  }
  const row={values:Array(15).fill('old'),formulas:Array(15).fill(''),codeDisplay:'12345678'};
  row.values[1]='12345678';row.values[8]=googleDate;row.values[4]='Особливий статус ЄДР';
  row.formulas[0]='=IF(B2="","",B2&$B$2)';
  const tabs=Object.fromEntries(['ЮО','ФОП'].map((n,i)=>[n,{id:i+1,maxRows:10,
    headers:Array.from(c.PQM_GOOGLE_HEADERS),rows:[JSON.parse(JSON.stringify(row))],
    templateRowHeight:30,merges:[],conditionalFormats:[]}]));
  tabs['ФОП'].rows[0].codeDisplay='0000000001';tabs['ФОП'].rows[0].values[1]='0000000001';
  const x={supplier_code:'12345678',entity_type:'legal_entity',monitoring_eligible:true,
    google_sync_eligible:true,supplier_name:'New',current_manager_name:'Ready manager',
    edr_status_current:'Зареєстровано',prozorro_status_google:'Активний',freshness_marker:null,
    last_application_date:'2026-10-11',google_sync_last_decided_application_date:'2026-10-11',
    verification_date:pqmDate,verification_officer:'Verified officer'};
  return {c,tabs,x,plan:()=>c.pqmGooglePlan_({count:1,items:[x]},tabs)};
}
for(const d of ['2026-10-10','2026-10-09',null,'','bad']) test('whole row date gate '+d,()=>{
  const f=fixture(d); assert.equal(f.plan().changes.length,0);
  if(d==='bad') assert.equal(f.plan().counts.conflicts,1);
});
for(const d of ['',null,'bad']) test('missing/invalid Google date blocks '+d,()=>{
  const f=fixture('2026-10-11',d);assert.equal(f.plan().changes.length,0);
  assert.equal(f.plan().counts.conflicts,1);
});
test('newer uses ready D, preserves source and E across special statuses',()=>{
  for(const status of ['Припинено','Банкрут','Немає інформації','Особливий статус','=NA()','']) {
    const f=fixture();f.tabs['ЮО'].rows[0].values[4]=status;f.x.edr_status_current='Unknown source status';
    const before=JSON.stringify({x:f.x,tabs:f.tabs});const p=f.plan();
    assert.equal(p.changes[0].cells[3],'Ready manager');assert.equal(Object.hasOwn(p.changes[0].cells,4),false);
    assert.equal(JSON.stringify({x:f.x,tabs:f.tabs}),before);
  }
});
test('D formula conflicts and blank D never clears',()=>{
  const f=fixture();f.tabs['ЮО'].rows[0].formulas[3]='=B2';assert.equal(f.plan().changes.length,0);
  f.tabs['ЮО'].rows[0].formulas[3]='';f.x.current_manager_name='';assert.equal(Object.hasOwn(f.plan().changes[0].cells,3),false);
});
test('missing officer fails closed rather than inventing a SANDBOX officer',()=>{
  const f=fixture();f.x.verification_officer='';assert.equal(f.plan().changes.length,0);
  assert.equal(f.plan().counts.conflicts,1);
});
test('append without I keeps B/C/D/F/H, copies only formula A, leaves E untouched',()=>{
  const f=fixture(null);f.x.supplier_code='87654321';const p=f.plan();
  const cells=p.changes[0].cells;assert.deepEqual(Object.keys(cells).map(Number).sort((a,b)=>a-b),[1,2,3,5,7]);
  const requests=f.c.pqmProdAppendRequests_(p.changes,f.tabs);
  const formulas=requests.filter(r=>r.copyPaste?.pasteType==='PASTE_FORMULA');
  assert.equal(formulas.length,1);assert.equal(formulas[0].copyPaste.destination.startColumnIndex,0);
  assert.equal(formulas[0].copyPaste.destination.endColumnIndex,1);
  assert.ok(requests.filter(r=>r.updateCells).every(r=>r.updateCells.range.startColumnIndex!==4));
  assert.ok(requests.filter(r=>r.copyPaste).every(r=>{
    const range=r.copyPaste.destination;
    return range.endColumnIndex<=4 || range.startColumnIndex>=5;
  }));
  assert.equal(f.c.pqmGoogleTranslatedAppendFormula_(f.tabs['ЮО'].rows[0].formulas[0],2,3),'=IF(B3="","",B3&$B$2)');
  assert.ok(requests.every(r=>!r.copyPaste || r.copyPaste.pasteType!=='PASTE_NORMAL'));
  f.tabs['ЮО'].rows[0].formulas[0]='';assert.throws(()=>f.c.pqmProdAppendRequests_(p.changes,f.tabs),/unsafe formula/);
});
test('tampered E plans rejected by update/full/append request builders',()=>{
  const f=fixture();const entry={tab:'ЮО',row:2,columns:[4],change:{cells:{4:'Зареєстровано'}}};
  assert.throws(()=>f.c.pqmProdControlledRequests_([entry],f.tabs),/frozen E/);
  assert.throws(()=>f.c.pqmProdFullRequests_([entry],f.tabs),/frozen E/);
  assert.throws(()=>f.c.pqmProdAppendRequests_([{tab:'ЮО',row:3,append:true,cells:{1:'87654321',4:'x'}}],f.tabs),/unsafe plan/);
});
test('PROD endpoint and destination guards fail closed without approved identity',()=>{
  const f=fixture();f.c.SpreadsheetApp={getActiveSpreadsheet:()=>({getId:()=> 'actual-prod'})};
  assert.throws(()=>f.c.pqmProdControlledSpreadsheetId_(),/guard/);
  f.c.PQM_PROD_CONTROLLED_SPREADSHEET_ID='actual-prod';assert.equal(f.c.pqmProdControlledSpreadsheetId_(),'actual-prod');
  f.c.PQM_PROD_FULL_REGISTRY_URL='https://pqm-sandbox.onrender.com/api/integrations/suppliers/full-registry';
  assert.throws(()=>f.c.pqmProdRegistryUrl_(),/guard/);
});
