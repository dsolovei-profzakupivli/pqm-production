"""Real existing Node adapter, a fake EDS response and the real Sandbox guard."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import sandbox_runtime as policy
import sandbox_eds as eds
NODE=os.environ.get('PQM_NODE_BINARY') or shutil.which('node')
if not NODE:
    NODE=str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe')
if not Path(NODE).is_file():raise RuntimeError('Node missing for mandatory EDS test')
package=ROOT/'tools/prozorro_eds_adapter/node_modules/@prozorro/prozorro-eds/package.json'
if not package.is_file() or json.loads(package.read_text())['version']!='1.1.2':
    raise RuntimeError('The locked official EDS 1.1.2 package is required')
calls=[]
active=[0];peak=[0];lock=threading.Lock()
@contextmanager
def fake_response(request,timeout):
    assert request.full_url==eds.ENDPOINT
    data=json.loads(request.data);assert set(data)=={'sign_url'};calls.append(data['sign_url'])
    class Response:
        status=200
        def read(self,limit):
            return json.dumps({'data':{'signers':[{'pszSubjCN':'SYNTHETIC SIGNER',
                'pszSubjDRFOCode':'1234567890','pszIssuerCN':'SYNTHETIC'}]}}).encode()
    with lock:active[0]+=1;peak[0]=max(peak[0],active[0])
    try:
        time.sleep(.2)
        yield Response()
    finally:
        with lock:active[0]-=1

with tempfile.TemporaryDirectory(prefix='pqm-eds-roundtrip-') as folder:
    env={**policy.POLICY,'PQM_SANDBOX_LOCAL_FIXTURE':'1','PQM_DATA_DIR':folder,
         'PQM_DB_PATH':str(Path(folder)/'pqm_sandbox.sqlite3')}
    if os.name=='nt':env['SystemRoot']=os.environ.get('SystemRoot','C:/Windows')
    with patch.dict(os.environ,env,clear=True),patch.object(policy,'_original_getaddrinfo',
            return_value=[(2,1,6,'',('8.8.8.8',443))]),patch.object(eds,'verification_open',fake_response):
        policy.install_outbound_guard()
        def verify(kind):
            result=eds.run_adapter(NODE,eds.ADAPTER,'https://documents.prozorro.gov.ua/synthetic/'+kind+'.p7s',4)
            data=json.loads(result.stdout)
            if result.returncode or data.get('status')!='success':
                raise AssertionError('Official EDS roundtrip failed: '+str(data.get('status')))
            assert data['signers'][0]['subjectDRFOCode']=='1234567890'
            assert not getattr(eds._launch,'expected',None)
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(verify,['sign','mvs','other-officer']))
        assert len(calls)==3 and peak[0]==2 and active[0]==0
        assert eds._SLOTS._value==2
        assert not [t for t in threading.enumerate() if t.name=='pqm-eds-bridge']
print('Official EDS adapter + Sandbox guard: 3 roundtrips PASS; live/external writes=0')
