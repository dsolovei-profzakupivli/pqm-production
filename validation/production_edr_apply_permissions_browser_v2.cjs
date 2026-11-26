/* Browser regression for Production EDR Preview-only copy and theme behavior. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const app = fs.readFileSync(path.resolve(__dirname, '..', 'app.js'), 'utf8').replaceAll('\r\n', '\n');
function sourceBetween(startText, endText) {
  const start = app.indexOf(startText);
  const end = app.indexOf(endText, start);
  assert.ok(start >= 0 && end > start, `${startText} source exists`);
  return app.slice(start, end);
}
const previewFunction = sourceBetween('async function previewSupplierEdrSync()', '\nfunction renderSupplierEdrReviewDetails()');
const detailFunction = sourceBetween('function renderSupplierEdrReviewDetails()', '\nfunction showSupplierEdrApplyResult(');
const exportFunction = sourceBetween('async function downloadSupplierEdrConflicts()', '\nfunction showSupplierEdrApplyResult(');
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
      for (const conflicts of [0, 1]) {
        await page.setContent(`<!doctype html><html data-theme="${theme}"><body>
          <button id="supplierEdrSync">Preview</button><dialog id="supplierEdrPreviewDialog">
            <div id="supplierEdrPreviewBody"></div><button id="supplierEdrPreviewApply" type="button">Підтвердити та застосувати</button>
          </dialog></body></html>`);
        const observed = await page.evaluate(async ({ labelsDeclaration, previewFunction, detailFunction, exportFunction, conflicts }) => {
          globalThis.API = '/api';
          globalThis.supplierEdrReviewCategory = 'all';
          globalThis.supplierEdrReviewSearch = '';
          globalThis.supplierEdrReviewPage = 1;
          globalThis.supplierEdrPreview = null;
          globalThis.$ = selector => document.querySelector(selector);
          globalThis.esc = value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;');
          globalThis.toast = () => {};
          const exportRequests = [];
          globalThis.fetch = async (url, options) => {
            exportRequests.push({ url, options });
            return { ok: true, blob: async () => new Blob(['synthetic xlsx']) };
          };
          globalThis.URL.createObjectURL = () => 'blob:synthetic-xlsx';
          globalThis.URL.revokeObjectURL = () => {};
          const requests = [];
          globalThis.request = async url => {
            requests.push(url);
            return { apply_enabled: false, apply_available: false, partial_apply_enabled: true,
              source_fingerprint: 'f'.repeat(64), state_digest: 'd'.repeat(64), conflicts_total: conflicts,
              summary: { ready_to_apply: 1, ready_with_changes: 1, ready_unchanged: 0, skipped: 0 },
              details: [{ supplier_code: '12345678', supplier_name: 'Тест', field: 'Примітка', action: 'update',
                current_pqm_value: '', google_value: 'текст', planned_pqm_value: 'текст' }], details_total: 1, details_complete: true };
          };
          globalThis.loadSupplierEdrStatus = async () => ({ enabled: true });
          const renderer = new Function(`${labelsDeclaration};${previewFunction};${detailFunction};${exportFunction};return previewSupplierEdrSync;`)();
          await renderer();
          const apply = document.querySelector('#supplierEdrPreviewApply');
          const dialog = document.querySelector('#supplierEdrPreviewDialog');
          const body = document.querySelector('#supplierEdrPreviewBody');
          const note = body.querySelector('[role="status"]');
          const exportButton = document.querySelector('#supplierEdrConflictDownload');
          const exportHandlerPresent = !!exportButton?.onclick;
          if (exportButton?.onclick) await exportButton.onclick();
          apply.click();
          return { disabled: apply.disabled, title: apply.title, dialogOpen: dialog.open,
            note: note?.textContent, text: body.textContent, exportButtonPresent: !!exportButton,
            exportHandlerPresent, exportRequests,
            requests, theme: document.documentElement.dataset.theme };
        }, { labelsDeclaration, previewFunction, detailFunction, exportFunction, conflicts });

        assert.equal(observed.disabled, true, `${theme}, conflicts=${conflicts}: Apply is disabled`);
        assert.equal(observed.title, 'Режим лише перегляду. Застосування змін вимкнено');
        assert.equal(observed.dialogOpen, true, `${theme}, conflicts=${conflicts}: Preview remains open`);
        assert.equal(observed.note, 'Режим лише перегляду. Застосування змін вимкнено');
        assert.match(observed.text, /Записи без конфліктів · рядки/);
        assert.match(observed.text, /Записи зі змінами · рядки/);
        assert.doesNotMatch(observed.text, /Готові до застосування|Готові зі змінами|Застосуються лише готові|можна застосувати|можна застосувати/i);
        assert.match(observed.text, /Планове значення/);
        assert.doesNotMatch(observed.text, /Після Apply/);
        if (conflicts) {
          assert.equal(observed.exportButtonPresent, true, `${theme}: conflict XLSX remains available`);
          assert.equal(observed.exportHandlerPresent, true, `${theme}: conflict XLSX has a handler`);
          assert.equal(observed.exportRequests.length, 1, `${theme}: XLSX action remains usable`);
          assert.equal(observed.exportRequests[0].url, '/api/supplier-edr-sync/conflicts.xlsx');
          assert.equal(observed.exportRequests[0].options.method, 'POST');
          assert.match(observed.text, /Конфліктні рядки показані окремо\. Інші записи наведені для перегляду\./);
        } else {
          assert.equal(observed.exportButtonPresent, false);
          assert.match(observed.text, /Конфліктів немає\. Результати записів зі змінами та без змін наведені для перегляду\./);
        }
        assert.deepEqual(observed.requests, ['/api/supplier-edr-sync/preview'], 'No Apply request was sent');
        assert.equal(observed.theme, theme);
        console.log(`PASS Preview-only copy · ${theme} theme · conflicts=${conflicts}`);
      }

      await page.setContent(`<!doctype html><html data-theme="${theme}"><body>
        <button id="supplierEdrSync">Preview</button><dialog id="supplierEdrPreviewDialog">
          <div id="supplierEdrPreviewBody"></div><button id="supplierEdrPreviewApply" type="button">Підтвердити та застосувати</button>
        </dialog></body></html>`);
      const applyMode = await page.evaluate(async ({ labelsDeclaration, previewFunction, detailFunction, exportFunction }) => {
        globalThis.API = '/api'; globalThis.supplierEdrReviewCategory = 'all';
        globalThis.supplierEdrReviewSearch = ''; globalThis.supplierEdrReviewPage = 1; globalThis.supplierEdrPreview = null;
        globalThis.$ = selector => document.querySelector(selector);
        globalThis.esc = value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;');
        globalThis.toast = () => {}; globalThis.downloadSupplierEdrConflicts = async () => {};
        globalThis.request = async () => ({ apply_enabled: true, apply_available: true, partial_apply_enabled: true,
          source_fingerprint: 'f'.repeat(64), state_digest: 'd'.repeat(64), conflicts_total: 0,
          summary: { ready_to_apply: 1, ready_with_changes: 1 }, details: [], details_total: 0, details_complete: true });
        globalThis.loadSupplierEdrStatus = async () => ({ enabled: true });
        const renderer = new Function(`${labelsDeclaration};${previewFunction};${detailFunction};${exportFunction};return previewSupplierEdrSync;`)();
        await renderer();
        return { disabled: document.querySelector('#supplierEdrPreviewApply').disabled,
          text: document.querySelector('#supplierEdrPreviewBody').textContent };
      }, { labelsDeclaration, previewFunction, detailFunction, exportFunction });
      assert.equal(applyMode.disabled, false, `${theme}: allowed Apply remains available`);
      assert.match(applyMode.text, /Готові до застосування · рядки/);
      assert.match(applyMode.text, /Застосуються лише готові записи після явного підтвердження\./);
      console.log(`PASS allowed Apply wording preserved · ${theme} theme`);
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
