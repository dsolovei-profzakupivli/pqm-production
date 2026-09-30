const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

const source=fs.readFileSync(path.join(__dirname,'..','nav_icons.js'),'utf8');
function resolved(environment){
  const elements=new Map();
  const navigation={append(button){elements.set(button.id,button)}};
  const document={
    documentElement:{dataset:{pqmEnvironment:environment}},
    getElementById(id){return id==='mainNav'?navigation:elements.get(id)},
    createElement(){return {dataset:{},classList:{toggle(){}},setAttribute(){}}},
  };
  const window={};
  vm.runInNewContext(source,{document,window,URL,Set,location:{href:'https://example.test/?view=applications'},localStorage:{getItem(){return null}}});
  window.pqmRenderNavigation({frameworksNav:{iconKey:'history',displayMode:'icon',visible:false},
    edrMonitoringNav:{iconKey:'requests',displayMode:'text'},
    administrationNav:{iconKey:'audit',displayMode:'icon-text'}});
  return Object.fromEntries(window.pqmResolvedNavigation().map(item=>[item.id,item]));
}

const sandbox=resolved('sandbox');
assert.equal(sandbox.frameworksNav.iconKey,'history');
assert.equal(sandbox.frameworksNav.displayMode,'icon');
assert.equal(sandbox.frameworksNav.visible,false);
assert.equal(sandbox.edrMonitoringNav.iconKey,'requests');
assert.equal(sandbox.edrMonitoringNav.displayMode,'text');
assert.equal(sandbox.administrationNav.iconKey,'audit');

const prod=resolved('');
assert.equal(prod.frameworksNav.iconKey,'frameworksTarget');
assert.equal(prod.edrMonitoringNav.iconKey,'edrSearch');
assert.equal(prod.administrationNav.iconKey,'administration');
process.stdout.write('SANDBOX navigation overrides persist in rendered state; PROD baseline unchanged\n');
