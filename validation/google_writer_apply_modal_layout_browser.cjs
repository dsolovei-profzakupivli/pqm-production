/* Responsive layout regression for the read-only Google Writer details dialog. */
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {chromium}=globalThis.PQM_PLAYWRIGHT_TEST_MODULE||require('playwright');
const browserPath=globalThis.PQM_TEST_BROWSER_PATH||process.env.PQM_TEST_BROWSER;
const root=path.resolve(__dirname,'..');
const read=file=>fs.readFileSync(path.join(root,file),'utf8').replace(/\r\n/g,'\n');
const index=read('index.html');
const dialog=index.match(/<dialog id="googleWriterApplyDetailsDialog"[\s\S]*?<\/dialog>/)?.[0];
assert(dialog,'Google Writer details dialog is present');
const css=['styles.css','theme.css','modules.css'].map(read).join('\n');
const html=`<!doctype html><html data-theme="light"><head><meta charset="utf-8"><style>${css}</style></head><body>
${dialog}<script>
const dialog=document.querySelector('#googleWriterApplyDetailsDialog');
const details=document.querySelector('#googleWriterApplyDetailsBody');
const audit=document.querySelector('#googleWriterSavedContinuationAuditResult');
for(let i=0;i<24;i++){
  for(const parent of [details,audit]){
    const dl=document.createElement('dl');dl.className='google-writer-apply-detail';
    const dt=document.createElement('dt');dt.textContent='Diagnostic field '+i;
    const dd=document.createElement('dd');dd.textContent='LONG_DIAGNOSTIC_CODE_'+i+'_'+('continuation_manifest_binding_mismatch_'.repeat(3));
    dl.append(dt,dd);parent.append(dl);
  }
}
dialog.showModal();
</script></body></html>`;
const sizes=[
  {name:'100%',width:1440,height:900,wide:true},
  {name:'125%',width:1152,height:720,wide:true},
  {name:'150%',width:960,height:600,wide:true},
  {name:'short viewport',width:1440,height:480,wide:true},
  {name:'narrow viewport',width:650,height:600,wide:false},
];
(async()=>{
  let browser;
  try{
    browser=await chromium.launch({headless:true,...(browserPath?{executablePath:browserPath}:{})});
    const page=await browser.newPage();
    await page.setContent(html);
    for(const size of sizes){
      await page.setViewportSize({width:size.width,height:size.height});
      const before=await page.evaluate(()=>{
        const dialog=document.querySelector('dialog');
        const content=dialog.querySelector('.google-writer-apply-scroll');
        const header=dialog.querySelector('form>header');
        const footer=dialog.querySelector('form>footer');
        const rect=node=>{const r=node.getBoundingClientRect();return{x:r.x,y:r.y,width:r.width,height:r.height,top:r.top,bottom:r.bottom,right:r.right}};
        return {viewport:{width:innerWidth,height:innerHeight},dialog:rect(dialog),header:rect(header),footer:rect(footer),
          content:{...rect(content),scrollHeight:content.scrollHeight,clientHeight:content.clientHeight},
          detailsColumns:getComputedStyle(document.querySelector('.google-writer-apply-details')).gridTemplateColumns.split(' ').length,
          auditColumns:getComputedStyle(document.querySelector('.google-writer-saved-continuation-audit-result')).gridTemplateColumns.split(' ').length,
          close:rect(document.querySelector('#googleWriterApplyDetailsClose')),
          footerButtons:[...footer.querySelectorAll('button')].map(rect)};
      });
      assert(before.dialog.top>=0&&before.dialog.bottom<=size.height,`${size.name}: dialog stays in viewport`);
      assert(before.content.scrollHeight>before.content.clientHeight,`${size.name}: inner content scrolls`);
      assert.equal(before.detailsColumns,size.wide?2:1,`${size.name}: diagnostic grid column count`);
      assert.equal(before.auditColumns,size.wide?2:1,`${size.name}: saved audit grid column count`);
      assert(before.close.top>=before.dialog.top&&before.close.bottom<=before.header.bottom,`${size.name}: close control remains in header`);
      assert(before.footerButtons.every(button=>button.top>=before.footer.top&&button.bottom<=before.footer.bottom&&button.right<=before.dialog.right),
        `${size.name}: all footer actions are visible ${JSON.stringify({dialog:before.dialog,footer:before.footer,buttons:before.footerButtons})}`);
      await page.locator('.google-writer-apply-scroll').evaluate(node=>{node.scrollTop=node.scrollHeight});
      const after=await page.evaluate(()=>({header:document.querySelector('form>header').getBoundingClientRect().top,
        footer:document.querySelector('form>footer').getBoundingClientRect().bottom,
        scrollTop:document.querySelector('.google-writer-apply-scroll').scrollTop}));
      assert(Math.abs(after.header-before.header.top)<1,`${size.name}: header stays fixed while scrolling`);
      assert(Math.abs(after.footer-before.footer.bottom)<1,`${size.name}: footer stays fixed while scrolling`);
      assert(after.scrollTop>0,`${size.name}: content scroll position changes`);
      console.log(`PASS ${size.name} (${size.width}x${size.height})`);
    }
  }finally{if(browser)await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
