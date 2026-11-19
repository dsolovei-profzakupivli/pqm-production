/* Reuse the established offline sheet fixture, execute the actual merged coordinator. */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const test = require('node:test');
const established = fs.readFileSync(path.join(__dirname, '../prod-contract/prod-full-apply.test.cjs'), 'utf8');
for (const env of ['prod', 'sandbox']) {
  const prefix = env === 'prod' ? 'Prod' : 'Sandbox';
  let harness = established.slice(established.indexOf('const source ='), established.indexOf("test('invalid Google/PQM"));
  harness = harness.replaceAll('Prod', prefix).replaceAll('PROD', prefix.toUpperCase());
  harness = harness.replace("const source = [", "const source = ['PqmEnvironmentGuard.gs', 'PqmVerificationDatetime.gs', 'Pqm" + prefix + "AppendApply.gs',");
  harness = harness.replace("'synthetic-prod'", 'context.PQM_MIRROR_ENV.spreadsheetId');
  harness = harness.replace("'old-status'", "'Неактивний'").replace("'Active'", "'Активний'");
  harness = harness.replace("context.pqm" + prefix + "RegistryUrl_ = () => 'https://pqm-sandbox.onrender.com/api/integrations/suppliers/full-registry';",
    "context.pqm" + prefix + "RegistryUrl_ = () => context.PQM_MIRROR_ENV.apiBase + '/api/integrations/suppliers/full-registry';");
  harness = harness.replace('context.Utilities = {', `
    context.ScriptApp = {getScriptId: () => context.PQM_MIRROR_ENV.scriptId};
    context.PropertiesService = {getScriptProperties: () => ({getProperty: () => context.PQM_MIRROR_ENV.spreadsheetId})};
    context.Utilities = {formatDate: date => {
      const p = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {timeZone:'Europe/Kyiv',
        year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'})
        .formatToParts(date).map(x => [x.type,x.value]));
      return p.year+'-'+p.month+'-'+p.day+'T'+p.hour+':'+p.minute+':'+p.second+'.'+String(date.getUTCMilliseconds()).padStart(3,'0');
    },`);
  const fixture = new Function('require', '__dirname', 'assert', 'crypto', 'fs', 'vm',
    harness + '\nreturn fixture;')(require, path.join(__dirname, env), assert, crypto, fs, vm);
  const run = (f, options) => f.context['pqm' + prefix + 'DailySync'](options);
  test(env + ': actual planner/coordinator update, immutable B/nonowned/formulas, repeat no-op', () => {
    const f = fixture();
    const original = [...f.raw].map(([key, cells]) => [key, JSON.parse(JSON.stringify(cells))]);
    const result = run(f);
    assert.equal(result.status, 'COMPLETE'); assert.equal(result.update, 8);
    assert.equal(result.append, 0); assert.equal(result.remaining_safe, 0);
    for (const [key, cells] of original) {
      const after = f.raw.get(key);
      for (const col of [0,1,6,9,10,12,13,14]) assert.deepEqual(after[col], cells[col]);
    }
    const writes = f.writes;
    assert.equal(run(f).update, 0); assert.equal(f.writes, writes);
    assert.equal(f.released, 2);
  });
  test(env + ': stale reviewed digest fails before writes', () => {
    const f = fixture();
    assert.throws(() => run(f, {expectedDigest:'stale'}), /stale execution Preview/);
    assert.equal(f.writes, 0); assert.equal(f.released, 1);
  });
  test(env + ': source change after first chunk stops partial Apply without retry', () => {
    const f = fixture();
    f.afterWrite(() => {f.body.items[0].current_manager_name = 'changed after Preview';});
    assert.throws(() => run(f), /source changed during run/);
    assert.equal(f.writes, 1); assert.equal(f.released, 1);
  });
  test(env + ': newer precise I updates D/E with exact counters; equal I skips entire row', () => {
    const f = fixture();
    // The inherited stress fixture limits chunks to four cells. This case changes
    // six cells in ONE row; use seven (still below runtime limits), never split its gate.
    f.context['PQM_' + prefix.toUpperCase() + '_FULL_CHUNK_MAX_CELLS'] = 7;
    for (const x of f.body.items) {
      x.verification_date = '2026-09-22T17:03:19+03:00';
      x.current_manager_name = 'УО confirmed manager'; x.edr_status_current = 'В стані припинення';
    }
    const result = run(f); assert.equal(result.update,8);
    for (const cells of f.raw.values()) {
      assert.equal(cells[3].effectiveValue.stringValue, 'УО confirmed manager');
      assert.equal(cells[4].effectiveValue.stringValue, 'В стані припинення');
      assert.equal(cells[8].userEnteredFormat.numberFormat.type, 'DATE_TIME');
    }
    const writes = f.writes;
    for (const x of f.body.items) x.current_manager_name = 'must not change equal I';
    assert.equal(run(f).update,0); assert.equal(f.writes,writes);
  });
}
