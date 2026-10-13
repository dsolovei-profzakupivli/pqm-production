/* Reuse the established offline sheet fixture, execute the actual merged coordinator. */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const established = fs.readFileSync(path.join(__dirname, '../prod-contract/prod-full-apply.test.cjs'), 'utf8');
function createFixture(env) {
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

  return fixture();
}
module.exports = createFixture;
