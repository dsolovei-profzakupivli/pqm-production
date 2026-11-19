/* Regression for pinned Applications table cells in the actual decorated Sandbox HTML. */
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..');
const served=process.env.PQM_SERVED_HTML||path.join(root,'..','pqm-sandbox-personal-theme-evidence-20261018','served-candidate.html');
const out=process.env.PQM_THEME_EVIDENCE||require('os').tmpdir();
const html=fs.readFileSync(served,'utf8');
const baselinePalette=execFileSync('git',['show','e7c85108cecb218daf1aded0054c0d1a036b293d:theme.css'],{cwd:root,encoding:'utf8'});
let palette=baselinePalette;
const expected={head:'rgb(21, 43, 70)',normal:'rgb(16, 34, 56)',active:'rgb(32, 62, 98)',ink:'rgb(237, 243, 252)'};
function rgb(hex){return hex.match(/[\da-f]{2}/gi).map(x=>parseInt(x,16))}
function luminance(value){const c=value.match(/[\d.]+/g).slice(0,3).map(Number).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4});return .2126*c[0]+.7152*c[1]+.0722*c[2]}
function contrast(a,b){const x=luminance(a),y=luminance(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05)}
(async()=>{
  fs.mkdirSync(out,{recursive:true});
  const browser=await chromium.launch({headless:true,...(process.env.PQM_TEST_BROWSER?{executablePath:process.env.PQM_TEST_BROWSER}:{})});
  try{
    const page=await browser.newPage({viewport:{width:1920,height:1000},deviceScaleFactor:1});
    await page.route('http://pqm.dark-table.fixture/**',route=>{
      const url=new URL(route.request().url());
      if(url.pathname==='/')return route.fulfill({body:html,contentType:'text/html'});
      const file=path.join(root,url.pathname.replace(/^\//,''));
      if(!fs.existsSync(file))return route.abort();
      if(file.endsWith('.js'))return route.fulfill({body:'',contentType:'application/javascript'});
      if(file.endsWith('theme.css'))return route.fulfill({body:palette,contentType:'text/css'});
      return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.css')?'text/css':'image/svg+xml'});
    });
    await page.goto('http://pqm.dark-table.fixture/');
    const setup=()=>{
      document.documentElement.dataset.theme='dark';
      const login=document.querySelector('#loginGate'),shell=document.querySelector('#applicationShell');
      if(login)login.hidden=true;if(shell)shell.hidden=false;
      const target=document.querySelector('#applicationsView');
      if(!target)throw new Error('Actual Sandbox HTML is missing #applicationsView');
      document.querySelectorAll('main').forEach(main=>main.hidden=main!==target);
      target.hidden=false;
      const table=target.querySelector('#applicationsTable');
      if(!table)throw new Error('Actual Sandbox HTML is missing #applicationsTable');
      const nav=document.querySelector('#mainNav');
      if(nav)nav.innerHTML='<button id="fixtureFolderText" class="main-nav-icon-text nav-active"><svg aria-label="Папка" viewBox="0 0 24 24"><path d="M3 6h7l2 2h9v11H3z"/></svg><span>База постачальників</span></button><button id="fixtureFolderIcon" class="main-nav-icon nav-active" aria-label="База постачальників"><svg viewBox="0 0 24 24"><path d="M3 6h7l2 2h9v11H3z"/></svg></button><button id="fixtureOtherNav" class="main-nav-icon"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/></svg></button>';
      let history=document.querySelector('#historyView');
      if(history){const pager=history.querySelector('.pagination');if(pager)pager.innerHTML='<span>Сторінка 1 із 7 · 322 записів</span><button>←</button><button>→</button>';}
      table.innerHTML='<thead><tr><th class="sticky" style="width:100px;min-width:100px;max-width:100px;left:0px">Вибір</th><th class="sticky" style="width:160px;min-width:160px;max-width:160px;left:100px">Дата</th><th class="sticky" style="width:220px;min-width:220px;max-width:220px;left:260px">Назва учасника</th><th>Решта таблиці</th></tr></thead><tbody><tr data-case="ordinary"><td class="sticky" style="width:100px;left:0px">звичайний</td><td class="sticky" style="width:160px;left:100px">звичайний</td><td class="sticky" style="width:220px;left:260px">звичайний</td><td>Звичайна клітинка</td></tr><tr data-case="active" class="active"><td class="sticky" style="width:100px;left:0px">активний</td><td class="sticky" style="width:160px;left:100px">активний</td><td class="sticky" style="width:220px;left:260px">активний</td><td>Активний рядок</td></tr><tr data-case="checked" class="application-review-completed"><td class="sticky" style="width:100px;left:0px"><input class="row-check" type="checkbox" checked></td><td class="sticky" style="width:160px;left:100px">вибраний</td><td class="sticky" style="width:220px;left:260px">вибраний</td><td>Розглянуто</td></tr><tr data-case="locked" class="application-final-locked"><td class="sticky locked" style="width:100px;left:0px">заблоковано</td><td class="sticky locked" style="width:160px;left:100px">заблоковано</td><td class="sticky locked" style="width:220px;left:260px">заблоковано</td><td>Фінальне рішення</td></tr></tbody>';
    };
    await page.evaluate(setup);
    const before=await page.locator('#applicationsTable').evaluate(table=>{
      const read=e=>({bg:getComputedStyle(e).backgroundColor,color:getComputedStyle(e).color});
      return {header:read(table.querySelector('th.sticky')),ordinary:read(table.querySelector('tr[data-case="ordinary"] td.sticky')),active:read(table.querySelector('tr[data-case="active"] td.sticky')),checked:read(table.querySelector('tr[data-case="checked"] td.sticky'))};
    });
    assert.notEqual(before.header.bg,expected.head,'baseline must reproduce the light sticky header');
    assert.notEqual(before.ordinary.bg,expected.normal,'baseline must reproduce the light sticky cell');
    const beforeNav=await page.locator('#fixtureFolderIcon').evaluate(e=>({bg:getComputedStyle(e).backgroundColor,border:getComputedStyle(e).borderColor}));
    const beforePager=await page.locator('#historyView>.pagination').evaluate(e=>getComputedStyle(e).backgroundColor);
    assert.equal(beforeNav.bg,'rgb(234, 244, 255)','baseline must reproduce the pale active nav fill');
    assert.notEqual(beforePager,'rgb(19, 40, 64)','baseline must reproduce the transparent history pager');
    await page.screenshot({path:path.join(out,'applications-dark-table-before.png'),fullPage:true});
    await page.locator('#mainNav').screenshot({path:path.join(out,'dark-navbar-before.png')});
    await page.evaluate(()=>{document.querySelectorAll('main').forEach(e=>e.hidden=e.id!=='historyView');const h=document.querySelector('#historyView');if(!h)throw Error('Missing actual #historyView');h.hidden=false;const table=h.querySelector('.history-table');if(table)table.innerHTML='<table><thead><tr><th>Дата</th><th>Історія</th></tr></thead><tbody><tr><td>18.10.2026</td><td>Ізольований запис історії</td></tr></tbody></table>';});
    await page.screenshot({path:path.join(out,'dark-history-pagination-before.png'),fullPage:true});
    palette=fs.readFileSync(path.join(root,'theme.css'),'utf8');
    await page.reload();
    await page.evaluate(setup);
    async function verify(){
      const state=await page.locator('#applicationsTable').evaluate(table=>{
        const color=e=>getComputedStyle(e).backgroundColor;
        const ink=e=>getComputedStyle(e).color;
        const cells=selector=>[...table.querySelectorAll(selector)].map(e=>({bg:color(e),color:ink(e),inline:e.style.backgroundColor}));
        return {header:cells('thead th.sticky'),ordinary:cells('tbody tr[data-case="ordinary"] td.sticky'),active:cells('tbody tr[data-case="active"] td.sticky'),checked:cells('tbody tr[data-case="checked"] td.sticky'),locked:cells('tbody tr[data-case="locked"] td.sticky')};
      });
      assert(state.header.length>=1);assert(state.ordinary.length>=1);assert(state.active.length>=1);assert(state.checked.length>=1);assert(state.locked.length>=1);
      for(const cell of state.header){assert.equal(cell.bg,expected.head,'pinned table header must use dark header surface');assert.equal(cell.color,expected.ink);assert.equal(cell.inline,'','no inline background in generated header');}
      for(const cell of state.ordinary){assert.equal(cell.bg,expected.normal,'ordinary pinned cell must use dark row surface');assert.equal(cell.color,expected.ink);assert.equal(cell.inline,'','no inline background in generated cell');}
      for(const group of [state.active,state.checked])for(const cell of group){assert.equal(cell.bg,expected.active,'active/checked pinned cells must use dark selection surface');assert.equal(cell.color,expected.ink);}
      for(const cell of state.locked){assert.notEqual(cell.bg,'rgb(255, 255, 255)','locked pinned cell must not retain light fill');assert.equal(cell.color,expected.ink);}
      return state;
    }
    let states=await verify();
    const darkNav=await page.locator('#fixtureFolderIcon').evaluate(e=>({bg:getComputedStyle(e).backgroundColor,color:getComputedStyle(e).color,border:getComputedStyle(e).borderColor,svg:getComputedStyle(e.querySelector('svg')).color}));
    const darkTextNav=await page.locator('#fixtureFolderText').evaluate(e=>getComputedStyle(e).backgroundColor);
    const darkPager=await page.locator('#historyView>.pagination').evaluate(e=>({bg:getComputedStyle(e).backgroundColor,color:getComputedStyle(e).color,rect:(()=>{const r=e.getBoundingClientRect();return [r.x,r.y,r.width,r.height]})()}));
    assert.equal(darkNav.bg,'rgb(32, 62, 98)','active icon-only nav item must be dark');
    assert.equal(darkNav.border,'rgb(134, 189, 255)','active nav item must retain a blue active outline');
    assert.equal(darkTextNav,'rgb(32, 62, 98)','active icon+text nav item must be dark');
    assert.equal(darkPager.bg,'rgb(19, 40, 64)','history pager needs a dark solid surface');
    assert.equal(darkPager.color,'rgb(237, 243, 252)','history pager text must be legible');
    const svgColorsBefore=await page.locator('#fixtureFolderIcon svg').evaluate(e=>({fill:getComputedStyle(e).fill,stroke:getComputedStyle(e).stroke,color:getComputedStyle(e).color}));
    await page.evaluate(()=>document.documentElement.dataset.theme='light');
    const lightNav=await page.locator('#fixtureFolderIcon').evaluate(e=>getComputedStyle(e).backgroundColor);
    const lightPager=await page.locator('#historyView>.pagination').evaluate(e=>getComputedStyle(e).backgroundColor);
    assert.equal(lightNav,'rgb(234, 244, 255)','light nav active styling must remain unchanged');
    assert.notEqual(lightPager,'rgb(19, 40, 64)','light history pager must remain unchanged');
    await page.evaluate(()=>document.documentElement.dataset.theme='dark');
    const switchedNav=await page.locator('#fixtureFolderIcon').evaluate(e=>getComputedStyle(e).backgroundColor);
    const switchedPager=await page.locator('#historyView>.pagination').evaluate(e=>getComputedStyle(e).backgroundColor);
    assert.equal(switchedNav,darkNav.bg,'theme switch back to dark must apply without reload');
    assert.equal(switchedPager,darkPager.bg,'theme switch back to dark must apply without reload');
    const svgColorsAfter=await page.locator('#fixtureFolderIcon svg').evaluate(e=>({fill:getComputedStyle(e).fill,stroke:getComputedStyle(e).stroke,color:getComputedStyle(e).color}));
    assert.deepEqual(svgColorsAfter,svgColorsBefore,'SVG icon paint must not be modified by the dark active state');
    const navGeometryBefore=await page.locator('#mainNav button').evaluateAll(es=>es.map(e=>{const r=e.getBoundingClientRect();return [r.x,r.y,r.width,r.height]}));
    await page.evaluate(()=>document.documentElement.dataset.theme='light');await page.evaluate(()=>document.documentElement.dataset.theme='dark');
    const navGeometryAfter=await page.locator('#mainNav button').evaluateAll(es=>es.map(e=>{const r=e.getBoundingClientRect();return [r.x,r.y,r.width,r.height]}));
    assert.deepEqual(navGeometryAfter,navGeometryBefore,'theme switching must not move/resize navbar buttons');
    await page.locator('#fixtureFolderIcon').hover({force:true});
    const navHover=await page.locator('#fixtureFolderIcon').evaluate(e=>getComputedStyle(e).backgroundColor);
    assert.equal(navHover,'rgb(40, 81, 123)','active nav hover must keep a dark, legible fill');
    await page.locator('#fixtureFolderIcon').focus();
    const navFocus=await page.locator('#fixtureFolderIcon').evaluate(e=>({outline:getComputedStyle(e).outlineColor,bg:getComputedStyle(e).backgroundColor}));
    assert.equal(navFocus.outline,'rgb(255, 220, 138)','active nav focus ring must remain visible');
    await page.locator('#mainNav').screenshot({path:path.join(out,'dark-navbar-active.png')});
    await page.evaluate(()=>{document.querySelectorAll('main').forEach(e=>e.hidden=e.id!=='historyView');const h=document.querySelector('#historyView');if(!h)throw Error('Missing actual #historyView');h.hidden=false;const table=h.querySelector('.history-table');if(table)table.innerHTML='<table><thead><tr><th>Дата</th><th>Історія</th></tr></thead><tbody><tr><td>18.10.2026</td><td>Ізольований запис історії</td></tr></tbody></table>';});
    const visiblePager=await page.locator('#historyView>.pagination').evaluate(e=>{const r=e.getBoundingClientRect();return {bg:getComputedStyle(e).backgroundColor,color:getComputedStyle(e).color,width:r.width,height:r.height}});
    assert(visiblePager.width>0&&visiblePager.height>0,'history pager must be rendered in the visible history view');
    assert.equal(visiblePager.bg,'rgb(19, 40, 64)');
    await page.screenshot({path:path.join(out,'dark-history-pagination.png'),fullPage:true});
    await page.evaluate(()=>{document.querySelectorAll('main').forEach(e=>e.hidden=e.id!=='applicationsView');document.querySelector('#applicationsView').hidden=false;});
    await page.screenshot({path:path.join(out,'applications-dark-table-after.png'),fullPage:true});
    await page.locator('#applicationsTable tbody tr[data-case="ordinary"]').hover({force:true});
    const hover=await page.locator('#applicationsTable tbody tr[data-case="ordinary"] td.sticky').first().evaluate(e=>getComputedStyle(e).backgroundColor);
    assert.equal(hover,expected.active,'hover must use dark selection surface');
    await page.locator('#applicationsTable tbody').evaluate(body=>{body.innerHTML='<tr data-case="ordinary"><td class="sticky" style="width:100px;left:0px">оновлено після фільтра</td><td class="sticky" style="width:160px;left:100px">оновлено</td><td class="sticky" style="width:220px;left:260px">оновлено</td><td>Динамічно перерендерено</td></tr><tr data-case="checked" class="application-review-completed"><td class="sticky"><input class="row-check" type="checkbox" checked></td><td class="sticky">знову вибраний</td><td class="sticky">знову вибраний</td><td>Динамічно вибраний рядок</td></tr>'});
    await page.mouse.move(1800,20);
    const updated=await page.locator('#applicationsTable tbody tr[data-case="ordinary"] td.sticky').first().evaluate(e=>getComputedStyle(e).backgroundColor);
    const updatedChecked=await page.locator('#applicationsTable tbody tr[data-case="checked"] td.sticky').first().evaluate(e=>({bg:getComputedStyle(e).backgroundColor,color:getComputedStyle(e).color}));
    assert.equal(updated,expected.normal,'dynamically inserted pinned cell must use dark surface');
    assert.deepEqual(updatedChecked,{bg:expected.active,color:expected.ink},'dynamically inserted checked row must remain legible');
    const minContrast=Math.min(contrast(expected.ink,expected.head),contrast(expected.ink,expected.normal),contrast(expected.ink,expected.active));
    assert(minContrast>=7,`table text contrast must be at least 7:1; got ${minContrast.toFixed(2)}`);
    const responsive=[];
    for(const width of [1920,1366,900,760])for(const zoom of [.75,.8,1,1.25]){await page.setViewportSize({width,height:1000});await page.evaluate(zoom=>{document.body.style.zoom=String(zoom);document.documentElement.dataset.theme='dark'},zoom);const dims=await page.locator('#mainNav button').evaluateAll(es=>es.map(e=>{const r=e.getBoundingClientRect();return [Math.round(r.width),Math.round(r.height)]}));assert(dims.every(([w,h])=>w>0&&h>0),'navbar buttons must remain visible at responsive widths and zoom levels');const activeBg=await page.locator('#fixtureFolderIcon').evaluate(e=>getComputedStyle(e).backgroundColor);assert.equal(activeBg,'rgb(32, 62, 98)');responsive.push({width,zoom,buttons:dims.length});}
    await page.evaluate(()=>document.body.style.zoom='1');
    console.log(JSON.stringify({result:'PASS',scenarios:32,before,beforeNav,beforePager,states,darkNav,darkTextNav,darkPager,visiblePager,lightNav,lightPager,switchedNav,switchedPager,navGeometryUnchanged:true,svgColorsUnchanged:true,navFocus,navHover,hover,updated,updatedChecked,minContrast:Number(minContrast.toFixed(2)),responsive,screenshots:{tableBefore:path.join(out,'applications-dark-table-before.png'),tableAfter:path.join(out,'applications-dark-table-after.png'),navBefore:path.join(out,'dark-navbar-before.png'),navAfter:path.join(out,'dark-navbar-active.png'),pagerBefore:path.join(out,'dark-history-pagination-before.png'),pagerAfter:path.join(out,'dark-history-pagination.png')},servedHtml:path.basename(served)}));
    await page.close();
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
