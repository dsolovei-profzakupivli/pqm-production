const assert = require('node:assert/strict');
const fs = require('node:fs');
const { chromium } = (() => {
  try { return require('playwright'); }
  catch { return require('C:/Users/User/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'); }
})();

const source = fs.readFileSync('app.js', 'utf8');
const cell = source.match(/<td>\$\{esc\(x\.punishment\|\|'—'\)\}<\/td>/);
assert(cell, 'Supplier card must render the API punishment value or an em dash');
const renderCell = new Function('x', 'esc', `return \`${cell[0]}\`;`);
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const htmlRows = [
  {punishment:'Визнано винним; призначено штраф.'},
  {punishment:''},
].map(row => renderCell(row, escapeHtml));
const tableRows = htmlRows.map(row => `<tr>${row}</tr>`);

(async () => {
  const browser = await chromium.launch({
    headless: true,
    ...(process.env.PQM_TEST_BROWSER ? { executablePath: process.env.PQM_TEST_BROWSER } : {}),
  });
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.setContent(`<!doctype html><meta charset="utf-8"><body><table><tbody id="rows"></tbody></table></body>`);
    const visible = await page.evaluate(rows => {
      const tbody = document.querySelector('#rows');
      tbody.innerHTML = rows.join('');
      return [...tbody.rows].map(row => row.cells[0].textContent.trim());
    }, tableRows);
    assert.deepEqual(visible, ['Визнано винним; призначено штраф.', '—']);
    assert.deepEqual(errors, []);
    console.log('PASS supplier card renders punishment text and — for an empty value');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
