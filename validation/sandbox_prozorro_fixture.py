"""Synthetic transport fixture. No production DB or external API access."""
import os,sys,time
from urllib.parse import urlsplit
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import sandbox_runtime as sandbox
data,db,service=sandbox.validate_environment()
assert service=='local-synthetic-fixture' and os.environ.get('PQM_SANDBOX_LOCAL_FIXTURE')=='1'
sandbox.install_outbound_guard()
import server
sandbox.bootstrap(server)
def transport(url):
    sandbox.validate_prozorro_url(url)
    url=urlsplit(url).path
    time.sleep(.15)
    if url.endswith('/frameworks/sandbox-framework'):
        return {'data':{'id':'sandbox-framework','prettyID':'SANDBOX-TEST-ONLY','status':'active',
            'procuringEntity':{'identifier':{'id':'40996564'}},'classification':{'id':'00000000-0'}}}
    if url.endswith('/submissions'):
        return {'data':[{'id':'sandbox-pending','qualificationID':'sandbox-q-pending','status':'active',
            'datePublished':'2026-09-16T10:00:00+03:00','tenderers':[{'name':'SYNTHETIC UPDATED','identifier':{'id':'00000000'}}]}]}
    if url.endswith('/qualifications'):
        return {'data':[{'id':'sandbox-q-pending','submissionID':'sandbox-pending','status':'active'}]}
    raise RuntimeError('Unexpected synthetic API URL: '+url)
sandbox.fetch_prozorro_json=transport
server.main()
