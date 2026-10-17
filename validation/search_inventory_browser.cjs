/* Offline inventory: actual markup, dynamic search templates and production clear installer. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),read=n=>fs.readFileSync(path.join(root,n),'utf8');
const styles=['styles.css','filters.css','modules.css','schema_ui.css','ui_improvements.css','sandbox_theme.css','ui_final.css','ui_tz2.css'];
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.PQM_TEST_BROWSER});
 const page=await browser.newPage();await page.route('**/*',r=>r.abort());
 try{
  const dynamic=[];
  for(const file of fs.readdirSync(root).filter(n=>n.endsWith('.js'))){
   for(const tag of read(file).matchAll(/<input\b[^>]*>/g))if(/search|пошук|знайти/i.test(tag[0]))dynamic.push({file,tag:tag[0]});
   for(const found of read(file).matchAll(/createElement\('input'\);(\w+)\.id='([^']*[Ss]earch[^']*)';\1\.placeholder='([^']*)'/g))dynamic.push({file,tag:`<input id="${found[2]}" placeholder="${found[3]}">`});
  }
  const inventory=new Map();
  for(const dark of [false,true])for(const zoom of [1,1.25])for(const width of [390,768,1440,1920]){
   await page.setViewportSize({width,height:1000});
   await page.setContent(read('index.html').replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,''));
   for(const name of styles)await page.addStyleTag({content:read(name)});
   await page.evaluate(({dark,zoom,dynamic})=>{
    document.documentElement.dataset.pqmEnvironment=dark?'sandbox':'';document.body.style.zoom=zoom;
    document.querySelectorAll('[hidden]').forEach(n=>{if(n.tagName!=='INPUT')n.hidden=false});
    document.querySelectorAll('dialog').forEach(n=>n.setAttribute('open',''));
    document.querySelectorAll('details').forEach(n=>n.open=true);
    for(const item of dynamic){const host=document.createElement('section');host.dataset.inventorySource=item.file;host.innerHTML=item.tag;document.body.append(host)}
    window.beforeSearch={};
    for(const id of ['searchInput','supplierRegistrySearch','requestsSearch','operationalTaskSearch']){
     const n=document.getElementById(id),r=n.getBoundingClientRect(),s=getComputedStyle(n);
     beforeSearch[id]={width:r.width,height:r.height,font:s.fontSize};
    }
   },{dark,zoom,dynamic});
   await page.addScriptTag({content:read('ui_improvements.js')});
   const boot=read('ui_improvements_boot.js').split("  document.querySelector('#frameworksBody').addEventListener")[0]+'})();';
   await page.addScriptTag({content:boot});
   const result=await page.evaluate(()=>{
    const records=[];
    for(const w of document.querySelectorAll('.pqm-clear-wrap')){
     const n=w.querySelector('input'),b=w.querySelector('.pqm-search-clear');
     const name=n.id||n.getAttribute('data-history')||n.getAttribute('data-audit-filter')||n.placeholder;
     // Chromium does not expose UA shadow pseudo computed styles through
     // getComputedStyle. Check the actual parsed CSSOM suppression rule.
     if(n.type==='search'&&![...document.styleSheets].some(sheet=>[...sheet.cssRules].some(rule=>rule.selectorText?.replaceAll(' ','').includes('.pqm-clear-wrap>input[type="search"]::-webkit-search-cancel-button')&&rule.style.display==='none'&&rule.style.getPropertyValue('-webkit-appearance')==='none')))throw Error(name+': native clear suppression missing');
     const other=document.getElementById('frameworksDk');other.value='4453';
     n.value='';n.dispatchEvent(new Event('input',{bubbles:true}));if(!b.hidden)throw Error(name+': empty clear');
     for(const value of ['Текст','Довгий кириличний текст '.repeat(20)]){
      n.value=value;n.dispatchEvent(new Event('input',{bubbles:true}));
      if(b.hidden||w.querySelectorAll('.pqm-search-clear').length!==1)throw Error(name+': clear count');
      const nr=n.getBoundingClientRect(),br=b.getBoundingClientRect(),wr=w.getBoundingClientRect(),s=getComputedStyle(n);
      if(nr.width>0&&nr.height>0){
       if(nr.x<wr.x-1||nr.right>wr.right+1||br.right>nr.right+1||br.x<nr.x-1)throw Error(name+': geometry '+JSON.stringify({nr,br,wr,display:getComputedStyle(w.parentElement).display,template:getComputedStyle(w.parentElement).gridTemplateColumns,align:getComputedStyle(w).alignSelf,width:getComputedStyle(w).width,parent:w.parentElement.outerHTML.slice(0,120)}));
       if(parseFloat(s.paddingRight)<br.width/Number(document.body.style.zoom))throw Error(name+': text overlaps clear');
      }
     }
     b.click();if(n.value||!b.hidden||other.value!=='4453')throw Error(name+': independent clear');
     const before=beforeSearch[n.id],r=n.getBoundingClientRect();
     if(before&&r.width){
      const allocated=w.parentElement.getBoundingClientRect();
      if(Math.abs(r.width-allocated.width)>1)throw Error(name+': does not fill allocated search width');
      if(Math.abs(r.height-before.height)>1||getComputedStyle(n).fontSize!==before.font)throw Error(name+': height/font changed');
      if(Math.abs(r.y-allocated.y)>1)throw Error(name+': vertical displacement');
     }
     records.push({name,type:n.type,source:n.closest('[data-inventory-source]')?.dataset.inventorySource||'index.html'});
    }
    return records;
   });
   result.forEach(r=>inventory.set(JSON.stringify(r),r));
  }
  console.log(JSON.stringify({result:'PASS',themes:2,zooms:[100,125],widths:[390,768,1440,1920],fields:[...inventory.values()]},null,2));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
