const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'app.js'), 'utf8');
const start = source.indexOf('function violationHasCompleteRejection(context={})');
const end = source.indexOf('bindViolationReview=function(item){const status=', start);
assert.ok(start >= 0 && end > start, 'scenario review renderer is present');
const context = {
  document: {documentElement: {dataset: {pqmEnvironment: 'sandbox'}}},
  esc: value => String(value ?? ''),
  displayDate: value => String(value ?? ''),
  displayDateOnly: value => String(value ?? ''),
  violationOfficerOptions: () => '<option value="">УО</option>',
  internalDecisionLabels: {warning: 'Попередження', decline: 'Відмова'},
};
vm.runInNewContext(source.slice(start, end), context);

const contractFields = [
  'actual_contract_signed', 'actual_contract_date',
  'actual_contract_number', 'actual_contract_url',
];
function render(reason, required, extra = {}) {
  return context.requestContextBlock({
    reason,
    procurement_context: {available: true, contract_info_required: required,
      winner_selected_at: '2026-09-01', ...extra.procurement_context},
    review: {actual_contract_signed: true, actual_contract_date: '2026-09-02',
      actual_contract_number: 'MANUAL-77', actual_contract_url: 'https://example.test/77',
      contract_deadline_extended: true, ...extra.review},
    deadline_control: {supplier_ready: true},
  });
}
function check(reason, required, extension, extra = {}) {
  const html = render(reason, required, extra);
  for (const field of contractFields) {
    const occurrences = html.split(`data-review="${field}"`).length - 1;
    assert.equal(occurrences, required ? 1 : 0, `${reason}: ${field} visibility`);
  }
  assert.equal(html.includes('data-review="contract_deadline_extended"'),
    extension, `${reason}: extension visibility`);
  return html;
}

check('contractBreach', true, true);
check('contractBreach', true, true, {procurement_context: {
  rejection_date: '2026-09-03', rejection_title: 'Інше відхилення'}});
check('contractBreach', false, true, {procurement_context: {
  rejection_date: '2026-09-03', rejection_title: 'Не підписано договір'}});
check('signingRefusal', true, false);
check('signingRefusal', false, false);
check('goodsNonCompliance', true, false);
check('goodsNonCompliance', false, false);
check('other', true, false);
check('other', false, false);
const unavailable = render('contractBreach', true, {procurement_context: {available: false}});
for (const field of [...contractFields, 'contract_deadline_extended'])
  assert.equal(unavailable.includes(`data-review="${field}"`), false,
    `unavailable context hides ${field}`);
assert.ok(check('signingRefusal', true, false).includes('data-review="written_refusal_date"'));
assert.ok(check('goodsNonCompliance', true, false).includes('data-review="court_decision_final_present"'));
assert.equal(check('contractBreach', true, true).includes(
  'data-review="guarantee_documents_visible"'), false,
  'guarantee control is hidden without a guarantee requirement');
assert.equal(check('contractBreach', true, true, {procurement_context: {
  contract_guarantee_required: true}}).includes(
  'data-review="guarantee_documents_visible"'), true,
  'guarantee control remains visible when required');
context.document.documentElement.dataset.pqmEnvironment = 'production';
assert.equal(render('contractBreach', true).includes('data-review="actual_contract_signed"'), true,
  'PROD retains its existing contract editor');
assert.equal(render('contractBreach', true, {procurement_context: {
  rejection_date: '2026-09-03', rejection_title: 'Інше відхилення'}})
  .includes('data-review="actual_contract_signed"'), false,
  'PROD retains its existing complete-rejection visibility');
console.log('SANDBOX_APPEALS_CONTRACT_CONTROLS_UI=PASS');
