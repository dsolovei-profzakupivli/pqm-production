"""Disposable browser acceptance environment. Never points at WEB business DB."""
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
import web_smoke as web

web.fixture()
subprocess.run([sys.executable,str(web.ROOT/'deploy_release.py'),'--db',str(web.server.DB_PATH),'--apply-navigation'],check=True)
port=int(os.environ.get('PQM_FIXTURE_PORT','8088'))
print(json.dumps({'fixture_only':True,'port':port,'username':'fixture-admin','password':web.PASSWORD}),flush=True)
web.server.ThreadingHTTPServer(('0.0.0.0',port),web.server.Handler).serve_forever()
