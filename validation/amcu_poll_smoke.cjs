// Execute the real polling functions with a synthetic DOM/clock, no HTTP.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../app.js'),'utf8');
const styles=fs.readFileSync(require('node:path').join(__dirname,'../styles.css'),'utf8');
assert.doesNotMatch(styles,/#refAmcuRefresh\s*\{[^}]*display\s*:\s*none/i,
 'AMCU retry must remain visible; access is controlled by role/runtime permissions');
const statusFn=source.slice(source.indexOf('async function loadReferenceStatus()'),source.indexOf('async function loadReferenceRegistry('));
const pollFn=source.slice(source.indexOf('function pollReferenceRefresh('),source.indexOf('async function refreshReference('));
const viewStart=source.indexOf('async function loadReferencesView()');
const viewFn=source.slice(viewStart,source.indexOf("$$('[data-ref-tab]')",viewStart));
const elements={},timers=[],loads=[],toasts=[];
let status={amcu:{status:'running'},nazk:{status:'ok'}},requests=0;
const ctx={API:'/api',Date,referencePollTimers:{},referenceLoaded:false,referenceTab:'amcu',
 $:key=>elements[key]??=( {textContent:'',disabled:false,dataset:{}}),
 referenceStatusText:s=>s?.status??'',request:async()=>{requests++;return status},
 setTimeout:fn=>{timers.push(fn);return timers.length},
 loadReferenceRegistry:async kind=>loads.push(kind),setReferenceTab:()=>{},toast:s=>toasts.push(s)};
vm.createContext(ctx);vm.runInContext(statusFn+pollFn+viewFn,ctx);
(async()=>{
 await ctx.loadReferencesView();
 assert.equal(timers.length,1,'F5/view load resumes active polling');
 assert.equal(elements['#refAmcuRefresh'].disabled,true);
 await ctx.loadReferencesView();ctx.pollReferenceRefresh('amcu');
 assert.equal(timers.length,1,'repeated view/refresh does not duplicate polls');
 await timers.shift()();assert.equal(timers.length,1,'one sequential poll, not overlapping intervals');
 status={amcu:{status:'ok',row_count:2},nazk:{status:'ok'}};
 await timers.shift()();assert.equal(timers.length,0);
 assert.equal(elements['#refAmcuRefresh'].disabled,false);
 assert.equal(elements['#refAmcuUploadBtn'].disabled,false);
 assert.deepEqual(loads,['amcu']);assert.deepEqual(toasts,[]);
 status={amcu:{status:'running'},nazk:{status:'running'}};
 await ctx.loadReferencesView();assert.equal(timers.length,2,'each source has independent poll');
 status={amcu:{status:'error',message:'interrupted'},nazk:{status:'ok'}};
 while(timers.length)await timers.shift()();
 assert.equal(Object.keys(ctx.referencePollTimers).length,0);
 assert.equal(elements['#refAmcuRefresh'].disabled,false);
 elements['#refAmcuRefresh'].dataset.roleDisabled='1';
 elements['#refAmcuUploadBtn'].dataset.runtimeDisabled='1';
 await ctx.loadReferenceStatus();
 assert.equal(elements['#refAmcuRefresh'].disabled,true,'poll preserves role denial');
 assert.equal(elements['#refAmcuUploadBtn'].disabled,true,'poll preserves runtime denial');
 console.log('AMCU polling smoke: PASS (reload, independent polls, dedup, terminal state, buttons)');
})().catch(error=>{console.error(error);process.exitCode=1});
