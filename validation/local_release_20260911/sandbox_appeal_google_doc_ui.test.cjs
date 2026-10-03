const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.resolve(__dirname, '../../app.js'), 'utf8');
function between(first, next) {
  const start = source.indexOf(first), end = source.indexOf(next, start + first.length);
  assert.ok(start >= 0 && end > start);
  return source.slice(start, end);
}

test('SANDBOX reopened appeal shows its saved Google Doc and PROD does not', () => {
  const code = between('const violationProtocolSandboxGoogleBase=requestContextBlock;',
    'async function generateViolationGoogleDoc(');
  const context = {requestContextBlock: () => '<section><h3>Протокольне рішення</h3></section>',
    document: {documentElement: {dataset: {pqmEnvironment: 'sandbox'}}},
    esc: value => String(value)};
  vm.createContext(context); vm.runInContext(code, context);
  const item = {id: 'report-1', protocol_readiness: {ready: true},
    review: {customer_verified_short_name: 'Замовник'},
    supplier_verified: {short_name: 'Постачальник'},
    generated_google_doc: {status: 'complete', document_id: 'sandbox_generated_123456789',
      document_name: 'report-1_9_П_Замовник_Постачальник (00123456)'}};
  assert.match(context.requestContextBlock(item), /docs\.google\.com\/document\/d\/sandbox_generated_123456789\/edit/);
  assert.match(context.requestContextBlock(item), /Створити нову версію Google Doc/);
  context.document.documentElement.dataset.pqmEnvironment = 'prod';
  assert.doesNotMatch(context.requestContextBlock(item), /sandbox_generated_123456789/);
});

test('missing short name disables Google Docs generation', () => {
  const code = between('const violationProtocolSandboxGoogleBase=requestContextBlock;',
    'async function generateViolationGoogleDoc(');
  const context = {requestContextBlock: () => '<section></section>',
    document: {documentElement: {dataset: {pqmEnvironment: 'sandbox'}}},
    esc: value => String(value)};
  vm.createContext(context); vm.runInContext(code, context);
  const item = {protocol_readiness: {ready: true}, review: {customer_verified_short_name: ''},
    supplier_verified: {short_name: 'Постачальник'}};
  assert.match(context.requestContextBlock(item), /id="generateViolationGoogleDoc" disabled/);
});
