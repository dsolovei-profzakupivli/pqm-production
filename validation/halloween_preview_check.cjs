const path=require('path'),assert=require('node:assert/strict');
const {chromium}=require('C:/Users/User/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{const browser=await chromium.launch({headless:true,executablePath:'C:/Users/User/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe'});try{
 const page=await browser.newPage({viewport:{width:1440,height:960}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('file:///'+path.resolve(__dirname,'../evidence/halloween-integration/index.html').replace(/\\/g,'/'));
 for(const theme of ['dark','light']){
  await page.click(theme==='dark'?'#previewDark':'#previewLight');
  await page.waitForFunction(()=>document.querySelector('img.sandbox-brand-initials').complete&&document.querySelector('img.sandbox-brand-initials').naturalWidth>0);
  assert.equal(await page.evaluate(()=>document.documentElement.dataset.theme),theme);
 }
 await page.uncheck('#previewHalloween');await page.waitForTimeout(100);assert.equal(await page.evaluate(()=>document.documentElement.dataset.halloween),'off');
 assert.equal(await page.locator('.halloween-flight-lane').count(),0);assert.deepEqual(errors,[]);console.log('PASS: offline preview, both themes, logo loading, Halloween toggle');
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exitCode=1});
