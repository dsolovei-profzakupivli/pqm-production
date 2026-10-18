/* Production HTML, actual theme module, synthetic read-only fixture. */
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),out=process.env.PQM_THEME_EVIDENCE||require('os').tmpdir();
(async()=>{
 const original=fs.readFileSync(path.join(root,'assets/pqm-brand-mark-prod.svg'),'utf8').replaceAll('\r\n','\n').trim();
 const dark=fs.readFileSync(path.join(root,'assets/pqm-brand-mark-prod-dark.svg'),'utf8').trim();
 assert.equal(dark,original.replaceAll('fill="#132840"','fill="#fff"'),'Only P/M fills may change');
 const html=fs.readFileSync(process.env.PQM_SERVED_HTML||path.join(root,'index.html'),'utf8');
 assert.equal(html,fs.readFileSync(path.join(root,'index.html'),'utf8'),'Served Production HTML must match candidate');
 const browser=await chromium.launch({headless:true,...(process.env.PQM_TEST_BROWSER?{executablePath:process.env.PQM_TEST_BROWSER}:{})});
 const results=[];
 try{for(const width of [1920,1280,800,390])for(const zoom of [1,1.25]){
  const page=await browser.newPage({viewport:{width,height:1000}}),errors=[];
  page.on('pageerror',e=>errors.push(String(e)));
  await page.route('**/*',r=>{
   const u=new URL(r.request().url());if(u.origin!=='http://pqm.test')return r.abort();
   const file=path.join(root,u.pathname==='/'?'index.html':u.pathname);
   if(!fs.existsSync(file))return r.abort();
   if(file.endsWith('.js')&&!['theme_ui.js','nav_icons.js'].includes(path.basename(file)))return r.fulfill({body:'',contentType:'application/javascript'});
   return r.fulfill({body:u.pathname==='/'?html:fs.readFileSync(file),contentType:file.endsWith('.html')?'text/html':file.endsWith('.css')?'text/css':file.endsWith('.js')?'application/javascript':'image/svg+xml'});
  });
  await page.goto('http://pqm.test/');
  await page.evaluate(zoom=>{document.body.style.zoom=String(zoom);document.getElementById('loginGate').hidden=true;document.getElementById('applicationShell').hidden=false;document.querySelectorAll('main').forEach(n=>n.hidden=n.id!=='applicationsView');},zoom);
  let geometry;
  for(const theme of ['light','dark','light']){
   assert.equal(await page.evaluate(t=>PqmThemeUI.apply(t),theme),theme);
   await page.locator('.prod-brand-initials').evaluate(n=>n.decode());
   const state=await page.evaluate(()=>{
    const logo=document.querySelector('.prod-brand-initials'),bar=document.querySelector('.topbar'),copy=document.querySelector('.prod-brand-copy');
    const rect=n=>{const r=n.getBoundingClientRect();return [r.x,r.y,r.width,r.height]};
    return{src:logo.getAttribute('src'),filter:getComputedStyle(logo).filter,text:[...copy.children].map(n=>getComputedStyle(n).color),bg:getComputedStyle(document.body).backgroundColor,geometry:[bar,logo,copy,document.getElementById('mainNav')].map(rect),logo:rect(logo),bar:rect(bar)};
   });
   assert.equal(state.src,`/assets/pqm-brand-mark-prod${theme==='dark'?'-dark':''}.svg`);
   assert.equal(state.filter,'none');
   if(theme==='dark')assert.deepEqual(state.text,['rgb(255, 255, 255)','rgb(255, 255, 255)']);
   assert.equal(state.bg,theme==='dark'?'rgb(11, 23, 42)':'rgb(245, 247, 248)');
   if(geometry)assert.deepEqual(state.geometry,geometry,'Theme switch changed header geometry');else geometry=state.geometry;
   assert(state.logo[0]>=0&&state.logo[0]+state.logo[2]<=width,'Logo outside viewport');
   assert(state.logo[1]>=state.bar[1]&&state.logo[1]+state.logo[3]<=state.bar[1]+state.bar[3]+1,'Logo clipped');
   const filename=`logo-${width}-${zoom}-${theme}.png`;
   await page.locator('.topbar').screenshot({path:path.join(out,filename)});
   results.push({width,zoom,theme,...state});
  }
  assert.deepEqual(errors,[]);await page.close();
 }}finally{await browser.close()}
 fs.writeFileSync(path.join(out,'LOGO_RESULTS.json'),JSON.stringify(results,null,2));
 console.log('LOGO_BROWSER=PASS; cases='+results.length+'; light/dark/light; original Q and geometry preserved');
})().catch(e=>{console.error(e);process.exitCode=1});
