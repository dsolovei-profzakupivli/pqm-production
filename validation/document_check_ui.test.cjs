const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const ui=require('../document_check_ui.js');
const check=(key,status='ok')=>({key,label:key,status,detail:'Evidence '+key});
test('A and B use identical evidence with only alignment changed',()=>{
 const data={checks:[check('signer'),check('mvs_criminal_liability'),check('mvs_unspent_conviction'),check('mvs_wanted_status')],counts:{ok:4}},before=JSON.stringify(data);
 const a=ui.render(data,{layout:'a'}),b=ui.render(data,{layout:'b'});
 assert.equal(a.replace('data-result-layout="a"','data-result-layout="b"'),b);
 for(const label of ['Притягнення','Судимість','Розшук'])assert(a.includes('>'+label+'</strong>'));
 assert.equal(JSON.stringify(data),before);
});
test('successful KEP values are concise; failures retain their explanation',()=>{
 const data={signature:{code:'12345678',signer:'ІВАНЕНКО ІВАН ІВАНОВИЧ',organization:'ТОВ «Тест»'}};
 for(const [key,value] of [['eds_verification','Перевірено'],['code','12345678'],['signer','ІВАНЕНКО ІВАН ІВАНОВИЧ'],['organization','ТОВ «Тест»']])assert.equal(ui.displayValue(check(key),data),value);
 for(const key of ['eds_verification','code','signer'])assert.equal(ui.displayValue({...check(key,'warning'),detail:'Не вдалося прочитати; перевірте файл'},data),'Не вдалося прочитати; перевірте файл');
});
test('MVS displays source values, never infers absent from status or missing data',()=>{
 const data={mvs_extract:{person_name:'ІВАНЕНКО ІВАН ІВАНОВИЧ',age_days:12,criminal_liability:{found:true,value:'ВІДСУТНІ'},unspent_conviction:{found:true,value:'НАЯВНІ'},wanted_status:{found:false,value:''}}};
 assert.equal(ui.displayValue(check('mvs_person'),data),'ІВАНЕНКО ІВАН ІВАНОВИЧ');assert.equal(ui.displayValue(check('mvs_age'),data),'12 к.д.');
 assert.equal(ui.displayValue(check('mvs_criminal_liability'),data),'ВІДСУТНІ');assert.equal(ui.displayValue(check('mvs_unspent_conviction','error'),data),'НАЯВНІ');
 assert.equal(ui.displayValue({...check('mvs_wanted_status','warning'),detail:'Не вдалося прочитати відповідний рядок у витягу'},data),'Не вдалося прочитати відповідний рядок у витягу');
 assert.equal(ui.displayValue({...check('mvs_age'),detail:'0 к.д. · 2026-11-21 → 2026-11-21'},{}),'0 к.д.');
 assert.equal(ui.displayValue({...check('contract_experience'),detail:'+ · Знайдено: 2'},{}),'Знайдено: 2');
});
test('experience icon depends on candidate evidence, never verdict severity',()=>{
 for(const status of ['ok','warning','error','neutral'])for(const found of [true,false]){
  const html=ui.render({checks:[{...check('contract_experience',status),search_status:found?'found':'none'}]});
  assert(html.includes(`data-experience-state="${found?'found':'none'}"`));assert(html.includes(`aria-hidden="true">${found?'+':'−'}</i>`));
 }
});
test('new registry rollup excludes seal and maps experience; legacy remains intact',()=>{
 const data={category_results:{mvs:{status:'warning',checks:[check('mvs_extract'),check('mvs_seal','warning')]},experience:{status:'neutral',checks:[{...check('contract_experience','neutral'),search_status:'found'}]}}},before=JSON.stringify(data);
 assert.deepEqual(ui.categoryStatuses(data),{mvs:'warning',experience:'ok'});
 assert.deepEqual(ui.categoryStatuses({...data,document_check_policy_version:2}),{mvs:'ok',experience:'ok'});
 assert.equal(JSON.stringify(data),before);
 for(const status of ['error','warning','ok','neutral'])assert.equal(ui.categoryStatuses({document_check_policy_version:2,category_results:{mvs:{checks:[check('mvs_extract',status),check('mvs_seal','error')]}}}).mvs,status);
});
test('KEP exact grid positions and spans',()=>{
 assert.deepEqual(ui.layouts.signature,[['main_signature',1,1,1],['eds_verification',1,2,1],['signing_time',1,3,1],['code',2,1,1],['organization',2,2,2],['signer_drfo',3,1,1],['signer',3,2,2],['authority',4,1,1],['certificate_issuer',4,2,2]]);
});
test('MVS exact grid positions and spans',()=>{
 assert.deepEqual(ui.layouts.mvs,[['mvs_extract',1,1,1],['mvs_extract_type',1,2,1],['mvs_age',1,3,1],['mvs_person',2,1,3],['mvs_criminal_liability',3,1,1],['mvs_unspent_conviction',3,2,1],['mvs_wanted_status',3,3,1]]);
});
test('saved counters are used verbatim, including legacy seal counters',()=>{
 const html=ui.render({checks:[check('mvs_seal','warning')],counts:{ok:16,warning:1,error:2}});
 for(const [status,n] of [['ok',16],['warning',1],['error',2]])assert(html.includes(`data-result-count="${status}">${n}</b>`));
 assert(html.includes('data-check-key="mvs_seal"'));assert(html.includes('data-check-status="warning"'));
});
test('new policy totals may exclude a preserved historical seal without discarding evidence',()=>{
 const html=ui.render({document_check_policy_version:2,checks:[check('signer'),check('mvs_seal','warning')],counts:{ok:1,warning:0,error:0}});
 assert(html.includes('data-result-count="warning">0</b>'));assert(html.includes('data-check-key="mvs_seal"'));
 assert(html.includes('не входить до підсумку нової перевірки'));
});
test('supplied severities and informational evidence remain unchanged',()=>{
 const checks=[check('code','warning'),check('mvs_age','error'),{...check('organization'),informational:true}];
 const html=ui.render({checks,counts:{ok:1,warning:1,error:1}});
 for(const c of checks)assert(html.includes(`data-check-key="${c.key}" data-check-status="${c.status}"`));
 assert(html.includes('informational'));assert(!html.includes('data-check-key="mvs_seal"'));
});
test('experience stays after KEP and MVS; existing link renderer is preserved',()=>{
 const html=ui.render({checks:[check('contract_experience','neutral'),check('mvs_extract'),check('main_signature')],counts:{ok:2}}, {renderBusinessRows:item=>item.key==='contract_experience'?'<a href="/existing">Existing link</a>':''});
 assert(html.indexOf('data-result-category="signature"')<html.indexOf('data-result-category="mvs"'));
 assert(html.indexOf('data-result-category="mvs"')<html.indexOf('data-result-category="experience"'));assert(html.includes('<a href="/existing">Existing link</a>'));
});
test('unknown historical fields are not silently discarded; input is not mutated',()=>{
 const data={checks:[check('legacy_signature_field'),check('mvs_old_field')],counts:{warning:7}},before=JSON.stringify(data);
 const html=ui.render(data);assert(html.includes('legacy_signature_field'));assert(html.includes('mvs_old_field'));assert.equal(JSON.stringify(data),before);
});
test('untrusted evidence is escaped and cannot add markup or attributes',()=>{
 const html=ui.render({checks:[{key:'signer',label:'<script>',detail:'<img onerror="oops">',status:'error'}],counts:{error:1}});
 assert(!html.includes('<script>'));assert(!html.includes('<img onerror='));assert(html.includes('&lt;script&gt;'));
});
test('UI002 styles preserve link colors while allowing the approved inline experience layout',()=>{
 const css=fs.readFileSync(path.join(__dirname,'../document_check_ui.css'),'utf8');
 assert(!/#officialSignatureCheck|\.button-link/.test(css));
 for(const rule of css.matchAll(/([^{}]+)\{([^{}]*)\}/g))if(/\.contract-experience-links a(?:\s|>|\{|$)/.test(rule[1])&&!/contract-date|contract-time|contract-buyer/.test(rule[1]))assert(!/(?:^|;)\s*(?:color|background)\s*:/.test(rule[2]));
 assert(css.includes('height:auto'));assert(css.includes('grid-template-columns:repeat(3,minmax(0,1fr))'));
});
