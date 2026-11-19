const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

const root=path.join(__dirname,'..');
const app=fs.readFileSync(path.join(root,'app.js'),'utf8');
const profileInitializer=app.match(/^const initializeApplicationsRegistry=.*$/m)?.[0];
assert.ok(profileInitializer,'application profile initializer exists');

function profileScenario(outcomes){
  let calls=0;const notices=[];
  const context={Promise,Error,authReady:Promise.resolve(),profilesMetadataReady:true,setTimeout:fn=>fn(),loading:false,
    reloadApplicationsRegistry:async()=>{calls++;const result=outcomes.shift();return result instanceof Error?Promise.reject(result):result},
    renderProfileFallback:()=>{},render:()=>{},toast:(...args)=>notices.push(args)};
  vm.runInNewContext(`let applicationsRegistryInitialization=null,applicationsRegistryInitialized=false;${profileInitializer}\n`+
    'globalThis.initialize=initializeApplicationsRegistry;globalThis.isInitialized=()=>applicationsRegistryInitialized;',context);
  return {context,calls:()=>calls,notices,addOutcome:value=>outcomes.push(value)};
}

(async()=>{
  const temporary=profileScenario([{ok:false,failures:['profiles']},{ok:true,failures:[]}]);
  await temporary.context.initialize();
  assert.equal(temporary.calls(),2);
  assert.equal(temporary.context.isInitialized(),true);
  assert.equal(temporary.notices.length,0);

  const failed=profileScenario(Array.from({length:3},()=>({ok:false,failures:['profiles']})));
  await failed.context.initialize();
  assert.equal(failed.calls(),3);
  assert.equal(failed.context.isInitialized(),false);
  assert.equal(failed.notices.length,1);
  failed.addOutcome({ok:true,failures:[]});
  await failed.context.initialize();
  assert.equal(failed.context.isInitialized(),true);
  assert.equal(failed.calls(),4);

  const source=fs.readFileSync(path.join(root,'table_widths_ui.js'),'utf8');
  const start=source.indexOf('let initialized=false,initializing=null;');
  assert.ok(start>0,'width-control initializer exists');
  const snippet=source.slice(start,source.lastIndexOf('})();'));
  let widthCalls=0,installs=0,observers=0;const listeners={};
  const widthContext={Promise,setTimeout:fn=>fn(),API:'/api',saved:{},document:{body:{}},
    authReady:{then(){}},window:{addEventListener:(name,fn)=>listeners[name]=fn},
    request:async()=>{widthCalls++;if(widthCalls<2)throw Error('temporary GET failure');return {tables:{}}},
    install:()=>{installs++},MutationObserver:class{observe(){observers++}},
    console:{warn:()=>{}},requestAnimationFrame:fn=>fn()};
  vm.runInNewContext(snippet+'\nglobalThis.initialize=initialize;globalThis.isInitialized=()=>initialized;',widthContext);
  await widthContext.initialize();
  assert.equal(widthCalls,2);
  assert.equal(installs,1);
  assert.equal(observers,1);
  assert.equal(widthContext.isInitialized(),true);
  assert.equal(typeof listeners.focus,'function');
  assert.equal(typeof listeners.online,'function');
  let exhaustedCalls=0;const retryListeners={};
  const exhaustedContext={...widthContext,saved:{},
    window:{addEventListener:(name,fn)=>retryListeners[name]=fn},
    request:async()=>{exhaustedCalls++;if(exhaustedCalls<=3)throw Error('temporary GET failure');return {tables:{}}}};
  vm.runInNewContext(snippet+'\nglobalThis.initialize=initialize;globalThis.isInitialized=()=>initialized;',exhaustedContext);
  await exhaustedContext.initialize();
  assert.equal(exhaustedCalls,3);
  assert.equal(exhaustedContext.isInitialized(),false);
  retryListeners.focus();
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(exhaustedCalls,4);
  assert.equal(exhaustedContext.isInitialized(),true);
  process.stdout.write('application profiles and system widths recover from transient GET failures\n');
})().catch(error=>{console.error(error);process.exitCode=1});
