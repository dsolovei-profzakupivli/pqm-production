const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const root = path.resolve(process.argv[2] || path.join(__dirname, '..'));
const app = fs.readFileSync(path.join(root, 'app.js'), 'utf8');
const widths = fs.readFileSync(path.join(root, 'table_widths_ui.js'), 'utf8');
const helperStart = app.indexOf('function installSupplierCodeAction(');
const helperEnd = app.indexOf('function supplierEdrDatesHtml(', helperStart);
const helper = app.slice(helperStart, helperEnd);
const profileStart = app.indexOf('openSupplierProfile=async function(code,context={}){');
const profileEnd = app.indexOf('\n};', profileStart) + 3;
const profile = app.slice(profileStart, profileEnd);
const appealsHandler = app.split(/\r?\n/).find(line => line.startsWith("$('#requestsBody').onclick="));
assert(helperStart >= 0 && helperEnd > helperStart && profileStart >= 0 && profileEnd > profileStart && appealsHandler,
  'production card handlers must exist');

(async () => {
  const browser = await chromium.launch({ headless: true, ...(process.env.PQM_TEST_BROWSER ? { executablePath: process.env.PQM_TEST_BROWSER } : {}) });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    page.on('pageerror', error => { throw error; });
    await page.setContent(`<!doctype html><html><body data-auth-role="admin">
      <main id="requestsView"><table data-system-table="appeals"><thead><tr><th data-column-key="action" data-default-width="130">Action</th><th data-column-key="text" data-default-width="300">Text</th></tr></thead><tbody id="requestsBody"><tr class="request-row" data-request-index="2"><td><button id="appeal-open">Open appeal</button></td><td>synthetic</td></tr><tr class="request-row" data-request-index="3"><td>Second appeal</td><td>synthetic</td></tr></tbody></table></main>
      <main id="edrMonitoringView"><table id="supplierRegistryTable" data-system-table="suppliers:edr"><thead><tr><th data-column-key="code" data-default-width="120">Code</th><th data-column-key="name" data-default-width="200">Name</th></tr></thead><tbody><tr><td id="edr-code-cell">46130719</td><td>synthetic EDR supplier</td></tr><tr><td>46130720</td><td>second EDR supplier</td></tr></tbody></table></main>
      <main id="suppliersView"><table id="supplierDatabaseTable" data-system-table="suppliers:database"><thead><tr><th data-column-key="code" data-default-width="120">Code</th><th data-column-key="name" data-default-width="200">Name</th></tr></thead><tbody><tr><td id="database-code-cell">46130719</td><td>synthetic database supplier</td></tr><tr><td>46130720</td><td>second database supplier</td></tr></tbody></table></main>
      <dialog id="supplierProfileDialog"><h2 id="supplierProfileTitle"></h2><p id="supplierProfileSubtitle"></p><div id="supplierProfileBody"></div></dialog><dialog id="appeal-card"></dialog>
      <script>
        window.API='/api'; window.authReady=Promise.resolve(); window.toast=()=>{}; window.esc=String; window.$=s=>document.querySelector(s);
        window.profileRequests=[];
        window.request=async(url)=>{
          if(url==='/api/table-widths')return {tables:{
            'suppliers:edr':{code:120,name:200,__order__:['name','code'],__visible__:['code','name']},
            'suppliers:database':{code:120,name:200,__order__:['name','code'],__visible__:['code','name']},
            'appeals':{action:130,text:300,__order__:['text','action'],__visible__:['action','text']}
          }};
          window.profileRequests.push(url);
          throw new Error('Synthetic profile API response for click-path test');
        };
        window.supplierRegistryItems=[{code:'46130719',name:'Synthetic supplier',current_manager:'Synthetic manager',edr_profile:{full_name:'Synthetic full name',short_name:'Synthetic',edr_status:'active'}}];
        window.displayEdrStatus=value=>value||'—'; window.displayDateOnly=value=>value||'';
        window.appealOpened=[];
        window.openViolationReport=i=>{window.appealOpened.push(i);document.querySelector('#appeal-card').showModal()};
      </script></body></html>`);

    await page.addScriptTag({ content: widths });
    await page.waitForFunction(() => document.querySelector('#supplierRegistryTable').dataset.resizeBound === '1');
    await page.addScriptTag({ content: profile });
    await page.addScriptTag({ content: helper });
    await page.evaluate(() => {
      installSupplierCodeAction(document.querySelector('#edr-code-cell'),()=>openSupplierProfile('46130719'));
      installSupplierCodeAction(document.querySelector('#database-code-cell'),()=>openSupplierProfile('46130719'));
    });
    await page.evaluate(source => (0, eval)(source), appealsHandler);
    await page.waitForTimeout(120);
    assert.deepEqual(await page.locator('#supplierRegistryTable thead th').allTextContents(), ['Name', 'Code']);
    assert.deepEqual(await page.locator('#requestsView thead th').allTextContents(), ['Text', 'Action']);

    const openClose = async (selector, dialog) => {
      await page.locator(selector).click();
      assert.equal(await page.locator(dialog).evaluate(element=>element.open), true, `${selector} must open on one ordinary click`);
      await page.locator(dialog).evaluate(element=>element.close());
    };
    await openClose('#edr-code-cell .supplier-card-action', '#supplierProfileDialog');
    await openClose('#database-code-cell .supplier-card-action', '#supplierProfileDialog');
    await openClose('#appeal-open', '#appeal-card');
    for(let i=0;i<6;i++){
      await openClose('#edr-code-cell .supplier-card-action', '#supplierProfileDialog');
      await openClose('#appeal-open', '#appeal-card');
    }
    assert.equal(await page.evaluate(()=>window.appealOpened.length), 7);
    assert.equal(await page.evaluate(()=>window.profileRequests.length), 8);

    await page.evaluate(() => {
      window.__tableMutationCount=0;
      const observer=new MutationObserver(records=>{window.__tableMutationCount+=records.filter(record=>record.target.closest?.('table')).length});
      observer.observe(document.body,{subtree:true,childList:true});
      window.__testObserver=observer;
    });
    const assertSettles = async (label, action) => {
      await action();
      await page.waitForTimeout(120);
      await page.evaluate(()=>window.__tableMutationCount=0);
      await page.waitForTimeout(250);
      const count=await page.evaluate(()=>window.__tableMutationCount);
      assert.equal(count,0,`${label} must settle without repeated table DOM mutations (observed ${count})`);
    };
    await assertSettles('initial correct order', async()=>page.evaluate(()=>document.body.classList.add('widths-ready')));
    await assertSettles('sort', async()=>page.evaluate(()=>{const body=document.querySelector('#supplierRegistryTable tbody');body.insertBefore(body.lastElementChild,body.firstElementChild)}));
    await assertSettles('filter', async()=>page.evaluate(()=>{document.querySelector('#supplierRegistryTable tbody').lastElementChild.hidden=true}));
    await assertSettles('page change', async()=>page.evaluate(()=>{const body=document.querySelector('#supplierRegistryTable tbody'),replacement=body.firstElementChild.cloneNode(true);body.replaceChildren(replacement)}));
    await assertSettles('column resize', async()=>{
      const header=page.locator('#supplierRegistryTable thead th').first();const box=await header.boundingBox();
      await page.mouse.move(box.x+box.width-2,box.y+box.height/2);await page.mouse.down();
      await page.mouse.move(box.x+box.width+28,box.y+box.height/2,{steps:5});await page.mouse.up();
    });

    console.log(`PASS ${path.basename(root)}: stable order after sort/filter/page/resize; one-click supplier EDR/database and appeal cards; 6 rapid repeat cycles`);
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1});
