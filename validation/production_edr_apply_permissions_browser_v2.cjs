/* Browser regression for the Production EDR read-only Preview mode. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const app = fs.readFileSync(path.resolve(__dirname, '..', 'app.js'), 'utf8').replaceAll('\r\n', '\n');
const start = app.indexOf('async function previewSupplierEdrSync()');
const end = app.indexOf('\nfunction renderSupplierEdrReviewDetails()', start);
assert.ok(start >= 0 && end > start, 'Production EDR Preview renderer exists');
const previewFunction = app.slice(start, end);
const labelsStart = app.indexOf('const supplierEdrMetricLabels=');
const labelsEnd = app.indexOf(';', labelsStart);
assert.ok(labelsStart >= 0 && labelsEnd > labelsStart, 'Preview metric labels exist');
const labelsDeclaration = app.slice(labelsStart, labelsEnd + 1);

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...((process.env.PQM_TEST_BROWSER || process.env.PQM_CHROMIUM_EXECUTABLE)
      ? { executablePath: process.env.PQM_TEST_BROWSER || process.env.PQM_CHROMIUM_EXECUTABLE } : {}) });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    for (const theme of ['light', 'dark']) {
      await page.setContent(`<!doctype html><html data-theme="${theme}"><body>
        <button id="supplierEdrSync">Preview</button><dialog id="supplierEdrPreviewDialog">
          <div id="supplierEdrPreviewBody"></div><button id="supplierEdrPreviewApply" type="button">Підтвердити та застосувати</button>
        </dialog></body></html>`);
      const observed = await page.evaluate(async ({ labelsDeclaration, previewFunction }) => {
        globalThis.API = '/api';
        globalThis.supplierEdrReviewCategory = 'all';
        globalThis.supplierEdrReviewSearch = '';
        globalThis.supplierEdrReviewPage = 1;
        globalThis.$ = selector => document.querySelector(selector);
        globalThis.esc = value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;');
        globalThis.toast = () => {};
        globalThis.renderSupplierEdrReviewDetails = () => {};
        let exportRequests = 0;
        globalThis.downloadSupplierEdrConflicts = async () => { exportRequests++; };
        const requests = [];
        globalThis.request = async url => {
          requests.push(url);
          return { apply_enabled: false, apply_available: false, partial_apply_enabled: true,
            source_fingerprint: 'f'.repeat(64), state_digest: 'd'.repeat(64), conflicts_total: 1,
            summary: { ready_to_apply: 1 }, details: [], details_complete: true };
        };
        globalThis.loadSupplierEdrStatus = async () => ({ enabled: true });
        const renderer = new Function(`${labelsDeclaration};${previewFunction};return previewSupplierEdrSync;`)();
        await renderer();
        const apply = document.querySelector('#supplierEdrPreviewApply');
        const dialog = document.querySelector('#supplierEdrPreviewDialog');
        const note = document.querySelector('#supplierEdrPreviewBody [role="status"]');
        const exportButton = document.querySelector('#supplierEdrConflictDownload');
        exportButton.click();
        await Promise.resolve();
        apply.click();
        return { disabled: apply.disabled, title: apply.title, dialogOpen: dialog.open,
          note: note?.textContent, exportButtonPresent: !!exportButton, exportRequests,
          requests, theme: document.documentElement.dataset.theme };
      }, { labelsDeclaration, previewFunction });
      assert.equal(observed.disabled, true, `${theme}: Apply is disabled`);
      assert.equal(observed.title, 'Режим лише перегляду. Застосування змін вимкнено');
      assert.equal(observed.dialogOpen, true, `${theme}: Preview remains open`);
      assert.equal(observed.note, 'Режим лише перегляду. Застосування змін вимкнено');
      assert.equal(observed.exportButtonPresent, true, `${theme}: conflict XLSX remains available`);
      assert.equal(observed.exportRequests, 1, `${theme}: XLSX action remains usable`);
      assert.deepEqual(observed.requests, ['/api/supplier-edr-sync/preview'], 'No Apply request was sent');
      assert.equal(observed.theme, theme);
      console.log(`PASS Production EDR read-only Preview · ${theme} theme`);
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
