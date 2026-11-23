const test=require('node:test'),assert=require('node:assert/strict');
const api=require('../application_documents_ui.js'),ui=require('../document_check_ui.js');
const one=[{index:0,document:{title:'sign.p7s'}}];
test('only KEP auto-selects; MVS always requires a user choice',()=>{assert.equal(api.initialValue(one,{},'signature'),'0');assert.equal(api.initialValue(one,{},'mvs'),'');});
test('explicit cancellation survives reopening for both categories',()=>{for(const category of ['signature','mvs'])assert.equal(api.initialValue(one,{_explicit:true},category),'');});
test('explicit previous user selection restores with its source index',()=>{for(const category of ['signature','mvs'])assert.equal(api.initialValue(one,{'0':[category],_explicit:true},category),'0');});
test('unchecked category has neutral text without adding counts',()=>{const data={checks:[{key:'eds_verification',status:'ok',detail:'Перевірено'}],counts:{ok:1},document_check_policy_version:2};const before=JSON.stringify(data),html=ui.render(data);assert.match(html,/data-result-category="mvs"><h3>Перевірка витягу МВС<\/h3><p class="muted">Не перевірено/);assert.equal(JSON.stringify(data),before);assert.match(html,/data-result-count="ok">1/);});
