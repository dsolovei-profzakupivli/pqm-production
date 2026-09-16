import {spawn} from 'node:child_process';
import {mkdir, readdir, readFile, rm} from 'node:fs/promises';
import path from 'node:path';

const chrome = process.env.PQM_CHROME_EXE;
const reportId = process.env.PQM_REPORT_ID;
const appUrl = process.env.PQM_APP_URL || 'http://127.0.0.1:8080';
if (!chrome || !reportId) throw new Error('PQM_CHROME_EXE and PQM_REPORT_ID are required');

const root = process.cwd();
const output = path.join(root, 'output', 'browser-acceptance', 'browser-download');
const profile = path.join(root, 'output', 'browser-acceptance', 'chrome-profile');
await mkdir(output, {recursive: true});
await mkdir(profile, {recursive: true});
for (const name of await readdir(output)) await rm(path.join(output, name), {force: true});

const port = 9227;
const targetUrl = `${appUrl}/?view=requests&report_id=${encodeURIComponent(reportId)}`;
const child = spawn(chrome, [
  '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, targetUrl,
], {stdio: 'ignore'});

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function json(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
  return response.json();
}

let socket;
try {
  let targets = [];
  for (let attempt = 0; attempt < 80; attempt++) {
    try { targets = await json(`http://127.0.0.1:${port}/json/list`); if (targets.length) break; } catch {}
    await sleep(100);
  }
  const target = targets.find(item => item.type === 'page');
  if (!target) throw new Error('Chrome page target was not created');
  socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  let sequence = 0;
  const pending = new Map(), events = [];
  socket.onmessage = event => {
    const message = JSON.parse(event.data);
    if (message.id) {
      const entry = pending.get(message.id); pending.delete(message.id);
      if (message.error) entry.reject(new Error(message.error.message)); else entry.resolve(message.result);
    } else events.push(message);
  };
  const send = (method, params={}) => new Promise((resolve, reject) => {
    const id = ++sequence; pending.set(id, {resolve, reject});
    socket.send(JSON.stringify({id, method, params}));
  });
  await send('Network.enable');
  await send('Runtime.enable');
  await send('Page.enable');
  await send('Page.setDownloadBehavior', {behavior: 'allow', downloadPath: output});

  let found = false;
  for (let attempt = 0; attempt < 120; attempt++) {
    const result = await send('Runtime.evaluate', {
      expression: `Boolean(document.querySelector('[data-download-protocol-pdf]'))`,
      returnByValue: true,
    });
    if (result.result.value) { found = true; break; }
    await sleep(100);
  }
  if (!found) throw new Error('Actual PDF button did not appear in violation-report card');
  const layoutResult = await send('Runtime.evaluate', {
    expression: `JSON.stringify({
      actions:[...document.querySelectorAll('.violation-protocol-actions>*')].map(node=>({
        text:node.textContent.trim(),tag:node.tagName,height:Math.round(node.getBoundingClientRect().height)
      })),
      fields:[...document.querySelectorAll('.violation-protocol-main>.request-form-grid input')].map(node=>Math.round(node.getBoundingClientRect().width)),
      metadataWidth:Math.round(document.querySelector('.violation-protocol-metadata')?.getBoundingClientRect().width||0),
      containerWidth:Math.round(document.querySelector('.violation-protocol-controls')?.getBoundingClientRect().width||0)
    })`,
    returnByValue: true,
  });
  const layout = JSON.parse(layoutResult.result.value);
  await send('Runtime.evaluate', {
    expression: `document.querySelector('[data-download-protocol-pdf]').click()`,
    returnByValue: true,
  });

  let files = [];
  for (let attempt = 0; attempt < 200; attempt++) {
    files = (await readdir(output)).filter(name => !name.endsWith('.crdownload'));
    if (files.length) break;
    await sleep(100);
  }
  if (!files.length) throw new Error('Browser click did not produce a downloaded file');
  const pdfName = files[0], bytes = await readFile(path.join(output, pdfName));
  const response = events.find(event => event.method === 'Network.responseReceived'
    && String(event.params.response.url).endsWith('/protocol/pdf'))?.params.response;
  const exceptions = events.filter(event => event.method === 'Runtime.exceptionThrown');
  console.log(JSON.stringify({
    targetUrl, layout, buttonClicked: true, httpStatus: response?.status,
    mimeType: response?.mimeType, contentType: response?.headers?.['Content-Type'],
    contentDisposition: response?.headers?.['Content-Disposition'],
    downloadedFilename: pdfName, size: bytes.length,
    pdfSignature: bytes.subarray(0, 5).toString('ascii'),
    runtimeExceptions: exceptions.length,
  }, null, 2));
} finally {
  if (socket?.readyState === WebSocket.OPEN) socket.close();
  child.kill();
}
