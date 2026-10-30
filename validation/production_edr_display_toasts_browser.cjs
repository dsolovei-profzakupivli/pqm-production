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
const cardDates = block('function supplierEdrDatesHtml(edr)', 'function nazkRegistrySourceNotice');
const applyFlow = block('async function startSupplierEdrSync()', 'function edrMonitoringParams');

(async () => {
  const browser = await chromium.launch({
    headless: true,
    ...(process.env.PQM_TEST_BROWSER ? { executablePath: process.env.PQM_TEST_BROWSER } : {}),
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
    const apply = await page.evaluate(async applyFlow => {
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
      const notices = [];
      let complete;
      const done = new Promise(resolve => { complete = resolve; });
      const nodes = new Map();
      globalThis.$ = selector => {
        if (!nodes.has(selector)) nodes.set(selector, { disabled: false, textContent: '', close() {} });
        return nodes.get(selector);
      };
      globalThis.toast = message => notices.push(message);
      globalThis.request = async (url, options = {}) => {
        if (options.method === 'POST') { applyRequests++; return { started: true }; }
        statusRequests++;
        return { state: { running: false, run_id: 'synthetic-run-1', error: null } };
      };
      globalThis.loadSupplierEdrStatus = async () => {};
      globalThis.loadQualifiedSuppliersFiltered = async () => { listReloads++; };
      globalThis.loadEdrMonitoring = async () => { monitorReloads++; complete(); };
      const originalSetTimeout = window.setTimeout.bind(window);
      window.setTimeout = (fn) => originalSetTimeout(fn, 0);
      new Function(`${applyFlow};return startSupplierEdrSync`)();
      const start = new Function(`${applyFlow};return startSupplierEdrSync`)();
      await Promise.all([start(), start()]);
      await Promise.race([done, new Promise((_, reject) => originalSetTimeout(() => reject(new Error('poll timeout')), 3000))]);
      globalThis.supplierEdrPreview = { source_fingerprint: 'a'.repeat(64), state_digest: 'b'.repeat(64) };
      globalThis.supplierEdrApplyInFlight = false;
      await start();
      await new Promise(resolve => originalSetTimeout(resolve, 20));
      return { applyRequests, statusRequests, listReloads, monitorReloads, notices };
    }, applyFlow);
    assert.equal(apply.applyRequests, 2, 'two explicit synthetic starts should each post once');
    assert.equal(apply.statusRequests, 2, 'each accepted run should use one completion poll');
    assert.equal(apply.listReloads, 2, 'one supplier-list refresh per run');
    assert.equal(apply.monitorReloads, 2, 'one EDR-monitor refresh per run');
    assert.deepEqual(apply.notices, ['Довідник постачальників з ЄДР оновлено'],
      'replayed completion with the same run id must not show a second toast');
    console.log('PASS: actual display functions light/dark timestamp/date-only/empty; Apply single-flight and one toast per run');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
