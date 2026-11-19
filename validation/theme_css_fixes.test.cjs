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

test('Supplier EDR metadata cards follow selected theme over Sandbox defaults',()=>{
  assert.match(base,/html\[data-pqm-environment="sandbox"\] \.supplier-edr-metadata>div\{background:#132840/);
  assert.match(dark,/html\[data-theme="light"\] #supplierProfileBody \.supplier-edr-metadata>div\{background-color:#f6f9fd;color:var\(--ink\);border-color:#d8e2ed\}/);
  assert.match(dark,/html\[data-theme="light"\] #supplierProfileBody \.supplier-edr-metadata dt\{color:#64748b\}/);
  assert.match(dark,/html\[data-theme="dark"\] #supplierProfileBody \.supplier-edr-metadata>div\{background-color:#132840;color:#edf3fc;border-color:#38516e\}/);
  assert.match(dark,/html\[data-theme="dark"\] #supplierProfileBody \.supplier-edr-metadata dt\{color:#b2c3db\}/);
});

test('Supplier Clarity action follows the selected theme, not the Sandbox environment',()=>{
  assert.match(base,/html\[data-pqm-environment="sandbox"\] \.supplier-edr-actions a\{background:#193451/);
  assert.match(dark,/html\[data-theme="light"\] #supplierProfileBody \.supplier-edr-actions a\{background-color:#f7f9fc;color:#184c83;border-color:#b7c8db\}/);
  assert.match(dark,/html\[data-theme="light"\] #supplierProfileBody \.supplier-edr-actions a:hover\{background-color:#e9f2ff/);
  assert.match(dark,/html\[data-theme="dark"\] :is\([^\n]*\.supplier-edr-actions a\),/);
  assert.match(dark,/html\[data-theme="dark"\] \.supplier-edr-actions a:hover,[\s\S]*?\.supplier-edr-actions a:focus-visible\{background-color:#28517b;color:#fff;border-color:#86bdff\}/);
});
