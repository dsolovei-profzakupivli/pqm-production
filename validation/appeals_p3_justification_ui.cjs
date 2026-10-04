const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'app.js'), 'utf8');
const start = source.indexOf('const violationScenarioReviewBase=requestContextBlock;');
const end = source.indexOf('const violationContractReviewBase=requestContextBlock;', start);
assert.ok(start > 0 && end > start);
const context = {requestContextBlock: item => item.review?.decision_justification || ''};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);
const base = {
  justification_template_key: 'p49_3_decline_no_final_court_decision_no_explanation',
  justification_draft: 'Погоджене типове обґрунтування',
  deadline_control: {supplier_ready: true}, review: {internal_decision: ''},
};
assert.equal(context.requestContextBlock(base), base.justification_draft);
assert.equal(base.review.decision_justification, undefined, 'Rendering must not mutate saved state');
assert.equal(context.requestContextBlock({...base, review: {decision_justification: 'Власний текст УО'}}), 'Власний текст УО');
assert.equal(context.requestContextBlock({...base, justification_template_key: ''}), '');
assert.equal(context.requestContextBlock({...base, deadline_control: {supplier_ready: false}}), '');
console.log('APPEALS_P3_JUSTIFICATION_UI=PASS');
