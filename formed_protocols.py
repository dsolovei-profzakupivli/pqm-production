"""Versioned generated documents. Legacy markers never reconstruct membership."""
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

def stamp():
    return datetime.now(timezone.utc).isoformat()

def migrate(con):
    con.executescript('''
    CREATE TABLE IF NOT EXISTS formed_protocols (
      id TEXT PRIMARY KEY, protocol_number TEXT NOT NULL, protocol_date TEXT NOT NULL,
      officer TEXT NOT NULL, series_key TEXT NOT NULL, version INTEGER NOT NULL,
      status TEXT NOT NULL CHECK(status IN ('active','cancelled','superseded')),
      created_at TEXT NOT NULL, created_by TEXT NOT NULL,
      cancelled_at TEXT, cancelled_by TEXT, reason TEXT,
      document_path TEXT NOT NULL, document_sha256 TEXT NOT NULL,
      count_all INTEGER NOT NULL, count_admitted INTEGER NOT NULL, count_rejected INTEGER NOT NULL,
      CHECK(count_all=count_admitted+count_rejected), UNIQUE(series_key,version));
    CREATE TABLE IF NOT EXISTS formed_protocol_members (
      protocol_id TEXT NOT NULL REFERENCES formed_protocols(id),
      submission_id TEXT NOT NULL REFERENCES submissions(id),
      position INTEGER NOT NULL, snapshot_json TEXT NOT NULL,
      active INTEGER NOT NULL CHECK(active IN (0,1)),
      PRIMARY KEY(protocol_id,submission_id));
    CREATE UNIQUE INDEX IF NOT EXISTS formed_protocol_active_submission
      ON formed_protocol_members(submission_id) WHERE active=1;
    CREATE UNIQUE INDEX IF NOT EXISTS formed_protocol_active_series
      ON formed_protocols(series_key) WHERE status='active';
    ''')

def active(con, sid):
    row=con.execute('''SELECT p.* FROM formed_protocol_members m JOIN formed_protocols p ON p.id=m.protocol_id
      WHERE m.submission_id=? AND m.active=1 AND p.status='active' ''',(sid,)).fetchone()
    return dict(row) if row else None

def pending(con,sid):
    row=con.execute('''SELECT COALESCE(q.status,'pending') status FROM submissions s
      LEFT JOIN qualifications q ON q.id=s.qualification_id WHERE s.id=?''',(sid,)).fetchone()
    if not row or row['status']!='pending':
        raise ValueError(f'Заявка {sid}: операція дозволена лише у статусі «Очікує рішення»')

def legacy(con,sid):
    row=con.execute('''SELECT generated_protocol_number,generated_protocol_date,
      generated_protocol_decision,protocol_generated_at FROM application_fields WHERE submission_id=?''',(sid,)).fetchone()
    return dict(row) if row and any(row) and not active(con,sid) else None

def available(con,sid):
    pending(con,sid)
    current=active(con,sid)
    if current:
        raise ValueError(f'Заявка {sid} вже включена до протоколу № {current["protocol_number"]} ({current["id"]}). Спочатку скасуйте формування.')
    if legacy(con,sid):
        raise ValueError(f'Заявка {sid}: Legacy — сформований раніше. Спочатку підтвердьте скасування старої позначки.')

def audit(con,sid,user,field,old,new):
    con.execute('''INSERT INTO audit_log(submission_id,changed_at,changed_by,field_name,old_value,new_value)
      VALUES (?,?,?,?,?,?)''',(sid,stamp(),user,field,old,new))

def clear_markers(con,sid):
    con.execute("""UPDATE application_fields SET generated_protocol_number='',generated_protocol_date='',
      generated_protocol_decision='',protocol_generated_at='' WHERE submission_id=?""",(sid,))

def release_legacy(con,sid,user,confirmed,reason):
    if confirmed is not True or not str(reason).strip():
        raise ValueError('Потрібне явне підтвердження і причина скасування legacy-позначки')
    pending(con,sid)
    if active(con,sid): raise ValueError('Ця заявка має новий сформований протокол. Скасуйте його через модалку протоколу.')
    old=legacy(con,sid)
    if not old: raise ValueError('Legacy-позначки немає або її вже скасовано')
    audit(con,sid,user,'legacy_protocol_cancelled',json.dumps(old,ensure_ascii=False),str(reason))
    clear_markers(con,sid)
    return {'cancelled':True,'submission_id':sid}

def document_info(record, directory=None):
    relative=record.pop('document_path')
    record['filename']=Path(relative).name
    target=(Path(directory)/relative).resolve() if directory is not None else None
    record['document_available']=bool(target and target.is_relative_to(Path(directory).resolve()) and target.is_file())
    record['download_url']='/api/protocol/formed/'+quote(record['id'])+'/download' if record['document_available'] else None
    return record

def detail(con,pid,directory=None):
    row=con.execute('SELECT * FROM formed_protocols WHERE id=?',(pid,)).fetchone()
    if not row: raise ValueError('Сформований протокол не знайдено')
    out=dict(row)
    out['items']=[json.loads(r[0]) for r in con.execute('SELECT snapshot_json FROM formed_protocol_members WHERE protocol_id=? ORDER BY position',(pid,))]
    document_info(out,directory)
    # Connected formations through actual immutable membership, never number/date or audit.
    records=con.execute('''WITH RECURSIVE linked(id) AS (
      SELECT id FROM formed_protocols WHERE id=?
      UNION
      SELECT b.protocol_id FROM linked l
        JOIN formed_protocol_members a ON a.protocol_id=l.id
        JOIN formed_protocol_members b ON b.submission_id=a.submission_id
    ) SELECT p.* FROM formed_protocols p JOIN linked l ON l.id=p.id ORDER BY p.created_at,p.id''',(pid,)).fetchall()
    out['history']=[]
    for row in records:
        entry=document_info(dict(row),directory)
        entry['items']=[json.loads(r[0]) for r in con.execute(
          'SELECT snapshot_json FROM formed_protocol_members WHERE protocol_id=? ORDER BY position',(entry['id'],))]
        out['history'].append(entry)
    return out

def cancel(con,pid,user,confirmed,reason):
    if confirmed is not True or not str(reason).strip(): raise ValueError('Потрібне явне підтвердження і причина скасування')
    record=detail(con,pid)
    if record['status']!='active': raise ValueError('Формування вже скасовано')
    for item in record['items']: pending(con,item['id'])
    con.execute("UPDATE formed_protocols SET status='cancelled',cancelled_at=?,cancelled_by=?,reason=? WHERE id=?",(stamp(),user,str(reason),pid))
    con.execute('UPDATE formed_protocol_members SET active=0 WHERE protocol_id=?',(pid,))
    for item in record['items']:
        clear_markers(con,item['id'])
        audit(con,item['id'],user,'formed_protocol_cancelled',pid,str(reason))
    return {'cancelled':True,'protocol_id':pid,'total':len(record['items'])}

PROTECTED={'protocol_number','protocol_date','protocol_officer','protocol_decision','protocol_remarks',
           'manager_name','compliance_status','compliance_comments','document_package'}

def guard_edit(con,sid,payload):
    row=con.execute('SELECT * FROM application_fields WHERE submission_id=?',(sid,)).fetchone()
    if not row or not any(k in payload and str(payload[k] or '')!=str(row[k] or '') for k in PROTECTED): return
    if active(con,sid) or legacy(con,sid):
        raise ValueError('Спочатку скасуйте формування протоколу / legacy-позначку. Реквізити та рішення не змінено.')

def create(con,items,document_payload,directory,builder,user):
    """Caller holds BEGIN IMMEDIATE from validation until successful commit."""
    ids=[x['id'] for x in items]
    if not ids or len(ids)!=len(set(ids)): raise ValueError('Потрібен непорожній склад без дублікатів')
    for sid in ids: available(con,sid)
    # Never allow a concurrent PATCH between readiness and the locked snapshot.
    for item in items:
        row=con.execute('SELECT * FROM application_fields WHERE submission_id=?',(item['id'],)).fetchone()
        if not row or any(str(row[k] or '')!=str(item.get(k) or '') for k in PROTECTED):
            raise ValueError('Дані заявки змінилися. Повторіть перевірку готовності протоколу.')
    number=document_payload['protocol_number'];date=document_payload['protocol_date'];officer=document_payload['officer']
    try:
        parsed=datetime.strptime(date,'%Y-%m-%d') if re.fullmatch(r'\d{4}-\d{2}-\d{2}',date) else datetime.strptime(date,'%d.%m.%Y')
    except (ValueError,TypeError): raise ValueError('Некоректна дата протоколу: використайте dd.mm.yyyy або yyyy-mm-dd')
    display_date=parsed.strftime('%d.%m.%Y')
    key=json.dumps([number,display_date,officer],ensure_ascii=False)
    if con.execute("SELECT 1 FROM formed_protocols WHERE series_key=? AND status='active'",(key,)).fetchone():
        raise ValueError('Протокол із цими реквізитами вже активний. Спочатку скасуйте його формування.')
    version=con.execute('SELECT COALESCE(MAX(version),0)+1 FROM formed_protocols WHERE series_key=?',(key,)).fetchone()[0]
    pid=uuid.uuid4().hex
    safe=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',str(number)).strip(' .') or 'protocol'
    filename=f'Протокол № {safe} від {display_date}.docx'
    relative=Path('_formed')/pid/filename
    output=Path(directory)/relative
    builder(document_payload,output)  # No records/markers on generator failure.
    if not output.is_file() or not output.stat().st_size: raise ValueError('DOCX не створено')
    with output.open('rb') as stream: digest=hashlib.file_digest(stream,'sha256').hexdigest()
    created=stamp();admitted=sum(x['protocol_decision']=='admit' for x in items);rejected=sum(x['protocol_decision']=='reject' for x in items)
    con.execute('''INSERT INTO formed_protocols(id,protocol_number,protocol_date,officer,series_key,version,status,
      created_at,created_by,document_path,document_sha256,count_all,count_admitted,count_rejected)
      VALUES (?,?,?,?,?,?,'active',?,?,?,?,?,?,?)''',(pid,number,date,officer,key,version,created,user,str(relative),digest,len(items),admitted,rejected))
    for position,item in enumerate(items):
        con.execute('INSERT INTO formed_protocol_members VALUES (?,?,?,?,1)',(pid,item['id'],position,json.dumps(item,ensure_ascii=False)))
        con.execute('''UPDATE application_fields SET generated_protocol_number=?,generated_protocol_date=?,
          generated_protocol_decision=protocol_decision,protocol_generated_at=? WHERE submission_id=?''',(number,date,created,item['id']))
        audit(con,item['id'],user,'formed_protocol_created','',pid)
    return {'generated':True,'protocol_id':pid,'protocol_number':number,'protocol_date':date,'total':len(items),
            'admitted':admitted,'rejected':rejected,'filename':filename,'download_url':'/api/protocol/formed/'+pid+'/download'}

def enrich(con,items):
    if not items: return
    marks=','.join('?' for _ in items)
    records={r['submission_id']:dict(r) for r in con.execute(f'''SELECT m.submission_id,p.id,p.protocol_number
      FROM formed_protocol_members m JOIN formed_protocols p ON p.id=m.protocol_id
      WHERE m.active=1 AND p.status='active' AND m.submission_id IN ({marks})''',[r['id'] for r in items])}
    for item in items:
        item['formed_protocol_id']=records.get(item['id'],{}).get('id')
        item['legacy_protocol']=not item['formed_protocol_id'] and bool(item.get('protocol_generated_at') or item.get('generated_protocol_number') or item.get('generated_protocol_date') or item.get('generated_protocol_decision'))
