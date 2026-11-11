/* Node-only UI flow regression tests; mocked DOM and API, no Playwright. */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');

class Element {
  constructor(id=''){this.id=id;this.open=false;this.disabled=false;this.hidden=false;this.textContent='';this.title='';this.value='';this.dataset={};this.listeners={};this.children=[];this.returnValue='';}
  addEventListener(type,fn,options={}){(this.listeners[type]??=[]).push({fn,once:!!options.once});}
  removeEventListener(type,fn){this.listeners[type]=(this.listeners[type]||[]).filter(x=>x.fn!==fn);}
  dispatchEvent(event){event.target??=this;for(const item of [...(this.listeners[event.type]||[])]){item.fn.call(this,event);if(item.once)this.removeEventListener(event.type,item.fn);}return true;}
  click(){if(this.disabled)return;if(this.onclick)this.onclick({target:this});this.dispatchEvent({type:'click',target:this});}
  showModal(){this.open=true;}
  close(value=''){this.returnValue=value;this.open=false;this.dispatchEvent({type:'close',target:this});}
  append(child){this.children.push(child);}
  querySelectorAll(){return [];}
  set innerHTML(value){this._html=value;this.textContent=String(value).replace(/<[^>]*>/g,' ');}
  get innerHTML(){return this._html||'';}
}

const root=path.resolve(__dirname,'..');
const source=fs.readFileSync(path.join(root,'google_writer_ui.js'),'utf8');
const server=fs.readFileSync(path.join(root,'server.py'),'utf8');
const index=fs.readFileSync(path.join(root,'index.html'),'utf8');
const dialogMarkup=index.match(/<dialog id="googleWriterPreviewDialog"[\s\S]*?<\/dialog>/)?.[0];
assert(dialogMarkup,'Preview dialog must be present in index.html');
const ids=[...new Set([...dialogMarkup.matchAll(/id="([^"]+)"/g)].map(match=>match[1]))];

function makeApp(mode){
  const elements=new Map(ids.map(id=>[id,new Element(id)]));
  elements.set('pqmGoogleWriterRun',new Element('pqmGoogleWriterRun'));
  elements.set('pqmGoogleWriterMessage',new Element('pqmGoogleWriterMessage'));
  elements.set('schedulerJobs',new Element('schedulerJobs'));
  const calls=[],notices=[];let applyCount=0,scopeCount=0;
  const original={append:276,update:2,conflict:2,error:0},latest={append:275,update:2,conflict:1,error:0};
  const details=(digest,counts,name)=>({version:1,environment:'SANDBOX',plan_digest:digest,counts,
    appends:[{tab:'ФОП',name,code:'000001',cells:[]}],updates:[],conflicts:[],errors:[]});
  const document={
    getElementById:id=>elements.get(id)||null,
    createElement:tag=>new Element(tag),
  };
  const app={
    document,console,crypto:{randomUUID:()=> 'a'.repeat(32)},setInterval:()=>1,clearInterval:()=>{},
    API:'/api',calls,notices,googleWriterBusy:false,
    esc:value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char])),
    displayDate:value=>String(value??''),toast:(message,type)=>notices.push({message,type}),
  };
  app.window=app;
  app.request=async(url,options={})=>{
    const body=options.body?JSON.parse(options.body):{};calls.push({url,method:options.method||'GET',body});
    if(url.endsWith('/google-writer/status'))return{can_execute:true,channel_ready:true,blocked:false,automation_blocked:true,
      configured_enabled:false,schedule:'07:00',last_status:'never',hour:7,minute:0,runs:[]};
    if(url.endsWith('/google-writer/preview'))return{ticket:'initial-ticket',plan_digest:'P'.repeat(43),details_digest:'D'.repeat(43),counts:original};
    if(url.includes('/google-writer/preview-details/'))return url.includes('bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb')?
      {details_digest:'E'.repeat(43),details:details('N'.repeat(43),latest,'latest-preview-row')}:
      {details_digest:'D'.repeat(43),details:details('P'.repeat(43),original,'original-preview-row')};
    if(url.endsWith('/google-writer/preview-scope')){
      scopeCount++;
      if(mode==='scope-error')throw Object.assign(new Error('scope fixture rejected'),{httpStatus:403});
      const current=body.ticket==='latest-ticket';
      return{scope:'APPEND_ONLY',counts:{...(current?latest:original),update:0},ticket:current?'latest-append-ticket':'initial-append-ticket'};
    }
    if(url.endsWith('/google-writer/apply')){
      applyCount++;
      if(mode==='stale'&&applyCount===1)throw Object.assign(new Error('stale plan'),{httpStatus:409,status:'PREVIEW_STALE_RECONFIRM',started:false,
        request_id:'b'.repeat(32),ticket:'latest-ticket',plan_digest:'N'.repeat(43),details_digest:'E'.repeat(43),counts:latest});
      if(mode==='apply-error')throw Object.assign(new Error('claim denied'),{httpStatus:409});
      const current=body.ticket==='latest-append-ticket';
      return{started:true,request_id:current?'b'.repeat(32):'a'.repeat(32),status:'running',
        counts:current?{append:275,update:0,conflict:1}:{append:276,update:0,conflict:2}};
    }
    throw new Error('Unexpected mock request: '+url);
  };
  vm.createContext(app);vm.runInContext(source,app,{filename:'google_writer_ui.js'});
  return {app,elements,calls,notices,get applyCount(){return applyCount},get scopeCount(){return scopeCount}};
}

async function waitFor(test,label){for(let i=0;i<300;i++){if(test())return;await new Promise(resolve=>setTimeout(resolve,5));}throw new Error('Timed out: '+label);}
async function openPreview(fixture){const run=fixture.elements.get('pqmGoogleWriterRun');await waitFor(()=>fixture.elements.get('pqmGoogleWriterMessage').textContent!=='','status loaded');await waitFor(()=>!run.disabled,'run enabled');run.click();await waitFor(()=>fixture.elements.get('googleWriterPreviewDialog').open,'preview opened; '+JSON.stringify(fixture.calls)+'; message='+fixture.elements.get('pqmGoogleWriterMessage').textContent);}
async function main(){
  assert.match(server,/['"]request_id['"]\s*:\s*replacement_id[\s\S]{0,180}['"]counts['"]\s*:\s*replacement\.get\(['"]counts['"]\s*,\s*\{\}\)/,
    'stale response must identify the frozen replacement Preview needed by the UI');
  const stale=makeApp('stale');await openPreview(stale);stale.elements.get('googleWriterPreviewAppendOnly').click();
  await waitFor(()=>stale.elements.get('googleWriterPreviewDialog').open&&stale.elements.get('googleWriterPreviewNotice').textContent.includes('Попередній план застарів'),'replacement Preview reopened');
  assert.match(stale.elements.get('googleWriterPreviewDetails').textContent,/latest-preview-row/);
  assert.equal(stale.elements.get('googleWriterPreviewAppend').textContent,'275');
  assert.match(stale.elements.get('googleWriterPreviewNotice').textContent,/Запис не розпочато/);
  stale.elements.get('googleWriterPreviewAppendOnly').click();
  await waitFor(()=>!stale.elements.get('googleWriterPreviewDialog').open&&!stale.elements.get('pqmGoogleWriterRun').disabled,'replacement confirmed');
  assert.equal(stale.applyCount,2);assert.equal(stale.scopeCount,2);
  assert(stale.notices.some(n=>n.type==='success'&&/b{32}/.test(n.message)&&/статус running/.test(n.message)&&/APPEND 275/.test(n.message)));

  const scopeFailure=makeApp('scope-error');await openPreview(scopeFailure);scopeFailure.elements.get('googleWriterPreviewAppendOnly').click();
  await waitFor(()=>!scopeFailure.elements.get('pqmGoogleWriterRun').disabled,'scope error handled');
  assert.equal(scopeFailure.applyCount,0);
  assert(scopeFailure.notices.some(n=>n.type==='error'&&n.message.includes('Apply не надсилався')&&n.message.includes('запис не розпочато')));

  const applyFailure=makeApp('apply-error');await openPreview(applyFailure);applyFailure.elements.get('googleWriterPreviewApply').click();
  await waitFor(()=>!applyFailure.elements.get('pqmGoogleWriterRun').disabled,'apply error handled');
  assert(applyFailure.notices.some(n=>n.type==='error'&&n.message.includes('Apply відхилено (HTTP 409)')&&n.message.includes('перевірте журнал')));

  console.log('PASS: stale 409 refreshes and reopens the bound Preview for explicit confirmation; scope/apply failures explain whether a run was accepted; 202 success shows run ID, status and counts');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
