const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
let chromium;try{({chromium}=require('playwright'))}catch{({chromium}=require('C:/Users/User/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'))}
const root=path.resolve(__dirname,'..'),out=path.join(root,'evidence','nazk-toolbar'),css=fs.readFileSync(path.join(root,'styles.css'),'utf8');
fs.mkdirSync(out,{recursive:true});
const toolbar=(id,klass,title,meta,search,select,refresh)=>{const amcu=id==='referenceAmcu';return `<section id="${id}" class="reference-panel"><div class="reference-toolbar card ${klass}"><div><strong>${title}</strong><small>${meta}</small></div><input id="${amcu?'refAmcuSearch':'refNazkSearch'}" placeholder="${search}"><label class="reference-date-filter">Від <input type="date"></label><label class="reference-date-filter">До <input type="date"></label><select ${amcu?'id="refAmcuAuthority"':''}><option>${select}</option></select>${amcu?'<select id="refAmcuSupplierScope"><option>Усі суб’єкти</option></select>':''}<button type="button" class="primary">${refresh}</button><button type="button" class="ghost icon-button system-width-button" aria-label="Налаштування колонок">▥</button></div></section>`};
const officerToolbar=`<section id="adminOfficersPanel"><div class="admin-officer-add"><input aria-label="ПІБ уповноваженої особи"><input aria-label="Роль"><button type="button">+ Додати УО</button><button type="button" class="system-width-button" aria-label="Налаштування колонок">▥</button></div></section>`;
const html=`<!doctype html><html data-theme="light"><head><meta charset="utf-8"><style>${css}\nbody{margin:0;padding:12px;box-sizing:border-box}.reference-panel{width:100%;box-sizing:border-box}</style></head><body>${toolbar('referenceNazk','', 'Реєстр НАЗК','31 355 записів · 15.10.2026, 09:23','Пошук за ПІБ, порушенням або справою…','Усі суди / органи','Оновити зараз')}${toolbar('referenceAmcu','amcu-toolbar','Реєстр АМКУ','Оновлено сьогодні','Пошук за назвою, кодом або рішенням…','Усі органи АМКУ','Оновити з сайту')}${officerToolbar}</body></html>`;
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.PQM_TEST_BROWSER?{executablePath:process.env.PQM_TEST_BROWSER}:fs.existsSync('C:/Users/User/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe')?{executablePath:'C:/Users/User/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe'}:{})});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:600}}),results=[],searchWidths={};
  await page.setContent(html);
  for(const theme of ['light','dark'])for(const width of [390,1024,1280,1440,1920]){
   await page.setViewportSize({width,height:600});await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);
   for(const id of ['referenceNazk','referenceAmcu']){
    const selector=`#${id} .reference-toolbar`,box=await page.locator(selector).evaluate(el=>{const r=el.getBoundingClientRect();const ids=[el.children[0],el.querySelector('input:not([type="date"])'),...el.querySelectorAll('.reference-date-filter'),...el.querySelectorAll('select'),el.querySelector('button.primary'),el.querySelector('.system-width-button')];return {left:r.left,right:r.right,width:r.width,client:el.clientWidth,scroll:el.scrollWidth,items:ids.map(n=>{const x=n.getBoundingClientRect();return {left:x.left,right:x.right,top:x.top,width:x.width}})}});
    assert(box.items.every(x=>x.width>0&&x.left>=box.left-1&&x.right<=box.right+1),`${id} clipped at ${theme}/${width}`);
    assert(box.scroll<=box.client+2,`${id} horizontal overflow at ${theme}/${width}`);
    if(width>=1280){assert(box.items.every(x=>Math.abs(x.top-box.items[0].top)<2),`${id} wrapped at desktop ${theme}/${width}`);assert(box.items.slice(1).every((x,i)=>x.left>=box.items[i].right-1),`${id} order/overlap at ${theme}/${width}`)}
    if(id==='referenceNazk'){
     searchWidths[`${theme}-${width}`]=box.items[1].width;
     if([390,1280].includes(width))await page.screenshot({path:path.join(out,`${theme}-${width}.png`),fullPage:true});
    }
   }
   const uo=await page.locator('#adminOfficersPanel .admin-officer-add').evaluate(el=>{const r=el.getBoundingClientRect();return {left:r.left,right:r.right,scroll:el.scrollWidth,client:el.clientWidth,items:[...el.children].map(n=>{const x=n.getBoundingClientRect();return {left:x.left,right:x.right,top:x.top,bottom:x.bottom,width:x.width}})}});
   assert(uo.items.every(x=>x.width>0&&x.left>=uo.left-1&&x.right<=uo.right+1),`officer toolbar clipped at ${theme}/${width}`);
   assert(uo.scroll<=uo.client+2,`officer toolbar overflow at ${theme}/${width}`);
   if(width>=1280){assert(uo.items.every(x=>Math.abs((x.top+x.bottom)/2-(uo.items[0].top+uo.items[0].bottom)/2)<2),`officer width button wrapped at desktop ${theme}/${width}: ${JSON.stringify(uo)}`);assert(uo.items.slice(1).every((x,i)=>x.left>=uo.items[i].right-1),`officer controls overlap at desktop ${theme}/${width}: ${JSON.stringify(uo)}`)}
   if(width===1280&&theme==='light')await page.screenshot({path:path.join(out,'uo-toolbar-1280.png'),fullPage:true});
  }
  for(const theme of ['light','dark'])assert(searchWidths[`${theme}-1920`]>=searchWidths[`${theme}-1280`],`NAZK search does not take remaining width in ${theme} theme`);
  results.push('NAZK/AMCU toolbar: one desktop row; exact control order; no clipping/overlap/overflow; narrow adaptive wrap');
  results.push('Officer directory toolbar: width settings remain beside the form controls at desktop widths');
  results.push('Themes light/dark; widths 390, 1024, 1280, 1440, 1920; search expands with available width');
  fs.writeFileSync(path.join(out,'results.json'),JSON.stringify({status:'PASS',results,searchWidths},null,2));console.log(JSON.stringify({status:'PASS',results,searchWidths},null,2));
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
