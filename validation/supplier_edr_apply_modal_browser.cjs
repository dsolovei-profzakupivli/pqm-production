/* Browser checks for the dedicated Google → PQM Apply progress/result dialog. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {chromium} = globalThis.PQM_PLAYWRIGHT_TEST_MODULE || require('playwright');
const screenshotDir = process.env.PQM_APPLY_SCREENSHOT_DIR;
if (screenshotDir) fs.mkdirSync(screenshotDir,{recursive:true});

const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8').replace(/\r\n/g, '\n');
const html = read('index.html');
const dialog = html.match(/<dialog id="supplierEdrApplyDialog"[\s\S]*?<\/dialog>/)?.[0];
assert(dialog, 'dedicated EDR Apply dialog is present');
const app = read('app.js');
const startFunctionStart = app.indexOf('async function startSupplierEdrSync(){');
const startFunctionEnd = app.indexOf('\nfunction updateSupplierEdrApplyElapsed(',startFunctionStart);
assert(startFunctionStart >= 0 && startFunctionEnd > startFunctionStart,'actual Apply start/duplicate-guard function is present');
const startFunction = app.slice(startFunctionStart,startFunctionEnd);
const start = app.indexOf('function updateSupplierEdrApplyElapsed(');
const end = app.indexOf('\nfunction edrMonitoringParams(', start);
assert(start >= 0 && end > start, 'actual EDR Apply rendering functions are present');
const renderers = app.slice(start, end);
const styles = `${read('styles.css')}\n${read('theme.css')}`;

(async()=>{
  const browser = await chromium.launch({headless:true});
  try {
    for (const theme of ['light','dark']) {
      for (const viewport of [{width:1920,height:1080},{width:1366,height:900},{width:900,height:850},{width:430,height:740}]) {
        const page = await browser.newPage({viewport});
        await page.setContent(`<!doctype html><html data-theme="${theme}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><style>${styles}</style></head><body>
          <button id="supplierEdrPreviewApply" type="button">Застосувати</button><button id="supplierEdrSync" type="button"></button><button id="edrMonitoringSync" type="button"></button>${dialog}<script>
          const $=selector=>document.querySelector(selector);let supplierEdrApplyStartedAt=Date.now(),supplierEdrApplySubmitting=false;
          let supplierEdrPreview={source_fingerprint:'a'.repeat(64),state_digest:'b'.repeat(64)},supplierEdrTimer=null,requestCount=0,resolveApplyRequest;
          const API='/api';window.confirm=()=>true;const request=()=>{requestCount++;return new Promise(resolve=>resolveApplyRequest=resolve)};
          const loadSupplierEdrStatus=async()=>({running:true,stage:'queued',progress_processed:0,progress_total:10});
          const toast=()=>{};const loadQualifiedSuppliersFiltered=async()=>{};const loadEdrMonitoring=async()=>{};let activeModule='suppliers';
          ${startFunction}
          ${renderers}
          $('#supplierEdrApplyOk').onclick=()=>$('#supplierEdrApplyDialog').close();
          $('#supplierEdrApplyDialog').addEventListener('cancel',event=>event.preventDefault());
          window.openApply=()=>$('#supplierEdrApplyDialog').showModal();
          $('#supplierEdrPreviewApply').onclick=startSupplierEdrSync;
        </script></body></html>`);
        await page.locator('#supplierEdrPreviewApply').click();
        assert.equal(await page.locator('#supplierEdrPreviewApply').isDisabled(),true,`${theme} ${viewport.width}: Apply is locked while request is pending`);
        assert.equal(await page.locator('#supplierEdrPreviewApply').getAttribute('aria-busy'),'true');
        await page.locator('#supplierEdrPreviewApply').evaluate(node=>node.click());
        await page.waitForTimeout(20);
        assert.equal(await page.evaluate(()=>requestCount),1,`${theme} ${viewport.width}: duplicate Apply is not sent`);
        await page.evaluate(()=>resolveApplyRequest({started:true}));
        await page.waitForTimeout(20);
        await page.evaluate(()=>{window.openApply();renderSupplierEdrApplyProgress({stage:'applying',elapsed_seconds:4,progress_processed:4,progress_total:10})});
        assert.equal(await page.locator('#supplierEdrApplyDialog').evaluate(node=>node.open),true,`${theme}: modal opens`);
        assert.equal(await page.locator('#supplierEdrApplyProgress').getAttribute('role'),'status');
        assert.equal(await page.locator('#supplierEdrApplyBar').isVisible(),true,`${theme}: actual progress is visible`);
        assert.equal(await page.locator('#supplierEdrApplyBar').evaluate(node=>[node.value,node.max]).then(JSON.stringify),'[4,10]');
        assert.match(await page.locator('#supplierEdrApplyStage').innerText(),/Застосування змін/);
        if(screenshotDir)await page.screenshot({path:path.join(screenshotDir,`${theme}-${viewport.width}-progress.png`)});
        const modalBounds=await page.locator('#supplierEdrApplyDialog').boundingBox();
        assert(modalBounds.x>=0&&modalBounds.y>=0&&modalBounds.x+modalBounds.width<=viewport.width+1&&modalBounds.y+modalBounds.height<=viewport.height+1,
          `${theme}: modal fits viewport ${JSON.stringify(modalBounds)}`);
        await page.keyboard.press('Escape');
        assert.equal(await page.locator('#supplierEdrApplyDialog').evaluate(node=>node.open),true,`${theme}: Escape cannot discard progress`);
        await page.evaluate(()=>showSupplierEdrApplyResult({last_result:'completed',duration_seconds:23,
          last_result_summary:{inserted:2,updated:7,successful:9,skipped_conflicts:0,unchanged:4,errors:0}}));
        assert.equal(await page.locator('#supplierEdrApplyInserted').innerText(),'2');
        assert.equal(await page.locator('#supplierEdrApplyUpdated').innerText(),'7');
        assert.equal(await page.locator('#supplierEdrApplyConflicts').innerText(),'0');
        assert.equal(await page.locator('#supplierEdrApplyUnchanged').innerText(),'4');
        assert.equal(await page.locator('#supplierEdrApplyErrors').innerText(),'0');
        assert.equal(await page.locator('#supplierEdrApplyDialog').getAttribute('data-result'),'success');
        const expectedColumns=viewport.width<=520?2:3;
        assert.equal(await page.locator('.supplier-edr-apply-metrics').evaluate(node=>{
          const firstRowTop=node.children[0].getBoundingClientRect().top;
          return [...node.children].filter(item=>Math.abs(item.getBoundingClientRect().top-firstRowTop)<1).length;
        }),expectedColumns,`${theme}: responsive result metrics`);
        if(screenshotDir)await page.screenshot({path:path.join(screenshotDir,`${theme}-${viewport.width}-success.png`)});
        const successColor=await page.locator('#supplierEdrApplyResultMessage').evaluate(node=>getComputedStyle(node).color);
        await page.waitForTimeout(250);
        assert.equal(await page.locator('#supplierEdrApplyDialog').evaluate(node=>node.open),true,`${theme}: result stays until acknowledged`);
        await page.locator('#supplierEdrApplyOk').click();
        assert.equal(await page.locator('#supplierEdrApplyDialog').evaluate(node=>node.open),false,`${theme}: OK closes result`);
        await page.evaluate(()=>{window.openApply();showSupplierEdrApplyResult({last_result:'completed',duration_seconds:3,
          last_result_summary:{successful:1,inserted:0,updated:1,skipped_conflicts:0,unchanged:0,errors:0}})});
        assert.equal(await page.locator('#supplierEdrApplyBar').isVisible(),false,`${theme}: missing progress is not fabricated`);
        await page.locator('#supplierEdrApplyOk').click();
        await page.evaluate(()=>{window.openApply();showSupplierEdrApplyResult({last_result:'completed',duration_seconds:8,
          last_result_summary:{successful:6,inserted:1,updated:5,skipped_conflicts:3,unchanged:2,errors:0}})});
        assert.equal(await page.locator('#supplierEdrApplyDialog').getAttribute('data-result'),'partial');
        if(screenshotDir)await page.screenshot({path:path.join(screenshotDir,`${theme}-${viewport.width}-partial.png`)});
        assert.notEqual(await page.locator('#supplierEdrApplyResultMessage').evaluate(node=>getComputedStyle(node).color),successColor,
          `${theme}: partial completion has a distinct status color`);
        await page.locator('#supplierEdrApplyOk').click();
        await page.evaluate(()=>{window.openApply();showSupplierEdrApplyResult({last_result:'failed',error:"can't compare offset-naive and offset-aware datetimes",duration_seconds:2,
          last_result_summary:{successful:0,inserted:0,updated:0,skipped_conflicts:0,unchanged:0,errors:1}})});
        assert.match(await page.locator('#supplierEdrApplyError').innerText(),/Не вдалося узгодити часові пояси/);
        assert.equal(await page.locator('#supplierEdrApplyDialog').getAttribute('data-result'),'error');
        if(screenshotDir)await page.screenshot({path:path.join(screenshotDir,`${theme}-${viewport.width}-error.png`)});
        await page.locator('#supplierEdrApplyOk').click();
        await page.close();
      }
      console.log(`PASS ${theme} theme: 1920/1366/900/430 px, duplicate-submit guard, progress, success, partial, error and persistent result`);
    }
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1});
