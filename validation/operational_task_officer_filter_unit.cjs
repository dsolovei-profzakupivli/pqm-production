const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('app.js','utf8');
const start=source.indexOf('function renderOperationalTaskOfficers(');
const end=source.indexOf("$('#operationalTaskTypes').onclick",start);
assert.notEqual(start,-1,'officer option renderer exists');
assert.notEqual(end,-1,'officer renderer has a bounded source block');
const select={value:'7',innerHTML:''};
const context={$:selector=>selector==='#operationalTaskOfficer'?select:null,esc:value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))};
vm.createContext(context);
vm.runInContext(source.slice(start,end),context);
context.renderOperationalTaskOfficers([
  {value:'42',full_name:'Повне Ім’я Прізвище'},
  {value:'__legacy_snapshot__:Олена Коваль',full_name:'Олена Коваль',historical_snapshot:true}
]);
assert.equal(select.value,'7','current selection survives refreshed options');
assert.match(select.innerHTML,/Повне Ім’я Прізвище/);
assert.match(select.innerHTML,/Олена Коваль · Історична УО/);
assert.match(select.innerHTML,/Не призначено/);
assert.match(select.innerHTML,/value="7"[^>]*>Вибрану УО не знайдено/);
select.value='__unassigned__';
context.renderOperationalTaskOfficers([{value:'42',full_name:'Повне Ім’я Прізвище'}]);
assert.equal(select.value,'__unassigned__','unassigned selection also survives refresh');
console.log('operational officer option renderer: PASS');
