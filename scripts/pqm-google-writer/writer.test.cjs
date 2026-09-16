const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {test} = require('node:test');
const source = fs.readFileSync(__dirname + '/PqmGoogleWriter.gs', 'utf8');
let p;
const clone = x => JSON.parse(JSON.stringify(x));
function row(code, name = 'old') {
  const values = Array(15).fill(''); values[1] = code; values[2] = name;
  return {values, formulas: Array(15).fill(''), codeDisplay: code, dateFormat: 'dd.MM.yyyy'};
}
function tabs() {
  return Object.fromEntries(['ФОП','ЮО'].map((name,i) => [name, {
    id: i + 1, maxRows: 100, templateRowHeight: 37, headers: clone(p.headers), rows: [row(i ? '00110183' : '0012345678')],
    conditionalFormats: [], merges: [], protectedRanges: []
  }]));
}
function item(overrides = {}) {
  return {supplier_code: '00110183', entity_type: 'legal_entity', supplier_name: 'new',
    monitoring_eligible: true, freshness_marker: 'EXACT marker', prozorro_status_google: '✅ Активний',
    last_application_date: '2026-09-16', ...overrides};
}
function body(items) { return {count: items.length, items}; }
function applyPlan(plan, t) {
  plan.changes.forEach(c => {
    while (t[c.tab].rows.length < c.row - 1) t[c.tab].rows.push(row('',''));
    const r = t[c.tab].rows[c.row - 2];
    Object.entries(c.cells).forEach(([k,v]) => { r.values[k] = v; if (k === '1') r.codeDisplay = v; });
    if ('7' in c.cells) r.dateFormat = 'dd.MM.yyyy';
  });
}
// Execute emitted requests, independently of the planner, to catch column/range/field-mask mistakes.
function applyRequests(requests, state) {
  const next=clone(state);
  function tab(id) {return Object.values(next).find(t=>t.id===id);}
  function at(t,index) {while(t.rows.length<=index)t.rows.push(row('',''));return t.rows[index];}
  for(const request of requests) {
    if(request.appendDimension) {const a=request.appendDimension;tab(a.sheetId).maxRows+=a.length;}
    else if(request.copyPaste) {
      const {source:s,destination:d,pasteType:type}=request.copyPaste,t=tab(s.sheetId),from=clone(t.rows[s.startRowIndex-1]);
      for(let i=d.startRowIndex;i<d.endRowIndex;i++) {
        const r=at(t,i-1);
        for(let c=d.startColumnIndex;c<d.endColumnIndex;c++) {
          if(type==='PASTE_FORMULA')r.formulas[c]=from.formulas[c];
          else {const key=type==='PASTE_FORMAT'?'formats':'validations';r[key]??={};r[key][c]=clone(from[key]?.[c]??null);}
        }
      }
    } else if(request.updateDimensionProperties) {const a=request.updateDimensionProperties; for(let i=a.range.startIndex;i<a.range.endIndex;i++) at(tab(a.range.sheetId),i-1).height=a.properties.pixelSize;
    } else if(request.updateConditionalFormatRule) {const a=request.updateConditionalFormatRule;tab(a.sheetId).conditionalFormats[a.index]=a.rule;}
    else if(request.updateCells) {
      const u=request.updateCells,t=tab(u.range.sheetId);
      assert.ok(u.fields.startsWith('userEnteredValue'));
      for(let i=0;i<u.rows.length;i++)u.rows[i].values.forEach((cell,j)=>{
        const c=u.range.startColumnIndex+j,r=at(t,u.range.startRowIndex+i-1),v=cell.userEnteredValue;
        r.values[c]=v.stringValue??v.numberValue;r.formulas[c]='';
        if(c===1)r.codeDisplay=String(r.values[c]);
        if(cell.userEnteredFormat?.numberFormat&&c===7)r.dateFormat=cell.userEnteredFormat.numberFormat.pattern;
      });
    } else throw Error('unhandled mock request');
  }
  Object.assign(state,next);
}
function runtime(input = body([item()]), state, status = 200) {
  let writes = 0, fetches = 0, releases = 0, held = false, rejectLock = false;
  let lastRequests = [], alerts = [], menu = [];
  const context = {module: {exports: {}}, console,
    PropertiesService: {getScriptProperties: () => ({getProperty: k => k.endsWith('URL') ? 'https://fixture.invalid/api/integrations/suppliers/full-registry' : 'fixture-secret'})},
    UrlFetchApp: {fetch: (_url, options) => { fetches++; assert.equal(options.followRedirects, false); return {getResponseCode: () => status, getContentText: () => JSON.stringify(input)}; }},
    LockService: {getScriptLock: () => ({tryLock: wait => { assert.equal(wait,0); if (held || rejectLock) return false; held = true; return true; }, releaseLock: () => { releases++; held = false; }})},
    Utilities: {DigestAlgorithm: {SHA_256: 'sha256'}, Charset: {UTF_8: 'utf8'},
      computeDigest: (_, data) => crypto.createHash('sha256').update(data).digest(), base64EncodeWebSafe: x => x.toString('base64url')},
    SpreadsheetApp: {getActiveSpreadsheet: () => ({getId: () => 'fixture'}), getUi: () => ({
      ButtonSet: {YES_NO: 'YES_NO', OK:'OK'}, Button: {YES:'YES'}, alert: (...a) => {alerts.push(a); return 'NO';},
      createMenu: name => {menu.push(name); const m = {addItem: (...x) => {menu.push(x); return m;}, addSeparator: () => {menu.push('|'); return m;}, addToUi: () => {}}; return m;}
    })},
    Sheets: {Spreadsheets: {get: () => {throw Error('snapshot override expected');}, batchUpdate: req => {assert.equal(held, true); writes++; lastRequests = req.requests; applyRequests(req.requests, state);}}}
  };
  vm.createContext(context); vm.runInContext(source, context);
  if (state) context.pqmGoogleSnapshot_ = () => clone(state);
  return {p: context.module.exports, context, stats: () => ({writes,fetches,releases,lastRequests,alerts,menu}), block: () => {rejectLock = true;}};
}
p = runtime().p;

test('routing, foreign/unknown, leading zero identity, and counts', () => {
  const plan = p.plan(body([item(), item({supplier_code:'0012345678',entity_type:'individual_entrepreneur'}),
    item({supplier_code:'US-7',entity_type:'foreign_legal_entity'}),item({supplier_code:'X',entity_type:'unknown'})]), tabs());
  assert.equal(plan.counts.updated,2); assert.equal(plan.counts.skipped,2);
  assert.equal(plan.per_tab['ФОП'].updated,1); assert.equal(plan.per_tab['ЮО'].updated,1);
  assert.equal(plan.changes[0].cells[1],undefined);
});
test('only A/C/F/H update; Google fields, key and missing supplier preserved', () => {
  const t=tabs(), r=t['ЮО'].rows[0];
  [3,4,6,8,9,10,11,12,13,14].forEach(c=> {r.values[c]='manual'+c;r.formulas[c]='=MANUAL()';});
  t['ЮО'].rows.push(row('missing','keep')); const before=clone(t);
  const plan=p.plan(body([item()]),t); assert.deepEqual(Object.keys(plan.changes[0].cells),['0','2','5','7']);
  applyPlan(plan,t); [1,3,4,6,8,9,10,11,12,13,14].forEach(c=>assert.equal(r.values[c],before['ЮО'].rows[0].values[c]));
  assert.deepEqual(t['ЮО'].rows[1],before['ЮО'].rows[1]);
});
test('blank API preserves all existing values',()=>{
  const plan=p.plan(body([item({supplier_name:' ',freshness_marker:null,prozorro_status_google:'',last_application_date:null})]),tabs());
  assert.equal(plan.counts.unchanged,1); assert.equal(plan.changes.length,0);
});
test('every owned formula including B conflicts even for blank incoming',()=>{
  for(const c of [0,1,2,5,7]) {const t=tabs();t['ЮО'].rows[0].formulas[c]='=A1';
    const plan=p.plan(body([item({freshness_marker:''})]),t);assert.equal(plan.counts.conflicts,1);assert.equal(plan.changes.length,0);}
});
test('eligible append, ineligible skip, existing ineligible update, no N/O generation',()=>{
  const t=tabs(); const plan=p.plan(body([item({monitoring_eligible:false}),item({supplier_code:'00000007'}),item({supplier_code:'00000008',monitoring_eligible:false})]),t);
  assert.equal(plan.counts.appended,1);assert.equal(plan.counts.updated,1);assert.equal(plan.counts.skipped,1);
  assert.equal(plan.changes[1].cells[1],'00000007');assert.equal(plan.changes[1].cells[13],undefined);
});
test('duplicates within tab, across tabs, API duplicates and routing mismatch conflict',()=>{
  for(const mode of ['within','across','api','routing']) {
    const t=tabs();let items=[item()];
    if(mode==='within')t['ЮО'].rows.push(row('00110183'));
    if(mode==='across')t['ФОП'].rows.push(row('00110183'));
    if(mode==='api')items.push(item());
    if(mode==='routing')items=[item({entity_type:'individual_entrepreneur'})];
    const plan=p.plan(body(items),t);assert.equal(plan.changes.length,0);assert.equal(plan.counts.conflicts,items.length);
    assert.equal(plan.counts.duplicate_keys,mode==='routing'?0:1);
  }
});
test('exact trimmed codes never pad or normalize',()=>{
  const plan=p.plan(body([item({supplier_code:' 00110183 '}),item({supplier_code:'110183'})]),tabs());
  assert.equal(plan.counts.matched,1);assert.equal(plan.counts.appended,1);assert.equal(plan.changes[1].cells[1],'110183');
});
test('invalid calendar date cannot overwrite H; marker copied without calculation',()=>{
  const t=tabs();t['ЮО'].rows[0].values[7]=45000;
  const plan=p.plan(body([item({last_application_date:'2026-02-30',freshness_marker:'literal custom marker'})]),t);
  assert.equal(plan.counts.errors,1);assert.equal(plan.changes[0].cells[7],undefined);assert.equal(plan.changes[0].cells[0],'literal custom marker');
  assert.equal(p.date('2024-02-29'),45351);assert.equal(p.date('2026-09-16T00:00:00Z'),null);
});
test('idempotent second run includes appended records and date formatting',()=>{
  const t=tabs(), b=body([item(),item({supplier_code:'00000007'})]);
  applyPlan(p.plan(b,t),t);const second=p.plan(b,t);assert.equal(second.changes.length,0);assert.equal(second.counts.unchanged,2);
});
test('append inherits formatting/validation/height; unaudited formulas and business values stay blank',()=>{
  const t=tabs();t['ЮО'].maxRows=2;t['ЮО'].rows[0].formulas[13]='=ROW()';t['ЮО'].rows[0].values[13]='private';
  t['ЮО'].conditionalFormats=[{ranges:[{sheetId:2,startRowIndex:1,endRowIndex:2}],booleanRule:{condition:{type:'NOT_BLANK'},format:{}}}];
  const req=p.requests(p.plan(body([item({supplier_code:'new'})]),t),t);
  assert.equal(req[0].appendDimension.length,1);
  assert.deepEqual(Array.from(req.filter(x=>x.copyPaste).map(x=>x.copyPaste.pasteType)),['PASTE_FORMAT','PASTE_DATA_VALIDATION']);
  assert.equal(req.find(x=>x.updateConditionalFormatRule).updateConditionalFormatRule.rule.ranges[0].endRowIndex,3);
  assert.ok(!JSON.stringify(req).includes('private'));
  const b=req.find(x=>x.updateCells?.range.startColumnIndex===1).updateCells;
  assert.equal(b.rows[0].values[0].userEnteredValue.stringValue,'new');
  const h=req.find(x=>x.updateCells?.range.startColumnIndex===7).updateCells;
  assert.equal(h.rows[0].values[0].userEnteredFormat.numberFormat.pattern,'dd.MM.yyyy');
});
test('API formula-like text is a literal string, not executable formula',()=>{
  const t=tabs();const req=p.requests(p.plan(body([item({supplier_name:'=IMPORTXML("url")'})]),t),t);
  assert.equal(req.find(x=>x.updateCells?.range.startColumnIndex===2).updateCells.rows[0].values[0].userEnteredValue.stringValue,'=IMPORTXML("url")');
});
test('dry-run zero writes; Apply atomic batch under lock; repeat preview unchanged',()=>{
  const t=tabs(), r=runtime(body([item(),item({supplier_code:'new'})]),t);
  const preview=r.p.writer();assert.equal(r.stats().writes,0);assert.equal(preview.dry_run,true);
  const applied=r.p.writer({apply:true,expectedDigest:preview.digest});assert.equal(applied.dry_run,false);assert.equal(r.stats().writes,1);
  assert.equal(r.p.writer().counts.unchanged,2);assert.equal(r.stats().releases,3);
});
test('emitted requests preserve manual cells and inherited validation after mock Apply',()=>{
  const t=tabs();t['ЮО'].rows[0].values[12]='manual note';t['ЮО'].rows[0].values[13]='manual N';
  t['ЮО'].rows[0].validations={5:{strict:true,values:['✅ Активний']}};
  t['ЮО'].rows[0].formats={0:{color:'green'}};
  const r=runtime(body([item(),item({supplier_code:'new'})]),t),preview=r.p.writer();
  r.p.writer({apply:true,expectedDigest:preview.digest});
  assert.equal(t['ЮО'].rows[0].values[12],'manual note');assert.equal(t['ЮО'].rows[0].values[13],'manual N');
  assert.equal(t['ЮО'].rows[1].height,37);assert.equal(t['ЮО'].rows[1].values[12],'');assert.equal(t['ЮО'].rows[1].values[13],'');
  assert.deepEqual(t['ЮО'].rows[1].validations[5],t['ЮО'].rows[0].validations[5]);
  assert.deepEqual(t['ЮО'].rows[1].formats[0],t['ЮО'].rows[0].formats[0]);
});
test('failed batch does not retry and releases lock with sanitized error',()=>{
  const t=tabs(),r=runtime(body([item()]),t),preview=r.p.writer(),before=clone(t);
  r.context.Sheets.Spreadsheets.batchUpdate=()=>{throw Error('sensitive upstream detail');};
  assert.throws(()=>r.p.writer({apply:true,expectedDigest:preview.digest}),/outcome unknown/);
  assert.deepEqual(t,before);assert.equal(r.stats().releases,2);
});
test('missing/stale preview abort before write',()=>{
  const t=tabs(),r=runtime(body([item()]),t);assert.throws(()=>r.p.writer({apply:true}),/preview/);
  const preview=r.p.writer();t['ЮО'].rows[0].values[12]='concurrent manual edit';
  assert.throws(()=>r.p.writer({apply:true,expectedDigest:preview.digest}),/stale/);assert.equal(r.stats().writes,0);
});
test('lock contention prevents API read and all writes',()=>{
  const r=runtime(body([item()]),tabs());r.block();assert.throws(()=>r.p.writer(),/another writer/);
  assert.equal(r.stats().fetches,0);assert.equal(r.stats().writes,0);assert.equal(r.stats().releases,0);
});
test('401/403/non-200, malformed schema and header mismatch abort before mutation',()=>{
  for(const code of [401,403,302,500]) {const r=runtime(body([item()]),tabs(),code);assert.throws(()=>r.p.writer(),/HTTP/);assert.equal(r.stats().writes,0);assert.equal(r.stats().releases,1);}
  for(const b of [{items:[]},body([item({supplier_code:110183})]),body([item({monitoring_eligible:null})]),body([item({supplier_name:undefined})])]) {
    const r=runtime(b,tabs());assert.throws(()=>r.p.writer(),/schema/);assert.equal(r.stats().writes,0);
  }
  const t=tabs();t['ФОП'].headers[0]='wrong';const r=runtime(body([item()]),t);assert.throws(()=>r.p.writer(),/header mismatch/);assert.equal(r.stats().writes,0);
});
test('HTTP/transport/body errors do not expose token or response body',()=>{
  const r=runtime(body([item()]),tabs());r.context.UrlFetchApp.fetch=()=>{throw Error('fixture-secret');};
  assert.throws(()=>r.p.writer(),e=>!e.message.includes('fixture-secret')&&e.message.includes('transport'));
  r.context.UrlFetchApp.fetch=()=>({getResponseCode:()=>200,getContentText:()=>'<fixture-secret>'});
  assert.throws(()=>r.p.writer(),/invalid JSON/);assert.equal(r.stats().writes,0);
});
test('preview menu requires explicit Apply; cancel performs zero writes',()=>{
  const r=runtime(body([item()]),tabs());r.p.preview();assert.equal(r.stats().writes,0);assert.equal(r.stats().alerts[0][2],'YES_NO');
  r.p.menu({clarityChecker:'fixtureClarity',dateAndOfficer:'fixtureDate',organizationEditor:'fixtureEditor'});
  assert.deepEqual(r.stats().menu,['⚙️ Робота з даними',['PQM → Google','pqmGooglePreview'],'|',['🏢 Заповнити дані з файлу ClarityChecker','fixtureClarity'],'|',['📆 Оновити Дату та УО для виділених рядків','fixtureDate'],'|',['✏️ Редактор ЮО','fixtureEditor']]);
});
test('missing template and template owned formula prevent append; merged owned cells conflict',()=>{
  const t=tabs();t['ЮО'].rows=[];assert.equal(p.plan(body([item()]),t).counts.conflicts,1);
  t['ЮО'].rows=[row('existing')];t['ЮО'].rows[0].formulas[0]='=NOW()';assert.equal(p.plan(body([item()]),t).counts.conflicts,1);
  t['ЮО'].rows=[row('00110183')];t['ЮО'].merges=[{startRowIndex:1,endRowIndex:2,startColumnIndex:0,endColumnIndex:3}];assert.equal(p.plan(body([item()]),t).counts.conflicts,1);
});
test('snapshot retains numeric formatted identity, serial dates and formula metadata',()=>{
  const r=runtime();r.context.Sheets.Spreadsheets.get=()=>({sheets:[{properties:{title:'ЮО',sheetId:2,gridProperties:{rowCount:50}},data:[{rowMetadata:[{pixelSize:21},{pixelSize:43},{pixelSize:21}],rowData:[
    {values:p.headers.map(x=>({effectiveValue:{stringValue:x}}))},
    {values:[{userEnteredValue:{formulaValue:'=1'},effectiveValue:{numberValue:1}},{effectiveValue:{numberValue:110183},formattedValue:'00110183'},...Array(5).fill({}),{effectiveValue:{numberValue:45000},userEnteredFormat:{numberFormat:{pattern:'dd.MM.yyyy'}}}]},
    {values:[{userEnteredFormat:{backgroundColor:{red:1}}}]}]}]}]});
  const t=r.p.snapshot('fixture');assert.equal(t['ЮО'].templateRowHeight,43);assert.equal(t['ЮО'].rows.length,1);assert.equal(t['ЮО'].rows[0].codeDisplay,'00110183');assert.equal(t['ЮО'].rows[0].formulas[0],'=1');assert.equal(t['ЮО'].rows[0].values[7],45000);
});

const fixtureTabs=tabs();
const fixture=p.plan(body([item(),item({supplier_code:'0012345678',entity_type:'individual_entrepreneur'}),item({supplier_code:'new'}),item({supplier_code:'no',monitoring_eligible:false}),item({supplier_code:'foreign',entity_type:'foreign_legal_entity'}),item({supplier_code:'unknown',entity_type:'unknown'})]),fixtureTabs);
fs.writeFileSync(__dirname+'/fixture-preview.json',JSON.stringify({dry_run:true,google_writes:0,counts:fixture.counts,per_tab:fixture.per_tab,issues:fixture.issues,gaps:fixture.gaps},null,2)+'\n');


test('hypothetical N/O template formulas stay blank and report an observed formula gap',()=>{
  const t=tabs();for(const c of [13,14])t['ЮО'].rows[0].formulas[c]='=ROW()';
  const r=runtime(body([item({supplier_code:'new'})]),t),preview=r.p.writer();
  assert.equal(preview.gaps[0].reason,'append_formulas_not_audited_left_blank');
  r.p.writer({apply:true,expectedDigest:preview.digest});
  for(const c of [13,14]) {assert.equal(t['ЮО'].rows[1].formulas[c],'');assert.equal(t['ЮО'].rows[1].values[c],'');assert.equal(t['ЮО'].rows[0].formulas[c],'=ROW()');}
});
test('unknown height and merged append area block appends',()=>{
  for(const mode of ['height','merge']) {const t=tabs();
    if(mode==='height')t['ЮО'].templateRowHeight=null;
    else t['ЮО'].merges=[{startRowIndex:2,endRowIndex:4,startColumnIndex:3,endColumnIndex:5}];
    const plan=p.plan(body([item({supplier_code:'new'})]),t);
    assert.equal(plan.counts.conflicts,1);assert.equal(plan.changes.length,0);
  }
});
test('height changes invalidate preview before Apply',()=>{
  const t=tabs(),r=runtime(body([item({supplier_code:'new'})]),t),preview=r.p.writer();
  t['ЮО'].templateRowHeight=60;
  assert.throws(()=>r.p.writer({apply:true,expectedDigest:preview.digest}),/stale/);assert.equal(r.stats().writes,0);
});
test('explicit Yes applies through shared writer with one fetch per invocation',()=>{
  const t=tabs(),r=runtime(body([item()]),t);
  const original=r.context.SpreadsheetApp.getUi;
  r.context.SpreadsheetApp.getUi=()=>({...original(),alert:()=> 'YES'});
  assert.equal(r.p.preview().dry_run,false);assert.equal(r.stats().writes,1);assert.equal(r.stats().fetches,2);
});


test('confirmed onEdit G to J/K values preserved; append blank with no formula gap',()=>{
  const t=tabs(),existing=t['ЮО'].rows[0];
  const values={6:'Рішення: дата запису 16.09.2026, номер запису 001234',9:46281,10:'001234'};
  for(const [c,v] of Object.entries(values))existing.values[c]=v;
  const r=runtime(body([item(),item({supplier_code:'new'})]),t),preview=r.p.writer();
  assert.equal(preview.gaps.length,0);
  r.p.writer({apply:true,expectedDigest:preview.digest});
  for(const [c,v] of Object.entries(values)) {
    assert.equal(t['ЮО'].rows[0].values[c],v);
    assert.equal(t['ЮО'].rows[1].values[c],'');
    assert.equal(t['ЮО'].rows[1].formulas[c],'');
  }
  assert.ok(!r.stats().lastRequests.some(x=>x.copyPaste?.pasteType==='PASTE_FORMULA'));
  assert.ok(!/function\s+onEdit\s*\(/.test(source));
});
