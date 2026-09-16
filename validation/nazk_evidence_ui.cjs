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
});
vm.runInContext(app.slice(start, end), context);
const render = facts => context.supplierNazkEvidenceHtml({id: 112, nazk_evidence: {registry_facts: facts}});
const history = render([{source_id: 'fixture', full_name: '<script>unsafe</script>',
  current_registry_present: false, registry_source: 'historical_web_snapshot', evidence_observed_at: '2026-09-13T08:53:12Z'}]);
assert(history.includes('Відсутній у поточному реєстрі НАЗК'));
assert(history.includes('2026-09-13'));
assert(history.includes('Це не результат перевірки особи'));
assert(history.includes('&lt;script&gt;'));
assert(!history.includes('<script>'));
assert(!render([{source_id: 'current', current_registry_present: true}]).includes('Відсутній у поточному'));
assert(render([{source_id: 'missing', current_registry_present: false, registry_source: 'missing_evidence'}]).includes('потребує перевірки'));
console.log('PASS: historical/current labels, observation date, no factual assertion, escaped values');
