const assert = require('node:assert/strict');
const path = require('node:path');
const { spawn } = require('node:child_process');
let chromium;
try { ({ chromium } = require('playwright')); }
catch { ({ chromium } = require('C:/Users/User/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright')); }

const root = path.resolve(process.env.PQM_TEST_ROOT || path.join(__dirname, '..'));
const python = process.env.PQM_PYTHON || 'C:/Users/User/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe';
const fixturePort = 8897;
const evidence = path.join(root, 'evidence', 'admin-management');
require('node:fs').mkdirSync(evidence, { recursive: true });

async function login(page, username) {
  await page.locator('#loginUsername').fill(username);
  await page.locator('#loginPassword').fill('Synthetic-test-only-2026');
  await page.locator('#loginForm button[type="submit"]').click();
  await page.locator('#applicationShell').waitFor({ state: 'visible', timeout: 15000 });
}

async function main() {
  const fixtureServer = spawn(python, [path.join(root, 'validation', 'browser_fixture.py')], {
    cwd: root, env: { ...process.env, PQM_FIXTURE_PORT: String(fixturePort) }, stdio: ['ignore', 'pipe', 'pipe'],
  });
  let startup = '', config;
  const ready = new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error(`Fixture server did not start: ${startup}`)), 30000);
    fixtureServer.stdout.on('data', chunk => {
      startup += chunk.toString();
      const line = startup.split(/\r?\n/).find(value => value.includes('"fixture_only"'));
      if (!line) return;
      try { config = JSON.parse(line); clearTimeout(timeout); resolve(config); }
      catch (error) { clearTimeout(timeout); reject(error); }
    });
    fixtureServer.stderr.on('data', chunk => { startup += chunk.toString(); });
    fixtureServer.once('exit', code => { if (!config) reject(new Error(`Fixture server exited (${code}): ${startup}`)); });
  });
  let browser;
  try {
    const fixture = await ready;
    assert.equal(fixture.fixture_only, true);
    browser = await chromium.launch({ headless: true, executablePath: process.env.PQM_CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe' });
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
    const page = await context.newPage(), errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(`http://127.0.0.1:${fixture.port}/`, { waitUntil: 'domcontentloaded' });
    await login(page, 'fixture-admin');
    await page.locator('#administrationNav').click();
    await page.locator('#administrationView').waitFor({ state: 'visible' });
    for (const theme of ['light', 'dark']) {
      await page.evaluate(value => { document.documentElement.dataset.theme = value; }, theme);
      await page.locator('[data-admin-tab="officers"]').click();
      await page.locator('#adminOfficersPanel').waitFor({ state: 'visible' });
      assert.equal(await page.locator('#adminAccountsPanel').isVisible(), false);
      await page.locator('[data-admin-tab="accounts"]').click();
      await page.locator('#adminAccountsPanel').waitFor({ state: 'visible' });
      await page.evaluate(() => document.querySelectorAll('#adminAccountsPanel details').forEach(detail => { detail.open = false; }));
      assert.equal(await page.locator('#adminOfficersPanel').isVisible(), false);
      for (const id of ['adminUserForm', 'adminUsersBody', 'accessPanel', 'accessAccountsPanel', 'accessOfficer']) assert.equal(await page.locator(`#${id}`).count(), 1);
      assert.equal(await page.locator('#accessPanel > summary').innerText(), 'Ролі та права доступу');
      assert.equal(await page.locator('#accessAccountsPanel > summary').innerText(), 'Облікові записи PQM');
      await page.locator('#accessPanel > summary').click();
      assert.equal(await page.locator('#accessRole').isVisible(), true);
      assert.equal(await page.locator('#accessAccountsPanel').evaluate(element => element.open), false);
      await page.locator('#accessAccountsPanel > summary').click();
      assert.equal(await page.locator('#accessPanel').evaluate(element => element.open), true);
      await page.locator('#accessUserRole').selectOption('admin');
      await page.locator('#accessOfficer').selectOption({ index: 1 });
      await page.locator('#accessUsername').fill(`unsaved-${theme}`);
      await page.locator('#accessName').fill(`Temporary ${theme}`);
      await page.locator('#accessPassword').fill('Synthetic-unsaved-only-2026');
      const draft = await page.evaluate(() => ({ role: accessUserRole.value, officer: accessOfficer.value, username: accessUsername.value, name: accessName.value, password: accessPassword.value }));
      assert.ok(draft.officer);
      await page.locator('#accessAccountsPanel > summary').click();
      await page.locator('#accessPanel > summary').click();
      await page.locator('#accessPanel > summary').click();
      await page.locator('#accessAccountsPanel > summary').click();
      assert.deepEqual(await page.evaluate(() => ({ role: accessUserRole.value, officer: accessOfficer.value, username: accessUsername.value, name: accessName.value, password: accessPassword.value })), draft);
    }
    const viewerContext = await browser.newContext();
    await viewerContext.addInitScript(() => { localStorage.setItem('pqm.adminTab', 'accounts'); localStorage.setItem('pqm.activeModule', 'administration'); });
    const viewer = await viewerContext.newPage(), forbiddenRequests = [];
    viewer.on('request', request => { if (/\/api\/admin\/(access-roles|users)/.test(request.url())) forbiddenRequests.push(request.url()); });
    viewer.on('pageerror', error => errors.push(error.message));
    await viewer.goto(`http://127.0.0.1:${fixture.port}/`, { waitUntil: 'domcontentloaded' });
    await login(viewer, 'fixture-viewer');
    assert.equal(await viewer.locator('#administrationView').isVisible(), false);
    await viewer.evaluate(() => { showModule('administration'); setAdminTab('accounts'); });
    assert.equal(await viewer.locator('#administrationView').isVisible(), false);
    assert.equal(await viewer.locator('[data-admin-tab="accounts"]').isVisible(), false);
    assert.equal(await viewer.locator('#adminAccountsPanel').isVisible(), false);
    assert.deepEqual(forbiddenRequests, []);
    assert.deepEqual(errors, []);
    await viewerContext.close(); await context.close();
    console.log(JSON.stringify({ status: 'PASS', fixture: 'synthetic-only', themes: ['light', 'dark'], accordions: 'independent', draftPreserved: true, nonAdminAdministration: 'blocked', forbiddenAdminRequests: 0 }));
  } finally {
    if (browser) await browser.close();
    fixtureServer.kill();
    await new Promise(resolve => fixtureServer.once('exit', resolve));
  }
}

main().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
