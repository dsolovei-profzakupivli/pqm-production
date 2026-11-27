const {chromium}=require('playwright');
const fs=require('fs'),assert=require('assert/strict');
(async()=>{
 const executablePath=process.env.PQM_CHROMIUM||(process.platform==='win32'?'C:/Users/User/AppData/Local/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-win64/chrome-headless-shell.exe':undefined);
 const browser=await chromium.launch({headless:true,...(executablePath?{executablePath}:{})});
 let checks=0;const errors=[];
 try{
  for(const [theme,width] of [['light',1280],['dark',1280],['light',390],['dark',390]]){
   const context=await browser.newContext({viewport:{width,height:900},extraHTTPHeaders:{Authorization:process.env.PQM_V311_AUTH},colorScheme:theme});
   const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
   await page.route('**/*',route=>{
    const url=new URL(route.request().url());
    if(url.origin!==process.env.PQM_V311_URL||url.pathname.endsWith('.js'))return route.abort();
    return route.continue();
   });
   await page.goto(process.env.PQM_V311_URL,{waitUntil:'domcontentloaded'});
   await page.evaluate(theme=>{document.documentElement.dataset.theme=theme;document.querySelector('#loginGate').hidden=true;document.querySelector('#applicationShell').hidden=false},theme);
   await page.addScriptTag({content:fs.readFileSync(process.env.PQM_V311_COMPONENT,'utf8')});
   await page.evaluate(()=>previewSupplierEdrSync());
   assert(await page.locator('#supplierEdrPreviewDialog').evaluate(e=>e.open));checks++;
   assert.equal(await page.locator('#supplierEdrPreviewApply').isDisabled(),false);checks++;
   assert.equal(await page.locator('#supplierEdrConflictExport').isHidden(),false);checks++;
   assert.match(await page.locator('#supplierEdrPreviewBody').innerText(),/Доступні зміни полів/);checks++;
   assert.equal(await page.evaluate(()=>displayEdrDate('2026-11-16T06:50:30Z')),'16.11.2026 08:50:30');checks++;
   assert.equal(await page.evaluate(()=>displayEdrDate('2026-09-02')),'02.09.2026');checks++;
   assert.equal(await page.evaluate(()=>displayEdrDate('2026-09-02T00:00:00+03:00','day')),'02.09.2026');checks++;
   const card=await page.evaluate(()=>supplierEdrDatesHtml({edr_checked_at:'2026-09-02T00:00:00+03:00',verification_datetime_precision:'day'}));
   assert.match(card,/02\.09\.2026/);assert.doesNotMatch(card,/00:00:00/);checks+=2;
   await page.locator('#supplierEdrReviewSearch').fill('СР 918414');
   assert.match(await page.locator('#supplierEdrReviewRows').innerText(),/СР 918414/);checks++;
   assert.doesNotMatch(await page.locator('#supplierEdrReviewRows').innerText(),/31587803/);checks++;
   await page.locator('#supplierEdrReviewCategory').selectOption('conflicts');
   assert.match(await page.locator('#supplierEdrReviewRows').innerText(),/Google|статус/i);checks++;
   await page.locator('#supplierEdrReviewSearch').fill('2884318089');
   assert.match(await page.locator('#supplierEdrReviewRows').innerText(),/За цим фільтром змін немає/);checks++;
   await page.locator('#supplierEdrReviewCategory').selectOption('verification');
   await page.locator('#supplierEdrReviewSearch').fill('31587803');
   assert.match(await page.locator('#supplierEdrReviewRows').innerText(),/16\.11\.2026 08:50:30/);checks++;
   const download=page.waitForEvent('download');
   await page.evaluate(()=>downloadSupplierEdrConflicts());
   await (await download).saveAs(process.env.PQM_V311_OUTPUT+`/V311_browser_${theme}_${width}.xlsx`);checks++;
   await page.screenshot({path:process.env.PQM_V311_OUTPUT+`/V311_browser_${theme}_${width}.png`});
   await context.close();
  }
  assert.deepEqual(errors,[]);checks++;
  console.log(JSON.stringify({browser:'Chromium',checks,status:'PASS',scope:'EDR components + actual authenticated HTTP; unrelated module startup omitted'}));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
