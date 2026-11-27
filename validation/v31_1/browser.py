"""Real Chromium, existing EDR modal/components and authenticated local HTTP API.

Only unrelated application startup is omitted; component code is read verbatim
from app.js. No external transport, working DB, scheduler or Google client.
"""
import json
import gc
import os
from pathlib import Path
import subprocess
import shutil
import threading
from unittest.mock import patch
from fixtures import server,reset,supplier,row,snapshot,auth,DATA,ROOT
import sandbox_runtime

con=reset()
for code in ('2884318089','31587803','СР 918414'):
    supplier(con,code,active=code!='2884318089',checked='' if code=='31587803' else '2026-09-02')
con.commit();before='\n'.join(con.iterdump())
source=snapshot(row('2884318089',status='Неактуально',checked='2026-09-02'),
    row('31587803'),row('СР 918414',status='Немає інформації'))
app=(ROOT/'app.js').read_text(encoding='utf-8')
component=app[app.index('let supplierEdrTimer=null'):app.index('function edrMonitoringParams()')]
component+=app[app.index('function supplierEdrDatesHtml('):app.index('function nazkRegistrySourceNotice(')]
prefix="""const $=s=>document.querySelector(s),API='/api';
function esc(x){return String(x??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]))}
function displayDateOnly(x){let t=String(x||'').slice(0,10);return /^\\d{4}-\\d{2}-\\d{2}$/.test(t)?t.split('-').reverse().join('.'):t}
async function request(path,options){const r=await fetch(path,options);const d=await r.json();if(!r.ok)throw new Error(d.error);return d}
function toast(message){throw new Error(message)}
function displayDate(value){return String(value||'')}
"""
component=prefix+component+"\nloadSupplierEdrStatus=async()=>({});"
base=Path(os.environ['PQM_V311_TEMP']);(base/'component.js').write_text(component,encoding='utf-8')
output=Path(os.environ.get('PQM_V311_EVIDENCE') or Path(os.environ['PQM_V311_SOURCE_ROOT'])/'evidence')
env={**os.environ,'PQM_V311_COMPONENT':str(base/'component.js'),'PQM_V311_OUTPUT':str(output),
     'PQM_V311_AUTH':auth()}
try:
    with patch.dict(os.environ,{**sandbox_runtime.POLICY,'PQM_SANDBOX_LOCAL_FIXTURE':'1',
            'RENDER_SERVICE_ID':'','RENDER_SERVICE_NAME':''}), \
        patch.object(server,'SANDBOX_MODE',True),patch.object(server,'SAFE_MODE',True), \
        patch.object(server,'sandbox_runtime',sandbox_runtime,create=True), \
        patch.object(sandbox_runtime,'attest_internal_target',return_value=server.DB_PATH), \
        patch.object(server,'supplier_edr_source_snapshot',return_value=source):
        http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        threading.Thread(target=http.serve_forever,daemon=True).start()
        env['PQM_V311_URL']='http://127.0.0.1:'+str(http.server_address[1])
        try:
            result=subprocess.run([os.environ.get('PQM_NODE',
                shutil.which('node') or ('C:/Users/User/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe' if os.name=='nt' else 'node')),
                'validation/v31_1/browser.cjs'],env=env,cwd=ROOT)
            if result.returncode:raise SystemExit(result.returncode)
        finally:http.shutdown();http.server_close()
    assert before=='\n'.join(con.iterdump()),'Browser Preview/XLSX changed business data'
    print('BROWSER DB: exact read-only PASS')
finally:con.close();gc.collect();DATA.cleanup()
