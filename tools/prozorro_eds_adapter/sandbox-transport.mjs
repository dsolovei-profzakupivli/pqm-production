/* Network confinement for the existing adapter. No changes to signature verification. */
import net from 'node:net';
import tls from 'node:tls';
import dns from 'node:dns';
import dgram from 'node:dgram';
import childProcess from 'node:child_process';
import {syncBuiltinESMExports} from 'node:module';

const endpoint = 'https://api-sign.prozorro.gov.ua/verify_data_internal';
const bridge = new URL(process.env.PQM_EDS_BRIDGE_URL || '');
const token = process.env.PQM_EDS_BRIDGE_TOKEN;
if (bridge.hostname !== '127.0.0.1' || bridge.protocol !== 'http:' || bridge.pathname !== '/verify' || !token) {
  throw new Error('Invalid Sandbox EDS bridge');
}
const deny = () => {throw new Error('Sandbox EDS outbound operation denied');};
const originalConnect = net.Socket.prototype.connect;
net.Socket.prototype.connect = function (...args) {
  // net.normalizeArgs wraps options in an array for internal undici connections.
  const values = Array.isArray(args[0]) ? args[0] : args;
  const options = typeof values[0] === 'object' ? values[0] : {port:values[0],host:values[1]};
  if (options.path || options.host !== '127.0.0.1' || Number(options.port) !== Number(bridge.port)) deny();
  return originalConnect.apply(this, args);
};
tls.connect = deny;
for (const object of [dns, dns.promises]) {
  for (const name of Object.keys(object)) {
    if (/^(lookup|resolve|reverse)/.test(name)) object[name] = deny;
  }
  object.Resolver = deny;
}
net.Server.prototype.listen = deny;
dgram.createSocket = deny;
for (const key of ['exec','execFile','fork','spawn','execSync','execFileSync','spawnSync']) childProcess[key] = deny;
syncBuiltinESMExports();
const nativeFetch = globalThis.fetch;
globalThis.fetch = async (input, init) => {
  const request = new Request(input, init);
  if (request.url !== endpoint || request.method !== 'POST') deny();
  const body = await request.text();
  if (Buffer.byteLength(body) > 16384) deny();
  return nativeFetch(bridge.href, {method:'POST', body, redirect:'error', signal:request.signal,
    headers:{'Content-Type':'application/json','X-PQM-EDS-Bridge':token,
      'X-PQM-EDS-Authorization':request.headers.get('authorization') || ''}});
};
