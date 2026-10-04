const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '..', 'sandbox_google_docs_picker.js'), 'utf8');
const ids = {
  warning: '1Nebc4MJerGuU7QlY-8nk7jWNOBOwaszlqmkrZzo0de4',
  decline_p49_1_2: '1IclKZui5_EEg9JV-gA-v-8Lm7rrN32V2CsysPUQr1a0',
  decline_p49_3: '1gVoNkbCWh2cXsmgU3LaoA0vRTOLZZR5e0QQ6dYOG4QM',
  destination: '1pT7R9CiWNWAG0siz2aeasF0kiEYGSMFN',
};
const order = Object.keys(ids);

function setup(environment = 'sandbox') {
  const calls = [], callbacks = [], views = [];
  const button = {disabled: false, addEventListener(_event, callback) {this.click = callback;}};
  const status = {lines: [], replaceChildren(...nodes) {this.lines = nodes.map(node => node.textContent);}};
  const panel = {hidden: true};
  class DocsView {
    constructor(type) {this.type = type;}
    setFileIds(files) {
      assert.equal(typeof files, 'string', 'Picker setFileIds requires a string');
      this.files = files;
      views.push(this);
      return this;
    }
    setSelectFolderEnabled(value) {this.selectFolder = value; return this;}
  }
  class PickerBuilder {
    setAppId(value) {assert.equal(value, '785118226581'); return this;}
    setDeveloperKey() {return this;}
    setOAuthToken() {return this;}
    setOrigin() {return this;}
    addView() {return this;}
    setCallback(value) {callbacks.push(value); return this;}
    build() {return {setVisible() {}};}
  }
  const picker = {DocsView, PickerBuilder, ViewId: {FOLDERS: 'folders', DOCUMENTS: 'documents'},
    Action: {PICKED: 'picked', CANCEL: 'cancel'}};
  const context = {
    document: {documentElement: {dataset: {pqmEnvironment: environment}},
      getElementById(id) {return id === 'sandboxDocsPickerSetup' ? panel
        : id === 'sandboxDocsPickerStart' ? button : status;},
      createElement(tag) {return tag === 'script'
        ? {set onload(callback) {queueMicrotask(callback);}} : {textContent: ''};},
      head: {appendChild() {}}},
    window: {gapi: {load(_key, options) {options.callback();}}, google: {picker}},
    google: {picker}, location: {origin: 'https://pqm-sandbox.onrender.com'},
    authReady: new Promise(() => {}), currentMe: {role: 'admin'},
    request: async url => {
      calls.push(url);
      if (url.endsWith('/config')) return {app_id: '785118226581', api_key: 'test',
        access_token: 'test', resources: {...ids}};
      if (url.endsWith('/access-check')) return {ready_for_single_generation_test: true,
        warning: true, decline_p49_1_2: true, decline_p49_3: true, destination: true};
      const key = new URL(url, 'https://pqm-sandbox.onrender.com').searchParams.get('key');
      return {id: ids[key], is_app_authorized: true};
    },
    queueMicrotask,
  };
  vm.runInNewContext(source, context);
  return {button, panel, status, calls, callbacks, views};
}

async function tick() {await new Promise(resolve => setImmediate(resolve));}

(async () => {
  const prod = setup('production');
  assert.equal(prod.panel.hidden, true);
  assert.equal(prod.button.click, undefined);

  const success = setup();
  const run = success.button.click();
  await tick();
  assert.equal(success.button.disabled, true);
  for (let i = 0; i < order.length; i++) {
    assert.equal(success.callbacks.length, i + 1, 'exactly one Picker at a time');
    assert.equal(success.views[i].files, ids[order[i]], `${order[i]} uses exact configured ID`);
    if (i === 3) assert.equal(success.views[i].selectFolder, true);
    await success.callbacks[i]({action: 'picked', docs: [{id: ids[order[i]]}]});
    await tick();
  }
  await run;
  assert.equal(success.status.lines.at(-1), 'Google Docs для звернень — ГОТОВО');
  assert.equal(success.status.lines.filter(line => line.includes('✓ доступ підтверджено')).length, 4);
  assert.equal(success.calls.length, 6, 'config + four fixed checks + final access-check');
  assert.equal(success.calls.some(url => url.includes('generate')), false);

  const wrong = setup();
  const stopped = wrong.button.click();
  await tick();
  await wrong.callbacks[0]({action: 'picked', docs: [{id: ids.decline_p49_3}]});
  await stopped;
  assert.equal(wrong.callbacks.length, 1);
  assert.equal(wrong.calls.length, 1, 'wrong ID never reaches backend confirmation');
  assert.equal(wrong.status.lines.includes('Google Docs для звернень — НЕ ГОТОВО'), true);
  console.log('SANDBOX_PICKER_SETUP_UI=PASS');
})().catch(error => {console.error(error); process.exitCode = 1;});
