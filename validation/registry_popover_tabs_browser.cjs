const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
let chromium;
try { ({ chromium } = require('playwright')); }
catch { ({ chromium } = require('C:/Users/User/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright')); }

const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const html = read('index.html').replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '').replace(/<link\s+[^>]*rel="stylesheet"[^>]*>/gi, '');

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: 'C:/Users/User/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe',
    args: ['--no-sandbox']
  });
  try {
    let scenarios = 0;
    for (const theme of ['light', 'dark']) for (const halloween of ['on', 'off']) {
      const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.setContent(html);
      for (const file of ['styles.css', 'theme.css', 'modules.css', 'filters.css', 'halloween_motion.css']) {
        if (fs.existsSync(path.join(root, file))) await page.addStyleTag({ path: path.join(root, file) });
      }
      await page.addScriptTag({ path: path.join(root, 'registry_popovers.js') });
      await page.evaluate(({ theme, halloween }) => {
        document.documentElement.dataset.theme = theme;
        document.documentElement.dataset.halloween = halloween;
        document.querySelector('#loginGate')?.setAttribute('hidden', '');
        document.querySelector('#applicationShell')?.removeAttribute('hidden');
      }, { theme, halloween });

      for (const testCase of [
        { view: '#applicationsView', parent: null, details: '#marketplaceDecisionFilter', control: 'input[value="__empty__"]' },
        { view: '#suppliersView', parent: null, details: '#supplierRegistryDkFilter', control: '.multi-search' },
        { view: '#edrMonitoringView', parent: '#edrMonitoringAdvanced', details: '#edrMonitoringProzorro', control: 'input[type="checkbox"]' }
      ]) {
        await page.evaluate(view => {
          document.querySelectorAll('main[id$="View"]').forEach(node => { node.hidden = `#${node.id}` !== view; });
        }, testCase.view);
        if (testCase.parent) {
          const parent = page.locator(testCase.parent);
          await parent.locator(':scope > summary').click();
          const parentPanel = parent.locator(':scope > .advanced-filter-panel, :scope > .edr-monitoring-filter-grid');
          await page.waitForFunction(selector => document.querySelector(selector)?.querySelector(':scope > .advanced-filter-panel, :scope > .edr-monitoring-filter-grid')?.matches(':popover-open'), testCase.parent);
          assert.equal(await parentPanel.evaluate(node => node.matches(':popover-open')), true, `${testCase.view}: parent filter uses top layer`);
        }
        const details = page.locator(testCase.details);
        await details.locator(':scope > summary').click();
        const panel = details.locator(':scope > .multi-panel');
        await page.waitForFunction(selector => document.querySelector(selector)?.querySelector(':scope > .multi-panel')?.matches(':popover-open'), testCase.details);
        assert.equal(await panel.evaluate(node => node.matches(':popover-open')), true, `${testCase.view}: child filter uses top layer`);
        const hit = await panel.evaluate(node => {
          const r = node.getBoundingClientRect();
          const x = Math.max(0, Math.min(innerWidth - 1, r.left + Math.min(r.width / 2, 20)));
          const y = Math.max(0, Math.min(innerHeight - 1, r.top + Math.min(r.height / 2, 20)));
          return { contained: node.contains(document.elementFromPoint(x, y)), visible: r.width > 0 && r.height > 0 };
        });
        assert.equal(hit.visible, true, `${testCase.view}: filter panel is visible`);
        assert.equal(hit.contained, true, `${testCase.view}: panel receives pointer hit-testing`);
        const control = panel.locator(testCase.control).first();
        assert.equal(await control.isVisible(), true, `${testCase.view}: filter control is visible`);
        await control.click();
        if (testCase.view !== '#suppliersView') {
          assert.equal(await control.isChecked(), true, `${testCase.view}: option is clickable`);
          assert.equal(await details.evaluate(node => node.open), false, `${testCase.view}: selection closes dropdown`);
        } else {
          assert.equal(await control.evaluate(node => document.activeElement === node), true, 'Supplier search is interactable');
          await page.keyboard.press('Escape');
          assert.equal(await details.evaluate(node => node.open), false, 'Escape closes supplier dropdown');
        }
        if (testCase.parent) {
          await page.locator(testCase.parent).locator('select,input').first().focus();
          await page.keyboard.press('Escape');
          assert.equal(await page.locator(testCase.parent).evaluate(node => node.open), false, `${testCase.view}: Escape closes parent filter`);
        }
        scenarios++;
      }
      assert.deepEqual(errors, [], `Browser errors: ${errors.join('; ')}`);
      await page.close();
    }
    console.log(`REGISTRY_POPOVER_TABS_BROWSER=PASS scenarios=${scenarios} themes=light,dark halloween=on,off tabs=registry,suppliers,edr`);
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
