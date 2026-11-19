const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const {chromium}=require('playwright');

const ROOT=path.resolve(__dirname,'..');
const OUT=process.env.PQM_APPLICATION_FILTER_EVIDENCE_DIR||path.join(os.tmpdir(),'pqm-application-filter-evidence');
const read=name=>fs.readFileSync(path.join(ROOT,name),'utf8');
const html=read('index.html').replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,'').replace(/<link\b[^>]*rel=["']stylesheet["'][^>]*>/gi,'');
const styles=['styles.css','chat_annotations.css','filters.css','modules.css','schema_ui.css','ui_improvements.css','ui_final.css','theme.css','uo_work_page.css','nazk_preview.css','ui_tz2.css','halloween.css'];

async function makePage(browser,theme,width,height){
  const page=await browser.newPage({viewport:{width,height},deviceScaleFactor:1});
  await page.setContent(html);
  for(const name of styles)if(fs.existsSync(path.join(ROOT,name)))await page.addStyleTag({content:read(name)});
  await page.evaluate(theme=>{
    document.documentElement.dataset.theme=theme;
    document.documentElement.dataset.pqmEnvironment='sandbox';
    document.documentElement.dataset.halloween='off';
    document.querySelector('#loginGate').hidden=true;
    document.querySelector('#applicationShell').hidden=false;
    document.querySelectorAll('main').forEach(main=>{main.hidden=main.id!=='applicationsView'});
    document.querySelector('#supplierCodeFilter .multi-options').innerHTML=Array.from({length:36},(_,i)=>`<label><input type="checkbox" value="supplier-${i}"><span>12345678 · Постачальник ${i} з довгою назвою для перевірки перенесення тексту</span></label>`).join('');
    document.querySelector('#frameworkFilter .multi-options').innerHTML=Array.from({length:22},(_,i)=>`<label><input type="checkbox" value="framework-${i}"><span>UA-F-${i} · Відбір із довгою назвою предмета закупівлі ${i}</span></label>`).join('');
    document.querySelector('#dkFilter .multi-options').innerHTML=Array.from({length:28},(_,i)=>`<label><input type="checkbox" value="4500000${i}-7"><span>4500000${i}-7 · Код категорії з довгим описом, який має переноситися в межах меню ${i}</span></label>`).join('');
    document.querySelector('#applicationCategoryFilter').innerHTML+='<option value="Їжа">Їжа</option>';
    document.querySelector('#profileSelect').innerHTML='<option value="personal">Мій профіль</option>';
    document.querySelector('#dateFromFilter').value='2026-11-02';
    document.querySelector('#dateToFilter').value='2026-11-16';
  },theme);
  await page.addScriptTag({path:path.join(ROOT,'filter_panels_ui.js')});
  await page.addScriptTag({path:path.join(ROOT,'registry_popovers.js')});
  return page;
}

(async()=>{
  fs.mkdirSync(OUT,{recursive:true});
  const browser=await chromium.launch({headless:true,ignoreDefaultArgs:['--hide-scrollbars'],executablePath:process.env.PQM_CHROMIUM_EXECUTABLE||undefined});
  try{
    const evidence=[];
    for(const theme of ['light','dark'])for(const [width,height] of [[1920,900],[1280,800],[900,700],[390,420],[320,600]]){
      const page=await makePage(browser,theme,width,height);
      const summary=page.locator('#applicationFiltersSummary');
      await summary.click();
      const layout=await page.evaluate(()=>{
        const panel=document.querySelector('#applicationFilterPanel'),fields=panel.querySelector('.application-filter-fields'),header=panel.querySelector('.application-filter-header'),rect=node=>{const r=node.getBoundingClientRect();return{x:r.x,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height}};
        return{viewport:{width:innerWidth,height:innerHeight},panel:rect(panel),header:rect(header),fields:{scrollHeight:fields.scrollHeight,clientHeight:fields.clientHeight,overflow:getComputedStyle(fields).overflowY,scrollbarWidth:getComputedStyle(fields).scrollbarWidth,scrollbarColor:getComputedStyle(fields).scrollbarColor,gap:getComputedStyle(fields).rowGap},rowHeights:[...panel.querySelectorAll('.application-filter-section')].map(section=>{const toggle=section.querySelector('.filter-accordion-toggle'),icon=getComputedStyle(toggle,'::after');return{section:section.getBoundingClientRect().height,toggle:toggle.getBoundingClientRect().height,icon:{content:icon.content,right:icon.right}}}),rootOverflow:getComputedStyle(document.documentElement).overflow,pageWidth:document.documentElement.scrollWidth,sectionCount:panel.querySelectorAll('.application-filter-section').length,allInside:[...panel.querySelectorAll('#applicationOfficerFilter,#applicationEntityTypeFilter,#supplierCodeFilter,#registryStatusFilter,#protocolNumberFilter,#protocolDecisionFilter,#complianceStatusFilter,#frameworkFilter,#dkFilter,#dateFromFilter,#dateToFilter')].every(node=>panel.contains(node)),allCollapsed:[...panel.querySelectorAll('.application-filter-section')].every(section=>section.querySelector('[aria-expanded="false"]')&&section.querySelector('.filter-accordion-content').hidden),oneColumn:[...panel.querySelectorAll('.application-filter-section')].every(section=>section.getBoundingClientRect().width>0),actions:['applicationFilterClear','applicationFilterApply','applicationFilterClose'].map(id=>!!document.getElementById(id)),main:['searchInput','applicationCategoryFilter','statusFilter','marketplaceDecisionFilter','profileSelect','saveProfileBtn'].every(id=>!panel.contains(document.getElementById(id)))};
      });
      assert.equal(layout.panel.width<=Math.min(460,width)+1,true,`drawer fits viewport width ${width}: ${JSON.stringify(layout.panel)}`);
      assert.ok(layout.panel.x>=0&&layout.panel.right<=width+1,`drawer stays within the viewport at ${width}px`);
      assert.equal(layout.panel.height,height,`drawer spans viewport height at ${height}px`);
      assert.equal(layout.sectionCount,10,'the ten agreed filter sections remain available, with both dates grouped together');
      assert.equal(layout.fields.gap,'7px','registry accordion spacing defines the compact section gap');
      assert.ok(layout.rowHeights.every(row=>Math.abs(row.toggle-42)<1&&Math.abs(row.section-44)<1&&row.icon.content==='"›"'&&row.icon.right==='10px'),`registry filter rows use the compact height and shared right-pointing icon: ${JSON.stringify(layout.rowHeights)}`);
      assert.equal(layout.allInside,true,'every advanced registry control is inside the drawer');
      assert.equal(layout.allCollapsed,true,'all filter sections start collapsed, including filters with selected values');
      assert.deepEqual(await page.locator('#applicationEntityTypeFilter').evaluate(node=>({labels:node.labels.length,ariaLabel:node.getAttribute('aria-label')})),{labels:1,ariaLabel:'Тип постачальника'},'the visually suppressed duplicate caption remains associated with the accessible control name');
      assert.equal(await page.locator('label[for="applicationEntityTypeFilter"]').evaluate(node=>node.classList.contains('filter-field-caption')),true,'the repeated supplier-type caption is visually suppressed, not removed');
      assert.equal(layout.main,true,'quick filters, search, and profile controls remain in the toolbar');
      assert.deepEqual(layout.actions,[true,true,true],'clear/apply/close remain at the top');
      assert.equal(layout.rootOverflow,'hidden','the page behind the drawer cannot scroll');
      assert.ok(layout.fields.overflow==='auto'&&layout.fields.scrollbarWidth==='thin'&&layout.fields.scrollbarColor!=='auto',`filter content has an internal theme-colored scrollbar: ${JSON.stringify(layout.fields)}`);
      if(height<500){
        assert.ok(layout.fields.scrollHeight>layout.fields.clientHeight,'short screens expose all filter sections through internal scrolling');
        const before=layout.header;
        await page.locator('.application-filter-fields').evaluate(node=>node.scrollTop=node.scrollHeight);
        const after=await page.locator('.application-filter-header').evaluate(node=>{const r=node.getBoundingClientRect();return{top:r.top,bottom:r.bottom}});
        assert.ok(Math.abs(after.top-before.top)<1&&Math.abs(after.bottom-before.bottom)<1,'title and top actions remain fixed while the filter list scrolls');
        await page.locator('[data-application-filter-section="application_date"] .filter-accordion-toggle').click();
        const dateSection=page.locator('[data-application-filter-section="application_date"]');
        assert.equal(await dateSection.locator('.filter-accordion-toggle').getAttribute('aria-expanded'),'true','the date section expands after scrolling inside the panel');
        assert.ok(await page.locator('#dateFromFilter').isVisible()&&await page.locator('#dateToFilter').isVisible(),'both vertically stacked date controls are reachable');
        await page.locator('#dateToFilter').scrollIntoViewIfNeeded();
        const dateLayout=await page.evaluate(()=>{const fields=document.querySelector('#applicationFilterPanel .application-filter-fields'),from=document.querySelector('#dateFromFilter'),to=document.querySelector('#dateToFilter'),rect=node=>{const r=node.getBoundingClientRect();return{top:r.top,bottom:r.bottom,left:r.left,right:r.right}};const a=rect(from),b=rect(to),f=fields.getBoundingClientRect();return{from:a,to:b,fields:{top:f.top,bottom:f.bottom},sameColumn:Math.abs(a.left-b.left)<1&&Math.abs(a.right-b.right)<1,vertical:b.top>=a.bottom-1,inside:a.top>=f.top&&b.bottom<=f.bottom,fromValue:from.value,toValue:to.value,scrollY};});
        assert.ok(dateLayout.sameColumn&&dateLayout.vertical,`from/to date controls stay vertically stacked: ${JSON.stringify(dateLayout)}`);
        assert.ok(dateLayout.inside,`both date controls can be scrolled fully into the panel viewport: ${JSON.stringify(dateLayout)}`);
        assert.equal(dateLayout.fromValue,'2026-11-02','the applied from-date value remains intact');
        assert.equal(dateLayout.toValue,'2026-11-16','the applied to-date value remains intact');
        if(width===390){const shot=path.join(OUT,`registry-date-expanded-${theme}-short.png`);await page.screenshot({path:shot,fullPage:false});evidence.push(shot)}
        const pageScrollBeforeClose=dateLayout.scrollY;
        await page.locator('#applicationFilters').evaluate(node=>{node.open=false});
        await page.locator('#applicationFiltersSummary').click();
        await page.waitForFunction(()=>document.querySelector('[data-application-filter-section="application_date"] .filter-accordion-toggle')?.getAttribute('aria-expanded')==='false');
        assert.equal(await dateSection.locator('.filter-accordion-toggle').getAttribute('aria-expanded'),'false','the date section is collapsed again when the drawer is reopened');
        assert.equal(await page.locator('#dateFromFilter').inputValue(),'2026-11-02','closing and reopening keeps the from-date value');
        assert.equal(await page.locator('#dateToFilter').inputValue(),'2026-11-16','closing and reopening keeps the to-date value');
        assert.equal(await page.evaluate(()=>scrollY),pageScrollBeforeClose,'opening/closing the panel does not scroll the page');
        if(width===390){const shot=path.join(OUT,`registry-filters-${theme}-short.png`);await page.screenshot({path:shot,fullPage:false});evidence.push(shot)}
      }
      if(width===1920){
        const shot=path.join(OUT,`registry-filters-${theme}-wide.png`);await page.screenshot({path:shot,fullPage:false});evidence.push(shot);
        await page.evaluate(()=>{const section=document.querySelector('[data-application-filter-section="entity_type"]'),select=document.querySelector('#applicationEntityTypeFilter'),count=section.querySelector('[data-application-filter-count]');select.value='individual_entrepreneur';section.classList.add('filter-active');count.textContent='1';count.hidden=false});
        const appliedShot=path.join(OUT,`registry-filters-${theme}-applied.png`);await page.screenshot({path:appliedShot,fullPage:false});evidence.push(appliedShot);
        await page.locator('[data-application-filter-section="entity_type"] .filter-accordion-toggle').click();
        assert.equal(await page.locator('[data-application-filter-section="entity_type"] .filter-accordion-toggle').getAttribute('aria-expanded'),'true','an applied filter can be expanded without losing its value');
        assert.deepEqual(await page.locator('[data-application-filter-section="entity_type"] .filter-accordion-toggle').evaluate(node=>{const style=getComputedStyle(node,'::after');return{content:style.content,right:style.right}}),{content:'"⌃"',right:'10px'},'expanded accordion rows consistently point up at the shared right inset');
        assert.equal(await page.locator('#applicationEntityTypeFilter').inputValue(),'individual_entrepreneur');
        const expandedShot=path.join(OUT,`registry-filters-${theme}-expanded.png`);await page.screenshot({path:expandedShot,fullPage:false});evidence.push(expandedShot);
        await page.locator('[data-application-filter-section="registry_status"] .filter-accordion-toggle').click();
        const collapsedDropdownIcon=await page.locator('#registryStatusFilter>summary').evaluate(node=>{const style=getComputedStyle(node,'::after');return{content:style.content,right:style.right}});
        await page.locator('#registryStatusFilter>summary').click();
        const expandedDropdownIcon=await page.locator('#registryStatusFilter>summary').evaluate(node=>{const style=getComputedStyle(node,'::after');return{content:style.content,right:style.right}});
        assert.deepEqual(collapsedDropdownIcon,{content:'"›"',right:'10px'},`collapsed multiselect arrow points right and sits at a fixed inset in ${theme}`);
        assert.deepEqual(expandedDropdownIcon,{content:'"⌃"',right:'10px'},`expanded multiselect arrow points up at the same inset in ${theme}`);
        const firstLabel=page.locator('#registryStatusFilter .multi-panel label').first();
        const checkbox=await firstLabel.locator('input').evaluate(node=>{const r=node.getBoundingClientRect();return{x:r.x,right:r.right,y:r.y,width:r.width,height:r.height,display:getComputedStyle(node.parentElement).display}});
        const statusText=await firstLabel.evaluate(node=>{const r=node.querySelector('span')?.getBoundingClientRect()||node.getBoundingClientRect();return{x:r.x,y:r.y,width:r.width,height:r.height}});
        assert.ok(checkbox.display==='grid'&&checkbox.width===15&&checkbox.height===15&&checkbox.right<statusText.x,`checkbox stays fixed immediately left of its label in ${theme}: ${JSON.stringify({checkbox,statusText})}`);
      }
      await page.close();
    }
    console.log(JSON.stringify({result:'PASS',responsiveCases:['registry drawer 1920/1280/900/390/320px light/dark','11 controls, fixed toolbar actions, internal scrolling and page scroll lock','checkbox size and alignment'],screenshots:evidence},null,2));
  }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
