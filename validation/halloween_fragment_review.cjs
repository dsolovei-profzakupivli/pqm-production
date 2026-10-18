const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require('C:/Users/User/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const {fixture}=require('./halloween_integration_browser.cjs');
const out=path.resolve(__dirname,'../evidence/halloween-fragment');fs.mkdirSync(out,{recursive:true});
const stage=process.argv[2]||'before';assert(['before','after'].includes(stage));
const root=path.resolve(__dirname,'..');
const motionSource=stage==='before'?require('child_process').execFileSync('git',['show','9ceb412639bac494b3bb14c4fc7218ccb86c10b8:halloween_motion.js'],{cwd:root,encoding:'utf8'}):null;
(async()=>{const browser=await chromium.launch({headless:true,executablePath:'C:/Users/User/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe'});const report=[];try{
for(const theme of ['light','dark']){
 const f=await fixture(browser,{theme,dpr:4,motionSource});
 for(let witch=1;witch<=2;witch++){
  await f.page.waitForSelector('.halloween-flight-sprite');
  const diagnostic=await f.page.evaluate(()=>{
   const svg=document.querySelector('.halloween-flight-sprite svg'),s=svg.parentElement,a=s.getAnimations()[0];a.pause();a.currentTime=a.effect.getTiming().duration*.5;
   for(const a of svg.getAnimations()){a.pause();a.currentTime=0}
   const box=svg.viewBox.baseVal,m=svg.getScreenCTM(),r=svg.getBoundingClientRect(),inverse=m.inverse();
   const point=svg.createSVGPoint();point.x=r.left;point.y=r.top;const p=point.matrixTransform(inverse);
   return {viewBox:[box.x,box.y,box.width,box.height],viewport:{width:r.width,height:r.height},sourceAtViewportLeft:p.x,sourceViewBoxLeft:box.x,paddingSourceUnits:box.x-p.x,clip:svg.querySelector('image').getAttribute('clip-path'),duration:a.effect.getTiming().duration};
  });
  // Crop actual runtime at 4x device pixel ratio; no image resizing or editing.
  const r=await f.page.locator('.halloween-flight-sprite').boundingBox();
  await f.page.waitForTimeout(100);
  await f.page.screenshot({path:path.join(out,`${stage}-${theme}-witch-${witch}.png`),clip:{x:r.x-24,y:r.y,width:r.width+100,height:r.height+8}});
  // Render the actual SVG on transparency, with the unchanged atlas embedded,
  // and count painted pixels strictly outside the selected source frame.
  const gutters=await f.page.evaluate(async()=>{
   const svg=document.querySelector('.halloween-flight-sprite svg'),blob=await (await fetch('assets/halloween-witches-sheet.png')).blob();
   const data=await new Promise(resolve=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.readAsDataURL(blob)});
   const clone=svg.cloneNode(true),w=108,h=78,scale=4;clone.setAttribute('xmlns','http://www.w3.org/2000/svg');clone.setAttribute('width',w);clone.setAttribute('height',h);clone.querySelector('image').setAttribute('href',data);
   const uri='data:image/svg+xml;base64,'+btoa(new XMLSerializer().serializeToString(clone));const img=new Image();img.src=uri;await img.decode();
   const canvas=document.createElement('canvas');canvas.width=w*scale;canvas.height=h*scale;const ctx=canvas.getContext('2d');ctx.drawImage(img,0,0,canvas.width,canvas.height);
   const pixels=ctx.getImageData(0,0,canvas.width,canvas.height).data,b=svg.viewBox.baseVal,gap=(w-h*b.width/b.height)/2;
   let paintedGutterPixels=0,insideFramePixelHash=2166136261;for(let y=0;y<canvas.height;y++)for(let x=0;x<canvas.width;x++){
    const index=(y*canvas.width+x)*4;
    if((x/scale<gap-1||x/scale>w-gap+1)&&pixels[index+3]>32)paintedGutterPixels++;
    if(x/scale>=gap+1&&x/scale<=w-gap-1)for(let c=0;c<4;c++)insideFramePixelHash=Math.imul(insideFramePixelHash^pixels[index+c],16777619)>>>0;
   }
   return{gapCssPixels:gap,paintedGutterPixels,insideFramePixelHash:insideFramePixelHash.toString(16)};
  });
  if(stage==='before')assert(gutters.paintedGutterPixels>0);else assert.equal(gutters.paintedGutterPixels,0);
  const phases=[];
  for(const fraction of [.001,.1,.25,.5,.75,.84,.94,.999]){
   const state=await f.page.evaluate(fraction=>{const s=document.querySelector('.halloween-flight-sprite'),a=s.getAnimations()[0];a.currentTime=a.effect.getTiming().duration*fraction;return{fraction,x:s.getBoundingClientRect().x,width:s.getBoundingClientRect().width,height:s.getBoundingClientRect().height,opacity:getComputedStyle(s).opacity,canvases:document.querySelectorAll('.halloween-broom-trail').length}},fraction);
   phases.push(state);assert.equal(state.canvases,1);
   await f.page.screenshot({path:path.join(out,`${stage}-${theme}-witch-${witch}-phase-${Math.round(fraction*1000)}.png`),clip:{x:0,y:72,width:1440,height:134}});
  }
  const completeFlight=await f.page.evaluate(()=>{const s=document.querySelector('.halloween-flight-sprite'),a=s.getAnimations()[0],svg=s.querySelector('svg'),box=svg.viewBox.baseVal;let samples=0;for(let i=0;i<100;i++){a.currentTime=a.effect.getTiming().duration*(i+.1)/100;const clip=svg.querySelector('clipPath rect');if(clip&&[clip.x.baseVal.value,clip.y.baseVal.value,clip.width.baseVal.value,clip.height.baseVal.value].join(',')!==[box.x,box.y,box.width,box.height].join(','))throw Error('Frame clip drift');samples++}return{samples,clipRectFixedToSourceFrame:!!svg.querySelector('clipPath rect')}});
  report.push({stage,theme,witch,...diagnostic,gutters,completeFlight,phases});
  if(witch===1){await f.page.evaluate(()=>document.querySelector('.halloween-flight-sprite').dispatchEvent(new AnimationEvent('animationend',{animationName:'pqm-witch-cross'})));await f.page.waitForTimeout(180)}
 }
 assert.deepEqual(f.errors,[]);await f.context.close();
}
fs.writeFileSync(path.join(out,stage+'.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report.map(({theme,witch,viewBox,paddingSourceUnits,clip})=>({stage,theme,witch,viewBox,paddingSourceUnits,clip})),null,2));
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exitCode=1});
