const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('operational_task_officers.js', 'utf8');
const options = [];
const select = {
  value: '7',
  replaceChildren(...children) { options.splice(0, options.length, ...children); },
  get options() { return options; }
};
const pending = [];
const window = {
  request(url) {
    return new Promise((resolve, reject) => pending.push({ url, resolve, reject }));
  }
};
const context = {
  window,
  document: {
    querySelector: selector => selector === '#operationalTaskOfficer' ? select : null,
    createElement: tag => ({ tag, value: '', textContent: '' })
  }
};
vm.createContext(context);
vm.runInContext(source, context);
const installed = window.request;
vm.runInContext(source, context);
assert.equal(window.request, installed, 'module installation is idempotent');

const older = window.request('/api/operational-tasks?status_group=active');
const newer = window.request('/api/operational-tasks?status_group=completed');
const latestOfficers = [
  { value: '42', full_name: 'Ірина Мельник' },
  { value: '7', full_name: 'Оксана Петренко', historical_snapshot: true },
  { value: '__legacy_snapshot__:Олена Коваль', full_name: 'Олена Коваль', historical_snapshot: true }
];
pending[1].resolve({ officers: latestOfficers, marker: 'newer' });
pending[0].resolve({ officers: [{ value: '99', full_name: 'Застаріла відповідь' }], marker: 'older' });
Promise.all([older, newer]).then(async () => {
  assert.deepEqual(options.map(option => [option.value, option.textContent]), [
    ['', 'Усі УО'],
    ['42', 'Ірина Мельник'],
    ['7', 'Оксана Петренко · Історична УО'],
    ['__legacy_snapshot__:Олена Коваль', 'Олена Коваль · Історична УО'],
    ['__unassigned__', 'Не призначено']
  ]);
  assert.equal(select.value, '7', 'selected officer survives refresh');

  select.value = '__unassigned__';
  const refresh = window.request('/api/operational-tasks?officer=__unassigned__');
  pending[2].resolve({ officers: latestOfficers });
  await refresh;
  assert.equal(select.value, '__unassigned__', 'unassigned selection survives refresh');

  const before = pending.length;
  const detail = window.request('/api/operational-tasks/0123456789abcdef0123456789abcdef');
  assert.equal(pending.length, before + 1, 'detail calls pass through once without option refresh logic');
  pending[3].resolve({ officers: [{ value: '100', full_name: 'Detail is not a list' }] });
  await detail;
  assert.equal(select.options.some(option => option.value === '100'), false, 'detail response does not rewrite list options');
  assert.equal(typeof window.request, 'function');
  console.log('operational task officer module: PASS (idempotence, stale-response guard, selection retention, history, unassigned)');
}).catch(error => { console.error(error); process.exitCode = 1; });
