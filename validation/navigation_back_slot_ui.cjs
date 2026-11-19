const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const css = fs.readFileSync(path.join(root, 'styles.css'), 'utf8');
const navigation = fs.readFileSync(path.join(root, 'navigation.js'), 'utf8');

assert.match(html, /id="pqmBackSlot" class="back-slot"><\/div>\s*<nav id="mainNav"/);
assert.match(navigation, /getElementById\('pqmBackSlot'\)/);
assert.match(navigation, /\(backSlot\|\|header\)\?\.append\(button\)/);
assert.match(css, /\.topbar \.back-slot\{[^}]*flex:0 0 116px;[^}]*padding-inline:8px;/);
assert.match(css, /\.topbar \.back-slot #pqmBack\{width:max-content;max-width:100%;padding-inline:9px;justify-content:center;transform:translateX\(-10px\)\}/);
assert.doesNotMatch(css, /\.back-slot\s*\{[^}]*display\s*:\s*none/);
console.log('NAV_BACK_SLOT_STRUCTURE=PASS');
