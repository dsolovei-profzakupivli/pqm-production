const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const boot=fs.readFileSync('ui_improvements_boot.js','utf8'),app=fs.readFileSync('app.js','utf8');
const start=boot.lastIndexOf("document.getElementById('mainNav').addEventListener('click',event=>{");
const callback=boot.slice(start).replace(/\r\n/g,'\n').split('\n  },true);')[0]+'\n},true);';
let checks=0;
for(const id of ['requestsNav','operationalTasksNav'])for(const count of [undefined,null,0,3,27])for(const permitted of [false,true]){
 const controls=new Map(),node=key=>{if(!controls.has(key))controls.set(key,{value:'old',classList:{add(){}},setAttribute(){}});return controls.get(key)};
 const target={id},context={document:{getElementById:node},$:selector=>node(selector.slice(1)),counts:new Map([[id,count]]),currentMe:{permissions:{'tasks.read':permitted,'appeals.read':permitted}},PqmUi:{responseExpired:false},requestsTimer:1,operationalTaskTimer:2,requestsPage:9,selectedRequestAuthority:'other',clearTimeout(){},expired:{classList:{add(){}},setAttribute(){}},clearState(){},refresh(){}};
 node('mainNav').addEventListener=(_name,fn)=>context.callback=fn;
 vm.createContext(context);vm.runInContext(app.split(/\r?\n/).find(s=>s.startsWith('function resetOperationalKpiFilters(')),context);vm.runInContext(callback,context);
 for(let repeat=0;repeat<2;repeat++){
  for(const n of controls.values())n.value='old';context.PqmUi.responseExpired=false;context.requestsPage=9;context.selectedRequestAuthority='other';
  context.callback({target:{closest:()=>target}});
  if(count>0&&permitted){
   if(id==='requestsNav'){for(const key of ['requestsSearch','requestsStatus','requestsReason','requestsDateFrom','requestsDateTo'])assert.equal(node(key).value,'');assert.equal(context.requestsPage,1);assert.equal(context.selectedRequestAuthority,'40996564');assert.equal(context.PqmUi.responseExpired,true)}
   else{for(const key of ['operationalTaskSearch','operationalTaskType','operationalTaskOfficer','operationalTaskDateFrom'])assert.equal(node(key).value,'');assert.equal(node('operationalTaskStatus').value,'needs_action')}
  }else{assert.equal(context.requestsPage,9);assert.equal(context.selectedRequestAuthority,'other');assert.equal(context.PqmUi.responseExpired,false);for(const n of controls.values())assert.equal(n.value,'old')}
  checks++;
 }
}
assert.match(fs.readFileSync('ui_tz2.css','utf8'),/\.action-count-badge\{[^}]*background:#b42318;color:#fff/);
assert.match(boot,/createElement\('div'\);wrapper.className='pqm-clear-wrap'/);
console.log('UI_TZ3_UNIT=PASS; navigation cases='+checks+'; positive/zero/unknown/permissions/repeated/filter reset/red badge');
