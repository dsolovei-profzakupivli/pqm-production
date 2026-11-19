const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const utilities = {formatDate(date) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {
    timeZone:'Europe/Kyiv', year:'numeric', month:'2-digit', day:'2-digit',
    hour:'2-digit', minute:'2-digit', second:'2-digit', hourCycle:'h23'
  }).formatToParts(date).map(p => [p.type,p.value]));
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}.${String(date.getUTCMilliseconds()).padStart(3,'0')}`;
}};

for (const env of ['prod', 'sandbox']) {
  const dir = path.join(__dirname, env);
  const source = fs.readdirSync(dir).filter(f => f.endsWith('.gs'))
    .map(f => fs.readFileSync(path.join(dir, f), 'utf8')).join('\n');
  function fixture() {
    let calls = 0;
    const ctx = vm.createContext({});
    vm.runInContext(fs.readFileSync(path.join(dir, 'PqmEnvironmentGuard.gs'), 'utf8'), ctx);
    const cfg = ctx.PQM_MIRROR_ENV;
    ctx.ScriptApp = {getScriptId: () => cfg.scriptId};
    ctx.SpreadsheetApp = {getActiveSpreadsheet: () => ({getId: () => cfg.spreadsheetId}),
      openById: () => { calls++; }};
    ctx.Sheets = {Spreadsheets: {batchUpdate: () => { calls++; },
      Values: {batchUpdate: () => { calls++; }}}};
    ctx.UrlFetchApp = {fetch: (url, options) => { calls++; return options; }};
    return {ctx, cfg, calls: () => calls};
  }
  test(env + ': entire merged project parses', () => new vm.Script(source));
  test(env + ': wrong script fails before writes', () => {
    const f = fixture(); f.ctx.ScriptApp.getScriptId = () => 'wrong';
    assert.throws(() => f.ctx.pqmMirrorSheetsBatchUpdate_({}, f.cfg.spreadsheetId), /identity mismatch/);
    assert.equal(f.calls(), 0);
  });
  test(env + ': wrong bound spreadsheet fails before writes', () => {
    const f = fixture(); f.ctx.SpreadsheetApp.getActiveSpreadsheet = () => ({getId: () => 'wrong'});
    assert.throws(() => f.ctx.pqmMirrorValuesBatchUpdate_({}, f.cfg.spreadsheetId), /identity mismatch/);
    assert.equal(f.calls(), 0);
  });
  test(env + ': cross-environment destinations and API fail closed', () => {
    const f = fixture();
    for (const name of ['pqmMirrorSheetsBatchUpdate_', 'pqmMirrorValuesBatchUpdate_'])
      assert.throws(() => f.ctx[name]({}, 'other-environment'), /destination rejected/);
    assert.throws(() => f.ctx.pqmMirrorOpenById_('other-environment'), /destination rejected/);
    assert.throws(() => f.ctx.pqmMirrorFetch_('https://other.example/api/test', {}), /API rejected/);
    assert.equal(f.calls(), 0);
  });
  test(env + ': foreign event and range fail closed', () => {
    const f = fixture();
    const range = {getSheet: () => ({getParent: () => ({getId: () => 'other'})})};
    assert.throws(() => f.ctx.pqmMirrorEvent_({range}), /destination rejected/);
    assert.throws(() => f.ctx.pqmMirrorEvent_({source: {getId: () => 'other'}}), /destination rejected/);
    assert.equal(f.calls(), 0);
  });
  test(env + ': API redirects cannot bypass destination guard', () => {
    const f = fixture();
    assert.equal(f.ctx.pqmMirrorFetch_(f.cfg.apiBase + '/api/test', {followRedirects: true}).followRedirects, false);
  });
  function planner(date = '2026-10-11', googleDate = '2026-10-10') {
    const c = vm.createContext({Date, Map, Set, Utilities:utilities});
    const prefix = env === 'prod' ? 'PqmProd' : 'PqmSandbox';
    vm.runInContext(fs.readFileSync(path.join(dir, prefix + 'PreviewDependencies.gs'), 'utf8'), c);
    vm.runInContext(fs.readFileSync(path.join(dir, 'PqmVerificationDatetime.gs'), 'utf8'), c);
    for (const name of ['ControlledApply','FullApply','AppendApply'])
      vm.runInContext(fs.readFileSync(path.join(dir,prefix + name + '.gs'),'utf8'),c);
    const row = {values: Array(15).fill('old'), formulas: Array(15).fill(''), codeDisplay: '12345678'};
    row.values[1] = '12345678'; row.values[5] = 'Активний'; row.values[8] = googleDate;
    row.values[4] = 'Особливий статус'; row.formulas[0] = '=IF(B2="","",B2&$B$2)';
    const tabs = Object.fromEntries(['ЮО', 'ФОП'].map((n, i) => [n, {id:i+1, maxRows:10,
      headers:Array.from(c.PQM_GOOGLE_HEADERS), rows:i ? [] : [row], templateRowHeight:30,
      merges:[], conditionalFormats:[]}]));
    const item = {supplier_code:'12345678', entity_type:'legal_entity', monitoring_eligible:true,
      google_sync_eligible:true, supplier_name:'New', current_manager_name:'Ready manager',
      latest_submission_name:'Application name', edr_status_current:'Зареєстровано',
      prozorro_status_google:'Активний', freshness_marker:null, last_application_date:'2026-10-11',
      google_sync_last_decided_application_date:'2026-10-11', verification_date:date,
      verification_officer:'Verified officer'};
    return {c, row, tabs, item, plan:() => c.pqmGooglePlan_({count:1, items:[item]}, tabs)};
  }
  for (const date of ['2026-10-10', '2026-10-09', '', null, 'bad'])
    test(env + ': whole-row date gate ' + date, () => {
      assert.equal(planner(date).plan().changes.length, 0);
    });
  for (const date of ['bad'])
    test(env + ': missing/invalid Google I blocks entire row ' + date, () => {
      assert.equal(planner('2026-10-11', date).plan().changes.length, 0);
    });
  test(env + ': newer I maps ready D and approved E; inputs unchanged', () => {
    const f = planner(); const before = JSON.stringify([f.tabs, f.item]);
    const plan = f.plan(); assert.equal(plan.changes.length, 1);
    assert.equal(plan.changes[0].cells[3], 'Ready manager');
    assert.equal(plan.changes[0].cells[4], 'Зареєстровано');
    assert.equal(JSON.stringify([f.tabs, f.item]), before);
  });
  test(env + ': D formula blocks; blank D does not clear', () => {
    const f = planner(); f.row.formulas[3] = '=B2';
    assert.equal(f.plan().changes.length, 0);
    f.row.formulas[3] = ''; f.item.current_manager_name = '';
    assert.equal(Object.hasOwn(f.plan().changes[0].cells, 3), false);
  });
  test(env + ': officer absent fails closed, not fabricated', () => {
    const f = planner(); f.item.verification_officer = '';
    assert.equal(f.plan().changes.length, 0);
  });
  for (const date of ['', null]) test(env + ': correct PQM I fills empty Google I ' + date, () => {
    assert.equal(planner('2026-10-11',date).plan().changes.length,1);
  });
  test(env + ': full time rather than date gate; equal instant skips', () => {
    const f = planner('2026-10-11T17:03:01+03:00','11.10.2026 17:03:00');
    assert.equal(f.plan().changes.length,1);
    f.item.verification_date='2026-10-11T14:03:00Z';
    assert.equal(f.plan().changes.length,0);
    f.item.verification_date='2026-10-11T17:02:59+03:00';
    assert.equal(f.plan().changes.length,0);
  });
  test(env + ': verification serial retains seconds and Kyiv time', () => {
    const f = planner(); const ms=Date.parse('2026-10-11T17:03:19+03:00');
    const serial=f.c.pqmVerificationSerial_(ms);
    assert.equal(f.c.pqmVerificationDatetime_(serial).value,ms);
  });
  test(env + ': DST gap/fold, invalid calendar/offset fail closed', () => {
    const f=planner();
    for (const text of ['2026-03-29T03:30:00','2026-10-25T03:30:00',
      '2026-02-30T12:00:00+02:00','2026-10-11T12:00:00+15:00'])
      assert.equal(f.c.pqmVerificationDatetime_(text).kind,'invalid',text);
    assert.throws(() => f.c.pqmVerificationSerial_(Date.parse('2026-10-25T03:30:00+03:00')), /unambiguously/);
  });
  test(env + ': E formula and unknown E reject whole row', () => {
    const f=planner(); f.row.formulas[4]='=B2';assert.equal(f.plan().changes.length,0);
    f.row.formulas[4]=''; f.item.edr_status_current='unmapped';assert.equal(f.plan().changes.length,0);
  });
  test(env + ': all approved E statuses update; nonowned fields remain unplanned', () => {
    for (const status of ['Неактуально','Зареєстровано','Припинено','В стані припинення','Порушено справу про банкрутство','Банкрут']) {
      const f=planner();f.item.edr_status_current=status;
      const cells=f.plan().changes[0].cells;
      assert.equal(cells[4],status);
      for (const column of [0,1,6,9,10,12,13,14]) assert.equal(Object.hasOwn(cells,column),false);
    }
  });
  test(env + ': update request includes E, datetime I format, never B or nonowned cells', () => {
    const f=planner('2026-10-11T17:03:19+03:00','11.10.2026 17:03:00');
    const change=f.plan().changes[0];const prefix=env==='prod'?'pqmProd':'pqmSandbox';
    const entry={tab:change.tab,row:change.row,change,columns:Object.keys(change.cells).map(Number)};
    const requests=f.c[prefix+'FullRequests_']([entry],f.tabs);
    const e=requests.find(r=>r.updateCells.range.startColumnIndex===4);
    const i=requests.find(r=>r.updateCells.range.startColumnIndex===8);
    assert.equal(e.updateCells.rows[0].values[0].userEnteredValue.stringValue,'Зареєстровано');
    assert.equal(i.updateCells.rows[0].values[0].userEnteredFormat.numberFormat.pattern,'dd.MM.yyyy HH:mm:ss');
    assert.equal(i.updateCells.rows[0].values[0].userEnteredFormat.numberFormat.type,'DATE_TIME');
    assert.ok(requests.every(r=>![0,1,6,9,10,12,13,14].includes(r.updateCells.range.startColumnIndex)));
    entry.change.cells[1]='OTHER';entry.columns.push(1);
    assert.throws(()=>f.c[prefix+'FullRequests_']([entry],f.tabs),/unowned/);
  });
  test(env + ': append without I maps B/D/E and only copies A formula', () => {
    const f=planner(null);f.item.supplier_code='00005678';const plan=f.plan();
    assert.equal(plan.changes.length,1);const change=plan.changes[0];
    assert.equal(change.append,true);assert.equal(change.cells[1],'00005678');
    assert.equal(change.cells[3],'Ready manager');assert.equal(change.cells[4],'Зареєстровано');
    const prefix=env==='prod'?'pqmProd':'pqmSandbox';
    const requests=f.c[prefix+'AppendRequests_'](plan.changes,f.tabs);
    const formulas=requests.filter(r=>r.copyPaste?.pasteType==='PASTE_FORMULA');
    assert.equal(formulas.length,1);assert.equal(formulas[0].copyPaste.destination.startColumnIndex,0);
    assert.equal(formulas[0].copyPaste.destination.endColumnIndex,1);
    assert.equal(f.c.pqmGoogleTranslatedAppendFormula_(f.row.formulas[0],2,3),'=IF(B3="","",B3&$B$2)');
    assert.ok(!requests.some(r=>r.copyPaste?.pasteType==='PASTE_NORMAL'));
  });
}
