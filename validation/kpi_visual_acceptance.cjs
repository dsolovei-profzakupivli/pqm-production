/* Local visual prototype screenshots using the candidate's real PQM HTML/CSS and isolated fixture values. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require(require.resolve('playwright',{paths:['C:/Users/User/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules']}));
const ROOT=path.resolve(__dirname,'..'),OUT=path.join(ROOT,'evidence','kpi-visual-acceptance-20261018');
const read=name=>fs.readFileSync(path.join(ROOT,name),'utf8');
const html=read('index.html').replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,'').replace(/<link\b[^>]*rel=["']stylesheet["'][^>]*>/gi,'');
const cssFiles=['styles.css','filters.css','modules.css','schema_ui.css','ui_improvements.css','ui_final.css','theme.css','ui_tz2.css','halloween.css'];
const roster=[{full_name:'Дмитро САВВА'},{full_name:'Тетяна ФЕДЧЕНКО'},{full_name:'Олена ЄРЬОМІНА'}];
const officers=['Д. Савва','Т. Федченко','О. Єрьоміна'];
async function pageFor(browser,{theme='light',view='applications',prototype=true}={}){
  const page=await browser.newPage({viewport:{width:1920,height:1080},deviceScaleFactor:1});
  page.on('pageerror',e=>{throw e});await page.setContent(html);
  for(const name of cssFiles){let css=read(name);if(!prototype&&name==='ui_improvements.css')css=css.split('/* Local visual prototype: all officer-distribution cards, including unassigned, share one light palette. */')[0];if(!prototype&&name==='theme.css')css=css.split('/* Local visual prototype: transparent empty Applications KPI wrapper; keep its children intact. */')[0];await page.addStyleTag({content:css})}
  await page.addScriptTag({content:read('ui_improvements.js')});
  await page.evaluate(({theme,view,roster,officers})=>{
    const root=document.documentElement;root.dataset.pqmEnvironment='sandbox';root.dataset.theme=theme;root.dataset.halloween='off';
    document.querySelector('#loginGate').hidden=true;document.querySelector('#applicationShell').hidden=false;
    document.querySelectorAll('main').forEach(el=>el.hidden=el.id!==({applications:'applicationsView',workQueue:'workQueueView',edr:'edrMonitoringView',requests:'requestsView'}[view]));
    document.querySelectorAll('#kpiCards [data-kpi]').forEach((el,i)=>el.textContent=String([322,156,88,48,27,201,121,43,19,260][i]));
    document.querySelector('#officerCards').innerHTML=officers.map((name,i)=>`<button type="button" class="officer-card${i===0&&location.hash==='#active'?' active':''}" data-officer="${name}"><span>${name}</span><strong>${[162,93,67][i]}</strong></button>`).join('')+'<button type="button" class="officer-card unassigned" data-officer="Не визначено"><span>Не визначено</span><strong>322</strong></button>';
    document.querySelector('#queueProtocolOfficerCards').innerHTML=officers.map((name,i)=>`<button type="button" class="qualification-summary-officer" data-protocol-officer="${name}"><span>${name}</span><strong>${[16,12,8][i]}</strong><small>у протоколі</small></button>`).join('');
    document.querySelector('#queueQualificationCards').innerHTML=officers.map((name,i)=>`<button type="button" class="qualification-summary-officer" data-qualification-officer="${name}"><span>${name}</span><strong>${[16,12,8][i]}</strong><small>очікує рішення</small></button>`).join('');
    for(const id of ['queueProtocolCategoryCards','queueCategoryCards'])document.querySelector(`#${id}`).innerHTML=['Ліки','Інше','Тас/ЄЕ'].map((name,i)=>`<button type="button" class="qualification-summary-officer qualification-summary-category"><span>${name}</span><strong>${[10,8,6][i]}</strong><small>категорія</small></button>`).join('');
    document.querySelector('#queuePublicationControl').innerHTML='<button data-publication-state="active"><span>Допущено</span><strong>48</strong></button><button data-publication-state="unsuccessful"><span>Відхилено</span><strong>7</strong></button><button class="warning" data-publication-state="pending"><span>Все ще очікує рішення</span><strong>17</strong></button>';
    const freshness=['not_current','lt30','gt30','gt60','gt90','not_checked'];
    freshness.forEach((key,i)=>{const button=document.querySelector(`#edrMonitoringKpis [data-freshness="${key}"]`);if(button){button.querySelector('strong').textContent=String([14,108,32,19,8,27][i]);}});
    document.querySelector('#requestAuthorityCards').innerHTML=['Професійні закупівлі','УСС','МЗУ'].map((name,i)=>`<button type="button" class="request-authority-card${i===1&&location.hash==='#active'?' active':''}" data-authority-code="fixture-${i}"><span>${name}</span><strong>${[28,14,9][i]}</strong></button>`).join('');
  },{theme,view,roster,officers});
  await page.evaluate(items=>window.PqmUi?.setOfficerRoster(items),roster);
  return page;
}
(async()=>{
  fs.mkdirSync(OUT,{recursive:true});const browser=await chromium.launch({headless:true,executablePath:'C:/Users/User/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe'});
  try{
    const shots=[];
    const save=async(options,selector,name)=>{const p=await pageFor(browser,options);await p.locator(selector).screenshot({path:path.join(OUT,name)});shots.push(name);return p};
    const light=await save({theme:'light',view:'applications'},'#applicationsView .page-heading','registry-light-no-filter-after.png');
    const active=await pageFor(browser,{theme:'light',view:'applications'});await active.locator('#officerCards>.officer-card[data-officer="Не визначено"]').evaluate(e=>e.classList.add('active'));await active.locator('#applicationsView .page-heading').screenshot({path:path.join(OUT,'registry-light-unassigned-active.png')});shots.push('registry-light-unassigned-active.png');
    const work=await save({theme:'dark',view:'workQueue'},'#workQueueView .work-queue-operational-grid','work-queue-dark-colored-kpis-full-names.png');
    const workNames=await work.locator('#queueProtocolOfficerCards span').allTextContents();assert.deepEqual(workNames,roster.map(x=>x.full_name));
    const edr=await save({theme:'dark',view:'edr'},'#edrMonitoringKpis','edr-dark-six-kpi-colors.png');
    const appeals=await save({theme:'dark',view:'requests'},'#requestsView .module-heading','appeals-dark-kpi-contrast.png');
    const regDark=await save({theme:'dark',view:'applications'},'#applicationsView .page-heading','registry-dark-transparent-kpi-wrapper.png');
    const darkActive=await pageFor(browser,{theme:'dark',view:'applications'});await darkActive.locator('#officerCards>.officer-card[data-officer="Не визначено"]').evaluate(e=>e.classList.add('active'));await darkActive.locator('#applicationsView .page-heading').screenshot({path:path.join(OUT,'registry-dark-unassigned-active.png')});shots.push('registry-dark-unassigned-active.png');
    const baselineDark=await pageFor(browser,{theme:'dark',view:'applications',prototype:false});await baselineDark.locator('#applicationsView .page-heading').screenshot({path:path.join(OUT,'registry-dark-before.png')});shots.push('registry-dark-before.png');
    const baselineLight=await pageFor(browser,{theme:'light',view:'applications',prototype:false});await baselineLight.locator('#applicationsView .page-heading').screenshot({path:path.join(OUT,'registry-light-before.png')});shots.push('registry-light-before.png');
    const values=await edr.locator('#edrMonitoringKpis button').evaluateAll(es=>es.map(e=>({status:e.dataset.freshness,bg:getComputedStyle(e).backgroundColor,fg:getComputedStyle(e).color})));assert.equal(values.length,6);
    const reqColors=await appeals.locator('#requestAuthorityCards button').evaluateAll(es=>es.map(e=>({label:getComputedStyle(e.querySelector('span')).color,value:getComputedStyle(e.querySelector('strong')).color})));assert.equal(reqColors.length,3);
    const wrapper=await regDark.locator('#applicationsView .heading-metrics').evaluate(e=>getComputedStyle(e).backgroundColor);assert.equal(wrapper,'rgba(0, 0, 0, 0)');
    const officerStates=async page=>page.locator('#applicationsView #officerCards>.officer-card').evaluateAll(es=>es.map(e=>({key:e.dataset.officer,bg:getComputedStyle(e).backgroundColor,color:getComputedStyle(e).color,span:getComputedStyle(e.querySelector('span')).color,strong:getComputedStyle(e.querySelector('strong')).color,rect:[e.getBoundingClientRect().width,e.getBoundingClientRect().height]})));
    const officersLight=await officerStates(light),officersDark=await officerStates(regDark);assert.deepEqual(officersLight.map(x=>x.key),[...officers,'Не визначено']);assert.deepEqual(officersDark.map(x=>x.key),[...officers,'Не визначено']);
    assert(officersLight.every(x=>x.bg==='rgb(237, 246, 232)'&&x.color==='rgb(23, 43, 65)'&&x.strong==='rgb(23, 43, 65)'),'all four light officer cards use the agreed pale-green palette');
    assert(officersDark.every(x=>x.bg==='rgb(23, 62, 56)'&&x.color==='rgb(184, 237, 202)'&&x.strong==='rgb(228, 247, 233)'),'all four dark officer cards use the same muted-green palette');
    const unassignedLight=await light.locator('#officerCards>.officer-card.unassigned').evaluate(e=>({background:getComputedStyle(e).backgroundColor,color:getComputedStyle(e).color}));assert.deepEqual(unassignedLight,{background:'rgb(237, 246, 232)',color:'rgb(23, 43, 65)'});
    const unassignedDark=await regDark.locator('#officerCards>.officer-card.unassigned').evaluate(e=>({background:getComputedStyle(e).backgroundColor,color:getComputedStyle(e).color}));assert.deepEqual(unassignedDark,{background:'rgb(23, 62, 56)',color:'rgb(184, 237, 202)'});
    const activeDark=await darkActive.locator('#officerCards>.officer-card.unassigned').evaluate(e=>({background:getComputedStyle(e).backgroundColor,border:getComputedStyle(e).borderTopColor,shadow:getComputedStyle(e).boxShadow}));assert.equal(activeDark.background,'rgb(23, 62, 56)');assert.equal(activeDark.border,'rgb(139, 224, 182)');assert(activeDark.shadow.includes('139, 224, 182'));
    const activeLight=await active.locator('#officerCards>.officer-card.unassigned').evaluate(e=>({background:getComputedStyle(e).backgroundColor,border:getComputedStyle(e).borderTopColor,shadow:getComputedStyle(e).boxShadow}));assert.equal(activeLight.background,'rgb(237, 246, 232)');assert.equal(activeLight.border,'rgb(39, 118, 70)');assert(activeLight.shadow.includes('39, 118, 70'));
    const hoverLight=await light.locator('#officerCards>.officer-card.unassigned').evaluate(e=>getComputedStyle(e).backgroundColor);await light.locator('#officerCards>.officer-card.unassigned').hover();const hoverLightAfter=await light.locator('#officerCards>.officer-card.unassigned').evaluate(e=>({background:getComputedStyle(e).backgroundColor,border:getComputedStyle(e).borderTopColor}));assert.equal(hoverLightAfter.background,'rgb(223, 240, 215)');assert.equal(hoverLightAfter.border,'rgb(141, 182, 122)');
    await regDark.locator('#officerCards>.officer-card.unassigned').hover();const hoverDark=await regDark.locator('#officerCards>.officer-card.unassigned').evaluate(e=>({background:getComputedStyle(e).backgroundColor,border:getComputedStyle(e).borderTopColor}));assert.equal(hoverDark.background,'rgb(32, 80, 63)');assert.equal(hoverDark.border,'rgb(90, 159, 121)');
    const kpiSignature=async page=>page.locator('#applicationsView #kpiCards>.kpi-card, #applicationsView .heading-actions button').evaluateAll(es=>es.map(e=>{const s=getComputedStyle(e),r=e.getBoundingClientRect();return{bg:s.backgroundColor,fg:s.color,border:s.borderColor,width:r.width,height:r.height}}));
    assert.deepEqual(await kpiSignature(light),await kpiSignature(baselineLight),'light non-officer KPI cards and right-side buttons remain unchanged');
    assert.deepEqual(await kpiSignature(regDark),await kpiSignature(baselineDark),'dark non-officer KPI cards and right-side buttons remain unchanged');
    console.log(JSON.stringify({result:'PASS',baseSha:'fbcce44cecf0923e4818ddeab269e478fe73939d',workQueueFullNames:workNames,registryOfficerCards:{light:officersLight,dark:officersDark,unassignedLight,unassignedDark,activeLight,activeDark,hoverLight:hoverLightAfter,hoverDark},edr:values,appeals:reqColors,registryDarkWrapper:wrapper,unchangedKpisAndActions:true,screenshots:OUT,files:shots},null,2));
    await Promise.all([light.close(),active.close(),work.close(),edr.close(),appeals.close(),regDark.close(),darkActive.close(),baselineDark.close(),baselineLight.close()]);
  }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
