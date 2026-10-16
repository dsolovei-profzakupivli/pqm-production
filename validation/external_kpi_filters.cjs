/* Run actual navigation functions against an isolated in-memory registry adapter. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync('app.js','utf8'),selection=require('../application_selection.js');
const nodes=new Map(),node=id=>{if(!nodes.has(id))nodes.set(id,{value:'',checked:false,classList:{toggle(){}}});return nodes.get(id)};
const selected=new Set(),snapshots=selection.create(selected),summaries={};
const c={URL,URLSearchParams,Set,selected,applicationSelection:snapshots,activeRow:'old',officerFilter:'old',categoryFilter:'old',deepLinkSubmissionId:'old',page:8,statsSignature:'old',loadRowsGeneration:0,
  filterSelections:Object.fromEntries(['status','marketplace','registry','supplier','framework','dk'].map(key=>[key,new Set()])),
  $:node,$$:()=>[],clearApplicationDeepLinkFilter:()=>{c.deepLinkSubmissionId=''},invalidateRegistryStats:()=>{c.invalidated=(c.invalidated||0)+1},
  syncPrimaryFilters:()=>{},saveFilterState:()=>{c.saved=true},updateApplicationFilterStyles:()=>{},marketplaceFilterLabels:{},
  updateMultiSummary:(id,label,set)=>{summaries[id]=[...set]},showModule:name=>{c.activeModule=name},addCalendarDays:()=> '2026-10-09',
  profilesMetadataReady:true,applicationRowsCurrent:()=>true,
  initializeApplicationsRegistry:()=>{c.loaded=(c.loaded||0)+1;return true}};
vm.createContext(c);
const start=src.indexOf('function resetApplicationsForExternalKpi(){'),end=src.indexOf("$('#queueSearch')",start);
assert(start>0&&end>start);
// Stop at the last known KPI handler, without installing unrelated queue controls.
const block=src.slice(start,src.indexOf('\n',src.indexOf("$('#queuePublicationControl').onclick=",start)));
vm.runInContext(block,c);
const fields=['searchInput','protocolNumberFilter','protocolDecisionFilter','complianceStatusFilter','dateFromFilter','dateToFilter'];
const profile={columns:[{width:321}],kpis:['officers','decision_yes']},unchanged=JSON.stringify(profile);
function stale(){for(const field of fields)node('#'+field).value='old';for(const set of Object.values(c.filterSelections))set.add('old');snapshots.toggle({id:'previous',protocolNumber:'old'},true);c.officerFilter='old';c.categoryFilter='old';c.deepLinkSubmissionId='old';node('#queueProtocolFrom').value='2026-10-01';node('#queueProtocolTo').value='2026-10-08'}
function click(id,data){node('#'+id).onclick({target:{closest:()=>({dataset:data})}})}
function clean(){for(const field of fields.slice(0,4))assert.equal(node('#'+field).value,'');for(const key of ['marketplace','registry','supplier','framework','dk'])assert.equal(c.filterSelections[key].size,0);assert.equal(selected.size,0);assert.equal(snapshots.entries().length,0);assert.equal(c.deepLinkSubmissionId,'');assert.equal(c.page,1);assert.equal(c.activeModule,'applications');assert.equal(JSON.stringify(profile),unchanged)}
stale();const oldRevision=snapshots.revision;click('queueQualificationCards',{qualificationOfficer:'Officer A'});clean();assert.equal(c.officerFilter,'Officer A');assert.equal(c.categoryFilter,'');assert.equal(node('#dateFromFilter').value,'2026-10-09');assert.equal(node('#dateToFilter').value,'');assert.deepEqual([...c.filterSelections.status],['Очікує рішення']);assert(snapshots.revision>oldRevision);
stale();click('queueCategoryCards',{qualificationCategory:'Їжа'});clean();assert.equal(c.categoryFilter,'Їжа');assert.equal(c.officerFilter,'');
stale();click('queueProtocolOfficerCards',{protocolOfficer:'Officer B'});clean();assert.equal(c.officerFilter,'Officer B');assert.equal(c.filterSelections.status.size,0);assert.equal(node('#dateFromFilter').value,'2026-10-01');assert.equal(node('#dateToFilter').value,'2026-10-08');
stale();click('queueProtocolCategoryCards',{protocolCategory:'Газ/ЕЕ'});clean();assert.equal(c.categoryFilter,'Газ/ЕЕ');assert.equal(c.officerFilter,'');
stale();click('queuePublicationControl',{publicationState:'active'});clean();assert.deepEqual([...c.filterSelections.status],['Допущено']);assert.equal(c.categoryFilter,'');assert.equal(c.officerFilter,'');
// Consecutive navigation replaces the first KPI's conditions, not combines them.
click('queueQualificationCards',{qualificationOfficer:'Не призначено'});clean();assert.equal(c.officerFilter,'__unassigned__');assert.deepEqual([...c.filterSelections.status],['Очікує рішення']);
// Exact fixture IDs/count from the resulting scope (including the compound date/status conditions).
const records=[{id:'yes',officer:'__unassigned__',status:'Очікує рішення',date:'2026-10-09'},{id:'old',officer:'__unassigned__',status:'Очікує рішення',date:'2026-10-08'},{id:'other',officer:'Officer A',status:'Очікує рішення',date:'2026-10-10'},{id:'rejected',officer:'__unassigned__',status:'Відхилено',date:'2026-10-10'}];
assert.deepEqual(records.filter(r=>r.officer===c.officerFilter&&c.filterSelections.status.has(r.status)&&r.date>=node('#dateFromFilter').value).map(r=>r.id),['yes']);
assert.deepEqual(summaries.frameworkFilter,[]);assert.equal(c.loaded,6);assert.equal(c.invalidated,6);
// Even an empty selection invalidates a pending select-all of the same filter scope.
snapshots.sync({status:'Очікує рішення'});const pendingScope=snapshots.scope,pendingRevision=snapshots.revision;
c.openApplicationsFromQueue({officer:'Не призначено'});
assert.equal(snapshots.all([{id:'late-response'}],pendingScope,pendingRevision),false);assert.equal(selected.size,0);
// The local decision handler remains additive and does not invoke the external reset.
const local=src.slice(src.indexOf('const decisionKpiValues='),src.indexOf("$('#clearFiltersBtn').onclick="));
assert(local.includes('protocolDecisionFilter'));assert(!local.includes('resetApplicationsForExternalKpi'));
assert.equal((src.match(/resetApplicationsForExternalKpi\(\)/g)||[]).length,2);
(async()=>{
 // A second navigation while metadata/rows are pending must load its own scope.
 let resolve;const pending=new Promise(done=>{resolve=done}),loaded=[];
 c.initializeApplicationsRegistry=()=>pending;c.applicationRowsCurrent=()=>false;
 c.loadRows=async()=>{loaded.push(c.officerFilter);return true};
 const first=c.openApplicationsFromQueue({officer:'First'}),second=c.openApplicationsFromQueue({officer:'Last'});
 resolve();await Promise.all([first,second]);assert.deepEqual(loaded,['Last']);assert.equal(selected.size,0);
 console.log('EXTERNAL_KPI_FILTERS=PASS (five entry points, rapid pending navigation, IDs/count, selection, profile invariance)');
})().catch(error=>{console.error(error);process.exitCode=1});
