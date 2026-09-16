// Pure rendering fixture: no browser session, API, DB or real person's data.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const app = fs.readFileSync(path.join(__dirname, '..', 'app.js'), 'utf8');
const start = app.indexOf('function supplierNazkEvidenceHtml(');
const end = app.indexOf('\nopenSupplierProfile=', start);
assert(start >= 0 && end > start);
const context = vm.createContext({
  esc: value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;'),
  displayDateOnly: value => String(value ?? '').slice(0, 10),
  frameworkNumber: String,
  operationalNazkStateLabels: {},
});
const noticeStart = app.indexOf('function nazkRegistrySourceNotice(');
assert(noticeStart >= 0 && noticeStart < start);
vm.runInContext(app.slice(noticeStart, start), context);
vm.runInContext(app.slice(start, end), context);
for (const [from, to] of [
  ['function operationalNazkRecords(', '\nfunction operationalNazkWorkspace('],
  ['function operationalNazkHtml(', '\nfunction operationalAmcuHtml('],
]) {
  const first = app.indexOf(from), last = app.indexOf(to, first);
  assert(first >= 0 && last > first);
  vm.runInContext(app.slice(first, last), context);
}
const renderers = {
  supplier: facts => context.supplierNazkEvidenceHtml({id: 112, nazk_evidence: {registry_facts: facts}}),
  task: facts => context.operationalNazkContext({status: 'in_progress', nazk_records: facts}),
  legacyTask: facts => context.operationalNazkHtml({status: 'in_progress', nazk_records: facts}),
};
for (const [name, render] of Object.entries(renderers)) {
  const fact = Object.freeze({source_id: 'fixture', full_name: '<script>unsafe</script>',
    current_registry_present: false, registry_source: 'historical_web_snapshot', evidence_observed_at: '2026-09-13T08:53:12Z'});
  const facts = Object.freeze([fact]);
  const before = JSON.stringify(facts), history = render(facts);
  assert(history.includes('Відсутній у поточному реєстрі НАЗК'), name + ': historical absence label');
  assert(history.includes('2026-09-13'), name + ': observation date');
  assert(history.includes('Це не результат перевірки особи'), name + ': non-factual disclaimer');
  assert(history.includes('&lt;script&gt;') && !history.includes('<script>'), name + ': escaped name');
  assert.equal(JSON.stringify(facts), before, name + ': rendering does not mutate evidence');
  for (const current of [true, undefined]) {
    assert(!render([{source_id: 'current', current_registry_present: current}]).includes('Відсутній у поточному'), name + ': no invented absence');
  }
  const missing = render([{source_id: 'missing', current_registry_present: false, registry_source: 'missing_evidence'}]);
  assert(missing.includes('потребує перевірки') && !missing.includes('WEB-знімок від'), name + ': missing evidence');
  const noDate = render([{...fact, evidence_observed_at: null}]);
  assert(noDate.includes('WEB-знімок від —.'), name + ': no invented observation date');
  const unsafeDate = render([{...fact, evidence_observed_at: '<svg/xss>'}]);
  assert(unsafeDate.includes('&lt;svg/xss&gt;') && !unsafeDate.includes('<svg/xss>'), name + ': escaped observation date');
  const mixed = render([fact, {...fact, source_id: 'current', current_registry_present: true}]);
  assert.equal(mixed.split('Відсутній у поточному реєстрі НАЗК').length - 1, 1, name + ': mixed evidence marks only historical row');
  console.log('PASS: ' + name + ' — historical/current/missing labels, observation date, disclaimer, escaping, no mutation');
}
