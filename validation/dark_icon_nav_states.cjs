/* Dark icon-only navigation states, rendered with the real Production CSS. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {execFileSync}=require('node:child_process'),{chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..'),OUT=process.env.PQM_VISUAL_EVIDENCE||path.join(ROOT,'evidence','integrated');
const BASE='18072b44b80e9a0c23fbddc3ca6f52548053aea4';
const read=name=>fs.readFileSync(path.join(ROOT,name),'utf8');
const baseline=execFileSync('git',['show',`${BASE}:theme.css`],{cwd:ROOT,encoding:'utf8'});
async function makePage(browser,theme){
 const page=await browser.newPage({viewport:{width:1360,height:360}});
 const css=['styles.css','filters.css','ui_tz2.css'].map(read).join('\n')+'\n'+theme;
 await page.setContent(`<html data-theme="dark"><head><style>${css}</style></head><body>
  <header class="topbar"><div class="brand">PQM</div><nav id="mainNav" aria-label="Основна навігація">
   <button class="main-nav-icon" type="button" aria-label="Звичайна" title="Звичайна">N</button>
   <button class="main-nav-icon nav-active" type="button" aria-label="Активна" title="Активна">A</button>
   <button class="main-nav-icon" type="button" aria-label="Вибрана" aria-selected="true" title="Вибрана">S</button>
   <button class="main-nav-icon" type="button" aria-label="Вимкнена" disabled title="Вимкнена">D</button>
  </nav><div class="service-nav"><button class="service-nav-button" type="button" aria-label="Службова активна"><svg viewBox="0 0 24 24"><path d="M4 4h16v16H4z"/></svg></button>
   <button class="service-nav-button nav-active" type="button" aria-label="Службова активна"><svg viewBox="0 0 24 24"><path d="M4 4h16v16H4z"/></svg></button>
   <button class="service-nav-button" type="button" aria-selected="true" aria-label="Службова вибрана"><svg viewBox="0 0 24 24"><path d="M4 4h16v16H4z"/></svg></button>
   <button class="service-nav-button" type="button" disabled aria-label="Службова вимкнена"><svg viewBox="0 0 24 24"><path d="M4 4h16v16H4z"/></svg></button></div></header>
  </body></html>`);
 return page;
}
async function bg(page,selector){return page.locator(selector).evaluate(e=>getComputedStyle(e).backgroundColor)}
(async()=>{
 fs.mkdirSync(OUT,{recursive:true});const browser=await chromium.launch({headless:true,...(process.env.PQM_TEST_BROWSER?{executablePath:process.env.PQM_TEST_BROWSER}:{})});
 try{
  const old=await makePage(browser,baseline),after=await makePage(browser,read('theme.css'));
  const oldActive=await bg(old,'#mainNav .nav-active');
  const active=await bg(after,'#mainNav .nav-active'),selected=await bg(after,'#mainNav [aria-selected="true"]');
  const normal=await bg(after,'#mainNav button:not(.nav-active):not([aria-selected]):not(:disabled)');
  const service=await bg(after,'.service-nav .nav-active'),serviceSelected=await bg(after,'.service-nav [aria-selected="true"]');
  assert.notEqual(oldActive,active,'baseline should expose the pale active-tab defect');
  assert.equal(active,'rgb(32, 62, 98)');assert.equal(selected,active);assert.equal(service,active);assert.equal(serviceSelected,active);
  assert.equal(normal,'rgb(25, 52, 81)');
  await old.screenshot({path:path.join(OUT,'before-dark-icon-nav.png'),fullPage:true});
  await after.screenshot({path:path.join(OUT,'after-dark-icon-nav.png'),fullPage:true});
  await after.locator('#mainNav button[aria-label="Звичайна"]').hover();
  assert.equal(await bg(after,'#mainNav button[aria-label="Звичайна"]'),'rgb(40, 81, 123)');
  await after.locator('.service-nav button[aria-label="Службова вибрана"]').hover();
  assert.equal(await bg(after,'.service-nav button[aria-label="Службова вибрана"]'),'rgb(40, 81, 123)');
  await after.keyboard.press('Tab');
  const focus=await after.locator(':focus').evaluate(e=>({matches:e.matches(':focus-visible'),outline:getComputedStyle(e).outlineStyle}));
  assert.equal(focus.matches,true);assert.notEqual(focus.outline,'none');
  const disabled=await bg(after,'#mainNav button:disabled'),serviceDisabled=await bg(after,'.service-nav button:disabled');
  assert.equal(disabled,'rgb(19, 40, 64)');assert.equal(serviceDisabled,disabled);
  console.log(JSON.stringify({result:'PASS',baselineActive:oldActive,active,selected,normal,hover:'rgb(40, 81, 123)',keyboardFocus:focus,disabled,serviceActive:service,serviceSelected},null,2));
  await old.close();await after.close();
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
