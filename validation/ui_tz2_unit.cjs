const assert=require('assert'),fs=require('fs'),vm=require('vm');
const {PqmAuditSearch}=require('../audit_search.js');
(async()=>{
  let value='A',active=0,maximum=0,clears=0;const waiting=[],calls=[],renders=[],errors=[];
  const controller=PqmAuditSearch.create({clientId:'test-client',params:()=>new URLSearchParams({search:value}),clear:()=>clears++,render:x=>renders.push(x),error:x=>errors.push(x),request:q=>{
    calls.push(new URLSearchParams(q));if(q.get('cancel'))return Promise.resolve({cancelled:true});
    active++;maximum=Math.max(maximum,active);return new Promise((resolve,reject)=>waiting.push({resolve:x=>{active--;resolve(x)},reject:e=>{active--;reject(e)}}));
  }});
  const first=controller.load();controller.invalidate();value='B';const second=controller.load();value='C';const third=controller.load();
  assert.equal(calls.filter(q=>!q.has('cancel')).length,1);assert.equal(calls.filter(q=>q.has('cancel')).length,1);
  waiting[0].reject(new Error('stale failure'));await first;await second;await new Promise(resolve=>setImmediate(resolve));
  assert.equal(calls.filter(q=>!q.has('cancel')).length,2);assert.equal(calls.at(-1).get('search'),'C');
  waiting[1].resolve({current:'C'});await third;
  assert.deepEqual(renders,[{current:'C'}]);assert.equal(errors.length,0);assert.equal(maximum,1);
  value='D';const failure=controller.load();waiting[2].reject(new Error('resource'));await failure;
  assert.equal(errors.length,1);assert.ok(clears>=4);
  const app=fs.readFileSync('app.js','utf8');const context={esc:s=>String(s??'').replaceAll('<','&lt;'),displayDateOnly:x=>x};vm.createContext(context);
  vm.runInContext(app.split(/\r?\n/).find(x=>x.startsWith('function violationProtocolCell(')),context);
  assert.equal(context.violationProtocolCell({},0),'');
  const item={protocol_summary:{number:'17',date:'2026-10-17',url:'/api/protocol/files/new.docx',officer:'Історична УО',askod:'Стислий опис',json_ready:false}};
  const before=context.violationProtocolCell(item,0);assert.match(before,/Історична УО/);assert.match(before,/АСКОД/);assert.doesNotMatch(before,/JSON/);
  item.protocol_summary.json_ready=true;assert.match(context.violationProtocolCell(item,0),/JSON/);
  item.protocol_summary.officer='';assert.doesNotMatch(context.violationProtocolCell(item,0),/Історична УО/);
  const boot=fs.readFileSync('ui_improvements_boot.js','utf8');assert.doesNotMatch(boot,/#requestsNav \.action-count-badge/);
  const position=fs.readFileSync('working_modal_drag.js','utf8').split(/\r?\n/).find(line=>line.trim().startsWith('const position='));
  for(const bounded of [false,true])for(const zoom of [1,1.25])for(const x of [-200,300,2000])for(const y of [-200,300,2000]){
    const target={style:{},dataset:{keepViewport:String(bounded)},getBoundingClientRect:()=>({width:600,height:500})};
    const ctx={target,innerWidth:1280,innerHeight:720,document:{body:{}},getComputedStyle:()=>({zoom}),Math,Number};vm.createContext(ctx);vm.runInContext(position+';position('+x+','+y+')',ctx);
    const scale=bounded?zoom:1;
    assert.equal(parseFloat(target.style.left)*scale,Math.max(8,Math.min(x,1280-600-8)));
    assert.equal(parseFloat(target.style.top)*scale,Math.max(8,Math.min(y,720-(bounded?500:80)-12)));
  }
  console.log('UI_TZ2_UNIT=PASS; single-flight/coalescing/cancel/stale/error/protocol phases');
})().catch(error=>{console.error(error);process.exit(1)});
