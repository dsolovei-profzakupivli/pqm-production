const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('app.js', 'utf8').replace(/\r\n/g, '\n');
const start = source.indexOf('async function loadDeclensionOverrides(){');
const cardEnd = source.indexOf('function violationCardDeclensionButton(', start);
const editorStart = source.indexOf('function openDeclensionEditor(', cardEnd);
const editorEnd = source.indexOf('async function returnToDeclensionReport(', editorStart);
const requestStart = source.indexOf('async function request(');
const requestEnd = source.indexOf('\n', requestStart);
assert(start >= 0 && cardEnd > start && editorStart > cardEnd && editorEnd > editorStart);
assert(requestStart >= 0 && requestEnd > requestStart);

function createContext(status) {
  const nodes = new Map();
  const dialog = {openCount: 0, showModal() { this.openCount++; }};
  const calls = [];
  const toasts = [];
  const node = selector => {
    if (!nodes.has(selector)) nodes.set(selector, selector === '#declensionDialog' ? dialog : {
      value: '', innerHTML: '', textContent: '', hidden: false, disabled: false,
      focus() {}, classList: {toggle() {}}, dataset: {},
    });
    return nodes.get(selector);
  };
  const context = {
    API: '/api',
    currentMe: {role: 'admin', permissions: {'declension.read': true, 'declension.manage': true}},
    declensionTypeLabels: {legal_entity: 'Юридична особа'},
    declensionItems: [], editingDeclensionId: null, declensionReturnContext: null,
    cardItem: {id: 42, author_name: 'СИНТЕТИЧНА ЮРИДИЧНА ОСОБА', author_code: '12345678'},
    esc: value => String(value), toast: (...args) => toasts.push(args),
    $: node, $$: () => [],
    fetch: async (url, options = {}) => {
      calls.push({url, method: options.method || 'GET'});
      const body = status === 200
        ? {items: [{id: 'synthetic-1', entity_type: 'legal_entity', original: 'СИНТЕТИЧНА ЮРИДИЧНА ОСОБА', genitive: 'СИНТЕТИЧНОЇ ЮРИДИЧНОЇ ОСОБИ'}]}
        : {error: `Синтетична HTTP ${status}`};
      return {ok: status === 200, status, headers: {get: () => 'application/json'}, text: async () => JSON.stringify(body)};
    },
  };
  vm.createContext(context);
  vm.runInContext(source.slice(requestStart, requestEnd) + '\n'
    + source.slice(start, cardEnd) + '\n'
    + source.slice(editorStart, editorEnd), context);
  return {context, dialog, calls, toasts, node};
}

(async () => {
  const success = createContext(200);
  await vm.runInContext("openViolationCardDeclension('customer', cardItem)", success.context);
  assert.equal(success.dialog.openCount, 1, 'HTTP 200 opens the existing editor');
  assert.equal(success.toasts.length, 0, 'successful load does not show an error');
  assert.equal(success.calls.length, 1);
  assert.equal(success.calls[0].url, '/api/declension-overrides');
  assert.equal(success.node('#declensionOriginal').value, 'СИНТЕТИЧНА ЮРИДИЧНА ОСОБА');
  assert.equal(success.node('#declensionGenitive').value, 'СИНТЕТИЧНОЇ ЮРИДИЧНОЇ ОСОБИ');
  assert.equal(success.node('#declensionSave').hidden, false, 'authorized admin keeps existing edit access');

  await vm.runInContext("openViolationCardDeclension('customer', cardItem)", success.context);
  assert.equal(success.dialog.openCount, 2, 'the editor can be opened again after the first open');
  assert.equal(success.calls.length, 2);
  assert.equal(success.toasts.length, 0);

  for (const status of [401, 403, 500]) {
    const failed = createContext(status);
    await vm.runInContext("openViolationCardDeclension('customer', cardItem)", failed.context);
    assert.equal(failed.dialog.openCount, 0, `HTTP ${status} does not open the editor`);
    assert.equal(failed.toasts.length, 1, `HTTP ${status} reports a load error`);
    assert.equal(failed.toasts[0][0], 'Не вдалося завантажити довідник відмінювання');
    assert.match(failed.node('#declensionBody').innerHTML, new RegExp(`HTTP ${status}`));
    assert.equal(failed.calls.length, 1);
  }

  console.log('DECLENSION_LOADER_RESULT=PASS (200, 401, 403, 500, reopen)');
})().catch(error => { console.error(error); process.exit(1); });
