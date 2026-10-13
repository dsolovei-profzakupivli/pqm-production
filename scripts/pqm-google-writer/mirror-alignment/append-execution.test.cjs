const test = require('node:test');
const assert = require('node:assert/strict');
const fixture = require('./engine-fixture.cjs');
const clone = value => JSON.parse(JSON.stringify(value));
function appendFixture(env) {
  const f = fixture(env), c = f.context, prefix = env === 'prod' ? 'Prod' : 'Sandbox';
  const heights = new Map(), requests = []; let writes = 0, afterWrite = null;
  const templateKey = '2:5';
  for (const [key, cells] of f.raw) {
    heights.set(key, 28);
    for (const cell of cells) {
      cell.userEnteredFormat = {...cell.userEnteredFormat, backgroundColor:{red:0.5}};
      cell.dataValidation = {condition:{type:'TEXT_CONTAINS',values:[{userEnteredValue:'x'}]},strict:false};
    }
  }
  const template = f.raw.get(templateKey);
  template[0].userEnteredValue = {formulaValue:'=IF(B5="","",B5&$B$5)'};
  template[6].userEnteredValue = {formulaValue:'=B5'};
  template[6].effectiveValue = {stringValue:'manual nonowned must not copy'};
  for (const column of [9,10,12,13,14]) template[column].effectiveValue = template[column].userEnteredValue = {stringValue:'manual template'};
  const item = {...f.body.items[4],supplier_code:'87654321',supplier_name:'Verified EDR full name',
    current_manager_name:'Confirmed manager',edr_status_current:'Зареєстровано',
    verification_date:'2026-09-22T17:03:19+03:00',verification_officer:'УО'};
  f.body.items = [item]; f.body.count = 1;
  function cells(id,row) {
    const key=id+':'+row;
    if (!f.raw.has(key)) f.raw.set(key,Array.from({length:15},()=>({})));
    return f.raw.get(key);
  }
  c.Sheets.Spreadsheets.get = (id, options) => {
    assert.equal(id,c.PQM_MIRROR_ENV.spreadsheetId);
    if (!options.ranges) return {sheets:Object.entries(f.tabs).map(([title,tab])=>({properties:{title,sheetId:tab.id,gridProperties:{rowCount:tab.maxRows}}}))};
    return {sheets:options.ranges.map(range=>{
      const m=/^'(ФОП|ЮО)'!A(\d+):O(\d+)$/.exec(range); assert.ok(m);
      const tab=f.tabs[m[1]],first=+m[2],last=+m[3];
      return {properties:{sheetId:tab.id},data:[{startRow:first-1,
        rowData:Array.from({length:last-first+1},(_,i)=>({values:clone(cells(tab.id,first+i))})),
        rowMetadata:Array.from({length:last-first+1},(_,i)=>({pixelSize:heights.get(tab.id+':'+(first+i))||28}))}]};
    })};
  };
  c.Sheets.Spreadsheets.Values = {batchGet(id,options) {
    assert.equal(id,c.PQM_MIRROR_ENV.spreadsheetId);
    return {valueRanges:options.ranges.map(range=>{
      const m=/^'(ФОП|ЮО)'!([AB])(\d+):([BO])(\d+)$/.exec(range); assert.ok(m);
      const tab=f.tabs[m[1]],first=+m[3],last=+m[5],start=m[2]==='B'?1:0,end=m[4]==='B'?2:15;
      return {values:Array.from({length:last-first+1},(_,i)=>cells(tab.id,first+i).slice(start,end).map(cell=>{
        const entered=cell.userEnteredValue||{},effective=cell.effectiveValue||{};
        if (options.valueRenderOption==='FORMULA' && entered.formulaValue) return entered.formulaValue;
        return effective.stringValue??effective.numberValue??'';
      }))};
    })};
  }};
  c.Sheets.Spreadsheets.batchUpdate = ({requests:batch},id) => {
    assert.equal(id,c.PQM_MIRROR_ENV.spreadsheetId);writes++;requests.push(clone(batch));
    for (const req of batch) {
      if (req.copyPaste) {
        const {source:s,destination:d,pasteType:type}=req.copyPaste;
        for (let r=d.startRowIndex;r<d.endRowIndex;r++) for(let col=d.startColumnIndex;col<d.endColumnIndex;col++) {
          const src=cells(s.sheetId,s.startRowIndex+1)[col],dst=cells(d.sheetId,r+1)[col];
          if(type==='PASTE_FORMAT') dst.userEnteredFormat=clone(src.userEnteredFormat||{});
          else if(type==='PASTE_DATA_VALIDATION') dst.dataValidation=clone(src.dataValidation||{});
          else {
            assert.equal(type,'PASTE_FORMULA');assert.equal(col,0);
            const delta=r-s.startRowIndex;
            const formula=src.userEnteredValue.formulaValue.replace(/(\$?[A-Z]+)(\$?)(\d+)/g,
              (_,column,absolute,row)=>column+absolute+(absolute?row:Number(row)+delta));
            dst.userEnteredValue={formulaValue:formula};dst.effectiveValue={stringValue:'computed marker'};
          }
        }
      } else if(req.updateDimensionProperties) {
        const {range:r,properties:p}=req.updateDimensionProperties;
        for(let index=r.startIndex;index<r.endIndex;index++) heights.set(r.sheetId+':'+(index+1),p.pixelSize);
      } else if(req.updateCells) {
        const {range:r,rows}=req.updateCells;assert.ok(r.startRowIndex>=5,'existing identities must never be rewritten by append');
        assert.ok([1,2,3,4,5,7,8,11].includes(r.startColumnIndex));
        const dst=cells(r.sheetId,r.startRowIndex+1)[r.startColumnIndex],src=rows[0].values[0];
        dst.userEnteredValue=clone(src.userEnteredValue);dst.effectiveValue=clone(src.userEnteredValue);
        if(src.userEnteredFormat) dst.userEnteredFormat={...dst.userEnteredFormat,numberFormat:clone(src.userEnteredFormat.numberFormat)};
      } else if(req.appendDimension) {
        const tab=Object.values(f.tabs).find(x=>x.id===req.appendDimension.sheetId);tab.maxRows+=req.appendDimension.length;
      } else assert.fail('Unhandled Sheets request '+JSON.stringify(req));
    }
    for(const tab of Object.values(f.tabs)) {
      let last=tab.rows.length+1;
      while(f.raw.get(tab.id+':'+(last+1))?.[1]?.effectiveValue?.stringValue) {
        tab.rows.push({values:[],formulas:[],codeDisplay:''});last++;
      }
    }
    if(afterWrite) afterWrite();
    return {replies:batch.map(()=>({}))};
  };
  return {f,c,item,requests,template,cells,writes:()=>writes,afterWrite:fn=>{afterWrite=fn;},
    run:()=>c['pqm'+prefix+'DailySync']()};
}
for (const env of ['prod','sandbox']) {
  test(env+': full append executes A relative/absolute formulas, metadata, exact timestamp, immutable existing B',()=>{
    const x=appendFixture(env),before=clone([...x.f.raw]);
    assert.equal(x.run().append,1);assert.equal(x.writes(),1);
    const row=x.cells(2,6);
    assert.equal(row[0].userEnteredValue.formulaValue,'=IF(B6="","",B6&$B$5)');
    assert.equal(row[1].effectiveValue.stringValue,'87654321');
    assert.equal(row[2].effectiveValue.stringValue,'Verified EDR full name');
    assert.equal(row[3].effectiveValue.stringValue,'Confirmed manager');
    assert.equal(row[8].effectiveValue.numberValue,x.c.pqmVerificationSerial_(Date.parse(x.item.verification_date)));
    for(const col of [6,9,10,12,13,14]) assert.deepEqual(row[col].userEnteredValue,undefined);
    for(let col=0;col<15;col++) {
      assert.deepEqual(row[col].dataValidation,x.template[col].dataValidation);
      assert.equal(row[col].userEnteredFormat.backgroundColor.red,0.5);
    }
    for(const [key,cells] of before) assert.deepEqual(x.f.raw.get(key),cells);
    assert.equal(x.run().append,0);assert.equal(x.writes(),1);
  });
  test(env+': unsafe template is fail-closed without a partial row',()=>{
    const x=appendFixture(env);x.template[0].userEnteredValue={formulaValue:'=INDIRECT("B5")'};
    const result=x.run();assert.equal(result.append,0);assert.equal(result.conflict,1);assert.equal(x.writes(),0);
    assert.equal(x.cells(2,6)[1].userEnteredValue,undefined);
  });
  test(env+': occupied destination blocks preflight before writes',()=>{
    const x=appendFixture(env);x.cells(2,6)[6]={effectiveValue:{stringValue:'manual preexisting'}};
    assert.throws(()=>x.run(),/destination row changed/);assert.equal(x.writes(),0);
  });
  test(env+': formula or metadata readback corruption stops without retry',()=>{
    for(const kind of ['formula','validation','time']) {
      const x=appendFixture(env);
      x.afterWrite(()=>{const row=x.cells(2,6);
        if(kind==='formula')row[0].userEnteredValue.formulaValue='=B999';
        if(kind==='validation')row[6].dataValidation={changed:true};
        if(kind==='time')row[8].effectiveValue.numberValue+=1/86400;
      });
      assert.throws(()=>x.run(),/formula A mismatch|validation mismatch|date mismatch/);
      assert.equal(x.writes(),1);
    }
  });
}
