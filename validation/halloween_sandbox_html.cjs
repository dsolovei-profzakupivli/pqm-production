const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const html=fs.readFileSync(0,'utf8'),expected=process.argv[2]==='1';
const hasTitle=/class="(?:sandbox|prod)-brand-copy"[^>]*><strong>/.test(html);
assert.equal(hasTitle,expected);assert(html.includes('id="accountSettingsForm"'));
assert(html.indexOf('src="halloween_season.js"')<html.indexOf('src="halloween.js"'));
for(const date of ['2026-10-18T06:00:00Z','2026-11-01T00:00:00Z']){
 let cat=false,inserted=false;
 const listeners={},input={addEventListener:(event,fn)=>listeners[event]=fn},hint={};
 const title={classList:{add(){}},insertAdjacentHTML:()=>cat=true};
 const label={querySelector:s=>s==='input'?input:hint};
 const form={querySelector:()=>({before:()=>inserted=true})};
 const document={documentElement:{dataset:{}},addEventListener(){},createElement:()=>label,
  querySelector:s=>s.includes('strong')?(hasTitle?title:null):s==='#accountSettingsForm'?form:null};
 class Clock extends Date{constructor(...args){super(...(args.length?args:[date]))}static now(){return Date.parse(date)}}
 const context={Date:Clock,document,window:{addEventListener(){}},localStorage:{getItem:()=>null,setItem(){}},setTimeout:()=>1,clearTimeout(){}};
 vm.runInNewContext(fs.readFileSync('halloween_season.js','utf8')+'\n'+fs.readFileSync('halloween.js','utf8'),context);
 assert(inserted,'Preference must initialize even without title');assert.equal(cat,expected);
 assert.equal(document.documentElement.dataset.halloween,date.includes('-10-')?'on':'off');
 assert.equal(input.disabled,!date.includes('-10-'));
 if(!input.disabled){input.checked=false;listeners.change();assert.equal(document.documentElement.dataset.halloween,'off')}
}
