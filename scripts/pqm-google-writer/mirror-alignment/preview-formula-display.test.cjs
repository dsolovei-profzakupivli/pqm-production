const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

const root=path.resolve(__dirname,'../../../');
const source=fs.readFileSync(path.join(root,'google_writer_ui.js'),'utf8');
const start=source.indexOf('function googleWriterPreviewHasFormula');
const render=source.indexOf('function renderGoogleWriterPreviewDetails',start);
const end=source.indexOf('\nfunction confirmGoogleWriterPreview',render);
assert(start>=0&&render>start&&end>render,'Preview formula renderer functions must exist');

const target={innerHTML:''};
const details={appends:[{tab:'ФОП',name:'=supplier name',code:'000001',cells:[
  {column:'A',old_value:'=OLD()',new_value:'=SUM(A1:A2)',formula:true},
  {column:'B',old_value:'old value',new_value:'new value'},
  {column:'C',old_value:'old',new_value:'new',formula:true},
]}],updates:[],conflicts:[],errors:[]};
const before=JSON.stringify(details);
const context={
  document:{getElementById:id=>id==='googleWriterPreviewDetails'?target:null},
  esc:value=>String(value??'').replace(/[&<>"']/g,char=>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char])),
};
vm.runInNewContext(source.slice(start,end),context,{filename:'google_writer_ui.js'});
context.renderGoogleWriterPreviewDetails(details);

assert(!target.innerHTML.includes('=OLD()'));
assert(!target.innerHTML.includes('=SUM(A1:A2)'));
assert.equal((target.innerHTML.match(/Формула/g)||[]).length,3);
assert(target.innerHTML.includes('=supplier name'),'non-cell labels retain their display');
assert(target.innerHTML.includes('old value</span> → <span'));
assert.equal(JSON.stringify(details),before,'the Preview object must remain unchanged');
console.log('PASS Preview formula text is masked for display only');
