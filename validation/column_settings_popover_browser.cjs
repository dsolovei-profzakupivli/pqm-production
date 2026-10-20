const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
let chromium;
try { ({ chromium } = require('playwright')); }
catch { ({ chromium } = require('C:/Users/User/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright')); }

const root = path.resolve(process.env.PQM_TEST_ROOT || path.join(__dirname, '..'));
const environment = fs.readFileSync(path.join(root, 'index.html'), 'utf8').includes('data-pqm-halloween-target="production"') ? 'production' : 'sandbox';
const evidence = path.join(root, 'evidence', 'column-settings');
fs.mkdirSync(evidence, { recursive: true });

function htmlBody() {
  return fs.readFileSync(path.join(root, 'index.html'), 'utf8')
    .replace(/<script\s+src="[^"]+"[^>]*><\/script>/g, '')
    .replace(/<link\s+[^>]*rel="stylesheet"[^>]*>/g, '');
}

async function prepare(browser, { theme, halloween, width, height, zoom }) {
  const page = await browser.newPage({ viewport: { width, height } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setContent(htmlBody(), { waitUntil: 'load' });
  const source = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
  const styles = [...source.matchAll(/<link\s+[^>]*href="([^"]+\.css)"[^>]*>/g)].map(match => match[1]);
  for (const style of styles) {
    const target = path.join(root, style);
    if (fs.existsSync(target)) await page.addStyleTag({ path: target });
  }
  await page.evaluate(() => {
    const values = new Map();
    Object.defineProperty(window, 'localStorage', { configurable: true, value: { getItem: key => values.has(key) ? values.get(key) : null, setItem: (key, value) => values.set(String(key), String(value)), removeItem: key => values.delete(String(key)), clear: () => values.clear() } });
    if (!crypto.randomUUID) Object.defineProperty(crypto, 'randomUUID', { configurable: true, value: () => '00000000-0000-4000-8000-000000000001' });
  });
  if (fs.existsSync(path.join(root, 'halloween_motion.css'))) await page.addStyleTag({ path: path.join(root, 'halloween_motion.css') });
  await page.evaluate(({ theme, halloween, environment, zoom }) => {
    const html = document.documentElement;
    html.style.zoom = String(zoom);
    html.dataset.theme = theme;
    html.dataset.pqmEnvironment = environment;
    html.dataset.halloween = halloween ? 'on' : 'off';
    document.querySelector('#loginGate')?.setAttribute('hidden', '');
    const shell = document.querySelector('#applicationShell');
    if (shell) shell.hidden = false;
    document.querySelectorAll('main').forEach(main => { main.hidden = main.id !== 'applicationsView'; });
    document.querySelector('#applicationsView')?.classList.add('halloween-workspace');
    const tbody = document.querySelector('#applicationsTable tbody');
    if (tbody) tbody.innerHTML = Array.from({ length: 22 }, (_, i) => `<tr><td>${i + 1}</td><td>Контрольний запис ${i + 1}</td><td>Дані</td></tr>`).join('');
    window.__fetchCalls = [];
    window.fetch = (url, init = {}) => { window.__fetchCalls.push({ url: String(url), method: init.method || 'GET', body: init.body || '' }); return new Promise(() => {}); };
  }, { theme, halloween, environment, zoom });
  let popoverLoaded = false;
  const scripts = [...source.matchAll(/<script\s+src="([^"]+)"[^>]*><\/script>/g)].map(match => match[1]);
  for (const script of scripts) {
    if (script === 'app.js' && !popoverLoaded) {
      await page.addScriptTag({ path: path.join(root, 'registry_popovers.js') });
      popoverLoaded = true;
    }
    const target = path.join(root, script);
    if (!fs.existsSync(target)) continue;
    await page.addScriptTag({ path: target });
    if (script === 'registry_popovers.js') popoverLoaded = true;
  }
  if (!popoverLoaded) await page.addScriptTag({ path: path.join(root, 'registry_popovers.js') });
  await page.waitForTimeout(80);
  await page.evaluate(halloween => { document.documentElement.dataset.halloween = halloween ? 'on' : 'off'; }, halloween);
  await page.evaluate(() => {
    window.__lateGlobalListenerAdds = 0;
    const nativeAdd = EventTarget.prototype.addEventListener;
    EventTarget.prototype.addEventListener = function (...args) {
      if (this === document || this === window) window.__lateGlobalListenerAdds++;
      return nativeAdd.apply(this, args);
    };
  });
  return { page, errors };
}

async function assertVisibleAndClickable(page) {
  const state = await page.evaluate(() => {
    const owner = document.querySelector('.toolbar-settings');
    const anchor = owner.querySelector(':scope > summary');
    const panel = owner.querySelector(':scope > .toolbar-settings-panel');
    const r = panel.getBoundingClientRect();
    const a = anchor.getBoundingClientRect();
    const hit = document.elementFromPoint(Math.min(r.right - 5, r.left + 15), Math.min(r.bottom - 5, r.top + 15));
    return {
      open: owner.open,
      topLayer: panel.matches(':popover-open'),
      position: getComputedStyle(panel).position,
      overflow: getComputedStyle(panel).overflowY,
      rect: { left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width, height: r.height },
      anchor: { left: a.left, right: a.right, bottom: a.bottom },
      viewport: { width: document.documentElement.clientWidth, height: document.documentElement.clientHeight },
      hitPanel: panel.contains(hit),
      actionButtons: panel.querySelectorAll('button').length,
      panelCount: document.querySelectorAll('.toolbar-settings-panel').length,
    };
  });
  assert.equal(state.open, true, JSON.stringify(state));
  assert.equal(state.topLayer, true, JSON.stringify(state));
  assert.equal(state.position, 'fixed');
  assert.equal(state.overflow, 'auto');
  assert.equal(state.hitPanel, true, JSON.stringify(state));
  assert.equal(state.actionButtons, 6);
  assert.equal(state.panelCount, 1);
  assert(state.rect.left >= 0 && state.rect.right <= state.viewport.width, JSON.stringify(state));
  assert(state.rect.top >= 0 && state.rect.bottom <= state.viewport.height, JSON.stringify(state));
  const preferredRight = state.anchor.right - state.rect.width;
  if (preferredRight >= 8) assert(Math.abs(state.rect.right - state.anchor.right) <= 2, JSON.stringify(state));
  else assert(state.rect.left >= 8 && state.rect.left <= state.anchor.left + 2, JSON.stringify(state));
  return state;
}

async function openGear(page) {
  await page.locator('.toolbar-settings > summary').click();
  await page.waitForFunction(() => {
    const owner = document.querySelector('.toolbar-settings');
    const panel = owner?.querySelector(':scope > .toolbar-settings-panel');
    return owner?.open && panel?.matches(':popover-open');
  });
}

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.PQM_TEST_BROWSER || 'C:/Program Files/Google/Chrome/Application/chrome.exe' });
  let scenarios = 0;
  try {
    for (const theme of ['light', 'dark']) for (const halloween of [false, true]) for (const [width, height, zoom] of [[1600, 900, 1], [1100, 720, 1], [680, 420, 1], [420, 190, 1], [1600, 900, 0.8], [1600, 900, 1.25]]) {
      const { page, errors } = await prepare(browser, { theme, halloween, width, height, zoom });
      await page.locator('.toolbar-settings > summary').scrollIntoViewIfNeeded();
      const toolbarBefore = await page.locator('.applications-toolbar').boundingBox();
      const tableBefore = await page.locator('#tableScrollTop').evaluate(node => node.getBoundingClientRect().y + window.scrollY);
      await openGear(page);
      const state = await assertVisibleAndClickable(page);
      assert.equal((await page.locator('.applications-toolbar').boundingBox()).height, toolbarBefore.height, 'Opening the panel must not resize the toolbar');
      assert.equal(await page.locator('#tableScrollTop').evaluate(node => node.getBoundingClientRect().y + window.scrollY), tableBefore, 'Opening the panel must not move the table');
      if (height <= 190) {
        const scrollState = await page.locator('.toolbar-settings-panel').evaluate(panel => ({ scrollHeight: panel.scrollHeight, clientHeight: panel.clientHeight }));
        assert(scrollState.scrollHeight > scrollState.clientHeight, `Short viewport should scroll inside the panel: ${JSON.stringify(scrollState)}`);
        await page.locator('.toolbar-settings-panel').evaluate(panel => { panel.scrollTop = panel.scrollHeight; });
        assert(await page.locator('#columnsBtn').isVisible(), 'Last settings action remains reachable by scrolling');
      }
      if (theme === 'light' && width === 1600 && height === 900 && zoom === 1) await page.screenshot({ path: path.join(evidence, `${environment}-light-halloween-${halloween ? 'on' : 'off'}.png`) });
      if (theme === 'dark' && width === 1600 && height === 900 && zoom === 1) await page.screenshot({ path: path.join(evidence, `${environment}-dark-halloween-${halloween ? 'on' : 'off'}.png`) });

      if (!(await page.locator('.toolbar-settings').evaluate(node => node.open))) await openGear(page);
      await page.locator('#columnsBtn').click();
      const dialogState = await page.locator('#columnsDialog').evaluate(dialog => ({ open: dialog.open, onclickType: typeof document.querySelector('#columnsBtn').onclick }));
      assert.equal(dialogState.open, true, `Columns action should open its existing dialog; state=${JSON.stringify(dialogState)}; errors=${errors.join('; ')}`);
      assert.equal(await page.locator('.toolbar-settings').evaluate(node => node.open), false, 'Selecting a settings action should close the gear panel');
      await page.evaluate(() => window.eval(`loading = false; rows = [{id:'column-settings-fixture',participant:'Тестовий учасник',edrpou:'12345678',documents:[],registryDocuments:[],decision:'Очікує рішення',protocolDecision:'',marketplaceDecision:'',complianceStatus:'',documentCheckCategories:{},nazkPresentationState:''}]; total = 1; pages = 1; render();`));
      await page.evaluate(() => window.eval(`profiles[0].id = 'synthetic-column-profile'; profiles[0].is_system = false; activeProfileId = 'synthetic-column-profile'; localStorage.setItem('pqm.server.activeProfile.v2', activeProfileId);`));
      const visible = page.locator('#columnsList .column-item[data-key="participant"] .col-visible');
      assert.equal(await visible.count(), 1, 'The participant column is available in the real settings dialog');
      const columnState = async () => page.evaluate(() => ({
        selectedProfile: localStorage.getItem('pqm.server.activeProfile.v2'),
        columns: window.profile().columns.map(({ key, visible, width, order }) => ({ key, visible, width, order })),
        header: Boolean(document.querySelector('#applicationsTable thead th[data-column-key="participant"]')),
        rowCell: Boolean(document.querySelector('#applicationsTable tbody td[data-column-key="participant"]')),
        scroll: { client: document.querySelector('#tableScroll').clientWidth, total: document.querySelector('#tableScroll').scrollWidth, left: document.querySelector('#tableScroll').scrollLeft }
      }));
      const beforeColumns = await columnState();
      if (beforeColumns.scroll.total > beforeColumns.scroll.client) {
        await page.locator('#tableScroll').evaluate(node => { node.scrollLeft = Math.min(120, node.scrollWidth - node.clientWidth); });
      }
      await visible.click();
      await page.waitForFunction(() => !document.querySelector('#applicationsTable thead th[data-column-key="participant"]'));
      assert.equal(await visible.isChecked(), false, 'Hiding a column updates its checkbox');
      await page.waitForTimeout(300);
      const hiddenSave = await page.evaluate(() => window.__fetchCalls.filter(call => call.method === 'PATCH' && call.url.includes('/api/application-profiles/synthetic-column-profile')).at(-1));
      assert(hiddenSave, 'Hiding a column saves the existing profile layout');
      assert.equal(JSON.parse(hiddenSave.body).columns.find(column => column.key === 'participant').visible, false, 'Saved layout records the hidden column');
      const hiddenColumns = await columnState();
      assert.equal(hiddenColumns.header, false, 'Hidden column disappears from the rendered table');
      assert.equal(hiddenColumns.rowCell, false, 'Hidden column cells disappear from rendered rows');
      for (const key of ['number', 'edrpou', 'clarity']) {
        const old = beforeColumns.columns.find(column => column.key === key);
        const current = hiddenColumns.columns.find(column => column.key === key);
        assert.deepEqual({ width: current.width, order: current.order, visible: current.visible }, { width: old.width, order: old.order, visible: old.visible }, `Unrelated column ${key} keeps its saved layout`);
      }
      assert.equal(hiddenColumns.selectedProfile, beforeColumns.selectedProfile, 'Active saved profile is not changed');
      assert.equal(hiddenColumns.scroll.total > hiddenColumns.scroll.client, beforeColumns.scroll.total > beforeColumns.scroll.client, 'Horizontal overflow remains in the same state after hiding a column');
      await visible.click();
      await page.waitForFunction(() => Boolean(document.querySelector('#applicationsTable thead th[data-column-key="participant"]')));
      assert.equal(await visible.isChecked(), true, 'Re-enabling a column updates its checkbox');
      await page.waitForTimeout(300);
      const restoredSave = await page.evaluate(() => window.__fetchCalls.filter(call => call.method === 'PATCH' && call.url.includes('/api/application-profiles/synthetic-column-profile')).at(-1));
      assert(restoredSave, 'Re-enabling a column saves the existing profile layout');
      assert.equal(JSON.parse(restoredSave.body).columns.find(column => column.key === 'participant').visible, true, 'Saved layout records the restored column');
      const restoredColumns = await columnState();
      assert.equal(restoredColumns.header, true, 'Re-enabled column returns to the table');
      assert.equal(restoredColumns.rowCell, true, 'Re-enabled column cells return to rows');
      const beforeParticipant = beforeColumns.columns.find(column => column.key === 'participant');
      const restoredParticipant = restoredColumns.columns.find(column => column.key === 'participant');
      assert.deepEqual({ width: restoredParticipant.width, order: restoredParticipant.order }, { width: beforeParticipant.width, order: beforeParticipant.order }, 'Restoring a column keeps its width and order');
      assert(restoredColumns.scroll.total > restoredColumns.scroll.client, 'The table retains horizontal scrolling after column updates');
      const scrollAfterRestore = await page.locator('#tableScroll').evaluate(node => ({ left: node.scrollLeft, maximum: Math.max(0, node.scrollWidth - node.clientWidth) }));
      assert.equal(scrollAfterRestore.left, Math.min(120, scrollAfterRestore.maximum), 'Horizontal scrolling remains operable after restoring the column');
      await page.keyboard.press('Escape');
      assert.equal(await page.locator('#columnsDialog').evaluate(dialog => dialog.open), false, 'Escape closes the columns dialog');
      if (halloween && zoom === 1 && width === 1600 && height === 900) {
        await page.locator('#marketplaceDecisionFilter > summary').click();
        assert.equal(await page.locator('.toolbar-settings').evaluate(node => node.open), false, 'Opening another filter closes the settings panel');
        assert.equal(await page.locator('#marketplaceDecisionFilter').evaluate(node => node.open), true, 'Other dropdown remains interactive');
        assert.equal(await page.locator('#marketplaceDecisionFilter input[value="__empty__"]').isVisible(), true, 'Other dropdown options remain visible and available');
        await page.locator('#marketplaceDecisionFilter > summary').click();
        assert.equal(await page.locator('#marketplaceDecisionFilter').evaluate(node => node.open), false, 'Escape closes the other dropdown');
      }

      for (let cycle = 0; cycle < 3; cycle++) {
        await openGear(page);
        await assertVisibleAndClickable(page);
        await page.keyboard.press('Tab');
        await page.keyboard.press('Escape');
        assert.equal(await page.locator('.toolbar-settings').evaluate(node => node.open), false, 'Escape closes the gear panel');
        assert.equal(await page.locator('.toolbar-settings > summary').evaluate(node => document.activeElement === node), true, 'Escape returns focus to the gear');
      }

      await openGear(page);
      await page.locator('#suppliersNav').click();
      await page.waitForFunction(() => !document.querySelector('.toolbar-settings')?.open);
      assert.equal(await page.evaluate(() => window.__lateGlobalListenerAdds), 0, 'Reopening does not accumulate global event listeners');
      await page.locator('#applicationsNav').click();
      await page.waitForFunction(() => !document.querySelector('#applicationsView')?.hidden);

      await openGear(page);
      await assertVisibleAndClickable(page);
      await page.evaluate(() => { document.querySelector('#tableScroll').scrollTop = 150; document.querySelector('#tableScroll').dispatchEvent(new Event('scroll')); });
      await page.setViewportSize({ width: Math.max(360, width - 70), height: Math.max(260, height - 80) });
      await page.waitForTimeout(40);
      const resized = await page.evaluate(() => {
        const panel = document.querySelector('.toolbar-settings-panel'), r = panel.getBoundingClientRect();
        const p = { x: Math.min(r.right - 5, r.left + 12), y: Math.min(r.bottom - 5, r.top + 12) };
        return { open: panel.matches(':popover-open'), hit: panel.contains(document.elementFromPoint(p.x, p.y)), right: r.right, bottom: r.bottom, width: document.documentElement.clientWidth, height: document.documentElement.clientHeight };
      });
      assert(resized.open && resized.hit && resized.right <= resized.width && resized.bottom <= resized.height, `Scroll/resize placement: ${JSON.stringify(resized)}`);
      await page.mouse.click(8, 8);
      assert.equal(await page.locator('.toolbar-settings').evaluate(node => node.open), false, 'Pointer outside closes the gear panel');
      assert.deepEqual(errors, [], `Browser errors: ${errors.join('; ')}`);
      scenarios++;
      await page.close();
      void state;
    }
    console.log(`COLUMN_SETTINGS_POPOVER_BROWSER=PASS environment=${environment} scenarios=${scenarios}`);
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
