"""Synthetic transport fixture. No production DB or external API access."""
import os,sys,time,sqlite3
from datetime import datetime,timedelta,timezone
from urllib.parse import urlsplit
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import sandbox_runtime as sandbox
data,db,service=sandbox.validate_environment()
assert service=='local-synthetic-fixture' and os.environ.get('PQM_SANDBOX_LOCAL_FIXTURE')=='1'
sandbox.install_outbound_guard()
import server
sandbox.bootstrap(server)
# Keep full-sync discovery deterministic in both networkless CI and Render:
# exercise the real directory/list/detail path with synthetic inputs only.
server.load_announcement_rows=lambda: [{'ID':'SANDBOX-TEST-ONLY','status':'активне'}]
def transport(url):
    sandbox.validate_prozorro_url(url)
    path=urlsplit(url).path
    time.sleep(.15)
    if path=='/api/2.5/frameworks':
        return {'data':[{'id':'sandbox-framework'}]}
    if path=='/api/2.5/frameworks/sandbox-framework':
        return {'data':{'id':'sandbox-framework','prettyID':'SANDBOX-TEST-ONLY','status':'active',
            'procuringEntity':{'identifier':{'id':'40996564'}},'classification':{'id':'00000000-0'},
            'agreementID':'sandbox-agreement'}}
    if path=='/api/2.5/frameworks/sandbox-framework/submissions':
        return {'data':[{'id':'sandbox-pending','qualificationID':'sandbox-q-pending','status':'active',
            'datePublished':'2026-09-16T10:00:00+03:00','tenderers':[{'name':'SYNTHETIC UPDATED','identifier':{'id':'00000000'}}]}]}
    if path=='/api/2.5/frameworks/sandbox-framework/qualifications':
        return {'data':[{'id':'sandbox-q-pending','submissionID':'sandbox-pending','status':'active'}]}
    if path=='/api/2.5/agreements/sandbox-agreement/contracts':
        return {'data':[]}
    raise RuntimeError('Unexpected synthetic API URL: '+path)
sandbox.fetch_prozorro_json=transport
if sandbox.prozorro_scheduler_enabled():
    with sqlite3.connect(db) as con:
        con.execute("UPDATE frameworks SET status='active' WHERE id='sandbox-framework'")
    # Accelerated clock is confined to this synthetic fixture, never runtime.
    server.next_hourly_run=lambda moment=None: datetime.now(timezone.utc)+timedelta(seconds=25)
server.main()
