const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');

async function assertHostedPopover(browser, { module, theme, width, html, preOpenSelector, openSelector, panelSelector, clickSelector, outsideCloseSelector, closeAfterSelection = true }) {
  const page = await browser.newPage({ viewport: { width, height: 900 } });
  await page.setContent(`<!doctype html><html data-theme="${theme}"><body>${html}</body></html>`);
  await page.evaluate(() => {
    const nav = document.createElement('nav'); nav.id = 'testNav';
    nav.innerHTML = '<button id="testNavigationButton" type="button">Інша вкладка</button>';
    nav.querySelector('button').addEventListener('click', () => { document.querySelector('main').hidden = true; });
    document.body.append(nav);
  });
  await page.addStyleTag({ content: `${read('styles.css')}\n${read('filters.css')}\n${read('modules.css')}\n${read('theme.css')}` });
  await page.addScriptTag({ content: `document.addEventListener('pointerdown',event=>document.querySelectorAll('.registry-toolbar details,.multi-filter,.toolbar-settings,.advanced-filters').forEach(item=>{if(item.open&&!item.contains(event.target))item.open=false}));window.__popoverGlobalAdds=0;const __nativeAdd=EventTarget.prototype.addEventListener;EventTarget.prototype.addEventListener=function(...args){if(this===document||this===window)window.__popoverGlobalAdds++;return __nativeAdd.apply(this,args)}` });
  await page.addScriptTag({ path: path.join(root, 'registry_popovers.js') });
  if (preOpenSelector) { await page.locator(preOpenSelector).click(); await page.waitForTimeout(40); }
  await page.locator(openSelector).click();
  await page.waitForTimeout(40);
  const panel = page.locator(panelSelector);
  const geometry = await page.evaluate(selector => {
    const node = document.querySelector(selector), r = node.getBoundingClientRect();
    const point = { x:r.left + Math.min(r.width / 2, 60), y:r.top + Math.min(r.height / 2, 22) };
    const hit = document.elementFromPoint(point.x, point.y);
    return { rect:{left:r.left,right:r.right,top:r.top,bottom:r.bottom}, hitText:hit?.textContent?.trim()||hit?.tagName, inside:node.contains(hit), width:innerWidth, height:innerHeight };
  }, panelSelector);
  assert(geometry.inside, `${theme}/${width} hosted dropdown is not clickable: ${JSON.stringify(geometry)}`);
  assert(geometry.rect.left >= 0 && geometry.rect.right <= width && geometry.rect.top >= 0 && geometry.rect.bottom <= 900, `${theme}/${width} hosted dropdown is clipped: ${JSON.stringify(geometry)}`);
  await page.screenshot({ path: path.join(root, 'evidence', `dropdown-after-${module}-${theme}-${width}.png`) });
  await page.locator(clickSelector).click();
  const selected = await page.locator(clickSelector).evaluate(node => node.matches('input[type="checkbox"]') ? node.checked : node.getAttribute('aria-pressed') || node.textContent.trim());
  assert(selected === true || Boolean(selected), `${theme}/${width} click did not apply to ${clickSelector}`);
  if (closeAfterSelection) assert.equal(await page.locator(openSelector).evaluate(node => node.closest('details').open), false, `${theme}/${width} menu did not close after selection`);
  if (outsideCloseSelector) {
    if (preOpenSelector) await page.locator(preOpenSelector).click();
    await page.locator(openSelector).click();
    await page.mouse.click(20, 850);
    await page.waitForTimeout(20);
    assert.equal(await page.locator(outsideCloseSelector).evaluate(node => node.open), false, `${theme}/${width} menu did not close on outside click`);
  }
  const globalAdds = await page.evaluate(() => window.__popoverGlobalAdds);
  const domCount = await page.locator('body *').count();
  for (let cycle = 0; cycle < 8; cycle++) {
    await page.locator(openSelector).click(); await page.waitForTimeout(25);
    assert.equal(await page.locator(openSelector).evaluate(node => node.closest('details').open), true, `${theme}/${width} cycle ${cycle}: menu did not open`);
    await page.locator(openSelector).click(); await page.waitForTimeout(25);
    assert.equal(await page.locator(openSelector).evaluate(node => node.closest('details').open), false, `${theme}/${width} cycle ${cycle}: menu did not close`);
    assert.equal(await page.locator(openSelector).evaluate(node => node.closest('details').classList.contains('popover-fixed')), false, `${theme}/${width} cycle ${cycle}: positioning state was not cleaned`);
  }
  assert.equal(await page.evaluate(() => window.__popoverGlobalAdds), globalAdds, `${theme}/${width} repeated openings registered extra listeners`);
  assert.equal(await page.locator('body *').count(), domCount, `${theme}/${width} repeated openings accumulated DOM nodes`);
  await page.locator(openSelector).click(); await page.waitForTimeout(25);
  await page.locator('#testNavigationButton').evaluate(button => button.click()); await page.waitForTimeout(25);
  assert.equal(await page.locator(outsideCloseSelector || openSelector).evaluate(node => node.closest('details').open), false, `${theme}/${width} menu remained open after keyboard/programmatic navigation`);
  assert.equal(await page.locator('main').evaluate(node => node.hidden), true, `${theme}/${width} navigation fixture did not transition views`);
  await page.close();
  return {theme,width,geometry,selection:selected,lifecycleCycles:8,globalListenersStable:true,domNodeCountStable:true,navigationClosesPopover:true};
}

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.PQM_TEST_BROWSER || 'C:/Program Files/Google/Chrome/Application/chrome.exe' });
  const report = [];
  try {
    for (const theme of ['light', 'dark']) for (const width of [1440, 1200, 1000]) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      await page.setContent(`<!doctype html><html data-theme="${theme}"><head></head><body>
        <main id="applicationsView" style="height:800px;display:flex;flex-direction:column;overflow:hidden">
          <section class="toolbar card applications-toolbar">
            <div class="search-wrap"><input placeholder="Пошук"></div>
            <select id="applicationCategoryFilter"><option value="">Усі категорії</option><option value="other">Інше</option></select>
            <details id="statusFilter" class="multi-filter"><summary>Статус</summary><div class="multi-panel"><label><input type="checkbox" value="active"> Активні</label><label><input type="checkbox" value="done"> Виконані</label></div></details>
            <details id="marketplaceDecisionFilter" class="multi-filter"><summary>Дія на майданчику</summary><div class="multi-panel"><label><input type="checkbox" value="__empty__"> Не виконано</label><label><input type="checkbox" value="admit"> Допустити</label><label><input type="checkbox" value="reject"> Відхилити</label></div></details>
            <button>Зберегти</button>
          </section>
          <div class="table-scroll-top"><div></div></div>
          <section class="card table-card" style="flex:1;overflow:hidden"><div class="table-scroll" style="height:500px;overflow:auto"><table><thead><tr><th style="position:sticky;top:0;z-index:15">Заголовок таблиці</th></tr></thead><tbody>${'<tr><td>Синтетичний запис</td></tr>'.repeat(30)}</tbody></table></div></section>
        </main></body></html>`);
      await page.addStyleTag({ content: `${read('styles.css')}\n${read('filters.css')}\n${read('theme.css')}` });
      await page.addScriptTag({ path: path.join(root, 'registry_popovers.js') });
      const toolbarBefore = await page.locator('.applications-toolbar').boundingBox();
      const tableBefore = await page.locator('.table-scroll-top').boundingBox();
      await page.locator('#marketplaceDecisionFilter>summary').click();
      await page.waitForTimeout(20);
      const panel = page.locator('#marketplaceDecisionFilter .multi-panel');
      if (width <= 1200) {
        await page.locator('.applications-toolbar').evaluate(node => { node.scrollLeft = 60; });
        await page.waitForTimeout(20);
      }
      const afterOpen = await page.evaluate(() => {
        const p = document.querySelector('#marketplaceDecisionFilter .multi-panel');
        const toolbar = document.querySelector('.applications-toolbar');
        const r = p.getBoundingClientRect(), t = toolbar.getBoundingClientRect();
        const point = { x: r.left + Math.min(r.width / 2, 80), y: r.top + 20 };
        const hit = document.elementFromPoint(point.x, point.y);
        return { width: innerWidth, toolbarOverflowX: getComputedStyle(toolbar).overflowX, toolbarOverflowY: getComputedStyle(toolbar).overflowY, toolbar: { top:t.top,bottom:t.bottom }, panel: { left:r.left,right:r.right,top:r.top,bottom:r.bottom }, hit: hit?.textContent?.trim() || hit?.tagName, label: p.querySelector('label')?.textContent?.trim(), checkboxHit: Boolean(hit?.closest('label')) };
      });
      assert(afterOpen.checkboxHit, `${theme} ${width}: menu item is occluded: ${JSON.stringify(afterOpen)}`);
      assert(afterOpen.panel.left >= 0 && afterOpen.panel.right <= width, `${theme} ${width}: menu spills horizontally: ${JSON.stringify(afterOpen)}`);
      assert(afterOpen.panel.top >= 0 && afterOpen.panel.bottom <= 900, `${theme} ${width}: menu spills vertically: ${JSON.stringify(afterOpen)}`);
      await page.screenshot({ path: path.join(root, 'evidence', `dropdown-after-${theme}-${width}.png`), fullPage: false });
      await panel.locator('label').first().click();
      assert.equal(await panel.locator('input').first().isChecked(), true, `${theme} ${width}: actual click did not select “Не виконано”`);
      const toolbarAfter = await page.locator('.applications-toolbar').boundingBox();
      const tableAfter = await page.locator('.table-scroll-top').boundingBox();
      assert.equal(toolbarAfter.height, toolbarBefore.height, `${theme} ${width}: toolbar height changed`);
      assert.equal(tableAfter.y, tableBefore.y, `${theme} ${width}: table shifted`);
      await page.locator('#marketplaceDecisionFilter>summary').click();
      await page.locator('#statusFilter>summary').click();
      await page.locator('#statusFilter .multi-panel label').first().click();
      assert.equal(await page.locator('#statusFilter input').first().isChecked(), true, `${theme} ${width}: status item was not clickable`);
      assert.equal(await page.locator('#statusFilter').evaluate(node => node.open), false, `${theme} ${width}: status menu did not close after selection`);
      await page.locator('#applicationCategoryFilter').selectOption('other');
      assert.equal(await page.locator('#applicationCategoryFilter').inputValue(), 'other', `${theme} ${width}: native category select failed`);
      await page.locator('#marketplaceDecisionFilter>summary').click();
      await page.mouse.click(20, 850);
      await page.waitForTimeout(20);
      assert.equal(await page.locator('#marketplaceDecisionFilter').evaluate(node => node.open), false, `${theme} ${width}: menu did not close on outside click`);
      report.push({ theme, ...afterOpen, clickApplied:true, toolbarHeightUnchanged:true, tablePositionUnchanged:true });
      await page.close();
    }
    for (const theme of ['light','dark']) for (const width of [1440,1200,700]) {
      const common = '<div class="table-scroll-top"><div></div></div><section class="card table-card" style="height:300px;overflow:auto"><table><thead><tr><th style="position:sticky;top:0;z-index:15">Синтетичний заголовок</th></tr></thead><tbody><tr><td>Дані</td></tr></tbody></table></section>';
      const supplier = await assertHostedPopover(browser,{module:'suppliers',theme,width,html:`<main id="suppliersView" style="height:800px;overflow:hidden"><section class="supplier-toolbar card"><div class="supplier-filter-field"><label>Код ДК</label><details id="supplierRegistryDkFilter" class="multi-filter"><summary>Усі коди ДК</summary><div class="multi-panel"><label><input type="checkbox" value="031"> 03100000-2</label></div></details></div></section>${common}</main>`,openSelector:'#supplierRegistryDkFilter>summary',panelSelector:'#supplierRegistryDkFilter .multi-panel',clickSelector:'#supplierRegistryDkFilter input',outsideCloseSelector:'#supplierRegistryDkFilter'});
      report.push({module:'suppliers',...supplier});
      const edr = await assertHostedPopover(browser,{module:'edr-monitoring',theme,width,html:`<main id="edrMonitoringView" style="height:800px;overflow:hidden"><section class="edr-monitoring-toolbar"><details id="edrMonitoringAdvanced" class="advanced-filters"><summary>Фільтри</summary><div class="edr-monitoring-filter-grid"><div class="edr-monitoring-filter-field"><span>Статус Prozorro</span><input id="edrSyntheticFilter" type="checkbox"><label for="edrSyntheticFilter">Активний</label><button id="edrSyntheticApply" type="button">Застосувати</button></div></div></details></section>${common}</main>`,openSelector:'#edrMonitoringAdvanced>summary',panelSelector:'#edrMonitoringAdvanced .edr-monitoring-filter-grid',clickSelector:'#edrSyntheticApply',outsideCloseSelector:'#edrMonitoringAdvanced',closeAfterSelection:false});
      report.push({module:'edr-monitoring',...edr});
    }
    console.log(JSON.stringify({cases:report.length,registry:report.filter(x=>!x.module).length,suppliers:report.filter(x=>x.module==='suppliers').length,edrMonitoring:report.filter(x=>x.module==='edr-monitoring').length,allSelections:true,allMenusViewportBounded:true,lifecycleCyclesPerHostedCase:8,globalListenersStable:true,domNodeCountStable:true,keyboardNavigationClosesPopover:true},null,2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
