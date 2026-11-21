import assert from 'node:assert/strict';
import net from 'node:net';
import tls from 'node:tls';
import dns from 'node:dns';
import dgram from 'node:dgram';
import childProcess from 'node:child_process';
process.env.PQM_EDS_BRIDGE_URL='http://127.0.0.1:9/verify';
process.env.PQM_EDS_BRIDGE_TOKEN='synthetic-only';
await import('../tools/prozorro_eds_adapter/sandbox-transport.mjs');
let checks=0;
for(const operation of [()=>new net.Socket().connect({host:'8.8.8.8',port:443}),
  ()=>tls.connect({host:'example.test',port:443}),()=>dns.lookup('example.test'),
  ()=>dns.resolve4('example.test'),()=>dns.promises.resolve4('example.test'),
  ()=>dgram.createSocket('udp4'),()=>childProcess.spawn('arbitrary'),
  ()=>new net.Server().listen(9999)]){
  assert.throws(operation,/denied/);checks++;
}
await assert.rejects(fetch('https://other.invalid/anything'),/denied/);checks++;
await assert.rejects(fetch('https://api-sign.prozorro.gov.ua/verify_data_internal',{method:'DELETE'}),/denied/);checks++;
console.log(`Sandbox EDS child confinement: ${checks} scenarios PASS`);
