const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require('C:/Users/User/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const {fixture}=require('./halloween_integration_browser.cjs');
const out=path.resolve(__dirname,'../evidence/halloween-maneuvers');fs.mkdirSync(out,{recursive:true});
(async()=>{const browser=await chromium.launch({headless:true,executablePath:'C:/Users/User/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe'});try{
const reports=await Promise.all(['light','dark'].map(async theme=>{
 const f=await fixture(browser,{theme,recordVideo:{dir:out,size:{width:1440,height:960}}}),page=f.page,video=page.video(),report={theme,variants:[]};
 await page.addScriptTag({path:path.join(__dirname,'halloween_shared_fixture.js')});
 for(let variant=1;variant<=2;variant++){
  await page.waitForSelector(`.halloween-flight-sprite[data-witch="${variant}"]`);
  const result=await page.evaluate(()=>{
   const sprite=document.querySelector('.halloween-flight-sprite'),wave=sprite.querySelector('.halloween-witch-maneuver'),cross=sprite.getAnimations()[0],motion=wave.getAnimations()[0],duration=cross.effect.getTiming().duration;
   cross.pause();motion.pause();const samples=[];
   for(let i=0;i<=100;i++){const t=duration*i/100;cross.currentTime=t;motion.currentTime=t;const b=sprite.getBoundingClientRect(),r=wave.getBoundingClientRect();samples.push({x:b.x,y:r.y,offset:new DOMMatrix(getComputedStyle(wave).transform).m42})}
   cross.currentTime=motion.currentTime=0;cross.play();motion.play();
   return{amplitude:parseFloat(getComputedStyle(sprite.parentElement).getPropertyValue('--maneuver-amplitude')),duration,samples};
  });
  assert(result.amplitude>=0&&result.amplitude<=20);assert(result.samples.every((s,i)=>!i||s.x<=result.samples[i-1].x));assert(result.samples.every(s=>Math.abs(s.offset)<=result.amplitude+.1));
  assert(result.samples[100].x+112<0);
  assert(variant===1?result.samples[24].offset<0:result.samples[22].offset>0);
  report.variants.push(result);
  for(let i=1;i<=4;i++){await page.waitForTimeout(result.duration/5);await page.screenshot({path:path.join(out,`${theme}-witch-${variant}-${i}.png`)})}
  await page.waitForTimeout(result.duration/5+100);
 }
 assert.deepEqual(f.errors,[]);assert(await page.evaluate(()=>__maxTrailFrames<=1&&__particles.max<=44));
 await f.context.close();await video.saveAs(path.join(out,`${theme}-both-witches.webm`));return report;
}));fs.writeFileSync(path.join(out,'motion-checks.json'),JSON.stringify(reports,null,2));console.log('PASS: two distinct smooth maneuvers, fixed horizontal speed, bounded amplitude/particles/RAF; videos saved');
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exitCode=1});
