const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require('C:/Users/User/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const {fixture}=require('./halloween_integration_browser.cjs');
const out=path.resolve(__dirname,'../evidence/halloween-integration');
(async()=>{const browser=await chromium.launch({headless:true,executablePath:'C:/Users/User/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe'});try{
for(const theme of ['light','dark']){
 const f=await fixture(browser,{theme});await f.page.waitForSelector('.halloween-flight-sprite');
 const geometry=await f.page.locator('img.halloween-cat').boundingBox();
 for(const [name,phase] of [['right',.2],['left',.85],['center',1]]){
  await f.page.evaluate(p=>{for(const a of document.querySelector('.halloween-cat-eyes').getAnimations({subtree:true})){a.pause();a.currentTime=a.effect.getTiming().duration*p}},phase);
  assert.deepEqual(await f.page.locator('img.halloween-cat').boundingBox(),geometry);
  await f.page.screenshot({path:path.join(out,`${theme}-eyes-${name}.png`),clip:{x:205,y:38,width:80,height:58}});
 }
 await f.context.close();
}
fs.writeFileSync(path.join(out,'eyes.html'),'<!doctype html><meta charset="utf-8"><title>Очі котика</title><style>body{background:#263346;color:#fff;font:16px system-ui;padding:24px}img{width:320px;margin:12px;border:1px solid #8a9bad}</style><h1>Котик · праворуч → ліворуч → центр</h1><p>Збільшені кадри фактичного Sandbox HTML; геометрія котика незмінна.</p>'+['light','dark'].map(t=>'<h2>'+t+'</h2>'+['right','left','center'].map(n=>'<img alt="'+n+'" src="'+t+'-eyes-'+n+'.png">').join('')).join(''));
console.log('PASS: eye sequence captured in both themes; original cat geometry unchanged');
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exitCode=1});
