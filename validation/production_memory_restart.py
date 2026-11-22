"""Crash/re-admission probe, actual worker and SQLite, synthetic external results."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]

def child(folder, phase):
    os.environ.update(PQM_ENV='local',PQM_SANDBOX='0',PQM_DATA_DIR=str(folder),
                      PQM_DB_PATH=str(folder/'synthetic.sqlite3'),PQM_RELEASE_SCHEMA_ONLY='1',
                      PQM_AUTH_ENABLED='0',PQM_USERS_JSON='',PQM_ENABLE_SCHEDULER='0',
                      PQM_ENABLE_GOOGLE='0',PQM_BIDS_MODE='disabled')
    sys.path.insert(0,str(ROOT))
    import server
    server.init_db();server.init_reference_tables(server.DB_PATH)
    if phase=='crash':
        with server.db() as con:
            con.execute("INSERT INTO frameworks(id,pretty_id,status,dk_code,raw_json,synced_at) VALUES('f','SYNTHETIC','active','44530000-4','{}','fixture')")
            for n in range(4):
                con.execute("INSERT INTO submissions(id,framework_id,supplier_code,supplier_name,date_published,raw_json,synced_at) VALUES(?,'f',?,'SYNTHETIC','2026-11-20T00:00:00Z','{}','fixture')",('s'+str(n),f'{n:08d}'))
                con.execute('INSERT INTO application_fields(submission_id) VALUES(?)',('s'+str(n),))
    calls=[]
    def search(code,cpv,stamp,sid):
        calls.append(sid)
        if phase=='crash' and sid=='s1':
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                with server.db() as con:
                    raw=con.execute("SELECT document_check_result_json FROM application_fields WHERE submission_id='s0'").fetchone()[0]
                if raw:os._exit(91)
                time.sleep(.005)
            raise AssertionError('First saved result was not committed')
        return {'status':'none','symbol':'−','message':'Synthetic','candidates':[]}
    server.search_supplier_contract_experience=search
    if phase=='resume':
        with server.db() as con:
            before=con.execute("SELECT document_check_result_json FROM application_fields WHERE submission_id='s0'").fetchone()[0]
    server.enqueue_contract_experience_search(['s0','s1','s2','s3'])
    deadline=time.monotonic()+10
    while server.CONTRACT_EXPERIENCE_QUEUE.snapshot()['owned']:
        if time.monotonic()>deadline:raise AssertionError('Restart queue did not drain')
        time.sleep(.005)
    server.CONTRACT_EXPERIENCE_QUEUE.close();server.CONTRACT_EXPERIENCE_EXECUTOR.shutdown(wait=True)
    if phase=='resume':
        with server.db() as con:
            after=con.execute("SELECT document_check_result_json FROM application_fields WHERE submission_id='s0'").fetchone()[0]
            assert before==after
            assert con.execute("SELECT COUNT(*) FROM application_fields WHERE document_check_result_json<>''").fetchone()[0]==4
            assert con.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert 's0' not in calls
        print(json.dumps({'crash_exit':91,'saved_result_unchanged':True,'resume_calls':calls,'rows':4,'integrity':'ok',
                          'scope':'Explicit re-admission by the existing ingestion path; no durable queue or new startup scan'}))

if __name__=='__main__':
    if len(sys.argv)>1:
        child(Path(sys.argv[1]),sys.argv[2])
    else:
        with tempfile.TemporaryDirectory(prefix='pqm-production-crash-') as folder:
            env=dict(os.environ,PYTHONPATH=str(ROOT/'validation/test_runtime'),PQM_TEST_NETWORK_ISOLATION='1')
            first=subprocess.run([sys.executable,'-B',__file__,folder,'crash'],env=env,capture_output=True,text=True,timeout=30)
            if first.returncode!=91:raise AssertionError((first.returncode,first.stdout,first.stderr))
            second=subprocess.run([sys.executable,'-B',__file__,folder,'resume'],env=env,capture_output=True,text=True,timeout=30)
            if second.returncode:raise AssertionError((second.returncode,second.stdout,second.stderr))
            print(second.stdout)
