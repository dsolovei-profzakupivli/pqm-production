const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('app.js','utf8');
const code=source.slice(source.indexOf('async function loadSandboxAutomationControl('),source.indexOf('async function toggleSchedulerJob('));
const root={},button={},label={};
let role='admin',disabled=false,locked=false,confirmed=false,posts=0,reloads=0,fail=false;
const context=vm.createContext({
  $:selector=>({'#sandboxAutomationControl':root,'#disableSandboxAutomation':button,'#sandboxAutomationState':label}[selector]),
  API:'/api',role:()=>role,confirm:()=>confirmed,toast:()=>{},
  currentMe:{permissions:{'admin.manage':true}},
  request:async(url,options)=>{
    assert.equal(url,'/api/admin/background-jobs');
    if(fail)throw Error('synthetic offline failure');
    if(options){assert.equal(options.method,'POST');assert.deepEqual(JSON.parse(options.body),{confirm:true});posts++;disabled=true;}
    return {disabled:disabled||locked,environment_locked:locked,can_disable:!disabled&&!locked};
  },
  loadRuntimeFeatures:async()=>{reloads++;await context.loadSandboxAutomationControl(true);}
});
vm.runInContext(code,context);
(async()=>{
  await context.loadSandboxAutomationControl(true);
  assert.equal(root.hidden,false);assert.equal(button.disabled,false);assert.equal(label.textContent,'Автоматика активна');
  await button.onclick();assert.equal(posts,0);
  confirmed=true;await button.onclick();assert.equal(posts,1);assert.equal(reloads,1);
  assert.equal(button.disabled,true);assert.equal(label.textContent,'Автоматику вимкнено');
  disabled=false;locked=true;await context.loadSandboxAutomationControl(true);
  assert.equal(button.disabled,true);assert.match(button.title,/PQM_DISABLE_BACKGROUND_JOBS=1/);
  await context.loadSandboxAutomationControl(false);assert.equal(root.hidden,true);
  role='viewer';await context.loadSandboxAutomationControl(true);assert.equal(root.hidden,true);
  role='admin';context.currentMe.permissions['admin.manage']=false;
  await context.loadSandboxAutomationControl(true);assert.equal(root.hidden,true);
  context.currentMe.permissions['admin.manage']=true;
  role='admin';fail=true;await context.loadSandboxAutomationControl(true);
  assert.equal(button.disabled,true);assert.equal(label.textContent,'Стан автоматики не підтверджено');
  console.log('SANDBOX_AUTOMATION_UI=PASS; NO_REAL_REQUESTS');
})().catch(error=>{console.error(error);process.exitCode=1;});
