const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const ids=['workQueueView','applicationsView','historyView','suppliersView','edrMonitoringView','frameworkAnalyticsView','procurementsView','referencesView','requestsView','operationalTasksView'];
for(const zoom of [.75,.8,1,1.25]){
 const listeners={},mutations=[],sizes=[],views={};let scroll=0;
 for(const id of [...ids,'messagesView','administrationView','loginGate','frameworksView']){
  const properties={},classes=new Set();views[id]={hidden:id!=='workQueueView',classes,properties,classList:{add:c=>classes.add(c)},getBoundingClientRect:()=>({top:80-scroll,height:5000}),style:{setProperty:(k,v)=>properties[k]=v}};
 }
 class Clock extends Date{constructor(...args){super(...(args.length?args:['2026-10-18T06:00:00Z']))}static now(){return Date.parse('2026-10-18T06:00:00Z')}}
 const window={addEventListener:(e,f)=>listeners[e]=f,get scrollY(){return scroll}};
 const document={documentElement:{dataset:{}},querySelector:s=>views[s.slice(1)]||null,addEventListener(){}};
 const context={document,window,Date:Clock,innerHeight:1000,getComputedStyle:()=>({zoom:String(zoom)}),requestAnimationFrame:f=>f(),setTimeout:()=>1,clearTimeout(){},localStorage:{getItem:()=>null},ResizeObserver:class{constructor(f){sizes.push(f)}observe(){}},MutationObserver:class{constructor(f){mutations.push(f)}observe(){}}};
 vm.runInNewContext(fs.readFileSync('halloween_season.js','utf8')+'\n'+fs.readFileSync('halloween.js','utf8'),context);
 for(const id of ids)assert(views[id].classes.has('halloween-workspace'),id);
 for(const id of ['messagesView','administrationView','loginGate','frameworksView'])assert(!views[id].classes.size,id);
 assert.equal(views.workQueueView.properties['--halloween-workspace-height'],920/zoom+'px');
 scroll=700;listeners.resize();assert.equal(views.workQueueView.properties['--halloween-workspace-height'],920/zoom+'px');
 views.workQueueView.hidden=true;views.historyView.hidden=false;mutations[0]();assert.equal(views.historyView.properties['--halloween-workspace-height'],920/zoom+'px');
 assert.equal(document.documentElement.dataset.halloween,'on');
}
console.log('PASS:10 allowlisted workspaces; excluded service screens; four zooms; long tables and scroll do not rescale scene; tab switch updates');
