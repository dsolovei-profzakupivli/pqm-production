const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'app.js'), 'utf8').replace(/\r\n/g, '\n');
const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');

// The table keeps the established settings key, shows the full scenario text,
// and offers the saved-justification action only when text is actually saved.
assert.match(html, /data-column-key="decision_justification">Сценарій<\/th>/);
assert.match(source, /declinedNoViolation:'Відхилено'/);
const cellStart = source.indexOf('function requestScenarioCell(');
const cellEnd = source.indexOf('\n', cellStart);
assert.ok(cellStart >= 0 && cellEnd > cellStart);
const ui = {esc: value => String(value), violationReports: [], $: () => null};
vm.createContext(ui);
vm.runInContext(source.slice(cellStart, cellEnd), ui);
const withJustification = ui.requestScenarioCell({
  scenario_summary: 'Сценарій: Перевірено строки та підстави.',
  decision_justification: 'Повне збережене обґрунтування.\nДругий абзац.',
}, 0);
assert.match(withJustification, /Перевірено строки та підстави\./);
assert.doesNotMatch(withJustification, /<span[^>]*>Сценарій:/);
assert.match(withJustification, /data-view-justification="0"/);
assert.match(ui.requestScenarioCell({scenario_summary: '', decision_justification: '  '}, 1), /—/);
assert.doesNotMatch(ui.requestScenarioCell({scenario_summary: 'Текст', decision_justification: ' \n '}, 1), /data-view-justification/);
assert.doesNotMatch(ui.requestScenarioCell({scenario_summary: 'Текст'}, 1), /data-view-justification/);

let dialogOpened = 0;
const dialog = {open: false, showModal() { this.open = true; dialogOpened++; }};
const body = {textContent: ''};
ui.violationReports = [{report_id: 'UA-D-SYNTHETIC', decision_justification: 'Збережений текст без змін.'}];
ui.$ = selector => selector === '#requestJustificationDialog' ? dialog
  : selector === '#requestJustificationBody' ? body
    : selector === '#requestJustificationTitle' ? {textContent: ''} : null;
ui.showSavedRequestJustification = undefined;
const justificationStart = source.indexOf('function showSavedRequestJustification(');
const justificationEnd = source.indexOf('\n', justificationStart);
vm.runInContext(source.slice(justificationStart, justificationEnd), ui);
ui.showSavedRequestJustification('0');
assert.equal(dialogOpened, 1);
assert.equal(body.textContent, 'Збережений текст без змін.');
assert.match(source, /view\)\{e\.preventDefault\(\);e\.stopPropagation\(\);showSavedRequestJustification/);
assert.match(html, /role="document"/); // Dialog content is presentation only.

// Card declension controls use the existing permissions. Read-only users can
// inspect forms, while only declension.manage exposes a save action.
const declStart = source.indexOf('function canReadDeclensions()');
const declEnd = source.indexOf('function declensionLookup(', declStart);
assert.ok(declStart >= 0 && declEnd > declStart);
const declNodes = new Map();
const decl = {
  currentMe: {role: 'admin', permissions: {'declension.read': true, 'declension.manage': true}},
  declensionItems: [], declensionReturnContext: null,
  $: selector => {
    if (!declNodes.has(selector)) declNodes.set(selector, selector === '#declensionDialog'
      ? {showModal() {}} : selector === '#declensionSave' ? {hidden: false}
        : selector === '#declensionDialogHint' ? {textContent: ''}
          : {value: '', disabled: false, focus() {}, classList: {toggle() {}}, dataset: {}});
    return declNodes.get(selector);
  },
  $$: () => [], loadDeclensionOverrides: async () => true, toast() {},
};
vm.createContext(decl);
vm.runInContext(source.slice(declStart, declEnd), decl);
assert.match(decl.violationCardDeclensionButton('customer'), /Відмінювання/);
decl.currentMe = {role: 'officer', permissions: {'declension.read': true, 'declension.manage': false}};
assert.match(decl.violationCardDeclensionButton('supplier'), /Відмінювання/);
decl.openDeclensionEditor({entity_type: 'legal_entity', original: 'Тест'}, '', {readOnly: true});
assert.equal(decl.$('#declensionSave').hidden, true);
decl.currentMe = {role: 'viewer', permissions: {'declension.read': false, 'declension.manage': false}};
assert.equal(decl.violationCardDeclensionButton('customer'), '');

const marketplaceStart = source.indexOf('function zakupivliComplaintLink(');
const marketplaceEnd = source.indexOf('\n', marketplaceStart);
assert.ok(marketplaceStart >= 0 && marketplaceEnd > marketplaceStart);
const marketplace = {};
vm.createContext(marketplace);
vm.runInContext(source.slice(marketplaceStart, marketplaceEnd), marketplace);
for (const code of ['43012009', '1234567890']) {
  const link = marketplace.zakupivliComplaintLink({defendant_code: code});
  assert.match(link, new RegExp(`defendant_srn=${code}`));
  assert.match(link, /target="_blank" rel="noopener noreferrer"/);
  assert.doesNotMatch(link, /s=pending/);
}
for (const code of ['', 'bad-code', '1234567']) {
  const link = marketplace.zakupivliComplaintLink({defendant_code: code});
  assert.match(link, /complaints\/list"/);
  assert.doesNotMatch(link, /defendant_srn=/);
}

// Ensure the production card retains its native rendering and merely adds
// the approved declension and supplier-filter links.
const wrapperStart = source.indexOf('const violationDetailProductionBase=violationDetailHtml;');
const wrapperEnd = source.indexOf('\nasync function saveViolationDocumentReview', wrapperStart);
assert.ok(wrapperStart >= 0 && wrapperEnd > wrapperStart);
const card = {
  violationDetailHtml: () => '<h3>Замовник</h3><h3>Постачальник <span class="violation-thresholds">0/3 · 0/5</span></h3><h3>Закупівля · Договір · Звернення</h3>',
  canReadDeclensions: () => true,
  violationCardDeclensionButton: side => `<button data-side="${side}">Відмінювання</button>`,
  zakupivliComplaintLink: item => `<a href="https://my.zakupivli.pro/cabinet/ecatalog/gov/complaints/list?defendant_srn=${item.defendant_code}" rel="noopener noreferrer"></a>`,
};
vm.createContext(card);
vm.runInContext(source.slice(wrapperStart, wrapperEnd), card);
const cardHtml = card.violationDetailHtml({defendant_code: '43012009'});
assert.equal((cardHtml.match(/Відмінювання/g) || []).length, 2);
assert.match(cardHtml, /defendant_srn=43012009/);
assert.doesNotMatch(cardHtml, /s=pending/);
assert.match(cardHtml, /violation-thresholds/);

console.log('PRODUCTION_APPEALS_MODULE_UI=PASS');
