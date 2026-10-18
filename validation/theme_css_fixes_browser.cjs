/* Visual smoke: real PQM markup/CSS with isolated synthetic presentation rows. */
const fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..');
const out=process.env.PQM_UI_EVIDENCE_DIR||path.resolve(root,'..','pqm-sandbox-next-visual-evidence-20261018');
const read=name=>fs.readFileSync(path.join(root,name),'utf8');

(async()=>{
  fs.mkdirSync(out,{recursive:true});
  const browser=await chromium.launch({headless:true,...(process.env.PQM_TEST_BROWSER?{executablePath:process.env.PQM_TEST_BROWSER}:{})});
  const page=await browser.newPage({viewport:{width:1440,height:1000},deviceScaleFactor:1});
  const errors=[];page.on('pageerror',error=>errors.push(String(error)));
  try{
    await page.setContent(read('index.html').replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,''));
    for(const name of ['styles.css','filters.css','modules.css','schema_ui.css','ui_improvements.css','ui_final.css','theme.css'])
      await page.addStyleTag({content:read(name)});
    await page.evaluate(()=>{
      document.documentElement.dataset.pqmEnvironment='sandbox';
      document.body.dataset.authRole='admin';
      document.querySelector('#loginGate').hidden=true;
      document.querySelector('#applicationShell').hidden=false;
      document.querySelector('#mainNav').innerHTML='<button>Робота УО</button><button class="nav-active">Відбори</button><button>База постачальників</button>';
      document.querySelector('#frameworkAnalyticsView').hidden=false;
      document.querySelector('#frameworksBody').innerHTML='<tr><td><input type="checkbox" checked></td><td>44530000-4</td><td><span class="framework-number"><a href="#">UA-F-2026-10-01-000001</a></span><small>AGREEMENT-001</small></td><td>Матеріали та обладнання</td><td>Активний</td><td>12</td><td>8</td><td>1</td><td>3</td><td><a class="ghost" href="#">Завантажити реєстр</a></td></tr><tr><td><input type="checkbox"></td><td>39100000-3</td><td><span class="framework-number"><a href="#">UA-F-2026-10-02-000002</a></span><small>AGREEMENT-002</small></td><td>Меблі</td><td>Активний</td><td>7</td><td>5</td><td>0</td><td>2</td><td><a class="ghost" href="#">Завантажити реєстр</a></td></tr>';
      document.querySelector('#frameworksTotal').textContent='2';
      document.querySelector('#frameworksPageInfo').textContent='Сторінка 1 із 1 · відборів 2';
      document.querySelector('#frameworksSyncStatus').textContent='Локальний кеш Prozorro. Експорт не запускає синхронізацію.';
      const body=document.querySelector('#supplierProfileBody');
      body.innerHTML='<section class="supplier-profile-section supplier-profile-edr"><h3>Керівник та відомості з ЄДР</h3><div class="supplier-edr-actions"><a href="#">↗ Clarity Project</a></div><dl class="supplier-edr-metadata">'+[
        ['Статус у Prozorro','Є у реєстрі'],['Статус у реєстрі (ЄДР)','Зареєстровано'],['Актуальність ЄДР','🟢 До 30 днів'],['Дата перевірки','16.10.2026']
      ].map(([label,value])=>`<div><dt>${label}</dt><dd>${value}</dd></div>`).join('')+'</dl></section>';
      document.querySelector('#supplierProfileTitle').textContent='ТОВ «ДЕМОНСТРАЦІЙНИЙ ПОСТАЧАЛЬНИК»';
      document.querySelector('#supplierProfileSubtitle').innerHTML='ЄДРПОУ / РНОКПП: <strong>12345678</strong>';
    });
    await page.locator('#frameworksExportSelected').evaluate(node=>{node.hidden=false;node.textContent='Експорт вибраних (1)';node.href='#'});

    // Capture the pre-fix states by restoring only the two diagnosed old rules.
    await page.evaluate(()=>{document.documentElement.dataset.theme='dark';const s=document.createElement('style');s.id='beforeRules';s.textContent='html[data-pqm-environment="sandbox"] .supplier-edr-metadata>div{background:#132840;color:#edf3fc;border-color:#44617f}html[data-pqm-environment="sandbox"] .supplier-edr-metadata dt{color:#b2c3db}#frameworkAnalyticsView .frameworks-table a.ghost,#frameworkAnalyticsView #frameworksExportSelected{background:#fff!important;color:#344357!important;border-color:#cbd4dc!important}';document.head.append(s)});
    const beforeExport=await page.locator('#frameworksBody a.ghost').first().evaluate(node=>getComputedStyle(node).backgroundColor);
    if(beforeExport!=='rgb(255, 255, 255)')throw new Error('Before-fix export link did not reproduce white surface: '+beforeExport);
    await page.screenshot({path:path.join(out,'before-dark-framework-exports.png'),fullPage:true});
    await page.locator('#frameworkAnalyticsView').screenshot({path:path.join(out,'before-dark-framework-exports-crop.png')});
    await page.evaluate(()=>{document.querySelector('#frameworkAnalyticsView').hidden=true;document.querySelector('#supplierProfileDialog').showModal()});
    const beforeClarity=await page.locator('.supplier-edr-actions a').evaluate(node=>getComputedStyle(node).backgroundColor);
    if(beforeClarity!=='rgb(25, 52, 81)')throw new Error('Before-fix Clarity action did not reproduce dark Sandbox fill: '+beforeClarity);
    await page.screenshot({path:path.join(out,'before-light-supplier-edr.png'),fullPage:true});
    await page.locator('#supplierProfileDialog').screenshot({path:path.join(out,'before-light-supplier-edr-crop.png')});

    await page.evaluate(()=>{document.querySelector('#beforeRules').remove();document.querySelector('#supplierProfileDialog').close();document.documentElement.dataset.theme='dark';document.querySelector('#frameworkAnalyticsView').hidden=false});
    const darkExport=await page.locator('#frameworksBody a.ghost').first().evaluate(node=>getComputedStyle(node).backgroundColor);
    if(darkExport!=='rgb(25, 52, 81)')throw new Error('Dark export surface mismatch: '+darkExport);
    await page.screenshot({path:path.join(out,'after-dark-framework-exports.png'),fullPage:true});
    await page.locator('#frameworkAnalyticsView').screenshot({path:path.join(out,'after-dark-framework-exports-crop.png')});
    await page.evaluate(()=>{document.querySelector('#frameworkAnalyticsView').hidden=true;document.documentElement.dataset.theme='light';document.querySelector('#supplierProfileDialog').showModal()});
    const lightEdr=await page.locator('.supplier-edr-metadata>div').first().evaluate(node=>getComputedStyle(node).backgroundColor);
    if(lightEdr!=='rgb(246, 249, 253)')throw new Error('Light EDR cards are not using the light surface: '+lightEdr);
    const lightClarity=await page.locator('.supplier-edr-actions a').evaluate(node=>getComputedStyle(node).backgroundColor);
    if(lightClarity!=='rgb(247, 249, 252)')throw new Error('Light Clarity action surface mismatch: '+lightClarity);
    await page.screenshot({path:path.join(out,'after-light-supplier-edr.png'),fullPage:true});
    await page.locator('#supplierProfileDialog').screenshot({path:path.join(out,'after-light-supplier-edr-crop.png')});

    await page.evaluate(()=>{document.documentElement.dataset.theme='dark'});
    const darkClarity=await page.locator('.supplier-edr-actions a').evaluate(node=>getComputedStyle(node).backgroundColor);
    if(darkClarity!=='rgb(25, 52, 81)')throw new Error('Dark Clarity action no longer follows dark palette: '+darkClarity);
    await page.locator('.supplier-edr-actions a').hover();
    const darkClarityHover=await page.locator('.supplier-edr-actions a').evaluate(node=>getComputedStyle(node).backgroundColor);
    if(darkClarityHover!=='rgb(40, 81, 123)')throw new Error('Dark Clarity hover mismatch: '+darkClarityHover);

    if(errors.length)throw new Error('Browser errors: '+errors.join('; '));
    console.log(`THEME_CSS_BROWSER=PASS screenshots=${out}`);
  }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
