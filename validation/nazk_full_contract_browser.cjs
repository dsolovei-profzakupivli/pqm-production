const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = (() => {
  try { return require('playwright'); }
  catch { return require('C:/Users/User/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'); }
})();

const root = path.resolve(__dirname, '..');
const app = fs.readFileSync(path.join(root, 'app.js'), 'utf8');
const index = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const styles = fs.readFileSync(path.join(root, 'styles.css'), 'utf8');
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));

function compileRow(line, marker, endMarker, args) {
  const start = line.indexOf(marker);
  assert.notEqual(start, -1, `missing renderer marker: ${marker}`);
  const from = start + marker.length;
  const end = line.indexOf(endMarker, from);
  assert.notEqual(end, -1, `missing renderer end: ${endMarker}`);
  const template = line.slice(from, end);
  return new Function(...args, 'return `' + template + '`;');
}

const registerTable = index.match(/<table class="reference-table" data-system-table="references:nazk">([\s\S]*?)<\/table>/);
assert(registerTable, 'NАЗК register table must keep its system-table key');
const registerHead = '<table><thead>' + registerTable[1].match(/<thead>([\s\S]*?)<\/thead>/)[1] + '</thead><tbody></tbody></table>';
const registerLine = app.split('\n').find(line => line.includes('x.decree_number') && line.includes('body.innerHTML=data.items'));
assert(registerLine, 'NАЗК register row renderer must expose all nine approved fields');
const renderRegisterRow = compileRow(registerLine, 'data.items.map(x=>`', '`).join', ['x','esc','displayDateOnly']);

const profileLine = app.split('\n').find(line => line.includes('nazkRegistry.map(x=>`'));
assert(profileLine, 'supplier profile NАЗК renderer must exist');
const profileHeadMatch = profileLine.match(/<thead>([\s\S]*?)<\/thead>/);
assert(profileHeadMatch, 'supplier profile NАЗК table headers must exist');
const profileHead = '<table><thead>' + profileHeadMatch[1] + '</thead><tbody></tbody></table>';
const renderProfileRow = compileRow(profileLine, 'nazkRegistry.map(x=>`', '`).join', ['x','esc','displayDateOnly']);

const opStart = app.indexOf('function operationalNazkContext(item)');
const opEnd = app.indexOf('\nfunction operationalNazkWorkspace', opStart);
assert(opStart !== -1 && opEnd !== -1, 'operational NАЗК card renderer must exist');
const opSource = app.slice(opStart, opEnd);
const renderOperational = new Function('operationalNazkRecords','esc','displayDateOnly','nazkRegistrySourceNotice',
  opSource + '; return operationalNazkContext;')(
    item => Array.isArray(item.nazk_records) ? item.nazk_records : [],
    escapeHtml,
    value => value ? (/^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value.slice(8,10)}.${value.slice(5,7)}.${value.slice(0,4)}` : value) : '',
    () => '',
  );
const dateLine = app.split('\n').find(line => line.startsWith('function displayDateOnly('));
assert(dateLine, 'shared date formatter must exist');
const displayDateOnly = new Function(dateLine + '; return displayDateOnly;')();

const complete = {
  source_id: 'nazk-record-001', full_name: 'КРУГЛЯК ОЛЕКСІЙ МИХАЙЛОВИЧ',
  offense_name: 'Опис порушення', punishment: 'Призначено штраф',
  court_case_number: '551/226/26', sentence_date: '2026-10-07',
  punishment_start: '2026-10-08', decision_url: 'https://example.test/decision',
  decree_number: 'Н-0012', decree_date: '2026-10-09',
};
const empty = {...complete, source_id:'nazk-empty', punishment:'', decree_number:'', decree_date:''};
const renderRegister = row => renderRegisterRow(row, escapeHtml, displayDateOnly);
const renderProfile = row => renderProfileRow(row, escapeHtml, displayDateOnly);
const renderTask = records => renderOperational({status:'in_progress',task_person_is_current:true,
  nazk_current_state:{manager_name:complete.full_name},current_manager:{manager_name:complete.full_name},
  nazk_records:records});

(async () => {
  const browser = await chromium.launch({headless:true,
    ...(process.env.PQM_TEST_BROWSER ? {executablePath:process.env.PQM_TEST_BROWSER} : {})});
  try {
    const page = await browser.newPage();
    const html = `<main>${registerHead}<section id="profile">${profileHead}</section>${renderTask([complete,empty])}</main>`;
    await page.setContent(html);
    await page.addStyleTag({content:styles});
    const actualRows = [renderRegister(complete),renderRegister(empty)];
    const profileRows = [renderProfile(complete),renderProfile(empty)];
    await page.evaluate(({actualRows,profileRows,formattedRegisterDates}) => {
      const reg=document.querySelector('main > table tbody');
      reg.innerHTML=actualRows.join('');
      for(const [rowIndex,values] of formattedRegisterDates.entries())
        for(const [columnIndex,value] of Object.entries(values))
          reg.rows[rowIndex].cells[Number(columnIndex)].textContent=value;
      const profile=document.querySelector('#profile tbody');
      profile.innerHTML=profileRows.join('');
    },{actualRows,profileRows,formattedRegisterDates:[complete,empty].map(row=>({
      4:displayDateOnly(row.sentence_date),5:displayDateOnly(row.punishment_start),8:displayDateOnly(row.decree_date)}))});
    const expectedHeaders = ['ПІБ','Порушення','Вид стягнення','Номер судової справи',
      'Дата рішення','Дата набрання законної сили','Посилання на рішення','№ наказу','Дата наказу'];
    const expectedProfileHeaders=['ПІБ','Порушення','Вид стягнення','№ судової справи',
      'Дата рішення','Набрання законної сили','№ наказу','Дата наказу','Рішення'];
    for (const [selector,expected] of [['main > table',expectedHeaders],['section#profile table',expectedProfileHeaders]]) {
      const headers=await page.locator(`${selector} thead th`).allTextContents();
      assert.deepEqual(headers,expected,`${selector} must keep its nine-field contract`);
      assert.equal(await page.locator(`${selector} tbody tr`).first().locator('td').count(),9);
      assert.equal(await page.locator(`${selector} tbody tr`).nth(1).locator('td').count(),9);
    }
    const taskHeaders=await page.locator('.operational-registry-list thead th').allTextContents();
    assert.deepEqual(taskHeaders,['ПІБ','Порушення','Вид стягнення','Справа / рішення','Дата рішення',
      'Набрання чинності','№ наказу','Дата наказу','ID запису','Джерело']);
    assert.equal(await page.locator('.operational-registry-list tbody tr').first().locator('td').count(),10);
    assert.equal(await page.locator('.operational-registry-list tbody tr').nth(1).locator('td').count(),10);
    for (const selector of ['main > table','section#profile table','.operational-registry-list table']) {
      const texts=await page.locator(`${selector} tbody tr`).first().allTextContents();
      assert(texts.join(' ').includes('nazk-record-001'),`${selector} must expose source_id`);
      assert(texts.join(' ').includes('07.10.2026') && texts.join(' ').includes('08.10.2026'),`${selector} base dates: ${texts.join('|')}`);
      assert(texts.join(' ').includes('09.10.2026'),`${selector} must format decree_date`);
    }
    for (const selector of ['main > table','section#profile table','.operational-registry-list table']) {
      const emptyTexts=await page.locator(`${selector} tbody tr`).nth(1).allTextContents();
      assert(emptyTexts.join(' ').includes('—'),`${selector} must render empty optional fields as a dash`);
    }
    for (const theme of ['light','dark']) {
      await page.evaluate(value => { document.documentElement.dataset.theme=value; },theme);
      assert.equal(await page.locator('main > table tbody tr').first().locator('td').count(),9);
      assert.equal(await page.locator('.operational-registry-list tbody tr').first().locator('td').count(),10);
      for(const selector of ['main > table','section#profile table','.operational-registry-list table'])
        assert((await page.locator(`${selector} th,${selector} td`).evaluateAll(cells=>cells.every(cell=>getComputedStyle(cell).display!=='none'))),
          `${selector} fields must remain visible in ${theme} theme`);
    }
    console.log('PASS NАЗК full-field browser contract: register 9, supplier profile 9, operational card 10; source IDs and dates present in light/dark modes');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode=1; });
