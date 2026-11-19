const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.join(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'app.js'), 'utf8');
const css = fs.readFileSync(path.join(root, 'styles.css'), 'utf8');
const start = source.indexOf('function violationKyivTodayISO()');
const end = source.indexOf('bindViolationReview=function(item){const status=', start);
assert.ok(start >= 0 && end > start);
const context = {
  requestContextBlock: () => '<div class="violation-admin-deadline"><small>Old</small><span>У межах строку</span></div>',
  esc: value => String(value ?? ''),
  displayDateOnly: value => String(value ?? ''),
};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);
const deadline = {admin_deadline: '2026-10-09', admin_overdue: false};
for (const [today, expected] of [
  ['2026-10-07', 'normal'], ['2026-10-08', 'attention'],
  ['2026-10-09', 'attention'], ['2026-10-10', 'overdue'],
]) {
  assert.equal(context.violationAdminDeadlineState(deadline, today), expected, today);
  const html = context.violationAdminDeadlineMarkup(deadline, today);
  assert.ok(html.includes(`data-deadline-state="${expected}"`), today);
  assert.equal(html.includes('Строк сплив'), expected === 'overdue', today);
  assert.ok(!html.includes('У межах строку'), today);
}
assert.equal(context.violationAdminDeadlineState({admin_deadline: '2026-10-12'}, '2026-10-09'), 'attention');
assert.equal(context.violationAdminDeadlineState({admin_deadline: '2026-10-12'}, '2026-10-08'), 'normal');
assert.equal(context.violationAdminDeadlineState({admin_deadline: null}, '2026-10-08'), 'normal');
const rendered = context.requestContextBlock({deadline_control: deadline});
assert.ok(rendered.includes('data-deadline-state='));
assert.ok(!rendered.includes('У межах строку'));
assert.match(css, /\.violation-admin-deadline\{[^}]*height:60px;/);
assert.doesNotMatch(css, /\.violation-p2-chronology-row>div:not\(:last-child\)::after/);
console.log('APPEALS_ADMIN_DEADLINE_UI=PASS');
