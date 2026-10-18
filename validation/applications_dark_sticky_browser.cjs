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
      table.innerHTML='<thead><tr><th class="sticky" style="width:100px;min-width:100px;max-width:100px;left:0px">Вибір</th><th class="sticky" style="width:160px;min-width:160px;max-width:160px;left:100px">Дата</th><th class="sticky" style="width:220px;min-width:220px;max-width:220px;left:260px">Назва учасника</th><th>Решта таблиці</th></tr></thead><tbody><tr data-case="ordinary"><td class="sticky" style="width:100px;left:0px">звичайний</td><td class="sticky" style="width:160px;left:100px">звичайний</td><td class="sticky" style="width:220px;left:260px">звичайний</td><td>Звичайна клітинка</td></tr><tr data-case="active" class="active"><td class="sticky" style="width:100px;left:0px">активний</td><td class="sticky" style="width:160px;left:100px">активний</td><td class="sticky" style="width:220px;left:260px">активний</td><td>Активний рядок</td></tr><tr data-case="checked" class="application-review-completed"><td class="sticky" style="width:100px;left:0px"><input class="row-check" type="checkbox" checked></td><td class="sticky" style="width:160px;left:100px">вибраний</td><td class="sticky" style="width:220px;left:260px">вибраний</td><td>Розглянуто</td></tr><tr data-case="locked" class="application-final-locked"><td class="sticky locked" style="width:100px;left:0px">заблоковано</td><td class="sticky locked" style="width:160px;left:100px">заблоковано</td><td class="sticky locked" style="width:220px;left:260px">заблоковано</td><td>Фінальне рішення</td></tr></tbody>';
    };
    await page.evaluate(setup);
    const before=await page.locator('#applicationsTable').evaluate(table=>{
      const read=e=>({bg:getComputedStyle(e).backgroundColor,color:getComputedStyle(e).color});
      return {header:read(table.querySelector('th.sticky')),ordinary:read(table.querySelector('tr[data-case="ordinary"] td.sticky')),active:read(table.querySelector('tr[data-case="active"] td.sticky')),checked:read(table.querySelector('tr[data-case="checked"] td.sticky'))};
    });
    assert.notEqual(before.header.bg,expected.head,'baseline must reproduce the light sticky header');
    assert.notEqual(before.ordinary.bg,expected.normal,'baseline must reproduce the light sticky cell');
    await page.screenshot({path:path.join(out,'applications-dark-table-before.png'),fullPage:true});
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
    console.log(JSON.stringify({result:'PASS',scenarios:9,before,states,hover,updated,updatedChecked,minContrast:Number(minContrast.toFixed(2)),screenshots:{before:path.join(out,'applications-dark-table-before.png'),after:path.join(out,'applications-dark-table-after.png')},servedHtml:path.basename(served)}));
    await page.close();
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
