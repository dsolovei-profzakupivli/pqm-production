import pathlib
import shutil
import subprocess
import unittest

HERE=pathlib.Path(__file__).resolve().parent
ROOT=HERE if (HERE/'app.js').exists() else HERE.parents[1]

SCRIPT=r'''
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('node:assert/strict');
const src=fs.readFileSync(path.join(process.cwd(),'app.js'),'utf8');
const chunk=(a,b)=>src.slice(src.indexOf(a),src.indexOf(b,src.indexOf(a)));
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject}};
function harness(){
  let filter='A';const pending=[],kpi={dataset:{kpi:'applications'},textContent:''},cards={innerHTML:''},scroll={scrollTop:70,scrollLeft:140},renders=[];
  const c={API:'/api',URLSearchParams,structuredClone,setTimeout,clearTimeout,statsSignature:'',statsGeneration:0,statsPending:null,
    profilesGeneration:0,profileLayoutGeneration:0,profilesMetadataReady:true,authReady:Promise.resolve(),registryReloadPromise:null,applicationsRegistryInitialized:false,applicationsRegistryInitialization:null,
    loadRowsGeneration:0,rows:[{id:'old'}],page:3,pages:5,total:250,loading:false,selected:new Set(),officerFilter:'',
    sortKey:'receivedDate',sortDirection:'desc',multiSort:[{key:'participant',direction:'asc'}],
    profiles:[{id:'personal',columns:[{key:'participant',width:321,pin:'left',visible:true}],kpis:['applications'],sorts:[]}],activeProfileId:'personal',columns:[],
    currentFilterParams:()=>({search:filter}),request:(url)=>{const d=deferred();pending.push({url,...d});return d.promise},
    $:selector=>selector==='#officerCards'?cards:scroll,$$:selector=>selector==='[data-kpi]'?[kpi]:[],
    esc:x=>x,formatOfficerName:x=>x,toast:()=>{},updateApplicationFilterStyles:()=>{},saveFilterState:()=>{},
    mapRow:x=>({...x}),render:()=>renders.push(c.rows.map(r=>r.id)),syncTableScroll:()=>{},
    defaultKpis:()=>[],saveProfiles:()=>{},renderProfiles:()=>{},applyProfileSort:()=>{c.sortApplied=true},
    loadAuthorizedOfficers:async()=>{},loadSearchFields:async()=>{},loadPrimaryFilterOptions:async()=>{},loadFrameworks:async()=>{},loadSupplierOptions:async()=>{},renderProfileFallback:()=>{},
  };
  vm.createContext(c);
  vm.runInContext(chunk('function invalidateRegistryStats()','let officerFilter='),c);
  vm.runInContext(chunk('async function loadStats()','function bindStaticMulti'),c);
  vm.runInContext(chunk('async function loadProfiles()','function normalizeProfiles()'),c);
  vm.runInContext(chunk('async function refreshOneRow(','function renderRemarksCatalog()'),c);
  vm.runInContext(chunk('async function saveField(','function buildRemarksText()'),c);
  vm.runInContext(chunk('async function reloadApplicationsRegistry(','function setProzorroSyncButtonIdle'),c);
  vm.runInContext(chunk('const initializeApplicationsRegistry=','$(\'#applicationsNav\').onclick=')+'\nglobalThis.initialize=initializeApplicationsRegistry;',c);
  return {c,pending,kpi,scroll,renders,setFilter:v=>{filter=v}};
}
let count=0;async function test(name,fn){await fn();count++;console.log('PASS '+name)}
(async()=>{
  await test('stats A/B latest wins',async()=>{const h=harness(),a=h.c.loadStats();h.setFilter('B');const b=h.c.loadStats();h.pending[1].resolve({applications:2});await b;h.pending[0].resolve({applications:99});await a;assert.equal(h.kpi.textContent,'2')});
  await test('same-filter data invalidation and coalescing',async()=>{const h=harness(),a=h.c.loadStats(),same=h.c.loadStats();assert.equal(h.pending.length,1);h.pending[0].resolve({applications:1});await Promise.all([a,same]);await h.c.loadStats();assert.equal(h.pending.length,1);h.c.invalidateRegistryStats();const b=h.c.loadStats();h.pending[1].resolve({applications:8});await b;assert.equal(h.kpi.textContent,'8')});
  await test('stale failure does not clear current signature',async()=>{const h=harness(),a=h.c.loadStats();h.setFilter('B');const b=h.c.loadStats();h.pending[1].resolve({applications:2});await b;h.pending[0].reject(Error('old'));await a;assert.equal(h.c.statsSignature,'search=B')});
  await test('rows latest wins and no duplicate state',async()=>{const h=harness(),a=h.c.loadRows(),b=h.c.loadRows();h.pending[1].resolve({items:[{id:'new'}],page:3,pages:4,total:170});await b;h.pending[0].resolve({items:[{id:'old'}],page:1,total:1});await a;assert.equal(h.c.rows.length,1);assert.equal(h.c.rows[0].id,'new');assert.equal(h.c.total,170);assert.deepEqual(h.renders.at(-1),['new'])});
  await test('failed rows recover without clearing readable rows',async()=>{const h=harness(),a=h.c.loadRows();h.pending[0].reject(Error('offline'));assert.equal(await a,false);assert.equal(h.c.rows[0].id,'old');assert.equal(h.c.loading,false);const b=h.c.loadRows();h.pending[1].resolve({items:[{id:'recovered'}],page:3,total:1});assert.equal(await b,true);assert.equal(h.c.rows[0].id,'recovered')});
  await test('row refresh uses full filtered page and preserves scroll/settings',async()=>{const h=harness(),columns=JSON.stringify(h.c.profiles),sorts=JSON.stringify(h.c.multiSort);const a=h.c.refreshOneRow({id:'old'});assert.match(h.pending[0].url,/search=A/);assert.match(h.pending[0].url,/page=3/);assert.doesNotMatch(h.pending[0].url,/submission_id/);h.pending[0].resolve({items:[{id:'replacement'}],page:3,pages:4,total:151});await a;assert.equal(h.c.total,151);assert.equal(h.c.rows[0].id,'replacement');assert.equal(h.scroll.scrollTop,70);assert.equal(h.scroll.scrollLeft,140);assert.equal(JSON.stringify(h.c.profiles),columns);assert.equal(JSON.stringify(h.c.multiSort),sorts)});
  await test('profile A/B stale response discarded',async()=>{const h=harness(),a=h.c.loadProfiles(),b=h.c.loadProfiles();h.pending[1].resolve({items:[{id:'new',columns:[],kpis:[]}]});await b;h.pending[0].resolve({items:[{id:'old',columns:[],kpis:[]}]});await a;assert.equal(h.c.profiles[0].id,'new')});
  await test('metadata reload preserves personal columns and live sort',async()=>{const h=harness();h.c.applicationsRegistryInitialized=true;const before=JSON.stringify(h.c.profiles[0].columns),a=h.c.loadProfiles();h.pending[0].resolve({items:[{id:'personal',columns:[{key:'participant',width:50}],kpis:[],sorts:[{key:'other'}]}]});await a;assert.equal(JSON.stringify(h.c.profiles[0].columns),before);assert.equal(h.c.sortApplied,undefined);assert.equal(h.c.page,3)});
  await test('local layout change invalidates profile response',async()=>{const h=harness(),a=h.c.loadProfiles();h.c.profilesGeneration++;h.c.profiles[0].columns[0].width=500;h.pending[0].resolve({items:[{id:'personal',columns:[],kpis:[]}]});await a;assert.equal(h.c.profiles[0].columns[0].width,500)});
  await test('initial load coalesced; reentry refreshes data only',async()=>{const h=harness(),calls=[];const d=deferred();h.c.reloadApplicationsRegistry=o=>{calls.push(o);return d.promise};const a=h.c.initialize(),b=h.c.initialize();await new Promise(resolve=>setImmediate(resolve));assert.equal(calls.length,1);assert.equal(calls[0].reloadMetadata,true);d.resolve({ok:true});await Promise.all([a,b]);await h.c.initialize();assert.equal(calls.length,2);assert.equal(calls[1].reloadMetadata,false)});
  await test('reload coalesced and failure unlocks retry',async()=>{const h=harness(),d=deferred();let calls=0;h.c.reloadApplicationsRegistryData=()=>{calls++;return d.promise};const a=h.c.reloadApplicationsRegistry(),b=h.c.reloadApplicationsRegistry();assert.equal(calls,1);d.reject(Error('offline'));await Promise.allSettled([a,b]);assert.equal(h.c.registryReloadPromise,null);h.c.reloadApplicationsRegistryData=async()=>{calls++;return {ok:true}};await h.c.reloadApplicationsRegistry();assert.equal(calls,2)});
  await test('failed initial metadata load remains retryable',async()=>{const h=harness();let calls=0;h.c.reloadApplicationsRegistry=async()=>({ok:++calls>1,failures:['profiles']});await h.c.initialize();assert.equal(calls,2);assert.equal(h.c.applicationsRegistryInitialized,true)});
  await test('successful field save invalidates stats with unchanged filters',async()=>{const h=harness();h.c.fieldMap={managerName:'manager_name'};h.c.role=()=> 'admin';h.c.$=()=>({selectedOptions:[{text:'Admin'}]});h.c.statsSignature='search=A';let statsCalls=0;h.c.loadStats=async()=>{statsCalls++};const a=h.c.saveField({id:'id'},'managerName','New');h.pending[0].resolve({});await a;assert.equal(h.c.statsSignature,'');assert.equal(statsCalls,1)});
  console.log('REGISTRY_F5_INTERACTIONS='+count+'/'+count+' PASS');
})().catch(e=>{console.error(e);process.exitCode=1});
'''

class RegistryF5State(unittest.TestCase):
    def test_frontend_interactions(self):
        node=shutil.which('node')
        if not node:
            runtime=pathlib.Path('C:/Users/User/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe')
            if runtime.exists():node=str(runtime)
        self.assertIsNotNone(node,'Node is required for Registry interaction regressions')
        result=subprocess.run([node,'-e',SCRIPT],cwd=ROOT,capture_output=True,text=True,timeout=30)
        self.assertEqual(0,result.returncode,result.stdout+result.stderr)
        self.assertIn('REGISTRY_F5_INTERACTIONS=13/13 PASS',result.stdout)

if __name__=='__main__':unittest.main()
