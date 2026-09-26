// Pure application renderer tests. No DB, browser session, API or business writes.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const app = fs.readFileSync(path.join(__dirname, '..', 'app.js'), 'utf8');
const start = app.indexOf('function applicationNazkMarker(');
const end = app.indexOf('\nfunction cell(', start);
assert(start >= 0 && end > start);
const context = vm.createContext({});
vm.runInContext(app.slice(start, end), context);
let cases = 0;
for (const historicalReadOnly of [false, true]) {
  for (const decision of ['Відхилено', 'Очікує рішення', 'Допущено']) {
    for (const protocolDecision of ['', 'reject']) {
      for (const [nazkPresentationState, label] of [
        ['', ''], ['not_required', ''], ['not_current', ''], ['possible', ''],
        ['needs_check', 'НАЗК · перевірити довідку'],
        ['refuted', 'НАЗК · Спростовано'], ['confirmed', 'НАЗК · підтверджено'],
      ]) {
        const row = Object.freeze({historicalReadOnly, decision, protocolDecision, nazkPresentationState});
        const before = JSON.stringify(row), html = context.applicationNazkMarker(row);
        assert(!html.includes('Не актуально'));
        assert.equal(html.replace(/<[^>]+>/g, ''), label);
        const actionable = nazkPresentationState === 'needs_check' && !historicalReadOnly
          && decision !== 'Відхилено' && protocolDecision !== 'reject';
        assert.equal(html.includes('<button'), actionable);
        assert.equal(JSON.stringify(row), before);
        cases++;
      }
    }
  }
}
// The participant cell must actually call the tested helper.
assert(app.includes("if(col.key==='participant'){const nazkMarker=applicationNazkMarker(row),amcuBlocked="));
assert(app.includes('Постачальник наявний в реєстрі АМКУ · рішення лише «Ні»'));
assert(app.includes("pending&&r.amcuMatch?'registry-risk-amcu'"));
assert(app.includes("protocolDecisions.filter(([value])=>!row.amcuMatch||value!=='admit')"));
assert(app.includes("marketplaceDecisions.filter(([value])=>!row.amcuMatch||value!=='admit')"));
console.log(`PASS: ${cases} application marker cases; no pseudo-NAZK rejection badge or mutations`);
