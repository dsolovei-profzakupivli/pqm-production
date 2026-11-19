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
    executablePath: process.env.PQM_CHROMIUM_EXECUTABLE || 'C:/Users/User/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe',
    args: ['--no-sandbox']
  });
  try {
    let scenarios = 0;
    for (const theme of ['light', 'dark']) for (const halloween of ['on', 'off']) {
      const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.setContent(html);
      for (const file of ['styles.css', 'theme.css', 'modules.css', 'filters.css', 'ui_final.css', 'halloween_motion.css']) {
        if (fs.existsSync(path.join(root, file))) await page.addStyleTag({ path: path.join(root, file) });
      }
      await page.addScriptTag({ path: path.join(root, 'registry_popovers.js') });
      await page.evaluate(({ theme, halloween }) => {
        document.documentElement.dataset.theme = theme;
        document.documentElement.dataset.halloween = halloween;
        document.querySelector('#loginGate')?.setAttribute('hidden', '');
        document.querySelector('#applicationShell')?.removeAttribute('hidden');
        document.querySelector('#supplierCodeFilter .multi-options').innerHTML='<label><input type="checkbox" value="12345678"><span>12345678 · Постачальник із дуже довгою назвою, яка має переноситися без зміщення прапорця</span></label>';
        document.querySelector('#frameworkFilter .multi-options').innerHTML='<label><input type="checkbox" value="fixture-framework"><span>UA-F-2026-11-19 · Відбір із довгою назвою для перевірки перенесення тексту</span></label>';
        document.querySelector('#dkFilter .multi-options').innerHTML='<label><input type="checkbox" value="45000000-7"><span>45000000-7 · Будівельні роботи з додатковим описом для перевірки перенесення</span></label>';
        document.querySelector('#supplierRegistryDkFilter .multi-options').innerHTML='<label><input type="checkbox" value="39100000-3"><span>39100000-3 · Меблі та інші товари з довгим описом коду</span></label>';
        document.querySelector('#edrMonitoringEdr .multi-panel').innerHTML='<label><input type="checkbox" value="Активний"> Активний</label><label><input type="checkbox" value="Призупинений"> Призупинений</label>';
      }, { theme, halloween });

      await page.addScriptTag({ path: path.join(root, 'filter_panels_ui.js') });

      for (const testCase of [
        { view: '#applicationsView', parent: '#applicationFilters', parentPanel: 'application-filter-panel', sectionToggle: '[data-application-filter-section="registry_status"] .filter-accordion-toggle', details: '#registryStatusFilter', control: 'input[value="Активний"]' },
        { view: '#applicationsView', parent: '#applicationFilters', parentPanel: 'application-filter-panel', sectionToggle: '[data-application-filter-section="supplier_codes"] .filter-accordion-toggle', details: '#supplierCodeFilter', control: 'input[value="12345678"]' },
        { view: '#applicationsView', parent: '#applicationFilters', parentPanel: 'application-filter-panel', sectionToggle: '[data-application-filter-section="framework_id"] .filter-accordion-toggle', details: '#frameworkFilter', control: 'input[value="fixture-framework"]' },
        { view: '#applicationsView', parent: '#applicationFilters', parentPanel: 'application-filter-panel', sectionToggle: '[data-application-filter-section="dk_code"] .filter-accordion-toggle', details: '#dkFilter', control: 'input[value="45000000-7"]' },
        { view: '#applicationsView', parent: null, details: '#marketplaceDecisionFilter', control: 'input[value="__empty__"]' },
        { view: '#suppliersView', parent: null, details: '#supplierRegistryDkFilter', control: 'input[value="39100000-3"]' },
        { view: '#edrMonitoringView', parent: '#edrMonitoringAdvanced', parentPanel: 'edr-monitoring-filter-panel', parentMode: 'fixed-drawer', sectionToggle: '[data-edr-filter-section="prozorro_status"] .filter-accordion-toggle', details: '#edrMonitoringProzorro', control: 'input[type="checkbox"]' },
        { view: '#edrMonitoringView', parent: '#edrMonitoringAdvanced', parentPanel: 'edr-monitoring-filter-panel', parentMode: 'fixed-drawer', sectionToggle: '[data-edr-filter-section="edr_status"] .filter-accordion-toggle', details: '#edrMonitoringEdr', control: 'input[type="checkbox"]' }
      ]) {
        await page.evaluate(view => {
          document.querySelectorAll('main[id$="View"]').forEach(node => { node.hidden = `#${node.id}` !== view; });
        }, testCase.view);
        if (testCase.parent) {
          const parent = page.locator(testCase.parent);
          if(!(await parent.evaluate(node=>node.open)))await parent.locator(':scope > summary').click();
          const parentPanel = parent.locator(`:scope > .${testCase.parentPanel||'advanced-filter-panel'}, :scope > .edr-monitoring-filter-grid`);
          if(testCase.parentMode==='fixed-drawer'){
            assert.equal(await parent.evaluate(node=>node.open),true,`${testCase.view}: drawer opens`);
            const drawer=parentPanel;
            assert.equal(await drawer.evaluate(node=>getComputedStyle(node).position==='fixed'&&node.getBoundingClientRect().width>0),true,`${testCase.view}: full-height drawer is visible`);
          }else{
            await page.waitForFunction(({selector,panelClass}) => document.querySelector(selector)?.querySelector(`:scope > .${panelClass}, :scope > .edr-monitoring-filter-grid`)?.matches(':popover-open'), {selector:testCase.parent,panelClass:testCase.parentPanel||'advanced-filter-panel'});
            assert.equal(await parentPanel.evaluate(node => node.matches(':popover-open')), true, `${testCase.view}: parent filter uses top layer`);
          }
        }
        if(testCase.sectionToggle)await page.locator(testCase.sectionToggle).click();
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
        if (testCase.control.startsWith('input[')) {
          const checkboxRow=await control.evaluate(input=>{const label=input.closest('label'),textElement=label.querySelector('span')||[...label.childNodes].find(node=>node.nodeType===Node.TEXT_NODE&&node.textContent.trim()),range=document.createRange();if(textElement.nodeType===Node.ELEMENT_NODE)range.selectNodeContents(textElement);else range.selectNode(textElement);const text=range.getClientRects()[0],box=input.getBoundingClientRect(),outer=label.getBoundingClientRect();return{display:getComputedStyle(label).display,input:{left:box.left,right:box.right,width:box.width,height:box.height,top:box.top},text:{left:text.left,right:text.right,top:text.top,height:text.height},gap:text.left-box.right,centerDelta:Math.abs((box.top+box.height/2)-(text.top+text.height/2)),click:{x:text.left-outer.left+Math.min(text.width/2,30),y:text.top-outer.top+text.height/2}}});
          assert.ok(['grid','flex'].includes(checkboxRow.display)&&checkboxRow.input.width===15&&checkboxRow.input.height===15&&checkboxRow.gap>=4&&checkboxRow.gap<=10&&checkboxRow.centerDelta<=3&&checkboxRow.text.left>checkboxRow.input.right,`checkbox is fixed immediately left of the first text line in ${testCase.details}: ${JSON.stringify(checkboxRow)}`);
          await control.locator('xpath=..').click({position:checkboxRow.click});
          assert.equal(await control.isChecked(), true, `${testCase.view}: option is clickable`);
          assert.equal(await details.evaluate(node => node.open), false, `${testCase.view}: selection closes dropdown`);
        } else {
          await control.click();
          assert.equal(await control.evaluate(node => document.activeElement === node), true, 'Supplier search is interactable');
          await page.keyboard.press('Escape');
          assert.equal(await details.evaluate(node => node.open), false, 'Escape closes supplier dropdown');
        }
        // app.js is deliberately absent from this isolated popover harness; close
        // the parent drawer directly so the next independent menu is not obscured.
        if(testCase.parent)await page.locator(testCase.parent).evaluate(node=>{node.open=false});
        scenarios++;
      }
      assert.deepEqual(errors, [], `Browser errors: ${errors.join('; ')}`);
      await page.close();
    }
    console.log(`REGISTRY_POPOVER_TABS_BROWSER=PASS scenarios=${scenarios} themes=light,dark halloween=on,off tabs=registry,suppliers,edr checkbox-menus=all`);
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
