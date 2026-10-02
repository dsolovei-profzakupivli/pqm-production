const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

const source=fs.readFileSync(path.join(__dirname,'..','nav_icons.js'),'utf8');
function render(environment,overrides){
  const elements=new Map();
  const navigation={append(button){elements.set(button.id,button)}};
  const document={
    documentElement:{dataset:{pqmEnvironment:environment}},
    getElementById(id){return id==='mainNav'?navigation:elements.get(id)},
    createElement(){
      const classes=new Set();
      return {dataset:{},classes,classList:{toggle(name,on){if(on)classes.add(name);else classes.delete(name)}},setAttribute(){}};
    },
  };
  const window={};
  vm.runInNewContext(source,{document,window,URL,Set,location:{href:'https://example.test/?view=applications'},localStorage:{getItem(){return null}}});
  window.pqmSetNavigationIcons([{icon_key:'attach',svg:'<svg data-test="attach"></svg>'}]);
  window.pqmRenderNavigation(overrides);
  return {items:Object.fromEntries(window.pqmResolvedNavigation().map(item=>[item.id,item])),elements};
}

// The DB round-trip test covers Save; a fresh VM represents F5 loading saved overrides.
const saved={frameworksNav:{iconKey:'attach',displayMode:'icon',visible:true},
  edrMonitoringNav:{iconKey:'edrSearch',displayMode:'icon',visible:true}};
for(const state of [render('sandbox',saved),render('sandbox',JSON.parse(JSON.stringify(saved)))]){
  assert.equal(state.items.frameworksNav.iconKey,'attach');
  assert.equal(state.items.frameworksNav.displayMode,'icon');
  assert.equal(state.items.edrMonitoringNav.iconKey,'edrSearch');
  assert.equal(state.items.edrMonitoringNav.displayMode,'icon');
  assert.equal(state.elements.get('frameworksNav').classes.has('main-nav-icon'),true);
  assert.match(state.elements.get('frameworksNav').innerHTML,/data-test="attach"/);
  assert.equal(state.elements.get('edrMonitoringNav').classes.has('main-nav-icon'),true);
  assert.doesNotMatch(state.elements.get('edrMonitoringNav').innerHTML,/Перевірка ЄДР/);
}
const prod=render('',{});
assert.equal(prod.items.frameworksNav.iconKey,'frameworksTarget');
assert.equal(prod.items.edrMonitoringNav.iconKey,'edrSearch');
assert.equal(prod.items.administrationNav.iconKey,'administration');
const savedAdmin=render('',{administrationNav:{iconKey:'attach',displayMode:'icon-text',order:13,visible:false}});
assert.equal(savedAdmin.items.administrationNav.iconKey,'attach');
assert.equal(savedAdmin.items.administrationNav.displayMode,'icon-text');
assert.equal(savedAdmin.items.administrationNav.order,13);
assert.equal(savedAdmin.items.administrationNav.visible,false);
assert.equal(savedAdmin.elements.get('administrationNav').hidden,true);
assert.match(savedAdmin.elements.get('administrationNav').innerHTML,/data-test="attach"/);
const appSource=fs.readFileSync(path.join(__dirname,'..','app.js'),'utf8');
assert.match(appSource,/adminNav\.hidden=!admin\|\|adminNav\.dataset\.navVisible==='false'/);
process.stdout.write('attach and edrSearch saved modes render unchanged after reload; PROD defaults unchanged\n');
