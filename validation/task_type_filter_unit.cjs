const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const app=fs.readFileSync('app.js','utf8'),nodes=new Map(),snapshots=[];
const groups={active:['new','in_progress','ready_for_document','awaiting_response','waiting_external','awaiting_sync'],needs_action:['new','in_progress','ready_for_document'],awaiting_response:['awaiting_response','waiting_external'],ready_for_document:['ready_for_document'],awaiting_sync:['awaiting_sync'],completed:['completed'],cancelled:['cancelled'],historical:['completed','cancelled']};
const types=['nazk_check','amcu_exclusion','warning_block','termination_exclusion'];
const c={$:selector=>{if(!nodes.has(selector))nodes.set(selector,{value:''});return nodes.get(selector)},
 operationalBasisDirection:'desc',resetOperationalKpiFilters:()=>{throw Error('Type chip must not reset filters')}};
c.loadOperationalTasks=()=>{const params=c.operationalTaskParams();snapshots.push(params);c.activeKpi=params.status_group;};
vm.createContext(c);
vm.runInContext(app.split(/\r?\n/).filter(line=>line.startsWith('function operationalTaskParams(')||line.startsWith("$('#operationalTaskTypes').onclick=")).join('\n'),c);
const click=type=>c.$('#operationalTaskTypes').onclick({target:{closest:()=>({dataset:{taskType:type}})}});
let combinations=0;
for(const status of Object.keys(groups))for(const type of types){
 const fields={operationalTaskSearch:'Контроль 0001',operationalTaskOfficer:'42',operationalTaskDateFrom:'2026-10-17',operationalTaskStatus:status,operationalTaskType:''};
 for(const [id,value]of Object.entries(fields))c.$('#'+id).value=value;
 const before=JSON.stringify(c.operationalTaskParams());click(type);
 assert.equal(c.$('#operationalTaskType').value,type);assert.equal(c.activeKpi,status);
 for(const [id,value]of Object.entries(fields))if(id!=='operationalTaskType')assert.equal(c.$('#'+id).value,value);
 assert.equal(snapshots.at(-1).sort,'latest_basis_date');assert.equal(snapshots.at(-1).direction,'desc');
 click(type);assert.equal(JSON.stringify(c.operationalTaskParams()),before);assert.equal(c.activeKpi,status);
 click(type);click(types[(types.indexOf(type)+1)%types.length]);assert.equal(c.activeKpi,status);
 combinations++;
}
const old=snapshots.length;c.$('#operationalTaskTypes').onclick({target:{closest:()=>null}});assert.equal(snapshots.length,old);
const rows=Array.from({length:16},(_,i)=>({status:'completed',type:i<2?'amcu_exclusion':i<5?'warning_block':'nazk_check'}));
rows.push({status:'new',type:'amcu_exclusion'});
for(const id of ['operationalTaskSearch','operationalTaskOfficer','operationalTaskDateFrom','operationalTaskType'])c.$('#'+id).value='';
c.$('#operationalTaskStatus').value='completed';
const selected=()=>rows.filter(r=>groups[c.operationalTaskParams().status_group].includes(r.status)&&(!c.operationalTaskParams().type||r.type===c.operationalTaskParams().type));
assert.equal(selected().length,16);click('amcu_exclusion');assert.equal(selected().length,2);assert.equal(c.activeKpi,'completed');
click('amcu_exclusion');assert.equal(selected().length,16);assert.equal(c.activeKpi,'completed');
console.log(`TASK_TYPE_FILTER_UNIT=PASS; ${combinations} status/type combinations, preserved filters/KPI/sort, toggle, 16→2→16`);
