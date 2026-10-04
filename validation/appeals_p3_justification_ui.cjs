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
for (const key of ['p49_1_decline_before_deadline', 'p49_1_warning', 'p49_2_decline_timely_refusal']) {
  assert.equal(context.requestContextBlock({...base, justification_template_key: key}), base.justification_draft);
}
const guardStart = source.indexOf('const violationP3DraftReviewNotice=');
const guardEnd = source.indexOf('async function generateViolationProtocol', guardStart);
assert.ok(guardStart > 0 && guardEnd > guardStart);
const guardContext = {requestContextBlock: () => '<section class="violation-justification"></section>', esc: value => value};
vm.createContext(guardContext);
vm.runInContext(source.slice(guardStart, guardEnd), guardContext);
const scenario = {...base, reason: 'goodsNonCompliance', review: {court_decision_final_present: false, internal_decision: ''}, defendant_statements: [], recommendation: {recommended_decision: 'decline'}};
assert.equal(guardContext.violationP3DraftNeedsReview(scenario, '', base.justification_draft), false);
assert.equal(guardContext.violationP3DraftNeedsReview(scenario, 'decline', base.justification_draft), false);
assert.equal(guardContext.violationP3DraftNeedsReview(scenario, 'warning', base.justification_draft), true);
assert.equal(guardContext.violationP3DraftNeedsReview(scenario, 'warning', ''), false);
assert.match(guardContext.requestContextBlock({...scenario, review: {...scenario.review, internal_decision: 'warning', decision_justification: base.justification_draft}}), /id="violationP3DraftReviewNotice" >Обране рішення не відповідає/);
assert.match(guardContext.requestContextBlock({...scenario, review: {...scenario.review, internal_decision: 'decline'}}), /id="violationP3DraftReviewNotice" hidden>/);
console.log('APPEALS_P3_JUSTIFICATION_UI=PASS');
