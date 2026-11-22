/* Execute the real loader with synthetic responses; no server/network/sync. */
const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('app.js','utf8');
const start=source.indexOf('async function loadFrameworkAnalytics(){');
const end=source.indexOf('async function loadFrameworkBidsSection(){',start);
assert(start>=0&&end>start);
const elements=new Map(),pending=[];
const context={
 $:selector=>{if(!elements.has(selector))elements.set(selector,{textContent:'',innerHTML:'',hidden:false,disabled:false,querySelectorAll:()=>[]});return elements.get(selector)},
 request:url=>{assert(url.startsWith('/api/framework-registry?'));return new Promise((resolve,reject)=>pending.push({resolve,reject}))},
 API:'/api',frameworkParams:()=>'',frameworkNumber:value=>String(value),esc:String,
 updateFrameworkRegistryExport:()=>{}
};
vm.createContext(context);
vm.runInContext('let frameworkRequestSequence=0,frameworkPage=1,frameworkPages=1;\n'+source.slice(start,end),context);
const load=()=>vm.runInContext('loadFrameworkAnalytics()',context);
const data=total=>({items:[],total,pages:1,bids_available:false});
(async()=>{
 const older=load(),newer=load();
 pending[1].resolve(data(42));await newer;
 const body=elements.get('#frameworksBody').innerHTML;
 pending[0].resolve(data(1));await older;
 assert.equal(elements.get('#frameworksTotal').textContent,'42');
 assert.equal(elements.get('#frameworksBody').innerHTML,body);
 const oldError=load(),latest=load();
 pending[3].resolve(data(99));await latest;
 pending[2].reject(new Error('stale synthetic failure'));await oldError;
 assert.equal(elements.get('#frameworksTotal').textContent,'99');
 assert(!elements.get('#frameworksBody').innerHTML.includes('stale synthetic failure'));
 assert.equal(pending.length,4);
 console.log('FRAMEWORK_REGISTRY_RACE_UI=PASS: stale success/error ignored; no sync');
})().catch(error=>{console.error(error);process.exitCode=1});
