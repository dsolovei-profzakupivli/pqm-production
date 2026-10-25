/* Browser regression for the compact, collapsed protocol name provenance block. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),read=name=>fs.readFileSync(path.join(root,name),'utf8'),app=read('app.js');
const start=app.indexOf('function protocolSupplierNamesHtml(item){'),end=app.indexOf('\nconst violationProtocolWorkbench=',start);
assert(start>=0&&end>start,'protocol supplier names renderer is missing');
const renderer=app.slice(start,end);
;(async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.PQM_TEST_BROWSER?{executablePath:process.env.PQM_TEST_BROWSER}:{})});
  try{
    const page=await browser.newPage();
    await page.setContent(`<!doctype html><html data-theme="light"><head><style>${read('styles.css')}\n${read('theme.css')}</style></head><body><main id="root"></main><script>
      const esc=value=>String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
      ${renderer}
      const item={protocol_supplier_names:{uses_fallback:true,full_name:{value:'ТОВ «Повна назва»',source_label:'З ЄДР'},short_name:{value:'ТОВ «Повна назва»',source_label:'Повна назва з ЄДР — скороченої немає'},filename_name:{value:'ТОВ «Повна назва»',source_label:'З ЄДР'}}};
      document.querySelector('#root').innerHTML=protocolSupplierNamesHtml(item);
    </script></body></html>`);
    for(const theme of ['light','dark']){
      await page.evaluate(value=>document.documentElement.dataset.theme=value,theme);
      const details=page.locator('details.protocol-supplier-name-provenance');
      assert.equal(await details.count(),1,`${theme}: block exists`);
      await details.evaluate(node=>node.open=false);
      assert.equal(await details.evaluate(node=>node.open),false,`${theme}: collapsed by default`);
      assert.equal(await details.locator('summary').textContent(),'Найменування для нового протоколу');
      await details.locator('summary').click();
      assert.equal(await details.evaluate(node=>node.open),true,`${theme}: expands`);
      assert.equal(await details.locator('dl>div').count(),3,`${theme}: all name/source/explanation rows remain available`);
      assert.equal(await details.locator('dd strong').first().textContent(),'ТОВ «Повна назва»');
      assert.equal(await details.locator('.request-warning').count(),1,`${theme}: source warning remains visible when expanded`);
      const colors=await details.evaluate(node=>({color:getComputedStyle(node).color,bg:getComputedStyle(node).backgroundColor}));
      assert.ok(colors.color&&colors.bg,`${theme}: computed theme styles exist`);
    }
    console.log('PASS: collapsed-by-default protocol names, all source rows and warning expand in light/dark themes');
  }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
