/* Synthetic data only, with the same markup used by the real task renderer. */
(()=>{
 const types=[['nazk_check','НАЗК',8],['amcu_exclusion','АМКУ',4],['warning_block','Блокування',3],['termination_exclusion','Припинення',2]];
 document.querySelector('#operationalTaskTypes').innerHTML=types.map(([type,label,count])=>`<button type="button" class="operational-type-marker operational-type-kpi" data-task-type="${type}" aria-pressed="false"><span>${label}</span><strong>${count}</strong></button>`).join('');
 for(const [id,n] of Object.entries({historyTotal:72,supplierRegistryTotal:128,supplierRegistryActive:92,supplierRegistryCandidates:18,supplierRegistryAmcu:4,supplierRegistryNazk:7,frameworksTotal:64}))document.getElementById(id).textContent=n;
})();
