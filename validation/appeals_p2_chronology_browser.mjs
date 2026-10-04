import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

const chrome = process.env.PQM_CHROME_EXE;
if (!chrome) throw new Error('PQM_CHROME_EXE is required for layout regression');
const css = readFileSync(path.resolve(import.meta.dirname, '..', 'styles.css'), 'utf8');
const labels = ['Дата визначення переможцем', 'Граничний строк письмової відмови',
  'Дата письмової відмови', 'Дата відхилення'];
const cells = labels.map((label, index) => `<div><small>${label}</small><strong>0${index + 1}.10.2026</strong></div>`).join('');
const html = `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>${css}</style><style>.panel{width:min(1100px,calc(100vw - 40px))}</style></head><body><div class="panel"><div class="request-form-grid violation-review-header"><label id="officerControl">Відповідальна УО<select><option>УО</option></select></label><label id="statusControl">Статус розгляду<select><option>На розгляді</option></select></label><div class="violation-admin-deadline" data-deadline-state="normal" id="adminDeadline"><small>Строк Адміністратора · 10 робочих днів</small><strong>09.10.2026</strong></div><label>Додаткова перевірка<input type="checkbox"></label></div><div class="violation-p2-chronology"><div class="violation-p2-chronology-row">${cells}</div><div class="violation-p2-rejection-ground"><small>Підстава відхилення</small><strong id="ground">${'Довга підстава відхилення '.repeat(40)}</strong></div></div></div></body></html>`;
const profile = await mkdtemp(path.join(os.tmpdir(), 'pqm-p2-chronology-'));
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
    const loaded = await send('Runtime.evaluate', {expression: `Boolean(document.getElementById('ground'))`, returnByValue: true});
    if (loaded.result.value) break;
    await sleep(100);
  }
  for (const [width, expectedColumns] of [[1360, 4], [1000, 4], [760, 2], [500, 1]]) {
    await send('Emulation.setDeviceMetricsOverride', {width, height: 900, deviceScaleFactor: 1, mobile: false});
    const measured = await send('Runtime.evaluate', {expression: `(() => {
      const row = document.querySelector('.violation-p2-chronology-row');
      const ground = document.querySelector('.violation-p2-rejection-ground');
      const columns = getComputedStyle(row).gridTemplateColumns.split(' ').length;
      document.getElementById('ground').textContent = 'Довга підстава відхилення '.repeat(40);
      const longHeight = row.getBoundingClientRect().height;
      document.getElementById('ground').textContent = 'Коротка підстава';
      const shortHeight = row.getBoundingClientRect().height;
      return {columns, longHeight, shortHeight, rowWidth: row.getBoundingClientRect().width,
        groundWidth: ground.getBoundingClientRect().width};
    })()`, returnByValue: true});
    const result = measured.result.value;
    assert.equal(result.columns, expectedColumns, `width=${width}`);
    assert.ok(Math.abs(result.longHeight - result.shortHeight) <= 1, `long rejection changes chronology height at ${width}`);
    assert.ok(Math.abs(result.rowWidth - result.groundWidth) <= 1, `ground is not full width at ${width}`);
    if (width === 1360) {
      const header = await send('Runtime.evaluate', {expression: `(() => {
        const deadline = document.getElementById('adminDeadline');
        const heights = [];
        for (const state of ['normal', 'attention', 'overdue']) {
          deadline.dataset.deadlineState = state;
          deadline.querySelector('span')?.remove();
          if (state === 'overdue') deadline.insertAdjacentHTML('beforeend', '<span>Строк сплив</span>');
          heights.push(deadline.getBoundingClientRect().height);
        }
        return {heights, officer: document.getElementById('officerControl').getBoundingClientRect().height,
          status: document.getElementById('statusControl').getBoundingClientRect().height,
          arrow: getComputedStyle(document.querySelector('.violation-p2-chronology-row>div'), '::after').content};
      })()`, returnByValue: true});
      const {heights, officer, status, arrow} = header.result.value;
      assert.ok(heights.every(height => Math.abs(height - officer) <= 6 && Math.abs(height - status) <= 6),
        `admin control height ${heights}, officer=${officer}, status=${status}`);
      assert.equal(arrow, 'none', 'chronology arrows must be removed');
    }
    console.log(`width=${width} P2_CHRONOLOGY_COLUMNS=${result.columns} GROUND_FULL_WIDTH=YES ROW_HEIGHT_STABLE=YES`);
  }
} finally {
  try { socket?.close(); } catch {}
  child.kill();
}
