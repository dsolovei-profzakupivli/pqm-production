/* Read-only offline protocol presentation acceptance. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('playwright'),root=path.resolve(__dirname,'..'),read=n=>fs.readFileSync(path.join(root,n),'utf8');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.PQM_TEST_BROWSER});
 const page=await browser.newPage();await page.route('**/*',r=>r.abort());
 try{
  await page.setContent('<table><tbody id="requestsBody"></tbody></table>');
  for(const name of ['styles.css','modules.css','sandbox_theme.css','ui_tz2.css'])await page.addStyleTag({content:read(name)});
  await page.evaluate(()=>{window.esc=s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');window.displayDateOnly=s=>s});
  await page.addScriptTag({content:read('app.js').split(/\r?\n/).find(s=>s.startsWith('function violationProtocolCell('))});
  for(const dark of [false,true])for(const zoom of [1,1.25])for(const width of [390,1440])for(const ready of [false,true]){
   await page.setViewportSize({width,height:900});
   await page.evaluate(({dark,zoom,ready})=>{
    document.documentElement.dataset.pqmEnvironment=dark?'sandbox':'';document.body.style.zoom=zoom;
    if(violationProtocolCell({},0)!=='')throw Error('Pre-generation cell not empty');
    const p={number:'12345/довгі-реквізити/2026',date:'17.10.2026',url:'/api/protocol/files/current.docx',officer:'ІСТОРИЧНА ВІДПОВІДАЛЬНА ОСОБА ПРОТОКОЛУ',askod:'Незмінний опис',json_ready:ready};
    document.getElementById('requestsBody').innerHTML='<tr><td>'+violationProtocolCell({protocol_summary:p},7)+'</td></tr>';
   },{dark,zoom,ready});
   const result=await page.locator('.request-protocol-cell').evaluate(n=>{
    const heading=n.querySelector('.request-protocol-heading'),copy=n.querySelector('.request-protocol-copy'),link=heading.querySelector('a');
    const r=link.getBoundingClientRect(),b=[...copy.children].map(x=>x.getBoundingClientRect());
    return {rows:n.children.length,icon:[r.width,r.height],url:link.getAttribute('href'),json:!!n.querySelector('[data-protocol-json]'),officer:n.children[1].textContent,copyRow:b.every(x=>Math.abs(x.y-b[0].y)<1),copyOverflow:copy.scrollWidth>copy.clientWidth};
   });
   assert.equal(result.rows,3);assert.deepEqual(result.icon,[28*zoom,28*zoom]);assert.equal(result.url,'/api/protocol/files/current.docx');assert.equal(result.json,ready);assert.match(result.officer,/ІСТОРИЧНА/);assert(result.copyRow&&!result.copyOverflow);
  }
  console.log('UI_TZ3_PROTOCOL=PASS; phases/3-rows/icon/current-document/historical-officer/themes/zoom/narrow');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
