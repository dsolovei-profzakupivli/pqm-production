const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const test = require('node:test');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, 'PqmSandboxResultUi.gs'), 'utf8');
function context(overrides = {}) {
  const c = {console, ...overrides};
  vm.createContext(c); vm.runInContext(source, c); return c;
}
test('preview keeps all details, escapes markup, has no Apply RPC', () => {
  const c = context();
  const result = {counts: {updated: 130}, conflicts_errors: [{message:'</script><img onerror=bad>'}],
    proposed_changes: Array.from({length:130}, (_,i)=>({supplier_code:String(i),old_value:'old',proposed_value:'new'}))};
  const model = c.pqmSandboxResultModel_(result,'preview');
  assert.equal(model.details.length,130);
  const html = c.pqmSandboxResultHtml_(model);
  assert.ok(!html.includes('</script><img'));
  assert.ok(!html.includes('google.script.run'));
  assert.ok(html.includes('size=50'));
  const embedded = html.match(/<script type="application\/json" id="data">([\s\S]*?)<\/script>/)[1];
  assert.equal(JSON.parse(embedded).details.length,130);
  const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
  scripts.forEach(x=>new vm.Script(x[1]));
});
test('apply shows confirmed counts; unknown counters stay unknown', () => {
  const c=context();
  let m=c.pqmSandboxResultModel_({selected_rows:8,verification_passed:true,failures:[]},'apply');
  assert.equal(m.summary.updated,8); assert.equal(m.summary.skipped,null); assert.equal(m.summary.conflicts,null);
  m=c.pqmSandboxResultModel_({selected_rows:8,verification_passed:false,failures:[{}]},'apply');
  assert.equal(m.summary.updated,null); assert.equal(m.summary.errors,1);
  m=c.pqmSandboxResultModel_({rows_processed:200,remaining_cells:12,status:'TIME_BUDGET_STOP_NEW_PREVIEW_REQUIRED',failures:0},'apply');
  assert.equal(m.summary.updated,200); assert.equal(m.summary.remaining_cells,12);
});
test('wrappers call original exactly once and preserve result/error', () => {
  let calls=0, shown=0; const result={cancelled:true,google_writes:0};
  const c=context({pqmSandboxControlledApply:()=>{calls++;return result}});
  c.pqmSandboxShowResult_=()=>{shown++};
  assert.equal(c.pqmSandboxControlledApplyWithResult(),result); assert.equal(calls,1); assert.equal(shown,1);
  const error=new Error('uncertain'); c.pqmSandboxFullApply=()=>{throw error};
  assert.throws(()=>c.pqmSandboxFullApplyWithResult(),e=>e===error); assert.equal(shown,2);
});
test('display failure is not propagated as writer failure', () => {
  const c=context({SpreadsheetApp:{getUi:()=>{throw new Error('UI unavailable')},getActiveSpreadsheet:()=>({toast(){}})}});
  assert.doesNotThrow(()=>c.pqmSandboxShowResult_('result',{},'apply'));
});
test('Preview hook is presentation only; logging remains', () => {
  const preview=fs.readFileSync(path.join(__dirname,'PqmSandboxPreview.gs'),'utf8');
  assert.ok(preview.includes("pqmSandboxShowResult_('PQM SANDBOX Preview — без записів', preview, 'preview');"));
  assert.ok(preview.includes('console.log(JSON.stringify('));
});
test('date presentation is symmetric, calendar-only and never mutates payload', () => {
  const c=context();
  for (const field of ['H','I','J','verification_date','termination_record_date']) {
    assert.equal(c.pqmSandboxUiDate_(46300.375,field),'05.10.2026');
    assert.equal(c.pqmSandboxUiDate_(46225,field),'22.07.2026');
    assert.equal(c.pqmSandboxUiDate_('2026-10-05T09:00:00+03:00',field),'05.10.2026');
    assert.equal(c.pqmSandboxUiDate_('05.10.2026',field),'05.10.2026');
    for(const blank of ['',null,undefined])assert.equal(c.pqmSandboxUiDate_(blank,field),blank);
    assert.equal(c.pqmSandboxUiDate_('2026-02-30',field),'2026-02-30');
  }
  assert.equal(c.pqmSandboxUiDate_(46300.375,'B'),46300.375);
  assert.equal(c.pqmSandboxUiDate_('Припинено','E'),'Припинено');
  const result={proposed_changes:[{column:'I',old_value:46300.375,proposed_value:46225}]};
  const before=JSON.stringify(result),model=c.pqmSandboxResultModel_(result,'preview');
  const html=c.pqmSandboxResultHtml_(model);
  assert.equal(JSON.stringify(result),before);
  const data=JSON.parse(html.match(/<script type="application\/json" id="data">([\s\S]*?)<\/script>/)[1]);
  assert.equal(data.details[0].old_value,46300.375);assert.equal(data.details[0].proposed_value,46225);
});
