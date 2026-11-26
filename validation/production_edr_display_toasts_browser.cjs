/* Isolated browser regression for Production EDR timestamp display and Apply polling. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const root = path.resolve(__dirname, '..');
const app = fs.readFileSync(path.join(root, 'app.js'), 'utf8').replaceAll('\r\n', '\n');
const oneLine = name => {
  const line = app.split('\n').find(value => value.startsWith(`function ${name}(`));
  assert.ok(line, `missing ${name}`);
  return line;
};
const block = (start, end) => {
  const from = app.indexOf(start);
  const to = app.indexOf(end, from);
  assert.ok(from >= 0 && to > from, `missing block ${start}`);
  return app.slice(from, to).trim();
};

const displayDate = oneLine('displayDate');
const displayDateOnly = oneLine('displayDateOnly');
const profile = oneLine('openSupplierProfile');
const resultModal = block('function showSupplierEdrApplyResult(state)', 'function supplierEdrErrorUk');
const errorMessage = block('function supplierEdrErrorUk(message)', 'async function startSupplierEdrSync');
const cardDates = block('function supplierEdrDatesHtml(edr)', 'function nazkRegistrySourceNotice');
const applyFlow = block('async function startSupplierEdrSync()', 'function edrMonitoringParams');

(async () => {
  const browser = await chromium.launch({
    headless: true,
    ...((process.env.PQM_TEST_BROWSER || process.env.PQM_CHROMIUM_EXECUTABLE)
      ? { executablePath: process.env.PQM_TEST_BROWSER || process.env.PQM_CHROMIUM_EXECUTABLE } : {}),
  });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    for (const theme of ['light', 'dark']) {
      await page.setContent('<html><body><div id="card"></div><div id="profile"></div></body></html>');
      const rendered = await page.evaluate(({ displayDate, displayDateOnly, profile, cardDates, theme }) => {
        document.documentElement.dataset.theme = theme;
        const all = new Function(`${displayDate};${displayDateOnly};return {displayDate,displayDateOnly}`)();
        globalThis.displayDate = all.displayDate;
        globalThis.displayDateOnly = all.displayDateOnly;
        globalThis.esc = value => String(value ?? '');
        globalThis.displayEdrStatus = value => value || '';
        globalThis.supplierRegistryItems = [{
          code: '38261938', name: 'Synthetic supplier', current_manager: 'Synthetic manager',
          edr_verification_timestamp: '2026-10-29T16:50:41+02:00',
          edr_verification_date: '2026-10-29', edr_verification_officer: '',
          edr_profile: { short_name: 'Synthetic supplier', full_name: 'Synthetic supplier',
            edr_checked_at: '2026-10-29T16:50:41+02:00', synced_at: '', edr_status: 'active' },
        }];
        const nodes = new Map();
        globalThis.$ = selector => {
          if (!nodes.has(selector)) nodes.set(selector, { textContent: '', innerHTML: '', disabled: false,
            close() {}, showModal() { this.opened = true; } });
          return nodes.get(selector);
        };
        new Function(`${profile};${cardDates};return {openSupplierProfile,supplierEdrDatesHtml}`)();
        const helpers = new Function(`${profile};${cardDates};return {openSupplierProfile,supplierEdrDatesHtml}`)();
        document.querySelector('#card').innerHTML = helpers.supplierEdrDatesHtml(supplierRegistryItems[0].edr_profile);
        helpers.openSupplierProfile('38261938');
        document.querySelector('#profile').innerHTML = $('#supplierProfileBody').innerHTML;
        const empty = all.displayDate('');
        return {
          card: document.querySelector('#card').innerText,
          profile: document.querySelector('#profile').innerText,
          timestamp: all.displayDate('2026-10-29T16:50:41+02:00'),
          dateOnly: all.displayDate('2026-10-29'),
          empty,
          theme: document.documentElement.dataset.theme,
        };
      }, { displayDate, displayDateOnly, profile, cardDates, theme });
      assert.equal(rendered.timestamp, '29.10.2026, 16:50');
      assert.equal(rendered.dateOnly, '29.10.2026');
      assert.equal(rendered.empty, '');
      assert.match(rendered.card, /29\.10\.2026, 16:50/);
      assert.match(rendered.profile, /29\.10\.2026, 16:50/);
      assert.equal(rendered.theme, theme);
    }

    await page.setContent('<html><body></body></html>');
    const apply = await page.evaluate(async ({ applyFlow, resultModal, errorMessage }) => {
      globalThis.API = '/api';
      globalThis.supplierEdrTimer = null;
      globalThis.supplierEdrPreview = { source_fingerprint: 'a'.repeat(64), state_digest: 'b'.repeat(64) };
      globalThis.supplierEdrReconnectRequired = false;
      globalThis.supplierEdrApplyInFlight = false;
      globalThis.activeModule = 'edrMonitoring';
      globalThis.confirm = () => true;
      window.confirm = () => true;
      const storage = new Map();
      Object.defineProperty(window, 'localStorage', { configurable: true, value: {
        getItem: key => storage.get(key) ?? null,
        setItem: (key, value) => storage.set(key, String(value)),
      } });
      let applyRequests = 0, statusRequests = 0, listReloads = 0, monitorReloads = 0;
      const outcomes = [
        { last_result: 'completed', result_summary: { ready_to_apply: 3, inserted: 1, updated: 1, unchanged: 1, skipped_conflicts: 0, errors: 0, elapsed_seconds: 2.5 } },
        { last_result: 'completed', result_summary: { ready_to_apply: 3, inserted: 1, updated: 1, unchanged: 0, skipped_conflicts: 1, errors: 0, elapsed_seconds: 3.1 } },
        { last_result: 'failed', error: 'synthetic Apply failure', result_summary: { ready_to_apply: 3, inserted: 0, updated: 0, unchanged: 0, skipped_conflicts: 0, errors: 1, error: 'synthetic Apply failure', elapsed_seconds: 1.2 } },
      ];
      const shown = [];
      let releaseFinalPoll = null;
      const nodes = new Map();
      globalThis.$ = selector => {
        if (!nodes.has(selector)) nodes.set(selector, { disabled: false, hidden: true,
          textContent: '', innerHTML: '', dataset: {}, attributes: {}, close() { this.opened = false; },
          showModal() { this.opened = true; },
          setAttribute(name, value) { this.attributes[name] = String(value); },
          removeAttribute(name) { delete this.attributes[name]; } });
        return nodes.get(selector);
      };
      globalThis.esc = value => String(value ?? '');
      new Function(`${resultModal};${errorMessage};globalThis.showSupplierEdrApplyResult=showSupplierEdrApplyResult;globalThis.supplierEdrErrorUk=supplierEdrErrorUk;`)();
      globalThis.request = async (url, options = {}) => {
        if (options.method === 'POST') { applyRequests++; return { started: true }; }
        statusRequests++;
        if (statusRequests % 2 === 1) return { state: { running: true, run_id: `synthetic-run-${Math.ceil(statusRequests / 2)}`,
          message: 'Застосування Google → PQM', processed: 1, progress_total: 3, elapsed_seconds: 2.5 } };
        await new Promise(resolve => { releaseFinalPoll = resolve; });
        return { state: outcomes[(Math.floor(statusRequests / 2) - 1) % outcomes.length] };
      };
      globalThis.loadSupplierEdrStatus = async () => {
        $('#edrMonitoringSync').disabled = false;
        $('#supplierEdrSync').disabled = false;
      };
      globalThis.loadQualifiedSuppliersFiltered = async () => { listReloads++; };
      globalThis.loadEdrMonitoring = async () => { monitorReloads++; };
      const originalSetTimeout = window.setTimeout.bind(window);
      window.setTimeout = (fn) => originalSetTimeout(fn, 0);
      const start = new Function(`${applyFlow};return startSupplierEdrSync`)();
      for (const theme of ['light', 'dark']) {
        document.documentElement.dataset.theme = theme;
        for (let outcomeIndex = 0; outcomeIndex < outcomes.length; outcomeIndex++) {
          const beforeRequests = applyRequests;
          globalThis.supplierEdrPreview = { source_fingerprint: 'a'.repeat(64), state_digest: 'b'.repeat(64) };
          if (theme === 'light' && outcomeIndex === 0) await Promise.all([start(), start()]);
          else await start();
          for (let attempt = 0; attempt < 100 && nodes.get('#supplierEdrProgress')?.hidden !== false; attempt++)
            await new Promise(resolve => originalSetTimeout(resolve, 1));
          for (let attempt = 0; attempt < 100 && !releaseFinalPoll; attempt++)
            await new Promise(resolve => originalSetTimeout(resolve, 1));
          const busyDuringApply = {
            flag: globalThis.supplierEdrApplyInFlight,
            button: $('#edrMonitoringSync').attributes['aria-busy'],
            buttonDisabled: $('#edrMonitoringSync').disabled,
            progressVisible: !$('#supplierEdrProgress').hidden,
            progressText: $('#supplierEdrProgress').textContent,
          };
          if (!releaseFinalPoll) throw new Error('final status poll did not start');
          releaseFinalPoll(); releaseFinalPoll = null;
          const expectedApply = beforeRequests + 1;
          for (let attempt = 0; attempt < 100 && monitorReloads < expectedApply; attempt++)
            await new Promise(resolve => originalSetTimeout(resolve, 1));
          const dialog = $('#supplierEdrApplyResultDialog');
          shown.push({ theme, outcomeIndex, result: dialog.dataset.result,
            title: $('#supplierEdrApplyResultTitle').textContent,
            body: $('#supplierEdrApplyResultBody').innerHTML,
            open: dialog.opened, busyAfter: globalThis.supplierEdrApplyInFlight,
            syncBusyAfter: $('#edrMonitoringSync').attributes['aria-busy'] || null,
            applyBusyAfter: $('#supplierEdrSync').attributes['aria-busy'] || null,
            progressHiddenAfter: $('#supplierEdrProgress').hidden,
            buttonEnabledAfter: !$('#edrMonitoringSync').disabled,
            busyDuringApply,
            theme: document.documentElement.dataset.theme,
          });
        }
      }
      return { applyRequests, statusRequests, listReloads, monitorReloads, shown };
    }, { applyFlow, resultModal, errorMessage });
    assert.equal(apply.applyRequests, 6, 'one Apply request per accepted run');
    assert.equal(apply.statusRequests, 12, 'each run reports progress then its final result');
    assert.equal(apply.listReloads, 6, 'one supplier-list refresh per completed run');
    assert.equal(apply.monitorReloads, 6, 'one EDR-monitor refresh per completed run');
    for (const result of apply.shown) {
      assert.equal(result.open, true, `${result.theme} result dialog stays open until user closes it`);
      assert.equal(result.busyAfter, false, `${result.theme} completed operation releases single-flight lock`);
      assert.equal(result.syncBusyAfter, null, `${result.theme} monitoring button clears aria-busy`);
      assert.equal(result.applyBusyAfter, null, `${result.theme} apply button clears aria-busy`);
      assert.equal(result.progressHiddenAfter, true, `${result.theme} progress indicator hides after completion`);
      assert.equal(result.buttonEnabledAfter, true, `${result.theme} monitoring button is available again`);
      assert.equal(result.busyDuringApply.flag, true, `${result.theme} duplicate start is locked while Apply runs`);
      assert.equal(result.busyDuringApply.button, 'true', `${result.theme} busy control exposes aria-busy`);
      assert.equal(result.busyDuringApply.buttonDisabled, true, `${result.theme} repeated Apply is disabled while running`);
      assert.equal(result.busyDuringApply.progressVisible, true, `${result.theme} progress indicator is visible while running`);
      assert.match(result.busyDuringApply.progressText, /1 із 3/);
    }
    for (const theme of ['light', 'dark']) {
      const results = apply.shown.filter(value => value.theme === theme);
      assert.deepEqual(results.map(value => value.result), ['success', 'partial', 'error']);
      assert.match(results[1].body, /Пропущено конфліктів/);
      assert.match(results[2].body, /synthetic Apply failure/);
    }
    console.log('PASS: actual display functions in light/dark; progress, single-flight, success/partial/error persistent modals and busy-state reset');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
