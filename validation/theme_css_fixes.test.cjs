const assert=require('node:assert/strict');
const fs=require('node:fs');
const test=require('node:test');

const dark=fs.readFileSync('theme.css','utf8');
const base=fs.readFileSync('styles.css','utf8');

test('Framework export links use dark surfaces only in dark theme',()=>{
  assert.match(dark,/html\[data-theme="dark"\] #frameworkAnalyticsView \.frameworks-table a\.ghost,[\s\S]*?#frameworkAnalyticsView #frameworksExportSelected\{background-color:#193451;color:#86bdff;border-color:#4a6788\}/);
  assert.match(dark,/html\[data-theme="dark"\] #frameworkAnalyticsView \.frameworks-table a\.ghost:hover,[\s\S]*?#frameworkAnalyticsView #frameworksExportSelected:focus-visible\{background-color:#28517b;color:#fff;border-color:#86bdff\}/);
  assert.doesNotMatch(base,/html\[data-theme="light"\].*frameworks-table/);
});

test('Supplier EDR metadata cards are no longer dark solely because environment is Sandbox',()=>{
  assert.doesNotMatch(base,/html\[data-pqm-environment="sandbox"\] \.supplier-edr-metadata/);
  assert.match(dark,/html\[data-theme="dark"\] #supplierProfileBody \.supplier-edr-metadata>div\{background-color:#132840;color:#edf3fc;border-color:#38516e\}/);
  assert.match(dark,/html\[data-theme="dark"\] #supplierProfileBody \.supplier-edr-metadata dt\{color:#b2c3db\}/);
});

test('Supplier Clarity action follows the selected theme, not the Sandbox environment',()=>{
  assert.doesNotMatch(base,/html\[data-pqm-environment="sandbox"\] \.supplier-edr-actions a/);
  assert.match(base,/\.supplier-edr-actions a\{[^}]*background:#f7f9fc;color:#184c83/);
  assert.match(dark,/html\[data-theme="dark"\] :is\([^\n]*\.supplier-edr-actions a\),/);
  assert.match(dark,/html\[data-theme="dark"\] \.supplier-edr-actions a:hover,[\s\S]*?\.supplier-edr-actions a:focus-visible\{background-color:#28517b;color:#fff;border-color:#86bdff\}/);
});
