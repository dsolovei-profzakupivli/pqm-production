import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

const chrome = process.env.PQM_CHROME_EXE;
if (!chrome) throw new Error('PQM_CHROME_EXE is required for layout regression');
const root = path.resolve(import.meta.dirname, '..');
const css = readFileSync(path.join(root, 'styles.css'), 'utf8');
const html = `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>${css}</style></head><body><header class="topbar"><div class="brand prod-brand"><span class="prod-brand-initials"></span><span class="prod-brand-divider"></span><span class="prod-brand-copy"><strong>Професійні закупівлі</strong><small>Procurement Qualification Manager</small></span></div><div id="pqmBackSlot" class="back-slot"><button id="pqmBack" hidden>← Назад</button></div><nav id="mainNav"><button id="workQueueNav" class="main-nav-text">Робота УО</button><button>Реєстр заявок</button></nav><div class="service-nav"></div><div class="account-menu"></div></header></body></html>`;
const profile = await mkdtemp(path.join(os.tmpdir(), 'pqm-back-slot-'));
const port = 19234 + Math.floor(Math.random() * 2000);
const child = spawn(chrome, ['--headless=new', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage', '--no-first-run', `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, 'about:blank'], {stdio: 'ignore'});
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
let socket;
try {
  let target;
  for (let i = 0; i < 100 && !target; i++) {
    try { target = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find(x => x.type === 'page'); } catch {}
    await sleep(100);
  }
  if (!target) throw new Error('Chrome target unavailable');
  socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  let id = 0;
  const pending = new Map();
  socket.onmessage = event => {
    const message = JSON.parse(event.data);
    if (!message.id) return;
    const waiter = pending.get(message.id);
    pending.delete(message.id);
    message.error ? waiter.reject(new Error(message.error.message)) : waiter.resolve(message.result);
  };
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const requestId = ++id;
    pending.set(requestId, {resolve, reject});
    socket.send(JSON.stringify({id: requestId, method, params}));
  });
  await send('Page.enable');
  await send('Runtime.enable');
  await send('Page.navigate', {url: `data:text/html;charset=utf-8,${encodeURIComponent(html)}`});
  for (let i = 0; i < 50; i++) {
    const loaded = await send('Runtime.evaluate', {expression: `Boolean(document.getElementById('workQueueNav'))`, returnByValue: true});
    if (loaded.result.value) break;
    await sleep(100);
  }
  for (const width of [1600, 1360, 1100, 800]) {
    await send('Emulation.setDeviceMetricsOverride', {width, height: 900, deviceScaleFactor: 1, mobile: false});
    const positions = await send('Runtime.evaluate', {expression: `(() => {
      const back = document.getElementById('pqmBack');
      const tab = document.getElementById('workQueueNav');
      back.hidden = true;
      const withoutBack = tab.getBoundingClientRect().x;
      back.hidden = false;
      const withBack = tab.getBoundingClientRect().x;
      return {withoutBack, withBack};
    })()`, returnByValue: true});
    const {withoutBack, withBack} = positions.result.value;
    assert.ok(Math.abs(withBack - withoutBack) <= 1,
      `NAV_TABS_X_WITH_BACK=${withBack} NAV_TABS_X_WITHOUT_BACK=${withoutBack} width=${width}`);
    console.log(`width=${width} NAV_TABS_X_WITH_BACK=${withBack} NAV_TABS_X_WITHOUT_BACK=${withoutBack}`);
  }
} finally {
  try { socket?.close(); } catch {}
  child.kill();
}
