const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { chromium } = require('playwright');

const root = path.resolve(process.env.PQM_TARGET_ROOT || path.join(__dirname, '..'));
const evidence = path.join(root, 'evidence');
fs.mkdirSync(evidence, { recursive: true });

const allowedScripts = new Set([
  'registry_popovers.js',
  'halloween_season.js',
  'halloween.js',
  'halloween_motion.js',
]);
function indexBody() {
  return fs.readFileSync(path.join(root, 'index.html'), 'utf8')
    .replace(/<script\s+src="[^"]+"[^>]*><\/script>/g, '')
    .replace(/<link\s+[^>]*rel="stylesheet"[^>]*>/g, '');
}

async function prepare(page, { theme, halloween, view = 'applicationsView' }) {
  await page.setContent(indexBody(), { waitUntil: 'load' });
  const source = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
  const styles = [...source.matchAll(/<link\s+[^>]*href="([^"]+\.css)"[^>]*>/g)].map(match => match[1]);
  for (const style of styles) {
    const target = path.join(root, style);
    if (fs.existsSync(target)) await page.addStyleTag({ path: target });
  }
  for (const script of allowedScripts) {
    const target = path.join(root, script);
    if (fs.existsSync(target)) await page.addScriptTag({ path: target });
  }
  await page.evaluate(({ theme, halloween, view }) => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.dataset.halloween = halloween ? 'on' : 'off';
    document.querySelector('#loginGate')?.setAttribute('hidden', '');
    const shell = document.querySelector('#applicationShell');
    if (shell) shell.hidden = false;
    document.querySelectorAll('main').forEach(main => { main.hidden = main.id !== view; });
    const target = document.getElementById(view);
    if (target) target.hidden = false;
    const tbody = document.querySelector('#applicationsTable tbody');
    if (tbody) tbody.innerHTML = Array.from({ length: 28 }, (_, i) => `<tr><td>${i + 1}</td><td>Контрольний запис ${i + 1}</td><td>Дані</td></tr>`).join('');
    window.dispatchEvent(new Event('resize'));
  }, { theme, halloween, view });
  await page.waitForTimeout(120);
}

async function openAndMeasure(page, detailsSelector, panelSelector) {
  await page.locator(`${detailsSelector} > summary`).click();
  await page.waitForTimeout(40);
  return page.evaluate(({ detailsSelector, panelSelector }) => {
    const details = document.querySelector(detailsSelector);
    const panel = document.querySelector(panelSelector);
    const rect = panel.getBoundingClientRect();
    const point = { x: rect.left + Math.min(24, rect.width / 2), y: rect.top + Math.min(24, rect.height / 2) };
    const hit = document.elementFromPoint(point.x, point.y);
    return {
      detailsOpen: details.open,
      topLayer: panel.matches(':popover-open'),
      parentPreserved: panel.parentElement === details,
      rect: { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom },
      viewport: { width: innerWidth, height: innerHeight },
      hitInside: panel.contains(hit),
      hitText: hit?.textContent?.trim() || hit?.tagName,
      popover: panel.getAttribute('popover'),
      parentPopover: panel.parentElement?.closest('[popover]')?.getAttribute('popover') || null,
      parentPopoverOpen: Boolean(panel.parentElement?.closest('[popover]')?.matches(':popover-open')),
      toolbarHeight: document.querySelector('.applications-toolbar')?.getBoundingClientRect().height,
      tableTop: document.querySelector('#tableScrollTop')?.getBoundingClientRect().top,
    };
  }, { detailsSelector, panelSelector });
}

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.PQM_TEST_BROWSER || 'C:/Program Files/Google/Chrome/Application/chrome.exe' });
  const report = [];
  try {
    let baseline = '';
    try {
      baseline = execFileSync('git', ['-C', root, 'show', 'HEAD:registry_popovers.js'], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] });
    } catch {
      // A target that did not previously ship the helper is its own baseline.
    }
    for (const theme of ['light', 'dark']) {
      const before = await browser.newPage({ viewport: { width: 1680, height: 900 } });
      await before.setContent(indexBody(), { waitUntil: 'load' });
      const source = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
      for (const match of source.matchAll(/<link\s+[^>]*href="([^"]+\.css)"[^>]*>/g)) {
        const target = path.join(root, match[1]); if (fs.existsSync(target)) await before.addStyleTag({ path: target });
      }
      if (baseline) await before.addScriptTag({ content: baseline });
      for (const script of ['halloween_season.js', 'halloween.js', 'halloween_motion.js']) {
        const target = path.join(root, script); if (fs.existsSync(target)) await before.addScriptTag({ path: target });
      }
      await before.evaluate(({ theme }) => { document.documentElement.dataset.theme = theme; document.documentElement.dataset.halloween = 'on'; document.querySelector('#loginGate')?.setAttribute('hidden', ''); const shell = document.querySelector('#applicationShell'); if (shell) shell.hidden = false; document.querySelectorAll('main').forEach(main => { main.hidden = main.id !== 'applicationsView'; }); window.dispatchEvent(new Event('resize')); }, { theme });
      await before.waitForTimeout(120);
      await before.locator('#marketplaceDecisionFilter > summary').click();
      await before.waitForTimeout(40);
      await before.screenshot({ path: path.join(evidence, `dropdown-full-before-${theme}-halloween-on.png`) });
      await before.close();

      for (const halloween of [true, false]) for (const width of [1680, 1200, 900]) {
        const page = await browser.newPage({ viewport: { width, height: 900 } });
        const errors = [];
        page.on('pageerror', error => errors.push(error.message));
        await prepare(page, { theme, halloween });
        const beforeToolbar = await page.locator('.applications-toolbar').boundingBox();
        const beforeTable = await page.locator('#tableScrollTop').boundingBox();
        const state = await openAndMeasure(page, '#marketplaceDecisionFilter', '#marketplaceDecisionFilter > .multi-panel');
        assert.equal(state.topLayer, true, `${theme}/${halloween}/${width}: panel is not in browser top layer`);
        assert.equal(state.parentPreserved, true, `${theme}/${halloween}/${width}: DOM ancestry changed`);
        assert.equal(state.hitInside, true, `${theme}/${halloween}/${width}: table still receives panel hit: ${JSON.stringify(state)}`);
        assert(state.rect.left >= 0 && state.rect.right <= width && state.rect.top >= 0 && state.rect.bottom <= 900, `${theme}/${halloween}/${width}: panel left viewport`);
        if (theme === 'light' && halloween && width === 1680) await page.screenshot({ path: path.join(evidence, 'dropdown-full-after-light-halloween-on.png') });
        if (theme === 'dark' && halloween && width === 1680) await page.screenshot({ path: path.join(evidence, 'dropdown-full-after-dark-halloween-on.png') });
        await page.locator('#marketplaceDecisionFilter input[value="__empty__"]').click();
        assert.equal(await page.locator('#marketplaceDecisionFilter input[value="__empty__"]').isChecked(), true);
        assert.equal(await page.locator('#marketplaceDecisionFilter').evaluate(node => node.open), false);
        assert.equal((await page.locator('.applications-toolbar').boundingBox()).height, beforeToolbar.height);
        assert.equal((await page.locator('#tableScrollTop').boundingBox()).y, beforeTable.y);

        await page.locator('#marketplaceDecisionFilter > summary').focus();
        await page.keyboard.press('Enter');
        await page.waitForTimeout(30);
        await page.keyboard.press('Tab');
        assert.equal(await page.locator('#marketplaceDecisionFilter > .multi-panel').evaluate(node => node.contains(document.activeElement)), true);
        await page.keyboard.press('Escape');
        await page.waitForTimeout(30);
        assert.equal(await page.locator('#marketplaceDecisionFilter').evaluate(node => node.open), false);
        assert.equal(await page.locator('#marketplaceDecisionFilter > summary').evaluate(node => document.activeElement === node), true);

        await page.locator('#marketplaceDecisionFilter > summary').click();
        await page.evaluate(() => { const table = document.querySelector('#tableScroll'); table.scrollTop = 180; table.dispatchEvent(new Event('scroll')); });
        await page.setViewportSize({ width: Math.max(760, width - 80), height: 820 });
        await page.waitForTimeout(40);
        const moved = await page.evaluate(() => { const panel = document.querySelector('#marketplaceDecisionFilter > .multi-panel'), r = panel.getBoundingClientRect(), hit = document.elementFromPoint(r.left + 20, r.top + 20); return { topLayer: panel.matches(':popover-open'), hitInside: panel.contains(hit), right: r.right, bottom: r.bottom, width: innerWidth, height: innerHeight }; });
        assert(moved.topLayer && moved.hitInside && moved.right <= moved.width && moved.bottom <= moved.height, `${theme}/${halloween}/${width}: scroll/resize regression ${JSON.stringify(moved)}`);
        const documentClose = await page.evaluate(() => { document.body.click(); return document.querySelector('#marketplaceDecisionFilter').open; });
        assert.equal(documentClose, false);

        await page.evaluate(() => {
          document.querySelectorAll('main').forEach(main => { main.hidden = main.id !== 'suppliersView'; });
          const options = document.querySelector('#supplierRegistryDkFilter .multi-options');
          options.innerHTML = '<label><input type="checkbox" value="03100000-2"> 03100000-2</label>';
          window.dispatchEvent(new Event('resize'));
        });
        const supplier = await openAndMeasure(page, '#supplierRegistryDkFilter', '#supplierRegistryDkFilter > .multi-panel');
        assert(supplier.topLayer && supplier.hitInside && supplier.parentPreserved, `${theme}/${halloween}/${width}: Supplier Base dropdown failed ${JSON.stringify(supplier)}`);
        await page.locator('#supplierRegistryDkFilter input[value="03100000-2"]').click();
        assert.equal(await page.locator('#supplierRegistryDkFilter input[value="03100000-2"]').isChecked(), true);

        await page.evaluate(() => {
          document.querySelectorAll('main').forEach(main => { main.hidden = main.id !== 'edrMonitoringView'; });
          window.dispatchEvent(new Event('resize'));
        });
        const edr = await openAndMeasure(page, '#edrMonitoringAdvanced', '#edrMonitoringAdvanced > .edr-monitoring-filter-grid');
        assert(edr.topLayer && edr.hitInside && edr.parentPreserved, `${theme}/${halloween}/${width}: EDR advanced dropdown failed ${JSON.stringify(edr)}`);
        const edrStatus = await openAndMeasure(page, '#edrMonitoringProzorro', '#edrMonitoringProzorro > .multi-panel');
        assert(edrStatus.topLayer && edrStatus.hitInside && edrStatus.parentPreserved, `${theme}/${halloween}/${width}: EDR status dropdown failed ${JSON.stringify(edrStatus)}`);
        await page.locator('#edrMonitoringProzorro input[value="Активний"]').click();
        assert.equal(await page.locator('#edrMonitoringProzorro input[value="Активний"]').isChecked(), true);
        assert.deepEqual(errors, [], `${theme}/${halloween}/${width}: browser exceptions: ${errors.join(' | ')}`);
        report.push({ theme, halloween, width, applications: true, suppliers: true, edrMonitoring: true, topLayer: true, hitInside: true, clickApplied: true, focusRestored: true, viewportBounded: true });
        await page.close();
      }
    }
    console.log(JSON.stringify({ root, cases: report.length, fullTargetHtml: true, actualCssAndHalloweenScripts: true, report }, null, 2));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
