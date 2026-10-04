const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.join(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'app.js'), 'utf8');
const css = fs.readFileSync(path.join(root, 'styles.css'), 'utf8');
const backend = fs.readFileSync(path.join(root, 'server.py'), 'utf8');
const start = source.indexOf('function violationHasCompleteRejection(context={})');
const end = source.indexOf('bindViolationReview=function(item){const status=', start);
assert.ok(start >= 0 && end > start);
const context = {
  document: {documentElement: {dataset: {pqmEnvironment: 'sandbox'}}},
  esc: value => String(value ?? ''),
  displayDate: value => String(value ?? ''),
  displayDateOnly: value => String(value ?? ''),
  violationOfficerOptions: () => '<option value="">УО</option>',
  internalDecisionLabels: {warning: 'Попередження', decline: 'Відмова'},
};
vm.runInNewContext(source.slice(start, end), context);
const item = {
  reason: 'signingRefusal',
  date_created: '2026-09-25T15:15:31+03:00',
  procurement_context: {
    winner_selected_at: '2026-09-24T10:00:00+03:00',
    written_refusal_deadline: '2026-09-28',
    day_3: '2026-09-27', day_3_weekday_uk: 'неділя', day_3_shifted: true,
    rejection_date: '2026-09-29T09:20:17+03:00',
    rejection_title: 'Довга підстава відхилення '.repeat(30),
    winner_chronology_mismatch: true,
  },
  review: {
    written_refusal_date: '2026-09-24',
    written_refusal_number: '24', written_refusal_url: 'https://example.test/refusal',
  },
};
const html = context.violationReasonFields(item);
const row = html.match(/<div class="violation-p2-chronology-row">([\s\S]*?)<\/div><div class="violation-p2-rejection-ground">/);
assert.ok(row, 'chronology and rejection ground are separate sibling blocks');
const labels = [...row[1].matchAll(/<small>([^<]+)<\/small><strong>/g)].map(match => match[1]);
assert.deepEqual(labels, [
  'Дата визначення переможцем',
  'Граничний строк письмової відмови',
  'Дата письмової відмови',
  'Дата відхилення',
]);
assert.ok(!row[1].includes('Підстава відхилення'));
assert.ok(html.includes(`<div class="violation-p2-rejection-ground"><small>Підстава відхилення</small><strong>${item.procurement_context.rejection_title}</strong>`));
assert.ok(!html.includes('Дата звернення замовника'));
assert.ok(!html.includes('Дата визначення переможцем не збігається'));
assert.ok(!html.includes(item.date_created));
assert.ok(html.includes('2026-09-28'));
assert.ok(html.includes('2026-09-27'));
assert.ok(html.includes('2026-09-24'));
for (const field of ['written_refusal_date', 'written_refusal_number', 'written_refusal_url']) {
  assert.equal(html.split(`data-review="${field}"`).length - 1, 1, `${field} remains editable once`);
}
assert.ok(html.indexOf('violation-p2-rejection-ground') < html.indexOf('violation-written-refusal'));
assert.match(css, /\.violation-p2-chronology-row\{display:grid;grid-template-columns:repeat\(4,minmax\(0,1fr\)\)/);
assert.match(css, /@media\(max-width:900px\)\{\.violation-p2-chronology-row\{grid-template-columns:repeat\(2,minmax\(0,1fr\)\)/);
assert.match(css, /@media\(max-width:560px\)\{\.violation-p2-chronology-row\{grid-template-columns:minmax\(0,1fr\)/);
assert.doesNotMatch(backend, /winner_chronology_mismatch/);

const absent = context.violationReasonFields({...item, procurement_context: {
  ...item.procurement_context, rejection_date: null, rejection_title: null,
}});
assert.ok(absent.includes('<small>Дата відхилення</small><strong>—</strong>'));
assert.ok(absent.includes('<small>Підстава відхилення</small><strong>—</strong>'));
const p1 = context.violationReasonFields({...item, reason: 'contractBreach'});
assert.ok(!p1.includes('Дата визначення переможцем не збігається'));
console.log('APPEALS_P2_CHRONOLOGY_UI=PASS');
