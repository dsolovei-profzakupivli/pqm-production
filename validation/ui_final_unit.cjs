const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const app=fs.readFileSync('app.js','utf8'),nodes=new Map();
const c={$:id=>{if(!nodes.has(id))nodes.set(id,{value:''});return nodes.get(id)},clearTimeout:()=>{},operationalTaskTimer:0,operationalBasisDirection:'desc',snapshots:[]};
c.loadOperationalTasks=()=>c.snapshots.push(Object.fromEntries([...nodes].map(([k,v])=>[k,v.value])));
vm.createContext(c);
vm.runInContext(app.split('\n').filter(line=>line.startsWith('function resetOperationalKpiFilters()')||line.startsWith("$('#operationalTaskKpis').onclick=")||line.startsWith("$('#operationalTaskTypes').onclick=")).join('\n'),c);
for(const group of ['active','needs_action','awaiting_response','ready_for_document','awaiting_sync','completed']){
 for(const id of ['operationalTaskSearch','operationalTaskType','operationalTaskOfficer','operationalTaskDateFrom'])c.$('#'+id).value='old';
 c.$('#operationalTaskStatus').value='completed';
 c.$('#operationalTaskKpis').onclick({target:{closest:()=>({dataset:{taskKpi:group}})}});
 assert.equal(c.$('#operationalTaskStatus').value,group);
 for(const id of ['operationalTaskSearch','operationalTaskType','operationalTaskOfficer','operationalTaskDateFrom'])assert.equal(c.$('#'+id).value,'');
}
c.$('#operationalTaskSearch').value='крини';c.$('#operationalTaskStatus').value='completed';
c.$('#operationalTaskKpis').onclick({target:{closest:()=>({dataset:{taskKpi:'needs_action'}})}});
assert.equal(c.$('#operationalTaskSearch').value,'');assert.equal(c.$('#operationalTaskStatus').value,'needs_action');
c.$('#operationalTaskTypes').onclick({target:{closest:()=>({dataset:{taskType:'amcu_exclusion'}})}});
assert.equal(c.$('#operationalTaskStatus').value,'needs_action');assert.equal(c.$('#operationalTaskType').value,'amcu_exclusion');
c.$('#operationalTaskTypes').onclick({target:{closest:()=>({dataset:{taskType:'amcu_exclusion'}})}});
assert.equal(c.$('#operationalTaskStatus').value,'needs_action');assert.equal(c.$('#operationalTaskType').value,'');
const ui=fs.readFileSync('ui_final.js','utf8');assert(!/method\s*:\s*['"](?:POST|PATCH|DELETE)/.test(ui));
assert(!ui.includes('schedulerScheduleDrafts'));assert(ui.includes('installViewportDrag(dialog,dialog,header)'));
assert(!ui.includes('protocolDecisionFilter')); // Protocol decision cards retain their independent handler.
console.log('UI_FINAL_UNIT=PASS; six KPI groups + additive type toggle + no writes');
