const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),crypto=require('node:crypto');
const test=require('node:test'),assert=require('node:assert/strict');
function fixture(env) {
  const c=vm.createContext({Date,console});
  for(const name of ['PqmEnvironmentGuard.gs','Код.gs','OrganizationEditor.gs','ccShowManagerApproval.gs'])
    vm.runInContext(fs.readFileSync(path.join(__dirname,env,name),'utf8'),c);
  const headers=['Маркер','Код ЄДРПОУ','Назва','ПІБ для перевірки','Статус ЄДР','Статус Prozorro','Реквізити','Дата заявки','Дата перевірки','Дата запису','Номер запису','УО','Примітки','Повна назва з ЄДР','Скорочена назва з ЄДР'];
  const values=[headers,['formula result','12345678','Existing name','Old manager','Special manual E','Активний','G','2026-09-01','2026-09-01','J','K','Old UO','M','Verified full','Verified short']];
  const formulas=[Array(15).fill(''),Array(15).fill('')];formulas[1][0]='=IF(B2="","",B2)';
  const formats=[Array(15).fill('@'),Array(15).fill('@')];const writes=[];let locked=false,released=0;
  let ss;
  const sheet={getName:()=> 'ЮО',getSheetId:()=>7,getParent:()=>ss,getLastRow:()=>values.length,getLastColumn:()=>15,
    getRange(row,col,height=1,width=1){
      const read=grid=>Array.from({length:height},(_,r)=>grid[row+r-1].slice(col-1,col-1+width));
      const range={getSheet:()=>sheet,getDisplayValues:()=>read(values).map(r=>r.map(x=>String(x??''))),
        getDisplayValue:()=>String(values[row-1][col-1]),getValues:()=>read(values),getFormulas:()=>read(formulas),
        getNumberFormats:()=>read(formats),getDataValidations:()=>Array.from({length:height},()=>Array(width).fill(null)),
        setValues(rows){assert.equal(rows.length,height);writes.push({row,col,height,width});
          rows.forEach((data,r)=>data.forEach((value,k)=>{
            const formula=typeof value==='string'&&value.startsWith('=')?value:'';
            formulas[row+r-1][col+k-1]=formula;values[row+r-1][col+k-1]=formula?'formula result':value;
          }));return range;},setValue(value){return range.setValues([[value]]);},
        setNumberFormat(format){for(let r=0;r<height;r++)for(let k=0;k<width;k++)formats[row+r-1][col+k-1]=format;return range;},
        setHorizontalAlignment(){return range;}};return range;
    }};
  ss={getId:()=>c.PQM_MIRROR_ENV.spreadsheetId,getSheetByName:name=>name==='ЮО'?sheet:null,
    getSheetById:id=>id===7?sheet:null,getActiveSheet:()=>sheet};
  c.ScriptApp={getScriptId:()=>c.PQM_MIRROR_ENV.scriptId};
  c.SpreadsheetApp={getActiveSpreadsheet:()=>ss,getActiveSheet:()=>sheet,openById:id=>{assert.equal(id,c.PQM_MIRROR_ENV.spreadsheetId);return ss;},flush(){},DataValidationCriteria:{VALUE_IN_LIST:'list'}};
  c.Session={getActiveUser:()=>({getEmail:()=> 'd.savva@profzakupivli.com'})};
  c.Utilities={parseCsv:text=>JSON.parse(text),DigestAlgorithm:{SHA_256:'sha256'},computeDigest:(_,text)=>crypto.createHash('sha256').update(text).digest(),base64EncodeWebSafe:bytes=>Buffer.from(bytes).toString('base64url')};
  c.LockService={getDocumentLock:()=>({tryLock:()=>{if(locked)return false;locked=true;return true;},waitLock:()=>{if(locked)throw Error('busy');locked=true;},releaseLock:()=>{locked=false;released++;}})};
  return {c,values,formulas,writes,ss,released:()=>released};
}
const clarityHeaders=['Код ЄДРПОУ','Результат перевірки','Нова дата перевірки ЄДР','Повна назва з ЄДР','Скорочена назва з ЄДР'];
const managerHeaders=['Код ЄДРПОУ','Старий ПІБ Керівника','Новий ПІБ керівника','Результат перевірки','Стара Назва'];
for(const env of ['prod','sandbox']) {
  test(env+': Clarity only I/L/N/O, unprocessed ignored, blank verified names never clear',()=>{
    const f=fixture(env),old=f.values[1].slice();
    const csv=JSON.stringify([clarityHeaders,['12345678','Перевірено','2026-10-13','New verified full',''],['99999999','','bad date','must ignore','ignore']]);
    const result=f.c.processFullNamesCSV(csv,'unused.csv');assert.equal(result.skippedUnprocessed,1);
    for(const write of f.writes)assert.ok([9,12,14,15].includes(write.col));
    for(const col of [0,1,2,3,4,5,6,7,9,10,12,14])assert.equal(f.values[1][col],old[col]);
    assert.equal(f.values[1][13],'New verified full');assert.equal(f.values[1][11],'Дмитро САВВА');
    assert.equal(f.formulas[1][0],'=IF(B2="","",B2)');
    const writes=f.writes.length;f.c.processFullNamesCSV(csv,'unused.csv');assert.equal(f.writes.length,writes);
  });
  test(env+': Clarity preflight invalid date or duplicate identities means zero writes',()=>{
    for(const rows of [[['12345678','checked','2026-02-30','New','']],
      [['12345678','checked','2026-10-13','New',''],['12345678','checked','2026-10-13','Other','']]]) {
      const f=fixture(env);assert.throws(()=>f.c.processFullNamesCSV(JSON.stringify([clarityHeaders,...rows]),''),/Preflight/);assert.equal(f.writes.length,0);
    }
  });
  test(env+': manager approval Preview read-only; explicit selections write D only; repeat/stale reject',()=>{
    const f=fixture(env),csv=JSON.stringify([managerHeaders,['12345678','Old manager','New confirmed manager','checked','name']]);
    const id=f.c.PQM_MIRROR_ENV.spreadsheetId,p=f.c.ccPreviewManagerChanges(csv,id,7);
    assert.equal(p.rows.length,1);assert.equal(f.writes.length,0);
    const before=f.values[1].slice(),selection=p.rows.map(x=>({code:x.code,oldManager:x.oldManager,newManager:x.newManager}));
    assert.equal(f.c.ccApplyApprovedManagers(csv,id,7,selection).updated,1);
    assert.deepEqual(f.writes.map(x=>x.col),[4]);
    for(let col=0;col<15;col++)if(col!==3)assert.equal(f.values[1][col],before[col]);
    assert.throws(()=>f.c.ccApplyApprovedManagers(csv,id,7,selection),/змінилися|оновлено/);assert.equal(f.writes.length,1);
    assert.equal(f.released(),2);
  });
  test(env+': manager formula is never offered for replacement',()=>{
    const f=fixture(env);f.formulas[1][3]='=B2';
    const p=f.c.ccPreviewManagerChanges(JSON.stringify([managerHeaders,['12345678','old','new','checked','name']]),f.c.PQM_MIRROR_ENV.spreadsheetId,7);
    assert.equal(p.formulaSkipped,1);assert.equal(p.rows.length,0);assert.equal(f.writes.length,0);
  });
  for(const header of ['Дата перевірки ЄДР','Дата перевірки']) test(env+': UO editor preserves formulas/manual values and rejects stale revision '+header,()=>{
    const f=fixture(env);f.values[0][8]=header;
    const model=f.c.organizationEditorGetRow(2),payload={row:2,revisionToken:model.revisionToken,values:model.fields.map(x=>x.value)};
    payload.values[2]='Edited name';payload.values[0]='do not replace formula';
    assert.equal(model.fields[0].readOnly,true);assert.equal(model.fields[8].readOnly,true);
    assert.equal(f.c.organizationEditorSaveRow(payload).ok,true);
    assert.equal(f.formulas[1][0],'=IF(B2="","",B2)');
    assert.equal(f.values[1][2],'Edited name');assert.equal(f.values[1][4],'Special manual E');
    assert.equal(f.values[1][11],'Дмитро САВВА');
    const count=f.writes.length;assert.throws(()=>f.c.organizationEditorSaveRow(payload),/змінив/);assert.equal(f.writes.length,count);
  });
  test(env+': ambiguous editor date columns reject before writes',()=>{
    const f=fixture(env);f.values[0][8]='Дата перевірки ЄДР';f.values[0][9]='Дата перевірки';
    const model=f.c.organizationEditorGetRow(2);
    assert.throws(()=>f.c.organizationEditorSaveRow({row:2,revisionToken:model.revisionToken,values:model.fields.map(x=>x.value)}),/колонку/);
    assert.equal(f.writes.length,0);
  });
  test(env+': every mutating handler fails before writes on wrong bound environment',()=>{
    for(const invoke of [c=>c.processFullNamesCSV('[]',''),c=>c.organizationEditorSaveRow({values:[]}),
      c=>c.ccApplyApprovedManagers('[]',c.PQM_MIRROR_ENV.spreadsheetId,7,[])]) {
      const f=fixture(env);f.c.SpreadsheetApp.getActiveSpreadsheet=()=>({getId:()=> 'OTHER_ENV'});
      assert.throws(()=>invoke(f.c),/identity mismatch/);assert.equal(f.writes.length,0);
    }
  });
}
