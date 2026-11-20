const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const html=fs.readFileSync(0,'utf8'),expected=process.argv[2]==='1';
const hasTitle=/class="(?:sandbox|prod)-brand-copy"[^>]*><strong(?:\s[^>]*)?>/.test(html);
assert.equal(hasTitle,expected);assert(html.includes('id="accountSettingsForm"'));
const sandboxShell=html.includes('data-pqm-environment="sandbox"');
if(sandboxShell){
 assert(html.includes('src="pqm_cat.js"'));assert(html.includes('href="pqm_cat.css"'));
 assert(html.includes('src="assets/pqm-cat-no-hat.png"'));
 assert(!html.includes('src="halloween.js"'));assert(!html.includes('src="halloween_motion.js"'));
 assert(!html.includes('href="halloween.css"'));assert(!html.includes('href="halloween_motion.css"'));
 console.log('SANDBOX_DEFAULT_CAT_HTML=PASS');
}else assert(html.indexOf('src="halloween_season.js"')<html.indexOf('src="halloween.js"'));
for(const date of (sandboxShell?['2026-10-18T06:00:00Z']:['2026-10-18T06:00:00Z','2026-11-01T00:00:00Z'])){
 let cat=false,inserted=false,catHtml='';
 const listeners={},input={addEventListener:(event,fn)=>listeners[event]=fn},hint={};
 const title={style:{},querySelector(){return null},classList:{add(){}},insertAdjacentHTML:(_,value)=>{cat=true;catHtml=value}};
 const label={querySelector:s=>s==='input'?input:hint};
 const form={querySelector:()=>({before:()=>inserted=true})};
 const document={documentElement:{dataset:{pqmEnvironment:html.includes('data-pqm-environment="sandbox"')?'sandbox':'production'}},addEventListener(){},createElement:()=>label,
  querySelector:s=>s.includes('strong')?(hasTitle?title:null):s==='#accountSettingsForm'?form:null};
 class Clock extends Date{constructor(...args){super(...(args.length?args:[date]))}static now(){return Date.parse(date)}}
 const context={Date:Clock,document,window:{addEventListener(){}},localStorage:{getItem:()=>null,setItem(){}},setTimeout:()=>1,clearTimeout(){}};
 vm.runInNewContext(fs.readFileSync('halloween_season.js','utf8')+'\n'+fs.readFileSync('halloween.js','utf8'),context);
 assert(inserted,'Preference must initialize even without title');assert.equal(cat,expected);
 if(cat){
  const sandbox=document.documentElement.dataset.pqmEnvironment==='sandbox';
  assert(catHtml.includes(`src="assets/${sandbox&&!date.includes('-10-')?'pqm-cat-no-hat.png':'halloween-witch-cat.webp'}"`),'first markup uses the correct seasonal asset');
  assert(catHtml.includes('width="180" height="97"'),'safe intrinsic geometry before CSS');
  assert.equal(title.style.position,'relative');
  if(sandbox)assert.equal(document.documentElement.dataset.pqmCat,'on','preference exists before the permanent controller');
 }
 assert.equal(document.documentElement.dataset.halloween,date.includes('-10-')?'on':'off');
 assert.equal(input.disabled,!date.includes('-10-'));
 if(!input.disabled){input.checked=false;listeners.change();assert.equal(document.documentElement.dataset.halloween,'off')}
}
