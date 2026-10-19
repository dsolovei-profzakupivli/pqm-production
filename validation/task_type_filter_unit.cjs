const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const app=fs.readFileSync('app.js','utf8'),nodes=new Map(),snapshots=[];
const types=['nazk_check','amcu_exclusion','warning_block','termination_exclusion'];
const c={$:selector=>{if(!nodes.has(selector))nodes.set(selector,{value:''});return nodes.get(selector)},
 operationalBasisDirection:'desc',resetOperationalKpiFilters:()=>{throw Error('Type selection must preserve status and other filters')}};
c.loadOperationalTasks=()=>{snapshots.push(c.operationalTaskParams())};vm.createContext(c);
vm.runInContext(app.split(/\r?\n/).filter(line=>line.startsWith('function operationalTaskParams(')||line.startsWith("$('#operationalTaskTypes').onclick=")).join('\n'),c);
const click=type=>c.$('#operationalTaskTypes').onclick({target:{closest:()=>({dataset:{taskType:type}})}});
const statuses=['active','needs_action','awaiting_response','ready_for_document','awaiting_sync','completed','cancelled','historical'];let checks=0;
for(const status of statuses)for(const type of types){
 const fields={operationalTaskSearch:'Контроль 0001',operationalTaskOfficer:'42',operationalTaskDateFrom:'2026-10-17',operationalTaskStatus:status,operationalTaskType:''};
 for(const [id,value]of Object.entries(fields))c.$('#'+id).value=value;
 const before=JSON.stringify(c.operationalTaskParams());click(type);
 assert.equal(c.$('#operationalTaskType').value,type);
 for(const [id,value]of Object.entries(fields))if(id!=='operationalTaskType')assert.equal(c.$('#'+id).value,value);
 assert.equal(snapshots.at(-1).sort,'latest_basis_date');assert.equal(snapshots.at(-1).direction,'desc');
 click(type);assert.equal(JSON.stringify(c.operationalTaskParams()),before);checks++;
}
const params=snapshots.at(-1);assert.equal(params.status_group,'historical');
console.log(`TASK_TYPE_FILTER_UNIT=PASS; ${checks} status/type intersections, shared filters preserved, toggle reset scoped to type`);
