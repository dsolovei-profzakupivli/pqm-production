const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const policy=fs.readFileSync('halloween_season.js','utf8'),ui=fs.readFileSync('halloween.js','utf8');
const c={};vm.createContext(c);vm.runInContext(policy,c);
const cases=[
 ['2026-09-30T20:59:59.999Z',false,'2026-09-30T21:00:00.000Z'],
 ['2026-09-30T21:00:00Z',true,'2026-10-31T22:00:00.000Z'],
 ['2026-10-25T00:59:59Z',true,'2026-10-31T22:00:00.000Z'],
 ['2026-10-25T01:00:00Z',true,'2026-10-31T22:00:00.000Z'],
 ['2026-10-31T21:59:59.999Z',true,'2026-10-31T22:00:00.000Z'],
 ['2026-10-31T22:00:00Z',false,'2027-09-30T21:00:00.000Z'],
 ['2027-09-30T20:59:59.999Z',false,'2027-09-30T21:00:00.000Z'],
 ['2027-09-30T21:00:00Z',true,'2027-10-31T22:00:00.000Z'],
 ['2026-12-31T23:00:00Z',false,'2027-09-30T21:00:00.000Z']
];
for(const tz of ['UTC','America/Los_Angeles','Asia/Tokyo','Europe/Kyiv']){
 process.env.TZ=tz;
 for(const [date,available,next]of cases){const s=c.PqmHalloweenSeason.state(new Date(date));assert.equal(s.available,available,date);assert.equal(new Date(s.nextTransitionAt).toISOString(),next);assert.equal(s.timeZone,'Europe/Kyiv')}
}
assert.equal(c.PqmHalloweenSeason.state(new Date('invalid')).available,false);
function fixture(start,stored='1'){
 let now=Date.parse(start),serial=0;const timers=new Map(),listeners={},storage=new Map([['pqm.halloween.cat.enabled.v1',stored]]);
 const input={checked:false,disabled:false,addEventListener:(name,fn)=>listeners['input:'+name]=fn};
 const hint={textContent:''},label={querySelector:s=>s==='input'?input:hint};
 const title={classList:{add(){}},insertAdjacentHTML(){}},form={querySelector:()=>({before(){}})};
 const document={documentElement:{dataset:{}},addEventListener:(name,fn)=>listeners[name]=fn,createElement:()=>({...label}),querySelector:s=>s.includes('strong')?title:s==='#accountSettingsForm'?form:null};
 class Clock extends Date{constructor(...args){super(...(args.length?args:[now]))}static now(){return now}}
 const context={Date:Clock,document,window:{addEventListener:(name,fn)=>listeners[name]=fn},localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},setTimeout:(fn,delay)=>{assert(delay>=1&&delay<=60000);timers.set(++serial,{fn,at:now+delay});return serial},clearTimeout:id=>timers.delete(id)};
 vm.createContext(context);vm.runInContext(policy+'\n'+ui,context);
 const advance=ms=>{now+=ms;for(const [id,t]of [...timers])if(t.at<=now){timers.delete(id);t.fn()}};
 const jump=(date,event='focus')=>{now=Date.parse(date);listeners[event]()};
 const change=checked=>{input.checked=checked;listeners['input:change']()};
 return {document,input,hint,timers,storage,listeners,advance,jump,change,on:()=>document.documentElement.dataset.halloween==='on'};
}
const f=fixture('2026-10-31T21:59:59.500Z');assert(f.on());assert.equal(f.timers.size,1);
f.advance(499);assert(f.on());f.advance(1);assert(!f.on());assert(f.input.disabled);assert(!f.input.checked);assert.equal(f.timers.size,1);
f.change(true);assert(!f.on());assert.equal(f.storage.get('pqm.halloween.cat.enabled.v1'),'1');
f.jump('2027-09-30T20:59:59.999Z');assert(!f.on());f.advance(1);assert(f.on());assert(!f.input.disabled);
f.change(false);assert(!f.on());f.jump('2027-10-02T12:00:00Z','visibilitychange');assert(!f.on());
f.change(true);assert(f.on());f.jump('2027-11-01T12:00:00Z','pageshow');assert(!f.on());
f.listeners.pagehide();assert.equal(f.timers.size,0);f.listeners.pageshow();assert.equal(f.timers.size,1);
const pref=fixture('2026-10-31T21:59:59Z','0');pref.advance(1000);pref.jump('2027-10-01T12:00:00Z');assert(!pref.on());assert(!pref.input.disabled);
const off=fixture('2026-09-30T20:59:59.999Z');assert(!off.on());off.advance(1);assert(off.on());
console.log('HALLOWEEN_SEASON=PASS:36 calendar/TZ boundaries, DST, exact timer boundary, preference/disabled guard, resume, annual availability, one timer');
