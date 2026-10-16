const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('app.js','utf8');
const helper=source.slice(source.indexOf('function protocolSupplierNamesHtml('),source.indexOf('const violationProtocolWorkbench='));
const generate=source.split('\n').find(line=>line.startsWith('async function generateViolationProtocol(item)'));
assert(helper&&generate);
const requests=[],button={textContent:'Сформувати',disabled:false};
const context={esc:s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;'),
  $:()=>button,API:'/api',collectViolationReview:()=>({protocol_number:'1',protocol_date:'2026-10-16'}),
  request:async url=>{requests.push(url);return{}},toast:()=>{},openViolationReportById:async()=>{},unresolvedDeclensionsByReport:new Map()};
vm.createContext(context);vm.runInContext(helper+'\n'+generate,context);
const fields={full_name:{value:'<img src=x onerror=bad()>',source_label:'Зі звернення Prozorro'},
  short_name:{value:'Коротка ЄДР',source_label:'З ЄДР (збережені дані PQM)'},
  filename_name:{value:'Назва зі звернення',source_label:'Зі звернення Prozorro'},uses_fallback:true};
context.item={id:'fixture',protocol_readiness:{ready:true},protocol_supplier_names:fields};
const html=vm.runInContext('protocolSupplierNamesHtml(item)',context);
assert(html.includes('Зі звернення Prozorro'));assert(html.includes('Коротка ЄДР'));
assert(html.includes('&lt;img'));assert(!html.includes('<img'));assert(!html.includes('disabled'));
assert.equal((html.match(/<dt>/g)||[]).length,3);
assert.equal(vm.runInContext('protocolSupplierNamesHtml({...item,is_read_only:true})',context),'');
const controls=source.split('\n').find(line=>line.startsWith('requestContextBlock=function(item){const html=violationProtocolWorkbench'));
assert(controls.indexOf('${protocolSupplierNamesHtml(item)}')<controls.indexOf('id="generateViolationProtocol"'));
(async()=>{await vm.runInContext('generateViolationProtocol(item)',context);
  assert.deepEqual(requests,['/api/violation-reports/fixture/review','/api/violation-reports/fixture/protocol/generate']);
  assert.equal(button.disabled,false);console.log('PROTOCOL_NAME_PROVENANCE_UI=PASS');
})().catch(e=>{console.error(e);process.exitCode=1});
