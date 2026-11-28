"""Synthetic native SQLite only, no app startup, schedules or network clients."""
import base64
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
DATA=tempfile.TemporaryDirectory(prefix='pqm-v311-data-',dir=os.environ['PQM_V311_TEMP'])
os.environ.update(PQM_ENV='test_web',PQM_SANDBOX='0',PQM_DATA_DIR=DATA.name,
    PQM_DB_PATH=str(Path(DATA.name)/'pqm_sandbox.sqlite3'),PQM_USERS_JSON='',PQM_AUTH_ENABLED='1',
    PQM_RELEASE_SCHEMA_ONLY='1',PQM_ENABLE_GOOGLE='0',PQM_ENABLE_SCHEDULER='0',
    PQM_ENABLE_PROZORRO_SCHEDULER='0',PQM_ENABLE_NAZK_SCHEDULER='0',
    PQM_ENABLE_VIOLATION_SCHEDULER='0',PQM_ENABLE_BIDS_UPDATE='0',PQM_ENABLE_BROWSER='0',
    PQM_DISABLE_BACKGROUND_JOBS='1',PQM_SANDBOX_EVIDENCE_V3_SHADOW='0')
socket.getfqdn=lambda name='':name or 'localhost'
_connect=socket.socket.connect
def connect(sock,address):
    if not isinstance(address,tuple) or address[0] not in {'localhost','127.0.0.1','::1'}:
        raise AssertionError('External network blocked in V31.1 tests')
    return _connect(sock,address)
socket.socket.connect=connect
import server
import edr_sync_v2 as sync

PASSWORD='Synthetic-V311-only!'

def database():
    server.init_db();server.init_reference_tables(server.DB_PATH)
    from migrations.additive import migrate
    migrate(server.DB_PATH,json.loads((ROOT/'migrations/target_schema.json').read_text()),Path(DATA.name)/'backups')
    return server.db()

def reset():
    con=database()
    for table in ['submission_nazk_controls','supplier_edr_verification_events','supplier_google_receipts','supplier_managers',
                  'supplier_edr_profiles','registry_contracts','qualifications','application_fields',
                  'submissions','framework_officers','frameworks','auth_users','authorized_officers']:
        con.execute('DELETE FROM '+table)
    con.execute("INSERT INTO authorized_officers(id,full_name,role,active,created_at,updated_at) VALUES(1,'Тестова УО SANDBOX','УО',1,'fixture','fixture')")
    con.execute("INSERT INTO auth_users(username,password_hash,role,officer_id,active,created_at,updated_at,created_by) VALUES(?,?,'admin',NULL,1,'fixture','fixture','fixture')",('fixture',server.hash_password(PASSWORD)))
    con.execute("INSERT INTO auth_users(username,password_hash,role,officer_id,active,created_at,updated_at,created_by) VALUES(?,?,'officer',1,1,'fixture','fixture','fixture')",('sandbox.officer',server.hash_password(PASSWORD)))
    con.execute('CREATE TABLE IF NOT EXISTS sandbox_deployment_identity(environment TEXT,service_id TEXT,created_at TEXT)')
    con.execute('DELETE FROM sandbox_deployment_identity')
    con.execute("INSERT INTO sandbox_deployment_identity VALUES('sandbox','local-synthetic-fixture','fixture')")
    con.execute('UPDATE scheduler_job_settings SET enabled=0')
    con.execute('UPDATE runtime_feature_settings SET enabled=0')
    con.commit();return con

def supplier(con,code,*,active=False,profile=True,status='Зареєстровано',checked='2026-09-02T00:00:00+03:00',officer='Тестова УО SANDBOX',name='ПРИКЛАД',manager='',decision=''):
    key='f-'+code
    con.execute("INSERT INTO frameworks(id,pretty_id,title,dk_code,status,raw_json,synced_at) VALUES(?,?,'Синтетичний відбір','44530000-4','active','{}','fixture')",(key,key))
    con.execute("INSERT INTO submissions(id,framework_id,supplier_code,supplier_name,date_published,qualification_id,raw_json,synced_at) VALUES(?,?,?,?,?,?,?,'fixture')",('s-'+code,key,code,name,'2026-10-22T10:00:00+03:00','q-'+code,json.dumps({'tenderers':[{'identifier':{'id':code,'scheme':'UA-EDR'},'address':{'countryName':'Україна'},'legalForm':'legal_entity'}]})))
    con.execute("INSERT INTO qualifications(id,framework_id,submission_id,status,decision_date,raw_json,synced_at) VALUES(?,?,?,'active','2026-10-23T11:00:00+03:00','{}','fixture')",('q-'+code,key,'s-'+code))
    con.execute("INSERT INTO application_fields(submission_id,protocol_decision,manager_name) VALUES(?,?,?)",('s-'+code,decision,manager))
    con.execute("INSERT INTO registry_contracts(id,framework_id,qualification_id,supplier_code,status,milestones_json,raw_json,synced_at) VALUES(?,?,?,?,?,'[]','{}','fixture')",('rc-'+code,key,'q-'+code,code,'active' if active else 'terminated'))
    if profile:
        con.execute("INSERT INTO supplier_edr_profiles(supplier_code,full_name,short_name,manager_name,edr_status,edr_checked_at,edr_officer,source_sheet,source_row,synced_at) VALUES(?,?,?,?,?,?,?,'ЮО',2,'fixture')",(code,name,name,manager,status,checked,officer))

def row(code,*,status='Зареєстровано',checked='2026-11-16T08:50:30+02:00',officer='Тестова УО SANDBOX',name='ПРИКЛАД',manager='',note='',short=None):
    return ['',code,'Найменування з Google C',manager,status,'Активний','','',checked,'','',officer,note,name,name if short is None else short]

def snapshot(*rows):
    return sync.source_snapshot({'ЮО':[list(sync.HEADERS),*rows],'ФОП':[list(sync.HEADERS)]})

def auth():return 'Basic '+base64.b64encode(('fixture:'+PASSWORD).encode()).decode()
