import importlib.util
import pathlib
import shutil
import subprocess
import unittest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE if (HERE / 'app.js').exists() else HERE.parents[1]
spec = importlib.util.spec_from_file_location('registry_harness', HERE / 'test_registry_f5_state.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)

SCRIPT = fixture.SCRIPT.split('let count=0;', 1)[0] + r'''
let count=0;async function test(name,fn){await fn();count++;console.log('PASS '+name)}
async function waitFor(predicate,label){const deadline=Date.now()+5000;while(!predicate()){assert.ok(Date.now()<deadline,'Timed out waiting for '+label);await new Promise(resolve=>setTimeout(resolve,10))}}
function profileHarness(){
  const h=harness();h.c.profilesMetadataReady=false;h.c.currentMe={role:'admin'};
  const nodes=new Map();h.c.$=key=>{if(!nodes.has(key))nodes.set(key,{innerHTML:''});return nodes.get(key)};
  h.c.normalizeProfiles=()=>{};h.c.profile=()=>h.c.profiles.find(p=>p.id===h.c.activeProfileId)||h.c.profiles[0];
  vm.runInContext(src.match(/^function renderProfiles\(\).*$/m)[0]+'\n'+src.match(/^let profileSaveTimer;function persistProfileLayout\(\).*$/m)[0]+'\n'+chunk('function renderProfileFallback(){','async function reloadApplicationsRegistry('),h.c);
  h.c.loadRows=async()=>true;h.c.loadStats=async()=>true;
  h.tick=async()=>{for(let i=0;i<12;i++)await Promise.resolve()};
  h.options=()=>h.c.$('#profileSelect').innerHTML;
  h.response={items:[{id:'personal',name:'Saved',columns:[],kpis:[],sorts:[]},{id:'system',name:'System',columns:[],kpis:[],is_system:true}]};
  return h;
}
function queueHarness(){
  const h=profileHarness();h.c.activeModule='workQueue';h.c.filterSelections={status:new Set()};
  h.response.items[0].columns=structuredClone(h.c.profiles[0].columns);
  h.c.addCalendarDays=()=> '2026-10-09';h.c.showModule=name=>{h.c.activeModule=name};
  h.c.loadRows=async()=>{h.rowLoads=(h.rowLoads||0)+1;h.c.rows=[{id:'registry-row'}];return true};
  h.c.$('#queueProtocolFrom').value='2026-10-01';h.c.$('#queueProtocolTo').value='2026-10-08';
  vm.runInContext(src.match(/^function openApplicationsFromQueue\(.*$/m)[0]+'\n'+src.match(/^\$\('#queueQualificationCards'\).*$/m)[0],h.c);
  h.click=officer=>h.c.$('#queueQualificationCards').onclick({target:{closest:()=>({dataset:{qualificationOfficer:officer}})}});
  return h;
}
(async()=>{
  await test('login work queue first KPI click populates profiles after auth',async()=>{const h=queueHarness(),auth=deferred();h.c.authReady=auth.promise;const layout=JSON.stringify(h.c.profiles[0].columns),sort=JSON.stringify(h.c.multiSort);h.click('Officer');assert.equal(h.c.activeModule,'applications');assert.equal(h.pending.length,0);auth.resolve();await h.tick();const done=h.c.initialize();assert.equal(h.pending.length,1);assert.equal(h.pending[0].url,'/api/application-profiles');h.pending[0].resolve(h.response);await done;assert.match(h.options(),/value="personal" selected/);assert.equal((h.options().match(/<option/g)||[]).length,2);assert.equal(h.c.rows[0].id,'registry-row');assert.equal(h.c.officerFilter,'Officer');assert.deepEqual([...h.c.filterSelections.status],['Очікує рішення']);assert.equal(h.c.$('#dateFromFilter').value,'2026-10-09');assert.equal(h.c.page,1);assert.equal(JSON.stringify(h.c.profiles[0].columns),layout);assert.equal(JSON.stringify(h.c.multiSort),sort);const listener=h.c.$('#queueQualificationCards').onclick;h.c.activeModule='workQueue';h.click('Second');await h.c.initialize();assert.equal(h.pending.length,1);assert.equal(h.rowLoads,2);assert.equal(h.c.officerFilter,'Second');assert.equal(h.c.$('#queueQualificationCards').onclick,listener);assert.equal((h.options().match(/<option/g)||[]).length,2)});
  await test('KPI pending metadata stale response retries and fills options',async()=>{const h=queueHarness(),done=h.c.openApplicationsFromQueue({category:'Category',status:'Допущено',protocol:true});await h.tick();h.c.profilesGeneration++;h.pending[0].resolve(h.response);await h.tick();assert.equal(h.c.applicationsRegistryInitialized,false);await waitFor(()=>h.pending.length===2,'profiles retry request');h.pending[1].resolve(h.response);await done;assert.match(h.options(),/Saved/);assert.equal(h.c.categoryFilter,'Category');assert.deepEqual([...h.c.filterSelections.status],['Допущено']);assert.equal(h.c.$('#dateFromFilter').value,'2026-10-01');assert.equal(h.c.$('#dateToFilter').value,'2026-10-08')});
  await test('KPI failed metadata fetch recovers without F5',async()=>{const h=queueHarness(),done=h.c.openApplicationsFromQueue({officer:'Не призначено'});await h.tick();h.pending[0].reject(Error('offline'));await waitFor(()=>h.pending.length===2,'profiles retry request');h.pending[1].resolve(h.response);await done;assert.equal(h.c.applicationsRegistryInitialized,true);assert.match(h.options(),/Saved/);assert.equal(h.c.officerFilter,'__unassigned__');assert.equal(h.c.rows[0].id,'registry-row')});
  await test('auth before first module entry; pending entries coalesced',async()=>{const h=profileHarness(),auth=deferred();h.c.authReady=auth.promise;const a=h.c.initialize(),b=h.c.initialize();assert.strictEqual(a,b);assert.equal(h.pending.length,0);auth.resolve();await h.tick();assert.equal(h.pending.length,1);h.pending[0].resolve(h.response);await a;assert.equal(h.c.applicationsRegistryInitialized,true);assert.match(h.options(),/Saved/)});
  await test('fresh page initial readiness and saved selection',async()=>{const h=profileHarness(),a=h.c.initialize();await h.tick();assert.equal(h.c.applicationsRegistryInitialized,false);h.pending[0].resolve(h.response);await a;assert.equal(h.c.activeProfileId,'personal');assert.match(h.options(),/value="personal" selected/)});
  await test('local-default never invalidates metadata',async()=>{const h=profileHarness();h.c.profiles=[{id:'local-default',columns:[],kpis:[],is_system:true}];const a=h.c.loadProfiles();h.c.persistProfileLayout();assert.equal(h.c.profilesGeneration,1);assert.equal(h.c.profileLayoutGeneration,0);h.pending[0].resolve(h.response);assert.equal(await a,true);assert.match(h.options(),/System/)});
  await test('forbidden system save never invalidates metadata',async()=>{const h=profileHarness();h.c.profiles[0].is_system=true;h.c.currentMe={role:'viewer'};const a=h.c.loadProfiles();h.c.persistProfileLayout();assert.equal(h.c.profileLayoutGeneration,0);h.pending[0].resolve(h.response);assert.equal(await a,true)});
  await test('layout edits preserve layout while list still populates',async()=>{const h=profileHarness(),a=h.c.loadProfiles();h.c.profiles[0].columns[0].width=499;h.c.persistProfileLayout();clearTimeout(h.c.profileSaveTimer);assert.equal(h.c.profilesGeneration,1);h.pending[0].resolve(h.response);assert.equal(await a,true);assert.equal(h.c.profiles[0].columns[0].width,499);assert.match(h.options(),/System/)});
  await test('stale response rejected by metadata readiness; init retries',async()=>{const h=profileHarness(),a=h.c.initialize();await h.tick();h.c.profilesGeneration++;h.pending[0].resolve(h.response);await h.tick();assert.equal(h.c.applicationsRegistryInitialized,false);await waitFor(()=>h.pending.length===2,'profiles retry request');assert.equal(h.pending.length,2);h.pending[1].resolve(h.response);await a;assert.equal(h.c.applicationsRegistryInitialized,true)});
  await test('aborted fetch recovers without F5',async()=>{const h=profileHarness(),a=h.c.initialize();await h.tick();h.pending[0].reject(new Error('AbortError'));await waitFor(()=>h.pending.length===2,'profiles retry request');assert.equal(h.pending.length,2);h.pending[1].resolve(h.response);await a;assert.match(h.options(),/Saved/)});
  await test('empty items controlled fallback',async()=>{const h=profileHarness(),a=h.c.loadProfiles();h.pending[0].resolve({items:[]});assert.equal(await a,true);assert.match(h.options(),/Основний реєстр/);assert.equal(h.c.profilesMetadataReady,true)});
  await test('malformed response not ready',async()=>{const h=profileHarness(),a=h.c.loadProfiles();h.pending[0].resolve({});await assert.rejects(a);assert.equal(h.c.profilesMetadataReady,false)});
  await test('exhausted fetch fallback retains saved selection and allows retry',async()=>{const h=profileHarness();h.c.setTimeout=fn=>{fn();return 0};h.c.profiles=[{id:'local-default',name:'Fallback',columns:[],kpis:[],is_system:true}];h.c.request=async()=>{throw Error('offline')};await h.c.initialize();assert.equal(h.c.applicationsRegistryInitialized,false);assert.equal(h.c.activeProfileId,'personal');assert.match(h.options(),/Fallback/);h.c.request=async()=>h.response;await h.c.initialize();assert.equal(h.c.applicationsRegistryInitialized,true);assert.equal(h.c.activeProfileId,'personal')});
  await test('reentry no duplicate options or profile requests',async()=>{const h=profileHarness(),a=h.c.initialize();await h.tick();h.pending[0].resolve(h.response);await a;const options=h.options();await h.c.initialize();await h.c.initialize();assert.equal(h.pending.length,1);assert.equal(h.options(),options);assert.equal((options.match(/<option/g)||[]).length,2)});
  await test('navigation restore uses metadata-ready initialization',async()=>{const nav=fs.readFileSync('navigation.js','utf8'),line=nav.split('\n').find(x=>x.includes('applications:{get:'));assert.match(line,/load:\(\)=>initializeApplicationsRegistry\(\)/);const h=profileHarness(),load=vm.runInContext(line.match(/load:(\(\)=>initializeApplicationsRegistry\(\))/)[1],h.c),a=load();await h.tick();h.pending[0].resolve(h.response);await a;assert.equal(h.c.profilesMetadataReady,true);assert.match(h.options(),/Saved/)});
  console.log('PROFILE_LOADING_INTERACTIONS='+count+'/15 PASS');
})().catch(e=>{console.error(e);process.exitCode=1});
'''


class RegistryProfileLoading(unittest.TestCase):
    def test_profile_loading_interactions(self):
        node = shutil.which('node') or str(pathlib.Path('C:/Users/User/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'))
        result = subprocess.run([node, '-e', SCRIPT], cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PROFILE_LOADING_INTERACTIONS=15/15 PASS', result.stdout)
